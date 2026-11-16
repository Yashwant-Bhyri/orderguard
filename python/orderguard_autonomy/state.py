"""The authoritative portfolio state (design section 3B).

S_t = (P_t, O_t, B_t, M_t, A_t): filled positions, outstanding orders, risk budgets and reservations, trusted market data,
active authorizations. Admission is linearizable per risk domain: every order is admitted against a state that already includes
every earlier admitted order. Capacity is held in a hierarchical escrow (firm, book, agent): a child admits against its own
allocation without a global lock and asks its parent for more. Uncertain broker states keep their reservation until reconciled.

Three pieces:

    PortfolioState + apply_event   the state is a pure fold over events, so it can always be rebuilt from the log
    ReservationLedger              the single writer: appends events to a hash-chained log with signed checkpoints, under a fencing
                                   token so a deposed writer can never append again (no consensus needed inside one firm)
    EscrowNode                     one node of the hierarchical escrow; capacity flows down on request and back up when idle
"""
from __future__ import annotations

import copy
import threading
from dataclasses import asdict, dataclass, field, replace
from enum import Enum

from ._crypto import public_b64, sha256_hex, sign_b64, verify_b64


class Lifecycle(str, Enum):
    PROPOSED = "proposed"
    POLICY_VALIDATED = "policy_validated"
    RISK_RESERVED = "risk_reserved"
    SUBMITTED = "submitted"
    UNCERTAIN = "uncertain"                 # sent, no acknowledgement: the reservation stays held
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELED = "canceled"
    RECONCILED = "reconciled"


L = Lifecycle
TRANSITIONS: dict[Lifecycle, frozenset[Lifecycle]] = {
    L.PROPOSED: frozenset({L.POLICY_VALIDATED, L.REJECTED}),
    L.POLICY_VALIDATED: frozenset({L.RISK_RESERVED, L.REJECTED}),
    L.RISK_RESERVED: frozenset({L.SUBMITTED, L.CANCELED, L.REJECTED}),
    L.SUBMITTED: frozenset({L.ACKNOWLEDGED, L.UNCERTAIN, L.PARTIALLY_FILLED, L.FILLED, L.REJECTED, L.CANCELED}),
    L.UNCERTAIN: frozenset({L.ACKNOWLEDGED, L.PARTIALLY_FILLED, L.FILLED, L.REJECTED, L.CANCELED}),
    L.ACKNOWLEDGED: frozenset({L.PARTIALLY_FILLED, L.FILLED, L.CANCELED, L.UNCERTAIN}),
    L.PARTIALLY_FILLED: frozenset({L.PARTIALLY_FILLED, L.FILLED, L.CANCELED, L.UNCERTAIN}),
    L.FILLED: frozenset({L.RECONCILED}),
    L.REJECTED: frozenset({L.RECONCILED}),
    L.CANCELED: frozenset({L.RECONCILED}),
    L.RECONCILED: frozenset(),
}
WORKING = frozenset({L.RISK_RESERVED, L.SUBMITTED, L.UNCERTAIN, L.ACKNOWLEDGED, L.PARTIALLY_FILLED})
TERMINAL = frozenset({L.FILLED, L.REJECTED, L.CANCELED, L.RECONCILED})


class InvalidTransition(Exception):
    pass


@dataclass(frozen=True)
class WorkingOrder:
    order_id: str
    agent: str
    contract_id: str
    symbol: str
    side: str
    quantity: float
    filled: float
    limit_price: float
    state: Lifecycle
    idempotency_key: str
    venue: str = "default"

    @property
    def sign(self) -> int:
        return 1 if self.side == "buy" else -1

    @property
    def remaining(self) -> float:
        return max(0.0, float(self.quantity) - float(self.filled))


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    order_id: str
    domain: str                 # the escrow node that granted it
    notional_usd: float
    risk_units: float           # reserved share of a subadditive risk budget (see risk.py)


