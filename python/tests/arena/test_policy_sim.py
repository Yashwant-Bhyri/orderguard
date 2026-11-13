import datetime as dt

from orderguard_guard.gate import generate_keypair, sign_mandate

from orderguard_arena.agents import Agent, Proposal
from orderguard_arena.arena import ArenaConfig, run_arena
from orderguard_arena.envelopes import EnvelopeBook, make_envelope, owner_key_from_seed
from orderguard_arena.feeds import ReplayFeed
from orderguard_arena.policy_review import parent_for_review
from orderguard_arena.policy_sim import PolicyScenario, compare_policies, policy_metrics, simulate_policy

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
BODY = {"symbols": ["AAPL", "MSFT"], "sides": ["buy", "sell"], "maxOrderNotionalUsd": 10_000,
        "maxDailyNotionalUsd": 100_000, "priceBandPct": 3, "expiresAt": "2026-03-01T00:00:00Z"}


class PositionDependentAgent(Agent):
    def propose(self, ctx, snap, step):
        symbol = "AAPL"
        quantity = 10 if self.id == 0 else 1
        price = snap.trusted()[symbol]
        if step == 0:
            side, limit = "buy", price * 1.005
        elif step == 1 and self.pos.get(symbol, 0):
            side, limit = "sell", price * 0.995
        else:
            return []
        return [Proposal(step, self.id, self.archetype, "core", "legit",
                         {"ticker": symbol, "side": side, "quantity": quantity, "limit_price": limit}, self._key(step))]


def test_policy_changes_follow_up_orders_without_changing_other_agents_fill_draws():
    feed = ReplayFeed(10, symbols=["AAPL"], steps=2, steps_per_day=2, vol_scale=0)
    price = feed.trusted_first()["AAPL"]
    key = owner_key_from_seed("paired-test")

    def run(cap):
        book = EnvelopeBook(key.public_key())
        book.add(make_envelope(key, name="core", symbols=feed.symbols, per_order=cap, daily=100_000, band_pct=2))
        agents = [PositionDependentAgent(i, "rebalancer", 10, "core", feed.symbols) for i in range(2)]
        return run_arena(ArenaConfig(seed=10, agents=2, steps=2, paired_fills=True),
                         feed=feed, book=book, agents=agents, attach_receiver=False)

    broad, tight = run(price * 11), run(price * 2)
    assert [(e["step"], e["d"]) for e in broad.events if e["agent"] == 0] == [(0, "allow"), (1, "allow")]
    assert [(e["step"], e["d"]) for e in tight.events if e["agent"] == 0] == [(0, "refuse")]
    assert [e["fill_price"] for e in broad.events if e["agent"] == 1] == [e["fill_price"] for e in tight.events if e["agent"] == 1]


def test_signed_policy_comparison_repeats_and_accounts_for_paper_effects(monkeypatch):
    key, pub = generate_keypair()
    parent = sign_mandate(BODY, key)
    scenario = PolicyScenario(seed=7, agents=100, steps=220, regime="collusion")
    monkeypatch.setenv("ORDERGUARD_RECEIVER_URL", "http://127.0.0.1:1")
    result = compare_policies(parent, BODY, pub, scenario, now=NOW)
    assert result["fit"]["fits"]
    a, b = result["simulation"]["results"].values()
    assert a == b and a["proposals"] > 0
    assert all(0 <= day <= BODY["maxDailyNotionalUsd"] for day in a["daily_reserved_usd"])
    assert 0 < a["legitimate_filled_usd_per_day"] <= a["legitimate_allowed_usd_per_day"]
    assert 0 <= a["bad_filled_usd_per_day"] <= a["bad_allowed_usd_per_day"]
    actual = simulate_policy(BODY, scenario)
    assert actual.authority.receiver is None and policy_metrics(actual) == a


def test_invalid_draft_stops_before_market_setup(monkeypatch):
    key, pub = generate_keypair()
    def unexpected(_):
        raise AssertionError("An invalid draft must be refused before any simulation.")
    monkeypatch.setattr(PolicyScenario, "feed", unexpected)
    draft = BODY | {"maxDailyNotionalUsd": 100_001}
    res = compare_policies(sign_mandate(BODY, key), draft, pub, PolicyScenario(), now=NOW)
    assert not res["fit"]["fits"] and res["simulation"] is None


def test_daily_paper_fill_notional_cannot_round_above_allowed_notional():
    body = parent_for_review("demo")["parent"] | {"maxOrderNotionalUsd": 10_000,
            "maxDailyNotionalUsd": 450_000, "priceBandPct": 2, "stepUpAboveUsd": 7_000}
    run = simulate_policy(body, PolicyScenario(43, 1_000, 600, "poisoned"))
    metrics = policy_metrics(run)
    assert run.summary["bad"]["executed_usd"] == run.summary["bad"]["leaked_usd"] > 0
    assert metrics["bad_filled_usd_per_day"] == metrics["bad_allowed_usd_per_day"]
