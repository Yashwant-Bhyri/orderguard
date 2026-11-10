"""Merge specs.json + memos.json into data/eval/cases.json (the core eval-runner schema) and refuse any memo that
lacks a required string. The finance meaning of each case kind is decided here, not in the core runner."""
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent / "data" / "eval"
specs = json.loads((root / "specs.json").read_text())
memos = json.loads((root / "memos.json").read_text())

SOFT = {"kind": "unverifiable_of_type", "types": ["rumour", "sentiment"]}   # results are the gateway's order status
KINDS = {  # kind -> (group, honest, acceptable actions, how to check it was stopped for the right reason)
    "honest": ("Honest twin / benign", True, ["cleared"], None),
    "surprise": ("Honest but surprising", True, ["cleared"], None),
    "stale": ("Stale or restated figure", False, ["returned", "blocked"], {"kind": "claim", "label": "stale"}),
    "rumour_side": ("Rumour as an aside", False, ["returned", "held", "blocked"], SOFT),
    "rumour_main": ("Rumour as the reason", False, ["held", "blocked"], SOFT),
    "sentiment_only": ("Sentiment alone", False, ["held", "blocked"], SOFT),
    "mandate": ("Outside the mandate", False, ["blocked"], {"kind": "reason_prefix", "prefix": "the request is outside the signed mandate"}),
}
cases, problems = [], []
for s in specs:
    memo = memos.get(s["id"], "")
    for req in s["required"]:
        if req not in memo:
            problems.append(f"{s['id']}: missing {req!r}")
    if str(s["quantity"]) not in re.sub(r"(?<=\d),(?=\d)", "", memo):
        problems.append(f"{s['id']}: quantity {s['quantity']} not stated")
    if s["kind"] == "planted":
        group = "False price (SYNTHETIC quotes, not in the headline)" if s["planted"]["metric"] == "price" else "False number (filings)"
        group, honest, expect, rr = group, False, ["blocked"], {"kind": "claim", "label": "contradicted"}
    else:
        group, honest, expect, rr = KINDS[s["kind"]]
    case = {"id": s["id"], "group": group, "honest": honest, "expect": expect, "text": memo,
            "proposal": {"ticker": s["ticker"], "side": s["side"], "quantity": s["quantity"], "as_of": s["as_of"]}}
    if rr:
        case["right_reason"] = rr
    if "planted" in s:
        case["planted"] = {"attribute": s["planted"]["metric"], "false_value": s["planted"]["false_value"],
                           "true_value": s["planted"]["true_value"], "text": s["planted"]["text"]}
    if s.get("position"):
        case["setup"] = {"position": s["position"]}
    case.update({k: s[k] for k in ("twin_of", "note") if k in s})
    cases.append(case)
if problems:
    print("\n".join(problems[:20]))
    sys.exit(f"{len(problems)} problem(s)")
(root / "cases.json").write_text(json.dumps(cases, indent=1))
print(f"wrote {len(cases)} cases")
