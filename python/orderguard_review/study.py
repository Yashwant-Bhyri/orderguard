"""Replay an arena decision stream and measure what typed triage does for a human reviewer who can clear only K held orders an hour.

The queue is built from HELD orders. Three queues, because the shipped order-risk model holds very few orders (see `shipped_model_holds`):

    model_holds    the gate-allowed orders the shipped model holds as is (risk between its hold and refuse thresholds): too few to make a queue
    model_flagged  every gate-allowed order with risk >= `floor`, treated as held for a human (the same model, a lower threshold, no automatic refusal)
    all_held       model_flagged plus every order the gate itself held (uncorroborated news triggers, step-up holds): the mixed queue a reviewer really faces

Reviewers act hour by hour (an hour is steps_per_day / hours_per_day steps). In each hour they open the top K orders of that hour's
queue under one ordering, and a bad dollar is "caught" when its order is opened. Orderings: FIFO, biggest notional first, the risk model's
p x notional, the decision model's p x notional, and the headline (noisy-OR of both) x notional. Labels never reach the decision model.
"""
from __future__ import annotations

import collections
import json
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from orderguard_risk.scorer import RiskScorer, arena_event

from . import advice as A
from .triage import triage

ROOT = Path(__file__).resolve().parents[2]
STREAM = ROOT / "results" / "arena" / "arena-s7-k1000-t2000.jsonl"
FLOOR = 3e-4
KS = (1, 2, 3, 5, 8, 12, 20)
HEADLINE = {"model_holds": 1, "model_flagged": 5, "all_held": 8}
ORDERINGS = ("fifo", "notional", "model", "jev", "jev+model")
ABLATIONS = ("mean(model,jev)", "pattern", "urgency", "model+pattern")
TAPE, RECENT = 25, 8


def load_stream(path: Path) -> tuple[dict, list[dict]]:
    rows = [json.loads(line) for line in Path(path).open()]
    summary = Path(path).with_suffix(".summary.json")
    meta = json.loads(summary.read_text()) if summary.exists() else (rows[0] if "envelopes" in rows[0] else {})
    return meta, [r for r in rows if "order" in r]


def held_order(e: dict, tp) -> dict:
    o = e["order"]
    return {"step": e["step"], "agent": e["agent"], "ticker": o.get("ticker"), "side": o.get("side"), "quantity": o.get("quantity"),
            "limit_price": o.get("limit_price"), "notional_usd": float(e.get("risk") or 0.0), "trusted_price": tp}


