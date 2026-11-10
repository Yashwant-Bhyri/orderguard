#!/usr/bin/env python3
"""Prove MANDATE-M1 revocation ordering at the offline LocalSim send boundary."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "futu-adapter"))
os.environ["ORDERGUARD_DISABLE_LOCAL_ENV"] = "1"
os.environ["ORDERGUARD_FUTU_SIMULATE_ENABLED"] = "1"
os.environ["ORDERGUARD_FUTU_CONFIG"] = str(ROOT / "futu-adapter/config.json")
import futu_simulate_adapter as adapter
from local_sim_venue import LocalSimVenue


def digest(value: Any) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(adapter._canonical(value).encode()).digest()).decode().rstrip("=")


def seed(path: Path, key: str, *, revoked: bool = False) -> dict[str, str]:
    order_id = f"v017-{key}"
    mandate_id = f"mandate-{key}"
    mandate_hash = digest({"mandate": key})
    order = {"orderId": order_id, "runId": "offline-v017", "symbol": "VLTA", "side": "buy",
             "quantity": 100, "market": "HK", "orderType": "limit", "limitPrice": 48.2,
             "limitPriceMinor": 4820, "currency": "HKD", "session": "hk_regular", "timeInForce": "day"}
    quote_result = {"provenance": "Futu OpenD SIMULATE quote snapshot.", "quotes": [
        {"symbol": "VLTA", "futuCode": "HK.00700", "provenance": "futu-opend-simulate", "currency": "HKD",
         "lotSize": 100, "last": 48.2, "bid": 48.1, "ask": 48.2}
    ]}
    receipt = {"synthetic": True, "symbol": "VLTA", "timestamp": "2026-10-31T00:00:00Z"}
    order_hash = adapter._mesh_order_hash(order)
    with sqlite3.connect(path) as db:
        db.executescript("""
          CREATE TABLE paper_orders (idempotency_key TEXT PRIMARY KEY, order_id TEXT NOT NULL, order_hash TEXT NOT NULL,
            order_json TEXT NOT NULL, execution_json TEXT NOT NULL, cancelled INTEGER NOT NULL,
            market_quote_result_json TEXT NOT NULL, market_quote_receipt_json TEXT NOT NULL, created_at INTEGER NOT NULL,
            market_quote_json TEXT NOT NULL);
          CREATE TABLE futu_m1_dispatch_authorizations (idempotency_key TEXT PRIMARY KEY, order_id TEXT NOT NULL,
            order_hash TEXT NOT NULL, mandate_id TEXT NOT NULL, mandate_hash TEXT NOT NULL, quote_receipt_hash TEXT NOT NULL,
            second_lock_decision TEXT NOT NULL, version TEXT NOT NULL, created_at INTEGER NOT NULL);
          CREATE TABLE human_mandates (mandate_id TEXT PRIMARY KEY, mandate_hash TEXT NOT NULL, document_json TEXT NOT NULL,
            created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER,
            revoke_requested_at INTEGER);
        """)
        db.execute("INSERT INTO paper_orders (idempotency_key, order_id, order_hash, order_json, execution_json, cancelled, market_quote_result_json, market_quote_receipt_json, created_at, market_quote_json) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                   (key, order_id, order_hash, json.dumps(order, separators=(",", ":")),
                    json.dumps({"status": "accepted"}), json.dumps(quote_result, separators=(",", ":")),
                    json.dumps(receipt, separators=(",", ":")), 100, "{}"))
        db.execute("ALTER TABLE paper_orders ADD COLUMN budget_currency TEXT NOT NULL DEFAULT 'HKD'")
        db.execute("ALTER TABLE paper_orders ADD COLUMN budget_notional_minor INTEGER NOT NULL DEFAULT 482000")
        db.execute("ALTER TABLE paper_orders ADD COLUMN budget_notional_usd REAL NOT NULL DEFAULT 0")
        db.execute("INSERT INTO human_mandates VALUES (?, ?, ?, 1, ?, ?, NULL)",
                   (mandate_id, mandate_hash, json.dumps({"synthetic": True}), 9_999_999_999_999,
                    101 if revoked else None))
        db.execute("INSERT INTO futu_m1_dispatch_authorizations VALUES (?, ?, ?, ?, ?, ?, 'allow', 'MANDATE-M1-v1.0.0', 100)",
                   (key, order_id, order_hash, mandate_id, mandate_hash, adapter._mesh_order_hash(receipt)))
    journal = adapter.DispatchJournal(str(path))
    try:
        journal.connection.execute(
            "INSERT INTO futu_simulate_dispatches (idempotency_key, order_id, order_hash, remark, state, updated_at_ms) "
            "VALUES (?, ?, ?, ?, 'prepared', 100)",
            (key, order_id, order_hash, "OG" + hashlib.sha256(key.encode()).hexdigest()[:32]),
        )
    finally:
        journal.close()
    return {"key": key, "order_id": order_id, "order_hash": order_hash,
            "mandate_id": mandate_id, "mandate_hash": mandate_hash, "order_json": order}


def seed_sibling(path: Path, key: str, mandate_id: str, mandate_hash: str) -> dict[str, str]:
    order_id = f"v017-{key}"
    order = {"orderId": order_id, "runId": "offline-v017", "symbol": "VLTA", "side": "buy",
             "quantity": 100, "market": "HK", "orderType": "limit", "limitPrice": 48.2,
             "limitPriceMinor": 4820, "currency": "HKD", "session": "hk_regular", "timeInForce": "day"}
    quote_result = {"provenance": "Futu OpenD SIMULATE quote snapshot.", "quotes": [
        {"symbol": "VLTA", "futuCode": "HK.00700", "provenance": "futu-opend-simulate", "currency": "HKD",
         "lotSize": 100, "last": 48.2, "bid": 48.1, "ask": 48.2}
    ]}
    receipt = {"synthetic": True, "symbol": "VLTA", "timestamp": "2026-10-31T00:00:00Z"}
    order_hash = adapter._mesh_order_hash(order)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO paper_orders (idempotency_key, order_id, order_hash, order_json, execution_json, cancelled, market_quote_result_json, market_quote_receipt_json, created_at, market_quote_json) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                   (key, order_id, order_hash, json.dumps(order, separators=(",", ":")),
                    json.dumps({"status": "accepted"}), json.dumps(quote_result, separators=(",", ":")),
                    json.dumps(receipt, separators=(",", ":")), 101, "{}"))
        db.execute("INSERT INTO futu_m1_dispatch_authorizations VALUES (?, ?, ?, ?, ?, ?, 'allow', 'MANDATE-M1-v1.0.0', 101)",
                   (key, order_id, order_hash, mandate_id, mandate_hash, adapter._mesh_order_hash(receipt)))
    journal = adapter.DispatchJournal(str(path))
    try:
        journal.connection.execute(
            "INSERT INTO futu_simulate_dispatches (idempotency_key, order_id, order_hash, remark, state, updated_at_ms) "
            "VALUES (?, ?, ?, ?, 'prepared', 101)",
            (key, order_id, order_hash, "OG" + hashlib.sha256(key.encode()).hexdigest()[:32]),
        )
    finally:
        journal.close()
    return {"key": key, "order_id": order_id, "mandate_id": mandate_id, "mandate_hash": mandate_hash}


def record_synthetic_terminal_pair(path: Path, row: dict[str, str], state: str) -> None:
    """Fixture only: model exact ledger evidence after a cancel/fill reconciliation."""
    if state not in {"cancelled", "filled"}:
        raise ValueError("terminal state must be cancelled or filled")
    with sqlite3.connect(path) as db:
        db.executescript("""
          CREATE TABLE IF NOT EXISTS venue_mandate_orders (
            venue TEXT NOT NULL, mandate_id TEXT NOT NULL, mandate_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL, order_id TEXT NOT NULL, order_hash TEXT NOT NULL,
            order_quantity_atoms INTEGER NOT NULL, client_order_id TEXT NOT NULL, venue_order_id TEXT,
            order_json TEXT NOT NULL, state TEXT NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
            PRIMARY KEY (venue, mandate_id, order_id), UNIQUE (venue, client_order_id)
          );
          CREATE TABLE IF NOT EXISTS mandate_cancellation_outbox (
            outbox_id TEXT PRIMARY KEY, venue TEXT NOT NULL, mandate_id TEXT NOT NULL,
            mandate_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL, order_id TEXT NOT NULL,
            order_hash TEXT NOT NULL, order_quantity_atoms INTEGER NOT NULL, client_order_id TEXT NOT NULL,
            venue_order_id TEXT, order_json TEXT NOT NULL, reason TEXT NOT NULL, state TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0, lease_until_ms INTEGER, next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
            last_observation_json TEXT, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
            UNIQUE (venue, mandate_id, order_id)
          );
        """)
        order_json = json.dumps(row["order_json"], separators=(",", ":"))
        db.execute("INSERT INTO venue_mandate_orders VALUES ('futu-simulate', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (row["mandate_id"], row["mandate_hash"], row["key"], row["order_id"], row["order_hash"], 100,
                    "client-" + row["key"], "venue-" + row["key"], order_json, state, 1, 1))
        db.execute("INSERT INTO mandate_cancellation_outbox "
                   "(outbox_id,venue,mandate_id,mandate_hash,idempotency_key,order_id,order_hash,order_quantity_atoms,"
                   "client_order_id,venue_order_id,order_json,reason,state,created_at_ms,updated_at_ms) "
                   "VALUES ('outbox-'||?,'futu-simulate',?,?,?,?,?,100,?,?,?,'revoked',?,1,1)",
                   (row["key"], row["mandate_id"], row["mandate_hash"], row["key"], row["order_id"],
                    row["order_hash"], "client-" + row["key"], "venue-" + row["key"], order_json, state))


def finalize_again(path: Path, row: dict[str, str]) -> None:
    journal = adapter.DispatchJournal(str(path))
    try:
        current = journal.connection.execute(
            "SELECT broker_order_id FROM futu_simulate_dispatches WHERE idempotency_key=?", (row["key"],)
        ).fetchone()
        journal.set_state(row["key"], "accepted", current[0])
    finally:
        journal.close()


def request(row: dict[str, str]) -> dict[str, object]:
    return {"action": "dispatch", "trd_env": "SIMULATE", "confirm_local_paper": True,
            "confirm_futu_simulate": True, "idempotency_key": row["key"], "order_id": row["order_id"]}


def dispatch(path: Path, row: dict[str, str], venue: LocalSimVenue) -> dict[str, object]:
    journal = adapter.DispatchJournal(str(path))
    try:
        return adapter.dispatch_order(request(row), lambda _market: venue, journal)
    finally:
        journal.close()


def cancel_via_mesh_store(path: Path, row: dict[str, str]) -> dict[str, object]:
    """Exercise the actual TypeScript cancellation transaction during dispatch."""
    probe = Path(__file__).with_name("cancel_dispatch_probe.ts")
    result = subprocess.run(
        ["node", "--import", "tsx", str(probe), str(path), row["key"], row["order_id"],
         row["order_hash"]],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def revoke(path: Path, row: dict[str, str], events: list[str], done: threading.Event) -> None:
    with sqlite3.connect(path, timeout=5) as db:
        in_flight = db.execute(
            "SELECT 1 FROM futu_m1_dispatch_authorizations a JOIN futu_simulate_dispatches d "
            "ON d.idempotency_key=a.idempotency_key WHERE a.mandate_id=? AND d.state IN ('dispatching','unknown','conflict') LIMIT 1",
            (row["mandate_id"],),
        ).fetchone()
        now = int(time.time() * 1000)
        if in_flight:
            db.execute("UPDATE human_mandates SET revoke_requested_at=? WHERE mandate_id=? AND revoked_at IS NULL",
                       (now, row["mandate_id"]))
            events.append("revoke_pending")
        else:
            db.execute("UPDATE human_mandates SET revoked_at=? WHERE mandate_id=? AND revoked_at IS NULL",
                       (now, row["mandate_id"]))
            events.append("revoked")
    done.set()


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="og-w2-v017-", dir="/tmp"))
    # Revoke committed before the final claim: dispatch must fail closed.
    revoked_db = root / "revoked.sqlite"
    revoked = seed(revoked_db, "revoked", revoked=True)
    revoked_venue = LocalSimVenue(account_id="90210001", market="HK")
    revoked_result = dispatch(revoked_db, revoked, revoked_venue)

    # A ledger cancellation after initial load but before the final claim also
    # prevents the venue call.
    cancelled_db = root / "cancelled-after-load.sqlite"
    cancelled = seed(cancelled_db, "cancelled-after-load")
    cancelled_journal = adapter.DispatchJournal(str(cancelled_db))
    cancelled_order = cancelled_journal.load_committed_order(cancelled["key"], cancelled["order_id"])
    cancelled_remark = "OG" + hashlib.sha256(cancelled["key"].encode()).hexdigest()[:32]
    cancelled_journal.reserve(cancelled_order, cancelled_remark, "90210001")
    cancelled_journal.close()
    with sqlite3.connect(cancelled_db) as db:
        db.execute("UPDATE paper_orders SET cancelled = 1 WHERE idempotency_key = ?", (cancelled["key"],))
    cancelled_journal = adapter.DispatchJournal(str(cancelled_db))
    try:
        cancelled_claim = cancelled_journal.claim_m1_dispatch(
            cancelled["key"], cancelled["order_id"], cancelled_order.order_hash,
        )
    finally:
        cancelled_journal.close()
    cancelled_venue = LocalSimVenue(account_id="90210001", market="HK")

    # Active control: a valid current mandate reaches LocalSim exactly once.
    active_db = root / "active.sqlite"
    active = seed(active_db, "active")
    active_venue = LocalSimVenue(account_id="90210001", market="HK")
    active_result = dispatch(active_db, active, active_venue)

    # Simulate process death after a durable claim and broker acceptance but
    # before the adapter records the acknowledgement; restart must find remark.
    crash_db = root / "crash-after-accept.sqlite"
    crash = seed(crash_db, "crash-after-accept")
    crash_venue = LocalSimVenue(account_id="90210001", market="HK")
    crash_journal = adapter.DispatchJournal(str(crash_db))
    crash_order = crash_journal.load_committed_order(crash["key"], crash["order_id"])
    crash_remark = "OG" + hashlib.sha256(crash["key"].encode()).hexdigest()[:32]
    crash_journal.reserve(crash_order, crash_remark, "90210001")
    crash_claim = crash_journal.claim_m1_dispatch(crash["key"], crash["order_id"], crash_order.order_hash)
    crash_venue.place_order(code="HK.00700", side="BUY", quantity=100, price=48.2,
                            account_id="90210001", trd_env="SIMULATE", remark=crash_remark)
    crash_journal.close()  # abrupt restart boundary: dispatch row is still dispatching
    crash_result = dispatch(crash_db, crash, crash_venue)

    # Ambiguous send keeps revocation pending; a sibling order cannot claim;
    # later reconciliation resolves the in-flight row and completes revocation.
    pending_db = root / "pending.sqlite"
    pending = seed(pending_db, "pending")

    class UnknownVenue(LocalSimVenue):
        def place_order(self, **kwargs: object) -> dict[str, object]:
            self.place_calls.append(dict(kwargs))
            raise TimeoutError("synthetic ambiguous send")
        def find_orders(self, **kwargs: object) -> list[dict[str, object]]:
            return []

    unknown_venue = UnknownVenue(account_id="90210001", market="HK")
    unknown_result = dispatch(pending_db, pending, unknown_venue)
    with sqlite3.connect(pending_db) as db:
        db.execute("UPDATE human_mandates SET revoke_requested_at = 200 WHERE mandate_id = ?", (pending["mandate_id"],))
    sibling = seed_sibling(pending_db, "pending-sibling", pending["mandate_id"], pending["mandate_hash"])
    sibling_venue = LocalSimVenue(account_id="90210001", market="HK")
    sibling_result = dispatch(pending_db, sibling, sibling_venue)
    pending_journal = adapter.DispatchJournal(str(pending_db))
    try:
        pending_journal.set_state(pending["key"], "accepted", "LOCAL-RECONCILED")
        pending_before_cancel_complete = pending_journal.connection.execute(
            "SELECT revoked_at,revoke_requested_at FROM human_mandates WHERE mandate_id=?",
            (pending["mandate_id"],),
        ).fetchone()
    finally:
        pending_journal.close()
    record_synthetic_terminal_pair(pending_db, pending, "cancelled")
    finalize_again(pending_db, pending)
    with sqlite3.connect(pending_db) as db:
        pending_after = db.execute("SELECT revoked_at, revoke_requested_at FROM human_mandates WHERE mandate_id = ?",
                                   (pending["mandate_id"],)).fetchone()

    # Race ordering: hold the SQLite send-boundary transaction while another
    # connection requests revocation. The revoke must wait for local send and
    # immediate reconciliation to finish, then commit afterwards.
    race_db = root / "race.sqlite"
    race = seed(race_db, "race")
    entered, release, revoke_started, revoked_done = (threading.Event() for _ in range(4))
    events: list[str] = []
    cancel_outcomes: list[dict[str, object]] = []
    cancel_errors: list[str] = []

    class PausingVenue(LocalSimVenue):
        def place_order(self, **kwargs: object) -> dict[str, object]:
            entered.set()
            if not release.wait(30):
                raise TimeoutError("proof barrier timed out")
            try:
                cancel_result = cancel_via_mesh_store(race_db, race)
            except Exception as error:
                stderr = getattr(error, "stderr", "")
                cancel_errors.append(f"{type(error).__name__}:{error};stderr={stderr}")
                raise
            cancel_outcomes.append(cancel_result)
            events.append("cancel_checked")
            result = super().place_order(**kwargs)
            events.append("placed")
            result["offline_cancel_result"] = cancel_result
            return result

    race_venue = PausingVenue(account_id="90210001", market="HK")
    dispatch_result: list[dict[str, object]] = []
    dispatch_thread = threading.Thread(target=lambda: dispatch_result.append(dispatch(race_db, race, race_venue)))
    dispatch_thread.start()
    if not entered.wait(3):
        raise RuntimeError("dispatch did not reach the deterministic send barrier")
    revoke_thread = threading.Thread(target=lambda: (revoke_started.set(), revoke(race_db, race, events, revoked_done)))
    revoke_thread.start()
    if not revoke_started.wait(3):
        raise RuntimeError("revocation thread did not start")
    revoke_pending_saved_during_send = revoked_done.wait(0.2)
    release.set()
    dispatch_thread.join(35)
    revoke_thread.join(35)
    if dispatch_thread.is_alive() or revoke_thread.is_alive():
        raise RuntimeError("dispatch/revocation barrier did not settle")
    with sqlite3.connect(race_db) as db:
        race_pending_before_cancel_complete = db.execute(
            "SELECT revoked_at, revoke_requested_at FROM human_mandates WHERE mandate_id = ?",
            (race["mandate_id"],),
        ).fetchone()
    record_synthetic_terminal_pair(race_db, race, "cancelled")
    finalize_again(race_db, race)
    with sqlite3.connect(race_db) as db:
        race_mandate_state = db.execute(
            "SELECT revoked_at, revoke_requested_at FROM human_mandates WHERE mandate_id = ?",
            (race["mandate_id"],),
        ).fetchone()

    observed = {
        "proof": "w2_m1_dispatch_revocation_linearization",
        "revoked_before_claim": {"state": revoked_result["state"], "local_place_calls": len(revoked_venue.place_calls)},
        "cancelled_after_load_before_claim": {"claim_state": cancelled_claim,
                                               "local_place_calls": len(cancelled_venue.place_calls)},
        "active_control": {"state": active_result["state"], "local_place_calls": len(active_venue.place_calls)},
        "crash_after_accept_before_ack_commit": {"claim_state": crash_claim, "restart_state": crash_result["state"],
                                                  "local_place_calls": len(crash_venue.place_calls)},
        "ambiguous_send_pending_revoke": {"initial_state": unknown_result["state"],
                                          "new_sibling_state": sibling_result["state"],
                                          "new_sibling_place_calls": len(sibling_venue.place_calls),
                                          "pending_before_cancel_complete": pending_before_cancel_complete[0] is None and pending_before_cancel_complete[1] == 200,
                                          "final_mandate_revoked": pending_after[0] is not None,
                                          "pending_marker_cleared": pending_after[1] is None},
        "revoke_during_claim": {"state": dispatch_result[0]["state"], "local_place_calls": len(race_venue.place_calls),
                                "revoke_pending_saved_during_send": revoke_pending_saved_during_send,
                                "revoke_pending_after_dispatch_ack": race_pending_before_cancel_complete[0] is None and race_pending_before_cancel_complete[1] is not None,
                                "revoke_finalized_after_cancel_complete": race_mandate_state[0] is not None and race_mandate_state[1] is None,
                                "event_order": events},
        "cancel_after_claim_before_place": {"cancel_result": cancel_outcomes[0] if cancel_outcomes else None,
                                            "cancel_errors": cancel_errors,
                                            "local_place_calls": len(race_venue.place_calls),
                                            "order_cancelled": sqlite3.connect(race_db).execute(
                                                "SELECT cancelled FROM paper_orders WHERE idempotency_key = ?", (race["key"],)
                                            ).fetchone()[0]},
        "synthetic_account": "90210001", "venue": "LocalSimVenue", "trd_env": "SIMULATE",
        "opend_calls": 0, "broker_calls": 0, "provider_calls": 0,
    }
    expected = (
        observed["revoked_before_claim"] == {"state": "rejected", "local_place_calls": 0}
        and observed["cancelled_after_load_before_claim"] == {"claim_state": "claim_ineligible", "local_place_calls": 0}
        and observed["active_control"] == {"state": "accepted", "local_place_calls": 1}
        and observed["crash_after_accept_before_ack_commit"] == {"claim_state": "claimed", "restart_state": "accepted",
                                                                  "local_place_calls": 1}
        and observed["ambiguous_send_pending_revoke"] == {"initial_state": "unknown", "new_sibling_state": "rejected",
                                                          "new_sibling_place_calls": 0, "pending_before_cancel_complete": True,
                                                          "final_mandate_revoked": True,
                                                          "pending_marker_cleared": True}
        and observed["revoke_during_claim"]["state"] == "accepted"
        and observed["revoke_during_claim"]["local_place_calls"] == 1
        and observed["revoke_during_claim"]["revoke_pending_saved_during_send"] is True
        and observed["revoke_during_claim"]["revoke_pending_after_dispatch_ack"] is True
        and observed["revoke_during_claim"]["revoke_finalized_after_cancel_complete"] is True
        and observed["revoke_during_claim"]["event_order"] == ["revoke_pending", "cancel_checked", "placed"]
        and observed["cancel_after_claim_before_place"]["cancel_result"] == {"kind": "dispatch-blocked", "state": "dispatching"}
        and observed["cancel_after_claim_before_place"]["local_place_calls"] == 1
        and observed["cancel_after_claim_before_place"]["order_cancelled"] == 0
    )
    print(json.dumps(observed, sort_keys=True, separators=(",", ":")))
    if not expected:
        raise SystemExit("V-017 dispatch/revocation outcome mismatch")
    print("V-017 offline boundary proof: n=7 k=7; synthetic terminal evidence only; OpenD=0; broker=0; provider=0")


if __name__ == "__main__":
    main()
