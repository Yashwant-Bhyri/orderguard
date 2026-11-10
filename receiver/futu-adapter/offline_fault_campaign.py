#!/usr/bin/env python3
"""Deterministic offline W2 fault campaign using the real adapter and fake OpenD."""

from __future__ import annotations

import datetime as dt
import argparse
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "futu-adapter/results/offline-quote-fixture.json"
ACCOUNT = "1"  # synthetic numeric-shape placeholder; never an account read from OpenD
SOURCE_FILES = (
    Path("futu-adapter/offline_fault_campaign.py"),
    Path("futu_simulate_adapter.py"),
    Path("futu-adapter/local_sim_venue.py"),
    Path("futu-adapter/config.json"),
)
QUOTE_FIXTURE = SNAPSHOT.relative_to(ROOT)
sys.path.insert(0, str(ROOT))
import futu_simulate_adapter as adapter
from local_sim_venue import LocalSimVenue


def create_ledger(path: Path, key: str) -> dict[str, Any]:
    order = {
        "orderId": "offline-" + key, "runId": "offline-fault-campaign", "symbol": "0700.HK",
        "side": "buy", "quantity": 2, "market": "HK", "orderType": "limit",
        "limitPrice": 388.0, "referencePrice": 388.0, "estimatedNotionalUsd": 776.0,
        "session": "hk_regular", "timeInForce": "day",
    }
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE paper_orders (
        idempotency_key TEXT PRIMARY KEY, order_id TEXT, order_hash TEXT, intent_hash TEXT,
        order_json TEXT, market_quote_json TEXT, market_quote_result_json TEXT,
        market_quote_receipt_json TEXT, execution_json TEXT, cancelled INTEGER)""")
    connection.execute("INSERT INTO paper_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)", (
        key, order["orderId"], adapter._mesh_order_hash(order), "offline-fixture",
        json.dumps(order, separators=(",", ":")), "{}", "{}", "{}",
        json.dumps({"status": "filled", "filledQuantity": 2, "averageFillPrice": 388.0}),
    ))
    connection.commit()
    connection.close()
    return order


def create_empty_ledger(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE paper_orders (
        idempotency_key TEXT PRIMARY KEY, order_id TEXT, order_hash TEXT, order_json TEXT,
        execution_json TEXT, cancelled INTEGER, market_quote_result_json TEXT,
        market_quote_receipt_json TEXT)""")
    connection.close()


def request_for(key: str, order: dict[str, Any]) -> dict[str, Any]:
    return {"action": "dispatch", "order_id": order["orderId"], "idempotency_key": key,
            "trd_env": "SIMULATE", "confirm_local_paper": True, "confirm_futu_simulate": True}


def dispatch(path: Path, request: dict[str, Any], gateway: LocalSimVenue) -> dict[str, Any]:
    journal = adapter.DispatchJournal(str(path))
    try:
        return adapter.dispatch_order(request, lambda _market: gateway, journal)
    finally:
        journal.close()


def journal_state(path: Path, key: str) -> str | None:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT state FROM futu_simulate_dispatches WHERE idempotency_key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        connection.close()


