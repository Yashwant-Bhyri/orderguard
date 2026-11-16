"""Counterfactual portfolio risk (design section 3C).

The question is not "is this order too large" but "how does it change the risk of the portfolio as it will be".
sigma_p = sqrt(w' Sigma w); ES_a(L) = E[L | L >= VaR_a(L)]; the order's incremental risk is ES(w + d) - ES(w).

Because sigma_p is a norm of Sigma^(1/2) w and ES is coherent, both are subadditive: rho(w + d1 + d2) <= rho(w) + rho(d1) + rho(d2).
So risk budget can be reserved per order like dollars, and the sum of reservations soundly bounds the total without searching the
2^n fill combinations of working orders. Euler allocation returns the diversification benefit at reconciliation.

Two classes, kept apart: loss under *declared* scenarios is arithmetic on signed inputs and may refuse; statistical estimates
(covariance, ES, liquidity, regime) may only hold or tighten.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from orderguard_autonomy import not_built


class CovarianceModel(Protocol):
    """A factor model with shrinkage toward a structured target, plus a stressed variant for crisis correlations."""
    def covariance(self, symbols: Sequence[str], *, stressed: bool = False): ...


@dataclass(frozen=True)
class Scenario:
    """A declared, signed stress scenario: a shock per symbol or factor. Loss under it is deterministic."""
    name: str
    shocks: dict[str, float]


def declared_scenario_loss(exposures: dict[str, float], scenarios: Sequence[Scenario]) -> dict[str, float]:
    """Loss in each declared scenario. Bounds loss in those scenarios only, never real-world loss."""
    raise not_built("section 3C, declared scenarios")


def incremental_es(model: CovarianceModel, exposures: dict[str, float], order: dict[str, float], alpha: float = 0.975) -> float:
    """Estimated Delta ES of adding `order` to `exposures`. Model-dependent: may tighten, never approve."""
    raise not_built("section 3C, counterfactual risk")


def reservable_risk(model: CovarianceModel, order: dict[str, float]) -> float:
    """Standalone risk of an order, the amount reserved against a subadditive risk budget."""
    raise not_built("section 3C, reservable risk budgets")


def euler_contributions(model: CovarianceModel, exposures: dict[str, float]) -> dict[str, float]:
    """Each position's share of portfolio risk, summing to the total; used to return diversification at reconciliation."""
    raise not_built("section 3C, Euler allocation")
