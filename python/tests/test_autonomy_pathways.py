"""The autonomy pathways are built. These tests keep the package honest at the top level: the one rule everything rests on
(tighten-only) holds, every pathway that used to raise NotImplementedError now returns a typed result, and the only thing still
marked unbuilt is what the design says is research. Detailed unit, property and adversarial tests are in tests/autonomy/."""
import inspect

import pytest

import orderguard_autonomy
from orderguard_autonomy import DESIGN, certificate, contract, judgement, risk, state, supervise
from orderguard_autonomy.admission import AdmissionController, Decision, combine


def test_tighten_only_rule():
    D = Decision
    assert combine(D.ALLOW, D.ALLOW) is D.ALLOW
    assert combine(D.ALLOW, D.HOLD) is D.HOLD
    assert combine(D.REFUSE, D.ALLOW) is D.REFUSE      # a model can never turn a hard refusal into an allowance
    assert combine(D.HOLD, D.REFUSE) is D.REFUSE
    for a in D:
        for b in D:
            assert [D.ALLOW, D.HOLD, D.REFUSE].index(combine(a, b)) >= [D.ALLOW, D.HOLD, D.REFUSE].index(a)


@pytest.mark.parametrize("call", [
    lambda: risk.declared_scenario_loss({"A": 1.0}, [risk.Scenario("s", {"*": -0.1})]),
    lambda: state.project(state.PortfolioState(), "AAPL", 1),
    lambda: state.reconcile(state.PortfolioState(), [], {}),
    lambda: supervise.step({}),
    lambda: supervise.LeaseAuthority().grant("a", "c"),
    lambda: supervise.herding_signal([], {}),
    lambda: supervise.loop_signal([]),
])
def test_former_stubs_now_return_results(call):
    assert call() is not None


def test_nothing_in_the_package_still_raises_not_built():
    for mod in (contract, state, risk, supervise, certificate, judgement):
        assert "not_built(" not in inspect.getsource(mod), mod.__name__
    assert callable(AdmissionController.admit)
    assert DESIGN == "docs/vision/AUTONOMY.md"
    assert callable(orderguard_autonomy.not_built)    # kept for future pathways
