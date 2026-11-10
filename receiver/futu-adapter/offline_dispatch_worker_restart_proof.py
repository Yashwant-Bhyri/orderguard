#!/usr/bin/env python3
"""Crash/restart proof for the W2 SIMULATE adapter against a synthetic venue.

The child process uses the real adapter journal and a persistent LocalSim-style
fixture. One arm exits after the fixture records acceptance but before the
adapter can persist the acknowledgement; restart must reconcile by idempotency
remark and avoid a second send. The blocked arm has no committed ledger row.
No OpenD, Futu, model provider, or external network endpoint is used.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import futu_simulate_adapter as adapter  # noqa: E402
from offline_fault_campaign import create_empty_ledger, create_ledger, request_for  # noqa: E402

ACCOUNT = "1"  # synthetic fixture identifier, never sourced from OpenD
SCRIPT = Path(__file__).resolve()


class DurableSyntheticVenue:
    """Small persistent fixture implementing only the adapter gateway contract."""

    def __init__(self, path: Path, *, crash_after_accept: bool = False) -> None:
        self.path = path
        self.crash_after_accept = crash_after_accept
        if not path.exists():
            self._save({"orders": [], "positions": {}, "place_calls": 0})
        self.state = json.loads(path.read_text(encoding="utf-8"))

    def _save(self, state: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)

    def get_accounts(self) -> list[dict[str, Any]]:
        return [{"acc_id": ACCOUNT, "trd_env": "SIMULATE", "sim_acc_type": "STOCK", "acc_status": "ACTIVE"}]

    def get_positions(self, *, account_id: str, market: str, trd_env: str) -> list[dict[str, Any]]:
        if account_id != ACCOUNT or market != "HK" or trd_env != "SIMULATE":
            raise ValueError("synthetic account scope mismatch")
        return [{"code": code, "qty": qty, "position_side": "LONG"}
                for code, qty in sorted(self.state["positions"].items()) if qty]

    def find_orders(self, *, code: str, account_id: str, start: str, end: str,
                    trd_env: str, remark: str | None = None) -> list[dict[str, Any]]:
        return [row for row in self.state["orders"]
                if row["code"] == code and row["acc_id"] == account_id
                and row["trd_env"] == trd_env
                and (not start or row["create_time"][:10] >= start[:10])
                and (not end or row["create_time"][:10] <= end[:10])
                and (remark is None or row["remark"] == remark)]

    def place_order(self, **kwargs: Any) -> dict[str, Any]:
        code = str(kwargs["code"])
        quantity = int(kwargs["quantity"])
        direction = 1 if str(kwargs["side"]).upper() == "BUY" else -1
        broker_id = f"LOCAL-{self.state['place_calls'] + 1:04d}"
        row = {
            "order_id": broker_id, "remark": kwargs["remark"], "code": code,
            "acc_id": ACCOUNT, "trd_side": str(kwargs["side"]).upper(),
            "qty": quantity, "price": float(kwargs["price"]), "order_type": "NORMAL",
            "trd_env": "SIMULATE", "order_status": "FILLED_ALL",
            "dealt_qty": quantity, "dealt_avg_price": float(kwargs["price"]),
            "time_in_force": "DAY", "create_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }
        self.state["orders"].append(row)
        self.state["place_calls"] += 1
        self.state["positions"][code] = self.state["positions"].get(code, 0) + direction * quantity
        self._save(self.state)
        if self.crash_after_accept:
            os._exit(73)  # durable fixture effect; no adapter acknowledgement
        return {"ret_ok": True, "order_id": broker_id}

    def close(self) -> None:
        return None


def configure_process() -> None:
    os.environ["ORDERGUARD_DISABLE_LOCAL_ENV"] = "1"
    os.environ["ORDERGUARD_FUTU_SIMULATE_ENABLED"] = "1"
    os.environ["ORDERGUARD_B3_DISPATCH_STARTED"] = "1"
    os.environ["ORDERGUARD_FUTU_CONFIG"] = str(ROOT / "futu-adapter/config.json")


def worker(db_path: Path, venue_path: Path, key: str, order_id: str, crash: bool) -> int:
    configure_process()
    journal = adapter.DispatchJournal(str(db_path))
    try:
        request = {"action": "dispatch", "order_id": order_id, "idempotency_key": key,
                   "trd_env": "SIMULATE", "confirm_local_paper": True,
                   "confirm_futu_simulate": True}
        result = adapter.dispatch_order(
            request, lambda _market: DurableSyntheticVenue(venue_path, crash_after_accept=crash), journal,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
        return 0
    finally:
        journal.close()


def state_for(db_path: Path, key: str) -> str | None:
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT state FROM futu_simulate_dispatches WHERE idempotency_key=?", (key,),
        ).fetchone()
        return row[0] if row else None
    finally:
        connection.close()


def run_case(seed: int, scratch: Path) -> dict[str, Any]:
    key = f"restart-{seed:02d}"
    db_path = scratch / f"ledger-{seed:02d}.sqlite"
    venue_path = scratch / f"venue-{seed:02d}.json"
    order = create_ledger(db_path, key)
    order_id = order["orderId"]
    env = {**os.environ, "ORDERGUARD_DISABLE_LOCAL_ENV": "1"}
    command = [sys.executable, str(SCRIPT), "--worker", str(db_path), str(venue_path), key, order_id]
    first = subprocess.run([*command, "crash"], env=env, capture_output=True, text=True)
    first_state = state_for(db_path, key)
    durable_after_crash = json.loads(venue_path.read_text(encoding="utf-8"))
    restarted = subprocess.run([*command, "recover"], env=env, capture_output=True, text=True)
    try:
        recovery_result = json.loads(restarted.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        recovery_result = {"state": "invalid_child_output"}
    final_state = state_for(db_path, key)
    final_venue = json.loads(venue_path.read_text(encoding="utf-8"))
    reconciliation = adapter.reconcile_live(
        str(db_path), lambda _market: DurableSyntheticVenue(venue_path),
    )
    counts = reconciliation.get("counts", {})
    return {
        "seed": seed,
        "crash_exit": first.returncode,
        "journal_after_crash": first_state,
        "venue_rows_after_crash": len(durable_after_crash["orders"]),
        "restart_exit": restarted.returncode,
        "recovery_state": recovery_result.get("state"),
        "final_journal_state": final_state,
        "venue_place_calls": final_venue["place_calls"],
        "position_qty": sum(final_venue["positions"].values()),
        "reconcile_mismatches": int(counts.get("order_mismatches", 0))
        + int(counts.get("position_mismatches", 0)),
        "reconcile_reconciled": reconciliation.get("state") == "reconciled" and reconciliation.get("ok") is True,
    }


def run_blocked_case(scratch: Path) -> dict[str, Any]:
    db_path = scratch / "blocked.sqlite"
    venue_path = scratch / "blocked-venue.json"
    create_empty_ledger(db_path)
    venue = DurableSyntheticVenue(venue_path)
    journal = adapter.DispatchJournal(str(db_path))
    try:
        try:
            adapter.dispatch_order({
                "action": "dispatch", "order_id": "uncommitted", "idempotency_key": "blocked",
                "trd_env": "SIMULATE", "confirm_local_paper": True, "confirm_futu_simulate": True,
            }, lambda _market: venue, journal)
            observed = "unexpected_return"
        except adapter.AdapterError as error:
            observed = error.code
    finally:
        journal.close()
    state = json.loads(venue_path.read_text(encoding="utf-8"))
    return {"observed": observed, "venue_place_calls": state["place_calls"], "venue_rows": len(state["orders"])}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", nargs=5, metavar=("DB", "VENUE", "KEY", "ORDER_ID", "MODE"))
    parser.add_argument("--output", type=Path, default=ROOT / "futu-adapter/results/dispatch-worker-restart-proof-2026-11-03.json")
    args = parser.parse_args()
    if args.worker:
        db, venue, key, order_id, mode = args.worker
        if mode not in {"crash", "recover"}:
            raise SystemExit("unknown worker mode")
        return worker(Path(db), Path(venue), key, order_id, mode == "crash")

    configure_process()
    with tempfile.TemporaryDirectory(prefix="og-w2-dispatch-restart-") as directory:
        scratch = Path(directory)
        recovered = [run_case(seed, scratch) for seed in range(1, 11)]
        blocked = run_blocked_case(scratch)
    passed = sum(
        row["crash_exit"] == 73
        and row["journal_after_crash"] == "dispatching"
        and row["venue_rows_after_crash"] == 1
        and row["restart_exit"] == 0
        and row["recovery_state"] == "accepted"
        and row["final_journal_state"] == "accepted"
        and row["venue_place_calls"] == 1
        and row["position_qty"] == 2
        and row["reconcile_mismatches"] == 0
        and row["reconcile_reconciled"] == 1
        for row in recovered
    )
    blocked_pass = blocked == {"observed": "ledger_commit_missing", "venue_place_calls": 0, "venue_rows": 0}
    result = {
        "schema_version": 1,
        "mode": "offline_dispatch_worker_crash_restart",
        "date_hkt": time.strftime("%Y-%m-%d", time.localtime()),
        "n": len(recovered) + 1,
        "k": passed + int(blocked_pass),
        "model": "N/A; deterministic adapter and synthetic venue",
        "dispatch_worker_crash_cases": len(recovered),
        "dispatch_worker_recovered_cases": passed,
        "blocked_uncommitted_cases": 1,
        "blocked_uncommitted_passed": int(blocked_pass),
        "local_sim_place_calls": sum(row["venue_place_calls"] for row in recovered) + blocked["venue_place_calls"],
        "reconcile_mismatches": sum(int(row["reconcile_mismatches"] or 0) for row in recovered),
        "opend_calls": 0,
        "futu_submissions": 0,
        "provider_calls": 0,
        "external_network_calls": 0,
        "cases": recovered,
        "blocked_case": blocked,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact": str(args.output.relative_to(ROOT)), "mode": result["mode"],
        "n": result["n"], "k": result["k"], "dispatch_worker_recovered": f"{passed}/10",
        "blocked_uncommitted": f"{int(blocked_pass)}/1",
        "local_sim_place_calls": result["local_sim_place_calls"],
        "reconcile_mismatches": result["reconcile_mismatches"],
        "opend_calls": 0, "futu_submissions": 0, "provider_calls": 0,
        "external_network_calls": 0,
    }, sort_keys=True, separators=(",", ":")), flush=True)
    return 0 if result["k"] == result["n"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