@dataclass
class PortfolioState:
    positions: dict[str, float] = field(default_factory=dict)          # P_t, signed quantity per symbol
    working: dict[str, WorkingOrder] = field(default_factory=dict)     # O_t
    reservations: dict[str, Reservation] = field(default_factory=dict) # B_t
    marks: dict[str, float] = field(default_factory=dict)              # M_t, trusted prices
    policy_versions: dict[str, int] = field(default_factory=dict)      # A_t, contract id -> signed version
    snapshot: int = 0
    agent_positions: dict[str, dict[str, float]] = field(default_factory=dict)
    by_key: dict[str, str] = field(default_factory=dict)               # idempotency key -> order id
    revoked_epochs: dict[str, int] = field(default_factory=dict)       # contract id -> highest revoked epoch
    marks_as_of: float = 0.0
    discrepancies: list = field(default_factory=list)

    def copy(self) -> "PortfolioState":
        return copy.deepcopy(self)

    def exposure_usd(self) -> dict[str, float]:
        """Filled positions in dollars at trusted marks."""
        return {s: q * self.marks.get(s, 0.0) for s, q in self.positions.items() if q}

    def working_orders(self) -> list[WorkingOrder]:
        return [o for o in self.working.values() if o.state in WORKING]


# ---------------------------------------------------------------------------------------------------------------------
# The pure fold
# ---------------------------------------------------------------------------------------------------------------------

def _add_pos(state: PortfolioState, agent: str, symbol: str, qty: float) -> None:
    state.positions[symbol] = state.positions.get(symbol, 0.0) + qty
    ap = state.agent_positions.setdefault(agent, {})
    ap[symbol] = ap.get(symbol, 0.0) + qty


def apply_event(state: PortfolioState, event: dict) -> None:
    """Fold one event into `state` in place. The only way state changes, live or on replay."""
    kind = event["kind"]
    if kind == "policy":
        state.policy_versions[event["contract_id"]] = int(event["version"])
    elif kind == "marks":
        state.marks.update({s: float(p) for s, p in event["marks"].items()})
        state.marks_as_of = float(event.get("as_of", state.marks_as_of))
    elif kind == "reserve":
        o = event["order"]
        wo = WorkingOrder(o["order_id"], o["agent"], o["contract_id"], o["symbol"], o["side"], float(o["quantity"]), 0.0,
                          float(o["limit_price"]), L.RISK_RESERVED, o["idempotency_key"], o.get("venue", "default"))
        if wo.order_id in state.working:
            raise InvalidTransition(f"order {wo.order_id} already exists")
        state.working[wo.order_id] = wo
        state.by_key[wo.idempotency_key] = wo.order_id
        r = event["reservation"]
        state.reservations[r["reservation_id"]] = Reservation(r["reservation_id"], r["order_id"], r["domain"], float(r["notional_usd"]),
                                                              float(r["risk_units"]))
    elif kind == "transition":
        wo = state.working[event["order_id"]]
        to = Lifecycle(event["to"])
        if to not in TRANSITIONS[wo.state]:
            raise InvalidTransition(f"{wo.order_id}: {wo.state.value} -> {to.value}")
        filled = float(event.get("filled", wo.filled))
        if filled < wo.filled - 1e-9 or filled > wo.quantity + 1e-9:
            raise InvalidTransition(f"{wo.order_id}: fill {filled} outside [{wo.filled}, {wo.quantity}]")
        delta = filled - wo.filled
        if delta:
            _add_pos(state, wo.agent, wo.symbol, wo.sign * delta)
        state.working[wo.order_id] = replace(wo, state=to, filled=filled)
    elif kind == "release":
        state.reservations.pop(event["reservation_id"], None)
    elif kind == "position_adjust":
        _add_pos(state, event.get("agent", "_reconciliation"), event["symbol"], float(event["qty"]))
        state.discrepancies.append({k: event[k] for k in ("symbol", "qty") if k in event})
    elif kind == "revoke_epoch":
        state.revoked_epochs[event["contract_id"]] = max(state.revoked_epochs.get(event["contract_id"], -1), int(event["epoch"]))
    elif kind in ("receipt", "note", "checkpoint"):
        pass
    else:
        raise ValueError(f"unknown event kind {kind!r}")


def check_event(state: PortfolioState, event: dict) -> None:
    """Raise InvalidTransition if `event` cannot apply to `state`. Never mutates: the ledger validates before it writes."""
    kind = event.get("kind")
    if kind == "reserve":
        if event["order"]["order_id"] in state.working:
            raise InvalidTransition(f"order {event['order']['order_id']} already exists")
    elif kind == "transition":
        wo = state.working.get(event["order_id"])
        if wo is None:
            raise InvalidTransition(f"unknown order {event['order_id']}")
        to = Lifecycle(event["to"])
        if to not in TRANSITIONS[wo.state]:
            raise InvalidTransition(f"{wo.order_id}: {wo.state.value} -> {to.value}")
        filled = float(event.get("filled", wo.filled))
        if filled < wo.filled - 1e-9 or filled > wo.quantity + 1e-9:
            raise InvalidTransition(f"{wo.order_id}: fill {filled} outside [{wo.filled}, {wo.quantity}]")


