"""Brokers and the order router.

No real-money broker adapter is shipped. `ReceiverPaperBroker` talks to the L8 bridge, whose SQLite ledger is the only
path to any effect; `SimBroker` is in-memory for tests. A real broker must be added behind the same `Broker` Protocol and
must still be reached through L8 (the receiver stays the final authority); nothing here bypasses it.

`OrderRouter` is the single entry point: gate decision -> broker. It submits only when the gate said `allow`, and it is
idempotent on the order's idempotency key (a repeat returns the first result and never reaches the broker again).
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .receiver_client import Receiver, ReceiverError


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    idempotency_key: str
    replay: bool = False


@dataclass(frozen=True)
class Reject:
    reason: str
    idempotency_key: str
    held: bool = False          # true: not refused, waiting for human approval
    replay: bool = False


Result = Fill | Reject


@runtime_checkable
class Broker(Protocol):
    def submit(self, order: dict, idempotency_key: str) -> Result: ...
    def cancel(self, order_id: str) -> bool: ...
    def positions(self) -> dict[str, int]: ...
    def cash(self) -> float: ...


def _fingerprint(order: dict) -> str:
    return hashlib.sha256(json.dumps(order, sort_keys=True, default=str).encode()).hexdigest()


def _valid(order: dict) -> str | None:
    if order.get("side") not in ("buy", "sell"):
        return "side must be buy or sell"
    q = order.get("quantity")
    if not isinstance(q, int) or isinstance(q, bool) or q <= 0:
        return "quantity must be a positive integer"
    p = order.get("limit_price", order.get("limitPrice"))
    if not isinstance(p, (int, float)) or isinstance(p, bool) or p <= 0:
        return "limit price must be a positive number"
    if not order.get("symbol"):
        return "symbol is required"
    return None


class SimBroker:
    """In-memory broker for tests. Fills at the order's limit price; refuses to oversell or overspend."""

    def __init__(self, cash: float = 100_000.0):
        self._cash = float(cash)
        self._pos: dict[str, int] = {}
        self._fills: dict[str, Fill] = {}
        self._seen: dict[str, str] = {}
        self._lock = threading.Lock()
        self._n = 0

    def submit(self, order: dict, idempotency_key: str) -> Result:
        with self._lock:
            fp = _fingerprint(order)
            if idempotency_key in self._seen:
                if self._seen[idempotency_key] != fp:
                    return Reject("idempotency key reused with a different order", idempotency_key)
                f = self._fills.get(idempotency_key)
                return Fill(**{**f.__dict__, "replay": True}) if f else Reject("duplicate of a rejected order", idempotency_key, replay=True)
            bad = _valid(order)
            if bad:
                return Reject(bad, idempotency_key)
            self._seen[idempotency_key] = fp
            price = float(order.get("limit_price", order.get("limitPrice")))
            qty, sym, side = order["quantity"], order["symbol"], order["side"]
            if side == "buy" and price * qty > self._cash:
                return Reject("insufficient cash", idempotency_key)
            if side == "sell" and self._pos.get(sym, 0) < qty:
                return Reject("insufficient position", idempotency_key)
            self._n += 1
            self._cash += -price * qty if side == "buy" else price * qty
            self._pos[sym] = self._pos.get(sym, 0) + (qty if side == "buy" else -qty)
            fill = Fill(f"S-{self._n:05d}", sym, side, qty, price, idempotency_key)
            self._fills[idempotency_key] = fill
            return fill

    def cancel(self, order_id: str) -> bool:
        return False            # every simulated order fills immediately

    def positions(self) -> dict[str, int]:
        return {k: v for k, v in self._pos.items() if v}

    def cash(self) -> float:
        return self._cash


class ReceiverPaperBroker:
    """Paper broker whose only effect is a call to the L8 bridge `/propose`. The ledger there is the source of truth."""

    def __init__(self, receiver: Receiver, starting_cash: float = 100_000.0):
        self.receiver = receiver
        self._start = float(starting_cash)

    def submit(self, order: dict, idempotency_key: str) -> Result:
        bad = _valid(order)
        if bad:
            return Reject(bad, idempotency_key)
        price = order.get("limit_price", order.get("limitPrice"))
        try:
            r = self.receiver.propose(order["symbol"], order["side"], order["quantity"], float(price), client_order_id=idempotency_key)
        except ReceiverError as e:
            return Reject(f"receiver unavailable, nothing was placed: {e}", idempotency_key)    # fail closed
        replay = bool(r.get("replay"))
        d = r.get("decision")
        if d == "filled":
            return Fill(str(r.get("orderId")), order["symbol"], order["side"], order["quantity"],
                        float(r.get("trustedPrice") or price), idempotency_key, replay=replay)
        return Reject(str(r.get("reason") or d or "rejected"), idempotency_key, held=(d == "held"), replay=replay)

    def cancel(self, order_id: str) -> bool:
        return False            # the bridge has no per-order cancel; `Receiver.revoke()` ends the whole mandate

    def _filled(self) -> list[dict]:
        try:
            return [o for o in self.receiver.snapshot().get("orders", []) if o.get("status", "filled") == "filled"]
        except ReceiverError:
            return []

    def positions(self) -> dict[str, int]:
        pos: dict[str, int] = {}
        for o in self._filled():
            q = int(o.get("quantity", 0))
            pos[o["symbol"]] = pos.get(o["symbol"], 0) + (q if o.get("side") == "buy" else -q)
        return {k: v for k, v in pos.items() if v}

    def cash(self) -> float:
        c = self._start
        for o in self._filled():
            px = float(o.get("fillPrice") or o.get("trustedPrice") or o.get("limitPrice") or 0)
            n = float(o.get("notionalUsd") or px * int(o.get("quantity", 0)))
            c += -n if o.get("side") == "buy" else n
        return c


@dataclass
class OrderRouter:
    """gate decision -> broker. Refuses anything that is not an explicit `allow`; idempotent per key."""
    broker: Broker
    _results: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def route(self, order: dict, decision: dict, idempotency_key: str) -> Result:
        if not idempotency_key:
            return Reject("an idempotency key is required", "")
        fp = _fingerprint(order)
        with self._lock:
            prior = self._results.get(idempotency_key)
            if prior is not None:
                if prior[0] != fp:
                    return Reject("idempotency key reused with a different order", idempotency_key)
                r = prior[1]
                return type(r)(**{**r.__dict__, "replay": True})
            if not isinstance(decision, dict) or decision.get("decision") != "allow":
                d = decision.get("decision") if isinstance(decision, dict) else None
                reasons = decision.get("reasons") if isinstance(decision, dict) else None
                why = " ".join(reasons) if reasons else f"gate decision was {d!r}, not allow"
                return Reject(f"not sent to the broker: {why}", idempotency_key, held=(d == "hold"))
            result = self.broker.submit(order, idempotency_key)
            self._results[idempotency_key] = (fp, result)
            return result
