"""Authoritative state: lifecycle, conservative projection, the hash-chained single-writer ledger, reconciliation and escrow."""
import itertools
import random
import threading

import pytest

from autonomy_helpers import LEDGER
from orderguard_autonomy import state as S
from orderguard_autonomy._crypto import key_from_label, public_b64

L = S.Lifecycle


def _reserve(led, oid, side, qty, sym="AAPL", agent="a", key=None):
    led.append({"kind": "reserve", "order": {"order_id": oid, "agent": agent, "contract_id": "c", "symbol": sym, "side": side,
                                             "quantity": qty, "limit_price": 100.0, "idempotency_key": key or oid},
                "reservation": {"reservation_id": "r-" + oid, "order_id": oid, "domain": "firm", "notional_usd": qty * 100,
                                "risk_units": 1.0}})


def test_lifecycle_rejects_illegal_transitions_and_overfills():
    led = S.ReservationLedger()
    _reserve(led, "o1", "buy", 10)
    with pytest.raises(S.InvalidTransition):
        led.transition("o1", L.ACKNOWLEDGED)                       # must be submitted first
    led.transition("o1", L.SUBMITTED)
    led.transition("o1", L.UNCERTAIN)
    led.transition("o1", L.PARTIALLY_FILLED, 4)
    with pytest.raises(S.InvalidTransition):
        led.transition("o1", L.PARTIALLY_FILLED, 3)                # fills never go backwards
    with pytest.raises(S.InvalidTransition):
        led.transition("o1", L.FILLED, 11)                         # never more than ordered
    led.transition("o1", L.FILLED, 10)
    with pytest.raises(S.InvalidTransition):
        led.transition("o1", L.CANCELED)
    assert led.state.positions["AAPL"] == 10
    with pytest.raises(S.InvalidTransition):
        _reserve(led, "o1", "buy", 1)                              # an order id is never reused


def test_the_ten_thousand_plus_three_agents_example():
    st = S.PortfolioState(positions={"NVDA": 100.0}, marks={"NVDA": 100.0})   # $10,000 held
    for i in range(3):
        st.working[f"o{i}"] = S.WorkingOrder(f"o{i}", f"agent{i}", "c", "NVDA", "buy", 50, 0, 100, L.SUBMITTED, f"k{i}")
    assert S.project(st, "NVDA", 0) * 100 == 25_000                 # what the account holds if all three fill


@pytest.mark.parametrize("seed", range(15))
def test_property_projection_bounds_are_exact_over_all_fill_subsets(seed):
    rng = random.Random(seed)
    st = S.PortfolioState(positions={"X": rng.uniform(-50, 50)})
    orders = []
    for i in range(rng.randint(0, 7)):
        o = S.WorkingOrder(f"o{i}", "a", "c", "X", rng.choice(["buy", "sell"]), rng.uniform(1, 30), 0, 1,
                           rng.choice([L.SUBMITTED, L.UNCERTAIN, L.ACKNOWLEDGED, L.FILLED, L.CANCELED]), f"k{i}")
        st.working[o.order_id] = o
        orders.append(o)
    add = rng.uniform(-20, 20)
    live = [o for o in orders if o.state in S.WORKING]
    deltas = [o.sign * o.remaining for o in live] + [add]           # the proposed order may or may not fill, like the rest
    outcomes = [st.positions["X"] + sum(sub) for r in range(len(deltas) + 1) for sub in itertools.combinations(deltas, r)]
    lo, hi = S.project_bounds(st, "X", add)
    assert lo == pytest.approx(min(outcomes))
    assert hi == pytest.approx(max(outcomes))
    assert abs(S.project(st, "X", add)) == pytest.approx(max(abs(lo), abs(hi)))


