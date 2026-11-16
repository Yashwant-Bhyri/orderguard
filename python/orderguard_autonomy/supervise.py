"""The continuous feedback loop (design section 3D).

An agent is a process, not a request: observe actions, market and portfolio; evaluate authority, risk, evidence and drift;
control; reconcile; observe again. Authority is leased: it expires unless renewed under current state, and an epoch number lets
one revocation invalidate a whole chain of spawned agents within one lease length. Semantic checks supervise; they never authorize.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from orderguard_autonomy import not_built


class Control(str, Enum):
    CONTINUE = "continue"
    TIGHTEN = "tighten"                       # smaller limits for this agent or coalition
    REVIEW = "review"                         # a person decides the next action
    SUSPEND_NEW_RISK = "suspend_new_risk"     # no new exposure; cancels and risk-reducing orders still allowed


@dataclass(frozen=True)
class Lease:
    agent: str
    contract_id: str
    epoch: int
    expires_at: float
    parent_agent: str | None = None


class LeaseAuthority:
    """Grants, renews and revokes leases. Revoking an epoch invalidates every lease issued under it, including spawned agents."""

    def grant(self, agent: str, contract_id: str, parent: Lease | None = None) -> Lease:
        raise not_built("section 3D, authorization leases")

    def renew(self, lease: Lease, state_snapshot: int) -> Lease:
        raise not_built("section 3D, authorization leases")

    def revoke_epoch(self, contract_id: str, epoch: int) -> None:
        raise not_built("section 3D, authorization leases")


class ChangeDetector(Protocol):
    """Sequential change detection (CUSUM or SPRT) over one agent's behaviour statistics."""
    def update(self, value: float) -> bool: ...


def herding_signal(orders: list[dict], evidence: dict[str, list[str]]) -> float:
    """How much supposedly independent agents are trading together and on the same sources."""
    raise not_built("section 3D, herding")


def loop_signal(actions: list[tuple[str, str]]) -> float:
    """Repetition in an agent's (tool, arguments) sequence, rising with frequency."""
    raise not_built("section 3D, loops")


def step(observation: dict) -> Control:
    """One turn of the loop: what to do with this agent or coalition now."""
    raise not_built("section 3D, continuous supervision")
