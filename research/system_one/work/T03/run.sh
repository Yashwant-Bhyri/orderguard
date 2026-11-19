#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TASK_DIR/../.."
LOG="$TASK_DIR/check.log"

if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
{
    echo "== T03 code checks v2: captured run $RUN_ID =="
    echo "== T03 tests =="
    "$PY" -m pytest og_s1/tests/test_checks.py -q -p no:cacheprovider -p no:dash

    echo "== full repository tests =="
    "$PY" -m pytest og_s1/tests -q -p no:cacheprovider -p no:dash

    echo "== reference evaluation =="
    "$PY" work/T03/evaluate.py
    echo "== end captured run $RUN_ID =="
} 2>&1 | tee -a "$LOG"
