#!/bin/sh
set -eu
TASK_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$TASK_DIR"
PYTHON="$TASK_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON=python3; fi
export PYTHONDONTWRITEBYTECODE=1
START=$(date +%s)
"$PYTHON" -B -c 'import pathlib, shutil; [shutil.rmtree(p) for p in pathlib.Path(".").rglob("__pycache__")]'
mkdir -p out
"$PYTHON" -B -m generator out/episodes.jsonl 150
"$PYTHON" -B -m og_s1.validate out/episodes.jsonl
"$PYTHON" -B audit.py out/episodes.jsonl
"$PYTHON" -B check_sweep.py
"$PYTHON" -B -c 'import pathlib, sys; caches=list(pathlib.Path(".").rglob("__pycache__")); bytecode=list(pathlib.Path(".").rglob("*.pyc")); print(f"bytecode audit: cache_dirs={len(caches)} pyc_files={len(bytecode)}"); sys.exit(bool(caches or bytecode))'
END=$(date +%s)
echo "elapsed_seconds=$((END - START))"
