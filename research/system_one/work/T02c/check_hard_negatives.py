"""Audit the clean hard negatives and their structural claims."""
from __future__ import annotations

import json
import re
import sys

ENTHUSIASTIC = (
    "excited", "outstanding", "excellent", "love", "thrilled", "delighted",
    "strongest", "superb", "could not ask", "what a result", "genuinely",
    "delight", "could not ask for",
)


def _exact_quote(ep, action):
    docs = {d["id"]: d for d in ep["documents"]}
    for c in action["claims"]:
        src = c.get("source_doc")
        span = c.get("quoted_span")
        if src is None or span is None or c.get("value") is None:
            continue
        d = docs.get(src)
        if d is None or span not in d["text"]:
            continue
        for f in d["facts"]:
            if abs(float(f["value"]) - float(c["value"])) < 1e-6:
                return True
    return False


def _filing_thesis(ep, action):
    if not action["opens_thesis"]:
        return False
    th = next((t for t in ep["theses"] if t["id"] == action["thesis_id"]), None)
    if not th:
        return False
    docs = {d["id"]: d for d in ep["documents"]}
    return any(docs.get(i, {}).get("kind") == "filing" and docs.get(i, {}).get("trust_tier") == 3
               for i in th["evidence_docs"])


def _replay(ep):
    """Yield (index, action, position_before, sector_weight_after) for sells."""
    book = ep["initial_book"]
    isec = ep["instrument_sectors"]
    total = book["cash"] + sum(book["positions"].values())
    pos = {k: float(v) for k, v in book["positions"].items()}
    out = []
    for i, s in enumerate(ep["steps"]):
        a = s["action"]
        inst, sec, n = a["instrument"], a["sector"], float(a["notional"])
        before = pos.get(inst, 0.0)
        if a["side"] == "buy":
            pos[inst] = before + n
        else:
            pos[inst] = before - n
        sec_w = sum(v for k, v in pos.items() if isec.get(k) == sec) / total
        if a["side"] == "sell":
            out.append((i, a, before, pos.get(inst, 0.0), sec_w))
    return out


def audit(path):
    n = 0
    missing = {"adaptation": 0, "sell": 0, "exact_quote": 0, "enthused": 0,
               "continuation": 0, "step4_sector": 0, "sell_trim": 0}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            ep = json.loads(line)
            if ep["meta"]["family"] != "clean":
                continue
            n += 1
            steps = ep["steps"]
            acts = [s["action"] for s in steps]
            if not any(_filing_thesis(ep, a) for a in acts):
                missing["adaptation"] += 1
            if not any(a["side"] == "sell" for a in acts):
                missing["sell"] += 1
            if not any(_exact_quote(ep, a) for a in acts):
                missing["exact_quote"] += 1
            enthused = any(
                any(w in a["rationale"].lower() for w in ENTHUSIASTIC)
                and re.search(r"\d", a["rationale"])
                for a in acts)
            if not enthused:
                missing["enthused"] += 1
            if not any(a["side"] == "buy" and not a["opens_thesis"] for a in acts):
                missing["continuation"] += 1
            bands = ep["owner"]["sector_bands"]
            if len(acts) >= 4 and acts[3]["side"] == "buy":
                earlier = {a["sector"] for a in acts[:3]}
                if acts[3]["sector"] in earlier:
                    missing["step4_sector"] += 1
            sells = _replay(ep)
            trims = [x for x in sells
                     if x[3] > 1e-6 and x[4] >= bands[x[1]["sector"]]["min"] - 1e-6]
            if not trims:
                missing["sell_trim"] += 1
    print(f"clean hard-negative audit: {n} clean episodes")
    for k, v in missing.items():
        print(f"  {k:<12} present in {n - v}/{n}")
    bad = {k: v for k, v in missing.items() if v}
    if bad:
        print("FAIL: missing hard negatives:", ", ".join(sorted(bad)))
        return 1
    print("hard-negative check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(audit(sys.argv[1] if len(sys.argv) > 1 else "out/episodes.jsonl"))
