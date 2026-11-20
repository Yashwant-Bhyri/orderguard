#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Never leave bytecode behind: a stale .pyc can contain an absolute home path,
# and the privacy scan must find nothing because nothing is there.
export PYTHONDONTWRITEBYTECODE=1
rm -rf __pycache__

# 2026q1 is the frozen-rule score (same funds as the exploratory quarter), not
# an evaluation: the lead ruling of 2026-11-19 settles that. 2026q2 is
# exploratory: one classifier edge case was corrected after seeing a 2026q2
# sample row in round 2.
PRIMARY="${PRIMARY_QUARTER:-2026q1}"
EXPLORATORY="${EXPLORATORY_QUARTER:-2026q2}"

PY="../../.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

FORCE_FLAG=""
if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  FORCE_FLAG="--force"
fi

{
  "$PY" download.py --quarter "$EXPLORATORY" $FORCE_FLAG
  "$PY" download.py --quarter "$PRIMARY" $FORCE_FLAG

  "$PY" score.py --quarter "$EXPLORATORY" --role exploratory \
    --out-suffix _exploratory
  "$PY" score.py --quarter "$PRIMARY" --role frozen_rule \
    --out-suffix "" --require-freeze

  "$PY" test_names.py
  "$PY" test_share.py
  "$PY" test_sampling.py
  "$PY" test_edgar.py
  "$PY" overlap.py
  "$PY" check_privacy.py
  "$PY" verify_edgar.py || echo "verify_edgar.py reported a live-check failure (expected only without a contact User-Agent)"
  "$PY" report.py
} 2>&1 | tee check.log
