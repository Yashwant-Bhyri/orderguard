"""Static L5 preflight used for cap studies and parity checks.

This helper is a shadow calculator. It is not an approval path: production
simulation orders still go through ``Authority.authorize``. Its scope is the
per-order/daily/price-band/step-up rules for a single envelope without portfolio
state, where the equations can be evaluated in NumPy arrays.
"""
from __future__ import annotations

import numpy as np


def vectorized_precheck(ticker, side, quantity, limit_price, trusted_price, daily_used, *,
                        symbols: set[str], sides: set[str], per_order: float, daily: float,
                        band_pct: float, step_up: float | None = None) -> np.ndarray:
    """Return ``allow``, ``hold`` or ``refuse`` predictions for independent rows."""
    tick = np.char.upper(np.char.strip(np.asarray(ticker, dtype=str)))
    sd = np.char.lower(np.char.strip(np.asarray(side, dtype=str)))
    q = np.asarray(quantity, dtype=np.float64)
    limit = np.asarray(limit_price, dtype=np.float64)
    px = np.asarray(trusted_price, dtype=np.float64)
    used = np.asarray(daily_used, dtype=np.float64)
    if not (tick.shape == sd.shape == q.shape == limit.shape == px.shape == used.shape):
        raise ValueError("all vectorized precheck inputs must have the same shape")
    valid = np.isfinite(q) & np.isfinite(limit) & np.isfinite(px) & np.isfinite(used) & (q > 0) & (q == np.floor(q))
    valid &= (limit > 0) & (px > 0) & (used >= 0)
    valid &= np.isin(tick, np.asarray(sorted(symbols), dtype=str)) & np.isin(sd, np.asarray(sorted(sides), dtype=str))
    cents = np.rint(q * px * 100.0)
    valid &= cents <= round(float(per_order) * 100.0)
    valid &= np.rint(used * 100.0) + cents <= round(float(daily) * 100.0)
    valid &= np.abs(limit / np.where(px > 0, px, 1.0) - 1.0) <= float(band_pct) / 100.0 + 1e-12
    result = np.full(tick.shape, "refuse", dtype="U8")
    if step_up is None:
        result[valid] = "allow"
    else:
        holds = valid & (cents > round(float(step_up) * 100.0))
        result[valid & ~holds] = "allow"
        result[holds] = "hold"
    return result

