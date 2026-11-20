#!/usr/bin/env bash
# Reproduce the whole corpus, validate it, print every REPORT.md number, and
# leave the same output in check.log.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

mkdir -p out
{
  "$PY" generate_all.py --out out/redteam.jsonl --attack-n 65 --benign-n 20
  "$PY" -m og_s1.validate out/redteam.jsonl
  "$PY" check_determinism.py out/redteam.jsonl
  "$PY" stats.py out/redteam.jsonl
} 2>&1 | tee check.log
