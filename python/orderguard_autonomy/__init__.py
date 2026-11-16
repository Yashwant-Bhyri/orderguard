"""Continuous autonomy control: the direction OrderGuard is building toward.

An agent never receives general trading authority. It receives a risk-aware delegation contract that is enforced against the
evolving portfolio and every outstanding agent action. Four parts, one module each:

    contract     the signed specification (intent, proposed policy and signed policy kept apart; attenuated delegation)
    state        the authoritative portfolio state (positions, working orders, hierarchical risk escrow, order lifecycle)
    admission    the admission controller (hard checks decide; model-based checks can only tighten)
    supervise    the continuous feedback loop (leases with epochs, drift, herding, loops, budget pacing)

Plus `risk` (counterfactual, incremental portfolio risk), `certificate` (proof-carrying orders and receipts) and `judgement`
(a research proposal for a long-horizon judgement model).

Design and rationale: docs/vision/AUTONOMY.md. Each interface here is the agreed shape of a component; anything not yet built raises
NotImplementedError naming the design section it implements, so nothing in this package can be mistaken for a working control.
"""

DESIGN = "docs/vision/AUTONOMY.md"


def not_built(section: str) -> NotImplementedError:
    """The error every unbuilt pathway raises: it names the design section, so a caller knows exactly what is missing."""
    return NotImplementedError(f"not built yet: see {DESIGN}, {section}")
