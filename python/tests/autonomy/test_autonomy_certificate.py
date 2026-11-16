"""Proof-carrying orders: a small certificate the receiver checks deterministically, and what it refuses (adversarial)."""
from dataclasses import replace

import pytest

from autonomy_helpers import ADMIT, RECEIVER, make_controller, req
from orderguard_autonomy._crypto import key_from_label, public_b64
from orderguard_autonomy.certificate import LIMITS_OF_PROOF, issue, verify, verify_receipt
from orderguard_autonomy.state import L

TRUSTED = {public_b64(ADMIT)}


@pytest.fixture
def admitted():
    ctl = make_controller()
    r = ctl.admit(req(ctl, "a1", "KO", "buy", 20, limit=100.5))
    assert r.certificate is not None
    return ctl, r


def _check(ctl, cert, **kw):
    return verify(cert, ctl.ledger.state, trusted_issuers=TRUSTED, now=ctl.test_clock(), max_evidence_age_s=3600,
                  receiver_key=RECEIVER, ledger=ctl.ledger, **kw)


def test_valid_certificate_gets_a_sealed_signed_receipt(admitted):
    ctl, r = admitted
    rc = _check(ctl, r.certificate)
    assert rc.decision == "allow" and not rc.failures
    assert rc.ledger_seal == ctl.ledger.head                         # the receipt is the latest ledger entry
    assert verify_receipt(rc, public_b64(RECEIVER))
    assert not verify_receipt(replace(rc, decision="refuse"), public_b64(RECEIVER))
    assert rc.limits_of_proof == LIMITS_OF_PROOF and "does not prove" in LIMITS_OF_PROOF[1]
    assert r.certificate.size_bytes() < 2048                          # small enough to travel with every order


@pytest.mark.parametrize("field,value", [
    ("order", {"symbol": "KO", "side": "buy", "quantity": 200.0, "limit_price": 100.5}),
    ("order", {"symbol": "XOM", "side": "buy", "quantity": 20.0, "limit_price": 100.5}),
    ("agent_id", "a2"), ("policy_version", 7), ("portfolio_snapshot", 1), ("reservation_id", "nope"), ("decision", "hold"),
])
def test_any_altered_field_is_refused(admitted, field, value):
    ctl, r = admitted
    rc = _check(ctl, replace(r.certificate, **{field: value}))
    assert rc.decision == "refuse"
    assert any("issuer_signature" in f for f in rc.failures)


def test_re_signed_forgeries_fail_on_substance(admitted):
    ctl, r = admitted
    mallory = key_from_label("mallory")
    forged = issue(replace(r.certificate, order={**r.certificate.order, "quantity": 500.0}), mallory)
    rc = _check(ctl, forged)
    assert any("trusted_issuer" in f for f in rc.failures) and any("reservation" in f for f in rc.failures)
    # even with the real admission key, a certificate for a bigger order than reserved is refused
    inflated = issue(replace(r.certificate, order={**r.certificate.order, "quantity": 500.0}), ADMIT)
    assert any("reservation" in f for f in _check(ctl, inflated).failures)
    other = make_controller().admit(req(make_controller(), "a1", "KO", "buy", 1))
    assert other.certificate is None or _check(ctl, other.certificate).decision == "refuse"


def test_released_reservation_revoked_epoch_new_version_and_stale_evidence_refuse(admitted):
    ctl, r = admitted
    cert = r.certificate
    assert _check(ctl, cert, max_snapshot_lag=0).decision == "allow"
    ctl.ledger.set_marks({"KO": 100.0}, ctl.test_clock())
    assert any("snapshot_fresh" in f for f in _check(ctl, cert, max_snapshot_lag=0).failures)
    late = verify(cert, ctl.ledger.state, trusted_issuers=TRUSTED, now=ctl.test_clock() + 10_000, max_evidence_age_s=3600)
    assert any("evidence_fresh" in f for f in late.failures)
    ctl.quarantine("a1")
    assert any("lease_epoch" in f for f in _check(ctl, cert).failures)
    ctl2 = make_controller()
    r2 = ctl2.admit(req(ctl2, "a2", "KO", "buy", 5))
    ctl2.on_terminal(r2.order_id, L.CANCELED, 0)
    rc = verify(r2.certificate, ctl2.ledger.state, trusted_issuers=TRUSTED)
    assert any("reservation" in f for f in rc.failures)
    ctl2.ledger.set_policy("c1", 2)
    r3 = ctl2.admit(req(ctl2, "a3", "KO", "buy", 5))
    assert r3.decision.value == "refuse"                               # the controller's contract is no longer current


def test_certificate_names_its_inputs(admitted):
    _, r = admitted
    c = r.certificate
    assert c.contract_sha256 and c.intent_sha256 and c.lease_id and c.evidence and c.evidence[0].content_sha256
    assert c.portfolio_snapshot > 0 and c.objective_id
