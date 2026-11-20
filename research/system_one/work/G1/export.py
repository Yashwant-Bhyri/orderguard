"""Export T05's exact evaluation set for the GPU zero-shot readers (lead experiment G1).

Rebuilds the records with T05's own sampler and defaults, so the GPU models see the same actions, the same
state the hosted decision model saw, and the same three questions. Labels are NOT exported to the host.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("t05eval", ROOT / "work/T05/evaluate.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
from og_s1.readers import decision  # noqa: E402

SEED, EPF, APE = 20261119, 30, 4          # T05's defaults
records = []
for shifted in (False, True):
    for family in ev.FAMILIES:
        records.extend(ev._sample_file(ROOT / f"data/ref/{family}{'.shifted' if shifted else ''}.jsonl", EPF, APE, SEED))

out = Path(__file__).parent / "items.jsonl"
with out.open("w") as f:
    for i, r in enumerate(records):
        item = r["decision_item"]
        f.write(json.dumps({"i": i, "state": item.get("state"), "questions": decision.QUESTIONS,
                            "support_override": item.get("support_override")}) + "\n")
print(f"exported {len(records)} actions to {out.name}")
