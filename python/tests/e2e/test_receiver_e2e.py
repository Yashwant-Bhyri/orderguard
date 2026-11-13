"""End to end against the real TypeScript receiver bridge (L8) on a loopback port.

Skips cleanly when node is missing or the sandbox forbids binding a port. Every decision below is made by the receiver core, not by Python:
the python side only proposes orders and reads the ledger back.
"""
from __future__ import annotations

import json
import datetime as dt
import socket
from concurrent.futures import ThreadPoolExecutor

import pytest

from orderguard_guard.broker import Fill, OrderRouter, Reject, ReceiverPaperBroker
from orderguard_guard import cli, gate, init_cmd
from orderguard_guard.paper_commands import ACTIVATE, REVOCATIONS, parent_proof, sign_action
from orderguard_guard.receiver_client import Bridge, ReceiverError, bridge_available

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

MANDATE = {"symbols": ["AAPL", "MSFT"], "sides": ["buy"], "maxOrderNotionalUsd": 10000, "maxDailyNotionalUsd": 20000, "priceBandPct": 5,
           "referencePrices": {"AAPL": 222.7, "MSFT": 420.18}}
BIND_ERRORS = ("EPERM", "EACCES", "operation not permitted", "permission denied", "listen ")


def _can_bind_loopback() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
    except OSError as e:
        return f"binding a loopback port is not permitted here ({e})"
    return None


def start_bridge(tmp_path, name, **mandate_over) -> Bridge:
    ok, why = bridge_available()
    if not ok:
        pytest.skip(f"receiver bridge unavailable: {why}")
    blocked = _can_bind_loopback()
    if blocked:
        pytest.skip(blocked)
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({**MANDATE, "expiresAt": exp, **mandate_over}))
    try:
        return Bridge.start(path, timeout=90)
    except ReceiverError as e:
        if any(m.lower() in str(e).lower() for m in BIND_ERRORS):
            pytest.skip(f"the bridge could not bind a port in this environment: {e}")
        raise


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    b = start_bridge(tmp_path_factory.mktemp("bridge"), "shared")
    yield b
    b.stop()


def ledger_state(rc):
    s = rc.snapshot()
    return len([o for o in s["orders"] if o.get("status", "filled") == "filled"]), s


def test_bridge_is_healthy_and_the_ledger_starts_intact(bridge):
    h = bridge.receiver.health()
    assert h["status"] == "ready" and h["revoked"] is False and h["issuerMandateActive"] is True
    assert bridge.receiver.snapshot()["ledgerIntegrity"] is True


def test_owner_activates_reviewed_draft_on_the_same_paper_ledger(tmp_path, capsys):
    available, reason = bridge_available()
    if not available or _can_bind_loopback():
        pytest.skip(reason or "loopback ports unavailable")
    owner_dir = tmp_path / "owner"
    init_cmd.init(owner_dir)
    parent = json.loads((owner_dir / init_cmd.MANDATE_FILE).read_text())
    key = gate.private_key_from_b64((owner_dir / init_cmd.KEY_FILE).read_text().strip())
    body = gate.Mandate.from_dict(parent).to_dict(with_signature=False)
    draft = body | {"sides": ["buy"], "maxOrderNotionalUsd": 800, "maxDailyNotionalUsd": 1000, "priceBandPct": 1}
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(draft))
    proof_path = tmp_path / "parent-proof.json"
    proof_path.write_text(json.dumps(parent_proof(parent)))
    revocations = owner_dir / REVOCATIONS
    with Bridge.start(proof_path, owner_public_key=owner_dir / init_cmd.PUB_FILE, revocations=revocations) as b:
        receiver = b.receiver
        args = ["--dir", str(owner_dir), "--receiver", f"http://127.0.0.1:{b.port}"]
        original = receiver.policy()
        assert original["parentId"] == gate.Mandate.from_dict(parent).id and original["revision"] == 0
        filled = receiver.propose("AAPL", "buy", 2, 200, "before-policy")
        held = receiver.propose("AAPL", "buy", 3, 200, "old-hold")
        assert filled["decision"] == "filled" and held["decision"] == "held"

        wrong_key, _ = gate.generate_keypair()
        wrong = receiver.activate_policy(sign_action(wrong_key, original, ACTIVATE, draft=draft))
        assert "signature did not verify" in wrong["error"]
        wide = receiver.activate_policy(sign_action(key, original, ACTIVATE, draft=draft | {"maxDailyNotionalUsd": 3000}))
        assert "does not fit" in wide["error"]
        other_ledger = receiver.activate_policy(sign_action(key, original | {"ledgerId": "0" * 32}, ACTIVATE, draft=draft))
        assert "different policy action or ledger" in other_ledger["error"]
        assert receiver.policy() == original

        proof = sign_action(key, original, ACTIVATE, draft=draft)
        assert cli.main(["activate-draft", str(path), *args]) == 0
        activated = json.loads(capsys.readouterr().out)
        assert activated["policy"]["revision"] == 1 and activated["cancelled"] == 1
        assert receiver.snapshot()["usedNotionalUsd"] == 400
        duplicate = receiver.propose("AAPL", "buy", 2, 200, "before-policy")
        assert duplicate["orderId"] == filled["orderId"] and duplicate["ledgerEffect"] is False
        assert receiver.propose("AAPL", "sell", 1, 200, "bad-side")["reason"] == "side_not_allowed"
        assert receiver.propose("AAPL", "buy", 5, 200, "over-per-order")["reason"] == "per_order_cap"
        assert receiver.propose("AAPL", "buy", 1, 203, "outside-band")["reason"] == "limit_outside_band"

        pending = receiver.propose("AAPL", "buy", 3, 200, "new-hold")
        assert pending["decision"] == "held"
        assert receiver.activate_policy(proof)["replay"] is True
        refused = receiver._req("POST", "/approve", json={"orderId": pending["orderId"]})
        assert refused["reason"] == "approval_invalid" and not refused["ledgerEffect"]
        assert cli.main(["approve-paper-order", pending["orderId"], *args]) == 0
        assert json.loads(capsys.readouterr().out)["ledgerEffect"] is True
        assert receiver.propose("AAPL", "buy", 1, 200, "over-daily")["reason"] == "daily_cap"

        state = receiver.policy()
        proofs = [sign_action(key, state, ACTIVATE, draft=draft | {"priceBandPct": band}) for band in (0.4, 0.6)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(receiver.activate_policy, proofs))
        assert sum("policy" in result for result in results) == 1
        assert sum("active policy changed" in result.get("error", "") for result in results) == 1
        assert "active policy changed" in receiver.activate_policy(proof)["error"]

        snap = receiver.snapshot()
        assert snap["ledgerIntegrity"] and snap["usedNotionalUsd"] == 1000
        assert [order["status"] for order in snap["orders"]] == ["filled", "cancelled", "filled"]
        revocations.write_text(json.dumps([original["parentId"]]))
        assert receiver.propose("AAPL", "buy", 1, 200, "revoked-parent")["reason"] == "mandate_revoked"
        new_proof = sign_action(key, receiver.policy(), ACTIVATE, draft=draft)
        assert "inactive" in receiver.activate_policy(new_proof)["error"]
        revocations.unlink()
        assert receiver.propose("AAPL", "buy", 1, 200, "still-revoked")["reason"] == "mandate_revoked"
        assert receiver.snapshot() == snap | {"revoked": True}


