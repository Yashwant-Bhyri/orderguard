"""Measure the copilot and the scope check on their labelled sets. Same code path as the product (`review_draft`, `scope_check`)."""
from __future__ import annotations

import bisect
import collections
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from orderguard_guard.decisions import REPLAY, Decisions
from orderguard_guard.llm import request_hash

from . import advice as A
from . import copilot, labelled_drafts as LD, labelled_scope as LS
from .scope import scope_check


def auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    s = sorted(neg)
    return sum((bisect.bisect_left(s, p) + bisect.bisect_right(s, p)) / 2 for p in pos) / (len(pos) * len(neg))


def breadth(d: dict, parent: dict) -> float:
    """The deterministic baseline: how much of the parent's room the draft uses (symbols, per-order, daily, orders a day, price band).
    It cannot read the purpose, so it can only catch drafts that are wide, not drafts that are wrong."""
    parts = [len(d["symbols"]) / len(parent["symbols"]), d["maxOrderNotionalUsd"] / parent["maxOrderNotionalUsd"], d["maxDailyNotionalUsd"] / parent["maxDailyNotionalUsd"],
             d["maxOrdersPerDay"] / parent["maxOrdersPerDay"], d["priceBandPct"] / parent["priceBandPct"]]
    return sum(parts) / len(parts)


def _cost(bodies: list[dict], replay_dir: Path) -> dict:
    import json
    total = n = 0
    for b in bodies:
        p = Path(replay_dir) / f"{request_hash(b)}.json"
        if p.exists():
            n += 1
            total += float((json.loads(p.read_text())["response"].get("usage") or {}).get("cost") or 0.0)
    return {"recorded_calls": n, "cost_usd": round(total, 6), "cost_per_1000_usd": round(total / n * 1000, 4) if n else None}


