"""Proof-carrying orders (design section 3E).

Every order carries a decision certificate: contract and policy version, portfolio snapshot, reservation, and evidence by content
hash and timestamp. The receiver verifies it and returns a signed receipt that is sealed into the ledger.

It proves the order was admitted against this authority, this state and this evidence. It does not prove the thesis was right.

The checker (`verify`) is deliberately small: it reads only the certificate and the receiver's own copy of the ledger state, does
arithmetic and signature checks, and has no model in it. Per Necula's proof-carrying code, the trusted base is this checker and the
policy, so it is kept short and tested on its own (python/tests/autonomy/test_certificate.py).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

from ._crypto import canonical_json, public_b64, sha256_hex, sign_b64, verify_b64

LIMITS_OF_PROOF = (
    "proves: the order was admitted under this signed contract version, against the ledger state at this snapshot, with this "
    "reservation held and this evidence on record, by a holder of the admission key",
    "does not prove: that the thesis was right, that the evidence is true, that the risk estimate is correct, that the broker "
    "executed the order as sent, or that state outside this ledger was accounted for",
)


@dataclass(frozen=True)
class EvidenceRef:
    source_id: str
    content_sha256: str
    observed_at: float


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
    contract_sha256: str = ""
    intent_sha256: str = ""
    lease_id: str = ""
    lease_epoch: int = 0
    lineage: str = ""
    order_id: str = ""
    reduces_position: bool = False    # admitted as risk-reducing: it reserved no dollars, and the receiver re-checks that it still reduces
    issued_at: float = 0.0
    decision: str = "allow"
    issuer_key: str = ""
    issuer_signature: str = ""

    def body(self) -> dict:
        d = asdict(self)
        d.pop("issuer_signature")
        d["evidence"] = [asdict(e) for e in self.evidence]
        return d

    def sha256(self) -> str:
        return sha256_hex(canonical_json({**self.body(), "issuer_signature": self.issuer_signature}))

    def size_bytes(self) -> int:
        return len(canonical_json({**self.body(), "issuer_signature": self.issuer_signature}))


@dataclass(frozen=True)
class Receipt:
    certificate_sha256: str
    decision: str                     # allow, hold or refuse
    checks: tuple[str, ...]
    ledger_seal: str
    signature: str
    failures: tuple[str, ...] = ()
    receiver_key: str = ""
    limits_of_proof: tuple[str, ...] = field(default=LIMITS_OF_PROOF)


def issue(cert: DecisionCertificate, issuer_key) -> DecisionCertificate:
    """The admission controller signs the certificate it attaches to an allowed order."""
    unsigned = replace(cert, issuer_key=public_b64(issuer_key), issuer_signature="")
    return replace(unsigned, issuer_signature=sign_b64(issuer_key, unsigned.body()))


def verify(cert: DecisionCertificate, state, *, max_evidence_age_s: float | None = None, trusted_issuers: set[str] | None = None,
           now: float | None = None, max_snapshot_lag: int | None = None, receiver_key=None, ledger=None) -> Receipt:
    """Check signatures, policy version, snapshot freshness, reservation and evidence freshness, then issue a sealed receipt.

    `state` is the receiver's own PortfolioState (rebuilt from the ledger it trusts), never one supplied by the sender. Every check is
    deterministic. The receipt is refused if any check fails; it is then sealed into `ledger` (if given) and signed with
    `receiver_key` (if given)."""
    checks, failures = [], []

    def ck(name: str, ok: bool, why: str) -> None:
        (checks if ok else failures).append(name if ok else f"{name}: {why}")

    sig_ok = bool(cert.issuer_signature) and verify_b64(cert.issuer_key, cert.issuer_signature, cert.body())
    ck("issuer_signature", sig_ok, "the certificate is not signed by its stated key, or was altered after signing")
    ck("trusted_issuer", trusted_issuers is None or cert.issuer_key in trusted_issuers, "the signing key is not a trusted admission key")
    ck("decision_allow", cert.decision == "allow", f"certificate records '{cert.decision}', not an allow")
    current = getattr(state, "policy_versions", {}).get(cert.contract_id)
    ck("policy_version", current is not None and int(current) == int(cert.policy_version),
       f"certificate is for version {cert.policy_version}, the ledger has {current}")
    snap = int(getattr(state, "snapshot", 0))
    ck("snapshot_not_future", cert.portfolio_snapshot <= snap, "the certificate names a snapshot this ledger has not reached")
    if max_snapshot_lag is not None:
        ck("snapshot_fresh", snap - cert.portfolio_snapshot <= max_snapshot_lag,
           f"admitted {snap - cert.portfolio_snapshot} ledger entries ago (limit {max_snapshot_lag})")
    rev = getattr(state, "revoked_epochs", {}).get(f"{cert.contract_id}/{cert.lineage}", -1)
    rev_all = getattr(state, "revoked_epochs", {}).get(cert.contract_id, -1)
    ck("lease_epoch", cert.lease_epoch > max(rev, rev_all), f"lease epoch {cert.lease_epoch} has been revoked")
    res = getattr(state, "reservations", {}).get(cert.reservation_id)
    wo = getattr(state, "working", {}).get(cert.order_id) if cert.order_id else None
    ok_res = res is not None and wo is not None and res.order_id == cert.order_id
    if ok_res:
        o = cert.order
        ok_res = (wo.symbol == o.get("symbol") and wo.side == o.get("side") and abs(wo.quantity - float(o.get("quantity", -1))) < 1e-9
                  and abs(wo.limit_price - float(o.get("limit_price", -1))) < 1e-9 and wo.agent == cert.agent_id
                  and wo.contract_id == cert.contract_id)
    ck("reservation", ok_res, "no matching reservation is held for this exact order")
    if ok_res:
        need = float(cert.order["quantity"]) * float(cert.order["limit_price"])
        if cert.reduces_position:
            pos = float(getattr(state, "positions", {}).get(cert.order["symbol"], 0.0))
            signed = float(cert.order["quantity"]) * (1 if cert.order["side"] == "buy" else -1)
            ck("still_reduces", pos * signed < 0 and abs(signed) <= abs(pos) + 1e-9,
               "admitted as risk-reducing, but against the ledger now it would add to or flip the position")
        else:
            ck("reservation_covers", res.notional_usd + 1e-6 >= need,
               f"reservation ${res.notional_usd:,.2f} does not cover ${need:,.2f} at the limit price")
    if max_evidence_age_s is not None and now is not None:
        old = [e.source_id for e in cert.evidence if now - float(e.observed_at) > max_evidence_age_s]
        ck("evidence_fresh", not old, f"evidence too old: {', '.join(old)}")
    decision = "allow" if not failures else "refuse"
    cert_hash = cert.sha256()
    payload = {"certificate_sha256": cert_hash, "decision": decision, "checks": checks, "failures": failures}
    seal = ""
    if ledger is not None:
        entry = ledger.append({"kind": "receipt", **payload})
        seal = entry["hash"]
    sig = sign_b64(receiver_key, {**payload, "ledger_seal": seal}) if receiver_key is not None else ""
    return Receipt(cert_hash, decision, tuple(checks), seal, sig, tuple(failures), public_b64(receiver_key) if receiver_key else "")


def verify_receipt(r: Receipt, receiver_public_key: str) -> bool:
    payload = {"certificate_sha256": r.certificate_sha256, "decision": r.decision, "checks": list(r.checks), "failures": list(r.failures),
               "ledger_seal": r.ledger_seal}
    return verify_b64(receiver_public_key, r.signature, payload)
