"""Evaluate draft ranking on fresh worlds under signed parent policies."""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np

from orderguard_arena.envelopes import owner_key_from_seed
from orderguard_arena.mandate_features import context_vector, scenario_inputs
from orderguard_arena.mandate_model import METRICS, feature_vector, load_model, output_units
from orderguard_arena.policy_candidates import policy_candidates
from orderguard_arena.policy_review import RISK_LIMITS, load_parent
from orderguard_arena.policy_search import point_risk
from orderguard_arena.policy_sim import REGIMES, PolicyScenario, policy_metrics, shared_policy_feed, simulate_policy
from orderguard_guard.gate import sign_mandate
from orderguard_guard.init_cmd import mandate_template

from .calibrate_mandate_model import RISK_COLUMNS, read_rows
from .evaluate_mandate_ranking import MODEL_PARAMS, features_and_labels, paired_trial_delta, summarize
from .train_mandate_model import arrays

SEEDS = range(7000, 7048)
PROFILES = {
    "starter": (50, 100, 150, 250, 400),
    "portfolio": (100, 150, 250, 400, 600, 800),
    "demo": (150, 250, 400, 600, 800, 1000),
}
LIMIT_PROFILES = {
    "strict": (0.04, 5_000, 0.20, 0.04),
    "balanced": (0.15, 25_000, 0.35, 0.06),
    "relaxed": (0.25, 100_000, 0.60, 0.15),
}
_AS_OF = dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc)


def signed_fixture(profile):
    if profile == "demo":
        return load_parent("demo")
    body = mandate_template(_AS_OF)
    if profile == "portfolio":
        prices = {"AAPL": 200, "MSFT": 420, "SPY": 540, "JNJ": 150, "KO": 65, "JPM": 230}
        body.update(symbols=list(prices), referencePrices=prices, maxOrderNotionalUsd=18_000,
                    maxDailyNotionalUsd=350_000, stepUpAboveUsd=14_000, priceBandPct=4)
    key = owner_key_from_seed(f"policy-ranking-study-{profile}")
    return sign_mandate(body, key), key.public_key(), ()


def simulate_group(job):
    profile, seed, regime = job
    rng = random.Random(f"signed-policy-ranking-1:{seed}:{regime}:{profile}")
    scenario = PolicyScenario(seed, rng.choice(PROFILES[profile]), rng.choice((120, 200, 300, 400, 600, 900)), regime)
    parent, key, revoked = signed_fixture(profile)
    return simulate_parent_group(profile, scenario, parent, key, revoked)


def simulate_parent_group(profile, scenario, parent, key, revoked):
    generated = policy_candidates(parent, key, revoked, now=_AS_OF)
    market = shared_policy_feed(scenario)
    return {"profile": profile, "scenario": asdict(scenario), "parent_id": generated["parent_id"],
            "parent_daily_cap": parent["maxDailyNotionalUsd"], "candidates": [
                candidate | {"actual": policy_metrics(simulate_policy(candidate["draft"], scenario, feed=market))}
                for candidate in generated["candidates"]]}


def generate_holdout(path, workers, *, seeds=SEEDS, simulator=simulate_group):
    jobs = [(profile, seed, regime) for seed in seeds for regime in REGIMES for profile in PROFILES]
    temporary = path.with_suffix(".partial.gz")
    with gzip.open(temporary, "wt") as output, ProcessPoolExecutor(max_workers=workers) as pool:
        for index, group in enumerate(pool.map(simulator, jobs), 1):
            output.write(json.dumps(group, sort_keys=True) + "\n")
            if index % 48 == 0 or index == len(jobs):
                print(f"Simulated {index}/{len(jobs)} signed-policy batches.", flush=True)
    temporary.replace(path)


def conditioned_samples(x, outcomes, units, original_limits, extra_limits=()):
    variants = [original_limits, *extra_limits]
    for relative, absolute, refusal, holds in LIMIT_PROFILES.values():
        variants.append(np.column_stack([np.minimum(relative, absolute / units[:, 0]),
                                        np.full(len(x), refusal), np.full(len(x), holds)]))
    rng = np.random.default_rng(53)
    for _ in range(12):
        ratios = rng.choice([0, 0.02, 0.04, 0.08, 0.15, 0.25, 0.45, 0.8], size=len(x))
        amounts = rng.choice([1_000, 5_000, 25_000, 100_000], size=len(x))
        variants.append(np.column_stack([np.minimum(ratios, amounts / units[:, 0]),
                                        rng.choice([0.1, 0.2, 0.35, 0.5, 0.6, 0.8], size=len(x)),
                                        rng.choice([0, 0.02, 0.04, 0.06, 0.15, 0.3], size=len(x))]))
    inputs = np.concatenate([np.column_stack([x, limits]) for limits in variants])
    labels = np.concatenate([np.all(outcomes[:, RISK_COLUMNS] <= limits, axis=1) for limits in variants])
    return inputs, labels


def fit_rankers(training):
    from sklearn.ensemble import HistGradientBoostingClassifier

    _, x, original_limits, original_labels = features_and_labels(training)
    _, outcomes, units, _ = arrays(training)
    inputs, labels = conditioned_samples(x, outcomes, units, original_limits)
    fixed = HistGradientBoostingClassifier(**MODEL_PARAMS).fit(x, original_labels)
    conditioned = HistGradientBoostingClassifier(**MODEL_PARAMS).fit(inputs, labels)
    return fixed, conditioned


