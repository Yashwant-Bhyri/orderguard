"""Test whether a learned ordering reduces exact simulator runs for mandate review."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from orderguard_arena.mandate_features import CONTEXT_FEATURES, context_vector, scenario_inputs
from orderguard_arena.mandate_model import FEATURES, feature_vector, forest_predict, load_model
from orderguard_arena.policy_sim import REGIMES, PolicyScenario

from .calibrate_mandate_model import RISK_COLUMNS, SPLITS, read_rows, scenario_features, simulate_cohort
from .train_mandate_model import arrays

HOLDOUT_SEEDS = range(6000, 6064)
COHORT_SIZES = {"wide": 8, "operator": 6}
MODEL_PARAMS = {"max_iter": 160, "max_leaf_nodes": 15, "min_samples_leaf": 25, "random_state": 41}


def generate_holdout(path: Path, workers: int) -> None:
    jobs = [(cohort, seed, regime) for seed in HOLDOUT_SEEDS for regime in REGIMES for cohort in COHORT_SIZES]
    temporary = path.with_suffix(".partial.gz")
    with gzip.open(temporary, "wt") as output, ProcessPoolExecutor(max_workers=workers) as pool:
        for batch in pool.map(simulate_cohort, jobs):
            for row in batch:
                output.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path)


def group_rows(rows):
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        scenario = row["scenario"]
        groups[scenario["seed"], scenario["regime"], row["cohort"]].append(index)
    return groups


def summarize(groups):
    feasible = [g for g in groups if g["feasible"]]
    rates = {}
    for method in groups[0]["methods"]:
        top1, top3, _ = np.mean([g["methods"][method] for g in feasible], axis=0) if feasible else (None,) * 3
        trials = np.array([g["methods"][method][2] for g in groups])
        rates[method] = {"top1_hit": top1, "top3_hit": top3, "mean_exact_trials": float(trials.mean()),
                         "total_exact_trials": float(trials.sum())}
    return {"groups": len(groups), "feasible_groups": len(feasible), "methods": rates}


def paired_trial_delta(groups, baseline):
    by_seed = defaultdict(list)
    for group in groups:
        methods = group["methods"]
        by_seed[group["seed"]].append(methods["learned"][2] - methods[baseline][2])
    means = np.array([np.mean(values) for values in by_seed.values()])
    sampled = np.random.default_rng(41).choice(means, (10_000, len(means)), replace=True).mean(axis=1)
    return {"mean": float(means.mean()), "bootstrap_95": np.percentile(sampled, (2.5, 97.5)).tolist()}


def features_and_labels(rows):
    base, actual, units, _ = arrays(rows)
    inputs = np.column_stack([base, [scenario_features(row) for row in rows]])
    limits = np.column_stack([np.minimum(0.15, 25_000 / units[:, 0]), np.full(len(rows), 0.35), np.full(len(rows), 0.06)])
    return base, inputs, limits, np.all(actual[:, RISK_COLUMNS] <= limits, axis=1)


def measure_ranking(model, holdout, groups, learned):
    durations = []
    for indices in groups.values():
        scenario = PolicyScenario(**holdout[indices[0]]["scenario"])
        start = time.perf_counter_ns()
        world = scenario_inputs(scenario)
        drafts = [holdout[i]["mandate"] for i in indices]
        features = [feature_vector(draft, scenario) + context_vector(draft, world) for draft in drafts]
        scores = model.decision_function(features)
        sorted(range(len(scores)), key=lambda i: -scores[i])
        durations.append((time.perf_counter_ns() - start) / 1e6)
        np.testing.assert_allclose(scores, learned[indices], rtol=0, atol=1e-12)
    return {"groups": len(durations), "median_ms": float(np.median(durations)),
            "p95_ms": float(np.percentile(durations, 95)), "max_ms": max(durations),
            "scope": "In-process seeded world generation, all features, scoring and sort."}


def evaluate(training, holdout):
    import sklearn
    from sklearn.ensemble import HistGradientBoostingClassifier

    wide, mixed = SPLITS["training"]
    expected = {(seed, regime, cohort): count for regime in REGIMES for cohort, count in COHORT_SIZES.items()
                for seed in (list(wide) + list(mixed) if cohort == "wide" else mixed)}
    if {key: len(value) for key, value in group_rows(training).items()} != expected:
        raise ValueError("Unexpected training groups or candidate counts.")
    groups = group_rows(holdout)
    expected = {(seed, regime, cohort): count for seed in HOLDOUT_SEEDS for regime in REGIMES
                for cohort, count in COHORT_SIZES.items()}
    if {key: len(value) for key, value in groups.items()} != expected:
        raise ValueError("Unexpected held-out groups or candidate counts.")
    _, x_train, _, y_train = features_and_labels(training)
    base, x_test, limits, qualifies = features_and_labels(holdout)
    model = HistGradientBoostingClassifier(**MODEL_PARAMS).fit(x_train, y_train)
    learned = model.decision_function(x_test)
    trees = load_model()["trees"]
    point = np.array([forest_predict(trees, row) for row in base.tolist()])
    point_risk = np.max(point[:, RISK_COLUMNS] / limits, axis=1)
    scores = {"learned": -learned, "point_forecast": point_risk, "given_order": np.arange(len(holdout))}

    results = []
    for (seed, regime, cohort), rows in groups.items():
        group = {"seed": seed, "regime": regime, "cohort": cohort, "feasible": int(qualifies[rows].sum()), "methods": {}}
        for name, values in scores.items():
            ordered = sorted(rows, key=values.__getitem__)
            first = next((i for i, row in enumerate(ordered, 1) if qualifies[row]), len(rows) + 1)
            group["methods"][name] = (first == 1, first <= 3, min(first, len(rows)))
        n, k = len(rows), group["feasible"]
        group["methods"]["random_expected"] = (k / n, 1 - math.comb(n - k, 3) / math.comb(n, 3),
                                               (n + 1) / (k + 1) if k else n)
        results.append(group)

    report = {"all": summarize(results)}
    for field, values in (("regime", REGIMES), ("cohort", COHORT_SIZES)):
        report[f"by_{field}"] = {value: summarize([g for g in results if g[field] == value]) for value in values}
    report["learned_minus_baseline_trials"] = {name: paired_trial_delta(results, name)
                                               for name in scores if name != "learned"}
    report["learned_minus_baseline_trials"]["random_expected"] = paired_trial_delta(results, "random_expected")
    report["ranking_latency"] = measure_ranking(model, holdout, groups, learned)
    methods = report["all"]["methods"]
    report["meets_experiment_criteria"] = (methods["learned"]["top3_hit"] >= 0.90 and
                                           methods["learned"]["mean_exact_trials"] < min(
                                               summary["mean_exact_trials"] for method, summary in methods.items()
                                               if method != "learned"))
    return report | {"model": {"type": "HistGradientBoostingClassifier", "parameters": MODEL_PARAMS,
                               "features": [*FEATURES, *CONTEXT_FEATURES],
                               "scikit_learn": sklearn.__version__},
                     "criteria": {"top3_hit_minimum": 0.90, "mean_exact_trials_below_each_baseline": True},
                     "exact_limits": {"bad_allowed_usd_per_day": "min(15% of draft daily cap, $25,000)",
                                      "false_refusal_rate": 0.35, "holds_per_day_per_agent": 0.06}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("training", type=Path, help="training.jsonl.gz from calibrate_mandate_model")
    parser.add_argument("holdout", type=Path, help="path to the unseen holdout.jsonl.gz")
    parser.add_argument("--generate-holdout", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.generate_holdout:
        generate_holdout(args.holdout, args.workers)
    training, holdout = read_rows(args.training), read_rows(args.holdout)
    report = evaluate(training, holdout)
    report["splits"] = {name: {"rows": len(rows), "seeds": sorted({r["scenario"]["seed"] for r in rows}),
                               "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}
                        for name, rows in (("training", training), ("holdout", holdout))}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
