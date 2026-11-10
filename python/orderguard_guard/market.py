"""Trusted market data: numbers the agent cannot touch.

`TrustedMarket.quote(ticker)` -> {"price", "as_of", "source"}. `SimMarket` is the lab implementation: prices are given at
construction, per venue or as one number; `quote` returns the median across venues.

Why: in the prototype 8 of 11 agents that believed a fake 10-for-1 split ordered about 440 shares at $22.30. Valuing that
order at its own limit price (about $9,800) passes a $10,000 cap; valuing it at the trusted quote ($222.70) gives about
$98,000 and refuses (lab/legacy/attack-lab-2026-11-06/README.md).
"""
from __future__ import annotations

import statistics
from typing import Protocol, runtime_checkable


@runtime_checkable
class TrustedMarket(Protocol):
    def quote(self, ticker: str) -> dict: ...


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("median of nothing")
    return float(statistics.median(values))


class UnknownTicker(KeyError):
    pass


class SimMarket:
    """prices = {"AAPL": 222.70} or {"AAPL": {"VenueA": 222.68, "VenueB": 222.72}}."""

    def __init__(self, prices: dict, as_of: str = "2024-11-06T15:05:00Z", source: str = "sim-broker"):
        self.prices = {k.upper(): v for k, v in prices.items()}
        self.as_of = as_of
        self.source = source

    def venues(self, ticker: str) -> dict[str, float]:
        v = self.prices.get(ticker.upper())
        if v is None:
            raise UnknownTicker(ticker)
        if isinstance(v, dict):
            return {str(k): float(x) for k, x in v.items()}
        return {self.source: float(v)}

    def quotes(self, ticker: str) -> list[dict]:
        return [{"venue": k, "price": p, "as_of": self.as_of} for k, p in self.venues(ticker).items()]

    def quote(self, ticker: str) -> dict:
        vs = self.venues(ticker)
        return {"price": median(list(vs.values())), "as_of": self.as_of, "source": self.source, "venues": len(vs)}

    def set(self, ticker: str, price: float, venue: str | None = None) -> None:
        t = ticker.upper()
        if venue is None:
            self.prices[t] = float(price)
        else:
            cur = self.prices.get(t)
            cur = dict(cur) if isinstance(cur, dict) else ({self.source: float(cur)} if cur is not None else {})
            cur[venue] = float(price)
            self.prices[t] = cur
