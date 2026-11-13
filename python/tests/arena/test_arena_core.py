"""Determinism, the colluding and compromised guarantees, feeds, the oracle metrics, LLM agent wrapper."""
import json

from orderguard_arena.agents import Agent, Ctx, LLMAgent, PopulationConfig, homoglyph, make_population, wrap_llm
from orderguard_arena.arena import ArenaConfig, run_arena
from orderguard_arena.envelopes import split_sleeves
from orderguard_arena.feeds import BinancePublicFeed, DEFAULT_SYMBOLS, RecordedFeed, ReplayFeed, median_price


def _strip(s):
    s = json.loads(json.dumps(s))
    s.pop("timing", None)
    return s


def test_arena_is_deterministic_for_a_seed():
    a = run_arena(ArenaConfig(seed=3, agents=80, steps=200, steps_per_day=50))
    b = run_arena(ArenaConfig(seed=3, agents=80, steps=200, steps_per_day=50))
    c = run_arena(ArenaConfig(seed=4, agents=80, steps=200, steps_per_day=50))
    assert a.summary["digest"] == b.summary["digest"] and _strip(a.summary) == _strip(b.summary)
    assert a.events == b.events
    assert c.summary["digest"] != a.summary["digest"]


def test_replay_feed_is_deterministic_and_median_resists_one_liar():
    f1, f2 = list(ReplayFeed(5, steps=60)), list(ReplayFeed(5, steps=60))
    assert [s.quotes for s in f1] == [s.quotes for s in f2]
    assert median_price({"A": 100.0, "B": 100.1, "C": 160.0}) == 100.1       # one venue lying +60% does not move the median
    lied = [s for s in ReplayFeed(5, steps=400, lie_rate=0.05) for sym in s.meta["liars"]]
    assert lied, "the feed should contain lying venues at this rate"
    s = lied[0]
    sym = next(iter(s.meta["liars"]))
    trusted = s.trusted()[sym]
    prices = sorted(s.quotes[sym].values())
    assert abs(trusted - prices[1]) < 1e-9


def test_colluders_each_under_per_order_cap_cannot_exceed_daily_cap():
    rates = {k: 0.0 for k in ("fat_finger", "stale_price", "off_list", "homoglyph", "compromised", "runaway")} | {"colluding": 0.1}
    r = run_arena(ArenaConfig(seed=7, agents=100, steps=300, steps_per_day=100, rates=rates))
    cols = [e for e in r.events if e["label"] == "collusion"]
    assert cols
    book_envs = {e.name: e for e in r.authority.book.envelopes()}
    tried = sum(e["risk"] for e in cols)
    allowed = sum(e["risk"] for e in cols if e["d"] == "allow")
    assert max(e["risk"] for e in cols) <= max(x.max_order for x in book_envs.values())      # every single order is under its cap
    # the arena ran 3 days; each envelope's shared daily budget never exceeded its cap, whoever spent it
    for env in book_envs.values():
        for day, used in env.budget.total_by_day().items():
            assert used <= env.budget.cap + 1e-6, (env.name, day)
    # the colluders alone tried more than one envelope-day and were stopped by the cap
    assert tried > min(x.budget.cap for x in book_envs.values()) and any(e["d"] == "refuse" and e["code"] == "daily" for e in cols)
    assert allowed <= sum(env.budget.cap for env in book_envs.values()) * 3


def test_fair_share_limits_what_a_colluding_group_can_drain():
    rates = {k: 0.0 for k in ("fat_finger", "stale_price", "off_list", "homoglyph", "compromised", "runaway")} | {"colluding": 0.1}
    base = run_arena(ArenaConfig(seed=7, agents=100, steps=300, steps_per_day=100, rates=rates))
    fair = run_arena(ArenaConfig(seed=7, agents=100, steps=300, steps_per_day=100, rates=rates, agent_share=0.02))
    assert fair.summary["bad"]["leaked_usd"] < 0.5 * base.summary["bad"]["leaked_usd"]


def test_compromised_agents_never_get_a_transfer_or_an_off_list_fill():
    rates = {k: 0.0 for k in ("fat_finger", "stale_price", "runaway", "colluding")} | {"compromised": 0.3, "off_list": 0.1, "homoglyph": 0.1}
    r = run_arena(ArenaConfig(seed=11, agents=120, steps=400, steps_per_day=100, rates=rates, fail_prob=0.5))
    labels = {e["label"] for e in r.events}
    assert {"compromised_transfer", "compromised_unlisted", "off_list", "homoglyph"} <= labels
    allowed_syms = set()
    for env in r.authority.book.envelopes():
        allowed_syms |= env.allowed
    for e in r.events:
        if e["label"] in ("compromised_transfer", "compromised_unlisted", "off_list", "homoglyph"):
            assert e["d"] != "allow", e
        if e["d"] == "allow" and e["order"].get("ticker"):
            assert e["order"]["ticker"] in allowed_syms                       # nothing outside the envelopes' allow-lists was ever authorized
        assert not (e["d"] == "allow" and ("destination_account" in e["order"] or e["order"].get("type") == "transfer"))
    for a in r.agents:
        assert all(s in allowed_syms for s in a.pos)                          # and no off-list position exists after the fills