def replay(entries: list[dict]) -> PortfolioState:
    """Rebuild the state from log entries alone (what an auditor does)."""
    s = PortfolioState()
    for e in entries:
        apply_event(s, e["event"])
        s.snapshot = int(e["seq"])
    return s


# ---------------------------------------------------------------------------------------------------------------------
# Hash-chained log, signed checkpoints, fencing
# ---------------------------------------------------------------------------------------------------------------------

GENESIS = "0" * 64


def entry_hash(seq: int, prev: str, event: dict) -> str:
    return sha256_hex({"seq": seq, "prev": prev, "event": event})


class StaleWriter(Exception):
    """A writer whose fencing token is no longer current tried to append (it was replaced after a failover)."""


class LogStore:
    """Durable storage for one risk domain's log. It accepts appends only under the current fencing token."""

    def __init__(self):
        self.entries: list[dict] = []
        self.checkpoints: list[dict] = []
        self.token = 0
        self._lock = threading.Lock()

    def acquire(self) -> int:
        """Make a new writer current. Every earlier token is fenced off from then on."""
        with self._lock:
            self.token += 1
            return self.token

    def append(self, token: int, entry: dict) -> None:
        with self._lock:
            if token != self.token:
                raise StaleWriter(f"token {token} is fenced; current is {self.token}")
            expected_prev = self.entries[-1]["hash"] if self.entries else GENESIS
            if entry["prev"] != expected_prev or entry["seq"] != len(self.entries) + 1:
                raise StaleWriter("append does not extend the current head")
            self.entries.append(entry)

    def add_checkpoint(self, token: int, cp: dict) -> None:
        with self._lock:
            if token != self.token:
                raise StaleWriter(f"token {token} is fenced; current is {self.token}")
            self.checkpoints.append(cp)


def verify_log(entries: list[dict], checkpoints: list[dict], trusted_keys: set[str]) -> list[str]:
    """Independent check of a log: every hash links, every checkpoint is signed by a trusted key over a head that is in the log."""
    problems = []
    prev = GENESIS
    heads = {}
    for i, e in enumerate(entries, start=1):
        if e.get("seq") != i:
            problems.append(f"entry {i}: sequence number {e.get('seq')}")
        if e.get("prev") != prev:
            problems.append(f"entry {i}: does not link to the previous hash")
        h = entry_hash(i, e.get("prev"), e.get("event"))
        if h != e.get("hash"):
            problems.append(f"entry {i}: content does not match its hash")
        prev = e.get("hash")
        heads[i] = e.get("hash")
    for cp in checkpoints:
        body = {"seq": cp.get("seq"), "head": cp.get("head")}
        if cp.get("key") not in trusted_keys or not verify_b64(cp.get("key", ""), cp.get("signature", ""), body):
            problems.append(f"checkpoint at {cp.get('seq')}: signature does not verify with a trusted key")
        elif heads.get(cp.get("seq")) != cp.get("head"):
            problems.append(f"checkpoint at {cp.get('seq')}: head is not in this log (rewritten history)")
    return problems


