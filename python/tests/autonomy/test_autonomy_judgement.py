"""The long-horizon judgement baseline: it learns something on its own distribution, it is calibrated, it survives a JSON round
trip, and in the admission controller it can only hold, never allow what the hard checks refuse."""
import numpy as np

from orderguard_autonomy import judgement as J
from orderguard_autonomy.admission import Decision

from autonomy_helpers import SECTORS, make_controller, req


def _small_model(seed=3):
    train, cal = J.make_dataset(60, seed), J.make_dataset(30, seed + 1)
    Xt, yt, _ = J._stack(train)
    Xc, yc, _ = J._stack(cal)
    return J.LogisticJudge(l2=1.0).fit(Xt, yt, Xc, yc)


def test_dataset_is_deterministic_and_labelled():
    a, b = J.make_dataset(5, 7), J.make_dataset(5, 7)
    assert [[r["y"] for r in ep] for ep in a] == [[r["y"] for r in ep] for ep in b]
    assert {ep[0]["mode"] for ep in J.make_dataset(40, 7)} == set(J.MODES)
    assert all(r["y"] == 0 for ep in a for r in ep if r["mode"] == "clean")


def test_small_model_separates_in_distribution_and_round_trips():
    m = _small_model()
    res = J.evaluate(m, J.make_dataset(40, 99))
    assert res["auroc"] > 0.85
    assert res["ece"] < 0.1
    m2 = J.LogisticJudge.from_json(m.to_json())
    X, _, _ = J._stack(J.make_dataset(3, 5))
    assert np.allclose(m.predict(X), m2.predict(X))
    assert isinstance(m.explain(X[0]), str)


def test_auroc_matches_definition():
    y = np.array([0, 0, 1, 1])
    assert J.auroc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert J.auroc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert abs(J.auroc(y, np.array([0.5, 0.5, 0.5, 0.5])) - 0.5) < 1e-9


class _Always:
    """A judge that is certain every action is bad, or certain every action is fine."""
    def __init__(self, p):
        self.p = p

    def score_request(self, *a):
        return self.p, "fixed"


class _Broken:
    def score_request(self, *a):
        raise RuntimeError("model down")


def test_judgement_only_tightens():
    # a judge that flags everything turns allows into holds, never into refusals of risk-reducing orders or into allows
    strict = make_controller(judgement=_Always(1.0))
    r = strict.admit(req(strict, "a1", "AAPL", "buy", 10))
    assert r.decision == Decision.HOLD
    # a judge that approves everything cannot rescue an order a hard check refuses
    lax = make_controller(judgement=_Always(0.0))
    r = lax.admit(req(lax, "a1", "AAPL", "buy", 10_000))           # $1M, far over the order cap
    assert r.decision == Decision.REFUSE
    # a broken judge degrades to no advice
    broken = make_controller(judgement=_Broken())
    assert broken.admit(req(broken, "a1", "AAPL", "buy", 10)).decision == Decision.ALLOW


def test_long_horizon_judge_scores_real_requests():
    judge = J.LongHorizonJudge(_small_model(), SECTORS)
    ctl = make_controller(judgement=judge, judgement_hold_at=0.99)
    out = [ctl.admit(req(ctl, "a1", s, "buy", 5)).decision for s in ("AAPL", "KO", "JNJ")]
    assert all(d in (Decision.ALLOW, Decision.HOLD) for d in out)
    assert "a1" in judge.mem and len(judge.mem["a1"].exposure_history) == 3