def test_replay_rebuilds_the_live_state_exactly():
    rng = random.Random(7)
    led = S.ReservationLedger(signing_key=LEDGER, checkpoint_every=5)
    led.set_marks({"AAPL": 100, "MSFT": 200}, 1.0)
    for i in range(60):
        oid = f"o{i}"
        _reserve(led, oid, rng.choice(["buy", "sell"]), rng.randint(1, 20), rng.choice(["AAPL", "MSFT"]))
        led.transition(oid, L.SUBMITTED)
        if rng.random() < 0.7:
            led.transition(oid, L.FILLED, led.state.working[oid].quantity)
        else:
            led.transition(oid, L.CANCELED)
        led.append({"kind": "release", "reservation_id": "r-" + oid})
    rebuilt = S.replay(led.store.entries)
    assert rebuilt.positions == led.state.positions
    assert rebuilt.working == led.state.working
    assert rebuilt.reservations == led.state.reservations == {}
    assert S.verify_log(led.store.entries, led.store.checkpoints, {public_b64(LEDGER)}) == []
    assert len(led.store.checkpoints) >= 10


def test_tampering_with_the_log_is_detected():
    led = S.ReservationLedger(signing_key=LEDGER, checkpoint_every=3)
    for i in range(9):
        _reserve(led, f"o{i}", "buy", 5)
    entries = [dict(e) for e in led.store.entries]
    trusted = {public_b64(LEDGER)}
    edited = [dict(e) for e in entries]
    edited[4] = {**edited[4], "event": {**edited[4]["event"], "order": {**edited[4]["event"]["order"], "quantity": 500}}}
    assert any("does not match its hash" in p for p in S.verify_log(edited, led.store.checkpoints, trusted))
    # rewrite history consistently from entry 4 on: hashes link, but the signed checkpoint no longer matches
    rewritten = entries[:3]
    for e in entries[3:]:
        ev = e["event"]
        prev = rewritten[-1]["hash"]
        seq = len(rewritten) + 1
        rewritten.append({"seq": seq, "prev": prev, "event": {**ev, "note": "x"}, "hash": S.entry_hash(seq, prev, {**ev, "note": "x"})})
    assert any("rewritten history" in p for p in S.verify_log(rewritten, led.store.checkpoints, trusted))
    forged = [{**c, "key": public_b64(key_from_label("mallory"))} for c in led.store.checkpoints]
    assert any("trusted key" in p for p in S.verify_log(entries, forged, trusted))
    assert any("link" in p for p in S.verify_log(entries[:2] + entries[3:], [], trusted))


def test_fencing_stops_a_deposed_writer():
    store = S.LogStore()
    old = S.ReservationLedger(store)
    old.set_marks({"AAPL": 1}, 0)
    new = S.ReservationLedger(store)                                # failover: the standby takes over and rebuilds from the log
    assert new.state.marks == {"AAPL": 1}
    with pytest.raises(S.StaleWriter):
        old.set_marks({"AAPL": 2}, 1)
    new.set_marks({"AAPL": 3}, 2)
    assert S.replay(store.entries).marks == {"AAPL": 3}


def test_reconcile_keeps_uncertain_orders_until_proven_and_adopts_broker_positions():
    led = S.ReservationLedger()
    for oid in ("o1", "o2", "o3"):
        _reserve(led, oid, "buy", 10, key="key-" + oid)
        led.transition(oid, L.SUBMITTED)
        led.transition(oid, L.UNCERTAIN)
    st = led.state
    # the broker's list is partial: o1 filled (found by idempotency key), o2 not mentioned, an unknown order appears
    broker = [{"idempotency_key": "key-o1", "status": "filled", "filled": 10}, {"order_id": "ghost", "status": "filled", "filled": 5}]
    out = S.reconcile(st, broker, {"AAPL": 15})
    assert out.working["o1"].state == L.FILLED
    assert out.working["o2"].state == L.UNCERTAIN and "r-o2" in out.reservations     # not proven: stays held
    assert out.positions["AAPL"] == 15 and out.discrepancies                          # broker is authoritative, difference logged
    evs = S.reconcile_events(st, broker, {"AAPL": 15})
    assert any(e.get("note") == "unknown_broker_order" for e in evs)
    # only a complete list as of after submission proves an order never arrived
    out2 = S.reconcile(st, [{"order_id": "o1", "status": "filled", "filled": 10}], None, complete=True)
    assert out2.working["o2"].state == L.REJECTED and "r-o2" not in out2.reservations
    assert st.working["o2"].state == L.UNCERTAIN                                         # reconcile is pure


