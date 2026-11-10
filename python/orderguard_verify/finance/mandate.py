"""Mandate check: does the order fit what the human signed? Pure code, no model.

It fails closed. The order is valued at the TRUSTED quote only; the agent's own limit price is never used to size an
order, and must sit inside a price band around the quote. If there is no fresh trusted quote the order is a violation.
The quote feed in this prototype is SYNTHETIC (see quotes.py)."""
from __future__ import annotations

from datetime import date, timedelta

from .models import Mandate, Order, normalise_ticker
from .truth_store import Snapshot, TruthStore

QUOTE_MAX_AGE = timedelta(days=7)


def trusted_quote(order: Order, store: TruthStore) -> Snapshot | None:
    """The gateway's own quote for the (normalised) ticker on the decision date, or None if there is none or it is too old."""
    t = normalise_ticker(order.ticker)
    if t is None:
        return None
    day = order.as_of or date.today()
    q = store.quote(t, day)
    if q is None or day - date.fromisoformat(q.as_of) > QUOTE_MAX_AGE:
        return None
    return q


def reference_price(order: Order, store: TruthStore) -> float | None:
    q = trusted_quote(order, store)
    return q.value if q else None


def check_mandate(order: Order, mandate: Mandate, store: TruthStore) -> list[str]:
    problems: list[str] = []
    ticker = normalise_ticker(order.ticker)
    allowed = {normalise_ticker(t) for t in mandate.allowed_tickers} - {None}
    if ticker is None:
        problems.append("the ticker is not a plain ASCII symbol")
    elif ticker not in allowed:
        problems.append(f"{ticker} is not on the allowed list")
    if order.side not in mandate.allowed_sides:
        problems.append(f"{order.side} orders are not allowed")
    if order.quantity > mandate.max_order_shares:
        problems.append(f"{order.quantity} shares exceeds the per-order limit of {mandate.max_order_shares}")
    price = reference_price(order, store)
    if price is None:
        problems.append("no reference price available to size the order")
        return problems
    if order.quantity * price > mandate.max_order_notional:
        problems.append(f"notional ${order.quantity * price:,.0f} exceeds the limit of ${mandate.max_order_notional:,.0f}")
    if order.limit_price is not None and not abs(order.limit_price - price) <= price * mandate.price_band_pct / 100:   # NaN fails too
        problems.append(f"limit price {order.limit_price:g} is outside the {mandate.price_band_pct:g}% band around the trusted quote")
    return problems
