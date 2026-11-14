"""L3 risk bucket: a repeat or dependent claim of a quarantined item is always quarantined; unrelated items are not (fixed seeds, no model)."""
from __future__ import annotations

import random

from orderguard_guard.bucket import RiskBucket, entities_in, numbers_in

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "KO", "IBM", "ORCL"]
FAKE_ENTITIES = ["Vexor", "Quillon", "Zandria", "Brightmoor", "Halcyone", "Marrowby", "Tessaly", "Norvane", "Drummond", "Pelagia", "Kestrel", "Oberyn"]
SOURCES = [f"wire-{i}" for i in range(40)]


def distinct_number(rng, used=()):
    while True:
        n = rng.randint(1000, 9_999_999)
        if 1900 <= n <= 2100 or n in used:
            continue
        return n


def fmt(n):
    return (f"${n:,}", f"{n:,}", str(n))[n % 3]


def item(source, ticker, text, kind="feed", **kw):
    return {"source": source, "ticker": ticker, "text": text, "kind": kind, **kw}


def test_a_repeat_sharing_a_distinctive_number_is_always_quarantined():
    rng = random.Random(1)
    for _ in range(1000):
        b = RiskBucket()
        t = rng.choice(TICKERS)
        n = distinct_number(rng)
        b.add(item(rng.choice(SOURCES[:20]), t, f"reported takeover offer at {fmt(n)} per share"))
        again = item(rng.choice(SOURCES[20:]), t, f"sources confirm the {fmt(n)} bid is financed")
        r = b.related(again)
        assert r is not None and "shares the number" in r["match"], (again, r)
        ok, entry = b.admit(again)
        assert not ok and entry["related_to"] == 0 and entry["reason"].startswith("repeats a quarantined claim")


def test_a_dependent_claim_naming_the_same_entity_is_quarantined():
    rng = random.Random(2)
    for _ in range(1000):
        b = RiskBucket()
        t = rng.choice(TICKERS)
        ent = rng.choice(FAKE_ENTITIES)
        b.add(item(rng.choice(SOURCES[:20]), t, f"a consortium led by {ent} is preparing a buyout"))
        later = item(rng.choice(SOURCES[20:]), t, f"arbitrage desks are positioning ahead of {ent} news")
        assert entities_in(later["text"], t) & {ent}
        assert b.related(later) is not None


def test_the_same_source_is_quarantined_whatever_it_says_unless_it_was_a_document():
    rng = random.Random(3)
    for _ in range(1000):
        b = RiskBucket()
        src = rng.choice(SOURCES)
        b.add(item(src, rng.choice(TICKERS), "planted instruction", kind=rng.choice(["feed", "web", "tool"])))
        other = item(src, rng.choice(TICKERS), f"harmless note {rng.random():.3f}")
        assert b.related(other) is not None
        d = RiskBucket()
        d.add(item(src, "AAPL", "poisoned paragraph", kind="doc"))
        assert d.related(item(src, "MSFT", "an unrelated paragraph of the same filing")) is None


def test_unrelated_items_are_not_quarantined():
    rng = random.Random(4)
    for _ in range(2000):
        b = RiskBucket()
        t1, t2 = rng.sample(TICKERS, 2)
        n1 = distinct_number(rng)
        e1 = rng.choice(FAKE_ENTITIES)
        b.add(item(SOURCES[0], t1, f"rumour that {e1} will pay {fmt(n1)}"))
        n2 = distinct_number(rng, {n1})
        e2 = rng.choice([e for e in FAKE_ENTITIES if e != e1])
        different_ticker = item(rng.choice(SOURCES[1:]), t2, f"rumour that {e1} will pay {fmt(n1)}")      # the same words, but about another company
        same_ticker_nothing_shared = item(rng.choice(SOURCES[1:]), t1, f"report that {e2} will pay {fmt(n2)}")
        assert b.related(different_ticker) is None, different_ticker
        assert b.related(same_ticker_nothing_shared) is None, same_ticker_nothing_shared


