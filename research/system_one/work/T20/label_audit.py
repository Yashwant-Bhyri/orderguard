"""Audit the rule labels (blind-checked) against the reference hypothesis (diagnostic only).

The labels in ``handlabels.jsonl`` never read ``step.label.cause``.  This script
reports where the content reading and the generator's hypothesis differ, and how
the sector-scoped stale trigger relates to the thesis instrument.  It is printed
by ``run.sh`` so the report's audit numbers reproduce.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

TASK = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK))

import handcheck as h  # noqa: E402


def main() -> None:
    handset = [json.loads(line) for line in (Path(__file__).resolve().parents[2] / "data" / "t20" / "handset.jsonl").open(encoding="utf-8") if line.strip()]
    handcheck = json.loads((TASK / "handcheck.json").read_text(encoding="utf-8"))
    raw = h.load_raw()

    agree = Counter()
    total = Counter()
    disagreements = []
    stale_same = 0
    stale_other = 0
    stale_unknown = 0
    stale_total = 0
    for item in handset:
        if item["kind"] != "ref_action":
            continue
        item_id = item["id"]
        _, name, ei, si = item_id.split(":")
        ei, si = int(ei), int(si)
        episode = raw[(name, ei, si)]
        step = episode["steps"][si]
        cause = str(step["label"]["cause"])
        total[cause] += 1
        row = handcheck[item_id]
        if row["content_truth"] == int(step["label"]["y"]):
            agree[cause] += 1
        else:
            disagreements.append(
                {
                    "id": item_id,
                    "reference_y": int(step["label"]["y"]),
                    "reference_cause": cause,
                    "content_y": row["content_truth"],
                    "labels": row["labels"],
                    "basis": row["label_basis"],
                }
            )
        if cause == "stale_thesis":
            stale_total += 1
            docs, _ = h.docs_and_notes(h.model_view_at(h.Episode.from_dict(episode), si))
            thesis = next(
                (t for t in episode.get("theses") or [] if t.get("id") == step["action"].get("thesis_id")),
                None,
            )
            if thesis is None:
                stale_unknown += 1
                continue
            thesis_insts = h.thesis_instruments(thesis, docs)
            ref_ids = [str(x) for x in step["label"].get("cause_refs") or []]
            trigger_docs = [d for d in episode.get("documents") or [] if str(d.get("id")) in ref_ids]
            trigger_insts = set()
            for doc in trigger_docs:
                trigger_insts |= h.instruments_in_text(doc.get("text"))
            if trigger_insts & thesis_insts:
                stale_same += 1
            elif trigger_insts:
                stale_other += 1
            else:
                stale_unknown += 1

    print("== label audit (rule labels (blind-checked) vs reference hypothesis) ==")
    for cause in sorted(total):
        print(f"{cause}: {agree[cause]}/{total[cause]} agree")
    print(f"disagreements: {len(disagreements)}")
    for row in disagreements:
        print(
            f"  {row['id']}: reference y={row['reference_y']} ({row['reference_cause']}), "
            f"content y={row['content_y']}, labels={row['labels']}; {row['basis']}"
        )
    print(
        "stale-thesis sample: "
        f"{stale_total} actions; trigger document names the thesis instrument "
        f"{stale_same}, a different instrument {stale_other}, unknown {stale_unknown}"
    )


if __name__ == "__main__":
    main()