def run_quote_case(snapshot: dict[str, Any], *, stale_seconds: int = 0, bad_lot: bool = False,
                   timeout: bool = False, preserve_recorded_time: bool = False) -> str:
    row = dict(snapshot["quote"])
    if preserve_recorded_time:
        pass
    elif stale_seconds:
        row["update_time"] = (dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
                              - dt.timedelta(seconds=stale_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    else:
        row["update_time"] = (dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
                              - dt.timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
    if bad_lot:
        row["lot_size"] = 0

    class FakeQuoteContext:
        def get_global_state(self) -> tuple[int, dict[str, Any]]:
            return 0, {"market_hk": "MORNING"}
        def get_market_snapshot(self, _codes: list[str]) -> tuple[int, Any]:
            if timeout:
                raise TimeoutError("simulated quote timeout")
            return 0, [row]
        def close(self) -> None:
            pass

    fake_sdk = type("FakeSDK", (), {"RET_OK": 0, "OpenQuoteContext": lambda **_kwargs: FakeQuoteContext()})
    old_loader = adapter._load_futu_sdk
    adapter._load_futu_sdk = lambda: fake_sdk
    try:
        try:
            result = adapter.read_simulate_quotes("offline_fault_campaign", [row["code"]])
            return "accepted" if result.get("ok") else "refused"
        except adapter.AdapterError as error:
            return error.code
    finally:
        adapter._load_futu_sdk = old_loader


def collect_source_inputs() -> dict[str, bytes]:
    paths = (*SOURCE_FILES, QUOTE_FIXTURE)
    return {path.as_posix(): (ROOT / path).read_bytes() for path in paths}


def build_source_archive(inputs: dict[str, bytes]) -> bytes:
    manifest = {
        "schema_version": 1,
        "source_file_sha256": {
            path.as_posix(): hashlib.sha256(inputs[path.as_posix()]).hexdigest()
            for path in SOURCE_FILES
        },
        "quote_fixture_sha256": hashlib.sha256(inputs[QUOTE_FIXTURE.as_posix()]).hexdigest(),
        "runtime": {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version},
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path, payload in sorted(inputs.items()):
            entry = zipfile.ZipInfo(f"orderguard-source/{path}", date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, payload)
        entry = zipfile.ZipInfo("orderguard-source/manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o100644 << 16
        bundle.writestr(entry, json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return archive.getvalue()


def run(inputs: dict[str, bytes]) -> dict[str, Any]:
    os.environ.pop("ORDERGUARD_MESH_MODE", None)
    os.environ["ORDERGUARD_DISABLE_LOCAL_ENV"] = "1"
    os.environ["ORDERGUARD_FUTU_SIMULATE_ENABLED"] = "1"
    os.environ["ORDERGUARD_B3_DISPATCH_STARTED"] = "1"
    os.environ["ORDERGUARD_FUTU_CONFIG"] = str(ROOT / "futu-adapter/config.json")
    snapshot_bytes = inputs[QUOTE_FIXTURE.as_posix()]
    snapshot = json.loads(snapshot_bytes)
    source_files = {
        path.as_posix(): hashlib.sha256(inputs[path.as_posix()]).hexdigest()
        for path in SOURCE_FILES
    }
    cases: list[dict[str, Any]] = []

    def record(name: str, passed: bool, expected: str, observed: str, detail: dict[str, Any] | None = None) -> None:
        cases.append({"case": name, "pass": bool(passed), "expected": expected, "observed": observed,
                      "detail": detail or {}})

    fresh = run_quote_case(snapshot)
    record("recorded_snapshot_fresh_variant", fresh == "accepted", "fresh SIMULATE quote accepted", fresh)
    recorded_stale = run_quote_case(snapshot, preserve_recorded_time=True)
    record("recorded_snapshot_original_timestamp", recorded_stale == "quote_snapshot_invalid",
           "old saved quote refused by 30s gate", recorded_stale,
           {"captured_at_hkt": snapshot.get("captured_at_hkt"), "dispatches_n": 0})
    stale = run_quote_case(snapshot, stale_seconds=31)
    record("recorded_snapshot_stale_31s", stale == "quote_snapshot_invalid", "refuse quote older than 30s", stale)
    invalid_lot = run_quote_case(snapshot, bad_lot=True)
    record("recorded_snapshot_invalid_lot", invalid_lot == "quote_snapshot_invalid", "refuse invalid board lot", invalid_lot)
    quote_timeout = run_quote_case(snapshot, timeout=True)
    record("quote_timeout", quote_timeout == "quote_bridge_internal_error", "fail closed before dispatch", quote_timeout)

    with tempfile.TemporaryDirectory(prefix="og-w2-fault-") as tmp:
        root = Path(tmp)
        # OpenD down during a two-order batch: first accepted; second remains prepared and is never sent.
        path = root / "opend-down.sqlite"
        o1 = create_ledger(path, "batch-1"); o2 = create_ledger(root / "unused.sqlite", "batch-2")
        # Put both independent committed rows in one ledger under unique keys and IDs.
        c = sqlite3.connect(path)
        raw2 = {**o2, "orderId": "offline-batch-2"}
        c.execute("INSERT INTO paper_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)", (
            "batch-2", raw2["orderId"], adapter._mesh_order_hash(raw2), "offline-fixture",
            json.dumps(raw2, separators=(",", ":")), "{}", "{}", "{}",
            json.dumps({"status": "filled", "filledQuantity": 2, "averageFillPrice": 388.0}),
        )); c.commit(); c.close()
        gw = LocalSimVenue()
        r1 = dispatch(path, request_for("batch-1", o1), gw)
        gw.down = True
        try:
            dispatch(path, request_for("batch-2", raw2), gw)
            down_result = "unexpected_return"
        except TimeoutError:
            down_result = "raised_timeout"
        record("opend_down_mid_batch", r1["state"] == "accepted" and down_result == "raised_timeout"
               and len(gw.place_calls) == 1 and journal_state(path, "batch-2") == "prepared",
               "first order retained; second prepared/no send", down_result,
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls),
                "second_journal_state": journal_state(path, "batch-2")})

        # Negative SDK acknowledgement with no broker row is terminal reject.
        path = root / "reject.sqlite"; order = create_ledger(path, "reject"); gw = LocalSimVenue("reject")
        result = dispatch(path, request_for("reject", order), gw)
        record("broker_reject", result["state"] == "rejected" and journal_state(path, "reject") == "rejected"
               and len(gw.orders) == 0, "rejected; no broker inventory delta", result["state"],
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls)})

        # Receiver-blocked proposals have no committed ledger row and cannot reach LocalSimVenue.
        path = root / "blocked-no-commit.sqlite"; create_empty_ledger(path); gw = LocalSimVenue()
        try:
            dispatch(path, {"action":"dispatch","order_id":"blocked","idempotency_key":"blocked",
                            "trd_env":"SIMULATE","confirm_local_paper":True,"confirm_futu_simulate":True}, gw)
            blocked_result = "unexpected_return"
        except adapter.AdapterError as error:
            blocked_result = error.code
        record("blocked_order_never_arrives", blocked_result == "ledger_commit_missing" and len(gw.place_calls) == 0
               and len(gw.orders) == 0, "no committed authorization; zero venue calls/inventory", blocked_result,
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls)})

        # The venue can reject board-lot and funds violations before adding inventory.
        path = root / "lot-reject.sqlite"; order = create_ledger(path, "lot-reject"); gw = LocalSimVenue("lot_check")
        result = dispatch(path, request_for("lot-reject", order), gw)
        record("venue_lot_reject", result["state"] == "rejected" and len(gw.orders) == 0,
               "reject invalid board lot with zero inventory", result["state"],
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls)})

        path = root / "funds-reject.sqlite"; order = create_ledger(path, "funds-reject"); gw = LocalSimVenue("funds_check")
        gw.cash_by_market["HK"] = 1.0
        result = dispatch(path, request_for("funds-reject", order), gw)
        record("venue_funds_reject", result["state"] == "rejected" and len(gw.orders) == 0,
               "reject insufficient local simulated cash", result["state"],
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls)})

        # The local venue must not silently accept a different account or environment.
        gw = LocalSimVenue()
        try:
            gw.place_order(code="HK.00700", side="BUY", quantity=2, price=388.0,
                           account_id="2", trd_env="SIMULATE", remark="wrong-account")
            account_guard = "unexpected_return"
        except ValueError:
            account_guard = "account_market_or_environment_mismatch"
        record("venue_wrong_account_refused", account_guard == "account_market_or_environment_mismatch"
               and len(gw.orders) == len(gw.place_calls) == 0,
               "wrong account refused before venue call inventory", account_guard,
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls)})
        try:
            gw.place_order(code="HK.00700", side="BUY", quantity=2, price=388.0,
                           account_id="1", trd_env="REAL", remark="wrong-env")
            env_guard = "unexpected_return"
        except ValueError:
            env_guard = "account_market_or_environment_mismatch"
        record("venue_real_environment_refused", env_guard == "account_market_or_environment_mismatch"
               and len(gw.orders) == len(gw.place_calls) == 0,
               "REAL environment refused before venue call inventory", env_guard,
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls)})

        gw.place_order(code="HK.00700", side="BUY", quantity=2, price=388.0,
                       account_id="1", trd_env="SIMULATE", remark="inventory-scope")
        exact_rows = gw.find_orders(code="HK.00700", account_id="1", start="", end="",
                                   trd_env="SIMULATE", remark="inventory-scope")
        foreign_rows = gw.find_orders(code="HK.00700", account_id="2", start="", end="",
                                      trd_env="SIMULATE", remark="inventory-scope")
        future_rows = gw.find_orders(code="HK.00700", account_id="1", start="2999-12-31", end="",
                                     trd_env="SIMULATE", remark="inventory-scope")
        record("venue_order_lookup_scope", len(exact_rows) == 1 and not foreign_rows and not future_rows,
               "order lookup filters account and requested date range", "scoped" if len(exact_rows) == 1 and not foreign_rows and not future_rows else "scope_mismatch",
               {"exact_n": len(exact_rows), "foreign_account_n": len(foreign_rows), "future_date_n": len(future_rows)})

        path = root / "latency-injection.sqlite"; order = create_ledger(path, "latency"); gw = LocalSimVenue(latency_ms=3)
        started = time.perf_counter(); result = dispatch(path, request_for("latency", order), gw)
        elapsed_ms = (time.perf_counter() - started) * 1000
        record("venue_latency_injection", result["state"] == "accepted" and elapsed_ms >= 2.0
               and len(gw.orders) == 1, "accepted after >=2ms injected local latency", f"{elapsed_ms:.2f}ms",
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls), "injected_ms": 3})

        # Partial fill remains in broker inventory; reconciliation must fail against the full ledger fill.
        path = root / "partial.sqlite"; order = create_ledger(path, "partial"); gw = LocalSimVenue("partial")
        result = dispatch(path, request_for("partial", order), gw)
        reconciliation = adapter.reconcile_live(str(path), lambda _market: gw)
        record("partial_fill_reconciliation", result["state"] == "accepted" and not reconciliation["ok"]
               and reconciliation["counts"]["order_mismatches"] == 1
               and reconciliation["counts"]["position_mismatches"] == 1,
               "accepted order visible; ledger/Futu mismatch surfaced", reconciliation["state"],
               {"broker_inventory_n": len(gw.orders), "broker_dealt_qty": gw.orders[0]["dealt_qty"],
                "counts": reconciliation["counts"]})

        # Process restart after durable reserve but before send must resume from prepared exactly once.
        path = root / "restart-prepared.sqlite"; order = create_ledger(path, "restart"); request = request_for("restart", order)
        j = adapter.DispatchJournal(str(path)); ledger_order = j.load_committed_order("restart", order["orderId"])
        remark = "OG" + adapter.hashlib.sha256(b"restart").hexdigest()[:32]
        j.reserve(ledger_order, remark, None); j.close()
        gw = LocalSimVenue(); result = dispatch(path, request, gw)
        record("restart_after_reserve_before_place", result["state"] == "accepted" and len(gw.place_calls) == 1
               and journal_state(path, "restart") == "accepted", "resume prepared order once", result["state"],
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls)})

        # Duplicate submit returns the same broker ID and does not cross send twice.
        path = root / "duplicate.sqlite"; order = create_ledger(path, "duplicate"); gw = LocalSimVenue()
        first = dispatch(path, request_for("duplicate", order), gw)
        second = dispatch(path, request_for("duplicate", order), gw)
        record("duplicate_submit", first["state"] == second["state"] == "accepted" and second["replayed_or_reconciled"]
               and len(gw.place_calls) == len(gw.orders) == 1, "one broker order for duplicate idempotency key",
               second["state"], {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls)})

        # Broker accepts but acknowledgement is lost: next call discovers exact remark, no retry.
        path = root / "lost-ack-after-accept.sqlite"; order = create_ledger(path, "lost-ack"); gw = LocalSimVenue("lost_after_accept")
        first = dispatch(path, request_for("lost-ack", order), gw)
        second = dispatch(path, request_for("lost-ack", order), gw)
        record("ack_lost_after_broker_accept", first["state"] == "unknown" and second["state"] == "accepted"
               and second["replayed_or_reconciled"] and len(gw.place_calls) == len(gw.orders) == 1,
               "unknown then remark reconciliation; no blind retry", f"{first['state']}->{second['state']}",
               {"inventory_n": len(gw.orders), "place_calls_n": len(gw.place_calls)})

    return {
        "schema_version": 2,
        "mode": "offline_fault_campaign",
        "date_hkt": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
        "quote_fixture_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "source_file_sha256": source_files,
        "runtime": {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version},
        "live_opend_calls": 0, "futu_order_submissions": 0, "provider_calls": 0,
        "case_n": len(cases), "passed_n": sum(case["pass"] for case in cases),
        "failed_n": sum(not case["pass"] for case in cases), "cases": cases,
        "limitations": ["All broker/account/order/position behavior used local fakes and scratch SQLite files.",
                        "No live Futu order or actual OpenD inventory was touched.",
                        "Recorded-quote time variants exercise current validator logic but are synthetic mutations, not new quotes.",
                        "The attached source archive contains the listed code, configuration, and quote fixture, but not the interpreter binary or an authenticated publisher signature."],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the offline W2 adapter campaign using fake OpenD and venue services.")
    parser.add_argument("--output", type=Path, help="new artifact path; existing files are never overwritten")
    args = parser.parse_args()
    timestamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%dT%H%M%S%z")
    output = args.output or ROOT / f"futu-adapter/results/offline-fault-campaign-{timestamp}.json"
    archive_path = output.with_name(f"{output.stem}.source.zip")
    if output.exists() or output.is_symlink() or archive_path.exists() or archive_path.is_symlink():
        raise SystemExit(f"Refusing to overwrite an existing artifact or source archive for: {output}")
    inputs = collect_source_inputs()
    result = run(inputs)
    archive_bytes = build_source_archive(inputs)
    result["source_snapshot_archive"] = {
        "file": archive_path.name,
        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "format": "zip",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with archive_path.open("xb") as archive_file:
            archive_file.write(archive_bytes)
        with output.open("x", encoding="utf-8") as artifact_file:
            artifact_file.write(json.dumps(result, indent=2) + "\n")
    except FileExistsError:
        raise SystemExit(f"Refusing to overwrite existing artifact or source archive for: {output}") from None
    print(json.dumps({"artifact": str(output), **{key: result[key] for key in
                     ("mode", "live_opend_calls", "futu_order_submissions", "provider_calls", "case_n", "passed_n", "failed_n")}},
                     separators=(",", ":")))
    for case in result["cases"]:
        print(json.dumps(case, separators=(",", ":")))
    raise SystemExit(0 if result["failed_n"] == 0 else 1)
