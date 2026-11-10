from orderguard_guard.bucket import RiskBucket, numbers_in
from orderguard_guard.llm import ScriptedLLM


def test_numbers_in_ignores_years_and_small_integers():
    assert numbers_in("In 2024 revenue was $431,035 million, up 7.38% with 3 segments") == ["431035", "7.38%"]


def test_repeat_of_quarantined_claim_with_shared_number_and_ticker():
    b = RiskBucket()
    b.add({"source": "FlashWire", "ticker": "AAPL", "text": "Apple in talks to be taken private at $400 a share"}, reason="L2: false_data")
    hit = b.related({"source": "MarketPulse", "ticker": "AAPL", "text": "Consortium bid of $400/share for Apple said to be financed"})
    assert hit is not None and "400" in hit["match"] and hit["source"] == "FlashWire"


def test_repeats_are_quarantined_too_with_provenance():
    b = RiskBucket()
    b.add({"source": "FlashWire", "ticker": "AAPL", "text": "taken private at $400 a share"}, reason="L2: false_data", related_to=None)
    ok, entry = b.admit({"source": "StreetTicker", "ticker": "AAPL", "text": "Arbitrage desks pile in on reported $400 buyout bid"})
    assert ok is False and entry["related_to"] == 0 and entry["source"] == "StreetTicker" and "repeats" in entry["reason"] and entry["time"]
    # and the repeat now anchors a further repeat
    assert b.related({"source": "X", "ticker": "AAPL", "text": "$400 bid confirmed"}) is not None


def test_unrelated_item_passes():
    b = RiskBucket()
    b.add({"source": "FlashWire", "ticker": "AAPL", "text": "taken private at $400 a share"})
    assert b.related({"source": "MarketWire", "ticker": "AAPL", "text": "Apple shares little changed in early trade"}) is None
    assert b.related({"source": "MarketWire", "ticker": "MSFT", "text": "Microsoft raises $400 million for data centres"}) is None


def test_same_source_is_related():
    b = RiskBucket()
    b.add({"source": "ExchangeNotices", "ticker": "MSFT", "text": "liquidate before 10:00", "kind": "feed"})
    hit = b.related({"source": "ExchangeNotices", "ticker": "ISRG", "text": "a different notice", "kind": "feed"})
    assert hit and "same source" in hit["match"]


def test_model_is_asked_only_when_code_is_unsure():
    llm = ScriptedLLM(['{"repeats": true, "which": 0, "why": "same buyout story"}'])
    b = RiskBucket(llm)
    b.add({"source": "A", "ticker": "AAPL", "text": "Apple being acquired in a stunning bid", "kind": "feed"})
    # code is sure (shared number): no model call
    b2 = RiskBucket(ScriptedLLM([]))
    b2.add({"source": "A", "ticker": "AAPL", "text": "bid at $400"})
    b2.related({"source": "B", "ticker": "AAPL", "text": "$400 again"})
    assert b2.model_calls == 0
    # same ticker, nothing concrete shared: the model decides
    hit = b.related({"source": "B", "ticker": "AAPL", "text": "suitors circle the iPhone maker", "kind": "feed"})
    assert b.model_calls == 1 and hit and "model judged" in hit["match"]


def test_model_failure_lets_item_through():
    class Boom:
        def chat(self, *a, **k):
            raise RuntimeError("x")
    b = RiskBucket(Boom())
    b.add({"source": "A", "ticker": "AAPL", "text": "something odd", "kind": "feed"})
    assert b.related({"source": "B", "ticker": "AAPL", "text": "unrelated words", "kind": "feed"}) is None


def test_filter_events_drops_quarantined_sources():
    b = RiskBucket()
    b.add({"source": "VenueC", "ticker": "ISRG", "text": "crash"})
    evs = [{"src": "VenueA"}, {"src": "VenueC"}, {"src": "VenueB", "quarantined": True}]
    assert b.filter_events(evs) == [{"src": "VenueA"}]
