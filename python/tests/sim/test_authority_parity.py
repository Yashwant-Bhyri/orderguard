import numpy as np

from orderguard_arena.authority import SnapshotMarket
from orderguard_arena.envelopes import make_envelope, owner_key_from_seed
from orderguard_guard.gate import OrderGate
from orderguard_sim.vectorized import vectorized_precheck


def test_vectorized_l5_shadow_matches_real_gate_on_100k_random_orders():
    n = 100_000
    rng = np.random.default_rng(913)
    tickers = np.array(["AAPL", "MSFT", "ZZZZ", " aapl "], dtype=object)
    sides = np.array(["buy", "sell", "short", "BUY"], dtype=object)
    ticker = rng.choice(tickers, n)
    side = rng.choice(sides, n)
    qty = rng.integers(-1, 160, n).astype(np.float64)
    qty[rng.random(n) < 0.02] += 0.5
    px = np.where(np.char.upper(np.char.strip(ticker.astype(str))) == "MSFT", 200.0, 100.0)
    limit = px * rng.uniform(0.96, 1.04, n)
    limit[rng.random(n) < 0.002] = 0.0
    used = rng.uniform(0.0, 50_000.0, n)
    key = owner_key_from_seed("sim-parity-100k")
    env = make_envelope(key, name="parity", symbols=["AAPL", "MSFT"], per_order=10_000, daily=50_000,
                        band_pct=2.0, step_up=8_000)
    predicted = vectorized_precheck(ticker, side, qty, limit, px, used, symbols={"AAPL", "MSFT"}, sides={"buy", "sell"},
                                    per_order=10_000, daily=50_000, band_pct=2.0, step_up=8_000)
    gate = OrderGate(env.m, SnapshotMarket({"AAPL": 100.0, "MSFT": 200.0}))
    as_of = "2026-01-05T09:30:00Z"
    for i in range(n):
        order = {"ticker": ticker[i], "side": side[i], "quantity": float(qty[i]), "limit_price": float(limit[i])}
        actual = gate.evaluate(order, {"daily_total_usd": float(used[i]), "as_of": as_of})["decision"]
        assert actual == predicted[i], (i, order, actual, predicted[i])

