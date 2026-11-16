"""Research proposal: a long-horizon judgement model (design section 3F). Not a feature.

Today's models judge one order or one window. Delegated trading needs judgement that persists: what the book is for, which theses
it holds, what evidence they rest on and how fresh it is, and whether today's actions still fit. The proposal is a model over a
persistent delegation memory, trained on simulated episodes whose long-run outcome is known, calibrated, and bound by the same rule
as every other model here: it can tighten, never approve.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Thesis:
    statement: str
    evidence: list[str] = field(default_factory=list)
    opened_at: str = ""
    status: str = "active"            # active, weakened, abandoned


@dataclass
class DelegationMemory:
    contract_id: str
    purpose: str
    theses: list[Thesis] = field(default_factory=list)
    exposure_history: list[dict] = field(default_factory=list)


class JudgementModel(Protocol):
    def score(self, action: dict, memory: DelegationMemory) -> tuple[float, str]:
        """Probability the action departs from the delegated purpose, and a plain-language reason. Used only to tighten."""
        ...
