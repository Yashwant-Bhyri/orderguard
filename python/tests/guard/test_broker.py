from orderguard_guard.broker import Broker, Fill, OrderRouter, ReceiverPaperBroker, Reject, SimBroker
from orderguard_guard.receiver_client import LocalLedger, ReceiverError

ORDER = {"symbol": "AAPL", "side": "buy", "quantity": 10, "limit_price": 100.0}
ALLOW = {"decision": "allow", "reasons": []}


def test_sim_broker_fills_and_tracks_state():
    b = SimBroker(cash=5000)
    assert isinstance(b, Broker)
    f = b.submit(ORDER, "k1")
    assert isinstance(f, Fill) and f.quantity == 10
    assert b.positions() == {"AAPL": 10} and b.cash() == 4000
    assert isinstance(b.submit({**ORDER, "side": "sell", "quantity": 11}, "k2"), Reject)
    assert isinstance(b.submit({**ORDER, "quantity": 1000}, "k3"), Reject)
    assert isinstance(b.submit({**ORDER, "quantity": 0}, "k4"), Reject)


def test_sim_broker_idempotent():
    b = SimBroker()
    f1 = b.submit(ORDER, "k")
    f2 = b.submit(ORDER, "k")
    assert f2.order_id == f1.order_id and f2.replay and b.positions() == {"AAPL": 10}
    assert isinstance(b.submit({**ORDER, "quantity": 5}, "k"), Reject)


def test_router_refuses_non_allow_and_never_calls_broker():
    b = SimBroker()
    r = OrderRouter(b)
    for d in ({"decision": "refuse", "reasons": ["too big"]}, {"decision": "hold", "reasons": []}, {}, {"decision": "ALLOW"}, None):
        res = r.route(ORDER, d, f"k-{d}")
        assert isinstance(res, Reject)
    assert b.positions() == {} and b.cash() == 100_000.0


def test_router_allows_and_is_idempotent():
    b = SimBroker()
    r = OrderRouter(b)
    a = r.route(ORDER, ALLOW, "k")
    again = r.route(ORDER, ALLOW, "k")
    assert isinstance(a, Fill) and again.replay and again.order_id == a.order_id
    assert b.positions() == {"AAPL": 10}
    assert isinstance(r.route({**ORDER, "quantity": 99}, ALLOW, "k"), Reject)
    assert isinstance(r.route(ORDER, ALLOW, ""), Reject)


def test_receiver_paper_broker_through_ledger():
    led = LocalLedger()
    b = ReceiverPaperBroker(led, starting_cash=1000)
    f = b.submit(ORDER, "c1")
    assert isinstance(f, Fill) and f.order_id.startswith("L-")
    assert b.submit(ORDER, "c1").replay or len(led.orders) == 1
    assert len(led.orders) == 1
    led.revoke()
    assert isinstance(b.submit(ORDER, "c2"), Reject)


def test_receiver_paper_broker_fails_closed():
    class Down:
        def propose(self, *a, **k):
            raise ReceiverError("receiver unreachable: ConnectError")
    res = ReceiverPaperBroker(Down()).submit(ORDER, "c")
    assert isinstance(res, Reject) and "nothing was placed" in res.reason


def test_receiver_paper_broker_maps_held_and_snapshot():
    class Fake:
        def propose(self, *a, **k):
            return {"decision": "held", "reason": "step_up_required"}
        def snapshot(self):
            return {"orders": [{"symbol": "AAPL", "side": "buy", "quantity": 3, "status": "filled", "notionalUsd": 300.0},
                               {"symbol": "AAPL", "side": "buy", "quantity": 9, "status": "held", "notionalUsd": 900.0}]}
    b = ReceiverPaperBroker(Fake(), 1000)
    assert b.submit(ORDER, "c").held
    assert b.positions() == {"AAPL": 3} and b.cash() == 700.0


# ---- failure modes: retries, transient results, malformed replies, error text ----
import json as _json
import math as _math

import httpx
import pytest

from orderguard_guard.broker import TRANSIENT_REASONS
from orderguard_guard.receiver_client import Receiver as _Receiver
from orderguard_guard.receiver_client import scrub