def measure_order(order, qualifies, allowed):
    ranks = [rank for rank, index in enumerate(order, 1) if qualifies[index]]
    if not ranks:
        return (False, False, len(order)), None
    first = ranks[0]
    best_utility = float(np.max(allowed[qualifies]))
    selected_utility = float(allowed[order[first - 1]])
    return (first == 1, first <= 3, first), {"allowed_usd_per_day": selected_utility,
                                            "gap_to_best_feasible_usd_per_day": best_utility - selected_utility}


def evaluate(training, holdout):
    expected = {(seed, regime, profile) for seed in SEEDS for regime in REGIMES for profile in PROFILES}
    actual = {(g["scenario"]["seed"], g["scenario"]["regime"], g["profile"]) for g in holdout}
    if actual != expected or len(holdout) != len(expected) or any(len(g["candidates"]) != 8 for g in holdout):
        raise ValueError("The signed-policy holdout is incomplete or has unexpected groups.")
    if {r["scenario"]["seed"] for r in training}.intersection(SEEDS):
        raise ValueError("Training and holdout seeds overlap.")
    fixed, conditioned = fit_rankers(training)
    trees = load_model()["trees"]
    results, timings = [], []
    for group in holdout:
        scenario = PolicyScenario(**group["scenario"])
        drafts = [candidate["draft"] for candidate in group["candidates"]]
        outcome = np.array([[c["actual"][key] for key in METRICS] for c in group["candidates"]])
        start = time.perf_counter_ns()
        world = scenario_inputs(scenario)
        inputs = np.array([feature_vector(d, scenario) + context_vector(d, world) for d in drafts])
        feature_ns = time.perf_counter_ns() - start
        fixed_score = fixed.decision_function(inputs)
        units = np.array([output_units(d, scenario) for d in drafts])[:, RISK_COLUMNS]
        for label, (relative, absolute, refusal, holds) in LIMIT_PROFILES.items():
            thresholds = np.array([min(relative * group["parent_daily_cap"], absolute), refusal, holds * scenario.agents])
            qualifies = np.all(outcome[:, RISK_COLUMNS] <= thresholds, axis=1)
            start = time.perf_counter_ns()
            scores = conditioned.decision_function(np.column_stack([inputs, thresholds / units]))
            learned_order = np.argsort(-scores, kind="stable")
            timings.append((time.perf_counter_ns() - start + feature_ns) / 1e6)
            limits = dict(zip(RISK_LIMITS, thresholds))
            point_order = sorted(range(len(drafts)), key=lambda i: point_risk(drafts[i], scenario, limits, trees))
            orders = {"learned": learned_order, "fixed_ranker": np.argsort(-fixed_score, kind="stable"),
                      "point_forecast": point_order, "given_order": range(len(drafts))}
            measured = {name: measure_order(order, qualifies, outcome[:, 1]) for name, order in orders.items()}
            results.append({"seed": scenario.seed, "regime": scenario.regime, "profile": group["profile"], "limits": label,
                            "feasible": int(qualifies.sum()), "methods": {name: values[0] for name, values in measured.items()},
                            "utility": {name: values[1] for name, values in measured.items()}})
    report = {"all": summarize(results)}
    for field, values in (("regime", REGIMES), ("profile", PROFILES), ("limits", LIMIT_PROFILES)):
        report[f"by_{field}"] = {value: summarize([g for g in results if g[field] == value]) for value in values}
    methods = report["all"]["methods"]
    deltas = {name: paired_trial_delta(results, name) for name in methods if name != "learned"}
    report["learned_minus_baseline_trials"] = deltas
    report["utility_on_feasible_batches"] = {}
    for name in methods:
        utilities = [g["utility"][name] for g in results if g["feasible"]]
        report["utility_on_feasible_batches"][name] = {
            key: float(np.mean([row[key] for row in utilities])) for key in utilities[0]}
    report["ranking_latency"] = {"p95_ms": float(np.percentile(timings, 95)), "batches": len(timings),
                                 "scope": "In-process world generation, all features, inference and sort."}
    report["meets_experiment_criteria"] = (methods["learned"]["top3_hit"] >= 0.9 and
                                           all(delta["bootstrap_95"][1] < 0 for delta in deltas.values()) and
                                           report["ranking_latency"]["p95_ms"] < 500)
    report["criteria"] = {"top3_hit_minimum": 0.9, "fewer_trials_than_each_baseline_at_upper_95_percent_bound": True,
                          "p95_ranking_ms_below": 500}
    report["candidate_worlds"] = len(holdout)
    report["simulated_drafts"] = sum(len(group["candidates"]) for group in holdout)
    report["limits_profiles"] = {name: dict(zip(("parent_cap_fraction", "absolute_bad_cap_usd_per_day", "false_refusal_rate",
                                               "holds_per_day_per_agent"), values)) for name, values in LIMIT_PROFILES.items()}
    report["seeds"] = list(SEEDS)
    report["model_parameters"] = MODEL_PARAMS
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("holdout", type=Path)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--training", type=Path, help="training.jsonl.gz from the calibration experiment")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if bool(args.training) != bool(args.output) or not (args.generate or args.training):
        parser.error("Use --generate, --training with --output, or both.")
    if args.generate:
        generate_holdout(args.holdout, args.workers)
    if args.training:
        training, holdout = read_rows(args.training), read_rows(args.holdout)
        report = evaluate(training, holdout)
        report["sha256"] = {name: hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
                            for name, rows in (("training", training), ("holdout", holdout))}
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
