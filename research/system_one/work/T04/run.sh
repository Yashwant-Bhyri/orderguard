#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TASK_DIR/../.."
LOG="$TASK_DIR/check.log"
RUN_START="$(date +%s)"

if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export PYTHONHASHSEED=0

{
    echo "== T04 captured run $(date -u +%Y%m%dT%H%M%SZ) =="
    echo "== tests =="
    "$PY" -m pytest og_s1/tests/test_models_eval.py -q -p no:cacheprovider -p no:dash

    echo "== build tiny fake --test directory from held-out reference episodes =="
    "$PY" "$TASK_DIR/make_fake_test.py"

    echo "== full reference evaluation (5 seeds, 1000 episode bootstraps) =="
    "$PY" -m og_s1.evaluate \
        --train data/ref \
        --test data/ref \
        --out "$TASK_DIR/results_ref.json"

    echo "== new --test directory needs no code change =="
    "$PY" -m og_s1.evaluate \
        --train data/ref \
        --test "$TASK_DIR/fake_test" \
        --out "$TASK_DIR/fake_test_results.json" \
        --seeds 1 \
        --bootstrap 50 \
        --max-train-episodes 40 \
        --max-cal-episodes 40 \
        --max-test-episodes 5 \
        --quiet

    echo "== reproduced results table =="
    cat "$TASK_DIR/results_ref.md"
    echo "== fake test table =="
    cat "$TASK_DIR/fake_test_results.md"

    RUN_END="$(date +%s)"
    "$PY" - "$RUN_START" "$RUN_END" "$TASK_DIR/run_meta.json" <<'PYEOF'
import json
import sys

start, end, path = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
with open(path, "w", encoding="utf-8") as handle:
    json.dump(
        {"run_start": start, "run_end": end, "elapsed_seconds": end - start},
        handle,
        indent=2,
    )
    handle.write("\n")
print(f"entry point elapsed: {end - start} s")
PYEOF

    echo "== regenerate REPORT.md from the JSON =="
    "$PY" "$TASK_DIR/build_report.py"
} 2>&1 | tee -a "$LOG"
