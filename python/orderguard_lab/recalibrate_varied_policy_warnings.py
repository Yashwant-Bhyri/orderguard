"""Recalibrate explanations for mandate warnings on varied signed policies."""
from __future__ import annotations

import argparse
import json
import random
import tempfile
import time
from pathlib import Path

import numpy as np

from orderguard_arena.mandate_features import context_vector, scenario_inputs
from orderguard_arena.mandate_model import feature_vector, forest_predict, load_model, outside_domain, output_units
from orderguard_arena.mandate_warning import FORMAT, MODEL_FEATURES, calibrated_lower, forecast_lower
from orderguard_arena.policy_sim import PolicyScenario

from .calibrate_mandate_model import MIN_WIDTH, RISK_COLUMNS, TRANSFORM_SCALE, read_rows, scenario_features
from .evaluate_mandate_ranking import MODEL_PARAMS
from .evaluate_selective_mandate import (CALIBRATION_SEEDS, CONFIRMATION_SEEDS, HOLDOUT_SEEDS, MAX_P95_MS, MAX_SEED_ERROR,
                                        MIN_CORRECT_SHARE, calibrate, check_groups, context_forecast, direction_report,
                                        fit_context_regressors, paired_coverage_gain, training_rows, upper_bound)
from .evaluate_signed_policy_ranking import SEEDS, generate_holdout
from .evaluate_varied_policy_warnings import RISK_METRICS, VARIED_SEEDS, data_digest, risk_thresholds, simulate_varied_group
from .train_mandate_model import arrays

_SEEDS = random.Random(249101).sample(range(10_000, 2**32), 160)
RECALIBRATION_SEEDS = tuple(_SEEDS[:64])
RECHECK_SEEDS = tuple(_SEEDS[64:])
SCALE = TRANSFORM_SCALE[list(RISK_COLUMNS)]
WIDTH_FLOOR = MIN_WIDTH[list(RISK_COLUMNS)]
LOWER = "adaptive_lower_bound"
POINT = "retrained_median"
BASELINE = "current_forecast"


def fit_quantiles(features, outcomes):
    from sklearn.ensemble import HistGradientBoostingRegressor

    transformed = np.log1p(outcomes[:, RISK_COLUMNS] / SCALE)
    params = MODEL_PARAMS | {"early_stopping": False}
    return tuple([HistGradientBoostingRegressor(loss="quantile", quantile=quantile, **params).fit(features, target)
                  for target in transformed.T] for quantile in (0.10, 0.90))


def predict_groups(groups, quantiles, median, *, save_features=False):
    trees = load_model()["trees"]
    batches, timings = [], []
    for group in groups:
        scenario = PolicyScenario(**group["scenario"])
        drafts = [candidate["draft"] for candidate in group["candidates"]]
        actual = np.array([[candidate["actual"][metric] for metric in RISK_METRICS] for candidate in group["candidates"]])
        start = time.perf_counter_ns()
        base = [feature_vector(draft, scenario) for draft in drafts]
        world = scenario_inputs(scenario)
        features = np.array([row + context_vector(draft, world) for row, draft in zip(base, drafts)])
        units = np.array([output_units(draft, scenario) for draft in drafts])[:, RISK_COLUMNS]
        eligible = np.array([not outside_domain(draft, scenario) for draft in drafts])
        low, high = (np.column_stack([model.predict(features) for model in models]) for models in quantiles)
        lo = np.maximum(0, np.minimum(low, high))
        width = np.maximum(np.maximum(low, high) - lo, WIDTH_FLOOR)
        timings.append((time.perf_counter_ns() - start) / 1e6)
        baseline = np.array([forest_predict(trees, row) for row in base])[:, RISK_COLUMNS] * units
        batch = {"seed": scenario.seed, "profile": group["profile"], "regime": scenario.regime, "units": units,
                 "eligible": eligible, "actual": actual, "low": lo, "width": width,
                 "limits": risk_thresholds(group, scenario), BASELINE: baseline,
                 POINT: context_forecast(median, features)[:, RISK_COLUMNS] * units}
        if save_features:
            batch["features"] = features.tolist()
        batches.append(batch)
    return batches, timings


def lower_adjustment(batches):
    scores, seeds = [], []
    for batch in batches:
        target = np.log1p(batch["actual"] / (batch["units"] * SCALE))
        errors = np.max((batch["low"] - target) / batch["width"], axis=1)
        scores.extend(np.where(batch["eligible"], errors, -np.inf))
        seeds.extend([batch["seed"]] * len(errors))
    return max(0, calibrate(np.array(scores), np.zeros(len(scores), dtype=bool), np.array(seeds), tolerance=True))


def lower_bound(batch, adjustment):
    return calibrated_lower(batch["low"], batch["width"], adjustment, SCALE, batch["units"])


