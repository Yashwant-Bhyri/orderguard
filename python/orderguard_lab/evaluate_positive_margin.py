"""Select a conservative positive forecast on past cases and confirm it on fresh worlds."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache, partial
from pathlib import Path

import numpy as np

from orderguard_arena.mandate_positive import FORMAT, POSITIVE_FEATURES, apply_headroom, forecast_scores
from orderguard_arena.mandate_warning import ARTIFACT as WARNING_ARTIFACT

from .calibrate_mandate_model import read_rows
from .evaluate_positive_mandate import (BASELINE, FACTORED, fit, forecast_mistakes, prepare_batches, prepare_group,
                                        predict, usefully_qualifies)
from .evaluate_selective_mandate import (MAX_P95_MS, MAX_SEED_ERROR, MIN_CORRECT_SHARE, calibrate, check_groups,
                                        direction_report, paired_coverage_gain)
from .evaluate_signed_policy_ranking import generate_holdout
from .evaluate_varied_policy_warnings import data_digest, simulate_varied_group
from .recalibrate_varied_policy_warnings import export_regressor

HOLDOUT_SEEDS = tuple(random.Random(47302813).sample(range(10_000, 2**32), 160))
CUTOFF_HOLDOUT_SEEDS = tuple(random.Random(11377817).sample(range(10_000, 2**32), 192))
HEADROOM = ((0, 0), (0.025, 0.06), (0.05, 0.10), (0.075, 0.15), (0.10, 0.20), (0.15, 0.25))
SELECTED = "selected"
PREVIOUS = "previous_operating_point"
TIGHTER = "stricter_cutoff_only"


def dataset_identity(groups):
    return {"sha256": data_digest(groups), "records": len(groups),
            "seeds": sorted({group["scenario"]["seed"] for group in groups})}


def write_json(path, data, *, compact=False):
    encoded = json.dumps(data, separators=(",", ":") if compact else None, indent=None if compact else 2,
                         sort_keys=True, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        output.write(encoded)
        temporary = Path(output.name)
    temporary.chmod(0o644)
    temporary.replace(path)


def combine(batches):
    return tuple(np.concatenate([getattr(batch, name) for batch in batches])
                 for name in ("features", "limits", "active", "rows", "warned"))


def freeze_model(directory, training, calibration, tuning, previous, workers):
    splits = {name: dataset_identity(groups) for name, groups in
              (("training", training), ("calibration", calibration), ("holdout", tuning))}
    if splits != previous["splits"] or hashlib.sha256(WARNING_ARTIFACT.read_bytes()).hexdigest() != previous["warning_artifact_sha256"]:
        raise ValueError("Model selection needs the exact datasets and warning artifact from the prior experiment.")
    if any(set(split["seeds"]).intersection(HOLDOUT_SEEDS) for split in splits.values()):
        raise ValueError("Fresh test seeds must be disjoint from all development seeds.")
    print("Reproducing the prior per-limit classifiers.", flush=True)
    models = fit(prepare_batches(training, True, workers), include_joint=False)
    cal_batches = prepare_batches(calibration, True, workers, enforce_warning=True)
    tuning_batches = prepare_batches(tuning, True, workers, enforce_warning=True)
    cal = combine(cal_batches)
    tune = combine(tuning_batches)
    cal_rows, tune_rows = cal[3], tune[3]
    cal_target, tune_target = usefully_qualifies(cal_rows), usefully_qualifies(tune_rows)

    def scores(data, headroom):
        features, limits, active, rows, warned = data
        raw = predict(models, features, apply_headroom(limits, active, headroom), active, FACTORED)
        return np.where(rows["eligible"] & ~warned, raw, -np.inf)

    cal_scores = scores(cal, HEADROOM[0])
    old = calibrate(cal_scores, cal_target, cal_rows["seed"], tolerance=True)
    np.testing.assert_allclose(old, previous["thresholds"][FACTORED], rtol=0, atol=1e-12)
    unchanged = direction_report(tune_rows, scores(tune, HEADROOM[0]) > old, tune_target)
    for name in ("correct", "errors", "seeds_with_errors", "seeds_with_forecasts"):
        if unchanged[name] != previous["overall"][FACTORED][name]:
            raise ValueError("The reproduced model did not match the prior tuning-world forecasts.")

    print("Selecting headroom and confidence from prior cases.", flush=True)
    options = []
    for headroom in HEADROOM:
        cal_scores, tune_scores = scores(cal, headroom), scores(tune, headroom)
        # Retain the previous confidence requirement and defer at all observed mistakes in development.
        cutoff = float(max(old, cal_scores[~cal_target].max(), tune_scores[~tune_target].max()) + 1e-12)
        measured = direction_report(tune_rows, tune_scores > cutoff, tune_target)
        options.append({"headroom": headroom, "cutoff": cutoff, "tuning": measured})
    chosen = max(options, key=lambda option: (option["tuning"]["correct"], option["tuning"]["seeds_with_forecasts"]))
    _, classifiers, fill = models
    artifact = {"format": FORMAT, "features": list(POSITIVE_FEATURES), "limits": [export_regressor(model) for model in classifiers],
                "fill": export_regressor(fill), "headroom": chosen["headroom"], "cutoff": chosen["cutoff"],
                "warning_sha256": previous["warning_artifact_sha256"]}
    # Check the portable scorer on both the original and tightened ceilings before freezing it.
    for batch in [*cal_batches[::19], *tuning_batches[::23]]:
        for headroom in (HEADROOM[0], chosen["headroom"]):
            limits = apply_headroom(batch.limits, batch.active, headroom)
            expected = predict(models, batch.features, limits, batch.active, FACTORED)
            portable = forecast_scores(artifact, batch.features, limits, batch.active)
            np.testing.assert_allclose(portable, expected, rtol=0, atol=2e-15)
            np.testing.assert_array_equal(portable > chosen["cutoff"], expected > chosen["cutoff"])
    frozen = {"artifact": artifact, "selected": chosen, "candidates": options, "development_splits": splits,
              "previous_cutoff": old, "point_cutoff": previous["thresholds"][BASELINE]}
    write_json(directory / "frozen.json", frozen, compact=True)
    print(json.dumps({"selected": chosen, "candidates": options}, indent=2), flush=True)


@lru_cache(maxsize=1)
def load_frozen(path):
    return json.loads(path.read_text(encoding="utf-8"))


def selected_artifact(frozen, cutoff_only):
    artifact = frozen["artifact"]
    if cutoff_only:
        return artifact | {"headroom": HEADROOM[0], "cutoff": frozen["candidates"][0]["cutoff"]}
    return artifact


def measure_group(group, frozen_path, cutoff_only):
    frozen = load_frozen(frozen_path)
    artifact = selected_artifact(frozen, cutoff_only)
    batch = prepare_group(group, include_runaway=True, enforce_warning=True)
    eligible = batch.rows["eligible"] & ~batch.warned
    limits = apply_headroom(batch.limits, batch.active, artifact["headroom"])
    parts = []
    timing = 0.0
    for start in range(0, len(batch.rows), 8):
        end = start + 8
        tick = time.perf_counter_ns()
        parts.append(forecast_scores(artifact, batch.features[start:end], limits[start:end], batch.active[start:end]))
        if start == 0:
            timing = batch.feature_ms + (time.perf_counter_ns() - tick) / 1e6
    selected = np.concatenate(parts)
    old = forecast_scores(artifact, batch.features, batch.limits, batch.active) if any(artifact["headroom"]) else selected
    scores = {SELECTED: selected, PREVIOUS: old, TIGHTER: old, BASELINE: batch.baseline}
    return batch.rows, {name: np.where(eligible, score, -np.inf) for name, score in scores.items()}, timing


def confirm(directory, output, publish, workers, *, cutoff_only):
    frozen_path = directory / "frozen.json"
    frozen = load_frozen(frozen_path)
    artifact = selected_artifact(frozen, cutoff_only)
    if hashlib.sha256(WARNING_ARTIFACT.read_bytes()).hexdigest() != artifact["warning_sha256"]:
        raise ValueError("The deployed warning artifact changed after model selection.")
    holdout_name, seeds = ("cutoff-holdout.jsonl.gz", CUTOFF_HOLDOUT_SEEDS) if cutoff_only else ("holdout.jsonl.gz", HOLDOUT_SEEDS)
    groups = read_rows(directory / holdout_name)
    check_groups(groups, seeds)
    identity = dataset_identity(groups)
    prior_seeds = set(HOLDOUT_SEEDS) if cutoff_only else set()
    for split in frozen["development_splits"].values():
        prior_seeds.update(split["seeds"])
    if prior_seeds.intersection(identity["seeds"]):
        raise ValueError("The final holdout must be disjoint from development.")
    print("Scoring the untouched holdout with the frozen portable model.", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        evaluate_group = partial(measure_group, frozen_path=frozen_path, cutoff_only=cutoff_only)
        groups_measured = list(pool.map(evaluate_group, groups, chunksize=12))
    rows = np.concatenate([item[0] for item in groups_measured])
    thresholds = {SELECTED: artifact["cutoff"], PREVIOUS: frozen["previous_cutoff"],
                  TIGHTER: frozen["candidates"][0]["cutoff"], BASELINE: frozen["point_cutoff"]}
    scores = {name: np.concatenate([item[1][name] for item in groups_measured]) for name in thresholds}
    forecasts = {name: score > thresholds[name] for name, score in scores.items()}
    target = usefully_qualifies(rows)
    overall = {name: direction_report(rows, prediction, target) for name, prediction in forecasts.items()}
    selected = overall[SELECTED]
    conditional = selected["error_seed_rate_given_forecast_upper_95"]
    timing = float(np.percentile([item[2] for item in groups_measured], 95))
    gain = paired_coverage_gain(rows, forecasts[SELECTED], forecasts[BASELINE], "likely_within_limits")
    criteria = {"correct_coverage_at_least_20_pct": selected["correct_share_of_actual"] >= MIN_CORRECT_SHARE,
                "seed_error_upper_at_most_5_pct": selected["error_seed_rate_upper_95"] <= MAX_SEED_ERROR,
                "predicting_seed_error_upper_at_most_5_pct": conditional is not None and conditional <= MAX_SEED_ERROR,
                "paired_improvement_over_current_forecast": gain["bootstrap_95"][0] > 0,
                "p95_below_500_ms": timing < MAX_P95_MS}
    report = {"development_splits": frozen["development_splits"], "holdout": identity, "cutoff_only": cutoff_only,
              "holdout_rows": len(rows), "selected_headroom": artifact["headroom"], "thresholds": thresholds,
              "development_options": frozen["candidates"], "warning_sha256": artifact["warning_sha256"],
              "overall": overall, "p95_ms_eight_drafts_including_features": timing, "paired_gain_over_baseline": gain,
              "selected_mistakes": forecast_mistakes(rows, scores[SELECTED], forecasts[SELECTED] & ~target, groups),
              "criteria": criteria, "criteria_met": all(criteria.values())}
    write_json(output, report)
    if publish:
        if not report["criteria_met"]:
            raise SystemExit("The model missed the publication criteria.")
        write_json(publish, artifact | {"validated": True, "holdout_sha256": identity["sha256"]}, compact=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--workers", type=int, default=7)
    parser.add_argument("--training", nargs="+", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--tuning", type=Path)
    parser.add_argument("--previous-report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--publish-model", type=Path)
    parser.add_argument("--cutoff-only", action="store_true", help="confirm the frozen stricter cutoff on a second untouched holdout")
    args = parser.parse_args()
    inputs = (args.training, args.calibration, args.tuning, args.previous_report)
    if args.workers < 1 or (any(inputs) and not all(inputs)) or (args.publish_model and not args.output):
        parser.error("Provide all model-selection inputs together, at least one worker, and a report path for publication.")
    if not (args.generate or args.training or args.output):
        parser.error("Use --generate, provide model-selection inputs, or set --output to evaluate a frozen model.")
    args.directory.mkdir(parents=True, exist_ok=True)
    if args.training:
        training = [group for path in args.training for group in read_rows(path)]
        freeze_model(args.directory, training, read_rows(args.calibration), read_rows(args.tuning),
                     json.loads(args.previous_report.read_text()), args.workers)
    if args.generate:
        name, seeds = ("cutoff-holdout.jsonl.gz", CUTOFF_HOLDOUT_SEEDS) if args.cutoff_only else ("holdout.jsonl.gz", HOLDOUT_SEEDS)
        generate_holdout(args.directory / name, args.workers, seeds=seeds, simulator=simulate_varied_group)
    if args.output:
        confirm(args.directory, args.output, args.publish_model, args.workers, cutoff_only=args.cutoff_only)


if __name__ == "__main__":
    main()