def _rc(handler, **kw):
    kw.setdefault("sleep", lambda s: None)
    return _Receiver("http://127.0.0.1:9", client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def test_a_timeout_is_retried_with_the_same_client_order_id_and_lands_once():
    ids, calls = [], []

    def h(req):
        body = _json.loads(req.content)
        calls.append(body["clientOrderId"])
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow")          # the first reply is lost; the receiver may have committed
        return httpx.Response(200, json={"decision": "filled", "orderId": "o1", "replay": True, "ledgerEffect": False})
    r = ReceiverPaperBroker(_rc(h)).submit(ORDER, "idem-7")
    assert isinstance(r, Fill) and r.replay and calls == ["idem-7", "idem-7"]


def test_retry_gives_up_after_the_budget_and_reports_an_unknown_outcome_actionably():
    n = []
    rc = _rc(lambda req: (n.append(1), (_ for _ in ()).throw(httpx.ReadTimeout("slow")))[1], retries=2)
    with pytest.raises(ReceiverError) as e:
        rc.propose("AAPL", "buy", 1, 1.0, "k")
    assert len(n) == 3 and e.value.outcome_unknown and e.value.transient
    assert "same client order id" in str(e.value)
    res = ReceiverPaperBroker(_rc(lambda req: httpx.Response(503), retries=0)).submit(ORDER, "k")
    assert isinstance(res, Reject) and res.transient and "nothing was placed" in res.reason


def test_activate_policy_is_never_retried():
    n = []
    rc = _rc(lambda req: (n.append(1), httpx.Response(502))[1])
    with pytest.raises(ReceiverError):
        rc.activate_policy({"payload": "x", "signature": "y"})
    assert len(n) == 1


def test_a_transient_failure_is_not_remembered_so_the_same_key_can_succeed_later():
    state = {"up": False, "sent": 0}

    def h(req):
        state["sent"] += 1
        if not state["up"]:
            return httpx.Response(503)
        return httpx.Response(200, json={"decision": "filled", "orderId": "o9"})
    router = OrderRouter(ReceiverPaperBroker(_rc(h, retries=0)))
    first = router.route(ORDER, ALLOW, "same")
    assert isinstance(first, Reject) and first.transient
    state["up"] = True
    second = router.route(ORDER, ALLOW, "same")
    assert isinstance(second, Fill) and not second.replay and second.order_id == "o9"
    third = router.route(ORDER, ALLOW, "same")
    assert third.replay and state["sent"] == 2            # now final, so remembered


def test_not_now_denials_are_transient_and_final_denials_are_remembered():
    assert {"anchor_unavailable", "mandate_changed"} <= TRANSIENT_REASONS
    for reason, transient in (("anchor_unavailable", True), ("limit_outside_band", False), ("daily_cap", False)):
        h = lambda req, reason=reason: httpx.Response(200, json={"decision": "denied", "reason": reason})     # noqa: E731
        res = ReceiverPaperBroker(_rc(h)).submit(ORDER, "k")
        assert isinstance(res, Reject) and res.transient is transient


def test_non_finite_and_non_mapping_orders_never_reach_the_receiver():
    sent = []
    broker = ReceiverPaperBroker(_rc(lambda req: (sent.append(1), httpx.Response(200, json={"decision": "filled", "orderId": "x"}))[1]))
    for bad in ({**ORDER, "limit_price": _math.nan}, {**ORDER, "limit_price": _math.inf}, {**ORDER, "symbol": 7}, None, [], "AAPL"):
        assert isinstance(broker.submit(bad, "k"), Reject)
        assert isinstance(OrderRouter(broker).route(bad, ALLOW, "k2"), Reject)
    with pytest.raises(ReceiverError):
        _rc(lambda req: httpx.Response(200, json={})).propose("AAPL", "buy", 1, _math.nan, "k")
    assert sent == []


def test_a_filled_reply_without_an_order_id_is_not_a_fill():
    for rep in ({"decision": "filled"}, {"decision": "filled", "orderId": ""}, {"decision": "filled", "orderId": 5}):
        res = ReceiverPaperBroker(_rc(lambda req, rep=rep: httpx.Response(200, json=rep))).submit(ORDER, "k")
        assert isinstance(res, Reject) and res.transient


def test_a_reply_that_is_not_a_decision_is_an_error_with_the_receivers_detail():
    rc = _rc(lambda req: httpx.Response(413, json={"error": "body_too_large", "detail": "Send only the order fields."}))
    with pytest.raises(ReceiverError, match="Send only the order fields"):
        rc.propose("AAPL", "buy", 1, 1.0, "k")
    with pytest.raises(ReceiverError):
        _rc(lambda req: httpx.Response(200, json=[1, 2])).health()


def test_different_keys_do_not_wait_for_a_slow_one():
    import threading
    gate, entered = threading.Event(), threading.Event()

    class Slow:
        def submit(self, order, key):
            if key == "slow":
                entered.set()
                gate.wait(5)
            return Fill(key, "AAPL", "buy", 1, 1.0, key)
        cancel = positions = cash = lambda self, *a: None
    router = OrderRouter(Slow())
    t = threading.Thread(target=lambda: router.route(ORDER, ALLOW, "slow"))
    t.start()
    assert entered.wait(5)
    assert isinstance(router.route(ORDER, ALLOW, "fast"), Fill)      # not blocked behind "slow"
    gate.set()
    t.join()


def test_error_text_never_carries_secrets_or_home_paths(monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setenv("SOME_API_KEY", "zz-verysecretvalue123")
    text = scrub(f"failed in {Path.home()}/proj/x.py token=abcdef Bearer abc.def and zz-verysecretvalue123")
    assert str(Path.home()) not in text and "verysecretvalue" not in text and "abcdef" not in text and "abc.def" not in text
    err = ReceiverError(f"bridge said bad thing at {Path.home()}/ledger.sqlite")
    assert str(Path.home()) not in str(err)
    for h in (lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")), lambda req: httpx.Response(500)):
        with pytest.raises(ReceiverError) as e:
            _rc(h, retries=0).health()
        assert "127.0.0.1" not in str(e.value)               # the receiver URL is not echoed


# ---- Binance testnet broker: pins and failure handling (mocked transport only; nothing is ever sent) ----
from orderguard_guard.brokers import BinanceTestnetBroker, TestnetRouter
from orderguard_guard.brokers.binance_testnet import NotRouted, WrongHost

_ENV = {"BINANCE_TESTNET_API_KEY": "k" * 12, "BINANCE_TESTNET_SECRET": "s" * 12}
_FILT = {"AAPLX": {}}


def _bn(transport, **kw):
    return BinanceTestnetBroker(env=_ENV, dry_run=False, transport=transport, filters={"BTCUSDT": {}}, **kw)


_BN_ORDER = {"symbol": "BTCUSDT", "side": "buy", "quantity": 1, "limit_price": 100.0}


def test_binance_is_pinned_dry_by_default_and_cannot_be_flipped_live():
    assert BinanceTestnetBroker(env=_ENV).dry_run is True
    b = BinanceTestnetBroker(env=_ENV)
    with pytest.raises(AttributeError):
        b.dry_run = False
    for url in ("https://api.binance.com", "http://testnet.binance.vision", "https://testnet.binance.vision.evil.test", "https://u:p@testnet.binance.vision",
                "https://testnet.binance.vision/api", "https://testnet.binance.vision:8443"):
        with pytest.raises(WrongHost):
            BinanceTestnetBroker(base_url=url, env=_ENV)


def test_binance_is_unreachable_except_through_its_router_after_an_allow():
    sent = []
    b = _bn(lambda req: (sent.append(req), (200, {"orderId": 1}))[1])
    with pytest.raises(NotRouted):
        b.submit(_BN_ORDER, "k")
    with pytest.raises(NotRouted):
        OrderRouter(b).route(_BN_ORDER, ALLOW, "k")             # a plain router does not arm it
    router = TestnetRouter(b)
    for decision in (None, {}, {"decision": "refuse"}, {"decision": "hold"}):
        assert isinstance(router.route(_BN_ORDER, decision, "k2"), Reject)
    assert sent == []
    with pytest.raises(NotRouted):                               # and the router disarms it afterwards
        b.submit(_BN_ORDER, "k3")


def test_binance_dry_run_sends_nothing_even_through_the_router():
    sent = []
    b = BinanceTestnetBroker(env=_ENV, transport=lambda req: (sent.append(req), (200, {}))[1], filters={"BTCUSDT": {}})
    r = TestnetRouter(b).route(_BN_ORDER, ALLOW, "k")
    assert isinstance(r, Reject) and "dry run" in r.reason and sent == []
    assert "***" in str(b.last_request["params"]["signature"]) and "k" * 12 not in str(b.last_request)


def test_binance_transport_failure_and_server_errors_are_transient_and_retryable_with_the_same_key():
    calls = []

    def transport(req):
        calls.append(req.params["newClientOrderId"])
        if len(calls) == 1:
            raise TimeoutError("slow")
        if len(calls) == 2:
            return 503, {}
        if len(calls) == 3:
            return 400, {"code": -1021}
        return 200, {"orderId": 77, "fills": []}
    router = TestnetRouter(_bn(transport))
    for _ in range(3):
        r = router.route(_BN_ORDER, ALLOW, "retry-me")
        assert isinstance(r, Reject) and r.transient and "same key" in r.reason
    ok = router.route(_BN_ORDER, ALLOW, "retry-me")
    assert isinstance(ok, Fill) and set(calls) == {"retry-me"}
    assert router.route(_BN_ORDER, ALLOW, "retry-me").replay and len(calls) == 4
    final = TestnetRouter(_bn(lambda req: (400, {"code": -2010}))).route(_BN_ORDER, ALLOW, "f")
    assert isinstance(final, Reject) and not final.transient


def test_binance_never_follows_the_environment_proxy_or_redirects(monkeypatch):
    import inspect
    from orderguard_guard.brokers import binance_testnet
    src = inspect.getsource(binance_testnet._httpx_transport)
    assert "trust_env=False" in src and "follow_redirects=False" in src
