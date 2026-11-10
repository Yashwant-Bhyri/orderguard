#!/usr/bin/env python3
"""Deterministic synthetic proof for the scheduler's quote-age gate."""

from __future__ import annotations

import datetime as dt
import argparse
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scheduler  # noqa: E402


TZ = ZoneInfo("Asia/Hong_Kong")
NOW = dt.datetime(2026, 11, 2, 23, 20, 0, tzinfo=TZ)


def rendered(seconds_from_now: int, *, aware: bool = True, utc_z: bool = False) -> str:
    value = NOW + dt.timedelta(seconds=seconds_from_now)
    if utc_z:
        return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if aware:
        return value.isoformat(timespec="seconds")
    return value.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


cases = [
    ("now_iso_offset", rendered(0), "fresh"),
    ("local_hk_naive_20s", rendered(-20, aware=False), "fresh"),
    ("utc_z_30s", rendered(-30, utc_z=True), "fresh"),
    ("age_boundary_60s", rendered(-60, aware=False), "fresh"),
    ("stale_61s", rendered(-61), "stale"),
    ("stale_1h", rendered(-3600), "stale"),
    ("future_skew_boundary_5s", rendered(5), "fresh"),
    ("future_6s", rendered(6), "future"),
    ("unparseable", "not-a-time", "invalid"),
    ("empty", "", "invalid"),
    ("missing", None, "invalid"),
    ("invalid_calendar_date", "2026-99-99T23:20:00+08:00", "invalid"),
]

observed = []
for case_id, value, expected in cases:
    status, _parsed = scheduler.quote_timestamp_status(value, now=NOW)
    observed.append({"case": case_id, "expected": expected, "observed": status})

passed = sum(item["expected"] == item["observed"] for item in observed)
failed = len(observed) - passed
payload = {
    "mode": "synthetic_quote_freshness_proof",
    "now_hkt": NOW.isoformat(timespec="seconds"),
    "max_age_seconds": scheduler.MAX_QUOTE_AGE_SECONDS,
    "future_skew_seconds": scheduler.MAX_QUOTE_FUTURE_SKEW_SECONDS,
    "n": len(observed),
    "k": passed,
    "failed": failed,
    "cases": observed,
    "live_opend_calls": 0,
    "futu_order_submissions": 0,
    "provider_calls": 0,
}
rendered_output = json.dumps(payload, sort_keys=True)
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path)
args = parser.parse_args()
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered_output + "\n", encoding="utf-8")
print(rendered_output)
raise SystemExit(0 if failed == 0 else 1)