def point_scores(estimates, limits):
    active = np.isfinite(limits) & (limits > 0)
    ratio = estimates / np.where(active, limits, np.inf)
    return np.where(active, np.log(np.maximum(ratio, 1e-12)), -np.inf)


def point_cutoffs(batches):
    scores = {method: [] for method in (POINT, BASELINE)}
    seeds = []
    for batch in batches:
        for limits in batch["limits"].values():
            thresholds = np.array([limits.get(metric, np.inf) for metric in RISK_METRICS])
            correct = batch["actual"] > thresholds
            for method, values in scores.items():
                margin = point_scores(batch[method], thresholds)
                wrong = np.where(batch["eligible"][:, None] & ~correct, margin, -np.inf)
                values.extend(np.max(wrong, axis=1))
            seeds.extend([batch["seed"]] * len(correct))
    return {method: calibrate(np.array(values), np.zeros(len(values), dtype=bool), np.array(seeds), tolerance=True)
            for method, values in scores.items()}


def outcomes(batches, adjustment, cutoffs):
    details, warnings, correct_reasons, bound_error_seeds = [], [], [], set()
    for batch in batches:
        bounds = lower_bound(batch, adjustment)
        if np.any(batch["eligible"][:, None] & (bounds > batch["actual"])):
            bound_error_seeds.add(batch["seed"])
        for level, limits in batch["limits"].items():
            thresholds = np.array([limits.get(metric, np.inf) for metric in RISK_METRICS])
            violates = batch["actual"] > thresholds
            details.extend((batch["seed"], batch["profile"], batch["regime"], level, not row.any(), eligible)
                           for row, eligible in zip(violates, batch["eligible"]))
            bound_ratio = bounds / np.maximum(thresholds, 1e-12)
            candidates = [(np.where(bounds > thresholds, bound_ratio, -np.inf), 0)]
            candidates.extend((point_scores(batch[method], thresholds), cutoff) for method, cutoff in cutoffs.items())
            issued, correct = [], []
            for scores, cutoff in candidates:
                chosen = np.argmax(scores, axis=1)
                i = np.arange(len(chosen))
                issued.append(batch["eligible"] & (scores[i, chosen] > cutoff))
                correct.append(violates[i, chosen])
            warnings.extend(zip(*issued))
            correct_reasons.extend(zip(*correct))
    fields = [("seed", "i8"), ("profile", "U10"), ("regime", "U10"), ("limits", "U10"), ("qualifies", "?"), ("eligible", "?")]
    return np.array(details, dtype=fields), np.array(warnings), np.array(correct_reasons), bound_error_seeds


def warning_report(rows, issued, reason_correct):
    violations = ~rows["qualifies"]
    report = direction_report(rows, issued, reason_correct)
    report["actual"] = int(violations.sum())
    report["correct_share_of_actual"] = report["correct"] / report["actual"] if report["actual"] else None
    report["warnings_on_drafts_meeting_every_limit"] = int((issued & ~violations).sum())
    return report


def export_regressor(model):
    trees = []
    for (predictor,) in model._predictors:
        if predictor.nodes["is_categorical"].any():
            raise ValueError("Portable mandate warnings use numerical split features.")
        tree = []
        for node in predictor.nodes:
            if node["is_leaf"]:
                tree.append([float(node["value"])])
            else:
                tree.append([int(node["feature_idx"]), float(node["num_threshold"]), int(node["left"]), int(node["right"])])
        trees.append(tree)
    return {"intercept": float(model._baseline_prediction[0, 0]), "trees": trees}


def export_validated_model(path, quantiles, adjustment, batches, evidence):
    artifact = {"format": FORMAT, "features": list(MODEL_FEATURES), "metrics": list(RISK_METRICS), "validated": True,
                "scale": SCALE.tolist(), "width_floor": WIDTH_FLOOR.tolist(), "adjustment": adjustment,
                "quantiles": [[export_regressor(model) for model in group] for group in quantiles], "evidence": evidence}
    encoded = json.dumps(artifact, separators=(",", ":"), allow_nan=False) + "\n"
    portable = json.loads(encoded)
    for batch in batches:
        reproduced = forecast_lower(portable, batch["features"], batch["units"])
        np.testing.assert_array_equal(reproduced, lower_bound(batch, adjustment))
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        output.write(encoded)
        temporary = Path(output.name)
    temporary.chmod(0o644)
    temporary.replace(path)


