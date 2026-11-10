"""`og gate`: fail on regression. Runs offline from the recorded model answers, so it is fast, free and repeatable.

1. The grader's canaries pass (the grader can still fail).
2. The synthetic development set scores no worse than the baseline.
3. The engine on the native development memos scores no worse than the baseline.
`og gate --update` rewrites the baseline; that is a deliberate act and shows up in the diff."""
from __future__ import annotations

import json
import os
from datetime import date

from .core import evalrun
from .core.llm import ask_json
from .finance.evalsetup import CASES, make_gateway
from .finance.truth_store import TruthStore
from .grader import canary
from .grader.score import score
from .native import arms, run
from .paths import RESULTS

BASELINE = RESULTS / "gate_baseline.json"


def measure() -> dict:
    os.environ["OG_LLM"] = "replay"
    s = evalrun.summarise(evalrun.run_all(evalrun.load_cases(CASES), make_gateway, ask_json, workers=8))
    memos = json.loads((run.DATA / "native" / "memos.json").read_text())
    labels = run.load_labels("dev")
    ids = sorted({lab["memo_id"] for lab in labels})
    engine = arms.engine(run.ENGINE, TruthStore())
    recs = [engine(i, memos[i]["text"], memos[i]["ticker"], date.fromisoformat(memos[i]["as_of"])) for i in ids]
    n = score(labels, recs)
    return {"synthetic_caught": sum(g["caught"] for g in s["groups"].values() if True), "synthetic_cases": sum(g["cases"] for g in s["groups"].values()),
            "synthetic_honest_wrongly_stopped": s["honest"]["wrongly_stopped"], "synthetic_errors": s["errors"],
            "native_false_flagged": n["flagged"], "native_false_named": n["named"], "native_false_claims": n["false_claims"], "native_false_alarms": n["false_alarms"],
            "native_true_claims": n["true_claims"], "native_errors": n["errors"]}


WORSE_IF_LOWER = ("synthetic_caught", "native_false_flagged", "native_false_named")
WORSE_IF_HIGHER = ("synthetic_honest_wrongly_stopped", "synthetic_errors", "native_false_alarms", "native_errors")


def main(update: bool = False) -> int:
    bad = [f"grader canary: {x}" for x in canary.failures()]
    now = measure()
    if update:
        BASELINE.write_text(json.dumps(now, indent=1) + "\n")
        print("baseline written:", now)
        return 1 if bad else 0
    base = json.loads(BASELINE.read_text())
    bad += [f"{k} fell from {base[k]} to {now[k]}" for k in WORSE_IF_LOWER if now[k] < base[k]]
    bad += [f"{k} rose from {base[k]} to {now[k]}" for k in WORSE_IF_HIGHER if now[k] > base[k]]
    print("gate measured:", now)
    print("FAIL:\n  " + "\n  ".join(bad) if bad else "gate passed: no regression against the recorded baseline (data/verify/results/gate_baseline.json)")
    return 1 if bad else 0
