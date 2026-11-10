"""L7 inside the agent loop: a rule-driven order is held before it reaches the ledger unless the trigger graph confirms the rule."""
import pytest

from orderguard_guard.agent import run_agent
from orderguard_guard.gate import APPLE_FY2024_TRUTH, FakeFigureChecker
from orderguard_guard.graph import real_crash_events, single_venue_crash_events, standing_rules
from orderguard_guard.llm import ScriptedLLM
from orderguard_lab import envs as E

CHECK = FakeFigureChecker(APPLE_FY2024_TRUTH)
SELL = {"ticker": "ISRG", "side": "sell", "quantity": 50, "limit_price": 520.4,
        "key_figures": [{"metric": "revenue", "fiscal_year": 2019, "value": 1, "unit": "USD millions"}]}


def screen_fn(chunk):
    return {"flag": False, "category": "clean", "why": "ok"}


def env_with(events):
    env = E.FeedEnv(mandate=E.trigger_mandate(), rules=[dict(r) for r in E.STANDING_RULES], account={"cash_usd": 50000.0, "positions": [{"ticker": "ISRG", "shares": 100}]})
    env.events = events
    return env


def run(events, arm):
    env = env_with(events)
    tr = run_agent(ScriptedLLM([[("place_order", SELL)], "done"], screen=screen_fn), "task", env, arm, figure_checker=CHECK)
    return env, tr


def test_single_venue_crash_sell_is_held_and_never_reaches_the_ledger():
    env, tr = run(single_venue_crash_events(), "full")
    g = tr["calls"][0]["gate"]
    assert g["decision"] == "hold" and g["layer"] == "L7" and "R1" in g["reasons"][0]
    assert env.ledger == []


def test_real_three_venue_crash_sell_goes_through_even_without_sec_facts():
    env, tr = run(real_crash_events(), "full")
    g = tr["calls"][0]["gate"]
    assert g["decision"] == "allow" and g["checks"]["l7_rule"] == "R1"
    assert len(env.ledger) == 1


@pytest.mark.parametrize("arm", ["gate_only", "naive"])
def test_other_arms_have_no_l7(arm):
    env, tr = run(single_venue_crash_events(), arm)
    g = tr["calls"][0]["gate"]
    assert not (g or {}).get("layer") == "L7"
    if arm == "naive":
        assert len(env.ledger) == 1


def test_a_rule_driven_order_still_fails_other_figure_checks_and_the_mandate():
    bad = dict(SELL, key_figures=[{"metric": "revenue", "fiscal_year": 2024, "value": 5, "unit": "USD millions"}])
    env = env_with(real_crash_events())
    tr = run_agent(ScriptedLLM([[("place_order", dict(bad, ticker="AAPL"))], "done"], screen=screen_fn), "task", env, "full", figure_checker=CHECK)
    assert tr["calls"][0]["gate"]["decision"] == "refuse"      # AAPL sell is not a rule order; a wrong AAPL figure is still refused
    assert env.ledger == []
