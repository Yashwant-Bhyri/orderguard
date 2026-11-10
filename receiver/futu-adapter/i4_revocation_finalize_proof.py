#!/usr/bin/env python3
"""Offline proof of Futu adapter revoke-finalization predicates (not venue I/O)."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["ORDERGUARD_DISABLE_LOCAL_ENV"] = "1"
os.environ["ORDERGUARD_FUTU_SIMULATE_ENABLED"] = "1"
os.environ["ORDERGUARD_FUTU_CONFIG"] = str(ROOT / "futu-adapter/config.json")
import futu_simulate_adapter as adapter  # noqa: E402

FINALIZE_AT = 123456789


def schema(db: sqlite3.Connection, revoke_requested_at: int | None,
           prior_revoked_at: int | None) -> None:
    db.executescript("""
      CREATE TABLE human_mandates (
        mandate_id TEXT PRIMARY KEY, mandate_hash TEXT NOT NULL, document_json TEXT NOT NULL,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER,
        revoke_requested_at INTEGER
      );
      CREATE TABLE futu_m1_dispatch_authorizations (
        idempotency_key TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE, order_hash TEXT NOT NULL,
        mandate_id TEXT NOT NULL, mandate_hash TEXT NOT NULL, quote_receipt_hash TEXT NOT NULL,
        second_lock_decision TEXT NOT NULL CHECK (second_lock_decision = 'allow'),
        version TEXT NOT NULL CHECK (version = 'MANDATE-M1-v1.0.0'), created_at INTEGER NOT NULL
      );
      CREATE TABLE futu_simulate_dispatches (
        idempotency_key TEXT PRIMARY KEY, order_id TEXT NOT NULL, order_hash TEXT NOT NULL,
        remark TEXT NOT NULL UNIQUE, state TEXT NOT NULL CHECK (state IN
        ('prepared','dispatching','accepted','unknown','rejected','conflict')),
        broker_order_id TEXT, account_id TEXT, account_masked TEXT, reconciliation_json TEXT,
        updated_at_ms INTEGER NOT NULL
      );
      CREATE TABLE venue_mandate_orders (
        venue TEXT NOT NULL, mandate_id TEXT NOT NULL, mandate_hash TEXT NOT NULL,
        idempotency_key TEXT NOT NULL, order_id TEXT NOT NULL, order_hash TEXT NOT NULL,
        order_quantity_atoms INTEGER NOT NULL CHECK (order_quantity_atoms > 0),
        client_order_id TEXT NOT NULL, venue_order_id TEXT, order_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('resident','unknown','cancelled','filled','blocked')),
        created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
        PRIMARY KEY (venue,mandate_id,order_id), UNIQUE (venue,client_order_id)
      );
      CREATE TABLE mandate_cancellation_outbox (
        outbox_id TEXT PRIMARY KEY, venue TEXT NOT NULL, mandate_id TEXT NOT NULL,
        mandate_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL, order_id TEXT NOT NULL,
        order_hash TEXT NOT NULL, order_quantity_atoms INTEGER NOT NULL CHECK (order_quantity_atoms > 0),
        client_order_id TEXT NOT NULL, venue_order_id TEXT, order_json TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (reason IN ('revoked','expired')),
        state TEXT NOT NULL CHECK (state IN ('pending','dispatching','retry','cancelled','filled','blocked')),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0), lease_until_ms INTEGER,
        next_attempt_at_ms INTEGER NOT NULL DEFAULT 0, last_observation_json TEXT,
        created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
        UNIQUE (venue,mandate_id,order_id)
      );
      INSERT INTO human_mandates VALUES ('m1','M1','{}',1,9999999999999,NULL,NULL);
    """)
    db.execute("UPDATE human_mandates SET revoke_requested_at=?, revoked_at=? WHERE mandate_id='m1'",
               (revoke_requested_at, prior_revoked_at))


def add_order(db: sqlite3.Connection, key: str, order_id: str, order_hash: str,
              dispatch_state: str) -> None:
    db.execute(
        "INSERT INTO futu_m1_dispatch_authorizations VALUES (?, ?, ?, 'm1', 'M1', 'Q', 'allow', 'MANDATE-M1-v1.0.0', 1)",
        (key, order_id, order_hash),
    )
    db.execute(
        "INSERT INTO futu_simulate_dispatches "
        "(idempotency_key,order_id,order_hash,remark,state,updated_at_ms) VALUES (?,?,?,?,?,1)",
        (key, order_id, order_hash, "remark-" + key, dispatch_state),
    )


def add_venue(db: sqlite3.Connection, *, venue: str = "futu-simulate", mandate_id: str = "m1",
              key: str = "k1", order_id: str = "o1", order_hash: str = "hash-1",
              state: str = "cancelled") -> None:
    db.execute(
        "INSERT INTO venue_mandate_orders VALUES (?, ?, 'M1', ?, ?, ?, 10, ?, 'vo-'||?, '{}', ?, 1, 1)",
        (venue, mandate_id, key, order_id, order_hash, "client-" + key, key, state),
    )


def add_outbox(db: sqlite3.Connection, *, mandate_id: str = "m1", key: str = "k1",
               order_id: str = "o1", order_hash: str = "hash-1", state: str = "cancelled") -> None:
    db.execute(
        "INSERT INTO mandate_cancellation_outbox "
        "(outbox_id,venue,mandate_id,mandate_hash,idempotency_key,order_id,order_hash,"
        "order_quantity_atoms,client_order_id,venue_order_id,order_json,reason,state,attempt_count,"
        "next_attempt_at_ms,created_at_ms,updated_at_ms) "
        "VALUES (?, 'futu-simulate', ?, 'M1', ?, ?, ?, 10, ?, 'vo-'||?, '{}', 'revoked', ?, 0, 0, 1, 1)",
        ("outbox-" + key + "-" + order_id, mandate_id, key, order_id, order_hash,
         "client-" + key, key, state),
    )


def run_case(name: str, seed_case, expected_finalized: bool,
             expected_revoked_at: int | None = None,
             expected_request_at: int | None = FINALIZE_AT) -> None:
    with tempfile.TemporaryDirectory(prefix="og-i4-futu-") as temp:
        path = Path(temp) / "ledger.sqlite"
        with sqlite3.connect(path) as db:
            schema(db, expected_request_at, expected_revoked_at)
            # Case builder creates only the identities and venue facts for this scenario.
            seed_case(db)
        journal = adapter.DispatchJournal(str(path))
        try:
            # Trigger an accepted result on k1; the finalizer inspects every order bound to m1.
            state = journal.set_state("k1", "accepted", "broker-k1")
            final_row = journal.connection.execute(
                "SELECT revoked_at,revoke_requested_at FROM human_mandates WHERE mandate_id='m1'"
            ).fetchone()
            finalize_time = journal.connection.execute(
                "SELECT updated_at_ms FROM futu_simulate_dispatches WHERE idempotency_key='k1'"
            ).fetchone()[0]
        finally:
            journal.close()
        finalized = state == "accepted" and final_row[0] is not None and final_row[1] is None
        if finalized != expected_finalized:
            raise AssertionError(f"{name}: expected finalized={expected_finalized}, got {final_row}")
        expect_revoked = (expected_revoked_at if expected_revoked_at is not None else finalize_time)
        expected = ((expect_revoked, None) if expected_finalized
                    else (expected_revoked_at, expected_request_at))
        if final_row != expected:
            raise AssertionError(f"{name}: expected {expected}, got {final_row}")


def case_single(dispatch_state: str = "accepted", venue_state: str | None = None,
                outbox_state: str | None = None, outbox_hash: str = "hash-1",
                venue_name: str = "futu-simulate"):
    def seed(db: sqlite3.Connection) -> None:
        add_order(db, "k1", "o1", "hash-1", dispatch_state)
        if venue_state is not None:
            add_venue(db, venue=venue_name, state=venue_state)
        if outbox_state is not None:
            add_outbox(db, order_hash=outbox_hash, state=outbox_state)
    return seed


def case_inflight_sibling(dispatch_state: str):
    def seed(db: sqlite3.Connection) -> None:
        add_order(db, "k1", "o1", "hash-1", "prepared")
        add_order(db, "k2", "o2", "hash-2", dispatch_state)
        add_venue(db, key="k1", order_id="o1", order_hash="hash-1", state="cancelled")
        add_outbox(db, key="k1", order_id="o1", order_hash="hash-1", state="cancelled")
    return seed


def case_second_unindexed():
    def seed(db: sqlite3.Connection) -> None:
        add_order(db, "k1", "o1", "hash-1", "prepared")
        add_order(db, "k2", "o2", "hash-2", "accepted")
        add_venue(db, key="k1", order_id="o1", order_hash="hash-1", state="cancelled")
        add_outbox(db, key="k1", order_id="o1", order_hash="hash-1", state="cancelled")
    return seed


def case_all_terminal():
    def seed(db: sqlite3.Connection) -> None:
        add_order(db, "k1", "o1", "hash-1", "prepared")
        add_order(db, "k2", "o2", "hash-2", "accepted")
        add_venue(db, key="k1", order_id="o1", order_hash="hash-1", state="cancelled")
        add_outbox(db, key="k1", order_id="o1", order_hash="hash-1", state="cancelled")
        add_venue(db, key="k2", order_id="o2", order_hash="hash-2", state="filled")
        add_outbox(db, key="k2", order_id="o2", order_hash="hash-2", state="filled")
    return seed


def main() -> None:
    cases = [
        ("resident_order_holds", case_single("accepted", venue_state="resident"), False, None, FINALIZE_AT),
        ("unknown_order_holds", case_single("accepted", venue_state="unknown"), False, None, FINALIZE_AT),
        ("blocked_order_holds", case_single("accepted", venue_state="blocked"), False, None, FINALIZE_AT),
        ("pending_cancel_holds", case_single("accepted", outbox_state="pending"), False, None, FINALIZE_AT),
        ("dispatching_cancel_holds", case_single("accepted", outbox_state="dispatching"), False, None, FINALIZE_AT),
        ("retry_cancel_holds", case_single("accepted", outbox_state="retry"), False, None, FINALIZE_AT),
        ("blocked_cancel_holds", case_single("accepted", outbox_state="blocked"), False, None, FINALIZE_AT),
        ("accepted_without_pair_holds", case_single("accepted"), False, None, FINALIZE_AT),
        ("terminal_pair_hash_mismatch_holds", case_single("accepted", "cancelled", "cancelled", "wrong-hash"), False, None, FINALIZE_AT),
        ("terminal_pair_state_mismatch_holds", case_single("accepted", "cancelled", "filled"), False, None, FINALIZE_AT),
        ("venue_terminal_without_outbox_holds", case_single("accepted", venue_state="cancelled"), False, None, FINALIZE_AT),
        ("outbox_terminal_without_venue_holds", case_single("accepted", outbox_state="cancelled"), False, None, FINALIZE_AT),
        ("dispatching_sibling_holds", case_inflight_sibling("dispatching"), False, None, FINALIZE_AT),
        ("unknown_sibling_holds", case_inflight_sibling("unknown"), False, None, FINALIZE_AT),
        ("conflict_sibling_holds", case_inflight_sibling("conflict"), False, None, FINALIZE_AT),
        ("second_unindexed_accepted_holds", case_second_unindexed(), False, None, FINALIZE_AT),
        ("other_venue_resident_holds", case_single("accepted", venue_state="resident", venue_name="binance-spot-testnet"), False, None, FINALIZE_AT),
        ("paired_cancelled_order_finalizes", case_single("accepted", "cancelled", "cancelled"), True, None, FINALIZE_AT),
        ("paired_filled_order_finalizes", case_single("accepted", "filled", "filled"), True, None, FINALIZE_AT),
        ("all_accepted_orders_terminal_finalizes", case_all_terminal(), True, None, FINALIZE_AT),
        ("existing_revoked_at_is_write_once", case_single("accepted", "cancelled", "cancelled"), True, 777, FINALIZE_AT),
        ("no_revoke_request_is_noop", case_single("accepted", "cancelled", "cancelled"), False, None, None),
    ]
    for name, seed_case, expected, prior_revoked_at, requested_at in cases:
        run_case(name, seed_case, expected, prior_revoked_at, requested_at)
        print(f"PASS {name}")
    print(f"Futu adapter I4 predicate proof: n={len(cases)} k={len(cases)}; "
          "OpenD=0; Futu=0; provider=0; TypeScript core invoked=0")


if __name__ == "__main__":
    main()
