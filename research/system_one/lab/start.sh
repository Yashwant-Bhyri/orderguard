#!/usr/bin/env bash
# Start the lab runner detached, so it survives the terminal or session that started it.
# Needs OG_ENV_FILE (the env file holding OPENCODE_API_KEY) in the environment. Nothing secret is stored here.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${OG_ENV_FILE:?set OG_ENV_FILE to the env file that holds OPENCODE_API_KEY}"
if [ -f lab/runner.pid ] && kill -0 "$(cat lab/runner.pid)" 2>/dev/null; then
  echo "runner already running (pid $(cat lab/runner.pid))"; exit 0
fi
nohup python3 lab/run_lab.py --loop >> lab/runner.out 2>&1 < /dev/null &
disown || true
sleep 2
echo "runner started (pid $(cat lab/runner.pid 2>/dev/null || echo '?')); board: research/system_one/STATUS.md"
