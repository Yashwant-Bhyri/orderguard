"""Calibrate mandate assessments that can defer to the exact simulator."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from pathlib import Path

import numpy as np

from orderguard_arena.mandate_features import context_vector, scenario_inputs
from orderguard_arena.mandate_model import METRICS, feature_vector, forest_predict, load_model, output_units
from orderguard_arena.policy_sim import REGIMES, PolicyScenario

from .calibrate_mandate_model import RISK_COLUMNS, TRANSFORM_SCALE, read_rows
from .evaluate_mandate_ranking import MODEL_PARAMS, features_and_labels
from .evaluate_signed_policy_ranking import LIMIT_PROFILES, PROFILES, SEEDS, conditioned_samples, generate_holdout
from .train_mandate_model import arrays

_SEEDS = random.Random(401711).sample(range(10_000, 2**32), 160)
CALIBRATION_SEEDS = tuple(_SEEDS[:64])
HOLDOUT_SEEDS = tuple(_SEEDS[64:])
CONFIRMATION_SEEDS = tuple(random.Random(710363).sample(range(10_000, 2**32), 96))
MAX_SEED_ERROR = 0.05
MIN_CORRECT_SHARE = 0.20
MAX_P95_MS = 500
BASELINE = "current_forecast"
PRIMARY_MODEL = "conditioned_classifier"


def check_groups(groups, seeds):
    expected = {(seed, regime, profile) for seed in seeds for regime in REGIMES for profile in PROFILES}
    observed = {(group["scenario"]["seed"], group["scenario"]["regime"], group["profile"]) for group in groups}
    if observed != expected or len(groups) != len(expected) or any(len(g["candidates"]) != 8 for g in groups):
        raise ValueError("The dataset does not contain the specified signed-policy batches.")


def training_rows(original, signed):
    additional = [{"scenario": group["scenario"], "mandate": candidate["draft"], "actual": candidate["actual"],
                   "parent_cap": group["parent_daily_cap"]} for group in signed for candidate in group["candidates"]]
    return [*original, *additional]


def fit_context_regressors(features, outcomes):
    from sklearn.ensemble import HistGradientBoostingRegressor

    params = MODEL_PARAMS | {"early_stopping": False}
    transformed = np.log1p(outcomes / TRANSFORM_SCALE)
    return [HistGradientBoostingRegressor(loss="absolute_error", **params).fit(features, values)
            for values in transformed.T]


def context_forecast(regressors, features):
    log_values = np.column_stack([model.predict(features) for model in regressors])
    return np.clip(np.expm1(log_values) * TRANSFORM_SCALE, 0, [1, 1, 1, np.inf])


def fit_models(original, signed):
    from sklearn.ensemble import HistGradientBoostingClassifier

    training = training_rows(original, signed)
    _, features, original_limits, _ = features_and_labels(training)
    _, outcomes, units, _ = arrays(training)
    parent_caps = np.array([r.get("parent_cap", r["mandate"]["maxDailyNotionalUsd"]) for r in training])
    thresholds = [np.column_stack([np.minimum(relative * parent_caps, absolute) / units[:, 0],
                                   np.full(len(training), refusal), np.full(len(training), holds)])
                  for relative, absolute, refusal, holds in LIMIT_PROFILES.values()]
    inputs, labels = conditioned_samples(features, outcomes, units, original_limits, thresholds)
    params = MODEL_PARAMS | {"early_stopping": False}
    conditioned = HistGradientBoostingClassifier(**params).fit(inputs, labels)
    return conditioned, fit_context_regressors(features, outcomes)


def risk_margin(point, limits):
    ratio = np.max(point[:, RISK_COLUMNS] / np.maximum(limits, 1e-12), axis=1)
    return -np.log(np.maximum(ratio, 1e-12))


def assessments(groups, models):
    conditioned, regressors = models
    trees = load_model()["trees"]
    metadata, scores, timings = [], [], []
    for group in groups:
        scenario = PolicyScenario(**group["scenario"])
        drafts = [candidate["draft"] for candidate in group["candidates"]]
        actual = np.array([[c["actual"][key] for key in METRICS] for c in group["candidates"]])
        positive_fills = [c["actual"]["legitimate_fills"] > 0 for c in group["candidates"]]
        start = time.perf_counter_ns()
        base = [feature_vector(draft, scenario) for draft in drafts]
        world = scenario_inputs(scenario)
        features = np.array([row + context_vector(draft, world) for row, draft in zip(base, drafts)])
        units = np.array([output_units(draft, scenario) for draft in drafts])
        features_ns = time.perf_counter_ns() - start

        start = time.perf_counter_ns()
        context_point = context_forecast(regressors, features)
        regression_ns = time.perf_counter_ns() - start
        baseline = np.array([forest_predict(trees, row) for row in base])
        for level, (relative, absolute, refusal, holds) in LIMIT_PROFILES.items():
            threshold = np.array([min(relative * group["parent_daily_cap"], absolute), refusal, holds * scenario.agents])
            start = time.perf_counter_ns()
            limits = threshold / units[:, RISK_COLUMNS]
            prediction = conditioned.decision_function(np.column_stack([features, limits]))
            conditioned_ns = time.perf_counter_ns() - start
            start = time.perf_counter_ns()
            context_score = risk_margin(context_point, limits)
            context_ns = regression_ns + time.perf_counter_ns() - start
            timings.append(((features_ns + conditioned_ns) / 1e6, (features_ns + context_ns) / 1e6))
            scores.extend(zip(risk_margin(baseline, limits), prediction, context_score))
            qualifies = np.all(actual[:, RISK_COLUMNS] <= threshold, axis=1)
            metadata.extend((scenario.seed, scenario.regime, group["profile"], level, bool(qualified), fill)
                            for qualified, fill in zip(qualifies, positive_fills))
    fields = [("seed", "i8"), ("regime", "U10"), ("profile", "U10"), ("limits", "U10"),
              ("qualifies", "?"), ("positive_fills", "?")]
    return np.array(metadata, dtype=fields), np.array(scores), np.array(timings)


def calibrate(scores, labels, seeds, *, tolerance=False):
    """Set a threshold using each seed's highest erroneous confidence."""
    unique, groups = np.unique(seeds, return_inverse=True)
    worst = np.full(len(unique), -np.inf)
    np.maximum.at(worst, groups, np.where(labels, -np.inf, scores))
    if tolerance:
        allowed_errors = [errors for errors in range(len(worst)) if upper_bound(errors, len(worst)) <= MAX_SEED_ERROR]
        if not allowed_errors:
            raise ValueError("Too few calibration seeds for the one-sided 95% tolerance bound.")
        rank = len(worst) - max(allowed_errors)
    else:
        rank = math.ceil((len(worst) + 1) * (1 - MAX_SEED_ERROR))
    if rank > len(worst):
        raise ValueError("Too few seeds to calibrate the stated error target.")
    return float(np.sort(worst)[rank - 1])


