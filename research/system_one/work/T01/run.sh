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

DATA=data/ref
mkdir -p "$DATA"

{
    echo "== T01 world v2 single captured run =="
    echo "== generate =="
    "$PY" -m og_s1.generate --out "$DATA" --n-per-family 200 --n-steps 120

    echo "== validate =="
    "$PY" -m og_s1.validate "$DATA"

    echo "== tests =="
    "$PY" -m pytest og_s1/tests -q -p no:cacheprovider -p no:dash
} 2>&1 | tee "$LOG"
