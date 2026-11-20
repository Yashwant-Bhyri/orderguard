#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TASK_DIR/../.."

# Never write bytecode: compiled files embed the absolute workspace path.
export PYTHONDONTWRITEBYTECODE=1

CAPTURES="$TASK_DIR/captures"
mkdir -p "$CAPTURES"
LOCK="$CAPTURES/.lock"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
CAPTURE="$CAPTURES/$RUN_ID.log"

# Acquire the capture lock.  A run killed with SIGKILL leaves the directory
# behind, so a lock is honored only while the PID recorded inside it is alive.
# A legacy lock with no pid file is treated as stale: the old script never
# wrote one, and treating it as live would make the folder permanently
# unreproducible (the round-4 REVISE).
acquire_lock() {
    local holder=""
    if mkdir "$LOCK" 2>/dev/null; then
        printf '%s\n' "$$" > "$LOCK/pid"
        return 0
    fi
    if [ -f "$LOCK/pid" ]; then
        holder="$(cat "$LOCK/pid" 2>/dev/null || true)"
    fi
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
        echo "another T15 run (pid $holder) holds work/T15/captures/.lock; refusing to interleave captures" >&2
        return 1
    fi
    echo "removing stale T15 lock at work/T15/captures/.lock (holder pid ${holder:-unknown} is not alive)" >&2
    rm -rf "$LOCK"
    if mkdir "$LOCK" 2>/dev/null; then
        printf '%s\n' "$$" > "$LOCK/pid"
        return 0
    fi
    echo "could not acquire work/T15/captures/.lock after clearing a stale lock" >&2
    return 1
}

if ! acquire_lock; then
    exit 75
fi
cleanup() { rm -rf "$LOCK"; }
trap cleanup EXIT INT TERM

if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi

# Remove stale bytecode so the path check cannot pass on an old cache.
find "$TASK_DIR" og_s1 -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

{
    echo "== T15 frozen evaluation bench: captured run $RUN_ID =="
    echo "== spec hash (before) =="
    "$PY" -c 'from og_s1.eval import spec_hash; print(spec_hash())'

    echo "== T15 tests =="
    "$PY" -m pytest work/T15/tests/test_eval.py -q -p no:cacheprovider -p no:dash

    echo "== T15 bench =="
    "$PY" work/T15/evaluate.py "$@"

    echo "== spec hash (after) =="
    "$PY" -c 'from og_s1.eval import spec_hash; print(spec_hash())'

    # Remove any bytecode the test/bench imports created before scanning: a
    # __pycache__ entry embeds the absolute workspace path.
    find "$TASK_DIR" og_s1 -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

    echo "== artifact check (absolute home paths, oversized files) =="
    "$PY" work/T15/check_artifacts.py

    echo "capture_file ${CAPTURE#"$TASK_DIR"/}"
    echo "== end captured run $RUN_ID =="
} 2>&1 | tee "$CAPTURE"

# One pointer line per clean capture; the per-run file is the immutable record.
# Never write an index line with an empty hash if the interpreter is killed
# while the line is being assembled.
FINAL_SPEC="$("$PY" -c 'from og_s1.eval import spec_hash; print(spec_hash())' 2>/dev/null || true)"
if [ -n "$FINAL_SPEC" ]; then
    printf '%s capture=%s spec_sha256=%s\n' \
        "$RUN_ID" "${CAPTURE#"$TASK_DIR"/}" "$FINAL_SPEC" \
        >> "$TASK_DIR/check.log"
else
    echo "spec hash unavailable; not indexing capture ${CAPTURE#"$TASK_DIR"/}" >&2
fi