def test_an_empty_bucket_relates_nothing_and_admits_everything():
    rng = random.Random(5)
    b = RiskBucket()
    for _ in range(500):
        it = item(rng.choice(SOURCES), rng.choice(TICKERS), f"claim {fmt(distinct_number(rng))}")
        assert b.related(it) is None and b.admit(it) == (True, None)
    assert len(b) == 0


def test_dependence_is_transitive_through_admit():
    rng = random.Random(6)
    for _ in range(500):
        b = RiskBucket()
        t = rng.choice(TICKERS)
        n1, n2 = distinct_number(rng), 0
        n2 = distinct_number(rng, {n1})
        b.add(item("s0", t, f"first claim {fmt(n1)}"))
        second = item("s1", t, f"second claim {fmt(n1)} and also {fmt(n2)}")          # repeats the first
        third = item("s2", t, f"third claim only mentions {fmt(n2)}")                  # repeats only the second
        assert b.admit(second)[0] is False
        ok, entry = b.admit(third)
        assert ok is False and entry["related_to"] == 1
        assert len(b) == 3


def test_quarantine_only_grows_and_keeps_provenance():
    rng = random.Random(7)
    b = RiskBucket()
    last = 0
    for i in range(300):
        b.admit(item(rng.choice(SOURCES), rng.choice(TICKERS), f"x {fmt(distinct_number(rng))}")) if rng.random() < 0.5 else b.add(
            item(rng.choice(SOURCES), rng.choice(TICKERS), "y"), reason="because")
        assert len(b) >= last
        last = len(b)
    for k, e in enumerate(b.summary()):
        assert e["index"] == k and e["reason"] and e["time"] and "source" in e
        assert e["related_to"] is None or 0 <= e["related_to"] < k
    assert b.quarantined_sources() <= set(SOURCES)


def test_number_extraction_normalises_formatting_and_ignores_years_and_small_integers():
    rng = random.Random(8)
    for _ in range(1000):
        n = distinct_number(rng)
        assert str(n) in numbers_in(f"offer of {fmt(n)} a share"), n
    assert numbers_in("in 2024 there were 3 offers and 7 bids") == []
    assert "10-for-1" in numbers_in("a 10-for-1 split")


def test_filter_events_drops_quarantined_sources_and_flagged_events():
    rng = random.Random(9)
    for _ in range(300):
        b = RiskBucket()
        bad = set(rng.sample(SOURCES, 5))
        for s in bad:
            b.add(item(s, "AAPL", "bad"))
        events = [{"src": rng.choice(SOURCES), "quarantined": rng.random() < 0.2, "i": i} for i in range(30)]
        kept = b.filter_events(events)
        assert all(e["src"] not in bad and not e["quarantined"] for e in kept)
        assert len(kept) == len([e for e in events if e["src"] not in bad and not e["quarantined"]])


def test_a_failing_model_never_lets_an_unsure_item_become_a_false_quarantine():
    """With a model configured but down, an unsure item (same ticker, nothing shared) passes; code-decided relations still hold."""
    class Down:
        def chat(self, *a, **k):
            raise RuntimeError("down")
    rng = random.Random(10)
    for _ in range(100):
        b = RiskBucket(Down())
        t = rng.choice(TICKERS)
        b.add(item("s0", t, f"claim {fmt(distinct_number(rng))}"))
        assert b.related(item("s1", t, "a different thing entirely")) is None
        assert b.related(item("s0", "KO", "same source")) is not None


def test_same_value_different_spelling_still_matches():
    from orderguard_guard.bucket import RiskBucket, numbers_in
    assert numbers_in("a $400.00 bid") == numbers_in("bid of 400") == ["400"]
    b = RiskBucket()
    b.add({"source": "wire-a", "ticker": "AAPL", "text": "Takeover bid at $400.00 per share"})
    assert b.related({"source": "wire-b", "ticker": "AAPL", "text": "Bidder offers 400 a share"}) is not None