def test_allowed_order_fills_once_and_the_duplicate_is_a_replay_with_no_second_effect(bridge):
    rc = bridge.receiver
    before, _ = ledger_state(rc)
    a = rc.propose("AAPL", "buy", 10, 222.7, client_order_id="e2e-honest")
    assert a["decision"] == "filled" and a["ledgerEffect"] is True and a["orderId"]
    b = rc.propose("AAPL", "buy", 10, 222.7, client_order_id="e2e-honest")
    assert b["ledgerEffect"] is False and b.get("orderId", a["orderId"]) == a["orderId"]
    after, snap = ledger_state(rc)
    assert after == before + 1 and snap["ledgerIntegrity"] is True


@pytest.mark.parametrize("label,args,reason", [
    ("unlisted symbol", ("TSLA", "buy", 1, 300.0), "unlisted_symbol"),
    ("fake split price", ("AAPL", "buy", 440, 22.3), "limit_outside_band"),
    ("sell is not in the mandate", ("AAPL", "sell", 1, 222.7), None),
    ("over the per-order cap", ("AAPL", "buy", 100, 222.7), None),
    ("zero quantity", ("AAPL", "buy", 0, 222.7), None),
    ("negative limit", ("AAPL", "buy", 1, -5.0), None),
])
def test_refused_orders_leave_the_ledger_untouched(bridge, label, args, reason):
    rc = bridge.receiver
    before, _ = ledger_state(rc)
    r = rc.propose(*args, client_order_id=f"e2e-{label.replace(' ', '-')}")
    assert r.get("decision") in ("denied", "held") and r.get("ledgerEffect") is False, (label, r)
    if reason:
        assert r["reason"] == reason
    after, snap = ledger_state(rc)
    assert after == before and snap["ledgerIntegrity"] is True


def test_the_daily_cap_stops_a_stream_of_individually_legal_orders(tmp_path):
    b = start_bridge(tmp_path, "daily", maxOrderNotionalUsd=5000, maxDailyNotionalUsd=9000)
    try:
        rc = b.receiver
        out = [rc.propose("AAPL", "buy", 20, 222.7, client_order_id=f"d{i}") for i in range(5)]      # 4,454 each
        assert [o["decision"] for o in out] == ["filled", "filled", "denied", "denied", "denied"]
        assert out[2]["ledgerEffect"] is False
        s = rc.snapshot()
        assert len(s["orders"]) == 2 and s["usedNotionalUsd"] <= 9000 and s["ledgerIntegrity"] is True
    finally:
        b.stop()


