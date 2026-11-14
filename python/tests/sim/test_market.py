import numpy as np

from orderguard_sim.market import DEFAULT_RECORDING, ImpactMarket, calibrate_recording


def test_square_root_impact_is_concave():
    market = ImpactMarket(["AAPL"], seed=1, sigma={"AAPL": 0.002}, adv={"AAPL": 10_000_000})
    one = market.impact_fraction("AAPL", 100_000)
    four = market.impact_fraction("AAPL", 400_000)
    assert np.isclose(four, 2.0 * one)
    assert four / 4.0 < one


def test_agent_flow_returns_are_fat_tailed_and_volatility_clusters():
    market = ImpactMarket(["AAPL"], seed=9, sigma={"AAPL": 0.002}, adv={"AAPL": 20_000_000})
    rng = np.random.default_rng(81)
    for _ in range(18_000):
        q = float(rng.choice([-1, 1]) * rng.lognormal(np.log(20_000), 1.2))
        market.step({"AAPL": q})
    r = np.asarray(market.returns)[:, 0]
    kurtosis = np.mean((r - r.mean()) ** 4) / np.var(r) ** 2 - 3.0
    abs_corr = np.corrcoef(np.abs(r[:-1]), np.abs(r[1:]))[0, 1]
    assert kurtosis > 2.0
    assert abs_corr > 0.02


def test_honest_symmetric_random_flow_has_no_directional_log_drift():
    market = ImpactMarket(["AAPL"], seed=17, sigma={"AAPL": 0.0015}, adv={"AAPL": 50_000_000})
    rng = np.random.default_rng(4)
    for _ in range(15_000):
        flow = float(rng.choice([-1, 1]) * rng.lognormal(np.log(5_000), 0.6))
        market.step({"AAPL": flow})
    mean_return = float(np.mean(np.asarray(market.returns)[:, 0]))
    assert abs(mean_return) < 0.0001


def test_net_flow_aggregation_matches_sequential_order_accumulation():
    orders = [("AAPL", 1, 100_000.25), ("MSFT", -1, 22_000.50), ("AAPL", -1, 7_125.75),
              ("AAPL", 1, 3_500.00), ("MSFT", 1, 1_250.10)]
    by_symbol = {"AAPL": 0.0, "MSFT": 0.0}
    for sym, side, dollars in orders:
        by_symbol[sym] += side * dollars
    batch = ImpactMarket(["AAPL", "MSFT"], seed=33)
    sequential = ImpactMarket(["AAPL", "MSFT"], seed=33)
    batch.step(by_symbol)
    accumulated = np.zeros(2)
    for sym, side, dollars in orders:
        accumulated[sequential.index[sym]] += side * dollars
    sequential.step(accumulated)
    assert np.allclose(batch.mid, sequential.mid, rtol=1e-12, atol=1e-12)


def test_recorded_feed_seeds_matching_crypto_vol_and_correlation():
    calibrated = calibrate_recording(DEFAULT_RECORDING, ["BTC-USD", "ETH-USD"])
    assert set(calibrated["sigma"]) == {"BTC-USD", "ETH-USD"}
    assert ("BTC-USD", "ETH-USD") in calibrated["correlation"]
    one_second = ImpactMarket.from_recording(["BTC-USD"], seed=5, simulation_step_seconds=1)
    one_hundred_seconds = ImpactMarket.from_recording(["BTC-USD"], seed=5, simulation_step_seconds=100)
    assert np.isclose(one_hundred_seconds.sigma[0], one_second.sigma[0] * 10)

