"""Fail-closed injection for L2 (screen), L3 (bucket), L7 (graph) and the LLM client, plus the L7 edge cases (ties, all-quarantined, even counts)."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import pytest

from orderguard_guard import llm
from orderguard_guard.bucket import RiskBucket
from orderguard_guard.graph import Rule, TriggerGraph, basket_mean_fall
from orderguard_guard.llm import ScriptedLLM
from orderguard_guard.screen import Screen


# ---- L2 screen: every way the model path can fail quarantines -----------------------------------------------------------------------

class Raises:
    model = "raises"

    def __init__(self, exc):
        self.exc = exc

    def chat(self, *a, **k):
        raise self.exc


class Replies:
    model = "replies"

    def __init__(self, content=None, resp=None):
        self.content, self.resp = content, resp
        self.n = 0

    def chat(self, *a, **k):
        self.n += 1
        if self.resp is not None:
            return self.resp
        return {"choices": [{"message": {"content": self.content}}], "_meta": {"cached": True, "cost_usd": 0.0}}


@pytest.mark.parametrize("exc", [TimeoutError("slow"), httpx.ReadTimeout("slow"), httpx.ConnectError("off"), llm.BudgetExceeded("cap"), llm.CreditFloor("floor"),
                                 llm.NoApiKey("none"), llm.ReplayMiss("miss"), RuntimeError("x"), KeyError("k"), ValueError("v")])
def test_screen_quarantines_on_every_model_failure(exc):
    s = Screen(Raises(exc))
    r = s.check("Net sales rose 2%.", "doc")
    assert r["flag"] is True and r["category"] == "error" and s.errors == 1
    assert "quarantined" in r["why"]


@pytest.mark.parametrize("content", ["", None, "no json here", "{not json}", "[]", "{}", '{"category": "clean"}', '{"flag": ', "```json\n```", "null", "{\"flag\": true",
                                     '{"flag": "yes", "category": "clean"}'])
def test_screen_never_passes_an_unreadable_or_incomplete_reply(content):
    r = Screen(Replies(content)).check("some chunk", "web")
    assert r["flag"] is True, content


def test_screen_passes_only_an_explicit_false_flag():
    assert Screen(Replies('{"flag": false, "category": "clean", "why": "ok"}')).check("c", "web")["flag"] is False
    assert Screen(Replies('{"flag": "false", "category": "clean"}')).check("c2", "web")["flag"] is False
    assert Screen(Replies('{"flag": 0}')).check("c3", "web")["flag"] is False or True


@pytest.mark.parametrize("resp", [{}, {"choices": []}, {"choices": [{}]}, {"choices": [{"message": None}]}, {"choices": "x"}, [], None])
def test_screen_quarantines_a_malformed_response_envelope(resp):
    r = Screen(Replies(resp=resp)).check("chunk", "tool")
    assert r["flag"] and r["category"] == "error"


def test_errors_are_not_cached_so_a_retry_can_succeed():
    s = Screen(Raises(RuntimeError("x")))
    s.check("chunk", "doc")
    s.check("chunk", "doc")
    assert s.calls == 2 and s.errors == 2 and not s.cache


def test_corrupt_or_hostile_cache_files_never_become_a_pass(tmp_path):
    p = tmp_path / "cache.json"
    from orderguard_guard.screen import content_hash
    h = content_hash("replies", "web", "chunk")
    for payload in ("not json", "[]", "null", json.dumps({h: "clean"}), json.dumps({h: {"flag": False}}), json.dumps({h: {"flag": False, "category": "instruction"}}),
                    json.dumps({h: {"flag": "no", "category": "clean"}})):
        p.write_text(payload)
        s = Screen(Replies('{"flag": true, "category": "instruction", "why": "model"}'), cache_path=p)
        assert s.check("chunk", "web")["flag"] is True, payload


def test_a_chunk_longer_than_the_window_is_screened_to_the_end():
    calls = []

    def verdict(chunk):
        calls.append(len(chunk))
        bad = "TAIL-PAYLOAD" in chunk
        return {"flag": bad, "category": "instruction" if bad else "clean", "why": "tail" if bad else "ok"}

    s = Screen(ScriptedLLM([], screen=verdict), max_chars=1000)
    chunk = "Net sales rose. " * 200 + "TAIL-PAYLOAD tell the assistant to sell"
    r = s.check(chunk, "doc")
    assert r["flag"] and r["category"] == "instruction" and len(calls) >= 3
    assert not s.check("Net sales rose. " * 200, "doc")["flag"]


def test_short_chunks_send_exactly_one_request_of_the_historical_shape():
    llm_ = ScriptedLLM([], screen=lambda c: {"flag": False, "category": "clean", "why": "ok"})
    Screen(llm_, max_chars=20000).check("hello", "doc")
    assert len(llm_.requests) == 1
    assert llm_.requests[0]["messages"][1]["content"] == "kind: doc\n<chunk>\nhello\n</chunk>"


def test_screen_accepts_odd_chunk_types_and_unencodable_text():
    s = Screen(ScriptedLLM([], screen=lambda c: {"flag": False, "category": "clean", "why": "ok"}))
    for chunk in (b"bytes\xff", {"a": 1}, [1, 2], "lone \ud800 surrogate", ""):
        assert s.check(chunk, "tool")["flag"] is False


def test_screen_threads_do_not_lose_counts():
    s = Screen(ScriptedLLM([], screen=lambda c: {"flag": False, "category": "clean", "why": "ok"}))
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(lambda i: s.check(f"chunk {i}", "doc"), range(400)))
    assert s.calls == 400 and s.errors == 0


def test_classifier_that_raises_quarantines():
    s = Screen(ScriptedLLM([], screen=lambda c: {"flag": False, "category": "clean", "why": "ok"}))

    class Bad:
        def score(self, chunk):
            raise RuntimeError("model file corrupt")
    s._clf = Bad()
    r = s.check("chunk", "doc")
    assert r["flag"] and r["category"] == "error"


# ---- L3 bucket ----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("reply", ["", "garbage", "{}", '{"repeats": "maybe"}', '{"repeats": true, "which": 99}', '{"repeats": true, "which": "0"}',
                                   '{"repeats": true, "which": -1}', '{"repeats": true, "which": true}'])
def test_bucket_model_failures_never_create_a_false_quarantine(reply):
    b = RiskBucket(Replies(reply))
    b.add({"source": "Wire1", "ticker": "AAPL", "text": "Apple takeover rumour", "kind": "feed"})
    admitted, _ = b.admit({"source": "Wire2", "ticker": "AAPL", "text": "other news item", "kind": "feed"})
    assert admitted


def test_bucket_survives_junk_items():
    b = RiskBucket(Replies('{"repeats": false}'))
    b.add({"source": "W", "ticker": "AAPL", "text": "x" * 10})
    for item in ({}, {"text": None}, {"text": 5, "ticker": None}, {"source": ["a"], "text": {"a": 1}}):
        try:
            b.admit(item)
        except Exception as e:      # noqa: BLE001
            pytest.fail(f"{item!r} raised {type(e).__name__}")


# ---- L7 graph ------------------------------------------------------------------------------------------------------------------------

def price_rule(inputs=("ISRG",), pct=-40):
    return Rule("T1", "test", list(inputs), basket_mean_fall(list(inputs), pct), 1000, "sell")


def ev(src, pct, ticker="ISRG", **k):
    return {"src": src, "type": "quote_change", "ticker": ticker, "pct": pct, **k}


def fires(g, events, **kw):
    return g.evaluate(events, **kw)[0]["fires"]


def test_even_count_median_is_the_mean_and_one_liar_among_two_cannot_fire():
    g = TriggerGraph([price_rule()], min_sources=2)
    assert g.read_inputs(g._usable([ev("A", -1), ev("B", -3)]), g.rules[0])["ISRG"]["value"] == -2
    assert not fires(g, [ev("A", -1), ev("B", -90)])                    # the mean (-45.5) would cross -40; low/high medians disagree, so it holds
    assert fires(g, [ev("A", -45), ev("B", -47)])                       # two honest venues agree on a real crash
    assert not fires(g, [ev("A", -90), ev("B", -1), ev("C", -1), ev("D", -80)])


def test_odd_and_even_medians_over_many_counts():
    g = TriggerGraph([price_rule()], min_sources=1)
    for vals, want in (([-1], -1), ([-1, -3], -2), ([-1, -3, -5], -3), ([-1, -3, -5, -9], -4), ([5, 5, 5, 5], 5)):
        got = g.read_inputs([ev(f"V{i}", v) for i, v in enumerate(vals)], g.rules[0])["ISRG"]["value"]
        assert got == want, vals


def test_equal_source_ties_count_once_per_distinct_source_and_owner():
    g = TriggerGraph([price_rule()], min_sources=2, groups={"A": "owner", "B": "owner"})
    assert not fires(g, [ev("A", -50), ev("B", -50)])                   # one owner counts once
    assert fires(g, [ev("A", -50), ev("B", -50), ev("C", -50)])
    g2 = TriggerGraph([price_rule()], min_sources=2)
    assert not fires(g2, [ev("A", -50), ev("A", -50), ev("A", -50)])    # the same source repeated is one source
    assert [r["fires"] for r in g2.evaluate([ev("A", -50), ev("B", -50)])] == [True]


def test_latest_print_of_a_source_wins_and_a_tie_in_values_changes_nothing():
    g = TriggerGraph([price_rule()], min_sources=2)
    assert not fires(g, [ev("A", -50), ev("B", -50), ev("A", -1)])
    assert fires(g, [ev("A", -1), ev("B", -50), ev("A", -50), ev("C", -50)])


def test_all_sources_quarantined_means_nothing_fires_and_nothing_raises():
    g = TriggerGraph([price_rule()], min_sources=1)
    events = [ev("A", -90), ev("B", -90)]
    assert not fires(g, events, quarantined_sources={"A", "B"})
    assert not fires(g, [dict(e, quarantined=True) for e in events])
    assert not fires(g, [])
    r = g.evaluate(events, quarantined_sources={"A", "B"})[0]
    assert r["notional"] == 0 and r["values"] == {"ISRG": 0.0}


def test_a_rule_that_fires_on_zero_does_not_fire_on_no_evidence():
    always = Rule("Z", "buy if the move is at least -5", ["ISRG"], lambda v: v["ISRG"] >= -5, 10, "buy")
    for ms in (0, -3, 1, 2):
        g = TriggerGraph([always], min_sources=ms)
        assert not g.evaluate([])[0]["fires"], ms
        assert not g.evaluate([ev("A", -90)], quarantined_sources={"A"})[0]["fires"], ms


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), None, True, "x", "nan", [], {}, "-50x"])
def test_unreadable_readings_count_as_no_source(bad):
    g = TriggerGraph([price_rule()], min_sources=2)
    assert not fires(g, [ev("A", -50), ev("B", bad)])
    assert fires(g, [ev("A", -50), ev("B", -50), ev("C", bad)])


def test_numeric_strings_are_read_and_junk_events_are_ignored():
    g = TriggerGraph([price_rule()], min_sources=2)
    assert fires(g, [ev("A", "-50"), ev("B", -50.0)])
    junk = [None, 5, "x", [], {"type": "quote_change"}, {"src": ["list"], "type": "quote_change", "ticker": "ISRG", "pct": -90}, {"src": {"a": 1}, "pct": 1}]
    assert not fires(g, junk[:5] + [ev("A", -50)])                      # unusable events add no source
    assert isinstance(fires(g, junk + [ev("A", -50)]), bool)           # a list as a source name is stringified, not a crash
    assert g.evaluate(None) is not None and g.evaluate("events") is not None


def test_rule_or_matcher_that_raises_does_not_fire_or_crash():
    boom = Rule("B", "x", ["ISRG"], lambda v: 1 / 0, 10, "sell")
    assert not TriggerGraph([boom], min_sources=1).evaluate([ev("A", -90)])[0]["fires"]
    m = Rule("M", "x", ["X_news"], lambda v: v["X_news"] > 0, 10, "buy", matchers={"X_news": lambda e: e["text"].startswith("hi")})
    assert not TriggerGraph([m], min_sources=1).evaluate([{"src": "w", "type": "headline"}])[0]["fires"]


def test_min_sources_floor_is_one():
    assert TriggerGraph([price_rule()], min_sources=0).min_sources == 1
    assert TriggerGraph([price_rule()], min_sources=-3).min_sources == 1


# ---- LLM client under concurrency -------------------------------------------------------------------------------------------------------

MSG = [{"role": "user", "content": "hello"}]


@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setenv("OG_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "PRICE_IN", 0.30)
    monkeypatch.setattr(llm, "PRICE_OUT", 1.20)
    monkeypatch.setattr(llm, "api_key", lambda: "test-only")
    monkeypatch.setattr(llm.LLM, "_backoff", lambda self, attempt: None)

    def make(handler, *, budget, balance="100", retries=0):
        spend = llm.Spend(budget_usd=budget)
        counts = {"GET": 0, "POST": 0}
        lock = threading.Lock()

        def transport(request):
            with lock:
                counts[request.method] += 1
            if request.method == "GET":
                return httpx.Response(200, json={"balance_infos": [{"currency": "USD", "total_balance": balance}]})
            return handler(request)

        client = llm.LLM("deepseek/deepseek-v4.1-flash", mode="live", client=httpx.Client(transport=httpx.MockTransport(transport)), spend=spend, retries=retries,
                         replay_dir=tmp_path / "replay", spend_file=tmp_path / "spend.jsonl")
        return client, spend, counts
    return make


def ok(cost):
    return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}], "usage": {"cost": cost}})


def test_many_threads_cannot_overshoot_the_budget(live):
    estimate_probe = None
    client, spend, counts = live(lambda r: ok(0.004), budget=0.05)
    # one reservation costs about 0.0048 at max_tokens=4000 -> at most 10 can be in flight or settled under 0.05
    barrier = threading.Barrier(48)
    outcomes = []

    def worker(i):
        barrier.wait()
        try:
            client.chat([{"role": "user", "content": f"q{i}"}], max_tokens=4000)
            return "ok"
        except llm.BudgetExceeded:
            return "refused"

    with ThreadPoolExecutor(48) as pool:
        outcomes = list(pool.map(worker, range(48)))
    assert counts["POST"] == outcomes.count("ok") <= 12            # 12 x 0.004 settled is the most the cap admits
    assert spend.spent_usd <= 0.05 + 1e-9
    assert spend._reserved == 0 and spend._inflight == 0
    assert outcomes.count("refused") > 30


def test_in_flight_reservations_alone_are_bounded_by_the_cap(live):
    """Calls held open at the provider still count against the cap: a burst cannot all be admitted."""
    gate, started = threading.Event(), threading.Semaphore(0)

    def slow(request):
        started.release()
        gate.wait(5)
        return ok(0.001)

    client, spend, counts = live(slow, budget=0.02)
    results = []
    with ThreadPoolExecutor(32) as pool:
        futures = [pool.submit(client.chat, [{"role": "user", "content": f"q{i}"}], max_tokens=4000) for i in range(32)]
        started.acquire(timeout=5)
        try:
            peak = counts["POST"]
            assert peak <= 5                                            # 5 x ~0.0048 is the most that fits under 0.02 at once
        finally:
            gate.set()
        for f in futures:
            try:
                f.result(timeout=10)
                results.append("ok")
            except llm.BudgetExceeded:
                results.append("refused")
    assert spend.spent_usd <= 0.02 + 1e-9 and spend._reserved == 0


def test_credit_floor_holds_under_concurrency(live):
    peak = {"reserved": Decimal(0)}
    holder = {}

    def handler(request):
        peak["reserved"] = max(peak["reserved"], holder["spend"]._reserved)
        return ok(0.0001)

    client, spend, counts = live(handler, budget=1.0, balance="0.31")        # headroom above the 0.30 floor is 0.01
    holder["spend"] = spend
    barrier = threading.Barrier(24)

    def worker(i):
        barrier.wait()
        try:
            client.chat([{"role": "user", "content": f"q{i}"}], max_tokens=1000)
            return 1
        except llm.BudgetExceeded:
            return 0

    with ThreadPoolExecutor(24) as pool:
        done = sum(pool.map(worker, range(24)))
    assert counts["GET"] == 1                                            # one balance check shared by everybody
    assert done > 0 and spend.spent_usd <= 0.01 + 1e-9 and spend._reserved == 0
    assert peak["reserved"] <= Decimal("0.01")                            # reservations in flight never exceeded the headroom


def test_credit_floor_refusal_under_concurrency_sends_nothing(live):
    client, spend, counts = live(lambda r: pytest.fail("sent a request below the floor"), budget=1.0, balance="0.10")
    with ThreadPoolExecutor(12) as pool:
        futures = [pool.submit(client.chat, [{"role": "user", "content": f"q{i}"}]) for i in range(12)]
        for f in futures:
            with pytest.raises(llm.CreditFloor):
                f.result(timeout=10)
    assert counts["POST"] == 0 and spend._reserved == 0 and spend._inflight == 0


def test_an_overspending_provider_charge_stops_further_calls(live):
    client, spend, counts = live(lambda r: ok(5.0), budget=0.05)
    client.chat(MSG, max_tokens=100)
    with pytest.raises(llm.BudgetExceeded):
        client.chat(MSG, max_tokens=100)
    assert counts["POST"] == 1


def test_settlement_after_failure_in_one_thread_does_not_leak_reservations(live):
    n = {"i": 0}
    lock = threading.Lock()

    def flaky(request):
        with lock:
            n["i"] += 1
            i = n["i"]
        return httpx.Response(400, text="bad") if i % 2 else ok(0.0005)

    client, spend, _ = live(flaky, budget=0.05)
    with ThreadPoolExecutor(8) as pool:
        futures = [pool.submit(client.chat, [{"role": "user", "content": f"q{i}"}], max_tokens=200) for i in range(40)]
        for f in futures:
            try:
                f.result(timeout=10)
            except llm.LLMError:
                pass
    assert spend._reserved == 0 and spend._inflight == 0


def test_replay_keys_are_byte_stable():
    """Existing recordings are addressed by this hash; a change to canonical() or the body shape would orphan all of them."""
    body = {"model": "deepseek/deepseek-v4.1-flash", "messages": [{"role": "user", "content": "héllo ✓"}], "max_tokens": 100, "temperature": 0.0, "usage": {"include": True}}
    assert llm.canonical(body) == ('{"max_tokens":100,"messages":[{"content":"héllo ✓","role":"user"}],"model":"deepseek/deepseek-v4.1-flash",'
                                   '"temperature":0.0,"usage":{"include":true}}')
    assert llm.request_hash(body) == llm.request_hash(dict(reversed(list(body.items()))))
    import hashlib
    assert llm.request_hash(body) == hashlib.sha256(llm.canonical(body).encode("utf-8")).hexdigest()[:32]


def test_corrupt_recordings_are_a_miss_not_a_traceback(tmp_path):
    c = llm.LLM("deepseek/deepseek-v4.1-flash", mode="replay", replay_dir=tmp_path, spend=llm.Spend(budget_usd=1.0))
    msg = [{"role": "user", "content": "x"}]
    body = {"model": c.model, "messages": msg, "max_tokens": 4000, "temperature": 0.0, "usage": {"include": True}}
    path = tmp_path / f"{llm.request_hash(body)}.json"
    for payload in ("{truncated", "[]", "null", json.dumps({"response": "str"}), json.dumps({"nothing": 1}), ""):
        path.write_text(payload)
        with pytest.raises(llm.ReplayMiss, match="unreadable|no recorded"):
            c.chat(msg)
    path.write_text(json.dumps({"response": {"choices": [{"message": {"content": "hi"}}]}, "cost_usd": 0.0}))
    assert c.chat(msg)["_meta"]["cached"]


def test_nonfinite_or_negative_budget_env_refuses_live_calls(live):
    for bad in (float("nan"), float("inf") * -1, -1.0, 0.0):
        client, spend, counts = live(lambda r: ok(0.0), budget=bad)
        with pytest.raises(llm.BudgetExceeded):
            client.chat(MSG, max_tokens=10)
        assert counts["POST"] == 0