def evaluate_drafts(decisions: Decisions | None = None, *, workers: int = 1) -> dict:
    decisions = decisions or Decisions(A.model_name())
    parent, pub = LD.parent()
    now = dt.datetime.fromisoformat(LD.NOW)

    def one(item):
        _id, cat, purpose, draft, _acc = item
        return copilot.review_draft(parent, draft, purpose, trusted_key=pub, now=now, decisions=decisions)
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(one, LD.SET)) if workers > 1 else [one(i) for i in LD.SET]
    rows, bodies = [], []
    for item, r in zip(LD.SET, results):
        _id, cat, purpose, draft, acc = item
        adv = r["advice"]
        flag = adv.get("flag_score")
        rows.append({"id": _id, "category": cat, "label": int(cat != "appropriate"), "fits": r["fits"], "flag_score": flag,
                     "appropriateness": (r["appropriateness"] or {}).get("score"), "scope_match": r["scope_match"], "concern": (r["concerns"] or {}).get("choice"),
                     "concern_ok": None if cat == "appropriate" or r["concerns"] is None else r["concerns"]["choice"] in acc, "breadth": breadth(draft, LD.PARENT_BODY),
                     "action": adv["suggested_action"]})
        bodies.append({"model": A.model_name(), "state": copilot.build_state(parent, draft, purpose), "questions": copilot.QUESTIONS})
    ok = [r for r in rows if r["flag_score"] is not None]
    pos = [r["flag_score"] for r in ok if r["label"]]
    neg = [r["flag_score"] for r in ok if not r["label"]]
    flagged = lambda r: r["flag_score"] >= copilot.FLAG_BELOW        # noqa: E731
    by_cat = collections.defaultdict(list)
    for r in ok:
        by_cat[r["category"]].append(r)
    base = auc([r["breadth"] for r in rows if r["label"]], [r["breadth"] for r in rows if not r["label"]])

    def sig(f):
        v = auc([f(r) for r in ok if r["label"]], [f(r) for r in ok if not r["label"]])
        return None if v is None else round(v, 4)
    cal, held = ok[0::2], ok[1::2]                       # threshold calibrated on the even-position half; every held-out figure is the odd half
    ho_pos, ho_neg = [r for r in held if r["label"]], [r for r in held if not r["label"]]
    cal_neg, cal_pos = [r["flag_score"] for r in cal if not r["label"]], [r["flag_score"] for r in cal if r["label"]]
    recalibrated = round((max((x for x in cal_neg if x < min(cal_pos)), default=min(cal_pos)) + min(cal_pos)) / 2, 4) if cal_pos and cal_neg else None
    return {"n": len(rows), "labels": dict(collections.Counter(r["category"] for r in rows)), "all_contained": all(r["fits"] for r in rows),
            "no_advice": len(rows) - len(ok), "model": A.model_name(), "flag_threshold": copilot.FLAG_BELOW,
            "auc": sig(lambda r: r["flag_score"]), "signal_auc": {"appropriateness": sig(lambda r: 1 - r["appropriateness"]), "scope_match": sig(lambda r: 1 - r["scope_match"]),
                                                                   "concern_named": sig(lambda r: 0.0 if r["concern"] == "none" else 1.0)},
            "baseline_breadth_auc": round(base, 4),
            "calibration": {"calibrated_on": "even-position drafts", "threshold_from_that_half": recalibrated, "shipped_threshold": copilot.FLAG_BELOW,
                            "heldout_n": len(held), "heldout_accuracy": round(sum(flagged(r) == bool(r["label"]) for r in held) / max(len(held), 1), 4),
                            "heldout_flag_rate_on_appropriate": round(sum(flagged(r) for r in ho_neg) / max(len(ho_neg), 1), 4),
                            "heldout_recall_on_inappropriate": round(sum(flagged(r) for r in ho_pos) / max(len(ho_pos), 1), 4)},
            "accuracy_all_40_optimistic": round(sum(flagged(r) == bool(r["label"]) for r in ok) / len(ok), 4) if ok else None,
            "flag_rate_on_appropriate": round(sum(flagged(r) for r in ok if not r["label"]) / max(len(neg), 1), 4),
            "recall_by_category": {c: round(sum(flagged(r) for r in v) / len(v), 4) for c, v in by_cat.items() if c != "appropriate"},
            "concern_named_acceptably": round(sum(bool(r["concern_ok"]) for r in ok if r["label"]) / max(len(pos), 1), 4),
            "cost": _cost(bodies, REPLAY), "rows": rows}


def evaluate_scope(decisions: Decisions | None = None, *, workers: int = 1) -> dict:
    decisions = decisions or Decisions(A.model_name())

    def one(item):
        _id, _label, intent, order = item
        return scope_check(LS.MANDATE, order, intent, decisions=decisions)
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(one, LS.SET)) if workers > 1 else [one(i) for i in LS.SET]
    rows = [{"id": i[0], "label": i[1], "mismatch": r["mismatch_probability"], "action": r["suggested_action"]} for i, r in zip(LS.SET, results)]
    ok = [r for r in rows if r["mismatch"] is not None]
    pos = [r["mismatch"] for r in ok if r["label"]]
    neg = [r["mismatch"] for r in ok if not r["label"]]
    from .scope import WARN_AT
    return {"n": len(rows), "no_advice": len(rows) - len(ok), "model": A.model_name(), "warn_at": WARN_AT,
            "auc": None if auc(pos, neg) is None else round(auc(pos, neg), 4),
            "accuracy": round(sum((r["mismatch"] >= WARN_AT) == bool(r["label"]) for r in ok) / len(ok), 4) if ok else None,
            "hold_rate_on_matching": round(sum(r["action"] == "hold" for r in ok if not r["label"]) / max(len(neg), 1), 4),
            "hold_rate_on_mismatching": round(sum(r["action"] == "hold" for r in ok if r["label"]) / max(len(pos), 1), 4),
            "warn_or_hold_rate_on_matching": round(sum(r["action"] != "none" for r in ok if not r["label"]) / max(len(neg), 1), 4),
            "warn_or_hold_rate_on_mismatching": round(sum(r["action"] != "none" for r in ok if r["label"]) / max(len(pos), 1), 4),
            "rows": rows}
