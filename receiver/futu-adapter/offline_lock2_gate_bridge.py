#!/usr/bin/env python3
"""Python bridge for the W2 Lock-2/LocalSim seam proof; no live venue access."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import futu_simulate_adapter as adapter  # noqa: E402
from offline_dispatch_worker_restart_proof import (  # noqa: E402
    DurableSyntheticVenue,
    configure_process,
    run_blocked_case,
)
from offline_fault_campaign import create_ledger, request_for  # noqa: E402


def run_control(directory: Path, seed: int) -> dict[str, object]:
    configure_process()
    key = f"lock2-clean-{seed:02d}"
    db_path = directory / f"control-{seed:02d}.sqlite"
    venue_path = directory / f"control-venue-{seed:02d}.json"
    order = create_ledger(db_path, key)
    journal = adapter.DispatchJournal(str(db_path))
    try:
        result = adapter.dispatch_order(
            request_for(key, order), lambda _market: DurableSyntheticVenue(venue_path), journal,
        )
    finally:
        journal.close()
    reconciliation = adapter.reconcile_live(
        str(db_path), lambda _market: DurableSyntheticVenue(venue_path),
    )
    counts = reconciliation.get("counts", {})
    venue = json.loads(venue_path.read_text(encoding="utf-8"))
    mismatches = int(counts.get("order_mismatches", 0)) + int(counts.get("position_mismatches", 0))
    return {
        "state": result.get("state"),
        "reconciled": reconciliation.get("ok") is True and reconciliation.get("state") == "reconciled",
        "venue_place_calls": venue["place_calls"],
        "reconcile_mismatches": mismatches,
    }


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"control", "blocked"}:
        raise SystemExit("usage: offline_lock2_gate_bridge.py control|blocked <scratch-dir>")
    mode, scratch_name = sys.argv[1:]
    scratch = Path(scratch_name)
    scratch.mkdir(parents=True, exist_ok=True)
    if mode == "control":
        result = run_control(scratch, seed=int(scratch.name[-2:]) if scratch.name[-2:].isdigit() else 1)
    else:
        configure_process()
        result = run_blocked_case(scratch)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