class ReservationLedger:
    """The single writer for one risk domain. Every state change is an appended, hash-chained event; every `checkpoint_every`
    entries the head is signed. `lock` is held by the admission controller across check-and-reserve, which is what makes
    admission linearizable."""

    def __init__(self, store: LogStore | None = None, *, signing_key=None, checkpoint_every: int = 256):
        self.store = store or LogStore()
        self.token = self.store.acquire()
        self.state = replay(self.store.entries)
        self.signing_key = signing_key
        self.checkpoint_every = int(checkpoint_every)
        self.lock = threading.RLock()

    @property
    def public_key(self) -> str | None:
        return public_b64(self.signing_key) if self.signing_key is not None else None

    def append(self, event: dict) -> dict:
        with self.lock:
            check_event(self.state, event)                         # validate before anything is written
            seq = len(self.store.entries) + 1
            prev = self.store.entries[-1]["hash"] if self.store.entries else GENESIS
            entry = {"seq": seq, "prev": prev, "event": event, "hash": entry_hash(seq, prev, event)}
            self.store.append(self.token, entry)
            apply_event(self.state, event)
            self.state.snapshot = seq
            if self.signing_key is not None and seq % self.checkpoint_every == 0:
                self.checkpoint()
            return entry

    def checkpoint(self) -> dict | None:
        if self.signing_key is None or not self.store.entries:
            return None
        head = self.store.entries[-1]
        body = {"seq": head["seq"], "head": head["hash"]}
        cp = {**body, "key": public_b64(self.signing_key), "signature": sign_b64(self.signing_key, body)}
        self.store.add_checkpoint(self.token, cp)
        return cp

    @property
    def head(self) -> str:
        return self.store.entries[-1]["hash"] if self.store.entries else GENESIS

    # convenience wrappers ------------------------------------------------------------------------------------------
    def set_marks(self, marks: dict[str, float], as_of: float) -> None:
        self.append({"kind": "marks", "marks": {s: float(p) for s, p in marks.items()}, "as_of": float(as_of)})

    def set_policy(self, contract_id: str, version: int) -> None:
        self.append({"kind": "policy", "contract_id": contract_id, "version": int(version)})

    def transition(self, order_id: str, to: Lifecycle, filled: float | None = None) -> WorkingOrder:
        ev = {"kind": "transition", "order_id": order_id, "to": Lifecycle(to).value}
        if filled is not None:
            ev["filled"] = float(filled)
        self.append(ev)
        return self.state.working[order_id]


# ---------------------------------------------------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------------------------------------------------

def project_bounds(state: PortfolioState, symbol: str, add_quantity: float = 0.0) -> tuple[float, float]:
    """(lowest, highest) position the symbol can reach: filled, plus any subset of working orders filling, plus the proposed order.
    Exact for linear exposure: the extremes are reached when all same-side working orders fill and no opposite-side ones do."""
    pos = float(state.positions.get(symbol, 0.0))
    buys = sum(o.remaining for o in state.working.values() if o.state in WORKING and o.symbol == symbol and o.side == "buy")
    sells = sum(o.remaining for o in state.working.values() if o.state in WORKING and o.symbol == symbol and o.side == "sell")
    add = float(add_quantity)
    return pos - sells + min(add, 0.0), pos + buys + max(add, 0.0)


def project(state: PortfolioState, symbol: str, add_quantity: float) -> float:
    """Conservative projected position: filled, plus every working order that would increase risk, plus the proposed order;
    risk-reducing working orders are assumed not to fill. Returns the signed extreme with the larger magnitude."""
    lo, hi = project_bounds(state, symbol, add_quantity)
    return hi if abs(hi) >= abs(lo) else lo


# ---------------------------------------------------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------------------------------------------------

BROKER_STATUS = {"acknowledged": L.ACKNOWLEDGED, "accepted": L.ACKNOWLEDGED, "new": L.ACKNOWLEDGED, "partially_filled": L.PARTIALLY_FILLED,
                 "filled": L.FILLED, "canceled": L.CANCELED, "cancelled": L.CANCELED, "rejected": L.REJECTED, "expired": L.CANCELED}


