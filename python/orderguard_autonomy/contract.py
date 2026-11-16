"""The signed specification (design section 3A).

Three objects are never merged: what the owner said (Intent), what a model proposed (ProposedPolicy) and what the owner signed
(AutonomyContract). A model may propose numbers; only a signature makes them binding, and the diff between the two is kept.
Delegation is by attenuation: a child contract may only be narrower than its parent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from orderguard_autonomy import not_built


@dataclass(frozen=True)
class Intent:
    """The owner's words, kept verbatim. Never enforced directly."""
    text: str
    owner: str


@dataclass(frozen=True)
class ProposedPolicy:
    """Numbers a model suggests for an Intent, with the scenario consequences shown to the owner before signing."""
    intent: Intent
    limits: dict
    consequences: dict = field(default_factory=dict)     # declared scenario -> projected loss under these limits
    proposer: str = ""


@dataclass(frozen=True)
class AutonomyContract:
    """What the owner signed. Trading permissions, portfolio constraints and autonomy terms, plus the signature over all of them."""
    contract_id: str
    principal: str
    authorized_agents: tuple[str, ...]
    trading: dict             # allowed assets, sides, leverage, largest single order
    portfolio: dict           # issuer and sector weights, factor exposure, declared-scenario loss, turnover
    autonomy: dict            # lease length, order rate per agent, when a person reviews, state freshness
    parent_id: str | None = None
    signature: str = ""
    signer_public_key: str = ""


class PolicyProposer(Protocol):
    """Turns an Intent into a ProposedPolicy. A proposal, never an authorization."""
    def propose(self, intent: Intent) -> ProposedPolicy: ...


@dataclass(frozen=True)
class Predicate:
    """One enforceable condition compiled from a contract, e.g. projected issuer weight <= 0.15. `hard` predicates can refuse."""
    name: str
    hard: bool
    description: str


def signed_diff(proposed: ProposedPolicy, signed: AutonomyContract) -> dict:
    """What the owner changed between the model's proposal and what they signed. Recorded with the contract."""
    raise not_built("section 3A, intent to signed specification")


def compile_predicates(contract: AutonomyContract) -> list[Predicate]:
    """Compile a signed contract into the predicates the admission controller evaluates."""
    raise not_built("section 3A, intent to signed specification")


def is_attenuation(parent: AutonomyContract, child: AutonomyContract) -> bool:
    """True only if every permission and limit of `child` is inside `parent`. Delegation that widens authority is refused."""
    raise not_built("section 3A, attenuated delegation")
