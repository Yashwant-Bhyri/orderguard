"""Money arithmetic shared by every Python path that values an order, so Python and the TypeScript receiver can never round differently.

ONE rule: an amount in US dollars becomes integer cents as JavaScript's Math.round(x * 100) does on the same IEEE doubles (the receiver's
valuation.ts `notionalCents` and every `Math.round(usd * 100)` cap there). Math.round rounds half toward +infinity and is exact; Python's
round() rounds half to even, so round(112.5) == 112 where Math.round(112.5) == 113, and `floor(x + 0.5)` is wrong for 0.49999999999999994
(the addition itself rounds up). `js_round` reproduces Math.round exactly for every finite double.

python/tests/guard/test_cents_parity.py runs the TypeScript implementation on random and half-cent cases and compares.
"""
from __future__ import annotations

import math


def js_round(x: float) -> int:
    """JavaScript Math.round for a finite double, as an int: the nearest integer, ties toward +infinity."""
    x = float(x)
    if not math.isfinite(x):
        raise ValueError(f"cannot round a non-finite amount ({x!r}) to cents")
    f = math.floor(x)
    return int(f) + (1 if x - f >= 0.5 else 0)       # x - f is exact for a double and its floor


def usd_cents(usd: float) -> int:
    """A dollar amount (a cap, a running total) in integer cents: Math.round(usd * 100)."""
    return js_round(float(usd) * 100)


def notional_cents(quantity: float, price: float) -> int:
    """Notional in integer cents: Math.round(quantity * price * 100), multiplied left to right as valuation.ts does."""
    return js_round(float(quantity) * float(price) * 100)


def notional_usd(quantity: float, price: float) -> float:
    """The same notional as a dollar float (cents / 100), for display and for callers that keep dollars."""
    return notional_cents(quantity, price) / 100.0
