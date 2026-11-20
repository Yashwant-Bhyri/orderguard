"""Check that the default generator still reproduces data/ref byte for byte."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1.world import FAMILIES, simulate  # noqa: E402

DATA_DIR = ROOT / "data" / "ref"
N_PER_FAMILY = 200


def main() -> int:
    checked = 0
    mismatches = []
    for fi, family in enumerate(FAMILIES):
        for shifted in (False, True):
            path = DATA_DIR / f"{family}{'.shifted' if shifted else ''}.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            for i in range(N_PER_FAMILY):
                expected = lines[i].strip()
                got = json.dumps(
                    simulate(fi * 1000 + i, family, n_steps=120, shifted=shifted).to_dict()
                )
                checked += 1
                if got != expected:
                    mismatches.append((family, shifted, i))
    print(f"v2 byte-for-byte: {checked - len(mismatches)}/{checked} episodes identical")
    for item in mismatches[:10]:
        print("MISMATCH", item)
    print(f"V2 REPRODUCTION: {'PASS' if not mismatches else 'FAIL'}")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
