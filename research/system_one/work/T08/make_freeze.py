#!/usr/bin/env python3
"""Write holdout_freeze.json for the current rule.

The round-3 rule was frozen before 2026q1 was first scored. Round 4 changed
the rule after that score (EP handling, money-market category, reporting), so
this manifest proves only that the current run uses the current code; it does
not prove the current rule predates 2026q1. The round-3 manifest is preserved
as freeze_round3.json. Run this by hand after the last edit to names.py or
score.py, then run run.sh.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha256(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    man = {
        "frozen_at_utc": now,
        "note": ("Round-4 rule. The round-3 rule was frozen before 2026q1 was "
                 "first scored; round 4 changed the rule after that score, so "
                 "2026q1 is a frozen-rule score of the same funds, not a held-out "
                 "evaluation. This manifest proves only that the current run "
                 "uses the current names.py and score.py. The round-3 manifest "
                 "is freeze_round3.json."),
        "files": {name: sha256(HERE / name) for name in ("names.py", "score.py")},
    }
    (HERE / "holdout_freeze.json").write_text(json.dumps(man, indent=2) + "\n")
    print("wrote holdout_freeze.json", man["files"])


if __name__ == "__main__":
    main()
