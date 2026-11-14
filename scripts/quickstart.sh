#!/bin/sh
# OrderGuard first run: venv, install, init, doctor, offline tests, then the dashboard.
# Safe to re-run: every step skips work that is already done.
#
#   sh scripts/quickstart.sh [--port N] [--no-serve] [--skip-tests] [--skip-node]
#
# No API key is needed. The app defaults to replay mode (OG_LLM=replay): no model call, no spend.
set -eu

PORT=8600
SERVE=1
TESTS=1
NODE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:?--port needs a number}"; shift ;;
    --no-serve) SERVE=0 ;;
    --skip-tests) TESTS=0 ;;
    --skip-node) NODE=0 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

step() { printf '\n==> %s\n' "$1"; }
die() { printf '\nERROR: %s\n' "$1" >&2; [ -n "${2:-}" ] && printf 'How to fix: %s\n' "$2" >&2; exit 1; }

# ---- 1. prerequisites -------------------------------------------------------------------------------------------------
step "Checking prerequisites"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
[ -n "$PY" ] || die "Python 3.11 or newer was not found." "install it from https://www.python.org/downloads/ (macOS: brew install python@3.12; Debian/Ubuntu: apt install python3.12 python3.12-venv), then run this script again."
"$PY" -c 'import venv, ensurepip' 2>/dev/null || die "Python's venv module is missing." "Debian/Ubuntu: apt install python3-venv (match your Python version)."
echo "python: $("$PY" --version 2>&1)"

if [ "$NODE" = 1 ]; then
  command -v node >/dev/null 2>&1 || die "Node.js was not found; the L8 receiver and its tests need Node 22.13 or newer." "install it from https://nodejs.org/ (macOS: brew install node), or re-run with --skip-node to use the Python parts only."
  node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22&&b>=13)?0:1)' \
    || die "Node $(node --version) is too old; 22.13 or newer is required." "upgrade Node (nvm install 22), or re-run with --skip-node."
  command -v npm >/dev/null 2>&1 || die "npm was not found next to node." "reinstall Node from https://nodejs.org/."
  echo "node: $(node --version)"
else
  echo "node: skipped (--skip-node): the receiver and TypeScript tests will not run"
fi

# ---- 2. python environment ----------------------------------------------------------------------------------------------
step "Python environment (.venv)"
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv || die "could not create .venv." "check disk space and permissions in $root."
  echo "created .venv"
else
  echo ".venv already exists"
fi
if [ ! -x .venv/bin/orderguard ] || { [ -f .venv/.og-installed ] && [ pyproject.toml -nt .venv/.og-installed ]; }; then
  echo "installing OrderGuard (this can take a minute)..."
  .venv/bin/python -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  if .venv/bin/python -m pip install --quiet -e '.[dev]'; then
    :
  elif [ -x .venv/bin/orderguard ] && .venv/bin/python -c 'import orderguard_guard, orderguard_app, fastapi' 2>/dev/null; then
    # A refresh that cannot reach the package index (offline, proxy, TLS inspection) must not block a working install.
    echo "WARNING: could not refresh the install (no route to the package index?); continuing with the existing one." >&2
    echo "         To force a clean reinstall later: rm -rf .venv and re-run this script with network access." >&2
  else
    die "pip install failed." "check your network connection (pip needs to download packages; behind a proxy set HTTPS_PROXY, and for TLS errors check your certificates), then re-run this script."
  fi
  : > .venv/.og-installed
else
  : > .venv/.og-installed
  echo "already installed (delete .venv/.og-installed and touch pyproject.toml to force a reinstall)"
fi

if [ "$NODE" = 1 ]; then
  step "Receiver dependencies (npm ci)"
  if [ -d node_modules ] && [ node_modules -nt package-lock.json ]; then echo "node_modules is up to date"
  else npm ci --no-audit --no-fund --loglevel=error || die "npm ci failed." "check your network connection, then re-run."; touch node_modules; fi
fi

# ---- 3. config --------------------------------------------------------------------------------------------------------
step "Configuration (orderguard init)"
home="${ORDERGUARD_HOME:-var/orderguard}"
if [ -f "$home/signing.key" ] && [ -f "$home/mandate.json" ]; then
  echo "found an existing configuration in $home: leaving it alone (your signing key is never overwritten)"
else
  .venv/bin/orderguard init || die "orderguard init failed." "read the message above; use --force only if you accept losing the old signing key."
fi

step "Health check (orderguard doctor)"
if .venv/bin/orderguard doctor; then :; else
  echo
  echo "Doctor reported problems. For a first run these are usually fine:"
  echo "  - a missing provider key or app token only matters for live model calls or non-local use"
  echo "  - docs/GUIDE.md (Troubleshooting) explains each message"
fi

# ---- 4. offline tests -------------------------------------------------------------------------------------------------
if [ "$TESTS" = 1 ]; then
  step "Offline test suite (replay mode, no network, no spend)"
  OG_LLM=replay .venv/bin/python -m pytest -q \
    || die "the offline tests failed." "this is unexpected on a clean checkout; open an issue with the output above, or re-run with --skip-tests to continue."
else
  echo; echo "tests skipped (--skip-tests)"
fi

# ---- 5. next steps and serve --------------------------------------------------------------------------------------------
cat <<MSG

==> Ready

  Dashboard:   http://127.0.0.1:$PORT   (this machine only; replay mode, no model calls)
  Next steps:
    1. Open the dashboard and try "Check order" with the fake 10-for-1 split example.
    2. Edit $home/mandate.json (limits, symbols, referencePrices), then: .venv/bin/orderguard init --resign
    3. For live model calls, put a provider key in $home/.env (names only are listed there), set OG_LLM=live and a low OG_BUDGET_USD.
    4. Run the receiver: node receiver/bridge/serve.mjs --port 8700 --mandate $home/mandate.json
       then export ORDERGUARD_RECEIVER_URL=http://127.0.0.1:8700 before serving.
    5. Read docs/GUIDE.md.

MSG
if [ "$SERVE" = 1 ]; then
  echo "Starting the dashboard. Press Ctrl+C to stop."
  OG_LLM="${OG_LLM:-replay}" exec .venv/bin/orderguard serve --host 127.0.0.1 --port "$PORT"
fi
echo "Not starting the server (--no-serve). Start it later with: .venv/bin/orderguard serve"
