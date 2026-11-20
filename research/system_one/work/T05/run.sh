#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TASK_DIR/../.."
LOG="$TASK_DIR/check.log"
TMP_LOG="$TASK_DIR/.check.log.tmp"
LOCK="$TASK_DIR/.runlock"

# One writer only: a second concurrent run would interleave two log tails.
if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -f "$LOCK/pid" ] && kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null; then
        echo "run.sh is already running (pid $(cat "$LOCK/pid")); refusing to start a second writer" >&2
        exit 1
    fi
    rm -rf "$LOCK"
    mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"
cleanup() {
    rm -rf "$LOCK"
    rm -f "$TMP_LOG"
}
trap cleanup EXIT INT TERM

if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi

mkdir -p work/T05/train_text work/T05/cache work/T05/runs data/models/hf
: > "$TMP_LOG"

# The harness may capture stdout to check.log itself.  Write our own capture to
# a temp file and move it into place after the pipeline finishes, so the final
# artifact has exactly one writer and cannot grow a duplicated tail.
{
    echo "== T05 bounded text channel: single captured run =="
    echo "== environment =="
    if ! "$PY" - <<'PY'
import importlib.util
mods = ["numpy", "sklearn", "joblib", "torch", "transformers", "sentence_transformers", "huggingface_hub", "pytest"]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
print("missing:", missing)
raise SystemExit(1 if missing else 0)
PY
    then
        echo "installing missing packages into the lab venv"
        "$PY" -m pip install --disable-pip-version-check torch transformers sentence-transformers scikit-learn joblib huggingface-hub pytest
    fi
    "$PY" -m pip freeze 2>/dev/null | grep -Ei '^(numpy|scipy|scikit-learn|joblib|torch|transformers|sentence-transformers|huggingface-hub|pytest)=' || true

    echo "== model cache =="
    "$PY" work/T05/fetch_models.py

    echo "== verify frozen authority candidates =="
    "$PY" work/T05/preregister.py --check

    echo "== build training text =="
    "$PY" work/T05/make_train_text.py --out work/T05/train_text

    echo "== training/ref leakage audit =="
    "$PY" work/T05/check_train_leakage.py \
        --train work/T05/train_text/train_text.jsonl \
        --data-dir data/ref \
        --out work/T05/leakage.json

    echo "== train reader 3 (MiniLM + logistic regression) =="
    "$PY" work/T05/train_embed.py --train work/T05/train_text/train_text.jsonl --out work/T05/embed_lr.joblib

    echo "== reader tournament and latency on reference corpora =="
    "$PY" work/T05/evaluate.py \
        --data-dir data/ref \
        --episodes-per-file 30 \
        --actions-per-episode 4 \
        --seed 20261119 \
        --bootstrap 1000 \
        --workers 4 \
        --out work/T05/results.json \
        --table work/T05/table.md

    echo "== generated numbers and REPORT numeric block =="
    "$PY" work/T05/report_numbers.py

    echo "== tests (online) =="
    "$PY" -m pytest og_s1/tests/test_text.py -q -p no:cacheprovider -p no:dash

    echo "== tests (offline model cache) =="
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
        "$PY" -m pytest og_s1/tests/test_text.py -q -p no:cacheprovider -p no:dash

    echo "== offline import =="
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
        "$PY" -c "import og_s1.text; print('og_s1.text imports offline')"
} 2>&1 | tee "$TMP_LOG"

mv "$TMP_LOG" "$LOG"
echo "wrote $LOG"
