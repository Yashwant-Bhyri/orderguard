"""Proof-carrying orders (design section 3E).

Every order carries a decision certificate: contract and policy version, portfolio snapshot, reservation, and evidence by content
hash and timestamp. The receiver verifies it and returns a signed receipt that is sealed into the ledger.

It proves the order was admitted against this authority, this state and this evidence. It does not prove the thesis was right.
"""
from __future__ import annotations

from dataclasses import dataclass

from orderguard_autonomy import not_built


@dataclass(frozen=True)
class EvidenceRef:
    source_id: str
    content_sha256: str
    observed_at: str


@dataclass(frozen=True)
class DecisionCertificate:
    order: dict                       # symbol, side, quantity, limit price
    agent_id: str
    strategy_version: str
    contract_id: str
    policy_version: int
    objective_id: str
    evidence: tuple[EvidenceRef, ...]
    portfolio_snapshot: int
    reservation_id: str


@dataclass(frozen=True)
class Receipt:
    certificate_sha256: str
    decision: str                     # allow, hold or refuse
    checks: tuple[str, ...]
    ledger_seal: str
    signature: str


def verify(cert: DecisionCertificate, state, *, max_evidence_age_s: float | None = None) -> Receipt:
    """Check signatures, policy version, snapshot freshness, reservation and evidence freshness, then issue a sealed receipt."""
    raise not_built("section 3E, proof-carrying orders")
