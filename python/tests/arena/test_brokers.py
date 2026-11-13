"""Binance testnet broker: pinned host, HMAC signing, dry run, credentials by name, routed-only. Mocked transport only: nothing is ever sent."""
import hashlib
import hmac
from urllib.parse import urlencode

import pytest

from orderguard_guard.broker import Fill, Reject
from orderguard_guard.brokers import BinanceTestnetBroker, FutuSimBroker, NotConfigured, NotRouted, TESTNET_BASE_URL, TestnetRouter
from orderguard_guard.brokers.binance_testnet import SignedRequest, WrongHost, _check_url

FAKE_KEY, FAKE_SECRET = "test-key-not-real-aaaa", "test-secret-not-real-bbbb"
ENV = {"BINANCE_TESTNET_API_KEY": FAKE_KEY, "BINANCE_TESTNET_SECRET": FAKE_SECRET}
ORDER = {"symbol": "BTCUSDT", "side": "buy", "quantity": 3, "limit_price": 61.000126}
ALLOW = {"decision": "allow", "reasons": []}
FILTERS = {"BTCUSDT": {"stepSize": "0.00100000", "minQty": "0.00100000", "tickSize": "0.01000000", "minNotional": "5.00000000"}}


class Spy:
    def __init__(self, reply=(200, {"orderId": 77, "fills": [{"price": "61000.10", "qty": "0.003"}]})):
        self.reqs, self.reply = [], reply

    def __call__(self, req):
        self.reqs.append(req)
        return self.reply


def test_base_url_is_hard_pinned():
    assert BinanceTestnetBroker(base_url=TESTNET_BASE_URL + "/").base_url == "https://testnet.binance.vision"
    for bad in ("https://api.binance.com", "https://testnet.binance.vision.evil.example", "http://testnet.binance.vision", "https://user@testnet.binance.vision",
                "https://testnet.binance.vision:8443", "https://testnet.binance.vision/api", "https://TESTNET.binance.vision@api.binance.com"):
        with pytest.raises(WrongHost):
            BinanceTestnetBroker(base_url=bad)
    for bad in ("https://api.binance.com/api/v3/order", "http://testnet.binance.vision/api/v3/order", "https://testnet.binance.vision@evil.example/x"):
        with pytest.raises(WrongHost):
            _check_url(bad)
    _check_url("https://testnet.binance.vision/api/v3/order")


def test_request_is_signed_with_hmac_sha256_and_redacted():
    b = BinanceTestnetBroker(env=ENV, clock=lambda: 1_700_000_000.0, filters=FILTERS, unit_size={"BTCUSDT": 0.001})
    req = b.build_order_request(ORDER, "idem-1")
    p = dict(req.params)
    sig = p.pop("signature")
    assert sig == hmac.new(FAKE_SECRET.encode(), urlencode(p).encode(), hashlib.sha256).hexdigest()
    assert p["newClientOrderId"] == "idem-1" and p["symbol"] == "BTCUSDT" and p["side"] == "BUY" and p["timestamp"] == 1_700_000_000_000
    assert p["quantity"] == "0.003" and p["price"] == "61000.12"                      # unit size applied, floored to the lot and tick size
    red = str(req.redacted()) + repr(req) + str(req)
    assert FAKE_KEY not in red and FAKE_SECRET not in red and sig not in red and "***" in red


def test_filters_reject_quantities_below_minimum():
    b = BinanceTestnetBroker(env=ENV, filters=FILTERS, unit_size={"BTCUSDT": 0.0001})
    with pytest.raises(ValueError):
        b.build_order_request({**ORDER, "quantity": 1}, "k")                           # 0.0001 BTC < minQty 0.001


def test_dry_run_is_the_default_and_never_sends():
    spy = Spy()
    b = BinanceTestnetBroker(env=ENV, transport=spy, filters=FILTERS)
    assert b.dry_run is True
    r = TestnetRouter(b).route(ORDER, ALLOW, "idem-2")
    assert isinstance(r, Reject) and "not sent" in r.reason and spy.reqs == []
    assert b.last_request["sent"] is False and "***" in str(b.last_request) and FAKE_SECRET not in str(b.last_request)
    with pytest.raises(NotConfigured):
        b._send(b.build_order_request(ORDER, "idem-3"))                                # even a direct send is blocked in dry-run


