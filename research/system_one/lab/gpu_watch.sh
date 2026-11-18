#!/usr/bin/env bash
# Wait (up to 24 h) for the founder's key-based GPU login to work, then reopen T09 and make sure the runner is up.
cd "$(dirname "$0")/.."
for i in $(seq 1 720); do
  if ssh -o BatchMode=yes -o ConnectTimeout=8 wilson-gpu true 2>/dev/null || ssh -o BatchMode=yes -o ConnectTimeout=8 orderguard-gpu true 2>/dev/null; then
    python3 lab/run_lab.py --reset T09
    bash lab/start.sh
    echo "GPU login works; T09 reopened"
    exit 0
  fi
  sleep 120
done
echo "gave up waiting for the GPU login"
