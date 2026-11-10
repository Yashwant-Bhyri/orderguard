"""Score arm outputs against the labels. Plain code, no model, no checker.

Labels (one per claim, written by the labelling agent from the filing documents):
    {"memo_id", "quote", "figure", "verdict": "true"|"false"|"not_in_filings", "borderline": bool, "error_class": str|None}
Arm output (one per memo):
    {"memo_id", "arm", "action": "pass"|"revise"|"block"|"escalate"|"error",
     "claims": [{"quote", "verdict": "ok"|"wrong"|"unchecked"}], "cost_usd", "seconds"}

A claim matches when the arm's quote contains the label's figure and the two quotes share words. Three ways to count a false label as found,
because arms quote differently (a judge often quotes a whole sentence holding several figures, the engine one figure at a time):

  flagged   some matching arm claim is marked "wrong" (the sentence was flagged; the figure may not be singled out)
  named     a matching arm claim that holds ONLY this label's figure is marked "wrong" (the figure itself was pointed at)
  caught    strict: each arm claim answers at most one label, best word overlap first (kept so earlier numbers can be reproduced)

No matching claim at all = not extracted = a miss under every count. A true label is wrongly flagged the same three ways; "clean" means no
false label of the same memo sits in the wrong-marked sentence, so the alarm cannot be blamed on a neighbouring figure."""
from __future__ import annotations

import math
import re

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
STOPPED = {"revise", "block", "escalate"}      # anything but pass; "error" is neither a catch nor a clean pass


def numbers(text: str) -> set[str]:
    """The figures in a piece of text. Bare years (2021) are not figures."""
    found = {n.replace(",", "") for n in NUM.findall(text.replace("$", ""))}
    return {n for n in found if not re.fullmatch(r"(19|20)\d\d", n)} or found


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", text.lower()))


def matches(label: dict, arm_claim: dict) -> bool:
    fig = numbers(label["figure"])
    if not fig or not fig <= numbers(arm_claim["quote"]):
        return False
    la, ar = label["quote"].lower(), arm_claim["quote"].lower()
    if la in ar or ar in la:
        return True
    a, b = words(la), words(ar)
    return bool(a & b) and len(a & b) / len(a | b) >= 0.25


def assign(labels: list[dict], record: dict) -> list[str]:
    """For each label of one memo: 'wrong', 'ok', 'unchecked' or 'not_extracted', as this arm saw it. One arm claim answers at most one label
    (the same figure can appear twice in a memo), best word overlap first."""
    pairs = []
    for i, lab in enumerate(labels):
        for j, c in enumerate(record["claims"]):
            if matches(lab, c):
                a, b = words(lab["quote"]), words(c["quote"])
                pairs.append(((len(a & b) / max(1, len(a | b))) + (1 if numbers(c["quote"]) == numbers(lab["figure"]) else 0), i, j))
    out, used_i, used_j = ["not_extracted"] * len(labels), set(), set()
    for _, i, j in sorted(pairs, reverse=True):
        if i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            out[i] = {"wrong": "wrong", "ok": "ok"}.get(record["claims"][j]["verdict"], "unchecked")
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def score(labels: list[dict], records: list[dict], include_borderline: bool = False) -> dict:
    by_memo: dict[str, list[dict]] = {}
    for lab in labels:
        by_memo.setdefault(lab["memo_id"], []).append(lab)
    rec = {r["memo_id"]: r for r in records}
    out = {"flagged": 0, "named": 0, "checked_loose": 0, "by_class_flagged": {}, "true_flagged": 0, "true_flagged_clean": 0, "true_named": 0, "memos": 0, "false_claims": 0, "caught": 0, "by_class": {}, "true_claims": 0, "false_alarms": 0, "checked": 0, "labelled": 0,
           "flawed_memos": 0, "flawed_stopped": 0, "clean_memos": 0, "clean_stopped": 0, "errors": 0, "cost_usd": 0.0, "seconds": 0.0,
           "misses": [], "false_alarm_list": [], "clean_stopped_list": []}
    for memo_id, labs in by_memo.items():
        if memo_id not in rec:
            continue
        r = rec[memo_id]
        out["memos"] += 1
        out["errors"] += r["action"] == "error"
        out["cost_usd"] += r.get("cost_usd", 0.0)
        out["seconds"] += r.get("seconds", 0.0)
        scored = [lab for lab in labs if lab["verdict"] in ("true", "false") and (include_borderline or not lab.get("borderline"))]
        flawed = any(lab["verdict"] == "false" for lab in scored)
        for lab, st in zip(scored, assign(scored, r)):
            hits = [c for c in r["claims"] if matches(lab, c)]
            wrong = [c for c in hits if c["verdict"] == "wrong"]
            named = any(numbers(c["quote"]) == numbers(lab["figure"]) for c in wrong)
            out["labelled"] += 1
            out["checked"] += st in ("ok", "wrong")
            out["checked_loose"] += any(c["verdict"] in ("ok", "wrong") for c in hits)
            if lab["verdict"] == "false":
                cls = out["by_class"].setdefault(lab.get("error_class") or "other", {"n": 0, "caught": 0})
                cls["n"] += 1
                out["false_claims"] += 1
                fc = out["by_class_flagged"].setdefault(lab.get("error_class") or "other", {"n": 0, "flagged": 0, "named": 0})
                fc["n"] += 1
                fc["flagged"] += bool(wrong)
                fc["named"] += named
                out["flagged"] += bool(wrong)
                out["named"] += named
                if st == "wrong":
                    cls["caught"] += 1
                    out["caught"] += 1
                if not wrong:       # a miss is a false claim that no matching arm claim flagged
                    why = "not_extracted" if not hits else "ok" if any(c["verdict"] == "ok" for c in hits) else "unchecked"
                    out["misses"].append({"memo_id": memo_id, "quote": lab["quote"], "why_missed": why, "error_class": lab.get("error_class")})
            else:
                out["true_claims"] += 1
                out["true_flagged"] += bool(wrong)
                out["true_named"] += named
                others = [f for f in scored if f["verdict"] == "false"]
                out["true_flagged_clean"] += any(not any(matches(f, c) for f in others) for c in wrong)
                if st == "wrong":
                    out["false_alarms"] += 1
                    out["false_alarm_list"].append({"memo_id": memo_id, "quote": lab["quote"]})
        if flawed:
            out["flawed_memos"] += 1
            out["flawed_stopped"] += r["action"] in STOPPED
        elif scored:
            out["clean_memos"] += 1
            out["clean_stopped"] += r["action"] != "pass"
            if r["action"] != "pass":
                out["clean_stopped_list"].append({"memo_id": memo_id, "action": r["action"]})
    return out


def rate(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.0%} (95% CI {lo:.0%} to {hi:.0%})" if n else "n/a"
