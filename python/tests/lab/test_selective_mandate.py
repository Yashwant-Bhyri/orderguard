import numpy as np
import pytest

from orderguard_lab.evaluate_selective_mandate import calibrate, upper_bound


def test_calibration_counts_each_seed_once_and_ignores_correct_scores():
    seeds = np.arange(64)
    scores = np.concatenate([seeds, np.full(64, 100), np.full(100, 62)])
    worlds = np.concatenate([seeds, seeds, np.full(100, 62)])
    correct = np.concatenate([np.zeros(64), np.ones(64), np.zeros(100)]).astype(bool)
    assert calibrate(scores, correct, worlds) == 61


def test_tolerance_uses_worst_calibration_seed_at_this_sample_size():
    pytest.importorskip("scipy")
    seeds = np.arange(64)
    labels = np.zeros(len(seeds), dtype=bool)
    assert calibrate(seeds, labels, seeds, tolerance=True) == 63
    assert upper_bound(1, 96) < 0.05 < upper_bound(2, 96)
    with pytest.raises(ValueError, match="Too few calibration seeds"):
        calibrate(seeds[:50], labels[:50], seeds[:50], tolerance=True)


def test_lower_bound_honors_zero_limit_and_checks_the_named_outcome():
    from orderguard_lab.recalibrate_varied_policy_warnings import BASELINE, POINT, SCALE, outcomes, warning_report

    actual = np.array([[20.0, 0.1, 0.0], [0.0, 0.9, 0.0]])
    estimated_lower = np.array([[10.0, 0.01, 0.0], [10.0, 0.04, 0.0]])
    units = np.ones_like(actual)
    batch = {"seed": 1, "profile": "portfolio", "regime": "normal", "eligible": np.ones(2, dtype=bool),
             "actual": actual, "units": units, "low": np.log1p(estimated_lower / SCALE), "width": np.ones_like(actual),
             "limits": {"strict": {"bad_allowed_usd_per_day": 0.0, "false_refusal_rate": 0.2}},
             BASELINE: np.zeros_like(actual), POINT: np.zeros_like(actual)}
    rows, warned, correct, invalid = outcomes([batch], 0, {POINT: 1, BASELINE: 1})
    assert warned[:, 0].tolist() == [True, True]
    assert correct[:, 0].tolist() == [True, False]
    assert not warned[:, 1:].any()
    assert invalid == {1}
    pytest.importorskip("scipy")
    report = warning_report(rows, warned[:, 0], correct[:, 0])
    assert report["errors"] == 1 and report["warnings_on_drafts_meeting_every_limit"] == 0


def test_runaway_features_use_fresh_ids_and_the_draft_limits():
    from orderguard_arena.agents import PopulationConfig, make_population
    from orderguard_arena.envelopes import split_sleeves
    from orderguard_arena.mandate_features import RUNAWAY_FEATURES, runaway_orders, runaway_vector, scenario_inputs
    from orderguard_arena.policy_sim import PolicyScenario

    scenario = PolicyScenario(7, 1000, 400, "volatile")
    market = scenario.feed()
    population = make_population(PopulationConfig(n=scenario.agents, seed=scenario.seed, rates=scenario.rates()),
                                 split_sleeves(market.symbols), scenario.steps)
    fresh = {agent.id for agent in population if agent.failure == "runaway" and agent.run_fresh}
    duplicate = {agent.id for agent in population if agent.failure == "runaway" and not agent.run_fresh}
    assert fresh and duplicate
    unfilled, filled = runaway_orders(market, population)
    assert unfilled.size and filled.size
    assert set(unfilled["agent"]) | set(filled["agent"]) <= fresh
    assert all(agent.run_order is None and not agent.pos for agent in population)
    world = scenario_inputs(scenario, market, include_runaway=True)
    assert all(np.array_equal(actual, expected) for actual, expected in zip(world.runaway, (unfilled, filled)))
    draft = {"maxOrderNotionalUsd": 40_000, "maxDailyNotionalUsd": 1_200_000, "priceBandPct": 5,
             "symbols": market.symbols, "sides": ["buy", "sell"]}
    assert len(runaway_vector(draft, world)) == len(RUNAWAY_FEATURES)
    assert runaway_vector(draft, world)[1] > 0
    assert runaway_vector(draft | {"stepUpAboveUsd": 0}, world) == [0, 0, 0, 1] * 2
