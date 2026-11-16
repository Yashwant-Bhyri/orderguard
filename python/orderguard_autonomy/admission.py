"""The admission controller (design section 2).

Order of evaluation, and the rule that binds it: hard predicates from the signed contract decide first and can refuse; model-based
checks (incremental risk, drift, herding, evidence quality, the judgement model) run after and can only hold or tighten. Nothing a
model returns can turn a refusal into an allowance.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from orderguard_autonomy import not_built


class Decision(str, Enum):
    ALLOW = "allow"
    HOLD = "hold"
    REFUSE = "refuse"


@dataclass(frozen=True)
class Admission:
    decision: Decision
    hard_reasons: tuple[str, ...]
    model_reasons: tuple[str, ...]
    reservation_id: str | None


def combine(hard: Decision, model: Decision) -> Decision:
    """The tighten-only rule: the stricter of the two, and a hard refusal always stands."""
    order = [Decision.ALLOW, Decision.HOLD, Decision.REFUSE]
    return max(hard, model, key=order.index)


class AdmissionController:
    def admit(self, certificate, contract, state) -> Admission:
        """Evaluate one proposed action against the signed contract and the projected portfolio state."""
        raise not_built("section 2, admission controller")