def evaluate(original, signed, development, calibration, holdout, *, export_path=None):
    import sklearn

    for groups, seeds in ((signed, SEEDS), (development, VARIED_SEEDS), (calibration, RECALIBRATION_SEEDS), (holdout, RECHECK_SEEDS)):
        check_groups(groups, seeds)
    protected = (*SEEDS, *VARIED_SEEDS, *CALIBRATION_SEEDS, *HOLDOUT_SEEDS, *CONFIRMATION_SEEDS, *RECALIBRATION_SEEDS, *RECHECK_SEEDS)
    if len(set(protected)) != len(protected) or set(protected).intersection(row["scenario"]["seed"] for row in original):
        raise ValueError("A training, calibration or holdout seed was reused.")
    training = training_rows(original, signed + development)
    base, measured, _, _ = arrays(training)
    features = np.column_stack([base, [scenario_features(row) for row in training]])
    quantile, median = fit_quantiles(features, measured), fit_context_regressors(features, measured)
    cal_batches, _ = predict_groups(calibration, quantile, median)
    adjustment = lower_adjustment(cal_batches)
    cutoffs = point_cutoffs(cal_batches)
    test_batches, timings = predict_groups(holdout, quantile, median, save_features=export_path is not None)
    test, warns, correct, bound_errors = outcomes(test_batches, adjustment, cutoffs)
    methods = (LOWER, *cutoffs)
    overall = {method: warning_report(test, warns[:, i], correct[:, i]) for i, method in enumerate(methods)}
    gain = paired_coverage_gain(test, warns[:, 0] & correct[:, 0], warns[:, 2] & correct[:, 2], "likely_exceeds_limits")
    slices = {}
    for field in ("profile", "regime", "limits"):
        slices[field] = {}
        for value in np.unique(test[field]):
            mask = test[field] == value
            slices[field][str(value)] = {method: warning_report(test[mask], warns[mask, i], correct[mask, i])
                                         for i, method in enumerate(methods)}
    p95 = float(np.percentile(timings, 95))
    main = overall[LOWER]
    bound_risk = upper_bound(len(bound_errors), len(RECHECK_SEEDS))
    criteria = {"warning_seed_error_upper_at_most_5_pct": main["error_seed_rate_upper_95"] <= MAX_SEED_ERROR,
                "lower_bound_seed_error_upper_at_most_5_pct": bound_risk <= MAX_SEED_ERROR,
                "correct_coverage_at_least_20_pct": main["correct_share_of_actual"] >= MIN_CORRECT_SHARE,
                "more_correct_warnings_than_current_forecast": gain["bootstrap_95"][0] > 0,
                "p95_below_500_ms": p95 < MAX_P95_MS}
    if export_path is not None and all(criteria.values()):
        evidence = {"calibration_seeds": len(RECALIBRATION_SEEDS), "holdout_seeds": len(RECHECK_SEEDS),
                    "holdout_sha256": data_digest(holdout), "warnings": main, "lower_bound_error_seed_rate_upper_95": bound_risk}
        export_validated_model(export_path, quantile, adjustment, test_batches, evidence)
    return {"criteria_met": all(criteria.values()), "criteria": criteria,
            "quantiles": [0.10, 0.90], "width_floor": WIDTH_FLOOR.tolist(),
            "lower_adjustment": adjustment, "point_cutoffs": cutoffs, "scikit_learn": sklearn.__version__,
            "training_drafts": len(training), "holdout_rows": len(test), "outside_domain_rows": int((~test["eligible"]).sum()),
            "bound_error_seeds": len(bound_errors), "bound_error_seed_rate_upper_95": bound_risk,
            "overall": overall, "slices": slices, "paired_gain_over_baseline": gain, "p95_ms_eight_drafts_including_features": p95}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--training", type=Path)
    parser.add_argument("--signed-training", type=Path)
    parser.add_argument("--development", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--export-model", type=Path, help="export the warning artifact after validation and runtime parity checks")
    args = parser.parse_args()
    paths = (args.training, args.signed_training, args.development, args.output)
    if any(paths) and not all(paths):
        parser.error("Provide all evaluation paths together.")
    if not (args.generate or args.output):
        parser.error("Use --generate or provide the evaluation paths.")
    if args.export_model and not args.output:
        parser.error("Export requires the evaluation inputs and report path.")
    if args.generate:
        args.directory.mkdir(parents=True, exist_ok=True)
        for name, seeds in (("calibration", RECALIBRATION_SEEDS), ("holdout", RECHECK_SEEDS)):
            generate_holdout(args.directory / f"{name}.jsonl.gz", args.workers, seeds=seeds, simulator=simulate_varied_group)
    if args.output:
        sources = {"training": args.training, "signed_training": args.signed_training, "development": args.development,
                   **{name: args.directory / f"{name}.jsonl.gz" for name in ("calibration", "holdout")}}
        data = {name: read_rows(path) for name, path in sources.items()}
        report = evaluate(*data.values(), export_path=args.export_model)
        report["splits"] = {name: {"sha256": data_digest(rows), "records": len(rows),
                                   "seeds": sorted({row["scenario"]["seed"] for row in rows})} for name, rows in data.items()}
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        if args.export_model and not report["criteria_met"]:
            raise SystemExit("The warning model missed the export criteria.")


if __name__ == "__main__":
    main()
