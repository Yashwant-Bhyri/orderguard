"""Coherence report for reference world v2.1, including the binding_error family."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1.coherence import (  # noqa: E402
    FINDING_KINDS,
    _COMPARISON_RE,
    build_context,
    case_for_step,
    coherence,
    finding_kinds,
)
from og_s1.schema import Episode  # noqa: E402
from og_s1.world import BINDING_ERROR, FAMILIES, FAMILIES_V21  # noqa: E402

DATA_DIR = ROOT / "data" / "ref_v21"


def _has_explicit_comparison(action: dict) -> bool:
    texts = [str(action.get("rationale") or "")]
    texts.extend(str(c.get("text") or "") for c in action.get("claims") or [])
    return any(_COMPARISON_RE.search(text) for text in texts)


def main() -> int:
    print("== v2.1 coherence rates per family and split ==")
    print(
        "family,shift,actions,positives,negatives,y0_dirty,y1_dirty,"
        + ",".join(FINDING_KINDS)
    )
    totals = {"y0_dirty": 0, "y1_dirty_nonbinding": 0}
    binding = {}
    for shifted in (False, True):
        label = "shifted" if shifted else "unshifted"
        for family in FAMILIES_V21:
            path = DATA_DIR / f"{family}{'.shifted' if shifted else ''}.jsonl"
            actions = positives = negatives = y0_dirty = y1_dirty = 0
            kinds = Counter()
            if family == BINDING_ERROR:
                binding[(family, shifted)] = {
                    "pos": 0, "pos_missed": 0, "ref_missed": 0,
                    "hard": 0, "hard_dirty": 0, "y0": 0,
                }
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    episode = Episode.from_dict(json.loads(line))
                    ctx = build_context(episode)
                    for i, step in enumerate(episode.steps):
                        fs = coherence(step.action, case_for_step(episode, i, context=ctx))
                        action = step.action.to_dict()
                        actions += 1
                        if step.label.y == 0:
                            negatives += 1
                            y0_dirty += bool(fs)
                            totals["y0_dirty"] += bool(fs)
                            if family == BINDING_ERROR:
                                binding[(family, shifted)]["y0"] += 1
                                if _has_explicit_comparison(action):
                                    binding[(family, shifted)]["hard"] += 1
                                    binding[(family, shifted)]["hard_dirty"] += bool(fs)
                        else:
                            positives += 1
                            y1_dirty += bool(fs)
                            if family != BINDING_ERROR:
                                totals["y1_dirty_nonbinding"] += bool(fs)
                            else:
                                refs = {str(r) for f in fs for r in f.get("refs") or []}
                                if not (refs & set(step.label.cause_refs)):
                                    binding[(family, shifted)]["ref_missed"] += 1
                        for kind in finding_kinds(fs):
                            kinds[kind] += 1
            print(
                f"{family},{label},{actions},{positives},{negatives},{y0_dirty},{y1_dirty},"
                + ",".join(str(kinds.get(k, 0)) for k in FINDING_KINDS)
            )
            if family == BINDING_ERROR:
                entry = binding[(family, shifted)]
                entry["pos"] = positives
                entry["pos_missed"] = positives - y1_dirty

    print("\n== v2.1 pass-bar checks ==")
    clean_ok = totals["y0_dirty"] == 0
    nonbinding_ok = totals["y1_dirty_nonbinding"] == 0
    print(f"clean (all y=0) actions with any finding: {totals['y0_dirty']} -> {'PASS' if clean_ok else 'FAIL'}")
    print(f"non-binding y=1 actions with any finding: {totals['y1_dirty_nonbinding']} -> {'PASS' if nonbinding_ok else 'FAIL'}")
    overall = clean_ok and nonbinding_ok
    print("binding,shift,positives,recall,hard_negatives,false_positives,fpr,cause_refs_missed")
    for shifted in (False, True):
        label = "shifted" if shifted else "unshifted"
        entry = binding[(BINDING_ERROR, shifted)]
        recall = (entry["pos"] - entry["pos_missed"]) / entry["pos"] if entry["pos"] else 0.0
        fpr = entry["hard_dirty"] / entry["hard"] if entry["hard"] else 0.0
        print(
            f"binding_error,{label},{entry['pos']},{recall:.4f},"
            f"{entry['hard']},{entry['hard_dirty']},{fpr:.4f},{entry['ref_missed']}"
        )
        if entry["pos"] < 2000:
            overall = False
        if entry["hard"] < 0.20 * entry["pos"]:
            overall = False
        if recall < 0.95 or fpr > 0.05:
            overall = False
        if entry["ref_missed"]:
            overall = False
    refs_missed = sum(binding[(BINDING_ERROR, s)]["ref_missed"] for s in (False, True))
    print(f"binding_error positives whose findings miss cause_refs: {refs_missed} -> "
          f"{'PASS' if refs_missed == 0 else 'FAIL'}")
    print("\n== binding_error hard-negative share ==")
    print("shift,actions,positives,hard_negatives,hard_per_positive,hard_per_action")
    for shifted in (False, True):
        label = "shifted" if shifted else "unshifted"
        entry = binding[(BINDING_ERROR, shifted)]
        per_pos = entry["hard"] / entry["pos"] if entry["pos"] else 0.0
        per_action = entry["hard"] / 24000
        print(
            f"{label},24000,{entry['pos']},{entry['hard']},"
            f"{per_pos:.4f},{per_action:.4f}"
        )
    print(f"V2.1 PASS BAR: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
