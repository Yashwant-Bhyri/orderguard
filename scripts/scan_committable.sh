#!/bin/sh
# Secret-scan this repository without git: every file except installed dependencies,
# ignored runtime state, virtualenvs, caches and binary databases. Then check that the
# TypeScript workspace contains no absolute home paths.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/og-scan.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
cd "$root"
tar -cf - \
  --exclude=./node_modules --exclude=./.git --exclude=./.venv --exclude=./var --exclude=./.orderguard \
  --exclude=./data/risk/.cache \
  --exclude=__pycache__ --exclude=.pytest_cache --exclude=.DS_Store \
  --exclude='*.db' --exclude='*.sqlite' --exclude='*.sqlite-journal' --exclude='*.mp4' \
  . | tar -xf - -C "$tmp"
python3 "$root/scripts/secret_scan.py" "$tmp"
if grep -rIlE -e "/Users/[A-Za-z]" -e "(^|[[:space:]\"'(=])/home/[a-z][a-z0-9_-]*/" packages examples bin scripts receiver docs python lab results data/lab README.md 2>/dev/null | grep -v "scripts/scan_committable.sh"; then
  echo "scan: absolute home path found in the files listed above" >&2
  exit 1
fi
echo "scan: no absolute home paths in the TypeScript workspace"
