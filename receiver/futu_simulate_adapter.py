"""Fail-closed OpenD SIMULATE bridge for committed OrderGuard paper orders.

The only order source is the durable mesh ledger. This module has no REAL,
unlock, password, or arbitrary symbol path. Live OpenD use is gated on an
explicit local SIMULATE enable flag.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import importlib
import inspect
import json
import math
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote


HOST = "127.0.0.1"
PORT = 11111
TRD_ENV = "SIMULATE"
MAX_ORDER_NOTIONAL_USD = 12_500.0
MAX_QUOTE_AGE_SECONDS = 30.0
SIM_TYPE_TRANSLATION_DOC = "https://openapi.futunn.com/futu-api-doc/en/quick/demo.html"
# Keep aligned with hkex-equity-price-rules.ts. This applies only to the
# explicitly mapped MANDATE-M1 HK equity aliases, not every HK instrument.
HKEX_EQUITY_SPREAD_TABLE_VERSION = "code-01-phase-2-2026-08-03"
HKEX_EQUITY_CODE_01_PHASE_2_BANDS_MILLS: tuple[tuple[int, int], ...] = (
    (250, 1),
    (10_000, 5),
    (20_000, 10),
    (50_000, 20),
    (100_000, 50),
    (200_000, 100),
    (500_000, 200),
    (1_000_000, 500),
    (2_000_000, 1_000),
    (5_000_000, 2_000),
    (9_995_000, 5_000),
)
SYMBOLS: dict[str, tuple[str, str]] = {
    "0700.HK": ("HK", "HK.00700"),
    "9988.HK": ("HK", "HK.09988"),
}


def _configured_symbols() -> dict[str, tuple[str, str]]:
    """Combine legacy paper symbols with the explicit MANDATE-M1 route config."""
    path = os.environ.get("ORDERGUARD_FUTU_CONFIG")
    if not path:
        path = str(Path(__file__).resolve().parent / "futu-adapter" / "config.json")
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(SYMBOLS)
    except (OSError, json.JSONDecodeError) as error:
        raise AdapterError("futu_config_invalid", "The Futu symbol-routing config could not be read.") from error
    if not isinstance(config, dict) or config.get("schema_version") != 1 or config.get("trd_env") != TRD_ENV:
        raise AdapterError("futu_config_invalid", "The Futu config must use schema version 1 and SIMULATE only.")
    configured = dict(SYMBOLS)
    rows = config.get("symbols")
    if not isinstance(rows, dict):
        raise AdapterError("futu_config_invalid", "The Futu symbol-routing map is missing.")
    for symbol, route in rows.items():
        if not isinstance(symbol, str) or not isinstance(route, dict):
            raise AdapterError("futu_config_invalid", "A configured Futu symbol route is malformed.")
        market, code = route.get("market"), route.get("code")
        if market != "HK" or not isinstance(code, str) or not code.startswith("HK."):
            raise AdapterError("futu_config_invalid", "Only explicit HK simulator symbol routes are supported in this config.")
        configured[symbol] = (market, code)
    return configured


def _configured_m1_symbols() -> dict[str, tuple[str, str]]:
    """Return only synthetic aliases explicitly marked for MANDATE-M1 routing."""
    path = os.environ.get("ORDERGUARD_FUTU_CONFIG")
    if not path:
        path = str(Path(__file__).resolve().parent / "futu-adapter" / "config.json")
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AdapterError("futu_config_invalid", "The MANDATE-M1 symbol map could not be read.") from error
    if not isinstance(config, dict) or config.get("schema_version") != 1 or config.get("trd_env") != TRD_ENV:
        raise AdapterError("futu_config_invalid", "The MANDATE-M1 symbol map must use SIMULATE only.")
    rows = config.get("symbols")
    if not isinstance(rows, dict):
        raise AdapterError("futu_config_invalid", "The MANDATE-M1 symbol map is missing.")
    mapped: dict[str, tuple[str, str]] = {}
    for symbol, route in rows.items():
        if not isinstance(route, dict) or route.get("fictional_mandate_symbol") is not True:
            continue
        market, code = route.get("market"), route.get("code")
        if market != "HK" or not isinstance(code, str) or not code.startswith("HK."):
            raise AdapterError("futu_config_invalid", "A MANDATE-M1 route must map to an HK simulator ticker.")
        mapped[symbol] = (market, code)
    return mapped


def _is_hkex_equity_code_01_price_minor(amount_minor: int) -> bool:
    """Check an HKD limit price in cents against the current Code 01 grid.

    Mills (HKD 0.001) preserve the HKD 0.005 tick exactly. Prices outside
    the published band table fail closed until the schedule is updated.
    """
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
        return False
    price_mills = amount_minor * 10
    for max_price_mills, tick_mills in HKEX_EQUITY_CODE_01_PHASE_2_BANDS_MILLS:
        if price_mills <= max_price_mills:
            return price_mills % tick_mills == 0
    return False


class AdapterError(Exception):
    def __init__(self, code: str, message: str, diagnostic: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class LedgerOrder:
    idempotency_key: str
    order_id: str
    order_hash: str
    order: dict[str, Any]
    execution: dict[str, Any]


def _canonical(value: Any) -> str:
    """Match the mesh's sorted-key JSON encoding for the bounded order schema."""
    if value is None or isinstance(value, (str, bool, int)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            raise AdapterError("invalid_ledger_order", "Ledger order contains a non-finite number.")
        if value == 0:
            return "0"
        if value.is_integer():
            return str(int(value))
        rendered = repr(value)
        if "e" in rendered:
            mantissa, exponent = rendered.split("e", 1)
            sign = "+" if int(exponent) >= 0 else "-"
            rendered = mantissa + "e" + sign + str(abs(int(exponent)))
        return rendered
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        fields = []
        for key in sorted(value):
            fields.append(_canonical(str(key)) + ":" + _canonical(value[key]))
        return "{" + ",".join(fields) + "}"
    raise AdapterError("invalid_ledger_order", "Ledger order contains an unsupported value.")


def _mesh_order_hash(order: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical(order).encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _safe_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 180 or any(ord(ch) < 32 for ch in value):
        raise AdapterError("invalid_request", f"A bounded {label} is required.")
    return value


class DispatchJournal:
    """A durable at-most-once journal stored beside the mesh paper ledger."""

    def __init__(self, database_path: str):
        if database_path == ":memory:" or database_path.startswith("file:"):
            raise AdapterError("durable_ledger_required", "OpenD SIMULATE requires the file-backed mesh ledger.")
        path = Path(database_path).expanduser().resolve()
        if not path.is_file():
            raise AdapterError("ledger_missing", "The committed mesh paper ledger does not exist.")
        self.connection = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS futu_simulate_dispatches (
                idempotency_key TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                order_hash TEXT NOT NULL,
                remark TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL CHECK (state IN ('prepared','dispatching','accepted','unknown','rejected','conflict')),
                broker_order_id TEXT,
                account_id TEXT,
                account_masked TEXT,
                reconciliation_json TEXT,
                updated_at_ms INTEGER NOT NULL
            )"""
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(futu_simulate_dispatches)")}
        if "reconciliation_json" not in columns:
            self.connection.execute("ALTER TABLE futu_simulate_dispatches ADD COLUMN reconciliation_json TEXT")
        mandate_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(human_mandates)")}
        if mandate_columns and "revoke_requested_at" not in mandate_columns:
            self.connection.execute("ALTER TABLE human_mandates ADD COLUMN revoke_requested_at INTEGER")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS futu_simulate_position_baselines (
                account_id TEXT NOT NULL,
                market TEXT NOT NULL,
                code TEXT NOT NULL,
                quantity REAL NOT NULL,
                captured_at_ms INTEGER NOT NULL,
                PRIMARY KEY (account_id, market, code)
            )"""
        )

    def close(self) -> None:
        self.connection.close()

    def load_committed_order(self, idempotency_key: str, order_id: str) -> LedgerOrder:
        row = self.connection.execute(
            "SELECT order_id, order_hash, order_json, execution_json, cancelled, market_quote_result_json, market_quote_receipt_json "
            "FROM paper_orders WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            raise AdapterError("ledger_commit_missing", "No committed paper-ledger row matches this idempotency key.")
        stored_order_id, order_hash, order_json, execution_json, cancelled, market_quote_result_json, market_quote_receipt_json = row
        if stored_order_id != order_id or bool(cancelled):
            raise AdapterError("ledger_order_mismatch", "The requested order is not the active committed ledger order.")
        try:
            order = json.loads(order_json)
            execution = json.loads(execution_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise AdapterError("invalid_ledger_order", "The committed ledger order is malformed.") from error
        if not isinstance(order, dict) or not isinstance(execution, dict):
            raise AdapterError("invalid_ledger_order", "The committed ledger order is malformed.")
        if order.get("orderId") != order_id:
            raise AdapterError("ledger_order_mismatch", "The committed order body does not match its ledger ID.")
        if _mesh_order_hash(order) != order_hash:
            raise AdapterError("ledger_digest_mismatch", "The committed order digest does not match the stored order.")
        if execution.get("status") not in {"accepted", "filled"}:
            raise AdapterError("ledger_commit_not_approved", "The mesh ledger has no approved execution for this order.")
        if isinstance(order.get("symbol"), str) and order["symbol"] in _configured_m1_symbols():
            try:
                authorization = self.connection.execute(
                    "SELECT order_id, order_hash, mandate_id, mandate_hash, quote_receipt_hash, second_lock_decision, version "
                    "FROM futu_m1_dispatch_authorizations WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                quote_result = json.loads(market_quote_result_json)
                quote_receipt = json.loads(market_quote_receipt_json)
            except (sqlite3.Error, TypeError, json.JSONDecodeError) as error:
                raise AdapterError("m1_authorization_missing", "The committed synthetic order has no verifiable MANDATE-M1 Futu authorization.") from error
            if (authorization is None or authorization[0] != order_id or authorization[1] != order_hash
                    or not isinstance(authorization[2], str) or not authorization[2]
                    or not isinstance(authorization[3], str) or len(authorization[3]) != 43
                    or authorization[4] != _mesh_order_hash(quote_receipt)
                    or authorization[5] != "allow" or authorization[6] != "MANDATE-M1-v1.0.0"
                    or not isinstance(quote_result, dict) or quote_result.get("provenance") != "Futu OpenD SIMULATE quote snapshot."):
                raise AdapterError("m1_authorization_mismatch", "The Futu dispatch authorization does not match the MANDATE-M1 ledger evidence.")
            quote_rows = quote_result.get("quotes")
            if not isinstance(quote_rows, list) or len(quote_rows) != 1 or not isinstance(quote_rows[0], dict):
                raise AdapterError("m1_authorization_mismatch", "The MANDATE-M1 ledger row is missing its signed OpenD quote.")
            quote = quote_rows[0]
            expected_route = _configured_m1_symbols().get(order.get("symbol"))
            if (expected_route is None or quote.get("symbol") != order.get("symbol")
                    or quote.get("futuCode") != expected_route[1]
                    or quote.get("provenance") != "futu-opend-simulate"
                    or quote.get("currency") != "HKD"):
                raise AdapterError("m1_authorization_mismatch", "The signed OpenD quote is not bound to the configured MANDATE-M1 symbol mapping.")
            lot_size = quote.get("lotSize")
            quantity = order.get("quantity")
            if (isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size < 1
                    or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity % lot_size != 0):
                raise AdapterError("m1_board_lot_mismatch", "The committed MANDATE-M1 quantity is not a multiple of its signed OpenD board lot.")
        return LedgerOrder(idempotency_key, order_id, order_hash, order, execution)

    def reserve(self, order: LedgerOrder, remark: str, account_id: str | None) -> dict[str, Any]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT order_id, order_hash, remark, state, broker_order_id, account_id, account_masked "
                "FROM futu_simulate_dispatches WHERE idempotency_key = ?",
                (order.idempotency_key,),
            ).fetchone()
            now_ms = int(time.time() * 1000)
            if row is None:
                masked = "****" + account_id[-4:] if account_id else None
                self.connection.execute(
                    "INSERT INTO futu_simulate_dispatches "
                    "(idempotency_key, order_id, order_hash, remark, state, account_id, account_masked, updated_at_ms) "
                    "VALUES (?, ?, ?, ?, 'prepared', ?, ?, ?)",
                    (order.idempotency_key, order.order_id, order.order_hash, remark, account_id, masked, now_ms),
                )
                row = (order.order_id, order.order_hash, remark, "prepared", None, account_id, masked)
            elif row[0] != order.order_id or row[1] != order.order_hash or row[2] != remark:
                raise AdapterError("dispatch_idempotency_conflict", "This ledger key is already bound to a different Futu order.")
            elif row[5] is not None and account_id is not None and row[5] != account_id:
                raise AdapterError("paper_account_changed", "The paper account differs from the account reserved for this order.")
            elif row[5] is None and account_id:
                masked = "****" + account_id[-4:]
                self.connection.execute(
                    "UPDATE futu_simulate_dispatches SET account_id = ?, account_masked = ?, updated_at_ms = ? "
                    "WHERE idempotency_key = ?",
                    (account_id, masked, now_ms, order.idempotency_key),
                )
                row = (*row[:5], account_id, masked)
            self.connection.execute("COMMIT")
            return {
                "order_id": row[0], "order_hash": row[1], "remark": row[2], "state": row[3],
                "broker_order_id": row[4], "account_id": row[5], "account_masked": row[6],
            }
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def set_state(self, key: str, state: str, broker_order_id: str | None = None) -> str:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            current = self.connection.execute(
                "SELECT state, broker_order_id FROM futu_simulate_dispatches WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if current is None:
                raise AdapterError("dispatch_journal_missing", "The durable Futu dispatch reservation disappeared.")
            current_state, current_broker_id = current
            next_state, next_broker_id = current_state, current_broker_id
            if current_state == "accepted":
                if state == "conflict":
                    next_state = "conflict"
                elif state == "accepted" and broker_order_id and current_broker_id and broker_order_id != current_broker_id:
                    next_state = "conflict"
            elif current_state == "conflict":
                # A broker-row match can resolve a false conflict; it cannot
                # authorize another send. Keep the original ID when available.
                if state == "accepted" and broker_order_id and current_broker_id in {None, broker_order_id}:
                    next_state, next_broker_id = "accepted", broker_order_id
            elif current_state not in {"rejected", "conflict"}:
                next_state = state
                if broker_order_id:
                    next_broker_id = broker_order_id
            now_ms = int(time.time() * 1000)
            self.connection.execute(
                "UPDATE futu_simulate_dispatches SET state = ?, broker_order_id = ?, updated_at_ms = ? "
                "WHERE idempotency_key = ?",
                (next_state, next_broker_id, now_ms, key),
            )
            self._finalize_pending_mandate_revocation(key, now_ms)
            self.connection.execute("COMMIT")
            return next_state
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def _finalize_pending_mandate_revocation(self, key: str, now_ms: int) -> None:
        required = {
            "human_mandates",
            "futu_m1_dispatch_authorizations",
            "futu_simulate_dispatches",
            "venue_mandate_orders",
            "mandate_cancellation_outbox",
        }
        present = {row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?, ?, ?)", tuple(required),
        )}
        if present != required:
            return
        self.connection.execute(
            "UPDATE human_mandates SET revoked_at = COALESCE(revoked_at, ?), revoke_requested_at = NULL "
            "WHERE mandate_id = (SELECT mandate_id FROM futu_m1_dispatch_authorizations WHERE idempotency_key = ?) "
            "AND revoke_requested_at IS NOT NULL AND NOT EXISTS ("
            "SELECT 1 FROM futu_m1_dispatch_authorizations a JOIN futu_simulate_dispatches d "
            "ON d.idempotency_key = a.idempotency_key WHERE a.mandate_id = human_mandates.mandate_id "
            "AND d.state IN ('dispatching','unknown','conflict')) AND NOT EXISTS ("
            "SELECT 1 FROM venue_mandate_orders v WHERE v.mandate_id = human_mandates.mandate_id "
            "AND v.state IN ('resident','unknown','blocked')) AND NOT EXISTS ("
            "SELECT 1 FROM mandate_cancellation_outbox c WHERE c.mandate_id = human_mandates.mandate_id "
            "AND c.state IN ('pending','dispatching','retry','blocked')) AND NOT EXISTS ("
            "SELECT 1 FROM futu_m1_dispatch_authorizations a JOIN futu_simulate_dispatches d "
            "ON d.idempotency_key = a.idempotency_key WHERE a.mandate_id = human_mandates.mandate_id "
            "AND d.state = 'accepted' AND NOT EXISTS ("
            "SELECT 1 FROM venue_mandate_orders v JOIN mandate_cancellation_outbox c "
            "ON c.venue = v.venue AND c.mandate_id = v.mandate_id AND c.order_id = v.order_id "
            "WHERE v.venue = 'futu-simulate' AND v.mandate_id = a.mandate_id "
            "AND v.idempotency_key = a.idempotency_key AND v.order_id = a.order_id "
            "AND v.order_hash = a.order_hash AND v.state IN ('cancelled','filled') "
            "AND c.venue = v.venue AND c.idempotency_key = a.idempotency_key "
            "AND c.state = v.state "
            "AND c.order_hash = a.order_hash AND c.state IN ('cancelled','filled'))) ",
            (now_ms, key),
        )

    def set_reconciliation(self, key: str, detail: dict[str, Any]) -> None:
        encoded = json.dumps(detail, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        self.connection.execute(
            "UPDATE futu_simulate_dispatches SET reconciliation_json = ?, updated_at_ms = ? WHERE idempotency_key = ?",
            (encoded, int(time.time() * 1000), key),
        )

    def claim_dispatch(self, key: str) -> bool:
        """Only one process can cross the external send boundary for this key."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.connection.execute(
                "UPDATE futu_simulate_dispatches SET state = 'dispatching', updated_at_ms = ? "
                "WHERE idempotency_key = ? AND state = 'prepared'",
                (int(time.time() * 1000), key),
            )
            self.connection.execute("COMMIT")
            return cursor.rowcount == 1
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def claim_m1_dispatch(self, key: str, order_id: str, order_hash: str) -> str:
        """Persist the M1 final mandate check and point-of-no-return claim.

        `revokeHumanMandate()` writes `human_mandates` in this same SQLite
        database. BEGIN IMMEDIATE orders revocation against this durable claim.
        A winning claim is never repeated after restart; remark reconciliation
        resolves whether the external effect happened. Ambiguous claims keep a
        pending revoke until the journal becomes terminal.
        """
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            now_ms = int(time.time() * 1000)
            row = self.connection.execute(
                "SELECT d.state, a.order_id, a.order_hash, a.second_lock_decision, a.version, "
                "m.mandate_id, m.mandate_hash, m.revoked_at, m.expires_at, m.revoke_requested_at, "
                "p.order_id, p.order_hash, p.cancelled "
                "FROM futu_simulate_dispatches d "
                "LEFT JOIN futu_m1_dispatch_authorizations a ON a.idempotency_key = d.idempotency_key "
                "LEFT JOIN human_mandates m ON m.mandate_id = a.mandate_id AND m.mandate_hash = a.mandate_hash "
                "LEFT JOIN paper_orders p ON p.idempotency_key = d.idempotency_key "
                "WHERE d.idempotency_key = ?",
                (key,),
            ).fetchone()
            if row is None or row[0] != "prepared":
                self.connection.execute("COMMIT")
                return "already_claimed"
            active = (
                row[1] == order_id and row[2] == order_hash and row[3] == "allow"
                and row[4] == "MANDATE-M1-v1.0.0" and isinstance(row[5], str)
                and isinstance(row[6], str) and row[7] is None
                and isinstance(row[8], int) and row[8] > int(time.time() * 1000) and row[9] is None
                and row[10] == order_id and row[11] == order_hash and row[12] == 0
            )
            if not active:
                self.connection.execute(
                    "UPDATE futu_simulate_dispatches SET state = 'rejected', updated_at_ms = ? "
                    "WHERE idempotency_key = ? AND state = 'prepared'",
                    (now_ms, key),
                )
                self._finalize_pending_mandate_revocation(key, now_ms)
                self.connection.execute("COMMIT")
                return "claim_ineligible"
            self.connection.execute(
                "UPDATE futu_simulate_dispatches SET state = 'dispatching', updated_at_ms = ? "
                "WHERE idempotency_key = ? AND state = 'prepared'",
                (int(time.time() * 1000), key),
            )
            self.connection.execute("COMMIT")
            return "claimed"
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def has_position_baseline(self, account_id: str, market: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM futu_simulate_position_baselines WHERE account_id = ? AND market = ? LIMIT 1",
            (account_id, market),
        ).fetchone()
        return row is not None

    def save_position_baseline(self, account_id: str, market: str, quantities: dict[str, float], codes: set[str]) -> None:
        now_ms = int(time.time() * 1000)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            for code in sorted(codes):
                self.connection.execute(
                    "INSERT OR IGNORE INTO futu_simulate_position_baselines "
                    "(account_id, market, code, quantity, captured_at_ms) VALUES (?, ?, ?, ?, ?)",
                    (account_id, market, code, quantities.get(code, 0.0), now_ms),
                )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def reconciliation_rows(self) -> list[tuple[Any, ...]]:
        return self.connection.execute(
            "SELECT d.idempotency_key, d.order_id, d.order_hash, d.remark, d.state, d.broker_order_id, "
            "d.account_id, d.account_masked, p.order_json, p.execution_json, d.reconciliation_json "
            "FROM futu_simulate_dispatches d JOIN paper_orders p ON p.idempotency_key = d.idempotency_key "
            "ORDER BY d.updated_at_ms, d.order_id"
        ).fetchall()

    def position_baselines(self, account_id: str, market: str) -> dict[str, float]:
        rows = self.connection.execute(
            "SELECT code, quantity FROM futu_simulate_position_baselines WHERE account_id = ? AND market = ?",
            (account_id, market),
        ).fetchall()
        return {str(code): float(quantity) for code, quantity in rows}


def _normalize_order(ledger_order: LedgerOrder) -> dict[str, Any]:
    raw = ledger_order.order
    symbol = raw.get("symbol")
    symbols = _configured_symbols()
    if not isinstance(symbol, str) or symbol not in symbols:
        raise AdapterError("unsupported_symbol", "The committed order symbol is not in the Futu paper allowlist.")
    market, code = symbols[symbol]
    if raw.get("market") != market:
        raise AdapterError("symbol_market_mismatch", "The committed order market does not match the Futu symbol.")
    m1_symbols = _configured_m1_symbols()
    if symbol in m1_symbols:
        if (market != "HK" or raw.get("currency") != "HKD" or raw.get("side") != "buy"
                or raw.get("orderType") != "limit" or raw.get("session") != "hk_regular"
                or str(raw.get("timeInForce", "")).lower() != "day"):
            raise AdapterError("m1_scope_mismatch", "The committed row does not match MANDATE-M1 HK BUY LIMIT day scope.")
        quantity = raw.get("quantity")
        minor = raw.get("limitPriceMinor")
        if (isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 10_000
                or isinstance(minor, bool) or not isinstance(minor, int) or not 1 <= minor <= 1_000_000_000_000
                or quantity * minor > 4_000_000):
            raise AdapterError("m1_order_size_limit", "The committed MANDATE-M1 order exceeds its positive whole-share or HKD 40,000 limit.")
        if not _is_hkex_equity_code_01_price_minor(minor):
            raise AdapterError(
                "m1_price_tick_invalid",
                f"The committed MANDATE-M1 HKD limit price is off HKEX spread table Code 01 ({HKEX_EQUITY_SPREAD_TABLE_VERSION}).",
            )
        price = minor / 100
        if "limitPrice" in raw:
            try:
                supplied_price = Decimal(str(raw["limitPrice"]))
            except (InvalidOperation, ValueError):
                raise AdapterError("invalid_limit_price", "The committed MANDATE-M1 limit price is invalid.")
            if not supplied_price.is_finite() or supplied_price != Decimal(minor) / Decimal(100):
                raise AdapterError("m1_price_mismatch", "The committed limitPrice differs from its authorized HKD minor-unit price.")
        return {"market": "HK", "code": code, "side": "BUY", "quantity": quantity, "price": price}
    side = raw.get("side")
    if side not in {"buy", "sell", "BUY", "SELL"}:
        raise AdapterError("unsupported_side", "Only a canonical buy or sell order can be sent.")
    side = str(side).upper()
    quantity = raw.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise AdapterError("invalid_quantity", "Futu SIMULATE requires a positive whole-share quantity.")
    if raw.get("orderType") != "limit":
        raise AdapterError("limit_orders_only", "Futu SIMULATE dispatch only accepts the committed LIMIT order type.")
    price = raw.get("limitPrice")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not (0 < float(price) < float("inf")):
        raise AdapterError("invalid_limit_price", "A positive finite LIMIT price is required.")
    estimated = raw.get("estimatedNotionalUsd")
    if isinstance(estimated, bool) or not isinstance(estimated, (int, float)) or not (0 < float(estimated) <= MAX_ORDER_NOTIONAL_USD):
        raise AdapterError("order_size_limit", "The committed notional is absent or exceeds the mesh per-order limit.")
    expected_session = "hk_regular" if market == "HK" else "regular"
    if raw.get("session") != expected_session:
        raise AdapterError("unsupported_session", "Only regular-session paper orders can be sent to OpenD.")
    if str(raw.get("timeInForce", "")).lower() != "day":
        raise AdapterError("unsupported_time_in_force", "Only DAY time-in-force is accepted by this adapter.")
    return {
        "market": market,
        "code": code,
        "side": side,
        "quantity": quantity,
        "price": float(price),
    }


def _enum_name(value: Any) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    rendered = str(value)
    return rendered.rsplit(".", 1)[-1]


def _get_field(row: Any, name: str) -> Any:
    try:
        value = row[name]
    except (KeyError, TypeError, IndexError):
        value = getattr(row, name, None)
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    return value


def _finite_number(row: Any, name: str) -> float | None:
    value = _get_field(row, name)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _position_quantities(rows: Any) -> dict[str, float]:
    quantities: dict[str, float] = {}
    for row in _rows(rows):
        code = str(_get_field(row, "code") or "")
        quantity = _get_field(row, "qty")
        if not code or isinstance(quantity, bool):
            continue
        try:
            amount = float(quantity or 0)
        except (TypeError, ValueError):
            continue
        side = _enum_name(_get_field(row, "position_side"))
        signed = -amount if side == "SHORT" else amount
        quantities[code] = quantities.get(code, 0.0) + signed
    return quantities


def _position_baseline(rows: Any, configured_codes: set[str]) -> tuple[dict[str, float], set[str]]:
    quantities = _position_quantities(rows)
    return quantities, set(configured_codes) | set(quantities)


def _compare_position_quantities(
    expected: dict[str, float], actual: dict[str, float], aliases: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    """Compare ledger and broker position quantities, including broker-only codes."""
    results: list[dict[str, Any]] = []
    mismatches = 0
    for code in sorted(set(expected) | set(actual)):
        expected_quantity = expected.get(code, 0.0)
        actual_quantity = actual.get(code, 0.0)
        matches = abs(actual_quantity - expected_quantity) < 1e-6
        if not matches:
            mismatches += 1
        results.append({
            "symbol": aliases.get(code, code), "futu_code": code,
            "expected_quantity": expected_quantity, "actual_quantity": actual_quantity,
            "matches": matches,
        })
    return results, mismatches


def _rows(data: Any) -> list[Any]:
    if data is None:
        return []
    if hasattr(data, "iterrows"):
        return [row for _, row in data.iterrows()]
    if isinstance(data, list):
        return data
    raise AdapterError("opend_response_invalid", "OpenD returned an unsupported account or order response.")


def _account_for_market(gateway: Any, market: str, prior_account_id: str | None = None) -> dict[str, str]:
    expected_sim_type = "STOCK" if market == "HK" else "STOCK_AND_OPTION"
    rows = _rows(gateway.get_accounts())
    eligible = [
        row for row in rows
        if _enum_name(_get_field(row, "trd_env")) == TRD_ENV
        and _enum_name(_get_field(row, "sim_acc_type")) == expected_sim_type
        and str(_get_field(row, "acc_status") or "ACTIVE") == "ACTIVE"
    ]
    requested = prior_account_id or os.environ.get("ORDERGUARD_FUTU_SIM_ACCOUNT_ID")
    if requested:
        eligible = [row for row in eligible if str(_get_field(row, "acc_id")) == requested]
    if len(eligible) != 1:
        raise AdapterError("paper_account_not_unambiguous", "Exactly one active SIMULATE stock account must match this market and account selection.")
    account_id = str(_get_field(eligible[0], "acc_id"))
    if not account_id.isdigit() or account_id == "0":
        raise AdapterError("paper_account_invalid", "The selected SIMULATE account ID is invalid.")
    return {"account_id": account_id, "masked": "****" + account_id[-4:]}


def _order_classification(row: Any, expected: dict[str, Any], remark: str, trd_env: str = TRD_ENV) -> str | None:
    """Return the documented reconciliation bucket without rewriting broker fields."""
    if trd_env != TRD_ENV:
        return None
    status = _enum_name(_get_field(row, "order_status"))
    row_env = _get_field(row, "trd_env")
    if row_env is not None and _enum_name(row_env) != TRD_ENV:
        return None
    quantity = _finite_number(row, "qty")
    price = _finite_number(row, "price")
    dealt_qty = _finite_number(row, "dealt_qty")
    if quantity is None or price is None or dealt_qty is None:
        return None
    common_match = (
        str(_get_field(row, "remark") or "") == remark
        and str(_get_field(row, "code") or "") == expected["code"]
        and _enum_name(_get_field(row, "trd_side")) == expected["side"]
        and abs(quantity - expected["quantity"]) < 1e-9
        and abs(price - expected["price"]) < 1e-9
        and status in {
            "WAITING_SUBMIT", "SUBMITTING", "SUBMITTED",
            "FILLED_PART", "FILLED_ALL", "CANCELLING_PART", "CANCELLING_ALL",
            "CANCELLED_PART", "CANCELLED_ALL",
        }
        and 0 <= dealt_qty <= expected["quantity"]
    )
    if not common_match:
        return None
    broker_type = _enum_name(_get_field(row, "order_type"))
    if broker_type == "NORMAL":
        return "reconciled_strict"
    if trd_env != TRD_ENV or expected.get("market") != "HK" or broker_type != "ABSOLUTE_LIMIT":
        return None
    dealt_avg_price = _finite_number(row, "dealt_avg_price")
    if dealt_avg_price is None:
        return None
    if dealt_qty != 0 or dealt_avg_price != 0:
        return None
    # Only the adapter-generated OG idempotency remark is eligible for this
    # documented SIMULATE translation classification.
    if not remark.startswith("OG") or len(remark) != 34:
        return None
    return "reconciled_sim_type_translation"


def _lookup_order_record(gateway: Any, expected: dict[str, Any], account_id: str, remark: str) -> tuple[Any | None, bool]:
    end = dt.datetime.now().astimezone()
    # The regular order list retains filled/cancelled rows for 24 hours. The
    # gateway falls back to the historical list for older idempotency remarks.
    start = end - dt.timedelta(hours=23)
    query = gateway.find_orders
    query_args = {
        "code": expected["code"], "account_id": account_id,
        "start": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end": end.strftime("%Y-%m-%d %H:%M:%S"), "trd_env": TRD_ENV,
    }
    if "remark" in inspect.signature(query).parameters:
        query_args["remark"] = remark
    rows = _rows(query(**query_args))
    matches = [row for row in rows if str(_get_field(row, "remark") or "") == remark]
    if not matches:
        return None, False
    if len(matches) != 1:
        return None, True
    if _order_classification(matches[0], expected, remark, TRD_ENV) is None:
        return matches[0], True
    order_id = str(_get_field(matches[0], "order_id") or "")
    if not order_id:
        return matches[0], True
    return matches[0], False


def _lookup_order(gateway: Any, expected: dict[str, Any], account_id: str, remark: str) -> tuple[str | None, bool]:
    row, mismatch = _lookup_order_record(gateway, expected, account_id, remark)
    return (str(_get_field(row, "order_id")), False) if row is not None else (None, mismatch)


def dispatch_order(request: dict[str, Any], gateway_factory: Callable[[str], Any], journal: DispatchJournal) -> dict[str, Any]:
    _assert_environment_gate()
    if request.get("action") != "dispatch":
        raise AdapterError("unsupported_action", "Only an approved paper-order dispatch action is supported.")
    if request.get("trd_env") != TRD_ENV:
        raise AdapterError("simulate_only", "The adapter accepts TrdEnv.SIMULATE only.")
    forbidden = {"unlock", "unlock_trade", "trading_password", "trade_write"}
    if any(field in request for field in forbidden):
        raise AdapterError("forbidden_capability", "Unlock and live-trading capabilities are not accepted by this adapter.")
    if request.get("confirm_local_paper") is not True or request.get("confirm_futu_simulate") is not True:
        raise AdapterError("explicit_confirmation_required", "Both local paper confirmation and Futu SIMULATE confirmation are required.")
    idempotency_key = _safe_identifier(request.get("idempotency_key"), "ledger idempotency key")
    order_id = _safe_identifier(request.get("order_id"), "ledger order ID")
    ledger_order = journal.load_committed_order(idempotency_key, order_id)
    expected = _normalize_order(ledger_order)
    remark = "OG" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
    state = journal.reserve(ledger_order, remark, None)

    if state["state"] in {"rejected", "conflict"}:
        return _result(state["state"], None, state["account_masked"], remark, replayed=True)

    gateway = gateway_factory(expected["market"])
    try:
        account = _account_for_market(gateway, expected["market"], state.get("account_id"))
        if state.get("account_id") is None:
            state = journal.reserve(ledger_order, remark, account["account_id"])
        elif state["account_id"] != account["account_id"]:
            raise AdapterError("paper_account_changed", "The paper account changed while the order was being reconciled.")

        position_query = getattr(gateway, "get_positions", None)
        if callable(position_query) and not journal.has_position_baseline(account["account_id"], expected["market"]):
            before_positions = position_query(
                account_id=account["account_id"], market=expected["market"], trd_env=TRD_ENV,
            )
            configured_codes = {
                code for market, code in _configured_symbols().values() if market == expected["market"]
            }
            baseline_quantities, baseline_codes = _position_baseline(before_positions, configured_codes)
            journal.save_position_baseline(
                account["account_id"], expected["market"], baseline_quantities,
                baseline_codes,
            )

        broker_order_id, mismatch = _lookup_order(gateway, expected, account["account_id"], remark)
        if mismatch:
            journal.set_state(idempotency_key, "conflict")
            return _result("conflict", None, account["masked"], remark, replayed=True)
        if broker_order_id:
            journal.set_state(idempotency_key, "accepted", broker_order_id)
            return _result("accepted", broker_order_id, account["masked"], remark, replayed=True)
        if state["state"] in {"dispatching", "unknown"}:
            journal.set_state(idempotency_key, "unknown")
            return _result("unknown", None, account["masked"], remark, replayed=True)
        if state["state"] != "prepared":
            raise AdapterError("dispatch_state_invalid", "The durable Futu dispatch state is not eligible to send.")

        # Re-check the account immediately before the only send boundary.
        final_account = _account_for_market(gateway, expected["market"], account["account_id"])
        if final_account["account_id"] != account["account_id"]:
            raise AdapterError("paper_account_changed", "The paper account changed before order submission.")
        is_m1 = isinstance(ledger_order.order.get("symbol"), str) \
            and ledger_order.order["symbol"] in _configured_m1_symbols()
        if is_m1:
            dispatch_state = journal.claim_m1_dispatch(idempotency_key, ledger_order.order_id, ledger_order.order_hash)
            if dispatch_state == "claim_ineligible":
                return _result("rejected", None, account["masked"], remark, replayed=False)
            if dispatch_state == "already_claimed":
                broker_order_id, mismatch = _lookup_order(gateway, expected, account["account_id"], remark)
                if mismatch:
                    journal.set_state(idempotency_key, "conflict")
                    return _result("conflict", None, account["masked"], remark, replayed=True)
                if broker_order_id:
                    journal.set_state(idempotency_key, "accepted", broker_order_id)
                    return _result("accepted", broker_order_id, account["masked"], remark, replayed=True)
                journal.set_state(idempotency_key, "unknown")
                return _result("unknown", None, account["masked"], remark, replayed=True)

        if not is_m1 and not journal.claim_dispatch(idempotency_key):
            broker_order_id, mismatch = _lookup_order(gateway, expected, account["account_id"], remark)
            if mismatch:
                journal.set_state(idempotency_key, "conflict")
                return _result("conflict", None, account["masked"], remark, replayed=True)
            if broker_order_id:
                journal.set_state(idempotency_key, "accepted", broker_order_id)
                return _result("accepted", broker_order_id, account["masked"], remark, replayed=True)
            journal.set_state(idempotency_key, "unknown")
            return _result("unknown", None, account["masked"], remark, replayed=True)
        try:
            placement = gateway.place_order(
                code=expected["code"], side=expected["side"], quantity=expected["quantity"], price=expected["price"],
                account_id=account["account_id"], trd_env=TRD_ENV, remark=remark,
            )
        except Exception:
            if is_m1:
                try:
                    broker_order_id, mismatch = _lookup_order(gateway, expected, account["account_id"], remark)
                except Exception:
                    broker_order_id, mismatch = None, False
                if mismatch:
                    journal.set_state(idempotency_key, "conflict")
                    return _result("conflict", None, account["masked"], remark, replayed=True)
                if broker_order_id:
                    journal.set_state(idempotency_key, "accepted", broker_order_id)
                    return _result("accepted", broker_order_id, account["masked"], remark, replayed=True)
            journal.set_state(idempotency_key, "unknown")
            return _result("unknown", None, account["masked"], remark, replayed=False)

        if placement.get("ret_ok") is True and placement.get("order_id"):
            broker_order_id = str(placement["order_id"])
            journal.set_state(idempotency_key, "accepted", broker_order_id)
            return _result("accepted", broker_order_id, account["masked"], remark, replayed=False)

        # A negative SDK response can race with an accepted push; reconcile by remark.
        try:
            broker_order_id, mismatch = _lookup_order(gateway, expected, account["account_id"], remark)
        except Exception:
            broker_order_id, mismatch = None, False
        if broker_order_id and not mismatch:
            journal.set_state(idempotency_key, "accepted", broker_order_id)
            return _result("accepted", broker_order_id, account["masked"], remark, replayed=True)
        final_state = "conflict" if mismatch else "unknown" if placement.get("ret_ok") is True else "rejected"
        journal.set_state(idempotency_key, final_state)
        return _result(final_state, None, account["masked"], remark, replayed=False)
    finally:
        try:
            gateway.close()
        except Exception:
            pass


def _result(state: str, broker_order_id: str | None, account_masked: str | None, remark: str, replayed: bool) -> dict[str, Any]:
    return {
        "ok": state == "accepted",
        "state": state,
        "broker_order_id": broker_order_id,
        "paper_account": account_masked,
        "endpoint": f"{HOST}:{PORT}",
        "trd_env": TRD_ENV,
        "idempotency_remark": remark,
        "replayed_or_reconciled": replayed,
    }


class FutuOpenDGateway:
    """Thin official-SDK wrapper; instantiated only after all local gates pass."""

    def __init__(self, market: str):
        if market != "HK":
            raise AdapterError("hk_market_only", "This Futu SIMULATE adapter is restricted to Hong Kong stock orders.")
        sdk = _load_futu_sdk()
        market_enum = sdk.TrdMarket.HK if market == "HK" else sdk.TrdMarket.US
        firm = sdk.SecurityFirm.FUTUSECURITIES if market == "HK" else sdk.SecurityFirm.FUTUINC
        self.sdk = sdk
        self.context = sdk.OpenSecTradeContext(
            filter_trdmarket=market_enum, host=HOST, port=PORT, security_firm=firm,
        )

    def get_accounts(self) -> Any:
        result, data = self.context.get_acc_list()
        if result != self.sdk.RET_OK:
            raise AdapterError("account_query_failed", "OpenD did not return a valid account list.")
        return data

    def find_orders(self, *, code: str, account_id: str, start: str, end: str, trd_env: str, remark: str | None = None) -> Any:
        if trd_env != TRD_ENV:
            raise AdapterError("simulate_only", "The adapter accepts TrdEnv.SIMULATE only.")
        result, data = self.context.order_list_query(
            order_id="", code=code, start=start, end=end, trd_env=self.sdk.TrdEnv.SIMULATE,
            acc_id=int(account_id), refresh_cache=True,
        )
        if result != self.sdk.RET_OK:
            raise AdapterError("order_reconciliation_failed", "OpenD could not reconcile the SIMULATE order list.")
        active_rows = _rows(data)
        if remark is not None and not any(str(_get_field(row, "remark") or "") == remark for row in active_rows):
            result, data = self.context.history_order_list_query(
                code=code, start="", end="", trd_env=self.sdk.TrdEnv.SIMULATE,
                acc_id=int(account_id),
            )
            if result != self.sdk.RET_OK:
                raise AdapterError("order_reconciliation_failed", "OpenD could not reconcile the SIMULATE order history.")
            return active_rows + _rows(data)
        return data

    def order_inventory(self, *, account_id: str, start: str, end: str, trd_env: str) -> Any:
        if trd_env != TRD_ENV:
            raise AdapterError("simulate_only", "The adapter accepts TrdEnv.SIMULATE only.")
        result, data = self.context.order_list_query(
            order_id="", code="", start=start, end=end, trd_env=self.sdk.TrdEnv.SIMULATE,
            acc_id=int(account_id), refresh_cache=True,
        )
        if result != self.sdk.RET_OK:
            raise AdapterError("order_reconciliation_failed", "OpenD could not reconcile the SIMULATE order inventory.")
        order_rows = _rows(data)
        result, history_data = self.context.history_order_list_query(
            code="", start=start, end=end, trd_env=self.sdk.TrdEnv.SIMULATE,
            acc_id=int(account_id),
        )
        if result != self.sdk.RET_OK:
            raise AdapterError("order_reconciliation_failed", "OpenD could not reconcile the SIMULATE order history inventory.")
        # OpenD may remove a same-day cancelled paper order from order_list_query
        # before the 24-hour window expires. Keep the bounded history result in
        # the before/after inventory too; prefer the live-list row on duplicate IDs.
        by_order_id: dict[str, Any] = {}
        for row in order_rows + _rows(history_data):
            order_id = str(_get_field(row, "order_id") or "")
            if order_id:
                by_order_id.setdefault(order_id, row)
        return list(by_order_id.values())

    def get_positions(self, *, account_id: str, market: str, trd_env: str) -> Any:
        if trd_env != TRD_ENV:
            raise AdapterError("simulate_only", "The adapter accepts TrdEnv.SIMULATE only.")
        market_enum = self.sdk.TrdMarket.HK if market == "HK" else self.sdk.TrdMarket.US
        result, data = self.context.position_list_query(
            code="", position_market=market_enum, trd_env=self.sdk.TrdEnv.SIMULATE,
            acc_id=int(account_id), refresh_cache=True,
        )
        if result != self.sdk.RET_OK:
            raise AdapterError("position_reconciliation_failed", "OpenD could not reconcile SIMULATE positions.")
        return data

    def place_order(self, *, code: str, side: str, quantity: int, price: float, account_id: str, trd_env: str, remark: str) -> dict[str, Any]:
        if trd_env != TRD_ENV:
            raise AdapterError("simulate_only", "The adapter accepts TrdEnv.SIMULATE only.")
        trd_side = self.sdk.TrdSide.BUY if side == "BUY" else self.sdk.TrdSide.SELL
        result, data = self.context.place_order(
            price=price, qty=quantity, code=code, trd_side=trd_side,
            order_type=self.sdk.OrderType.NORMAL, trd_env=self.sdk.TrdEnv.SIMULATE,
            acc_id=int(account_id), remark=remark, time_in_force=self.sdk.TimeInForce.DAY,
            fill_outside_rth=False,
        )
        if result != self.sdk.RET_OK:
            return {"ret_ok": False}
        order_id = None
        try:
            values = data["order_id"].tolist()
            if values:
                order_id = str(values[0])
        except Exception:
            pass
        return {"ret_ok": True, "order_id": order_id}

    def close(self) -> None:
        self.context.close()


def read_live_order_inventory(gateway_factory: Callable[[str], Any] = FutuOpenDGateway) -> dict[str, Any]:
    """Read the recent full HK SIMULATE order list for before/after proof deltas."""
    _assert_environment_gate()
    gateway = gateway_factory("HK")
    try:
        account = _account_for_market(gateway, "HK")
        end = dt.datetime.now().astimezone()
        start = end - dt.timedelta(hours=23)
        rows = _rows(gateway.order_inventory(
            account_id=account["account_id"], start=start.strftime("%Y-%m-%d %H:%M:%S"),
            end=end.strftime("%Y-%m-%d %H:%M:%S"), trd_env=TRD_ENV,
        ))
        orders = []
        for row in rows:
            order_id = str(_get_field(row, "order_id") or "")
            if not order_id:
                continue
            orders.append({
                "order_id": order_id,
                "remark": str(_get_field(row, "remark") or ""),
                "code": str(_get_field(row, "code") or ""),
                "trd_side": _enum_name(_get_field(row, "trd_side")),
                "qty": _finite_number(row, "qty"),
                "price": _finite_number(row, "price"),
                "order_type_raw": _enum_name(_get_field(row, "order_type")),
                "order_status": _enum_name(_get_field(row, "order_status")),
                "dealt_qty": _finite_number(row, "dealt_qty"),
                "dealt_avg_price": _finite_number(row, "dealt_avg_price"),
            })
        orders.sort(key=lambda order: (order["order_id"], order["remark"]))
        return {
            "ok": True,
            "endpoint": f"{HOST}:{PORT}",
            "trd_env": TRD_ENV,
            "market": "HK",
            "paper_account": account["masked"],
            "window_start": start.strftime("%Y-%m-%d %H:%M:%S %z"),
            "window_end": end.strftime("%Y-%m-%d %H:%M:%S %z"),
            "order_count": len(orders),
            "orders": orders,
        }
    finally:
        try:
            gateway.close()
        except Exception:
            pass


def _load_futu_sdk() -> Any:
    """Import SDK with its unconditional logs redirected away from user paths."""
    import logging
    import logging.handlers

    original_makedirs = os.makedirs
    original_file_handler = logging.handlers.TimedRotatingFileHandler
    original_stream_handler = logging.StreamHandler

    def disabled_handler(*args: Any, **kwargs: Any) -> logging.NullHandler:
        return logging.NullHandler()

    def safe_makedirs(name: Any, *args: Any, **kwargs: Any) -> Any:
        rendered = os.fspath(name)
        if ".com.futunn.FutuOpenD/Log" in rendered:
            return original_makedirs(Path(__file__).resolve().parents[1] / ".orderguard" / "futu-opend-logs", exist_ok=True)
        return original_makedirs(name, *args, **kwargs)

    os.makedirs = safe_makedirs
    logging.handlers.TimedRotatingFileHandler = disabled_handler
    logging.StreamHandler = disabled_handler
    try:
        return importlib.import_module("futu")
    finally:
        os.makedirs = original_makedirs
        logging.handlers.TimedRotatingFileHandler = original_file_handler
        logging.StreamHandler = original_stream_handler


_QUOTE_CALL_SITES = {
    "receiver_prepare", "receiver_post_model", "scheduler_health", "dashboard_refresh",
    "replay", "adapter_cli", "diagnostic_probe",
}


def _quote_call_site(value: Any) -> str:
    return value if isinstance(value, str) and value in _QUOTE_CALL_SITES else "adapter_cli"


def _quote_response_shape(data: Any) -> dict[str, Any]:
    """Describe SDK payload shape only; never serialize quote or account values."""
    allowed_fields = {
        "code", "name", "last_price", "bid_price", "ask_price", "lot_size", "update_time",
        "data_time", "prev_close_price", "suspension", "market_state", "server_ver",
        "program_status_type", "qot_logined", "trd_logined", "market_hk",
    }
    if data is None:
        return {"kind": "null"}
    if isinstance(data, dict):
        names = {str(key) for key in data.keys()}
        return {"kind": "mapping", "field_names": sorted(names & allowed_fields), "other_field_count": len(names - allowed_fields)}
    columns = getattr(data, "columns", None)
    if columns is not None:
        try:
            names = {str(key) for key in list(columns)}
            rows = int(len(data))
            return {"kind": "table", "field_names": sorted(names & allowed_fields), "other_field_count": len(names - allowed_fields), "row_count": rows}
        except Exception:
            return {"kind": "table", "shape": "unavailable"}
    if isinstance(data, (list, tuple)):
        return {"kind": "sequence", "row_count": len(data)}
    return {"kind": type(data).__name__[:40]}


def read_simulate_quotes(call_site: str = "adapter_cli", requested_codes: Any = None) -> dict[str, Any]:
    """Read current HK quotes for configured routes or a validated subset; never opens trade context."""
    started = time.monotonic()
    stage = "environment_gate"
    diagnostic: dict[str, Any] = {
        "call_site": _quote_call_site(call_site), "source": "OpenD",
        "path": "upstream_opend", "cache_used": False,
        "endpoint": f"{HOST}:{PORT}", "stage": stage,
        "upstream_http_status": "not_exposed_by_futu_python_sdk",
        "response_body_summary": "OpenD SDK payload shape only; raw body is not exposed",
    }
    context = None
    try:
        _assert_environment_gate()
        stage = "sdk_load"
        diagnostic["stage"] = stage
        sdk = _load_futu_sdk()
        stage = "route_config"
        diagnostic["stage"] = stage
        configured_codes = {code for market, code in _configured_symbols().values() if market == "HK"}
        if requested_codes is None:
            code_set = sorted(configured_codes)
        else:
            if (not isinstance(requested_codes, list) or not requested_codes
                    or any(not isinstance(code, str) or code not in configured_codes for code in requested_codes)):
                diagnostic["validation_reason"] = "requested_quote_route_invalid"
                raise AdapterError("quote_route_invalid", "OpenD quote request must use configured HK simulator routes.")
            code_set = sorted(set(requested_codes))
        stage = "open_quote_context"
        diagnostic["stage"] = stage
        context = sdk.OpenQuoteContext(host=HOST, port=PORT)
        stage = "get_global_state"
        diagnostic["stage"] = stage
        call_started = time.monotonic()
        state_ret, global_state = context.get_global_state()
        diagnostic["global_state_ms"] = round((time.monotonic() - call_started) * 1000, 3)
        diagnostic["sdk_ret_code"] = int(state_ret) if isinstance(state_ret, int) else None
        diagnostic["response_body_summary"] = _quote_response_shape(global_state)
        if state_ret != sdk.RET_OK or not isinstance(global_state, dict):
            raise AdapterError("quote_market_state_failed", "OpenD did not return the HK market state.")
        market_state = str(global_state.get("market_hk") or "")
        diagnostic["market_state"] = market_state if market_state in {"MORNING", "AFTERNOON", "CLOSED", "PRE_MARKET", "AFTER_HOURS"} else "other"
        if market_state not in {"MORNING", "AFTERNOON"}:
            raise AdapterError("hk_market_closed", "OpenD does not report a regular HK trading session.")
        stage = "get_market_snapshot"
        diagnostic["stage"] = stage
        call_started = time.monotonic()
        result, data = context.get_market_snapshot(code_set)
        diagnostic["market_snapshot_ms"] = round((time.monotonic() - call_started) * 1000, 3)
        diagnostic["sdk_ret_code"] = int(result) if isinstance(result, int) else None
        diagnostic["response_body_summary"] = _quote_response_shape(data)
        if result != sdk.RET_OK:
            raise AdapterError("quote_snapshot_failed", "OpenD did not return the configured HK quote snapshot.")
        stage = "validate_snapshot_rows"
        diagnostic["stage"] = stage
        quotes: list[dict[str, Any]] = []
        for row in _rows(data):
            code = str(_get_field(row, "code") or "")
            if code not in code_set:
                diagnostic["validation_reason"] = "symbol_outside_configured_routes"
                raise AdapterError("quote_snapshot_invalid", "OpenD returned a symbol outside the configured HK route set.")
            try:
                last = float(_get_field(row, "last_price"))
                bid = float(_get_field(row, "bid_price"))
                ask = float(_get_field(row, "ask_price"))
                lot_value = float(_get_field(row, "lot_size"))
            except (TypeError, ValueError) as error:
                diagnostic["validation_reason"] = "numeric_quote_or_lot_field_invalid"
                raise AdapterError("quote_snapshot_invalid", "OpenD returned an invalid HK price or board lot size.") from error
            if not math.isfinite(lot_value) or lot_value < 1 or not lot_value.is_integer():
                diagnostic["validation_reason"] = "board_lot_not_positive_integer"
                raise AdapterError("quote_snapshot_invalid", "OpenD returned an invalid HK board lot size.")
            lot_size = int(lot_value)
            update_time = str(_get_field(row, "update_time") or "")
            suspended = _get_field(row, "suspension") is True
            timestamp_text = update_time.replace(" ", "T")
            if "T" in timestamp_text and not any(marker in timestamp_text for marker in ("+", "Z")):
                timestamp_text += "+08:00"
            try:
                quote_time = dt.datetime.fromisoformat(timestamp_text)
                if quote_time.tzinfo is None:
                    quote_time = quote_time.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
            except ValueError as error:
                diagnostic["validation_reason"] = "quote_timestamp_invalid"
                raise AdapterError("quote_snapshot_invalid", "OpenD returned an invalid HK quote timestamp.") from error
            age_seconds = (dt.datetime.now(dt.timezone.utc) - quote_time.astimezone(dt.timezone.utc)).total_seconds()
            if not (0 < last < float("inf")):
                diagnostic["validation_reason"] = "last_price_not_positive_finite"
                raise AdapterError("quote_snapshot_invalid", "OpenD returned an incomplete HK quote snapshot.")
            if not (0 < bid <= ask < float("inf")):
                diagnostic["validation_reason"] = "bid_ask_not_positive_ordered_finite"
                raise AdapterError("quote_snapshot_invalid", "OpenD returned an incomplete HK quote snapshot.")
            if not update_time:
                diagnostic["validation_reason"] = "quote_timestamp_missing"
                raise AdapterError("quote_snapshot_invalid", "OpenD returned an incomplete HK quote snapshot.")
            if age_seconds < -5:
                diagnostic["validation_reason"] = "quote_timestamp_too_far_in_future"
                raise AdapterError("quote_snapshot_invalid", "OpenD returned an incomplete HK quote snapshot.")
            if age_seconds > MAX_QUOTE_AGE_SECONDS:
                diagnostic["validation_reason"] = "quote_timestamp_stale"
                raise AdapterError("quote_snapshot_invalid", "OpenD returned an incomplete HK quote snapshot.")
            quotes.append({
                "code": code, "last_price": last, "bid_price": bid, "ask_price": ask,
                "lot_size": lot_size, "update_time": update_time,
                "suspension": suspended, "market_state": market_state,
            })
        if {quote["code"] for quote in quotes} != set(code_set):
            diagnostic["validation_reason"] = "configured_route_quote_missing"
            raise AdapterError("quote_snapshot_incomplete", "OpenD did not return every configured HK quote.")
        diagnostic.update({
            "stage": "complete", "quote_count": len(quotes),
            "returned_codes": sorted(quote["code"] for quote in quotes),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "error_code": None,
        })
        return {"ok": True, "endpoint": f"{HOST}:{PORT}", "trd_env": TRD_ENV, "quotes": quotes,
                "diagnostic": diagnostic}
    except AdapterError as error:
        diagnostic.update({
            "stage": stage, "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "error_code": error.code,
        })
        error.diagnostic = diagnostic
        raise
    except Exception as error:
        wrapped = AdapterError("quote_bridge_internal_error", "The OpenD quote bridge failed safely.")
        diagnostic.update({
            "stage": stage, "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "error_code": wrapped.code,
            "exception_type": type(error).__name__[:64],
        })
        wrapped.diagnostic = diagnostic
        raise wrapped from error
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass


def handle_request(request: dict[str, Any], gateway_factory: Callable[[str], Any] = FutuOpenDGateway) -> dict[str, Any]:
    _assert_environment_gate()
    database_path = os.environ.get("ORDERGUARD_LEDGER_DB")
    if not database_path:
        raise AdapterError("ledger_path_missing", "The mesh ledger path is required for the Futu adapter.")
    journal = DispatchJournal(database_path)
    try:
        return dispatch_order(request, gateway_factory, journal)
    finally:
        journal.close()


def reconcile_live(database_path: str, gateway_factory: Callable[[str], Any] = FutuOpenDGateway) -> dict[str, Any]:
    """Compare committed mesh fills with SIMULATE order-list and position state."""
    if database_path == ":memory:" or database_path.startswith("file:"):
        raise AdapterError("durable_ledger_required", "Futu reconciliation requires the file-backed mesh ledger.")
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise AdapterError("ledger_missing", "The committed mesh paper ledger does not exist.")
    journal = DispatchJournal(str(path))
    symbols = _configured_symbols()
    config_path = os.environ.get("ORDERGUARD_FUTU_CONFIG") or str(Path(__file__).resolve().parent / "futu-adapter" / "config.json")
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        aliases: dict[str, str] = {}
        for symbol, route in config["symbols"].items():
            if isinstance(route, dict) and isinstance(route.get("code"), str):
                aliases.setdefault(route["code"], str(route.get("display_symbol") or symbol))
        rows = journal.reconciliation_rows()
        accounts = sorted({(str(row[6]), json.loads(row[8]).get("market")) for row in rows if row[6] and row[8]})
        if not rows:
            return {
                "ok": True, "state": "empty", "endpoint": f"{HOST}:{PORT}", "trd_env": TRD_ENV,
                "counts": {"ledger_dispatches": 0, "accepted_orders": 0,
                           "reconciled_strict": 0, "reconciled_sim_type_translation": 0,
                           "unknown_orders": 0, "order_mismatches": 0, "position_mismatches": 0,
                           "account_mismatches": 0, "unresolved_orders": 0},
                "orders": [], "positions": [],
            }
        order_results: list[dict[str, Any]] = []
        position_results: list[dict[str, Any]] = []
        unbound_rows = [row for row in rows if not row[6] or not row[8]]
        order_mismatches = len(unbound_rows)
        for row in unbound_rows:
            order_results.append({
                "order_id": row[1], "broker_order_id": row[5], "state": "unbound",
                "paper_account": row[7], "trd_env": TRD_ENV, "remark_matched": False,
            })
        position_mismatches = 0
        account_mismatches = len(unbound_rows)
        accepted_count = 0
        reconciled_strict = 0
        reconciled_sim_type_translation = 0
        unknown_count = 0
        for account_id, market_value in accounts:
            if market_value != "HK":
                raise AdapterError("ledger_market_invalid", "A committed Futu ledger row has an unsupported market.")
            market = str(market_value)
            gateway = gateway_factory(market)
            try:
                account = _account_for_market(gateway, market, account_id)
                if account["account_id"] != account_id:
                    raise AdapterError("paper_account_changed", "The SIMULATE account differs from the ledger-bound account.")
                expected_positions = journal.position_baselines(account_id, market)
                if not expected_positions:
                    raise AdapterError("position_baseline_missing", "The SIMULATE position baseline was not recorded before dispatch.")
                actual_positions = _position_quantities(gateway.get_positions(
                    account_id=account_id, market=market, trd_env=TRD_ENV,
                ))
                relevant_rows = [row for row in rows if str(row[6]) == account_id and json.loads(row[8]).get("market") == market]
                for row in relevant_rows:
                    (key, order_id, order_hash, remark, state, broker_order_id, _, account_masked,
                     order_json, execution_json, _) = row
                    order = json.loads(order_json)
                    execution = json.loads(execution_json)
                    ledger_order = LedgerOrder(key, order_id, order_hash, order, execution)
                    expected = _normalize_order(ledger_order)
                    remark_matched = False
                    broker_status = None
                    broker_dealt_qty = None
                    broker_order_type = None
                    classification = None
                    broker_snapshot = None
                    if state in {"accepted", "unknown", "conflict"}:
                        broker_row, mismatch = _lookup_order_record(gateway, expected, account_id, remark)
                        remark_matched = broker_row is not None
                        if broker_row is not None:
                            broker_status = _enum_name(_get_field(broker_row, "order_status"))
                            broker_dealt_qty = _finite_number(broker_row, "dealt_qty")
                            broker_order_type = _enum_name(_get_field(broker_row, "order_type"))
                            classification = _order_classification(broker_row, expected, remark, TRD_ENV)
                            broker_snapshot = {
                                "order_id": str(_get_field(broker_row, "order_id") or ""),
                                "order_type": broker_order_type,
                                "order_type_raw": broker_order_type,
                                "order_status": broker_status,
                                "code": str(_get_field(broker_row, "code") or ""),
                                "trd_side": _enum_name(_get_field(broker_row, "trd_side")),
                                "qty": _finite_number(broker_row, "qty"),
                                "price": _finite_number(broker_row, "price"),
                                "dealt_qty": broker_dealt_qty,
                                "dealt_avg_price": _finite_number(broker_row, "dealt_avg_price"),
                                "remark": str(_get_field(broker_row, "remark") or ""),
                                "time_in_force": _enum_name(_get_field(broker_row, "time_in_force")),
                                "trd_env": _enum_name(_get_field(broker_row, "trd_env")) if _get_field(broker_row, "trd_env") is not None else None,
                            }
                        else:
                            broker_order_type = None
                        if mismatch:
                            if state != "conflict":
                                journal.set_state(key, "conflict")
                            order_mismatches += 1
                            state = "conflict"
                        elif broker_row is not None:
                            found_id = str(_get_field(broker_row, "order_id"))
                            if classification is None or (broker_order_id and broker_order_id != found_id):
                                journal.set_state(key, "conflict")
                                order_mismatches += 1
                                state = "conflict"
                            else:
                                ledger_execution_status = execution.get("status")
                                ledger_filled_qty = float(execution.get("filledQuantity", 0) or 0)
                                execution_matches = (
                                    abs(broker_dealt_qty - ledger_filled_qty) < 1e-6
                                    and ((ledger_execution_status == "filled" and broker_status == "FILLED_ALL")
                                         or (ledger_execution_status == "accepted" and broker_dealt_qty == 0))
                                )
                                if not execution_matches:
                                    journal.set_state(key, "conflict")
                                    order_mismatches += 1
                                    state = "conflict"
                                else:
                                    persisted_state = journal.set_state(key, "accepted", found_id)
                                    if persisted_state != "accepted":
                                        order_mismatches += 1
                                        state = "conflict"
                                    else:
                                        state, broker_order_id = "accepted", found_id
                        elif state == "accepted":
                            journal.set_state(key, "conflict")
                            order_mismatches += 1
                            state = "conflict"
                        elif state == "conflict":
                            order_mismatches += 1
                        else:
                            unknown_count += 1
                        if state != "accepted":
                            classification = None
                        final_classification = classification or ("mismatch" if state == "conflict" else state)
                        journal.set_reconciliation(key, {
                            "trd_env": TRD_ENV,
                            "market": market,
                            "classification": final_classification,
                            "expected_order_type": "NORMAL",
                            "broker": broker_snapshot,
                            "classification_doc_url": SIM_TYPE_TRANSLATION_DOC if classification == "reconciled_sim_type_translation" else None,
                        })
                    if state == "accepted":
                        accepted_count += 1
                        if classification == "reconciled_strict":
                            reconciled_strict += 1
                        elif classification == "reconciled_sim_type_translation":
                            reconciled_sim_type_translation += 1
                    order_results.append({
                        "order_id": order_id, "broker_order_id": broker_order_id,
                        "state": state, "paper_account": account_masked,
                        "trd_env": TRD_ENV, "remark_matched": remark_matched,
                        "expected_order_type": "NORMAL", "broker_order_type": broker_order_type,
                        "reconciliation_class": classification or ("mismatch" if state == "conflict" else None),
                        "classification_doc_url": SIM_TYPE_TRANSLATION_DOC if classification == "reconciled_sim_type_translation" else None,
                        "broker_status": broker_status, "broker_dealt_qty": broker_dealt_qty,
                        "broker": broker_snapshot,
                    })
                    if state == "accepted" and execution.get("status") == "filled":
                        code = expected["code"]
                        direction = 1 if expected["side"] == "BUY" else -1
                        expected_positions[code] = expected_positions.get(code, 0.0) + direction * float(execution.get("filledQuantity", 0) or 0)
                account_position_results, account_position_mismatches = _compare_position_quantities(
                    expected_positions, actual_positions, aliases,
                )
                position_results.extend(account_position_results)
                position_mismatches += account_position_mismatches
            finally:
                try:
                    gateway.close()
                except Exception:
                    pass
        counts = {
            "ledger_dispatches": len(rows), "accepted_orders": accepted_count,
            "reconciled_strict": reconciled_strict,
            "reconciled_sim_type_translation": reconciled_sim_type_translation,
            "unknown_orders": unknown_count, "order_mismatches": order_mismatches,
            "position_mismatches": position_mismatches, "account_mismatches": account_mismatches,
            "unresolved_orders": len(rows) - accepted_count,
        }
        clean = (accepted_count == len(rows)
                 and reconciled_strict + reconciled_sim_type_translation == accepted_count
                 and order_mismatches == 0
                 and position_mismatches == 0 and unknown_count == 0 and account_mismatches == 0)
        return {
            "ok": clean, "state": "reconciled" if clean else "mismatch",
            "endpoint": f"{HOST}:{PORT}", "trd_env": TRD_ENV,
            "counts": counts, "orders": order_results, "positions": position_results,
        }
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise AdapterError("reconcile_data_invalid", "The adapter could not parse its local reconciliation data.") from error
    finally:
        journal.close()


def read_dispatch_report(database_path: str) -> dict[str, Any]:
    """Read persisted B5 outcomes without loading the SDK or contacting OpenD."""
    if database_path == ":memory:" or database_path.startswith("file:"):
        raise AdapterError("durable_ledger_required", "The Futu SIMULATE report requires the file-backed mesh ledger.")
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        return {"ok": True, "trd_env": TRD_ENV, "endpoint": f"{HOST}:{PORT}", "counts": {}, "orders": []}
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        try:
            rows = connection.execute(
                "SELECT d.order_id, d.order_hash, d.state, d.broker_order_id, d.account_masked, d.updated_at_ms, "
                "d.remark, p.order_json FROM futu_simulate_dispatches d "
                "JOIN paper_orders p ON p.idempotency_key = d.idempotency_key "
                "ORDER BY d.updated_at_ms, d.order_id"
            ).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                rows = []
            else:
                raise AdapterError("report_read_failed", "The Futu dispatch report could not be read.") from error
    finally:
        connection.close()
    counts: dict[str, int] = {}
    orders: list[dict[str, Any]] = []
    for order_id, order_hash, state, broker_order_id, account_masked, updated_at_ms, remark, order_json in rows:
        counts[state] = counts.get(state, 0) + 1
        try:
            order = json.loads(order_json)
        except (TypeError, json.JSONDecodeError):
            order = {}
        if not isinstance(order, dict):
            order = {}
        created_at = dt.datetime.fromtimestamp(int(updated_at_ms) / 1000, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
        orders.append({
            "order_id": order_id,
            "order_sha256_b64url": order_hash,
            "symbol": order.get("symbol"),
            "market": order.get("market"),
            "side": order.get("side"),
            "quantity": order.get("quantity"),
            "limit_price": order.get("limitPrice"),
            "state": state,
            "broker_order_id": broker_order_id,
            "paper_account": account_masked,
            "updated_at_utc": created_at,
            "idempotency_remark": remark,
            "endpoint": f"{HOST}:{PORT}",
            "trd_env": TRD_ENV,
        })
    return {"ok": True, "trd_env": TRD_ENV, "endpoint": f"{HOST}:{PORT}", "counts": counts, "orders": orders}


def _assert_environment_gate() -> None:
    if (
        os.environ.get("ORDERGUARD_FUTU_SIMULATE_ENABLED") != "1"
        or os.environ.get("ORDERGUARD_MESH_MODE") == "containers"
    ):
        raise AdapterError("futu_simulate_gate_closed", "OpenD SIMULATE requires explicit local adapter enablement.")


def main() -> int:
    try:
        line = sys.stdin.readline()
        if not line:
            raise AdapterError("request_missing", "A single JSON dispatch request is required on stdin.")
        request = json.loads(line)
        if not isinstance(request, dict):
            raise AdapterError("invalid_request", "A JSON object is required.")
        if request.get("action") == "report":
            database_path = os.environ.get("ORDERGUARD_LEDGER_DB")
            if not database_path:
                raise AdapterError("ledger_path_missing", "The mesh ledger path is required for the Futu report.")
            result = read_dispatch_report(database_path)
            sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
            return 0
        if request.get("action") == "reconcile":
            _assert_environment_gate()
            database_path = os.environ.get("ORDERGUARD_LEDGER_DB")
            if not database_path:
                raise AdapterError("ledger_path_missing", "The mesh ledger path is required for Futu reconciliation.")
            result = reconcile_live(database_path)
            sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
            return 0 if result.get("ok") else 3
        if request.get("action") == "quotes":
            call_site = request.get("call_site")
            result = read_simulate_quotes(call_site if isinstance(call_site, str) else "adapter_cli", request.get("codes"))
            sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
            return 0
        result = handle_request(request)
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        return 0 if result.get("ok") else 2
    except AdapterError as error:
        payload = {"ok": False, "state": "refused", "code": error.code}
        if isinstance(error.diagnostic, dict):
            payload["diagnostic"] = error.diagnostic
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        return 2
    except (json.JSONDecodeError, UnicodeDecodeError):
        sys.stdout.write('{"ok":false,"state":"refused","code":"invalid_request"}\n')
        return 2
    except Exception:
        # Do not emit SDK exception text: it may contain account or session details.
        sys.stdout.write('{"ok":false,"state":"unknown","code":"adapter_internal_error"}\n')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