def test_oracle_metrics_are_consistent(small_run):
    s = small_run.summary
    assert s["decisions"]["allow"] + s["decisions"]["hold"] + s["decisions"]["refuse"] == s["proposals"]
    L, B = s["legit"], s["bad"]
    assert L["allowed"] + L["held"] + L["refused"] == L["proposals"]
    assert abs(B["blocked_usd"] + B["leaked_usd"] + B["duplicates_absorbed_usd"] - B["attack_notional_usd"]) < 1.0
    assert 0 <= L["false_refusal_rate"] <= 1 and B["leaked_usd"] <= B["attack_notional_usd"]
    assert s["by_label"]["legit"]["n"] == L["proposals"]
    assert small_run.summary["timing"]["latency_us"]["p99"] >= small_run.summary["timing"]["latency_us"]["p50"]


def test_revocation_stops_an_envelope_mid_run():
    r = run_arena(ArenaConfig(seed=7, agents=100, steps=200, steps_per_day=100, revoke={"step": 100, "envelope": "tactical"}))
    after = [e for e in r.events if e["step"] >= 100 and e["env"] == "tactical"]
    assert after and all(e["d"] == "refuse" and e["code"] == "revoked" for e in after)


def test_population_is_seeded_and_honours_rates():
    sl = split_sleeves(DEFAULT_SYMBOLS)
    p1 = make_population(PopulationConfig(n=400, seed=2), sl, 1000)
    p2 = make_population(PopulationConfig(n=400, seed=2), sl, 1000)
    assert [(a.archetype, a.failure, a.sleeve, a.symbols) for a in p1] == [(a.archetype, a.failure, a.sleeve, a.symbols) for a in p2]
    assert sum(a.failure == "fat_finger" for a in p1) == 8 and sum(a.failure == "colluding" for a in p1) % 5 == 0
    assert homoglyph("AAPL") != "AAPL" and homoglyph("AAPL").upper() != "AAPL"


def test_binance_public_feed_records_and_replays_exactly(tmp_path):
    calls = []

    def fake_fetch(path, params):
        calls.append(path)
        syms = json.loads(params["symbols"])
        if path.endswith("bookTicker"):
            return [{"symbol": s, "bidPrice": "100.0", "askPrice": "100.2"} for s in syms]
        return [{"symbol": s, "price": "100.1"} for s in syms]

    rec = tmp_path / "f.jsonl"
    feed = BinancePublicFeed(["BTCUSDT"], max_steps=5, duration_s=None, record_path=rec, fetch=fake_fetch, sleep=lambda s: None, unit_size={"BTCUSDT": 0.5})
    live = [s.quotes for s in feed]
    assert len(live) == 5 and set(calls) == {"/api/v3/ticker/bookTicker", "/api/v3/ticker/price"}
    assert live[0]["BTCUSDT"] == {"bid": 50.0, "last": 50.05, "ask": 50.1}
    assert [s.quotes for s in RecordedFeed(rec)] == live
    r = run_arena(ArenaConfig(agents=20, steps=5), feed=RecordedFeed(rec))
    assert r.summary["proposals"] >= 0


def test_binance_public_feed_reads_only_two_public_endpoints():
    import pytest
    from orderguard_arena.feeds import FeedError
    f = BinancePublicFeed(["BTCUSDT"])
    with pytest.raises(FeedError):
        f._http_fetch("/api/v3/order", {})
    with pytest.raises(FeedError):
        BinancePublicFeed(["BTCUSDT"], base_url="https://testnet.binance.vision")        # market data from public hosts only
    with pytest.raises(FeedError):
        BinancePublicFeed(["BTCUSDT"], base_url="https://api.binance.com.evil.example")


def test_llm_agent_wrapper_turns_a_scripted_reply_into_a_proposal():
    class Model:
        def chat(self, messages, tools=None, **kw):
            return {"choices": [{"message": {"content": '{"ticker":"AAPL","side":"buy","quantity":3,"limit_price":200.0}'}}]}

    sl = split_sleeves(DEFAULT_SYMBOLS)
    agents = make_population(PopulationConfig(n=20, seed=1), sl, 100)
    agents = wrap_llm(agents, Model(), 2)
    llm = [a for a in agents if isinstance(a, LLMAgent)]
    assert len(llm) == 2
    ctx = Ctx(100)
    ctx.update(0, {"AAPL": 200.0}, ())
    props = []
    for s in range(0, 60):
        props += llm[0].propose(ctx, None, s)
    assert props and props[0].order["ticker"] == "AAPL" and props[0].label == "legit"
