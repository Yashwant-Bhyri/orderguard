"""Programmed units, one-shot weight edits, exact inference and latency of the v2 order-risk model. Offline and fast."""
import json
import random
from pathlib import Path

import pytest

from orderguard_risk import features as F
from orderguard_risk import program as G
from orderguard_risk.scorer import MODEL_PATH, RiskScorer, tighten

ENVS = {"core": {"per_order": 25_000.0, "daily": 8_000_000.0, "step_up": 20_000.0, "band_pct": 1.0},
        "crypto": {"per_order": 15_000.0, "daily": 2_000_000.0, "step_up": 12_000.0, "band_pct": 3.0}}
TICKERS = {"core": ["AAPL", "MSFT", "JPM", "KO"], "crypto": ["BTC", "ETH"]}
PX = {"AAPL": 222.7, "MSFT": 444.3, "JPM": 201.1, "KO": 61.3, "BTC": 1000.0, "ETH": 250.0}


def honest_stream(seed=0, agents=60, steps=400, start=0, first_agent=0):
    """Scheduled agents: each has its own period, usual size and distance from the price; prices drift a little."""
    rng = random.Random(seed)
    spec = []
    for a in range(agents):
        env = "core" if a % 3 else "crypto"
        spec.append((first_agent + a, env, rng.randint(20, 60), rng.randrange(60), rng.uniform(800, 4000), rng.uniform(0.0005, 0.003), rng.sample(TICKERS[env], 2)))
    px = dict(PX)
    out = []
    for step in range(start, start + steps):
        for t in px:
            px[t] *= 1 + rng.gauss(0, 0.0008)
        for aid, env, period, phase, size, aggr, tks in spec:
            if (step + phase) % period:
                continue
            tk = tks[(step // period) % 2]
            side = rng.choice(["buy", "sell"])
            qty = max(1, round(size * rng.uniform(0.9, 1.1) / px[tk]))
            out.append({"step": step, "agent": aid, "env": env, "ticker": tk, "side": side, "qty": float(qty), "tp": px[tk],
                        "limit": round(px[tk] * (1 + aggr if side == "buy" else 1 - aggr), 2), "notional": qty * px[tk], "key": f"h{aid}-{step}", "trig": None, "listed": True})
    return out, px


def scorer_with(history):
    s = RiskScorer.load()
    s.set_envelopes(ENVS, 500)
    res = []
    for e in history:
        res.append(s.score(e))
        s.observe(e)
    return s, res


def fired(r, name, level=0.5):
    return any(u["name"] == name and u["activation"] >= level for u in r.get("units", []))


def order(step, agent, tk, usd, px, env="core", side="buy", dev=0.001, key=None):
    qty = max(1, round(usd / px[tk]))
    return {"step": step, "agent": agent, "env": env, "ticker": tk, "side": side, "qty": float(qty), "tp": px[tk],
            "limit": round(px[tk] * (1 + dev if side == "buy" else 1 - dev), 2), "notional": qty * px[tk], "key": key or f"x{agent}-{step}-{usd}", "trig": None, "listed": True}


def test_no_programmed_unit_fires_on_an_honest_baseline():
    hist, _ = honest_stream(seed=1)
    _s, res = scorer_with(hist)
    assert len(res) > 500
    assert not any(u["activation"] >= 0.5 for r in res for u in r["units"])
    assert sum(r["action"] != "none" for r in res) <= 0.01 * len(res)


def run_signature(events_fn):
    hist, px = honest_stream(seed=2, steps=300)
    s, _ = scorer_with(hist)
    out = []
    for e in events_fn(px):
        out.append(s.score(e))
        s.observe(e)
    return out


def test_unit_split_under_threshold_and_coordinated_burst_fire_on_collusion():
    def ev(px):
        return [order(300 + t, 900 + a, "AAPL", 19_000, px) for t in range(14) for a in range(5)]
    res = run_signature(ev)
    assert any(fired(r, "split_under_threshold") for r in res)
    assert any(fired(r, "coordinated_burst") for r in res)
    assert all(tighten("allow", r) != "allow" for r in res[-20:])           # once the pattern is established every slice is stopped


def test_unit_order_rate_and_repeat_loop_fire_on_a_runaway():
    def ev(px):
        return [order(300 + t, 950, "MSFT", 2_000, px, key=f"loop{t}") | {"qty": 4.0, "limit": 445.0, "notional": 4 * px["MSFT"]} for t in range(12)]
    res = run_signature(ev)
    assert any(fired(r, "repeat_loop") for r in res) and any(fired(r, "order_rate") for r in res)
    assert tighten("allow", res[-1]) != "allow"


def test_unit_size_discontinuity_fires_on_a_fat_finger_only():
    def ev(px):
        return [order(300 + 40 * t, 960, "KO", 2_000, px) for t in range(6)] + [order(540, 960, "KO", 20_000, px)]
    res = run_signature(ev)
    assert fired(res[-1], "size_discontinuity") and not any(fired(r, "size_discontinuity") for r in res[:-1])
    assert tighten("allow", res[-1]) != "allow"


def test_unit_limit_far_from_trusted_fires_on_a_stale_price():
    def ev(px):
        return [order(300 + 40 * t, 970, "BTC", 2_000, px, env="crypto") for t in range(5)] + [order(500, 970, "BTC", 2_000, px, env="crypto", dev=0.08)]
    res = run_signature(ev)
    assert fired(res[-1], "limit_far_from_trusted") and not any(fired(r, "limit_far_from_trusted") for r in res[:-1])


def test_unit_schedule_break_fires_off_schedule_only():
    def ev(px):
        return [order(300 + 40 * t, 980, "JPM", 2_000, px) for t in range(6)] + [order(513, 980, "JPM", 2_000, px, side="sell")]
    res = run_signature(ev)
    assert fired(res[-1], "schedule_break") and not any(fired(r, "schedule_break") for r in res[:-1])
    assert any("schedule" in t for t in res[-1]["reasons"])


def test_programmed_weight_cannot_be_explained_away():
    """risk >= pi * activation for every unit, whatever the learned part says."""
    hist, px = honest_stream(seed=3, steps=300)
    s, _ = scorer_with(hist)
    pis = {u["name"]: u["pi"] for u in s.model["units"]}
    for t in range(12):
        e = order(300 + t, 990, "MSFT", 1_500, px) | {"qty": 3.0, "limit": 440.0}
        r = s.score(e)
        s.observe(e)
        for u in r["units"]:
            assert r["risk"] >= pis[u["name"]] * u["activation"] - 1e-6
    assert all(u["pi"] >= G.PI_FLOOR_FRAC * u["programmed_pi"] for u in s.model["units"])


def test_one_shot_weight_edit_holds_the_pattern_within_the_honest_budget():
    hist, px = honest_stream(seed=4, steps=500)
    s, _ = scorer_with(hist)

    def attack(step, agent):                                 # a new pattern no unit knows: marketable sells 2% through the price in the 3% band
        return order(step, agent, "ETH", 1_500, px, env="crypto", side="sell", dev=0.02)
    a0 = attack(500, 2000)
    before = s.score(a0)
    assert before["action"] == "none"
    kappa = s.label_attack(a0, note="case 7")
    assert kappa and kappa > 0 and len(s.edits) == 1
    assert s.edits[0]["captured_reference"] <= max(1, int(0.001 * s.edits[0]["reference_orders"]))
    s.observe(a0)
    after = s.score(attack(502, 2001))                       # a DIFFERENT agent repeating the pattern, a bit less extreme
    assert after["action"] == "hold" and tighten("allow", after) == "hold"
    assert any("labelled as an attack" in r and "case 7" in r for r in after["reasons"])
    more, _ = honest_stream(seed=5, steps=300, start=503, first_agent=0)
    newly = 0
    for e in more:
        r = s.score(e)
        s.observe(e)
        newly += any("labelled as an attack" in t for t in r["reasons"])
    assert newly <= 0.005 * len(more)                        # the edit stays inside its honest capture budget on fresh honest flow


def test_one_shot_edit_refuses_to_write_a_pattern_that_looks_honest():
    hist, px = honest_stream(seed=6, steps=400)
    s, _ = scorer_with(hist)
    ref = [x for _a, x in s.recent_x]
    assert len(ref) >= 200
    assert G.edit_from_example(ref[len(ref) // 2], ref, stats=s.model["edit"]) is None


def test_units_numpy_and_python_agree_and_json_matches_reference():
    np = pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    from orderguard_risk import pipeline as P
    from orderguard_risk.models import TreeEnsemble, fit_platt
    rng = np.random.default_rng(0)
    X = np.abs(rng.normal(size=(3000, F.NF))).astype(np.float32) * 3
    X[:, F.IX["trig"]] = -1
    y = ((X[:, F.IX["agent_burst"]] + X[:, F.IX["size_jump"]] * X[:, 3] + rng.normal(scale=0.5, size=3000)) > 5).astype(int)
    clf = P._trees2(X, y, P.V2_COLS, True, 20, 0)
    raw = clf.decision_function(X[:, P.V2_COLS])
    platt = fit_platt(raw, y)
    ft = P.Fitted2(clf, P.V2_COLS, platt, [u["pi"] for u in G.UNITS], {b: 0.5 for b in P.BUDGETS}, 0.9)
    ref = P.predict2(ft, X[:300])
    ens = TreeEnsemble.from_json(json.loads(json.dumps(TreeEnsemble.from_sklearn(clf, [F.NAMES[c] for c in P.V2_COLS]).to_json())))
    ens.platt = platt
    cu = G.compile_units()
    got = []
    for x in X[:300].astype(float).tolist():
        q = 1.0 - ens.prob(ens.raw([x[c] for c in P.V2_COLS]))
        for u in cu:
            q *= 1.0 - u["pi"] * G.unit_value(u["terms"], x)
        got.append(1.0 - q)
    assert max(abs(a - b) for a, b in zip(ref, got)) < 1e-6
    U = G.units_matrix(X[:300])
    assert max(abs(U[i, k] - G.unit_value(u["terms"], X[i].astype(float).tolist())) for i in range(300) for k, u in enumerate(cu)) < 1e-5
    assert all(v >= 0 for v in clf.monotonic_cst) and sum(clf.monotonic_cst) == len(P.MONO)


def test_v2_latency_including_features():
    hist, _ = honest_stream(seed=8, steps=600, agents=120)
    s = RiskScorer.load()
    s.set_envelopes(ENVS, 500)
    lat = []
    for e in hist:
        lat.append(s.score(e)["latency_us"])
        s.observe(e)
    lat.sort()
    assert lat[len(lat) // 2] < 300 and lat[int(0.99 * len(lat))] < 2000      # generous for CI; measured ~45 us median, < 300 us p99


def test_first_model_still_loads_for_comparison():
    p = MODEL_PATH.with_name("order_risk_v1.json")
    if not p.exists():
        pytest.skip("v1 model not kept")
    s = RiskScorer.load(p)
    s.set_envelopes(ENVS, 500)
    hist, _ = honest_stream(seed=9, steps=100)
    assert all(0.0 <= s.score(e)["risk"] <= 1.0 for e in hist[:50]) and "units" not in s.score(hist[0])
