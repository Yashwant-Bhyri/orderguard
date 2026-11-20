"""Build the auxiliary-hint-free variant of the T20 200-item set.

The primary states expose ``triage_rules``, and the review states expose
``task``, ``review_verdict`` and ``section``.  This script copies the 200 items
and removes those fields so the same questions can be asked without them.

``owner_label`` is deliberately kept: the ``label_ok`` question asks whether the
displayed owner label is plausibly wrong, so removing it would make that question
unanswerable.  Its strength is quantified separately by the displayed-label
baseline in ``score.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "work" / "T20"
IN = ROOT / "data" / "t20" / "handset.jsonl"
OUT = ROOT / "data" / "t20_blind" / "handset_blind.jsonl"


def main() -> None:
    items = [json.loads(line) for line in IN.open(encoding="utf-8") if line.strip()]
    out = []
    for item in items:
        state = dict(item["state"])
        state.pop("triage_rules", None)
        if item["kind"] == "review_finding":
            for key in ("task", "review_verdict", "section"):
                state.pop(key, None)
        row = {
            "id": item["id"],
            "kind": item["kind"],
            "source": item["source"],
            "state": state,
            "questions": item["questions"],
        }
        if "family" in item:
            row["family"] = item["family"]
            row["shifted"] = item["shifted"]
        out.append(row)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for row in out:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    try:
        shown = OUT.relative_to(ROOT)
    except ValueError:
        shown = Path(OUT.name)
    print(f"wrote {len(out)} blind items to {shown}")


if __name__ == "__main__":
    main()
