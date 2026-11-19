#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TASK_DIR/../.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
LOG="$TASK_DIR/check.log"

# Keep generated caches out of the task folder: they embed absolute paths.
find "$TASK_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +

if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
{
    echo "== T14 taint propagation: captured run $RUN_ID =="

    echo "== T03 regression tests =="
    "$PY" -m pytest og_s1/tests/test_checks.py -q -p no:cacheprovider -p no:dash

    echo "== T14 taint tests =="
    "$PY" -m pytest work/T14/test_taint.py -q -p no:cacheprovider -p no:dash

    echo "== T14 reference evaluation =="
    "$PY" work/T14/evaluate.py

    echo "OVERALL: PASS (both pytest suites and the gate exited 0)"
    echo "== end captured run $RUN_ID =="
} 2>&1 | tee -a "$LOG"
