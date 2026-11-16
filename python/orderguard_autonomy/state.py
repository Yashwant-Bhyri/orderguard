"""The authoritative portfolio state (design section 3B).

S_t = (P_t, O_t, B_t, M_t, A_t): filled positions, outstanding orders, risk budgets and reservations, trusted market data,
active authorizations. Admission is linearizable per risk domain: every order is admitted against a state that already includes
every earlier admitted order. Capacity is held in a hierarchical escrow (firm, book, agent): a child admits against its own
allocation without a global lock and asks its parent for more. Uncertain broker states keep their reservation until reconciled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from orderguard_autonomy import not_built


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


class EscrowNode:
    """One node of the hierarchical risk escrow. Holds capacity granted by its parent and reserves it per order."""

    def __init__(self, name: str, capacity_usd: float, risk_capacity: float, parent: "EscrowNode | None" = None):
        self.name, self.capacity_usd, self.risk_capacity, self.parent = name, capacity_usd, risk_capacity, parent

    def reserve(self, order: WorkingOrder, notional_usd: float, risk_units: float) -> Reservation:
        raise not_built("section 3B, hierarchical risk escrow")

    def release(self, reservation_id: str, unused_usd: float, unused_risk: float) -> None:
        raise not_built("section 3B, hierarchical risk escrow")

    def request_more(self, usd: float, risk: float) -> bool:
        raise not_built("section 3B, hierarchical risk escrow")


def project(state: PortfolioState, symbol: str, add_quantity: float) -> float:
    """Conservative projected position: filled, plus every working order that would increase risk, plus the proposed order;
    risk-reducing working orders are assumed not to fill."""
    raise not_built("section 3B, working orders")


def reconcile(state: PortfolioState, broker_orders: list[dict], broker_positions: dict[str, float]) -> PortfolioState:
    """Resolve UNCERTAIN and partial states against the broker's own records, conservatively."""
    raise not_built("section 3B, uncertain broker state")
