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
