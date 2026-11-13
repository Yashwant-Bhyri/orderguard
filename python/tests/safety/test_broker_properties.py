"""Broker and OrderRouter: nothing is routed without an explicit allow, duplicates are idempotent, an unavailable receiver fails closed."""
from __future__ import annotations

import json
import random
import threading

import httpx

from orderguard_guard.broker import Fill, OrderRouter, Reject, ReceiverPaperBroker, SimBroker
from orderguard_guard.receiver_client import LocalLedger, Receiver, ReceiverError


class Spy:
    """A broker that records every submit and fills it."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def submit(self, order, key):
        with self.lock:
            self.calls.append((order, key))
        return Fill(f"S-{len(self.calls)}", order["symbol"], order["side"], order["quantity"], float(order["limit_price"]), key)

    def cancel(self, order_id):
        return False

    def positions(self):
        return {}

    def cash(self):
        return 0.0


def order(rng, **kw):
    o = {"symbol": rng.choice(["AAPL", "MSFT"]), "side": rng.choice(["buy", "sell"]), "quantity": rng.randint(1, 50), "limit_price": round(rng.uniform(10, 500), 2)}
    o.update(kw)
    return o


NOT_ALLOW = [None, {}, {"decision": "refuse"}, {"decision": "hold"}, {"decision": "ALLOW"}, {"decision": "allow "}, {"decision": True}, {"decision": ["allow"]},
             {"decision": None, "reasons": ["x"]}, "allow", ["allow"], 1, {"Decision": "allow"}, {"decision": "refuse", "checks": {"decision": "allow"}},
             {"decision": "hold", "reasons": []}]


def test_the_router_routes_only_an_explicit_allow():
    rng = random.Random(1)
    for i in range(1500):
        spy = Spy()
        router = OrderRouter(spy)
        bad = rng.choice(NOT_ALLOW)
        r = router.route(order(rng), bad, f"k{i}")
        assert isinstance(r, Reject) and spy.calls == [] and r.held == (isinstance(bad, dict) and bad.get("decision") == "hold")
        good = router.route(order(rng), {"decision": "allow", "reasons": []}, f"g{i}")
        assert isinstance(good, Fill) and len(spy.calls) == 1


def test_no_idempotency_key_means_no_routing():
    rng = random.Random(2)
    for key in ("", None):
        spy = Spy()
        assert isinstance(OrderRouter(spy).route(order(rng), {"decision": "allow"}, key), Reject) and spy.calls == []


def test_duplicate_keys_reach_the_broker_once_and_a_changed_order_never_does():
    rng = random.Random(3)
    for _ in range(300):
        spy = Spy()
        router = OrderRouter(spy)
        keys = [f"k{i}" for i in range(rng.randint(1, 8))]
        first = {k: order(rng) for k in keys}
        results = {}
        for k in rng.sample(keys, rng.randint(1, len(keys))):           # a subset of keys is used for real first
            r = router.route(first[k], {"decision": "allow"}, k)
            assert isinstance(r, Fill) and not r.replay
            results[k] = r
        for _ in range(rng.randint(5, 40)):
            k = rng.choice(keys)
            if k not in results:
                continue
            same = rng.random() < 0.7
            o = first[k] if same else {**first[k], "quantity": first[k]["quantity"] + rng.randint(1, 9)}
            r = router.route(o, {"decision": "allow"}, k)
            if same:
                assert isinstance(r, Fill) and r.replay and r.order_id == results[k].order_id and r.quantity == results[k].quantity
            else:
                assert isinstance(r, Reject) and "different order" in r.reason
        assert len(spy.calls) == len(results) and len({c[1] for c in spy.calls}) == len(spy.calls)


def test_concurrent_duplicates_are_submitted_once():
    spy = Spy()
    router = OrderRouter(spy)
    o = {"symbol": "AAPL", "side": "buy", "quantity": 5, "limit_price": 222.7}
    out = []
    ts = [threading.Thread(target=lambda: out.append(router.route(o, {"decision": "allow"}, "same-key"))) for _ in range(32)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(spy.calls) == 1 and len(out) == 32 and sum(1 for r in out if not r.replay) == 1


def test_sim_broker_never_goes_negative_or_oversells():
    rng = random.Random(4)
    for seed in range(20):
        b = SimBroker(cash=rng.choice([1_000, 10_000, 100_000]))
        for i in range(150):
            o = order(rng, quantity=rng.choice([1, 5, 50, 500, 0, -3, 2.5, True]), limit_price=rng.choice([1.0, 50.0, 500.0, 0, -1, "x", True]))
            r = b.submit(o, f"k{rng.randint(0, 80)}")
            assert isinstance(r, (Fill, Reject))
            assert b.cash() >= -1e-6 and all(q >= 0 for q in b.positions().values())


def test_sim_broker_is_idempotent_and_conserves_value():
    rng = random.Random(5)
    b = SimBroker(cash=50_000)
    start, fills = b.cash(), {}
    for i in range(200):
        o = order(rng, side="buy", quantity=rng.randint(1, 5))
        k = f"k{i % 40}"
        r = b.submit(o, k)
        if isinstance(r, Fill) and not r.replay:
            fills[k] = r
    assert b.cash() == start - sum(f.price * f.quantity for f in fills.values()) or abs(b.cash() - (start - sum(f.price * f.quantity for f in fills.values()))) < 1e-6
    assert sum(b.positions().values()) == sum(f.quantity for f in fills.values())


def test_router_over_a_receiver_that_is_down_fails_closed_and_places_nothing():
    rng = random.Random(6)
    handlers = {
        "unreachable": lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        "timeout": lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
        "http500": lambda req: httpx.Response(500, text="boom"),
        "http503": lambda req: httpx.Response(503, text=""),
        "not_json": lambda req: httpx.Response(200, text="<html>nope</html>"),
    }
    for name, h in handlers.items():
        for _ in range(100):
            receiver = Receiver("http://127.0.0.1:9", client=httpx.Client(transport=httpx.MockTransport(h)))
            broker = ReceiverPaperBroker(receiver, starting_cash=1000.0)
            router = OrderRouter(broker)
            r = router.route(order(rng), {"decision": "allow"}, f"k{rng.random()}")
            assert isinstance(r, Reject) and "nothing was placed" in r.reason, (name, r)
            assert broker.positions() == {} and broker.cash() == 1000.0


def test_receiver_paper_broker_maps_every_receiver_reply_closed():
    """Only decision == filled produces a Fill; anything else (denied, held, junk, missing fields) is a Reject."""
    rng = random.Random(7)
    replies = [{"decision": "denied", "reason": "limit_outside_band"}, {"decision": "held", "reason": "step_up"}, {}, {"decision": None}, {"decision": "FILLED"},
               {"decision": "filled "}, {"decision": ["filled"]}, {"error": "bad request"}, {"decision": "unlisted"}, {"decision": "revoked"}]
    for rep in replies:
        for _ in range(50):
            h = lambda req, rep=rep: httpx.Response(200, json=rep)       # noqa: E731
            b = ReceiverPaperBroker(Receiver("http://127.0.0.1:9", client=httpx.Client(transport=httpx.MockTransport(h))))
            r = b.submit(order(rng), f"k{rng.random()}")
            assert isinstance(r, Reject), rep
            assert r.held == (rep.get("decision") == "held")


def test_receiver_paper_broker_rejects_malformed_orders_before_any_request():
    rng = random.Random(8)
    sent = []
    h = lambda req: (sent.append(req), httpx.Response(200, json={"decision": "filled", "orderId": "x"}))[1]       # noqa: E731
    b = ReceiverPaperBroker(Receiver("http://127.0.0.1:9", client=httpx.Client(transport=httpx.MockTransport(h))))
    bad = [{"side": "hold"}, {"quantity": 0}, {"quantity": -1}, {"quantity": 1.0}, {"quantity": True}, {"quantity": "5"}, {"limit_price": 0}, {"limit_price": -2},
           {"limit_price": "x"}, {"limit_price": True}, {"symbol": ""}, {"symbol": None}]
    for patch in bad:
        r = b.submit(order(rng, **patch), "k")
        assert isinstance(r, Reject), patch
    assert sent == []


def test_the_request_the_broker_sends_is_exactly_the_order_and_its_key():
    seen = []

    def h(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"decision": "filled", "orderId": "R-1", "trustedPrice": 222.7})
    b = ReceiverPaperBroker(Receiver("http://127.0.0.1:9", client=httpx.Client(transport=httpx.MockTransport(h))))
    r = b.submit({"symbol": "AAPL", "side": "buy", "quantity": 3, "limit_price": 222.7}, "idem-1")
    assert isinstance(r, Fill) and seen == [{"symbol": "AAPL", "side": "buy", "quantity": 3, "limitPrice": 222.7, "clientOrderId": "idem-1"}]


def test_local_ledger_is_idempotent_on_client_order_id_and_honours_revoke():
    rng = random.Random(9)
    led = LocalLedger()
    ids = {}
    for i in range(200):
        k = f"c{rng.randint(0, 30)}"
        r = led.propose("AAPL", "buy", 1, 222.7, client_order_id=k)
        if k in ids:
            assert r["ledgerEffect"] is False and "duplicate" in r["reason"]
        else:
            ids[k] = r["orderId"]
            assert r["decision"] == "filled" and r["ledgerEffect"] is True
    assert len(led.snapshot()["orders"]) == len(ids)
    led.revoke()
    n = len(led.snapshot()["orders"])
    r = led.propose("AAPL", "buy", 1, 222.7, client_order_id="fresh")
    assert r["decision"] == "denied" and len(led.snapshot()["orders"]) == n


def test_receiver_errors_are_receiver_errors():
    for h in (lambda req: httpx.Response(500), lambda req: httpx.Response(200, text="x")):
        r = Receiver("http://127.0.0.1:9", client=httpx.Client(transport=httpx.MockTransport(h)))
        for call in (r.health, r.snapshot, r.revoke, lambda: r.propose("AAPL", "buy", 1, 1.0)):
            try:
                call()
            except ReceiverError:
                continue
            raise AssertionError("expected ReceiverError")
