"""Check the frozen warning model on varied signed policies and operator limits."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np

from orderguard_arena.envelopes import owner_key_from_seed
from orderguard_arena.feeds import DEFAULT_SYMBOLS
from orderguard_arena.mandate_features import context_vector, scenario_inputs
from orderguard_arena.mandate_model import METRICS, feature_vector, forest_predict, load_model, outside_domain, output_units
from orderguard_arena.policy_sim import PolicyScenario
from orderguard_guard.gate import Mandate, sign_mandate

from .calibrate_mandate_model import RISK_COLUMNS, read_rows, scenario_features
from .evaluate_selective_mandate import (BASELINE, CALIBRATION_SEEDS, CONFIRMATION_SEEDS, HOLDOUT_SEEDS, MAX_P95_MS, MAX_SEED_ERROR,
                                        MIN_CORRECT_SHARE, calibrate, check_groups, context_forecast, direction_report,
                                        fit_context_regressors, paired_coverage_gain, training_rows)
from .evaluate_signed_policy_ranking import LIMIT_PROFILES, PROFILES, SEEDS, generate_holdout, signed_fixture, simulate_parent_group
from .train_mandate_model import arrays

VARIED_SEEDS = tuple(random.Random(849227).sample(range(10_000, 2**32), 96))
SYMBOL_COUNTS = {"starter": (1, 3), "portfolio": (3, 9), "demo": (8, len(DEFAULT_SYMBOLS))}
REGRESSION = "context_regression"
WARNING = "likely_exceeds_limits"
RISK_METRICS = tuple(METRICS[i] for i in RISK_COLUMNS)


def varied_parent(profile, seed):
    rng = random.Random(f"varied-mandate-1:{profile}:{seed}")
    base, _, _ = signed_fixture(profile)
    body = Mandate.from_dict(base).to_dict(with_signature=False)
    symbols = sorted(rng.sample(DEFAULT_SYMBOLS, rng.randint(*SYMBOL_COUNTS[profile])))
    order = round(body["maxOrderNotionalUsd"] * rng.uniform(0.55, 1.65), 2)
    daily = round(max(order, body["maxDailyNotionalUsd"] * rng.uniform(0.5, 1.75)), 2)
    approval = rng.choices(["threshold", "none", "all"], weights=[75, 20, 5])[0]
    step_up = {"threshold": round(order * rng.uniform(0.25, 0.95), 2), "none": None, "all": 0}[approval]
    sides = list(rng.choices([("buy", "sell"), ("buy",), ("sell",)], weights=[70, 20, 10])[0])
    body.update(symbols=symbols, sides=sides, maxOrderNotionalUsd=order, maxDailyNotionalUsd=daily,
                priceBandPct=round(body["priceBandPct"] * rng.uniform(0.4, 1.5), 6), stepUpAboveUsd=step_up,
                referencePrices={symbol: price for symbol, price in body.get("referencePrices", {}).items() if symbol in symbols})
    key = owner_key_from_seed(f"varied-mandate-study:{profile}:{seed}")
    return sign_mandate(body, key), key.public_key(), ()


def operator_limits(parent, scenario, profile):
    rng = random.Random(f"varied-operator-1:{scenario.seed}:{profile}")
    limits = {}
    for level, (relative, absolute, refusal, holds) in LIMIT_PROFILES.items():
        limits[level] = {"bad_allowed_usd_per_day": round(min(relative * parent["maxDailyNotionalUsd"], absolute) * rng.uniform(0.55, 1.55), 2),
                         "false_refusal_rate": round(min(1, refusal * rng.uniform(0.55, 1.55)), 6),
                         "holds_per_day": round(holds * scenario.agents * rng.uniform(0.55, 1.55), 4)}
    sparse = dict(limits["balanced"])
    del sparse[rng.choice(tuple(sparse))]
    limits["partial"] = sparse
    zero = dict(limits["strict"])
    zero[rng.choice(tuple(zero))] = 0
    limits["zero"] = zero
    return limits


def simulate_varied_group(job):
    profile, seed, regime = job
    rng = random.Random(f"varied-scenario-1:{profile}:{seed}:{regime}")
    scenario = PolicyScenario(seed, rng.randint(min(PROFILES[profile]), max(PROFILES[profile])), rng.randint(120, 900), regime)
    parent, key, revoked = varied_parent(profile, seed)
    group = simulate_parent_group(profile, scenario, parent, key, revoked)
    return group | {"operator_limits": operator_limits(parent, scenario, profile)}


def risk_thresholds(group, scenario):
    if "operator_limits" in group:
        return group["operator_limits"]
    return {level: dict(zip(RISK_METRICS, (min(relative * group["parent_daily_cap"], absolute), refusal, holds * scenario.agents)))
            for level, (relative, absolute, refusal, holds) in LIMIT_PROFILES.items()}


def measure(groups, regressors):
    trees = load_model()["trees"]
    evidence, timings, outside_fields, mistakes = [], [], Counter(), []
    for group in groups:
        scenario = PolicyScenario(**group["scenario"])
        candidates = group["candidates"]
        drafts = [c["draft"] for c in candidates]
        actual = np.array([[c["actual"][key] for key in RISK_METRICS] for c in candidates])
        start = time.perf_counter_ns()
        base = [feature_vector(draft, scenario) for draft in drafts]
        world = scenario_inputs(scenario)
        features = np.array([row + context_vector(draft, world) for row, draft in zip(base, drafts)])
        units = np.array([output_units(draft, scenario) for draft in drafts])[:, RISK_COLUMNS]
        outside = [outside_domain(draft, scenario) for draft in drafts]
        context = context_forecast(regressors, features)[:, RISK_COLUMNS] * units
        inference_ns = time.perf_counter_ns() - start
        point = np.array([forest_predict(trees, row) for row in base])[:, RISK_COLUMNS] * units
        outside_fields.update(field for fields in outside for field in fields)
        for level, limits in risk_thresholds(group, scenario).items():
            start = time.perf_counter_ns()
            threshold = np.array([limits.get(name, np.inf) for name in RISK_METRICS])
            denominator = np.where(threshold > 0, threshold, np.inf)
            context_ratio = context / denominator
            context_score = np.log(np.maximum(np.max(context_ratio, axis=1), 1e-12))
            driver = np.argmax(context_ratio, axis=1)
            timings.append((inference_ns + time.perf_counter_ns() - start) / 1e6)
            point_score = np.log(np.maximum(np.max(point / denominator, axis=1), 1e-12))
            exceeds = actual > threshold
            for i, candidate in enumerate(candidates):
                draft = candidate["draft"]
                evidence.append((scenario.seed, scenario.regime, group["profile"], level, not exceeds[i].any(), not outside[i],
                                 ",".join(draft["sides"]), draft.get("stepUpAboveUsd") == 0,
                                 RISK_METRICS[driver[i]], bool(exceeds[i, driver[i]]), context_score[i], point_score[i]))
                mistakes.append({"seed": scenario.seed, "regime": scenario.regime, "profile": group["profile"], "limits_kind": level,
                                 "draft": candidate["name"], "symbols": draft["symbols"], "sides": draft["sides"], "limits": limits,
                                 "actual": dict(zip(RISK_METRICS, actual[i].tolist())), "estimated": dict(zip(RISK_METRICS, context[i].tolist()))})
    dtype = [("seed", "i8"), ("regime", "U10"), ("profile", "U10"), ("limits", "U10"), ("qualifies", "?"),
             ("inside_domain", "?"), ("sides", "U10"), ("all_require_approval", "?"), ("driver", "U32"),
             ("driver_correct", "?"), (REGRESSION, "f8"), (BASELINE, "f8")]
    return np.array(evidence, dtype=dtype), timings, outside_fields, mistakes


def data_digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def evaluate(original, signed, calibration, holdout, frozen):
    import sklearn

    check_groups(signed, SEEDS)
    check_groups(calibration, CALIBRATION_SEEDS)
    check_groups(holdout, VARIED_SEEDS)
    if len({g["parent_id"] for g in holdout}) != len(PROFILES) * len(VARIED_SEEDS):
        raise ValueError("The varied holdout must have a distinct signed parent per seed and profile.")
    protected = {*SEEDS, *CALIBRATION_SEEDS, *HOLDOUT_SEEDS, *CONFIRMATION_SEEDS, *(r["scenario"]["seed"] for r in original)}
    if protected.intersection(VARIED_SEEDS):
        raise ValueError("The varied holdout overlaps a prior seed split.")
    if frozen.get("calibration_rule") != "nonparametric_tolerance_95" or frozen["software"]["scikit_learn"] != sklearn.__version__:
        raise ValueError("Rebuild the frozen confirmation with the documented scikit-learn version first.")
    for name, data in (("training", original), ("signed_training", signed), ("calibration", calibration)):
        if data_digest(data) != frozen["splits"][name]["sha256"]:
            raise ValueError(f"The {name} data differ from the frozen confirmation.")

    training = training_rows(original, signed)
    base, outcomes, _, _ = arrays(training)
    features = np.column_stack([base, [scenario_features(row) for row in training]])
    regressors = fit_context_regressors(features, outcomes)
    cal, _, _, _ = measure(calibration, regressors)
    thresholds = {method: frozen["thresholds"][method][WARNING] for method in (REGRESSION, BASELINE)}
    for method, threshold in thresholds.items():
        measured_threshold = calibrate(cal[method], ~cal["qualifies"], cal["seed"], tolerance=True)
        if not math.isclose(measured_threshold, threshold, rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"The reproduced {method} threshold differs from the frozen confirmation.")

    test, timings, outside_fields, examples = measure(holdout, regressors)
    labels = ~test["qualifies"]
    warnings = {method: (test[method] > threshold) & test["inside_domain"] for method, threshold in thresholds.items()}
    primary = warnings[REGRESSION]
    errors = np.flatnonzero(primary & ~labels)
    errors = sorted(errors, key=lambda i: -test[REGRESSION][i])
    p95 = float(np.percentile(timings, 95))
    gain = paired_coverage_gain(test, primary, warnings[BASELINE], WARNING)
    overall = {method: direction_report(test, given, labels) for method, given in warnings.items()}
    main = overall[REGRESSION]
    criteria = main["error_seed_rate_upper_95"] <= MAX_SEED_ERROR and main["correct_share_of_actual"] >= MIN_CORRECT_SHARE
    criteria = criteria and gain["bootstrap_95"][0] > 0 and p95 < MAX_P95_MS
    slices = {}
    for field in ("profile", "regime", "limits", "sides", "all_require_approval"):
        slices[field] = {}
        for value in np.unique(test[field]):
            mask = test[field] == value
            slices[field][str(value)] = {method: direction_report(test[mask], given[mask], labels[mask])
                                         for method, given in warnings.items()}
    return {"criteria_met": bool(criteria), "thresholds": thresholds, "p95_ms_eight_drafts_including_features": p95,
            "criteria": {"max_error_seed_rate_upper_95": MAX_SEED_ERROR, "minimum_correct_share": MIN_CORRECT_SHARE,
                         "positive_seed_bootstrap_gain_over_baseline": True, "max_p95_ms": MAX_P95_MS},
            "overall": overall, "slices": slices, "paired_gain_over_baseline": gain,
            "rows": len(test), "outside_domain_rows": int((~test["inside_domain"]).sum()),
            "outside_domain_drafts_by_field": dict(outside_fields),
            "signed_parents": len({g["parent_id"] for g in holdout}), "seeds": sorted(VARIED_SEEDS),
            "actual_draft_runs": sum(len(g["candidates"]) for g in holdout),
            "warning_driver_violated": int((primary & test["driver_correct"]).sum()),
            "warnings_by_driver": dict(Counter(test["driver"][primary].tolist())),
            "false_warning_examples": [examples[i] for i in errors[:12]], "holdout_sha256": data_digest(holdout)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("holdout", type=Path)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--training", type=Path)
    parser.add_argument("--signed-training", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--frozen-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evaluation_paths = (args.training, args.signed_training, args.calibration, args.frozen_report, args.output)
    if any(evaluation_paths) and not all(evaluation_paths):
        parser.error("Provide all evaluation paths together.")
    if not (args.generate or args.output):
        parser.error("Use --generate or provide the evaluation paths.")
    if args.generate:
        generate_holdout(args.holdout, args.workers, seeds=VARIED_SEEDS, simulator=simulate_varied_group)
    if args.output:
        data = [read_rows(path) for path in (args.training, args.signed_training, args.calibration, args.holdout)]
        frozen = json.loads(args.frozen_report.read_text(encoding="utf-8"))
        report = evaluate(*data, frozen)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