def test_an_oversize_request_body_never_reaches_the_ledger(bridge):
    rc = bridge.receiver
    before, _ = ledger_state(rc)
    big = {"symbol": "AAPL", "side": "buy", "quantity": 1, "limitPrice": 222.7, "clientOrderId": "x" * 200_000}
    try:
        r = rc._req("POST", "/propose", json=big)
        assert r.get("decision") != "filled" and r.get("ledgerEffect") is not True
    except ReceiverError:
        pass                                                           # the bridge cut the connection: also a refusal
    assert ledger_state(rc)[0] == before
    assert rc.health()["status"] == "ready"                            # and it still serves


def test_malformed_requests_are_rejected_and_never_fill(bridge):
    rc = bridge.receiver
    before, _ = ledger_state(rc)
    for body in ({}, {"symbol": "AAPL"}, {"symbol": "AAPL", "side": "buy", "quantity": "ten", "limitPrice": 222.7, "clientOrderId": "m1"},
                 {"symbol": ["AAPL"], "side": "buy", "quantity": 1, "limitPrice": 222.7, "clientOrderId": "m2"},
                 {"symbol": "AAPL", "side": "buy", "quantity": 1, "limitPrice": "222.7", "clientOrderId": "m3"},
                 {"symbol": "AAPL", "side": "buy", "quantity": 1.5, "limitPrice": 222.7, "clientOrderId": "m4"}):
        try:
            r = rc._req("POST", "/propose", json=body)
        except ReceiverError:
            continue
        assert r.get("decision") != "filled" and r.get("ledgerEffect") is not True, (body, r)
    assert ledger_state(rc)[0] == before


def test_router_and_paper_broker_through_the_real_receiver(bridge):
    broker = ReceiverPaperBroker(bridge.receiver, starting_cash=100_000.0)
    router = OrderRouter(broker)
    before_pos = broker.positions().get("MSFT", 0)
    o = {"symbol": "MSFT", "side": "buy", "quantity": 5, "limit_price": 420.18}
    refused = router.route(o, {"decision": "refuse", "reasons": ["gate said no"]}, "r-refused")
    assert isinstance(refused, Reject) and broker.positions().get("MSFT", 0) == before_pos
    ok = router.route(o, {"decision": "allow"}, "r-ok")
    assert isinstance(ok, Fill) and broker.positions().get("MSFT", 0) == before_pos + 5
    again = router.route(o, {"decision": "allow"}, "r-ok")
    assert again.replay and broker.positions().get("MSFT", 0) == before_pos + 5
    fake = router.route({**o, "symbol": "AAPL", "quantity": 440, "limit_price": 22.3}, {"decision": "allow"}, "r-fake")       # even if a gate wrongly allowed it
    assert isinstance(fake, Reject) and "limit_outside_band" in fake.reason
    # a second router with the same client order id still cannot double-fill: the receiver is the final authority
    other = OrderRouter(ReceiverPaperBroker(bridge.receiver)).route(o, {"decision": "allow"}, "r-ok")
    assert isinstance(other, Reject) or other.replay
    assert broker.positions().get("MSFT", 0) == before_pos + 5
    spent = 100_000.0 - broker.cash()
    assert spent >= 5 * 420.18 - 1e-6


def test_after_revoke_nothing_fills_and_the_ledger_stays_intact(tmp_path):
    b = start_bridge(tmp_path, "revoke")
    try:
        rc = b.receiver
        assert rc.propose("AAPL", "buy", 5, 222.7, client_order_id="pre")["decision"] == "filled"
        assert rc.revoke()["revoked"] is True
        h = rc.health()
        assert h["revoked"] is True and h["issuerMandateActive"] is False
        n = len(rc.snapshot()["orders"])
        for i in range(5):
            r = rc.propose("AAPL", "buy", 1, 222.7, client_order_id=f"post{i}")
            assert r["decision"] == "denied" and r["reason"] == "mandate_revoked" and r["ledgerEffect"] is False
        again = rc.propose("AAPL", "buy", 5, 222.7, client_order_id="pre")                     # even a replay of a filled order is not a new effect
        assert again["ledgerEffect"] is False
        s = rc.snapshot()
        assert len(s["orders"]) == n and s["ledgerIntegrity"] is True and s["revoked"] is True
        broker = ReceiverPaperBroker(rc)
        assert isinstance(OrderRouter(broker).route({"symbol": "AAPL", "side": "buy", "quantity": 1, "limit_price": 222.7}, {"decision": "allow"}, "post-router"), Reject)
    finally:
        b.stop()


def test_a_stopped_bridge_fails_closed(tmp_path):
    b = start_bridge(tmp_path, "stopped")
    rc, port = b.receiver, b.port
    broker = ReceiverPaperBroker(type(rc)(f"http://127.0.0.1:{port}", timeout=2.0), starting_cash=1000.0)
    b.stop()
    r = OrderRouter(broker).route({"symbol": "AAPL", "side": "buy", "quantity": 1, "limit_price": 222.7}, {"decision": "allow"}, "k-down")
    assert isinstance(r, Reject) and "nothing was placed" in r.reason
    assert broker.positions() == {} and broker.cash() == 1000.0
