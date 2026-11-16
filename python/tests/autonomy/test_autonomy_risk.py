"""Counterfactual risk: subadditivity (the property that makes risk budgets reservable), Euler, scenarios, estimators, backtests."""
import itertools
import math

import numpy as np
import pytest

from orderguard_autonomy import risk as R


def _random_model(rng, n):
    a = rng.standard_normal((n, n)) * 0.02
    syms = [f"S{i}" for i in range(n)]
    return R.StaticCovariance(syms, a @ a.T + np.eye(n) * 1e-5), syms


def test_es_factors_match_known_values():
    assert R.es_factor(0.975) == pytest.approx(2.33780, abs=1e-4)
    assert R.var_factor(0.975) == pytest.approx(1.95996, abs=1e-5)
    assert R.es_factor(0.975, 5) > R.es_factor(0.975)             # fat tails raise ES at the same variance
    assert R.norm_ppf(0.5) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("seed", range(20))
def test_property_reserved_risk_bounds_every_fill_combination(seed):
    """ES(w + sum f_i d_i) <= ES(w) + sum ES(d_i) for every subset (f_i in {0,1}) and random partial fills."""
    rng = np.random.default_rng(seed)
    model, syms = _random_model(rng, 6)
    w = {s: float(v) for s, v in zip(syms, rng.normal(0, 50_000, 6))}
    orders = [{syms[rng.integers(6)]: float(rng.normal(0, 20_000))} for _ in range(7)]
    bound = R.expected_shortfall(model, w) + sum(R.reservable_risk(model, d) for d in orders)
    for k in range(len(orders) + 1):
        for subset in itertools.combinations(orders, k):
            book = dict(w)
            for d in subset:
                for s, v in d.items():
                    book[s] = book.get(s, 0.0) + v
            assert R.expected_shortfall(model, book) <= bound + 1e-6
    for _ in range(50):
        f = rng.uniform(0, 1, len(orders))
        book = dict(w)
        for fi, d in zip(f, orders):
            for s, v in d.items():
                book[s] = book.get(s, 0.0) + fi * v
        assert R.expected_shortfall(model, book) <= bound + 1e-6


@pytest.mark.parametrize("seed", range(10))
def test_euler_contributions_sum_to_total(seed):
    rng = np.random.default_rng(100 + seed)
    model, syms = _random_model(rng, 5)
    w = {s: float(v) for s, v in zip(syms, rng.normal(0, 10_000, 5))}
    c = R.euler_contributions(model, w)
    assert sum(c.values()) == pytest.approx(R.expected_shortfall(model, w), rel=1e-9)
    books = {"a": {syms[0]: w[syms[0]], syms[1]: w[syms[1]]}, "b": {s: w[s] for s in syms[2:]}}
    g = R.group_euler(model, books)
    assert sum(g.values()) == pytest.approx(R.expected_shortfall(model, w), rel=1e-9)
    # diversification returned: the sum of standalone risks is at least the Euler total
    assert sum(R.reservable_risk(model, b) for b in books.values()) >= sum(g.values()) - 1e-9


def test_incremental_es_of_a_hedge_is_negative_and_of_a_correlated_add_is_large():
    cov = np.array([[4e-4, 3.6e-4], [3.6e-4, 4e-4]])
    m = R.StaticCovariance(["A", "B"], cov)
    assert R.incremental_es(m, {"A": 100_000}, {"B": -50_000}) < 0
    assert R.incremental_es(m, {"A": 100_000}, {"B": 50_000}) > 0.9 * R.reservable_risk(m, {"B": 50_000})
    diversified = R.StaticCovariance(["A", "B"], np.diag([4e-4, 4e-4]))
    assert R.incremental_es(diversified, {"A": 100_000}, {"B": 50_000}) < R.incremental_es(m, {"A": 100_000}, {"B": 50_000})