def test_dry_run_works_without_credentials_and_says_so():
    b = BinanceTestnetBroker(env={}, filters=FILTERS)
    req = b.build_order_request(ORDER, "k")
    assert any("not signed" in n for n in req.notes) and req.params["signature"].startswith("unsigned")


def test_live_mode_needs_credentials_named_by_variable_only():
    b = BinanceTestnetBroker(env={}, dry_run=False, transport=Spy(), filters=FILTERS)
    r = TestnetRouter(b).route(ORDER, ALLOW, "k")
    assert isinstance(r, Reject) and "BINANCE_TESTNET_API_KEY" in r.reason and "BINANCE_TESTNET_SECRET" in r.reason


def test_only_reachable_through_the_router_after_an_allow():
    spy = Spy()
    b = BinanceTestnetBroker(env=ENV, dry_run=False, transport=spy, filters=FILTERS)
    with pytest.raises(NotRouted):
        b.submit(ORDER, "direct")
    router = TestnetRouter(b)
    for d in ({"decision": "refuse", "reasons": ["no"]}, {"decision": "hold", "reasons": ["human"]}, {}, None):
        assert isinstance(router.route(ORDER, d, f"k-{d}"), Reject)
    assert spy.reqs == []
    fill = router.route(ORDER, ALLOW, "ok-1")
    assert isinstance(fill, Fill) and fill.order_id == "77" and len(spy.reqs) == 1
    req = spy.reqs[0]
    assert req.url == "https://testnet.binance.vision/api/v3/order" and req.method == "POST" and req.headers["X-MBX-APIKEY"] == FAKE_KEY
    again = router.route(ORDER, ALLOW, "ok-1")                                         # idempotent: no second request
    assert again.replay and len(spy.reqs) == 1
    with pytest.raises(NotRouted):                                                     # the arming ended with the route
        b.submit(ORDER, "after")


def test_receiver_must_fill_first_when_configured():
    class Rcv:
        def __init__(self, decision):
            self.decision, self.calls = decision, 0

        def propose(self, *a, **k):
            self.calls += 1
            return {"decision": self.decision, "reason": "r"}

    spy = Spy()
    b = BinanceTestnetBroker(env=ENV, dry_run=False, transport=spy, filters=FILTERS)
    assert isinstance(TestnetRouter(b, Rcv("denied")).route(ORDER, ALLOW, "r1"), Reject) and spy.reqs == []
    assert isinstance(TestnetRouter(b, Rcv("filled")).route(ORDER, ALLOW, "r2"), Fill) and len(spy.reqs) == 1


def test_the_host_is_rechecked_at_send_time():
    spy = Spy()
    b = BinanceTestnetBroker(env=ENV, dry_run=False, transport=spy, filters=FILTERS)
    req = b.build_order_request(ORDER, "k")
    req.url = "https://api.binance.com/api/v3/order"                                   # something rewrote the URL after building
    with pytest.raises(WrongHost):
        b._send(req)
    assert spy.reqs == []


def test_exchange_rejection_and_filter_loading_via_mock():
    def transport(req):
        if req.method == "GET":
            return 200, {"symbols": [{"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"}, {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                                                  {"filterType": "NOTIONAL", "minNotional": "5"}]}]}
        return 400, {"code": -1013, "msg": "Filter failure"}

    b = BinanceTestnetBroker(env=ENV, dry_run=False, transport=transport)
    r = TestnetRouter(b).route({**ORDER, "quantity": 1}, ALLOW, "k")
    assert isinstance(r, Reject) and "-1013" in r.reason and b._filters["BTCUSDT"]["tickSize"] == "0.01"


def test_futu_sim_is_closed_without_sdk_and_gateway():
    with pytest.raises(NotConfigured):
        FutuSimBroker(trd_env="REAL")
    with pytest.raises(NotConfigured):
        FutuSimBroker(host="10.0.0.5")
    f = FutuSimBroker()
    with pytest.raises(NotRouted):
        f.submit(ORDER, "k")
    from orderguard_guard.brokers.binance_testnet import _ARMED
    tok = _ARMED.set(True)
    try:
        with pytest.raises(NotConfigured):
            f.submit(ORDER, "k")                                                       # SDK / OpenD absent: a clear error, nothing sent
    finally:
        _ARMED.reset(tok)