def upper_bound(errors, trials):
    from scipy.stats import beta

    if trials == 0:
        return None
    return float(beta.ppf(0.95, errors + 1, trials - errors)) if errors < trials else 1.0


def direction_report(rows, given, target):
    seeds = rows["seed"]
    errors = given & ~target
    correct = given & target
    unique_seeds = len(np.unique(seeds))
    error_seeds = len(np.unique(seeds[errors]))
    predicting_seeds = len(np.unique(seeds[given]))
    return {"issued": int(given.sum()), "correct": int(correct.sum()), "errors": int(errors.sum()),
            "actual": int(target.sum()), "correct_share_of_actual": float(correct.sum() / target.sum()) if target.any() else None,
            "seeds_with_forecasts": predicting_seeds, "seeds_with_errors": error_seeds,
            "error_seed_rate_upper_95": upper_bound(error_seeds, unique_seeds),
            "error_seed_rate_given_forecast_upper_95": upper_bound(error_seeds, predicting_seeds)}


def report_assessments(rows, clears, flags):
    qualifies = rows["qualifies"]
    useful = qualifies & rows["positive_fills"]
    return {"rows": len(rows), "seeds": len(np.unique(rows["seed"])),
            "deferred": int((~clears & ~flags).sum()), "actually_qualifies_with_fills": int(useful.sum()),
            "forecast_qualifies_with_fills": int((clears & useful).sum()),
            "likely_within_limits": direction_report(rows, clears, qualifies),
            "likely_exceeds_limits": direction_report(rows, flags, ~qualifies)}


def paired_coverage_gain(rows, prediction, baseline, direction):
    qualifies = rows["qualifies"]
    if direction == "likely_within_limits":
        target = qualifies & rows["positive_fills"]
    else:
        target = ~qualifies
    correct_delta = (prediction & target).astype(int) - (baseline & target).astype(int)
    _, group = np.unique(rows["seed"], return_inverse=True)
    totals = np.bincount(group, weights=correct_delta)
    bootstrap = np.random.default_rng(47).choice(totals, (10_000, len(totals)), replace=True).mean(axis=1)
    return {"mean_extra_correct_per_seed": float(totals.mean()), "bootstrap_95": np.percentile(bootstrap, [2.5, 97.5]).tolist()}