def reconcile_events(state: PortfolioState, broker_orders: list[dict], broker_positions: dict[str, float] | None, *,
                     complete: bool = False) -> list[dict]:
    """The events that bring `state` in line with the broker's own records, resolving conservatively.

    - A working order the broker reports moves to the broker's status and fill.
    - A SUBMITTED or UNCERTAIN order the broker does not report stays held, unless `complete` says the broker's list is complete
      as of a time after it was sent: only then is it proven never to have arrived (REJECTED, reservation released).
    - Broker positions are authoritative for fills: any remaining difference becomes an explicit `position_adjust` event, logged as
      a discrepancy, never silently absorbed.
    - A broker order this ledger never admitted is reported as `unknown_broker_order` (an alarm: something sent it around us).
    """
    events: list[dict] = []
    probe = state.copy()
    seen: set[str] = set()
    for bo in broker_orders:
        oid = bo.get("order_id")
        if oid not in probe.working and bo.get("idempotency_key") in probe.by_key:
            oid = probe.by_key[bo["idempotency_key"]]
        if oid not in probe.working:
            events.append({"kind": "note", "note": "unknown_broker_order", "broker_order": dict(bo)})
            continue
        seen.add(oid)
        wo = probe.working[oid]
        if wo.state not in WORKING:
            continue
        to = BROKER_STATUS.get(str(bo.get("status", "")).lower())
        if to is None:
            continue
        filled = min(float(bo.get("filled", wo.filled)), wo.quantity)
        filled = max(filled, wo.filled)
        if to == L.PARTIALLY_FILLED and filled >= wo.quantity:
            to = L.FILLED
        if to == wo.state and filled == wo.filled and to != L.PARTIALLY_FILLED:
            continue
        if to not in TRANSITIONS[wo.state]:
            if wo.state == L.RISK_RESERVED:
                ev0 = {"kind": "transition", "order_id": oid, "to": L.SUBMITTED.value}
                apply_event(probe, ev0)
                events.append(ev0)
            else:
                continue
        ev = {"kind": "transition", "order_id": oid, "to": to.value, "filled": filled}
        apply_event(probe, ev)
        events.append(ev)
    if complete:
        for oid, wo in list(probe.working.items()):
            if wo.state in (L.SUBMITTED, L.UNCERTAIN) and oid not in seen:
                ev = {"kind": "transition", "order_id": oid, "to": L.REJECTED.value}
                apply_event(probe, ev)
                events.append(ev)
    for oid, wo in probe.working.items():
        if wo.state in TERMINAL:
            for rid, r in probe.reservations.items():
                if r.order_id == oid:
                    events.append({"kind": "release", "reservation_id": rid})
    if broker_positions is not None:
        for sym in sorted(set(broker_positions) | set(probe.positions)):
            diff = float(broker_positions.get(sym, 0.0)) - float(probe.positions.get(sym, 0.0))
            if abs(diff) > 1e-9:
                events.append({"kind": "position_adjust", "symbol": sym, "qty": diff})
    return events


def reconcile(state: PortfolioState, broker_orders: list[dict], broker_positions: dict[str, float], *,
              complete: bool = False) -> PortfolioState:
    """Resolve UNCERTAIN and partial states against the broker's own records, conservatively. Returns a new state."""
    out = state.copy()
    for ev in reconcile_events(state, broker_orders, broker_positions, complete=complete):
        apply_event(out, ev)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Hierarchical risk escrow
# ---------------------------------------------------------------------------------------------------------------------

class EscrowExhausted(Exception):
    pass


