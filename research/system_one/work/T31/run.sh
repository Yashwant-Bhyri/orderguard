#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TASK_DIR/../.."
LOG="$TASK_DIR/check.log"
LOCK="$TASK_DIR/.run.lock"
TMP_LOG="$TASK_DIR/.check.log.$$"

if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi

if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -f "$LOCK/pid" ] && kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then
        echo "run.sh is already running (pid $(cat "$LOCK/pid")); refusing to run concurrently" >&2
        exit 1
    fi
    rm -rf "$LOCK"
    mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"
cleanup() {
    rm -f "$TMP_LOG"
    rm -rf "$LOCK"
}
trap cleanup EXIT

{
    echo "== T31 binding coherence: single captured run =="
    echo "== 1. v2 byte-for-byte reproduction =="
    "$PY" work/T31/verify_v2.py

    echo
    echo "== 2. generate reference world v2.1 (same seeds, sizes and splits as v2) =="
    "$PY" -m og_s1.generate --out data/ref_v21 --n-per-family 200 --coherent

    echo
    echo "== 2b. disk use of generated corpus =="
    du -sh data/ref_v21 | sed 's/^/data\/ref_v21: /'

    echo
    echo "== 3. validate v2.1 =="
    "$PY" -m og_s1.validate data/ref_v21

    echo
    echo "== 4. v2 coherence rates and T03 re-score =="
    "$PY" work/T31/rescore_t03.py

    echo
    echo "== 5. v2.1 coherence and binding_error pass-bar checks =="
    "$PY" work/T31/analyze_v21.py

    echo
    echo "== 6. T05 registered-reader re-score =="
    echo "(the external decision model is read from T05's on-disk cache; no network call)"
    "$PY" work/T31/rescore_t05.py

    echo
    echo "== 7. full test suite =="
    "$PY" -m pytest og_s1/tests -q -p no:cacheprovider -p no:dash
} 2>&1 | tee "$TMP_LOG"

echo "== 8. capture integrity ==" | tee -a "$TMP_LOG"
"$PY" - "$TMP_LOG" <<'PY' | tee -a "$TMP_LOG"
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
headings = [
    "== 1. v2 byte-for-byte reproduction ==",
    "== 2. generate reference world v2.1",
    "== 2b. disk use of generated corpus ==",
    "== 3. validate v2.1 ==",
    "== 4. v2 coherence rates and T03 re-score ==",
    "== 5. v2.1 coherence and binding_error pass-bar checks ==",
    "== 6. T05 registered-reader re-score ==",
    "== 7. full test suite ==",
    "== 8. capture integrity ==",
]
bad = [(h, text.count(h)) for h in headings if text.count(h) != 1]
print(f"section headings appearing exactly once: {len(headings) - len(bad)}/{len(headings)}")
for heading, count in bad:
    print(f"DUPLICATE OR MISSING: {count} x {heading}")
print(f"CAPTURE INTEGRITY: {'PASS' if not bad else 'FAIL'}")
raise SystemExit(0 if not bad else 1)
PY

mv "$TMP_LOG" "$LOG"
echo "wrote single capture: $LOG"
