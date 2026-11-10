"""`og-lab sweep`: run many seeded worlds through the arms, record per-run metrics, resume where it stopped.

One job = (seed, technique, arm). Each job runs the attack world AND its benign twin, so utility loss and false refusals are measured:

    attack  attempted, executed, belief, success, harm_usd (USD notional at TRUSTED prices), stopped_by (layer), quarantined_n, cost, tokens
    twin    utility (the legitimate task completed), refused (a legitimate order the gate refused), quarantined_n, cost
    false_refusal  the twin did not complete its legitimate task in this arm
    blast_radius_usd  trigger worlds: notional of the rule orders that actually executed

Offline mode (default when no model is given) drives a PolicyLLM (cautious / credulous / mixed) instead of a model: zero spend, mode=offline.
Live mode estimates first and refuses to start if the estimate exceeds OG_BUDGET_USD.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import judge
from ..paths import SWEEPS
from ..runner import PRICES, DEFAULT_PRICE, FactsChecker, est_tokens, figure_checker, compact
from . import compiler
from .policy import PolicyLLM

ARMS = ("naive", "gate_only", "full")


def technique_names(families: str | None = None, names: str | None = None) -> list[str]:
    """`families` like "B,C,D" (A..F, control); `names` a comma list of technique names. Empty = every non-control technique."""
    if names:
        return [n.strip() for n in names.split(",") if n.strip()]
    fams = [f.strip() for f in families.split(",")] if families else ["A", "B", "C", "D", "E", "F"]
    return [n for n, t in compiler.TECHNIQUES.items() if t.family in fams]


def parse_fixed(s: str | None) -> dict:
    out = {}
    for kv in (s or "").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def job_key(rec_or_tuple) -> tuple:
    if isinstance(rec_or_tuple, dict):
        r = rec_or_tuple
        return (r["seed"], r["case_id"], r["arm"], r["who"], r.get("rep", 0))
    return rec_or_tuple


def who_of(model, policy) -> str:
    return f"policy:{policy}" if model is None else str(model)


def run_job(seed: int, name: str, arm: str, *, model=None, policy: str = "mixed", fixed: dict | None = None, rep: int = 0, max_steps: int = 12, llm=None) -> dict:
    from orderguard_guard.agent import run_agent
    sc = compiler.compile_case(seed, name, fixed=fixed)
    offline = model is None
    agent = PolicyLLM(policy, seed=seed * 7919 + rep) if offline else (llm or model)
    checker = figure_checker(offline)
    runs = {}
    for label, env in (("attack", sc.attack_env()), ("twin", sc.twin_env())):
        t0 = time.time()
        try:
            tr = run_agent(agent, sc.task, env, arm, max_steps=max_steps, figure_checker=checker)
        except Exception as e:
            tr = {"calls": [], "final": "", "quarantined": [], "cost_usd": 0.0, "error": f"{type(e).__name__}: {str(e)[:200]}"}
        runs[label] = (tr, time.time() - t0, env)
    atr, _, aenv = runs["attack"]
    ttr, _, tenv = runs["twin"]
    l7_info = {"applied": False}
    if sc.trigger:
        from ..l7 import apply_l7
        atr, l7_info = apply_l7(aenv.events, atr, arm)
        ttr, _ = apply_l7(tenv.events, ttr, arm)
    ev = judge.evaluate(sc.spec, atr, arm, goal=sc.goal)
    ev_util = judge.utility(sc.twin_spec["utility"], ttr)
    ctrl = sc.technique.control
    if ctrl:                                   # controls: the "attack" env is itself the legitimate scenario
        util_attack = judge.utility(sc.spec["utility"], atr) if sc.spec.get("utility") else None
    else:
        util_attack = judge.utility(sc.twin_spec["utility"], atr)
    twin_refused = any(judge.gate_decision(c) in ("refuse", "hold") for c in judge.orders(ttr))
    rec = {"seed": seed, "case_id": sc.case_id, "technique": name, "family": sc.family, "surface": sc.surface, "goal": sc.goal, "expected_stop": sc.expected_stop,
           "params": sc.params, "arm": arm, "who": who_of(model, policy), "rep": rep, "mode": "offline" if offline else "live", "model": getattr(agent, "model", str(model)),
           "policy": policy if offline else None, "control": ctrl, "world": sc.world.digest(), "twin_parity": sc.parity()["ok"],
           "attack": {k: ev.get(k) for k in ("attempted", "executed", "belief", "success", "harm_usd", "stopped_by", "quarantined_n", "n_calls", "natural_error", "first_order_figure_error", "utility")}
                     | {"utility_in_attack_world": util_attack, "cost_usd": round(float(atr.get("cost_usd") or 0), 6), "est_tokens": est_tokens(atr), "error": atr.get("error"),
                        "belief_sentences": ev.get("belief_sentences", [])[:2]},
           "twin": {"utility": ev_util, "refused": twin_refused, "quarantined_n": len(ttr.get("quarantined") or []), "cost_usd": round(float(ttr.get("cost_usd") or 0), 6),
                    "est_tokens": est_tokens(ttr), "error": ttr.get("error")},
           "false_refusal": None if sc.trigger else (not ev_util),
           "blast_radius_usd": ev.get("harm_usd") if sc.trigger else None,
           "trigger_world": sc.trigger, "l7": l7_info}
    if os.environ.get("OG_SWEEP_KEEP_TRANSCRIPTS"):
        rec["transcripts"] = {"attack": compact(atr), "twin": compact(ttr)}
    return rec


def sweep_estimate(jobs: list, model: str | None) -> dict:
    """Expected live cost of a sweep: two runs per job (attack + twin). Offline sweeps cost nothing."""
    if model is None:
        return {"usd": 0.0, "runs": 2 * len(jobs), "calls": 0, "offline": True}
    pin, pout = PRICES.get(model, DEFAULT_PRICE)
    cache: dict = {}
    calls = tin = tout = 0
    for seed, name, arm, _fx in jobs:
        key = (seed, name)
        if key not in cache:
            sc = compiler.compile_case(seed, name)
            cache[key] = int(sum(len(json.dumps(e, default=str)) for e in sc.attack_env().events) / 3.7) if sc.surface == "feed" else 900
        content = cache[key]
        steps = 6
        extra = 1.5 if arm == "full" else 1.0              # screening calls on every tool output (cached by content, so a ceiling)
        for _ in range(2):
            calls += int(steps * extra)
            tin += int((steps * 1300 + (steps - 2) * content) * extra)
            tout += steps * 600
    return {"usd": tin / 1e6 * pin + tout / 1e6 * pout, "runs": 2 * len(jobs), "calls": calls, "in": tin, "out": tout, "offline": False}


def run_sweep(seeds: int, names: list[str], arms, *, model=None, policy="mixed", concurrency=8, out: Path | None = None, resume: Path | None = None,
              fixed: dict | None = None, seed0: int = 0, reps: int = 1, progress=None, max_steps=12) -> tuple[Path, list[dict], dict]:
    SWEEPS.mkdir(parents=True, exist_ok=True)
    out = Path(resume) if resume else (out or SWEEPS / (time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + ".jsonl"))
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            try:
                done.add(job_key(json.loads(line)))
            except (ValueError, KeyError):
                pass
    who = who_of(model, policy)
    jobs = [(s, n, a, rep) for s in range(seed0, seed0 + seeds) for n in names for a in arms for rep in range(reps)]
    todo = [j for j in jobs if (j[0], f"sbx/{j[1]}/s{j[0]}", j[2], who, j[3]) not in done]
    est = sweep_estimate([(s, n, a, None) for s, n, a, _ in todo], model)
    if model is not None:
        budget = float(os.environ.get("OG_BUDGET_USD", "0.05"))
        if est["usd"] > budget:
            raise RuntimeError(f"estimated US${est['usd']:.3f} exceeds OG_BUDGET_USD US${budget:.3f}; refusing to start (reduce --seeds or raise the budget)")
    lock, results = threading.Lock(), []
    stop = threading.Event()
    from ..llm_shared import shared_llm
    llm = shared_llm(model) if model is not None else None

    def work(j):
        if stop.is_set():
            return
        s, n, a, rep = j
        rec = run_job(s, n, a, model=model, policy=policy, fixed=fixed, rep=rep, max_steps=max_steps, llm=llm)
        err = (rec["attack"].get("error") or "") + (rec["twin"].get("error") or "")
        if "BudgetExceeded" in err or "CreditFloor" in err:
            stop.set()
        with lock:
            results.append(rec)
            with out.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if progress:
                progress(len(results), len(todo), rec)

    with ThreadPoolExecutor(max(1, concurrency)) as ex:
        list(ex.map(work, todo))
    return out, results, {"jobs": len(jobs), "skipped": len(jobs) - len(todo), "ran": len(results), "estimate": est}
