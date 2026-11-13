"""Authority: parity with the real OrderGate, idempotency, L7, step-up, revocation, shared budget under threads, L8 sampling."""
import random
import threading

from orderguard_arena.authority import Authority, SnapshotMarket
from orderguard_arena.envelopes import DailyBudget, EnvelopeBook, default_envelopes, make_envelope, owner_key_from_seed
from orderguard_arena.feeds import DEFAULT_SYMBOLS
from orderguard_guard.gate import OrderGate

PRICES = {"AAPL": 200.0, "MSFT": 400.0, "JNJ": 150.0}


def tiny_book(per_order=1000.0, daily=3000.0, band=1.0, step_up=None, symbols=("AAPL", "MSFT"), name="one"):
    key = owner_key_from_seed("test")
    book = EnvelopeBook(key.public_key())
    book.add(make_envelope(key, name=name, symbols=symbols, per_order=per_order, daily=daily, band_pct=band, step_up=step_up))
    return book, key


def _auth(book, **kw):
    a = Authority(book, steps_per_day=100, **kw)
    a.set_prices(dict(PRICES))
    return a


def test_fast_path_agrees_with_the_real_order_gate_on_random_orders():
    rng = random.Random(1)
    book, _ = tiny_book(per_order=5000, daily=90000, band=1.5, step_up=3500, symbols=("AAPL", "MSFT", "JNJ"))
    env = book.envelopes()[0]
    fast = _auth(book)
    gate_book, _ = tiny_book(per_order=5000, daily=90000, band=1.5, step_up=3500, symbols=("AAPL", "MSFT", "JNJ"))
    strict = _auth(gate_book, strict=True)
    tickers = ["AAPL"] * 6 + ["MSFT"] * 6 + ["JNJ"] * 4 + ["QNTX", "aapl", " MSFT ", "АAPL", "", None, "TSLA"]
    n_diff = 0
    for i in range(3000):
        t = rng.choice(tickers)
        px = PRICES.get(str(t).strip().upper(), 100.0)
        limit = rng.choice([px * (1 + rng.uniform(-0.03, 0.03))] * 8 + [None, 0, -1, "oops"])
        o = {"ticker": t, "side": rng.choice(["buy"] * 6 + ["sell"] * 6 + ["BUY", "short", ""]),
             "quantity": rng.choice([1, 2, 3, 5, 8, 10, 12, 17, 25, 40, 0, -3, 2.5, "7", None]), "limit_price": limit}
        step = rng.randrange(0, 300)
        a = fast.authorize(o, key=f"k{i}", step=step, envelope=env)
        b = strict.authorize(o, key=f"k{i}", step=step, envelope=gate_book.envelopes()[0])
        assert a.decision == b.decision, (o, a, b)
        n_diff += a.decision != "refuse"
    assert n_diff > 100                                                     # the sample is not all refusals
    # and one direct OrderGate call, to pin that "strict" really is OrderGate
    g = OrderGate(env.m, SnapshotMarket(PRICES))
    assert g.evaluate({"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 200.0}, {"as_of": "2026-01-05"})["decision"] == "allow"


def test_money_movement_and_lookalike_tickers_are_refused():
    book, _ = tiny_book()
    a = _auth(book)
    assert a.authorize({"type": "transfer", "destination_account": "ACC-1", "amount_usd": 5}, key="t", step=0).layer == "money"
    d = a.authorize({"ticker": "АAPL", "side": "buy", "quantity": 1, "limit_price": 200.0}, key="h")
    assert d.decision == "refuse" and "non-Latin" in d.reasons[0]


def test_sizing_uses_the_trusted_price_not_the_agents_limit_price():
    book, _ = tiny_book(per_order=10000, daily=100000, band=50)
    a = _auth(book)
    # 440 shares "at $22.30" is $9,812 at its own limit but $88,000 at the trusted $200
    d = a.authorize({"ticker": "AAPL", "side": "buy", "quantity": 440, "limit_price": 22.30}, key="f2")
    assert d.decision == "refuse" and d.notional == 88000.0 and "per-order cap" in d.reasons[0]


def test_idempotency_replays_and_rejects_key_reuse():
    book, _ = tiny_book(per_order=1000, daily=1000, band=5)
    a = _auth(book)
    o = {"ticker": "AAPL", "side": "buy", "quantity": 4, "limit_price": 200.0}
    d1, d2 = a.authorize(o, key="x", step=0), a.authorize(dict(o), key="x", step=0)
    assert d1.decision == "allow" and d2.decision == "allow" and d2.replay and not d1.replay
    assert book.envelopes()[0].budget.used(0) == 800.0                       # the duplicate consumed nothing
    d3 = a.authorize({**o, "quantity": 1}, key="x", step=0)
    assert d3.decision == "refuse" and d3.layer == "idempotency"


def test_step_up_hold_then_human_approval_reserves_budget():
    book, _ = tiny_book(per_order=5000, daily=6000, band=5, step_up=1000)
    a = _auth(book)
    d = a.authorize({"ticker": "AAPL", "side": "buy", "quantity": 10, "limit_price": 200.0}, key="big", step=0)
    assert d.decision == "hold" and book.envelopes()[0].budget.used(0) == 2000.0 and "big" in a.pending     # a hold reserves, as in the receiver
    assert a.approve("big", step=0).decision == "allow" and book.envelopes()[0].budget.used(0) == 2000.0    # approval reserves nothing more


def test_daily_cap_is_per_day_and_resets_at_the_day_boundary():
    book, _ = tiny_book(per_order=1000, daily=1000, band=5)
    a = _auth(book)
    o = {"ticker": "AAPL", "side": "buy", "quantity": 5, "limit_price": 200.0}
    assert a.authorize(o, key="1", step=10).decision == "allow"
    assert a.authorize(o, key="2", step=20).decision == "refuse"
    assert a.authorize(o, key="3", step=110).decision == "allow"              # next day (100 steps per day)


def test_l7_holds_an_unconfirmed_rule_trigger_and_lets_a_confirmed_one_through():
    book, _ = tiny_book(per_order=5000, daily=50000, band=5)
    a = _auth(book)
    o = {"ticker": "AAPL", "side": "buy", "quantity": 5, "limit_price": 200.0}
    # one origin repeated by three wires counts as ONE source
    a.news["N1"] = [{"src": w, "type": "headline", "ticker": "AAPL", "origin": "RumourMill", "news_id": "N1", "text": "x"} for w in ("W1", "W2", "W3")]
    a.news["N2"] = [{"src": w, "type": "headline", "ticker": "AAPL", "origin": w, "news_id": "N2", "text": "x"} for w in ("W1", "W2", "W3")]
    d1 = a.authorize(o, key="a", trigger={"rule": "news", "news_id": "N1"}, step=0)
    d2 = a.authorize(o, key="b", trigger={"rule": "news", "news_id": "N2"}, step=0)
    d3 = a.authorize(o, key="c", trigger={"rule": "news", "news_id": "missing"}, step=0)
    assert (d1.decision, d1.layer) == ("hold", "L7") and d2.decision == "allow" and d3.decision == "hold"


def test_revocation_refuses_everything_afterwards():
    book, _ = tiny_book()
    a = _auth(book)
    o = {"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 200.0}
    assert a.authorize(o, key="1").decision == "allow"
    a.revoke("one")
    d = a.authorize(o, key="2")
    assert d.decision == "refuse" and "revoked" in d.reasons[0]


def test_daily_budget_is_atomic_under_threads():
    b = DailyBudget(10_000.0)
    got = []

    def work():
        n = 0
        for _ in range(2000):
            n += b.reserve(0, 7.0)
        got.append(n)

    ts = [threading.Thread(target=work) for _ in range(16)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(got) * 7.0 == b.used(0) <= 10_000.0 and sum(got) == int(10_000 // 7)       # exactly floor(cap/7) reservations, never one more


def test_concurrent_agents_share_one_envelope_budget_through_the_authority():
    book, _ = tiny_book(per_order=1000, daily=50_000, band=5)
    a = _auth(book)
    out = []

    def agent(i):
        for j in range(400):
            d = a.authorize({"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 200.0}, key=f"{i}-{j}", step=0, agent=i)
            out.append(d.decision)

    ts = [threading.Thread(target=agent, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out.count("allow") == 250 and book.envelopes()[0].budget.used(0) == 50_000.0     # 12 x 400 attempts, exactly cap/200 allowed


def test_concurrent_duplicate_key_reserves_once():
    book, _ = tiny_book(per_order=1000, daily=50_000, band=5)
    a = _auth(book)
    res = []
    ts = [threading.Thread(target=lambda: res.append(a.authorize({"ticker": "AAPL", "side": "buy", "quantity": 2, "limit_price": 200.0}, key="same", step=0))) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert book.envelopes()[0].budget.used(0) == 400.0 and sum(not d.replay for d in res) == 1


def test_batch_matches_single_calls():
    book1, _ = tiny_book(per_order=1000, daily=3000, band=2)
    book2, _ = tiny_book(per_order=1000, daily=3000, band=2)
    a1, a2 = _auth(book1), _auth(book2)
    orders = [{"ticker": "AAPL", "side": "buy", "quantity": q, "limit_price": 200.0} for q in (1, 2, 3, 9, 4, 2)]
    batch = a1.authorize_batch([(o, f"k{i}", None, None, None, 0) for i, o in enumerate(orders)])
    single = [a2.authorize(o, key=f"k{i}", step=0) for i, o in enumerate(orders)]
    assert [d.decision for d in batch] == [d.decision for d in single]
    assert a1.latency_us()["p99"] >= a1.latency_us()["p50"] > 0


def test_l8_passthrough_counts_agreement_with_the_receiver():
    class FakeReceiver:
        def __init__(self):
            self.calls = []

        def propose(self, symbol, side, quantity, limit_price, client_order_id=None):
            self.calls.append(client_order_id)
            return {"decision": "filled" if quantity <= 5 else "denied", "reason": "x"}

    book, _ = tiny_book(per_order=5000, daily=50000, band=5)
    rcv = FakeReceiver()
    a = _auth(book, receiver=rcv, receiver_sample=1.0)
    for i, q in enumerate((1, 3, 8, 12)):
        a.authorize({"ticker": "AAPL", "side": "buy", "quantity": q, "limit_price": 200.0}, key=f"k{i}", step=0)
    assert a.l8["sampled"] == 4 and a.l8["agree"] == 2 and a.l8["disagree"] == 2 and len(rcv.calls) == 4
    b = _auth(tiny_book()[0], receiver=rcv, receiver_sample=0.0)
    b.authorize({"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 200.0}, key="z")
    assert b.l8["sampled"] == 0


def test_default_book_is_signed_and_sleeves_cover_symbols():
    book = default_envelopes(DEFAULT_SYMBOLS, 1000)
    assert {e.name for e in book.envelopes()} == {"core", "tactical", "crypto"} and all(e.m.signature for e in book.envelopes())
    assert book.home_for("AAPL").name == "core" and book.home_for("NVDA").name == "tactical" and book.home_for("BTC-USD").name == "crypto"


class ReceiverModel:
    """Pure-Python model of receiver/core/receiver-core.ts accounting (integer cents): band, per-order cap, step-up, then at commit the
    idempotency check and the daily cap over filled AND held orders. No ports, no node."""

    def __init__(self, prices, per_order, daily, band_pct, step_up, symbols):
        self.p, self.po, self.day, self.band, self.su, self.sym = prices, round(per_order * 100), round(daily * 100), band_pct, round(step_up * 100), set(symbols)
        self.used, self.seen = 0, {}

    def propose(self, sym, side, qty, limit, cid):
        if sym not in self.sym or side not in ("buy", "sell"):
            return "denied"
        t = self.p[sym]
        if abs(limit - t) / t * 100 > self.band + 1e-9:
            return "denied"
        cents = round(qty * t * 100)
        if cents > self.po:
            return "denied"
        if cid in self.seen:
            return self.seen[cid]
        if self.used + cents > self.day:
            return "denied"
        self.used += cents                                   # filled and held both count
        self.seen[cid] = "held" if cents > self.su else "filled"
        return self.seen[cid]


def test_holds_count_against_the_daily_budget_like_the_receiver():
    """The disagreement the real-L8 check found: the arena did not count held orders, the receiver does, so the arena allowed orders the receiver refused for daily_cap."""
    book, _ = tiny_book(per_order=5000, daily=10000, band=5, step_up=3000, symbols=("AAPL",))
    a = _auth(book)
    seq = [(20, None), (20, None), (20, None)]
    got = []
    for i, (q, _) in enumerate(seq):
        d = a.authorize({"ticker": "AAPL", "side": "buy", "quantity": q, "limit_price": 200.0}, key=f"k{i}", step=0)
        got.append({"hold": "held", "allow": "filled", "refuse": "denied"}[d.decision])
    # $4,000 > $3,000 step-up, so the first two are held and both count; the third would make $12,000 > $10,000 and is denied
    assert got == ["held", "held", "denied"] and book.envelopes()[0].budget.used(0) == 8000.0


def test_arena_accounting_matches_the_receiver_model_on_random_orders():
    rng = random.Random(5)
    syms = ("AAPL", "MSFT", "JNJ")
    for per_order, daily, step_up in ((6000, 120_000, 4000), (25_000, 400_000, 20_000), (3000, 30_000, 2500)):
        book, _ = tiny_book(per_order=per_order, daily=daily, band=1.0, step_up=step_up, symbols=syms)
        a = _auth(book)
        model = ReceiverModel(PRICES, per_order, daily, 1.0, step_up, syms)
        used_keys = {}
        for i in range(2500):
            t = rng.choice(syms)
            q = rng.choice([1, 2, 5, 9, 14, 20, 30, 45, 80, 120])
            lim = PRICES[t] * (1 + rng.choice([0, 0.002, -0.004, 0.009, 0.02]))
            key = f"k{rng.randrange(1800)}"                         # some repeated keys; a repeat of an identical order is a replay
            order = {"ticker": t, "side": "buy", "quantity": q, "limit_price": lim}
            if used_keys.setdefault(key, order) != order:
                continue                                             # skip key reuse with a different order (the receiver reports a conflict)
            d = a.authorize(order, key=key, step=0, agent=i % 9)
            theirs = model.propose(t, "buy", q, lim, key)
            ours = {"allow": "filled", "hold": "held", "refuse": "denied"}[d.decision]
            assert ours == theirs, (i, order, d, theirs)
        assert book.envelopes()[0].budget.used(0) * 100 == model.used