def build_cases(events: list[dict], meta: dict, *, floor: float = FLOOR, hours_per_day: int = 8) -> tuple[list[dict], dict]:
    """Stream the events through the risk model, point in time, and return every order that can be in some queue."""
    envs = {e["name"]: e for e in meta.get("envelopes", [])}
    spd = int((meta.get("config") or {}).get("steps_per_day") or 500)
    sc = RiskScorer.load()
    sc.set_envelopes({n: {"per_order": e["per_order"], "daily": e["daily"], "step_up": e.get("step_up"), "band_pct": e.get("band_pct")} for n, e in envs.items()}, spd)
    by_agent, by_tk = collections.defaultdict(list), collections.defaultdict(list)
    cases = []
    for i, e in enumerate(events):
        ev = arena_event(e)
        r = sc.score(ev)
        sc.observe(ev)
        gate_held = e.get("d") == "hold"
        allowed = e.get("d") == "allow" and not e.get("replay")
        if gate_held or (allowed and r["risk"] >= floor):
            env = envs.get(e.get("env") or e.get("sleeve"), {})
            ho = held_order(e, e.get("tp"))
            ctx = {"envelope": {k: env.get(k) for k in ("name", "per_order", "step_up", "daily", "band_pct")},
                   "agent_recent": [held_order(x, x.get("tp")) for x in by_agent[e["agent"]][-RECENT:]],
                   "tape": [held_order(x, x.get("tp")) for x in by_tk[e["order"].get("ticker")][-TAPE:]]}
            cases.append({"i": i, "hour": int(e["step"] * hours_per_day // spd), "label": e["label"], "bad": e["label"] != "legit", "usd": ho["notional_usd"],
                          "gate_held": gate_held, "risk": r, "p_model": r["risk"], "action": r["action"], "held": ho, "context": ctx})
        by_agent[e["agent"]].append(e)
        by_tk[e["order"].get("ticker")].append(e)
    return cases, {"t_hold": sc.t_hold, "t_refuse": sc.t_refuse, "steps_per_day": spd, "hours_per_day": hours_per_day}


def queue_members(cases: list[dict], t_refuse: float) -> dict[str, list[dict]]:
    flagged = [c for c in cases if not c["gate_held"]]
    return {"model_holds": [c for c in flagged if c["action"] == "hold"], "model_flagged": flagged, "all_held": list(cases)}


def triage_all(cases: list[dict], decisions, *, workers: int = 1) -> dict:
    """Run the product's own `triage` on every case. Attaches `t` to each case; returns call statistics."""
    lat: list[float] = []

    def one(c):
        t0 = time.perf_counter()
        t = triage(c["held"], c["context"], risk=c["risk"], decisions=decisions)
        ms = (time.perf_counter() - t0) * 1000
        if ms > 50:                                  # a replayed recording takes well under a millisecond: only live calls are timed
            lat.append(ms)
        return t
    if workers > 1:
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(one, cases))
    else:
        results = [one(c) for c in cases]
    errors = collections.Counter()
    for c, t in zip(cases, results):
        c["t"] = t
        adv = t["advice"]
        if not adv["available"]:
            errors[adv["error"]] += 1
            c["p_jev"], c["pattern_bad"], c["urgency"] = None, None, None
        else:
            c["p_jev"] = adv["compromised_probability"]
            probs = adv.get("pattern_probabilities") or {}
            c["pattern_bad"] = (1.0 - probs["looks_honest"]) if "looks_honest" in probs else (0.0 if adv["pattern"] == "looks_honest" else 1.0)
            c["urgency"] = adv["urgency"]
    lat.sort()
    return {"calls": len(cases), "no_advice": sum(errors.values()), "errors": dict(errors),
            "live_latency_ms": {"n": len(lat), "p50": round(lat[len(lat) // 2], 1), "p95": round(lat[int(0.95 * (len(lat) - 1))], 1)} if lat else None}


def keys_for(c: dict) -> dict[str, float]:
    u, pm, pj = c["usd"], c["p_model"], c["p_jev"]
    merged = A.merge_probability(pm, pj)
    mean = pm if pj is None else (pm + pj) / 2
    return {"fifo": 0.0, "notional": u, "model": pm * u, "jev": (pj if pj is not None else 0.0) * u, "jev+model": merged * u,
            "mean(model,jev)": mean * u, "pattern": (c["pattern_bad"] or 0.0) * u, "urgency": (c["urgency"] or 0.0) * u,
            "model+pattern": A.merge_probability(pm, c["pattern_bad"]) * u}


def _hours(queue: list[dict]) -> dict[int, list[dict]]:
    out = collections.defaultdict(list)
    for c in queue:
        out[c["hour"]].append(c)
    return out


def _sorted(items: list[dict], name: str) -> list[dict]:
    if name == "fifo":
        return sorted(items, key=lambda c: c["i"])
    return sorted(items, key=lambda c: (-c["keys"][name], c["i"]))


def caught(queue: list[dict], name: str, k: int, hours=None) -> dict:
    """Bad dollars caught when the reviewer opens the top k of each hour's queue under ordering `name`."""
    by_hour = _hours(queue)
    bad_usd = bad_n = got_usd = got_n = opened = 0.0
    for h in (hours if hours is not None else sorted(by_hour)):
        items = by_hour.get(h, [])
        top = _sorted(items, name)[:k]
        bad_usd += sum(c["usd"] for c in items if c["bad"])
        bad_n += sum(1 for c in items if c["bad"])
        got_usd += sum(c["usd"] for c in top if c["bad"])
        got_n += sum(1 for c in top if c["bad"])
        opened += len(top)
    return {"bad_usd_caught_share": got_usd / bad_usd if bad_usd else None, "bad_orders_caught_share": got_n / bad_n if bad_n else None,
            "precision": got_n / opened if opened else None, "bad_usd_caught": got_usd, "reviews": int(opened)}


def reviews_to_catch(queue: list[dict], name: str, share: float) -> int:
    """Total reviews, summed over hours, until `share` of each hour's bad dollars has been opened."""
    total = 0
    for items in _hours(queue).values():
        bad = sum(c["usd"] for c in items if c["bad"])
        if not bad:
            continue
        acc = 0.0
        for n, c in enumerate(_sorted(items, name), 1):
            acc += c["usd"] if c["bad"] else 0.0
            if acc >= share * bad - 1e-9:
                total += n
                break
    return total


def auc(queue: list[dict], key) -> float | None:
    pos = [key(c) for c in queue if c["bad"]]
    neg = [key(c) for c in queue if not c["bad"]]
    if not pos or not neg:
        return None
    s = sorted(neg)
    import bisect
    return sum((bisect.bisect_left(s, p) + bisect.bisect_right(s, p)) / 2 for p in pos) / (len(pos) * len(neg))


def bootstrap(queue: list[dict], a: str, b: str, k: int, reps: int = 2000, seed: int = 0) -> dict:
    """Seeded bootstrap over hours of caught-share(a) - caught-share(b)."""
    hours = sorted(_hours(queue))
    rng = random.Random(seed)
    diffs = []
    for _ in range(reps):
        sample = [rng.choice(hours) for _ in hours]
        ca, cb = _caught_sample(queue, a, k, sample), _caught_sample(queue, b, k, sample)
        if ca is not None and cb is not None:
            diffs.append(ca - cb)
    diffs.sort()
    return {"low": round(diffs[int(0.025 * (len(diffs) - 1))], 4), "high": round(diffs[int(0.975 * (len(diffs) - 1))], 4)} if diffs else {}


def _caught_sample(queue, name, k, sample_hours):
    by_hour = _hours(queue)
    bad = got = 0.0
    for h in sample_hours:
        items = by_hour.get(h, [])
        bad += sum(c["usd"] for c in items if c["bad"])
        got += sum(c["usd"] for c in _sorted(items, name)[:k] if c["bad"])
    return got / bad if bad else None


def evaluate_queue(queue: list[dict], headline_k: int) -> dict:
    for c in queue:
        c["keys"] = keys_for(c)
    names = ORDERINGS + ABLATIONS
    bad = [c for c in queue if c["bad"]]
    out = {"orders": len(queue), "bad_orders": len(bad), "bad_usd": round(sum(c["usd"] for c in bad), 2),
           "honest_orders": len(queue) - len(bad), "hours": len(_hours(queue)),
           "orders_per_hour_mean": round(len(queue) / max(len(_hours(queue)), 1), 1),
           "by_label": {l: {"orders": n, "usd": round(sum(c["usd"] for c in bad if c["label"] == l), 2)} for l, n in collections.Counter(c["label"] for c in bad).items()},
           "caught_by_k": {}, "reviews_to_catch": {}, "auc": {}, "headline_k": headline_k}
    for name in names:
        out["caught_by_k"][name] = {str(k): {m: (round(v, 4) if isinstance(v, float) else v) for m, v in caught(queue, name, k).items()} for k in KS}
        out["reviews_to_catch"][name] = {"90%": reviews_to_catch(queue, name, 0.90), "99%": reviews_to_catch(queue, name, 0.99)}
    for name, key in (("model", lambda c: c["p_model"]), ("jev", lambda c: c["p_jev"] if c["p_jev"] is not None else 0.0),
                      ("jev+model", lambda c: A.merge_probability(c["p_model"], c["p_jev"])), ("pattern", lambda c: c["pattern_bad"] or 0.0), ("urgency", lambda c: c["urgency"] or 0.0),
                      ("model+pattern", lambda c: A.merge_probability(c["p_model"], c["pattern_bad"]))):
        a = auc(queue, key)
        out["auc"][name] = None if a is None else round(a, 4)
    k = headline_k
    out["headline"] = {"k_per_hour": k,
                       "bootstrap_vs_model": bootstrap(queue, "jev+model", "model", k), "bootstrap_vs_fifo": bootstrap(queue, "jev+model", "fifo", k),
                       "by_label_caught_usd_share": {l: {name: round(sum(c["usd"] for c in _top_all(queue, name, k) if c["label"] == l) / v["usd"], 4) if v["usd"] else None
                                                          for name in ("fifo", "model", "jev+model")} for l, v in out["by_label"].items()}}
    out["pattern_by_label"] = {l: dict(collections.Counter(c["t"]["advice"].get("pattern", "no_advice") for c in queue if c["label"] == l))
                               for l in sorted({c["label"] for c in queue})}
    return out


def _top_all(queue, name, k):
    out = []
    for items in _hours(queue).values():
        out += _sorted(items, name)[:k]
    return out


def jev_cost(cases: list[dict], replay_dir: Path) -> dict:
    """Sum the recorded cost of every call this study made (read from the recordings, so it is the same in replay)."""
    from orderguard_guard.llm import request_hash
    from .triage import QUESTIONS, build_state
    from .advice import model_name
    total, n = 0.0, 0
    for c in cases:
        body = {"model": model_name(), "state": build_state(c["held"], c["context"]), "questions": QUESTIONS}
        p = Path(replay_dir) / f"{request_hash(body)}.json"
        if p.exists():
            n += 1
            total += float((json.loads(p.read_text())["response"].get("usage") or {}).get("cost") or 0.0)
    return {"recorded_calls": n, "cost_usd": round(total, 6), "cost_per_1000_usd": round(total / n * 1000, 4) if n else None}


def run_study(stream: Path = STREAM, *, decisions, floor: float = FLOOR, hours_per_day: int = 8, workers: int = 1, limit: int | None = None,
              replay_dir: Path | None = None) -> dict:
    meta, events = load_stream(stream)
    events = events[:limit] if limit else events
    cases, info = build_cases(events, meta, floor=floor, hours_per_day=hours_per_day)
    stats = triage_all(cases, decisions, workers=workers)
    members = queue_members(cases, info["t_refuse"])
    queues = {name: evaluate_queue(members[name], HEADLINE[name]) for name in ("model_holds", "model_flagged", "all_held")}
    from orderguard_guard.decisions import REPLAY
    return {"stream": Path(stream).name, "events": len(events), "floor": floor, "model_thresholds": {"hold": round(info["t_hold"], 6), "refuse": round(info["t_refuse"], 6)},
            "hours_per_day": hours_per_day, "steps_per_day": info["steps_per_day"], "model": A.model_name(), "jev_calls": stats,
            "jev_cost": jev_cost(cases, replay_dir or REPLAY), "queues": queues,
            "shipped_model_holds": {"gate_allowed_orders": sum(1 for e in events if e.get("d") == "allow" and not e.get("replay")),
                                    "model_holds": sum(1 for c in cases if not c["gate_held"] and c["action"] == "hold"),
                                    "model_refuses": sum(1 for c in cases if not c["gate_held"] and c["action"] == "refuse"),
                                    "gate_holds": sum(1 for c in cases if c["gate_held"])}}