def _tree(firm=1000.0, book_limit=800.0, agent_limit=500.0, agents=3):
    root = S.EscrowNode("firm", firm, 100.0)
    book = S.EscrowNode("book", 0, 0, root, limit_usd=book_limit, risk_limit=80.0)
    leaves = [S.EscrowNode(f"a{i}", 0, 0, book, limit_usd=agent_limit, risk_limit=50.0) for i in range(agents)]
    return root, book, leaves


def _wo(i):
    return S.WorkingOrder(f"o{i}", "a", "c", "X", "buy", 1, 0, 1, L.RISK_RESERVED, f"k{i}")


def test_escrow_child_never_holds_more_than_granted_and_asks_upward():
    root, book, (a, b, c) = _tree()
    ra = a.reserve(_wo(1), 400, 10)
    assert a.capacity_usd == 400 and book.capacity_usd == 400 and root.used_usd == 400
    with pytest.raises(S.EscrowExhausted):
        a.reserve(_wo(2), 200, 1)                                   # a's own signed limit is 500
    b.reserve(_wo(3), 400, 10)
    with pytest.raises(S.EscrowExhausted):
        c.reserve(_wo(4), 10, 1)                                    # the book's limit (800) is used up
    a.release(ra.reservation_id, 400, 10)
    assert a.free_usd == 400
    a.relinquish()                                                  # idle capacity goes back up for siblings
    c.reserve(_wo(5), 10, 1)
    assert root.check_invariants() == []


def test_property_escrow_invariants_hold_under_random_concurrent_operations():
    root, book, leaves = _tree(firm=10_000, book_limit=8_000, agent_limit=3_000, agents=6)
    errors = []

    def worker(node, seed):
        rng = random.Random(seed)
        held = []
        for i in range(400):
            r = rng.random()
            try:
                if r < 0.5:
                    held.append(node.reserve(_wo(f"{seed}-{i}"), rng.uniform(1, 400), rng.uniform(0, 5)))
                elif r < 0.75 and held:
                    res = held.pop(rng.randrange(len(held)))
                    node.release(res.reservation_id, res.notional_usd, res.risk_units)
                elif r < 0.9 and held:
                    res = held.pop(rng.randrange(len(held)))
                    node.settle(res.reservation_id, res.notional_usd * 0.5, res.risk_units * 0.5)
                else:
                    node.relinquish()
            except S.EscrowExhausted:
                pass
            except Exception as e:                                  # pragma: no cover - surfaced below
                errors.append(e)
    threads = [threading.Thread(target=worker, args=(n, i)) for i, n in enumerate(leaves)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert root.check_invariants() == []
    assert root.over_reserved() == []
    assert sum(n.capacity_usd for n in leaves) <= book.limit_usd + 1e-6
    assert book.capacity_usd <= root.capacity_usd + 1e-6


def test_rebase_returns_diversification_and_flags_upward_remeasure():
    root, book, (a, *_) = _tree()
    r = a.reserve(_wo(1), 300, 30)
    a.settle(r.reservation_id, 300, 30)
    a.rebase_filled(300, 18)                                        # Euler share smaller than the standalone reservation
    assert a.used_risk == pytest.approx(18) and a.free_risk == pytest.approx(12)
    a.rebase_filled(300, 45)                                        # volatility rose: over capacity, nothing new admitted
    assert a.path in root.over_reserved()
    with pytest.raises(S.EscrowExhausted):
        a.reserve(_wo(2), 1, 10)
