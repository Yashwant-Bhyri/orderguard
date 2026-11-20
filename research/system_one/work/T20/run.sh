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

export PYTHONDONTWRITEBYTECODE=1
mkdir -p work/T20/cache data/t20
rm -rf work/T20/__pycache__

{
    echo "== T20 hosted decision-model triage: offline re-score =="
    echo "== 200-item set =="
    "$PY" work/T20/build_handset.py

    echo "== item-level rule labels (blind-checked) =="
    "$PY" work/T20/handcheck.py

    echo "== label audit against the reference hypothesis =="
    "$PY" work/T20/label_audit.py

    echo "== auxiliary-hint-free variant =="
    "$PY" work/T20/build_blind.py

    echo
    echo "== both rule-label vs blind-label checks, and the 60 blind items =="
    "$PY" work/T20/blind_check.py

    echo "== primary comparison table, catalog and recommendation (from cache) =="
    "$PY" work/T20/score.py

    echo
    echo "== blind comparison table and recommendation (from cache) =="
    "$PY" work/T20/score.py \
        --handset data/t20_blind/handset_blind.jsonl \
        --cache work/T20/cache/triage_blind.jsonl \
        --out work/T20/results_blind.json \
        --table work/T20/table_blind.md \
        --title "T20 comparison - rule labels (blind-checked), auxiliary-hint-free model input"

    echo "== total final-cache spend =="
    "$PY" - <<'PY'
import json
from pathlib import Path
primary = json.loads(Path("work/T20/results.json").read_text())
blind = json.loads(Path("work/T20/results_blind.json").read_text())
a = primary["cache_cost_usd"]
b = blind["cache_cost_usd"]
g = primary["global_cache_cost_usd"]
print(f"primary file ${a:.6f} + blind file ${b:.6f} = ${a + b:.6f}")
print(f"lifetime total across {', '.join(Path(p).name for p in primary['cache_files'])}: ${g:.6f} (cap $5)")
PY

    echo "== offline tests: recorded responses, no network =="
    "$PY" -m pytest work/T20/test_triage.py -q -p no:cacheprovider -p no:dash
    rm -rf work/T20/__pycache__
} 2>&1 | tee "$LOG"

# The reviewer found a duplicated log in round 5.  Check both markers, and a
# third section marker, after writing the log, so a second writer cannot pass
# silently.
headers=$(grep -c '^== T20 hosted decision-model triage' "$LOG" || true)
passes=$(grep -c '9 passed' "$LOG" || true)
spends=$(grep -c '^== total final-cache spend' "$LOG" || true)
if [ "$headers" -ne 1 ] || [ "$passes" -ne 1 ] || [ "$spends" -ne 1 ]; then
    echo "check.log is not a single clean run: headers=$headers passed=$passes spend=$spends" >&2
    exit 1
fi
echo "log check: headers=$headers passed=$passes spend-sections=$spends"

"$PY" work/T20/check_size.py