def test_declared_scenarios_and_worst_case_over_fills():
    s = R.Scenario("tech", {"*": -0.05, "sector:tech": -0.3, "KO": 0.02})
    sectors = {"AAPL": "tech", "KO": "staples", "SPY": "index"}
    loss = R.declared_scenario_loss({"AAPL": 10_000, "KO": 10_000, "SPY": 10_000}, [s], sectors)["tech"]
    assert loss == pytest.approx(3000 - 200 + 500)
    base = {"AAPL": 10_000}
    pending = [{"AAPL": 5_000}, {"KO": -4_000}, {"SPY": 2_000}, {"AAPL": -3_000}]
    worst = R.worst_case_scenario_loss(base, pending, [s], sectors)["tech"]
    brute = max(R.declared_scenario_loss({k: base.get(k, 0) + sum(d.get(k, 0) for d in sub) for k in ("AAPL", "KO", "SPY")}, [s], sectors)["tech"]
                for r in range(5) for sub in itertools.combinations(pending, r))
    assert worst == pytest.approx(brute)


def test_shrinkage_estimators_are_well_conditioned():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((40, 30)) * 0.01                        # fewer observations than a stable sample covariance needs
    shrunk, delta = R.ledoit_wolf_constant_correlation(x)
    assert 0 < delta <= 1
    assert np.linalg.eigvalsh(shrunk).min() > 0
    assert np.linalg.cond(shrunk) < np.linalg.cond(np.cov(x, rowvar=False, bias=True) + 1e-18 * np.eye(30))
    sk = pytest.importorskip("sklearn.covariance")
    # same family as sklearn's Ledoit-Wolf (which shrinks toward a scaled identity); both must give positive definite output
    assert np.linalg.eigvalsh(sk.LedoitWolf().fit(x).covariance_).min() > 0
    sectors = {i: "a" if i < 15 else "b" for i in range(30)}
    f = R.factor_covariance(x, list(range(30)), sectors)
    assert np.linalg.eigvalsh(f).min() > 0


def test_stressed_covariance_is_psd_and_riskier_for_a_long_book():
    rng = np.random.default_rng(4)
    model, syms = _random_model(rng, 6)
    long_book = {s: 10_000.0 for s in syms}
    stressed = R.expected_shortfall(model, long_book, stressed=True)
    assert stressed > R.expected_shortfall(model, long_book)
    assert np.linalg.eigvalsh(model.covariance(syms, stressed=True)).min() > -1e-12


def test_regime_detector_enters_and_leaves_with_hysteresis():
    rng = np.random.default_rng(5)
    det = R.RegimeDetector()
    calm = [det.update(r) for r in rng.normal(0, 0.01, 200)]
    assert not any(calm[50:])
    storm = [det.update(r) for r in rng.normal(0, 0.05, 40)]
    assert any(storm)
    after = [det.update(r) for r in rng.normal(0, 0.01, 400)]
    assert not after[-1]


def test_backtest_is_calibrated_when_the_model_is_right_and_flags_understatement():
    rng = np.random.default_rng(6)
    sigma = 1000.0
    losses = rng.standard_normal(20_000) * sigma
    var, es = R.var_factor(0.975) * sigma, R.es_factor(0.975) * sigma
    good = R.backtest_var_es(losses, [var] * len(losses), [es] * len(losses))
    assert abs(good["exceptions"] - good["expected_exceptions"]) < 4 * math.sqrt(good["expected_exceptions"])
    assert abs(good["acerbi_szekely_z2"]) < 0.1
    bad = R.backtest_var_es(losses * 2, [var] * len(losses), [es] * len(losses))
    assert bad["kupiec_p"] < 1e-6 and bad["acerbi_szekely_z2"] > 0.5


def test_liquidity_cost_grows_faster_than_size():
    assert R.liquidity_cost(2e6, 5e7, 0.02) > 2 * R.liquidity_cost(1e6, 5e7, 0.02)
    assert R.liquidity_cost(0, 1, 0.02) == 0