class EscrowNode:
    """One node of the hierarchical risk escrow. Holds capacity granted by its parent and reserves it per order.

    Two resources, dollars (gross exposure) and risk units (standalone ES, see risk.reservable_risk). For each:

        capacity   what the parent has granted this node (the root's capacity is its signed limit)
        limit      the most this node may ever hold (its own signed limit; a child can never hold more than this)
        used       this node's own reservations + filled exposure + everything granted on to its children

    Invariant, checked by `check_invariants` and by the property tests: used <= capacity <= limit at every node, and the
    capacities of a node's children sum to at most what that node has granted them. A child admits orders against its own capacity
    without touching its parent; only when it runs short does it ask (`request_more`), and the request walks upward taking each
    node's lock in turn, child before parent, so locks are always acquired in the same order and cannot deadlock.
    """

    def __init__(self, name: str, capacity_usd: float, risk_capacity: float, parent: "EscrowNode | None" = None, *,
                 limit_usd: float | None = None, risk_limit: float | None = None):
        self.name, self.parent = name, parent
        self.limit_usd = float(limit_usd if limit_usd is not None else capacity_usd)
        self.risk_limit = float(risk_limit if risk_limit is not None else risk_capacity)
        self.capacity_usd = 0.0 if parent is not None else min(float(capacity_usd), self.limit_usd)
        self.risk_capacity = 0.0 if parent is not None else min(float(risk_capacity), self.risk_limit)
        self.used_usd = 0.0
        self.used_risk = 0.0
        self.granted_usd: dict[str, float] = {}
        self.granted_risk: dict[str, float] = {}
        self.reservations: dict[str, tuple[float, float]] = {}
        self.filled_usd = 0.0
        self.filled_risk = 0.0
        self.children: list[EscrowNode] = []
        self.lock = threading.RLock()
        self._seq = 0
        if parent is not None:
            parent.children.append(self)
            if (capacity_usd or risk_capacity) and not parent.grant(self, float(capacity_usd), float(risk_capacity)):
                raise EscrowExhausted(f"{parent.name} cannot grant the initial allocation to {name}")

    @property
    def path(self) -> str:
        return self.name if self.parent is None else f"{self.parent.path}/{self.name}"

    @property
    def free_usd(self) -> float:
        return self.capacity_usd - self.used_usd

    @property
    def free_risk(self) -> float:
        return self.risk_capacity - self.used_risk

    # capacity flow ------------------------------------------------------------------------------------------------
    def grant(self, child: "EscrowNode", usd: float, risk: float) -> bool:
        """Move capacity from this node to `child`, asking upward if this node is short. All or nothing."""
        usd, risk = max(0.0, usd), max(0.0, risk)
        with self.lock:
            if child.capacity_usd + usd > child.limit_usd + 1e-6 or child.risk_capacity + risk > child.risk_limit + 1e-9:
                return False
            short_usd, short_risk = max(0.0, usd - self.free_usd), max(0.0, risk - self.free_risk)
            if (short_usd > 1e-9 or short_risk > 1e-12) and not self.request_more(short_usd, short_risk):
                return False
            self.used_usd += usd
            self.used_risk += risk
            self.granted_usd[child.name] = self.granted_usd.get(child.name, 0.0) + usd
            self.granted_risk[child.name] = self.granted_risk.get(child.name, 0.0) + risk
            child.capacity_usd += usd
            child.risk_capacity += risk
            return True

    def request_more(self, usd: float, risk: float) -> bool:
        """Ask the parent for more capacity. The root cannot: its capacity is its signed limit."""
        if self.parent is None:
            return False
        with self.lock:
            return self.parent.grant(self, usd, risk)

    def relinquish(self, usd: float | None = None, risk: float | None = None) -> tuple[float, float]:
        """Return idle capacity to the parent (all free capacity by default), so a quiet child does not starve its siblings."""
        if self.parent is None:
            return 0.0, 0.0
        with self.lock, self.parent.lock:                       # child before parent, like every other path
            u = max(0.0, min(self.free_usd, self.free_usd if usd is None else usd))
            r = max(0.0, min(self.free_risk, self.free_risk if risk is None else risk))
            self.capacity_usd -= u
            self.risk_capacity -= r
            p = self.parent
            p.used_usd -= u
            p.used_risk -= r
            p.granted_usd[self.name] = p.granted_usd.get(self.name, 0.0) - u
            p.granted_risk[self.name] = p.granted_risk.get(self.name, 0.0) - r
            return u, r

    def obtainable(self) -> tuple[float, float]:
        """(dollars, risk) this node could reserve right now, counting what its ancestors could still grant. Read-only."""
        with self.lock:
            if self.parent is None:
                return self.free_usd, self.free_risk
            pu, pr = self.parent.obtainable()
            # free can be negative after a rebase re-measured risk upward; that debt must be covered before anything new
            return (self.free_usd + max(0.0, min(self.limit_usd - self.capacity_usd, pu)),
                    self.free_risk + max(0.0, min(self.risk_limit - self.risk_capacity, pr)))

    def return_idle(self) -> None:
        """Every descendant hands its unused capacity back up, leaves first, so idle allocations never strand budget that a
        sibling needs. Capacity is pulled down again on demand (request_more). Called at reconciliation."""
        for ch in self.children:
            ch.return_idle()
        if self.parent is not None:
            self.relinquish()

    # reservations -------------------------------------------------------------------------------------------------
    def can_reserve(self, notional_usd: float, risk_units: float, *, ask_parent: bool = True) -> bool:
        with self.lock:
            # Nothing asked, nothing needed: a risk-reducing order reserves zero and must pass even when the node is in debt.
            short_usd = max(0.0, notional_usd - self.free_usd) if notional_usd > 0 else 0.0
            short_risk = max(0.0, risk_units - self.free_risk) if risk_units > 0 else 0.0
            if short_usd <= 1e-9 and short_risk <= 1e-12:
                return True
            return ask_parent and self.request_more(short_usd, short_risk)

    def reserve(self, order: WorkingOrder, notional_usd: float, risk_units: float) -> Reservation:
        notional_usd, risk_units = max(0.0, float(notional_usd)), max(0.0, float(risk_units))
        with self.lock:
            if not self.can_reserve(notional_usd, risk_units):
                raise EscrowExhausted(f"{self.path} has ${self.free_usd:,.0f} and {self.free_risk:,.2f} risk free; "
                                      f"needs ${notional_usd:,.0f} and {risk_units:,.2f}")
            self._seq += 1
            rid = f"{self.path}#{self._seq}:{order.order_id}"
            self.reservations[rid] = (notional_usd, risk_units)
            self.used_usd += notional_usd
            self.used_risk += risk_units
            return Reservation(rid, order.order_id, self.path, notional_usd, risk_units)

    def release(self, reservation_id: str, unused_usd: float, unused_risk: float) -> None:
        """Return the unused part of a reservation (a cancel, a reject, the unfilled rest of an order). The rest stays consumed."""
        with self.lock:
            usd, risk = self.reservations[reservation_id]
            u, r = min(usd, max(0.0, unused_usd)), min(risk, max(0.0, unused_risk))
            self.used_usd -= u
            self.used_risk -= r
            left = (usd - u, risk - r)
            if left[0] <= 1e-9 and left[1] <= 1e-12:
                del self.reservations[reservation_id]
            else:
                self.reservations[reservation_id] = left

    def settle(self, reservation_id: str, filled_usd: float, filled_risk: float) -> None:
        """A reservation's filled part becomes filled exposure; whatever is left of the reservation is released."""
        with self.lock:
            usd, risk = self.reservations.pop(reservation_id, (0.0, 0.0))
            self.used_usd -= usd
            self.used_risk -= risk
            self.filled_usd += filled_usd
            self.filled_risk += filled_risk
            self.used_usd += filled_usd
            self.used_risk += filled_risk

    def rebase_filled(self, filled_usd: float, filled_risk: float) -> None:
        """Reconciliation: set filled exposure to its re-measured value (gross at marks; Euler share of ES). This is where the
        diversification benefit returns. If the re-measure is larger (prices or volatility moved against us) the node can end up
        over its capacity; it then admits nothing that adds risk until it is back under, which is the conservative outcome."""
        with self.lock:
            self.used_usd += max(0.0, filled_usd) - self.filled_usd
            self.used_risk += max(0.0, filled_risk) - self.filled_risk
            self.filled_usd, self.filled_risk = max(0.0, filled_usd), max(0.0, filled_risk)

    def check_invariants(self) -> list[str]:
        problems = []
        with self.lock:
            own = sum(u for u, _ in self.reservations.values()) + self.filled_usd + sum(self.granted_usd.values())
            own_r = sum(r for _, r in self.reservations.values()) + self.filled_risk + sum(self.granted_risk.values())
            if abs(own - self.used_usd) > 1e-3 or abs(own_r - self.used_risk) > 1e-6:
                problems.append(f"{self.path}: used does not equal reservations + filled + grants")
            if self.capacity_usd > self.limit_usd + 1e-3 or self.risk_capacity > self.risk_limit + 1e-6:
                problems.append(f"{self.path}: capacity above its limit")
            for ch in self.children:
                if ch.capacity_usd > self.granted_usd.get(ch.name, 0.0) + 1e-3 or ch.risk_capacity > self.granted_risk.get(ch.name, 0.0) + 1e-6:
                    problems.append(f"{ch.path}: holds more than its parent granted")
        for ch in self.children:
            problems += ch.check_invariants()
        return problems

    def over_reserved(self) -> list[str]:
        """Nodes whose reservations exceed capacity (possible only after a rebase that re-measured risk upward)."""
        out = [self.path] if self.used_usd > self.capacity_usd + 1e-3 or self.used_risk > self.risk_capacity + 1e-6 else []
        for ch in self.children:
            out += ch.over_reserved()
        return out

    def describe(self) -> dict:
        return {"name": self.name, "capacity_usd": round(self.capacity_usd, 2), "used_usd": round(self.used_usd, 2),
                "risk_capacity": round(self.risk_capacity, 4), "used_risk": round(self.used_risk, 4),
                "children": [c.describe() for c in self.children]}


def order_dict(o: WorkingOrder) -> dict:
    d = asdict(o)
    d["state"] = o.state.value
    return d
