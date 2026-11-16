"""Smoke and determinism tests for the four-system benchmark (one seed, short checks; the full run is in docs/vision/BENCHMARK.md)."""
import json

import pytest

from orderguard_autonomy.bench import audit
from orderguard_autonomy.bench.run import HEADLINE, aggregate, markdown, run_one, verdicts
from orderguard_autonomy.bench.scenarios import SCENARIOS
from orderguard_autonomy.bench.systems import SYSTEMS


def test_every_scenario_has_a_headline_measure():
    assert set(HEADLINE) == set(SCENARIOS)
    assert audit.AUDIT_SCENARIOS                     # the auditor restates the declared scenarios on its own


@pytest.mark.parametrize("scenario", ["coordinated_misinformation", "cross_venue"])
def test_run_is_deterministic(scenario):
    a = run_one(scenario, "D", 1)
    b = run_one(scenario, "D", 1)
    for k in ("proposals", "legit_executed_usd", "harmful_executed_usd", "holds", "refusals"):
        assert a[k] == b[k], k
    assert a["harm"] == b["harm"]


def test_d_holds_its_hard_limits_and_certificates_check_out():
    r = run_one("tool_compromise", "D", 1)
    assert r["hard_limit_breaches"] == 0
    assert r["escrow_invariants_ok"]
    assert r["certificates"]["verified_refuse"] == 0
    assert r["certificates"]["verified_allow"] > 0
    assert r["harm"]["compromised_notional_executed_usd"] == 0
    assert 0 <= r["legit_completion"] <= 1.0 + 1e-9


def test_bare_agent_is_harmed_where_d_is_not():
    a = run_one("coordinated_misinformation", "A", 1)
    d = run_one("coordinated_misinformation", "D", 1)
    assert a["harm"]["rumour_notional_executed_usd"] > 0
    assert d["harm"]["rumour_notional_executed_usd"] == 0


def test_report_builds_from_rows():
    rows = [run_one("delayed_acks", s, seed) for s in ("C", "D") for seed in (1, 2)]
    agg = aggregate(rows)
    ver = verdicts(agg)
    assert "delayed_acks" in ver and "D_vs_C" in ver["delayed_acks"]
    md = markdown(agg, ver, {"seeds": "1..2", "command": "test"})
    assert f"## {SCENARIOS['delayed_acks'].title}" in md and "D vs C: better" in md
    assert "-0.0%" not in md
    json.dumps(agg)


def test_systems_list_is_the_documented_one():
    assert tuple(SYSTEMS) == ("A", "B", "C", "C+", "D_auth", "D")
