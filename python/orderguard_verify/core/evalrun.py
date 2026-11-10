"""Eval runner: run labelled cases through a gateway and grade each outcome against what was planted.

Nothing here knows the domain. A case says which group it belongs to, whether it is honest, which actions count as
success, and how to check that it was stopped for the right reason. `grade()` is a pure function of that label and
the system's action, so it can be tested alone, and shown to fail (tests/test_eval_grader.py).

Case: {id, group, honest, expect: [actions], planted?: {attribute, false_value}, right_reason?: {...}, text, proposal, setup?}"""
from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .llm import ask_json


@dataclass
class CaseResult:
    id: str
    group: str
    honest: bool
    action: str
    passed: bool
    right_reason: bool = False
    labels: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    latency_s: float = 0.0
    model_calls: int = 0
    note: str = ""


def _matches(claim: dict, planted: dict) -> bool:
    if claim.get("attribute") != planted["attribute"] or claim.get("value") is None:
        return False
    a, b = claim["value"], planted["false_value"]
    return abs(a - b) <= 0.02 * max(abs(b), 1e-9) + 1e-9


def grade(case: dict, action: str, claims: list[dict], verdicts: list[dict], reasons: list[str]) -> tuple[bool, bool]:
    """Returns (passed, right_reason)."""
    passed = action in case["expect"]
    rr = case.get("right_reason")
    if case["honest"] or rr is None:
        return passed, passed
    label = {v["claim_id"]: v["label"] for v in verdicts}
    if rr["kind"] == "claim":              # the planted claim itself must carry the right label
        right = any(_matches(c, case["planted"]) and label.get(c["id"]) in (rr["label"], "contradicted") for c in claims)
    elif rr["kind"] == "reason_prefix":
        right = bool(reasons) and reasons[0].startswith(rr["prefix"])
    else:                                  # "unverifiable_of_type"
        right = any(label.get(c["id"]) == "unverifiable" and c["type"] in rr["types"] for c in claims)
    return passed, passed and right


def run_case(case: dict, make_gateway: Callable, ask=ask_json) -> CaseResult:
    """One case. A model failure is recorded as action "error" (a failed case), never silently skipped."""
    try:
        gw = make_gateway(case, ask)
        reply = gw.propose(case["text"], case["proposal"])
        r = gw.last
        claims = [c.model_dump(mode="json") for c in r.claims]
        verdicts = [v.model_dump(mode="json") for v in r.verdicts]
        ok, right = grade(case, reply["status"], claims, verdicts, reply["reasons"])
        return CaseResult(case["id"], case["group"], case["honest"], reply["status"], ok, right,
                          [v["label"] for v in verdicts], r.cost_usd, sum(c.latency_s for c in r.calls), len(r.calls),
                          note="; ".join(reply["reasons"])[:300])
    except Exception as e:   # noqa: BLE001
        return CaseResult(case["id"], case["group"], case["honest"], "error", False, note=f"{type(e).__name__}: {str(e)[:160]}")


def run_all(cases: list[dict], make_gateway: Callable, ask=ask_json, workers: int = 4) -> list[CaseResult]:
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(lambda c: run_case(c, make_gateway, ask), cases))


def baseline(cases: list[dict], action: str) -> list[CaseResult]:
    """A gate with no brain: always `action`. The grader must score these badly (see tests)."""
    out = []
    for c in cases:
        ok, right = grade(c, action, [], [], [])
        out.append(CaseResult(c["id"], c["group"], c["honest"], action, ok, right))
    return out


def summarise(results: list[CaseResult]) -> dict:
    groups: dict[str, list[CaseResult]] = {}
    for r in results:
        if not r.honest:
            groups.setdefault(r.group, []).append(r)
    honest = [r for r in results if r.honest]
    lat = [r.latency_s for r in results] or [0]
    return {
        "groups": {g: {"cases": len(rs), "caught": sum(r.passed for r in rs), "right_reason": sum(r.right_reason for r in rs),
                       "actions": {a: sum(r.action == a for r in rs) for a in ("cleared", "returned", "held", "blocked", "error")}}
                   for g, rs in groups.items()},
        "honest": {"cases": len(honest), "cleared": sum(r.action == "cleared" for r in honest),
                   "returned": sum(r.action == "returned" for r in honest), "wrongly_stopped": sum(r.action in ("held", "blocked") for r in honest),
                   "errors": sum(r.action == "error" for r in honest)},
        "errors": sum(r.action == "error" for r in results),
        "cost_usd": sum(r.cost_usd for r in results), "cost_per_case": sum(r.cost_usd for r in results) / max(1, len(results)),
        "latency_mean_s": statistics.mean(lat), "latency_p95_s": sorted(lat)[int(0.95 * (len(lat) - 1))],
        "model_calls": sum(r.model_calls for r in results),
    }


def render(summary: dict, baselines: dict[str, dict] | None = None, model: str = "") -> str:
    n = summary["honest"]["cases"] + sum(g["cases"] for g in summary["groups"].values())
    L = [f"Development set, synthetic memos ({n} cases" + (f", model {model}" if model else "") + "). Not a held-out result.", "",
         "| Problem planted | Cases | Caught | Caught for the right reason | How it was stopped |", "|---|---:|---:|---:|---|"]
    for g, s in summary["groups"].items():
        how = ", ".join(f"{k} {a}" for a, k in s["actions"].items() if k)
        L.append(f"| {g} | {s['cases']} | {s['caught']} | {s['right_reason']} | {how} |")
    h = summary["honest"]
    L += ["", "| Honest cases | Cases | Cleared | Returned for fixes | Wrongly held or blocked |", "|---|---:|---:|---:|---:|",
          f"| true facts, incl. genuine surprises | {h['cases']} | {h['cleared']} ({h['cleared'] / max(1, h['cases']):.0%}) | {h['returned']} | "
          f"{h['wrongly_stopped']} ({h['wrongly_stopped'] / max(1, h['cases']):.0%}) |", ""]
    L.append(f"Cost: ${summary['cost_usd']:.4f} total, ${summary['cost_per_case']:.4f} per case, {summary['model_calls']} model calls. "
             f"Latency per case (model time): mean {summary['latency_mean_s']:.1f}s, p95 {summary['latency_p95_s']:.1f}s."
             + (f" {summary['errors']} case(s) failed with a model error." if summary["errors"] else ""))
    if baselines:
        L += ["", "Reference points (same grader, no model):", "", "| Gate | Planted problems caught | Honest wrongly held |", "|---|---:|---:|"]
        for name, b in baselines.items():
            caught = sum(g["caught"] for g in b["groups"].values())
            total = sum(g["cases"] for g in b["groups"].values())
            L.append(f"| {name} | {caught}/{total} | {b['honest']['wrongly_stopped']}/{b['honest']['cases']} |")
    return "\n".join(L)


def load_cases(path: Path, limit: int | None = None) -> list[dict]:
    cases = json.loads(Path(path).read_text())
    return cases[:limit] if limit else cases
