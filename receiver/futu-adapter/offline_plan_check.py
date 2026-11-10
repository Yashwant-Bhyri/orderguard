#!/usr/bin/env python3
"""Check W2's cap-sized scenario plan against a saved, non-dispatch quote."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import replay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    data = json.loads(args.snapshot.read_text(encoding="utf-8"))
    quote = data.get("quote") if isinstance(data, dict) else None
    if not isinstance(quote, dict):
        raise SystemExit("snapshot must contain a quote object")
    plan = replay.scenarios(quote)
    controls = [row for row in plan if row["class"] == "approved"]
    blocked = [row for row in plan if row["class"] == "mandate_blocked"]
    attacks = [row for row in plan if row["class"] == "attack_induced"]
    total_control_notional_minor = sum(
        int(row["expected"]["limitPrice"]["amount_minor"]) * int(row["expected"]["quantity"])
        for row in controls
    )
    cap_90_minor = replay.SESSION_CAP_MINOR * replay.CONTROL_CAP_FRACTION_NUMERATOR // replay.CONTROL_CAP_FRACTION_DENOMINATOR
    output = {
        "mode": "offline_plan_only",
        "snapshot_source": data.get("source"),
        "snapshot_captured_at_hkt": data.get("captured_at_hkt"),
        "trd_env": data.get("trd_env"),
        "dispatch_attempted": False,
        "provider_calls": 0,
        "scenario_count_n": len(plan),
        "approved_controls_n": len(controls),
        "mandate_blocked_n": len(blocked),
        "saved_attack_replications_n": len(attacks),
        "saved_attack_bank_ids_n": len(replay.saved_attack_proposals()),
        "control_total_notional_minor": total_control_notional_minor,
        "control_budget_90pct_minor": cap_90_minor,
        "control_cap_pass": total_control_notional_minor <= cap_90_minor,
        "within_20_to_50": replay.MIN_LIVE_ORDER_COUNT <= len(plan) <= replay.MAX_LIVE_ORDER_COUNT,
        "quote_age_gate": "not evaluated offline; live run must enforce 30 seconds",
    }
    print(json.dumps(output, separators=(",", ":")))
    return 0 if output["control_cap_pass"] and output["within_20_to_50"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
