"""Build a tiny unshifted test world from held-out reference episodes.

The split mirrors ``og_s1.evaluate.split_records`` but reads only metadata, so
the demo does not need to featurise the whole reference corpus first.  The five
chosen episodes are drawn from the evaluator's test split, never from train or
calibration.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from og_s1.evaluate import PREVIOUS_SPLIT_SEED, split_records

TASK = Path(__file__).resolve().parent
ROOT = TASK.parent.parent
DATA = ROOT / "data" / "ref"
OUT = TASK / "fake_test"


def main() -> int:
    items = []
    locations = {}
    for path in sorted(DATA.glob("*.jsonl")):
        if ".shifted" in path.name:
            continue
        with open(path, "r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle):
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                family = str((raw.get("meta") or {}).get("family", "unknown"))
                key = f"{path.resolve()}::{line_no}"
                items.append(SimpleNamespace(key=key, family=family))
                locations[key] = (path, line)
    previous_test_keys = {
        item.key for item in split_records(items, seed=PREVIOUS_SPLIT_SEED)["test"]
    }
    splits = split_records(items, avoid_test_keys=previous_test_keys)
    test = sorted(splits["test"], key=lambda item: item.key)
    chosen = []
    seen = set()
    for item in test:
        if item.family == "clean" and "clean" not in seen:
            chosen.append(item)
            seen.add("clean")
    for item in test:
        if len(chosen) >= 5:
            break
        if item.family not in seen:
            chosen.append(item)
            seen.add(item.family)
    for item in test:
        if len(chosen) >= 5:
            break
        if item not in chosen:
            chosen.append(item)
    chosen = chosen[:5]

    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.jsonl"):
        stale.unlink()
    target = OUT / "ref_copy.jsonl"
    with open(target, "w", encoding="utf-8") as handle:
        for item in chosen:
            path, line = locations[item.key]
            handle.write(line.rstrip("\n") + "\n")
    print(f"wrote {target.relative_to(ROOT)} with {len(chosen)} episodes: {[item.family for item in chosen]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
