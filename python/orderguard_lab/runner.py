"""Run cases through the guard's agent loop, record one JSON line per run, and estimate cost before spending anything.

A run record keeps the judged fields (attempted, executed, belief, utility, natural errors, stopped_by, harm_usd) AND a compact
transcript, so `og-lab tables` can re-judge every number offline from results/runs/*.jsonl.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import cases as C
from . import judge
from .envs import env_chunks
from .paths import RUNS

ARMS = ("naive", "gate_only", "full")
# US$ per million tokens (input, output). Only models with a price we have been given are listed.
# US$ per million tokens (input, output), OpenRouter list prices checked 2026-11-11. The plain V4.1 Flash id now routes
# at a much higher input price than its dated snapshot "-1017"; live runs from 2026-11-11 use the snapshot.
PRICES = {"deepseek/deepseek-v4.1-flash": (0.30, 1.20), "deepseek/deepseek-v4.1-flash-1017": (0.30, 1.20),
          "liquid/lfm-2.5-24b-a2b": (0.05, 0.70), "anthropic/claude-haiku-5.5": (0.10, 0.50), "qwen/qwen3.7-flash": (0.03, 0.13),
          "z-ai/glm-5.3-flash": (0.04, 0.078)}
DEFAULT_PRICE = PRICES["deepseek/deepseek-v4.1-flash-1017"]   # unknown models are estimated at peak V4.1 Flash price


# ---------------------------------------------------------------------------------------------------- figure checker (L6) for the lab
class FactsChecker:
    """L6 stand-in for every company in data/lab/sec_facts_10co.json: confirmed / contradicted / not_public_yet / unverifiable.
    Used only when orderguard_verify.api is not importable; the real L6 takes over automatically."""

    def __call__(self, ticker, as_of, figures):
        table = judge.truth_table(ticker)
        if ticker.upper() in ("ISRG", "ROK", "TER"):         # rule-driven basket orders carry no filing figures; no fixture coverage exists for them
            return [{"figure": f, "status": "confirmed", "truth": None, "unit": f.get("unit", ""), "source": None, "reason": "not applicable to a rule-driven order"} for f in figures]
        ends = {int(e[:4]): e for e in (judge.facts().get(ticker.upper(), {}).get("revenue") or {})}
        out = []
        for f in figures:
            key = (f.get("metric"), int(judge.num(f.get("fiscal_year"))))
            tv = table.get(key)
            end = ends.get(key[1])
            public = True
            if end:
                public = dt.date.fromisoformat(end) + dt.timedelta(days=45) <= as_of
            if tv is None:
                st, reason = "unverifiable", "no filing figure is on record"
            elif not public:
                st, reason = "not_public_yet", "first published after the decision date"
            else:
                st = {"ok": "confirmed", "wrong": "contradicted"}[judge.figure_status(f, table)]
                reason = "matches the filing" if st == "confirmed" else f"the filing reports {tv:g}"
            out.append({"figure": f, "status": st, "truth": tv, "unit": f.get("unit", ""), "source": None, "reason": reason})
        return out


def figure_checker(offline: bool | None = None):
    """The real L6 (orderguard_verify.api) for live runs; the facts table for offline runs and when it is not importable.
    OG_LAB_L6=verify forces the real one, OG_LAB_L6=facts forces the table (so tests never touch the network)."""
    import os
    force = os.environ.get("OG_LAB_L6")
    if force == "facts" or (offline and force != "verify"):
        return _CheckerMulti()
    try:
        from orderguard_verify.api import check_figures      # type: ignore
        return check_figures
    except Exception:
        return _CheckerMulti()


class _CheckerMulti:
    def __init__(self):
        self.inner = FactsChecker()

    def __call__(self, ticker, as_of, figures):
        return self.inner(ticker, as_of, figures)


# ---------------------------------------------------------------------------------------------------- transcripts
def compact_result(r):
    if isinstance(r, dict):
        keep = {k: r[k] for k in ("status", "ledger_effect", "error", "reason", "reasons", "reference", "quantity", "fill_price", "ticker") if k in r}
        if "text" in r or "events" in r or "results" in r or len(json.dumps(r, default=str)) > 400:
            keep["_head"] = json.dumps(r, ensure_ascii=False, default=str)[:300]
        else:
            keep = dict(r)
        return keep
    return str(r)[:300]


def compact(tr: dict) -> dict:
    return {
        "calls": [{"name": c.get("name"), "args": c.get("args"), "result": compact_result(c.get("result")),
                   "gate": ({"decision": c["gate"].get("decision"), "reasons": c["gate"].get("reasons"), **({"layer": c["gate"]["layer"]} if c["gate"].get("layer") else {}),
                             "checks": {k: v for k, v in (c["gate"].get("checks") or {}).items() if k in ("ticker", "figures", "kind", "mandate", "notional_usd")}}
                            if isinstance(c.get("gate"), dict) else None)} for c in tr.get("calls", [])],
        "final": (tr.get("final") or "")[:2500],
        "quarantined": [{k: q.get(k) for k in ("layer", "tool", "kind", "category", "why")} | {"excerpt": (q.get("excerpt") or "")[:120]} for q in tr.get("quarantined", [])],
        "cost_usd": tr.get("cost_usd", 0.0), "error": tr.get("error"),
        **({"guard_notices": [{k: n.get(k) for k in ("step", "claims", "trusted")} for n in tr["guard_notices"]]} if tr.get("guard_notices") else {}),
    }


def est_tokens(tr: dict) -> int:
    n = len(tr.get("final") or "") + sum(len(json.dumps(c.get("result"), default=str)) + len(json.dumps(c.get("args"), default=str)) for c in tr.get("calls", []))
    return int(n / 3.7)


def judged(case, tr: dict, arm: str) -> dict:
    return case.evaluate(tr, arm)


def run_case(case, model, arm: str, rep: int = 0, *, screen_model=None, max_steps: int = 12, mode: str = "live") -> dict:
    """One run. `model` is a model name or any object with .chat (a ScriptedLLM offline)."""
    from orderguard_guard.agent import run_agent
    if callable(model) and not hasattr(model, "chat"):
        model = model()
    env = case.build_env()
    t0 = time.time()
    try:
        tr = run_agent(model, case.user_task(), env, arm, max_steps=max_steps, screen_model=screen_model, figure_checker=figure_checker(mode == 'offline'))
    except Exception as e:                              # the loop reports its own errors; this is a last resort
        tr = {"calls": [], "final": "", "quarantined": [], "cost_usd": 0.0, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    from .llm_shared import check_replay_complete
    if mode != "offline":
        check_replay_complete(tr, f"case {case.id} arm {arm} rep {rep}")
    from .l7 import l7_info
    l7 = l7_info(tr, arm, "trigger" in case.tags)
    ev = judged(case, tr, arm)
    rec = {"case": case.id, "family": case.family, "surface": case.surface, "goal": case.goal, "technique": case.technique, "expected_stop": case.expected_stop,
           "control": case.control, "arm": arm, "model": getattr(model, "model", model), "rep": rep, "mode": mode,
           "secs": round(time.time() - t0, 2), "est_tokens": est_tokens(tr), "ledger_n": len(getattr(env, "ledger", [])), "l7": l7, **ev,
           "cost_usd": round(float(tr.get("cost_usd") or 0.0), 6), "error": tr.get("error"), "transcript": compact(tr)}
    if case.control and ev["utility"] is None:
        rec["utility"] = None
    return rec


def run_many(case_list, model, arms, reps: int, *, out: Path | None = None, concurrency: int = 8, screen_model=None, mode="live", max_steps=12,
             progress=None) -> tuple[Path, list[dict]]:
    RUNS.mkdir(parents=True, exist_ok=True)
    out = out or RUNS / (time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + ".jsonl")
    jobs = [(c, a, r) for c in case_list for a in arms for r in range(reps)]
    lock, results, stop = threading.Lock(), [], threading.Event()

    def work(job):
        if stop.is_set():
            return None
        c, a, r = job
        rec = run_case(c, model, a, r, screen_model=screen_model, mode=mode, max_steps=max_steps)
        err = (rec.get("error") or "")
        if "BudgetExceeded" in err or "CreditFloor" in err:
            stop.set()
        with lock:
            results.append(rec)
            with out.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if progress:
                progress(len(results), len(jobs), rec)
        return rec

    with ThreadPoolExecutor(max(1, concurrency)) as ex:
        list(ex.map(work, jobs))
    return out, results


# ---------------------------------------------------------------------------------------------------- estimate
def chunk_tokens(text: str) -> int:
    return int(len(text) / 3.7) + 1


BASE_TOKENS = 1300           # system prompt, task, tool specs
OUT_TOKENS_PER_CALL = 600    # includes reasoning overhead
SCREEN_SYSTEM_TOKENS = 700


def estimate(case_list, model: str, arms, reps: int) -> dict:
    price_in, price_out = PRICES.get(model, DEFAULT_PRICE)
    per_arm: dict[str, dict] = {}
    seen_chunks: set[str] = set()
    screen_calls = screen_in = 0
    for c in case_list:
        env = c.build_env()
        chunks = env_chunks(env)
        content = sum(chunk_tokens(t) for _, t in chunks)
        steps = 6
        agent_in = steps * BASE_TOKENS + (steps - 2) * content
        agent_out = steps * OUT_TOKENS_PER_CALL
        for a in arms:
            d = per_arm.setdefault(a, {"runs": 0, "calls": 0, "in": 0, "out": 0})
            d["runs"] += reps
            d["calls"] += reps * steps
            d["in"] += reps * agent_in
            d["out"] += reps * agent_out
        if "full" in arms:
            for kind, t in chunks:                 # screening is cached by content hash, so each distinct chunk is paid once
                h = kind + "\x1f" + t
                if h not in seen_chunks:
                    seen_chunks.add(h)
                    screen_calls += 1
                    screen_in += SCREEN_SYSTEM_TOKENS + chunk_tokens(t)
    if "full" in per_arm:
        per_arm["full"]["calls"] += screen_calls
        per_arm["full"]["in"] += screen_in
        per_arm["full"]["out"] += screen_calls * 80
    for d in per_arm.values():
        d["usd"] = d["in"] / 1e6 * price_in + d["out"] / 1e6 * price_out
    tot = {"runs": sum(d["runs"] for d in per_arm.values()), "calls": sum(d["calls"] for d in per_arm.values()),
           "in": sum(d["in"] for d in per_arm.values()), "out": sum(d["out"] for d in per_arm.values()), "usd": sum(d["usd"] for d in per_arm.values())}
    return {"model": model, "priced": model in PRICES, "price_in": price_in, "price_out": price_out, "reps": reps, "cases": len(case_list),
            "per_arm": per_arm, "total": tot, "screen_calls": screen_calls}


def format_estimate(e: dict) -> str:
    lines = [f"model {e['model']}{'' if e['priced'] else ' (no listed price: using the deepseek-v4.1-flash price)'}  in ${e['price_in']}/M  out ${e['price_out']}/M",
             f"{e['cases']} cases x reps {e['reps']}",
             f"{'arm':10} {'runs':>6} {'calls':>7} {'tokens in':>12} {'tokens out':>11} {'US$':>8}"]
    for a, d in e["per_arm"].items():
        lines.append(f"{a:10} {d['runs']:>6} {d['calls']:>7} {d['in']:>12,} {d['out']:>11,} {d['usd']:>8.3f}")
    t = e["total"]
    lines.append(f"{'total':10} {t['runs']:>6} {t['calls']:>7} {t['in']:>12,} {t['out']:>11,} {t['usd']:>8.3f}")
    if "full" in e["per_arm"]:
        lines.append(f"(includes {e['screen_calls']} distinct screen calls, paid once because screening is cached by content)")
    return "\n".join(lines)
