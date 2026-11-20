#!/usr/bin/env bash
# Reproduce the whole dataset and every number in REPORT.md.
set -uo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi

status=0
rm -rf out
rm -rf __pycache__ og_s1/__pycache__
mkdir -p out
"$PY" generate_dataset.py --n 150 --out out/episodes.jsonl || status=1
"$PY" -m og_s1.validate out/episodes.jsonl || status=1
"$PY" check_variety.py out/episodes.jsonl || status=1
"$PY" check_hard_negatives.py out/episodes.jsonl || status=1
"$PY" check_facts.py out/episodes.jsonl || status=1
"$PY" probe.py --n 1000 || status=1
"$PY" -c 'import hashlib,sys; print("sha256:", hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' out/episodes.jsonl || status=1
find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
exit "$status"
