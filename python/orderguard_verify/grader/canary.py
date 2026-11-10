"""Canary: known arms with known right answers. A grader that disagrees with any of them is broken.
This project once shipped a grader that scored an inverted metric; this is the check that would have caught it."""
from __future__ import annotations

from .score import score

LABELS = [
    {"memo_id": "m1", "quote": "revenue of $100 billion", "figure": "$100 billion", "verdict": "true", "borderline": False},
    {"memo_id": "m1", "quote": "net income of $50 billion", "figure": "$50 billion", "verdict": "false", "borderline": False, "error_class": "wrong_figure"},
    {"memo_id": "m2", "quote": "revenue of $80 billion", "figure": "$80 billion", "verdict": "true", "borderline": False},
]


def _arm(action1: str, v_true: str, v_false: str, action2: str, v2: str) -> list[dict]:
    claims1 = [{"quote": "revenue of $100 billion", "verdict": v_true}, {"quote": "net income of $50 billion", "verdict": v_false}]
    return [{"memo_id": "m1", "arm": "x", "action": action1, "claims": claims1},
            {"memo_id": "m2", "arm": "x", "action": action2, "claims": [{"quote": "revenue of $80 billion", "verdict": v2}]}]


ARMS = {
    "perfect": _arm("block", "ok", "wrong", "pass", "ok"),
    "no_checker": _arm("pass", "unchecked", "unchecked", "pass", "unchecked"),
    "blocks_everything": _arm("block", "wrong", "wrong", "block", "wrong"),
    "inverted": _arm("pass", "wrong", "ok", "block", "wrong"),
}
# arm -> (false claims caught, true claims called wrong, honest memos stopped, flawed memos stopped)
EXPECTED = {"perfect": (1, 0, 0, 1), "no_checker": (0, 0, 0, 0), "blocks_everything": (1, 2, 1, 1), "inverted": (0, 2, 1, 0)}


def failures(score_fn=score) -> list[str]:
    bad = []
    for name, records in ARMS.items():
        s = score_fn(LABELS, records)
        got = (s["caught"], s["false_alarms"], s["clean_stopped"], s["flawed_stopped"])
        if got != EXPECTED[name]:
            bad.append(f"{name}: expected {EXPECTED[name]}, grader says {got}")
    return bad
