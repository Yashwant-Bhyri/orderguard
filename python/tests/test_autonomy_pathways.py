"""The autonomy pathways are interfaces until built. These tests keep them honest: the shapes exist, the one rule that is already
decided (tighten-only) holds, and every unbuilt pathway says so instead of returning something that looks like a decision."""
import pytest

from orderguard_autonomy import DESIGN
from orderguard_autonomy.admission import Decision, combine
from orderguard_autonomy import contract, state, risk, supervise, certificate


def test_tighten_only_rule():
    D = Decision
    assert combine(D.ALLOW, D.ALLOW) is D.ALLOW
    assert combine(D.ALLOW, D.HOLD) is D.HOLD
    assert combine(D.REFUSE, D.ALLOW) is D.REFUSE      # a model can never turn a hard refusal into an allowance
    assert combine(D.HOLD, D.REFUSE) is D.REFUSE


@pytest.mark.parametrize("call", [
    lambda: contract.compile_predicates(None),
    lambda: contract.is_attenuation(None, None),
    lambda: state.project(state.PortfolioState(), "AAPL", 1),
    lambda: state.EscrowNode("book", 1, 1).reserve(None, 1, 1),
    lambda: risk.incremental_es(None, {}, {}),
    lambda: risk.declared_scenario_loss({}, []),
    lambda: supervise.step({}),
    lambda: supervise.LeaseAuthority().grant("a", "c"),
    lambda: certificate.verify(None, None),
])
def test_unbuilt_pathways_say_so(call):
    with pytest.raises(NotImplementedError, match=DESIGN):
        call()
