"""Validate fast forecasts of useful drafts that satisfy the entered limits."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

import numpy as np

from orderguard_arena.mandate_features import RUNAWAY_FEATURES, context_vector, runaway_vector, scenario_inputs
from orderguard_arena.mandate_model import feature_vector, forest_predict, load_model, outside_domain, output_units
from orderguard_arena.mandate_warning import ARTIFACT as WARNING_ARTIFACT
from orderguard_arena.mandate_warning import forecast_lower, load_warning_model
from orderguard_arena.policy_review import RISK_LIMITS
from orderguard_arena.policy_sim import PolicyScenario

from .calibrate_mandate_model import RISK_COLUMNS, TRANSFORM_SCALE, read_rows
from .evaluate_selective_mandate import (MAX_P95_MS, MAX_SEED_ERROR, MIN_CORRECT_SHARE, calibrate, check_groups,
                                        direction_report, paired_coverage_gain)
from .evaluate_signed_policy_ranking import generate_holdout
from .evaluate_varied_policy_warnings import RISK_METRICS, data_digest, risk_thresholds, simulate_varied_group
from .recalibrate_varied_policy_warnings import warning_report

_SEEDS = random.Random(520339).sample(range(10_000, 2**32), 160)
CALIBRATION_SEEDS = tuple(_SEEDS[:64])
HOLDOUT_SEEDS = tuple(_SEEDS[64:])
_RUNAWAY_SEEDS = random.Random(1481927).sample(range(10_000, 2**32), 192)
RUNAWAY_CALIBRATION_SEEDS = tuple(_RUNAWAY_SEEDS[:64])
RUNAWAY_HOLDOUT_SEEDS = tuple(_RUNAWAY_SEEDS[64:])
JOINT = "joint_monotone"
FACTORED = "per_limit_monotone"
BASELINE = "current_forecast"
WITHOUT_RUNAWAY = "per_limit_without_runaway"
SCALE = TRANSFORM_SCALE[list(RISK_COLUMNS)]
PARAMETERS = {"max_iter": 240, "max_leaf_nodes": 31, "min_samples_leaf": 30, "early_stopping": False,
              "l2_regularization": 2, "random_state": 41}
FIELDS = [("seed", "i8"), ("regime", "U10"), ("profile", "U10"), ("limits", "U10"),
          ("candidate", "i4"), ("qualifies", "?"), ("positive_fills", "?"), ("eligible", "?")]


@dataclass(frozen=True)
class AssessmentBatch:
    features: np.ndarray
    limits: np.ndarray
    active: np.ndarray
    within: np.ndarray
    rows: np.ndarray
    baseline: np.ndarray
    warned: np.ndarray
    warning_correct: np.ndarray
    feature_ms: float


def prepare_group(group, *, include_runaway=False, enforce_warning=False):
    scenario = PolicyScenario(**group["scenario"])
    drafts = [candidate["draft"] for candidate in group["candidates"]]
    actual = np.array([[candidate["actual"][metric] for metric in RISK_METRICS] for candidate in group["candidates"]])
    fills = [candidate["actual"]["legitimate_fills"] > 0 for candidate in group["candidates"]]
    start = time.perf_counter_ns()
    base = [feature_vector(draft, scenario) for draft in drafts]
    world = scenario_inputs(scenario, include_runaway=include_runaway)
    context = np.array([row + context_vector(draft, world) for draft, row in zip(drafts, base)])
    features = np.column_stack([context, [runaway_vector(draft, world) for draft in drafts]]) if include_runaway else context
    units = np.array([output_units(draft, scenario) for draft in drafts])[:, RISK_COLUMNS]
    eligible = np.array([not outside_domain(draft, scenario) for draft in drafts])
    lower = np.zeros_like(units)
    if enforce_warning and eligible.any():
        lower[eligible] = forecast_lower(load_warning_model(), context[eligible].tolist(), units[eligible])
    elapsed = (time.perf_counter_ns() - start) / 1e6

    profiles = risk_thresholds(group, scenario)
    entered = np.array([[profile.get(metric, np.inf) for metric in RISK_METRICS] for profile in profiles.values()])
    # An omitted limit imposes the same constraint as the maximum attainable outcome.
    normalized_maxima = np.column_stack([np.ones(len(drafts)), np.ones(len(drafts)), RISK_LIMITS["holds_per_day"] / units[:, 2]])
    normalized = np.minimum(entered[:, None, :] / units, normalized_maxima)
    limits = np.log1p(normalized / SCALE)
    active = np.broadcast_to(np.isfinite(entered)[:, None, :], limits.shape)
    within = actual <= entered[:, None, :]
    exceeds = lower > entered[:, None, :]
    warned = exceeds.any(axis=2)
    relative = lower / np.maximum(entered[:, None, :], 1e-12)
    named = np.argmax(np.where(exceeds, relative, -np.inf), axis=2)[..., None]
    warning_correct = warned & np.take_along_axis(~within, named, axis=2)[..., 0]
    rows = [(scenario.seed, scenario.regime, group["profile"], level, index, fits, fill, allowed)
            for level, met in zip(profiles, within.all(axis=2))
            for index, (fits, fill, allowed) in enumerate(zip(met, fills, eligible))]
    trees = load_model()["trees"]
    point = np.array([forest_predict(trees, row) for row in base])[:, RISK_COLUMNS]
    ratio = np.max(point / np.maximum(entered[:, None, :] / units, 1e-12), axis=2)
    baseline = -np.log(np.maximum(ratio, 1e-12)).ravel()
    return AssessmentBatch(np.tile(features, (len(profiles), 1)), limits.reshape(-1, len(RISK_METRICS)),
                           active.reshape(-1, len(RISK_METRICS)), within.reshape(-1, len(RISK_METRICS)),
                           np.array(rows, dtype=FIELDS), baseline, warned.ravel(), warning_correct.ravel(), elapsed)


def usefully_qualifies(rows):
    return rows["qualifies"] & rows["positive_fills"]


def fit(batches, *, include_joint=True):
    from sklearn.ensemble import HistGradientBoostingClassifier

    features, limits, active, within, rows = (np.concatenate([getattr(batch, name) for batch in batches])
                                              for name in ("features", "limits", "active", "within", "rows"))
    monotone = [0] * features.shape[1]
    joint = None
    if include_joint:
        joint = HistGradientBoostingClassifier(monotonic_cst=monotone + [1] * len(RISK_METRICS), **PARAMETERS)
        joint.fit(np.column_stack([features, limits]), usefully_qualifies(rows))
    conditional = []
    for i, measured in enumerate(within.T):
        applies = active[:, i]
        model = HistGradientBoostingClassifier(monotonic_cst=monotone + [1], **PARAMETERS)
        model.fit(np.column_stack([features[applies], limits[applies, i]]), measured[applies])
        conditional.append(model)
    # Fit one example per simulated draft because its fills do not depend on the entered limits.
    one_per_draft = rows["limits"] == "balanced"
    fill = HistGradientBoostingClassifier(**PARAMETERS).fit(features[one_per_draft], rows["positive_fills"][one_per_draft])
    return joint, conditional, fill


def predict(models, features, limits, active, name):
    joint, conditional, fill = models
    if name == JOINT:
        return joint.decision_function(np.column_stack([features, limits]))
    loss = 1 - fill.predict_proba(features)[:, 1]
    for i, model in enumerate(conditional):
        loss += active[:, i] * model.predict_proba(np.column_stack([features, limits[:, i]]))[:, 0]
    return -loss


def score_batches(batches, models, without_runaway=None):
    rows = np.concatenate([batch.rows for batch in batches])
    features, limits, active = (np.concatenate([getattr(batch, name) for batch in batches])
                               for name in ("features", "limits", "active"))
    scores = {BASELINE: np.concatenate([batch.baseline for batch in batches])}
    for name in ((JOINT, FACTORED) if without_runaway is None else (FACTORED,)):
        scores[name] = predict(models, features, limits, active, name)
    if without_runaway is not None:
        scores[WITHOUT_RUNAWAY] = predict(without_runaway, features[:, :-len(RUNAWAY_FEATURES)], limits, active, FACTORED)
    eligible = rows["eligible"] & ~np.concatenate([batch.warned for batch in batches])
    return rows, {name: np.where(eligible, score, -np.inf) for name, score in scores.items()}


def model_timings(batches, models, names):
    timings = {name: [] for name in names}
    for batch in batches:
        for name, elapsed in timings.items():
            features, limits, active = batch.features[:8], batch.limits[:8], batch.active[:8]
            start = time.perf_counter_ns()
            predict(models, features, limits, active, name)
            elapsed.append(batch.feature_ms + (time.perf_counter_ns() - start) / 1e6)
    return {name: float(np.percentile(elapsed, 95)) for name, elapsed in timings.items()}


def forecast_mistakes(rows, scores, wrong, groups):
    worlds = {(group["scenario"]["seed"], group["scenario"]["regime"], group["profile"]): group for group in groups}
    cases = []
    for row, score in zip(rows[wrong], scores[wrong]):
        group = worlds[int(row["seed"]), row["regime"], row["profile"]]
        scenario = PolicyScenario(**group["scenario"])
        candidate = group["candidates"][row["candidate"]]
        limits = risk_thresholds(group, scenario)[row["limits"]]
        observed = {metric: candidate["actual"][metric] for metric in (*RISK_METRICS, "legitimate_fills")}
        cases.append({"scenario": group["scenario"], "profile": group["profile"], "parent_id": group["parent_id"],
                      "draft": candidate["draft"], "limits": limits, "observed": observed, "score": float(score)})
    return cases


def prepare_batches(groups, include_runaway, workers, *, enforce_warning=False):
    prepare = partial(prepare_group, include_runaway=include_runaway, enforce_warning=enforce_warning)
    if not include_runaway or workers == 1:
        return [prepare(group) for group in groups]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(prepare, groups, chunksize=16))


def deployed_warning_evidence(batches):
    rows, warned, correct = (np.concatenate([getattr(batch, name) for batch in batches])
                             for name in ("rows", "warned", "warning_correct"))
    return warning_report(rows, warned, correct)


def evaluate(training, calibration, holdout, primary, *, include_runaway=False, workers=1):
    import sklearn

    print("Preparing training features.", flush=True)
    training_batches = prepare_batches(training, include_runaway, workers)
    print("Fitting the forecast models.", flush=True)
    models = fit(training_batches, include_joint=not include_runaway)
    without_runaway = None
    if include_runaway:
        ablation = [replace(batch, features=batch.features[:, :-len(RUNAWAY_FEATURES)]) for batch in training_batches]
        without_runaway = fit(ablation, include_joint=False)
    print("Calibrating selective scores by seed.", flush=True)
    calibration_batches = prepare_batches(calibration, include_runaway, workers, enforce_warning=include_runaway)
    rows, scores = score_batches(calibration_batches, models, without_runaway)
    cutoffs = {name: calibrate(score, usefully_qualifies(rows), rows["seed"], tolerance=True) for name, score in scores.items()}

    print("Scoring held-out batches.", flush=True)
    batches = prepare_batches(holdout, include_runaway, workers, enforce_warning=include_runaway)
    rows, scores = score_batches(batches, models, without_runaway)
    forecasts = {name: scores[name] > cutoffs[name] for name in scores}
    target = usefully_qualifies(rows)
    overall = {name: direction_report(rows, prediction, target) for name, prediction in forecasts.items()}
    missed = ~np.concatenate([batch.within for batch in batches])
    for name, result in overall.items():
        result["forecast_errors_by_outcome"] = {metric: int(np.sum(forecasts[name] & errors))
                                                for metric, errors in zip(RISK_METRICS, missed.T)}
        result["forecast_errors_by_outcome"]["no_legitimate_fills"] = int(np.sum(forecasts[name] & ~rows["positive_fills"]))
    primary_mistakes = forecast_mistakes(rows, scores[primary], forecasts[primary] & ~target, holdout)
    slices = {field: {str(level): {name: direction_report(rows[mask], prediction[mask], target[mask])
                                  for name, prediction in forecasts.items()}
                      for level in np.unique(rows[field]) if (mask := rows[field] == level).any()}
              for field in ("regime", "profile", "limits")}
    gain = paired_coverage_gain(rows, forecasts[primary], forecasts[BASELINE], "likely_within_limits")
    timings = model_timings(batches, models, (FACTORED,) if include_runaway else (JOINT, FACTORED))
    selected = overall[primary]
    conditional = selected["error_seed_rate_given_forecast_upper_95"]
    criteria = {"correct_coverage_at_least_20_pct": selected["correct_share_of_actual"] >= MIN_CORRECT_SHARE,
                "seed_error_upper_at_most_5_pct": selected["error_seed_rate_upper_95"] <= MAX_SEED_ERROR,
                "predicting_seed_error_upper_at_most_5_pct": conditional is not None and conditional <= MAX_SEED_ERROR,
                "paired_improvement_over_current_forecast": gain["bootstrap_95"][0] > 0,
                "p95_below_500_ms": timings[primary] < MAX_P95_MS}
    report = {"primary": primary, "training_parameters": PARAMETERS, "scikit_learn": sklearn.__version__,
              "training_drafts": sum(len(group["candidates"]) for group in training), "holdout_rows": len(rows),
              "outside_domain_rows": int((~rows["eligible"]).sum()), "thresholds": cutoffs, "overall": overall,
              "slices": slices, "primary_mistakes": primary_mistakes, "paired_gain_over_baseline": gain,
              "p95_ms_eight_drafts_including_features": timings,
              "criteria": criteria, "criteria_met": all(criteria.values())}
    if include_runaway:
        report["runaway_features"] = list(RUNAWAY_FEATURES)
        report["warning_precedence_rows"] = int(sum(batch.warned.sum() for batch in batches))
        report["deployed_warning_recheck"] = deployed_warning_evidence(batches)
        report["warning_artifact_sha256"] = hashlib.sha256(WARNING_ARTIFACT.read_bytes()).hexdigest()
        report["paired_gain_over_same_model_without_runaway_inputs"] = paired_coverage_gain(
            rows, forecasts[primary], forecasts[WITHOUT_RUNAWAY], "likely_within_limits")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--training", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--primary", choices=(JOINT, FACTORED), default=FACTORED)
    parser.add_argument("--runaway-features", action="store_true", help="use the fresh splits for the runaway-order refinement")
    parser.add_argument("--development-probe", action="store_true", help="evaluate on prior datasets without claiming fresh validation")
    args = parser.parse_args()
    if not (args.generate or args.output) or bool(args.training) != bool(args.output):
        parser.error("Use --generate or provide both --training and --output.")
    if args.runaway_features and args.primary != FACTORED:
        parser.error("The runaway-input refinement uses the per-limit model as its primary forecast.")
    if args.workers < 1:
        parser.error("Use at least one worker.")
    calibration_seeds, holdout_seeds = ((RUNAWAY_CALIBRATION_SEEDS, RUNAWAY_HOLDOUT_SEEDS) if args.runaway_features
                                        else (CALIBRATION_SEEDS, HOLDOUT_SEEDS))
    if args.generate:
        args.directory.mkdir(parents=True, exist_ok=True)
        for name, seeds in (("calibration", calibration_seeds), ("holdout", holdout_seeds)):
            generate_holdout(args.directory / f"{name}.jsonl.gz", args.workers, seeds=seeds, simulator=simulate_varied_group)
    if args.output:
        training = [group for path in args.training for group in read_rows(path)]
        calibration, holdout = (read_rows(args.directory / f"{name}.jsonl.gz") for name in ("calibration", "holdout"))
        splits = {"training": training, "calibration": calibration, "holdout": holdout}
        identities = {name: {group["scenario"]["seed"] for group in groups} for name, groups in splits.items()}
        if len(set.union(*identities.values())) != sum(map(len, identities.values())):
            raise ValueError("Training, calibration, and holdout seeds must be disjoint.")
        if not args.development_probe:
            check_groups(calibration, calibration_seeds)
            check_groups(holdout, holdout_seeds)
        report = evaluate(training, calibration, holdout, args.primary, include_runaway=args.runaway_features, workers=args.workers)
        report["development_probe"] = args.development_probe
        report["splits"] = {name: {"sha256": data_digest(groups), "records": len(groups), "seeds": sorted(identities[name])}
                            for name, groups in splits.items()}
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
