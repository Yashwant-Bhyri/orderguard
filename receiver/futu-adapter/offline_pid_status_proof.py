#!/usr/bin/env python3
"""Prove scheduler PID status handling with synthetic os.kill outcomes."""

from __future__ import annotations

import errno
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scheduler  # noqa: E402


real_kill = scheduler.os.kill


def synthetic_kill(pid: int, sig: int) -> None:
    if pid == 101:
        return None
    if pid == 202:
        raise ProcessLookupError(errno.ESRCH, "synthetic absent PID")
    if pid == 303:
        raise PermissionError(errno.EPERM, "synthetic inaccessible PID")
    raise OSError(errno.EIO, "synthetic unknown process status")


scheduler.os.kill = synthetic_kill
cases = [
    (101, "alive", True),
    (202, "dead", False),
    (303, "unknown", True),
    (404, "unknown", True),
]
observed = []
for pid, expected_status, expected_dedup in cases:
    status = scheduler.pid_status(pid)
    dedup = scheduler.pid_blocks_duplicate_start(status)
    observed.append({
        "pid_fixture": pid,
        "status": status,
        "dedup_blocks_new_start": dedup,
        "expected_status": expected_status,
        "expected_dedup_blocks_new_start": expected_dedup,
    })

scheduler.os.kill = real_kill
passed = sum(
    row["status"] == row["expected_status"]
    and row["dedup_blocks_new_start"] == row["expected_dedup_blocks_new_start"]
    for row in observed
)
payload = {
    "mode": "synthetic_scheduler_pid_status_proof",
    "n": len(observed),
    "k": passed,
    "failed": len(observed) - passed,
    "cases": observed,
    "real_pid_signals": 0,
    "launchctl_calls": 0,
    "opend_calls": 0,
    "futu_calls": 0,
    "provider_calls": 0,
}
output = json.dumps(payload, sort_keys=True)
print(output)
raise SystemExit(0 if passed == len(observed) else 1)
