"""Order-risk layer: the tighten-only invariant, exact JSON inference, point-in-time features, the shipped model, one-shot labels and
the arena replay. Offline and fast."""
import json
import random
import statistics
from pathlib import Path

import pytest

from orderguard_risk import features as F
from orderguard_risk.scorer import MODEL_PATH, ORDER, RiskScorer, arena_event, tighten

ROOT = Path(__file__).resolve().parents[3]
STREAM = ROOT / "results" / "arena" / "arena-s7-k1000-t2000.jsonl"
ENVS = {"core": {"per_order": 25_000.0, "daily": 8_000_000.0, "step_up": 20_000.0, "band_pct": 1.0},
        "tactical": {"per_order": 40_000.0, "daily": 6_000_000.0, "step_up": 30_000.0, "band_pct": 2.0},
        "crypto": {"per_order": 15_000.0, "daily": 2_000_000.0, "step_up": 12_000.0, "band_pct": 3.0}}


def _event(rng, step, agent=None):
    tp = rng.choice([39.7, 222.7, 444.3, 1.0])
    qty = rng.choice([1, 5, 20, 80, 300])
    return {"step": step, "agent": rng.randrange(50) if agent is None else agent, "env": rng.choice(list(ENVS)), "ticker": rng.choice(["AAPL", "MSFT", "NVDA", "BTC"]),
            "side": rng.choice(["buy", "sell"]), "qty": float(qty), "limit": tp * rng.uniform(0.98, 1.02), "tp": tp, "notional": qty * tp,
            "key": f"k{step}-{rng.random()}", "trig": None, "listed": True}


def test_tighten_never_loosens():
    rng = random.Random(1)
    for _ in range(5000):
        d = rng.choice(["allow", "hold", "refuse", "bogus"])
        r = rng.choice([None, {}, {"action": "none"}, {"action": "hold"}, {"action": "refuse"}, {"action": "weird"}])
        out = tighten(d, r)
        assert out in ORDER
        if d in ORDER:
            assert ORDER[out] >= ORDER[d]                     # never looser than the gate
        else:
            assert out == "refuse"                            # unknown gate output fails closed
        if d == "refuse":
            assert out == "refuse"


def test_json_trees_match_sklearn_exactly():
    np = pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    from orderguard_risk.models import TreeEnsemble, fit_trees
    rng = np.random.default_rng(0)
    X = rng.normal(size=(3000, 6)).astype(np.float32)
    y = ((X[:, 0] + 0.5 * X[:, 2] * X[:, 3] + rng.normal(scale=0.3, size=3000)) > 0.4).astype(int)
    clf = fit_trees(X, y, iters=25, seed=0)
    ens = TreeEnsemble.from_json(json.loads(json.dumps(TreeEnsemble.from_sklearn(clf, [f"f{i}" for i in range(6)]).to_json())))
    ref = clf.decision_function(X[:400])
    got = [ens.raw([float(v) for v in x]) for x in X[:400]]
    assert max(abs(a - b) for a, b in zip(ref, got)) < 1e-6


def test_features_are_point_in_time():
    rng = random.Random(7)
    evs = [_event(rng, s // 3) for s in range(600)]

    def run(n):
        eng = F.FeatureEngine(ENVS, 100)
        out = []
        for e in evs[:n]:
            out.append(eng.featurize(e))
            eng.update(e)
        return out
    short, long = run(300), run(600)
    assert short == long[:300]                               # appending later events never changes an earlier feature vector


def test_shipped_model_loads_and_scores_deterministically():
    assert MODEL_PATH.exists() and MODEL_PATH.stat().st_size < 5_000_000
    a, b = RiskScorer.load(), RiskScorer.load()
    for s in (a, b):
        s.set_envelopes(ENVS, 100)
    rng = random.Random(3)
    evs = [_event(rng, i // 4) for i in range(400)]
    ra, rb = [], []
    for e in evs:
        ra.append(a.score(e)["risk"]); a.observe(e)
        rb.append(b.score(e)["risk"]); b.observe(e)
    assert ra == rb and all(0.0 <= p <= 1.0 for p in ra)
    m = json.loads(MODEL_PATH.read_text())
    assert m["format"] == "orderguard-order-risk/2" and "text" not in m["feature_names"][0]
    assert not any(n in m["feature_names"] for n in ("text_logit", "stated_ratio", "has_stated", "script_dup"))   # shipped model is behavioural


def test_score_latency_budget():
    s = RiskScorer.load()
    s.set_envelopes(ENVS, 100)
    rng = random.Random(5)
    lat = []
    for i in range(1500):
        e = _event(rng, i // 5)
        lat.append(s.score(e)["latency_us"])
        s.observe(e)
    lat.sort()
    assert lat[len(lat) // 2] < 500 and lat[int(0.99 * len(lat))] < 5000      # generous for CI; typically ~40 µs median here


def test_one_shot_label_holds_the_same_pattern_without_retraining():
    s = RiskScorer.load()
    s.set_envelopes(ENVS, 100)
    rng = random.Random(11)
    for i in range(800):                                     # build a reference of recent, mostly honest flow
        e = _event(rng, i // 5)
        s.score(e); s.observe(e)
    attack = {**_event(rng, 170, agent=999), "qty": 1.0, "notional": 222.7, "tp": 222.7, "limit": 222.7, "ticker": "AAPL", "env": "core"}
    before = s.score(attack)
    h = s.label_attack(attack, note="analyst case 1")
    assert h is not None and h > 0
    after = s.score(attack)
    assert after["prototype_similarity"] > 0.99 and after["action"] in ("hold", "refuse")
    assert tighten("allow", after) != "allow"
    assert any("labelled as an attack" in r for r in after["reasons"]) or before["action"] != "none"


@pytest.mark.skipif(not STREAM.exists(), reason="recorded arena stream not present")
def test_arena_replay_only_tightens_and_costs_little():
    from orderguard_risk.cli import replay_arena
    res = replay_arena(STREAM, limit=6000)
    assert res["leak_after_usd"] <= res["leak_before_usd"]
    assert res["honest_tightened_rate"] < 0.05
    rows = [json.loads(l) for _, l in zip(range(50), STREAM.open())]
    assert all(set(arena_event(r)) >= {"step", "agent", "env", "ticker", "side", "qty", "tp", "notional"} for r in rows if "order" in r)
