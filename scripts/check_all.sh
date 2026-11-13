#!/usr/bin/env bash
# One command for everything a reviewer needs, offline: python tests, lab tables and sandbox manifest checks, the TypeScript receiver
# checks (unit, quickstart, 1,000-seed invariants) and the secret scan. Prints PASS/FAIL per step with timings; exits non-zero if any step fails.
#
#   bash scripts/check_all.sh              run every step
#   CHECK_ALL_SKIP="npm" bash scripts/check_all.sh    skip steps whose name contains a word in the list (e.g. no node installed)
#   CHECK_ALL_VERBOSE=1 bash scripts/check_all.sh     stream each step's output instead of keeping it for failures only
set -u
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

if [ -x "$root/.venv/bin/python" ]; then PY="$root/.venv/bin/python"; else PY="${PYTHON:-python3}"; fi
if [ -x "$root/.venv/bin/og-lab" ]; then OGLAB="$root/.venv/bin/og-lab"; else OGLAB="og-lab"; fi

export OG_LLM=replay                      # no live model call can happen: a request without a recording raises
export OG_LAB_L6=facts                    # lab figure checks use the bundled SEC facts, never the network
export PYTHONDONTWRITEBYTECODE=1

log=$(mktemp -d "${TMPDIR:-/tmp}/og-check.XXXXXX")
trap 'rm -rf "$log"' EXIT

names=(); results=(); times=(); fail=0

skipped() {
  for w in ${CHECK_ALL_SKIP:-}; do case "$1" in *"$w"*) return 0 ;; esac; done
  return 1
}

step() {            # step "name" command...
  local name="$1"; shift
  if skipped "$name"; then names+=("$name"); results+=("SKIP"); times+=("-"); return; fi
  printf '\n== %s\n' "$name"
  local t0=$SECONDS rc=0 out="$log/$(printf '%s' "$name" | tr -c 'A-Za-z0-9' '_').log"
  if [ -n "${CHECK_ALL_VERBOSE:-}" ]; then "$@" 2>&1 | tee "$out"; rc=${PIPESTATUS[0]}; else "$@" >"$out" 2>&1 || rc=$?; fi
  local dt=$((SECONDS - t0))
  names+=("$name"); times+=("${dt}s")
  if [ "$rc" -eq 0 ]; then results+=("PASS"); tail -n 2 "$out" | sed 's/^/   /'
  else results+=("FAIL"); fail=1; tail -n 25 "$out" | sed 's/^/   /'; fi
}

step "pytest (all python tests)"           "$PY" -m pytest -q -p no:cacheprovider
step "og-lab tables --check"               "$OGLAB" tables --check
step "og-lab sandbox describe --check"     "$OGLAB" sandbox describe --check
step "npm run check (receiver, invariants, scan)"  npm run --silent check
step "secret scan (scan_committable.sh)"   sh scripts/scan_committable.sh

printf '\n%-52s %-6s %s\n' "STEP" "RESULT" "TIME"
printf '%-52s %-6s %s\n' "----------------------------------------------------" "------" "-----"
for i in "${!names[@]}"; do printf '%-52s %-6s %s\n' "${names[$i]}" "${results[$i]}" "${times[$i]}"; done
if [ "$fail" -eq 0 ]; then echo; echo "ALL CHECKS PASSED"; else echo; echo "SOME CHECKS FAILED"; fi
exit "$fail"