def evaluate(original, signed, calibration, holdout, *, confirmation=False):
    import sklearn

    check_groups(signed, SEEDS)
    check_groups(calibration, CALIBRATION_SEEDS)
    check_groups(holdout, CONFIRMATION_SEEDS if confirmation else HOLDOUT_SEEDS)
    protected = (*SEEDS, *CALIBRATION_SEEDS, *HOLDOUT_SEEDS, *CONFIRMATION_SEEDS)
    if len(set(protected)) != len(protected) or {row["scenario"]["seed"] for row in original}.intersection(protected):
        raise ValueError("Training inputs overlap another seed split.")
    models = fit_models(original, signed)
    cal, cal_scores, _ = assessments(calibration, models)
    directions = ("likely_within_limits", "likely_exceeds_limits")
    methods = (BASELINE, PRIMARY_MODEL, "context_regression")
    thresholds, predictions, reports = {}, {}, {}
    for index, method in enumerate(methods):
        scores = cal_scores[:, index]
        clear = calibrate(scores, cal["qualifies"], cal["seed"], tolerance=confirmation)
        flag = calibrate(-scores, ~cal["qualifies"], cal["seed"], tolerance=confirmation)
        thresholds[method] = dict(zip(directions, (clear, flag)))
    test, test_scores, timings = assessments(holdout, models)
    slices = {"all": {"all": np.ones(len(test), dtype=bool)}}
    slices.update({field: {value: test[field] == value for value in values}
                   for field, values in (("regime", REGIMES), ("profile", PROFILES), ("limits", LIMIT_PROFILES))})
    for index, method in enumerate(methods):
        clear, flag = (thresholds[method][direction] for direction in directions)
        clears, flags = test_scores[:, index] > clear, -test_scores[:, index] > flag
        overlap = clears & flags
        issued_clear, issued_flag = predictions[method] = (clears & ~overlap, flags & ~overlap)
        reports[method] = {field: {value: report_assessments(test[mask], issued_clear[mask], issued_flag[mask])
                                   for value, mask in masks.items()} for field, masks in slices.items()}

    latency = dict(zip(methods[1:], np.percentile(timings, 95, axis=0).tolist()))
    for method in methods[1:]:
        reports[method]["comparisons"] = comparisons = {}
        overall = reports[method]["all"]["all"]
        for direction, prediction, baseline in zip(directions, predictions[method], predictions[BASELINE]):
            report = overall[direction]
            coverage = report["correct_share_of_actual"]
            if direction == "likely_within_limits":
                actual_with_fills = overall["actually_qualifies_with_fills"]
                coverage = overall["forecast_qualifies_with_fills"] / actual_with_fills if actual_with_fills else 0
            gain = paired_coverage_gain(test, prediction, baseline, direction)
            comparisons[direction] = gain | {"meets_criteria": report["error_seed_rate_upper_95"] <= MAX_SEED_ERROR
                                              and coverage is not None and coverage >= MIN_CORRECT_SHARE
                                              and gain["bootstrap_95"][0] > 0 and latency[method] < MAX_P95_MS}
    return {"primary_model": PRIMARY_MODEL, "model_parameters": MODEL_PARAMS | {"early_stopping": False},
            "calibration_rule": "nonparametric_tolerance_95" if confirmation else "split_conformal_95",
            "software": {"scikit_learn": sklearn.__version__, "numpy": np.__version__},
            "thresholds": thresholds, "holdout": reports, "p95_ms_eight_drafts_including_features": latency,
            "criteria": {"max_error_seed_rate_upper_95": MAX_SEED_ERROR, "minimum_correct_share": MIN_CORRECT_SHARE,
                         "positive_seed_bootstrap_gain_over_baseline": True, "max_p95_ms": MAX_P95_MS}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--confirmation", action="store_true", help="use the stricter calibration rule and independent confirmation seeds")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--training", type=Path, help="training.jsonl.gz from the original calibration study")
    parser.add_argument("--signed-training", type=Path, help="holdout.jsonl.gz from the prior signed-policy ranking study")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if len([arg for arg in (args.training, args.signed_training, args.output) if arg]) not in (0, 3):
        parser.error("Use --training, --signed-training and --output together.")
    if not (args.generate or args.output):
        parser.error("Generate datasets or provide training and output paths.")
    if args.generate:
        args.directory.mkdir(parents=True, exist_ok=True)
        splits = (("confirmation", CONFIRMATION_SEEDS),) if args.confirmation else (
            ("calibration", CALIBRATION_SEEDS), ("holdout", HOLDOUT_SEEDS))
        for name, seeds in splits:
            generate_holdout(args.directory / f"{name}.jsonl.gz", args.workers, seeds=seeds)
    if args.output:
        sources = {"training": args.training, "signed_training": args.signed_training,
                   "calibration": args.directory / "calibration.jsonl.gz",
                   "holdout": args.directory / ("confirmation.jsonl.gz" if args.confirmation else "holdout.jsonl.gz")}
        data = {name: read_rows(path) for name, path in sources.items()}
        report = evaluate(*data.values(), confirmation=args.confirmation)
        report["splits"] = {name: {"records": len(rows), "seeds": sorted({r["scenario"]["seed"] for r in rows}),
                                   "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}
                            for name, rows in data.items()}
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
