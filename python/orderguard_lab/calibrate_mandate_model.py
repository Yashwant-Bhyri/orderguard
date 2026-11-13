"""Reproduce the mandate model's adaptive-interval experiment on synthetic worlds."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import numpy as np

from orderguard_arena.feeds import DEFAULT_SYMBOLS
from orderguard_arena.mandate_features import context_vector, scenario_inputs
from orderguard_arena.mandate_model import ARTIFACT, METRICS, forest_predict
from orderguard_arena.policy_sim import REGIMES, PolicyScenario, policy_metrics, simulate_policy

from .train_mandate_model import COVERAGE_TARGET, arrays, simulate_world

TRANSFORM_SCALE = np.array([0.05, 0.1, 1.0, 0.05])
MIN_WIDTH = np.array([0.05, 0.1, 0.06, 0.08])
RISK_COLUMNS = (0, 2, 3)
SPLITS = {
    "training": (range(1000, 1036), range(1100, 1132)),
    "calibration": (range(0), range(2200, 2240)),
    "holdout": (range(0), range(5000, 5064)),
}


def simulate_cohort(job):
    cohort, seed, regime = job
    if cohort == "wide":
        return [row | {"cohort": cohort} for row in simulate_world((seed, regime, 8))]
    rng = random.Random(f"operator-v1:{seed}:{regime}")
    scenario = PolicyScenario(seed, rng.choice((50, 100, 150, 250, 400, 600, 800, 1000)),
                              rng.choice((120, 200, 300, 400, 600, 900)), regime)
    market = scenario.feed()
    rows = []
    for i in range(6):
        order = round(math.exp(rng.uniform(math.log(4_000), math.log(24_000))), 2)
        daily = round(min(5_000_000, scenario.agents * (scenario.steps // 4) *
                          math.exp(rng.uniform(math.log(12), math.log(100)))), 2)
        band = round(rng.uniform(1, 5), 2)
        step_up = None if i % 3 == 0 else round(order * rng.uniform(0.65, 1), 2)
        mandate = {"symbols": sorted(DEFAULT_SYMBOLS), "sides": ["buy", "sell"],
                   "maxOrderNotionalUsd": order, "maxDailyNotionalUsd": max(daily, order),
                   "priceBandPct": band, "stepUpAboveUsd": step_up}
        result = policy_metrics(simulate_policy(mandate, scenario, feed=market))
        rows.append({"cohort": cohort, "scenario": asdict(scenario), "mandate": mandate,
                     "digest": result["digest"], "proposals": result["proposals"],
                     "actual": {key: result[key] for key in METRICS}})
    return rows


def read_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt") as file:
        return [json.loads(line) for line in file]


def generate_data(directory: Path, workers: int):
    directory.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for split, (wide_seeds, mixed_seeds) in SPLITS.items():
            jobs = [("wide", seed, regime) for seed in wide_seeds for regime in REGIMES]
            jobs += [(cohort, seed, regime) for seed in mixed_seeds for regime in REGIMES for cohort in ("wide", "operator")]
            path = directory / f"{split}.jsonl.gz"
            temporary = directory / f"{split}.partial.gz"
            with gzip.open(temporary, "wt") as file:
                for batch in executor.map(simulate_cohort, jobs):
                    for row in batch:
                        file.write(json.dumps(row, sort_keys=True) + "\n")
            temporary.replace(path)
            print(f"Generated {split} from {len(jobs)} scenario and cohort combinations.", flush=True)


_cached_inputs = lru_cache(maxsize=3072)(scenario_inputs)


def scenario_features(row):
    return context_vector(row["mandate"], _cached_inputs(PolicyScenario(**row["scenario"])))


def calibration_correction(scores):
    rank = math.ceil((len(scores) + 1) * COVERAGE_TARGET)
    if rank > len(scores):
        raise ValueError("Insufficient independent calibration seeds.")
    return max(0.0, float(np.sort(scores)[rank - 1]))


def interval_metrics(y, units, seeds, point, lower, upper):
    limits = np.column_stack([np.minimum(0.15, 25_000 / units[:, 0]), np.full(len(y), 0.35), np.full(len(y), 0.06)])
    meets = np.all(y[:, RISK_COLUMNS] <= limits, axis=1)
    inside = np.all((y >= lower - 1e-12) & (y <= upper + 1e-12), axis=1)
    clears = np.all(upper[:, RISK_COLUMNS] <= limits, axis=1)
    exceeds = np.any(lower[:, RISK_COLUMNS] > limits, axis=1)
    return {"rows": len(y), "joint_row_coverage": float(inside.mean()),
            "joint_seed_coverage": float(np.mean([np.all(inside[seeds == s]) for s in np.unique(seeds)])),
            "actually_meet": int(meets.sum()), "clear": int(clears.sum()), "false_clear": int((clears & ~meets).sum()),
            "flagged": int(exceeds.sum()), "false_flagged": int((exceeds & meets).sum()),
            "mean_normalized_width": (upper - lower).mean(axis=0).tolist(),
            "normalized_mae": np.abs(y - point).mean(axis=0).tolist()}


def run_experiment(data):
    from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor

    base = {split: arrays(rows) for split, rows in data.items()}
    x = {split: np.column_stack([base[split][0], [scenario_features(r) for r in rows]]) for split, rows in data.items()}
    xt, yt, _, _ = base["training"]
    _, yc, _, gc = base["calibration"]
    xv, yv, uv, gv = base["holdout"]
    regimes_c = np.array([r["scenario"]["regime"] for r in data["calibration"]])
    regimes_v = np.array([r["scenario"]["regime"] for r in data["holdout"]])
    cohorts = np.array([r["cohort"] for r in data["holdout"]])
    zt, zc = np.log1p(yt / TRANSFORM_SCALE), np.log1p(yc / TRANSFORM_SCALE)
    predictions = {split: [] for split in ("calibration", "holdout")}
    for alpha in (0.05, 0.5, 0.95):
        models = [GradientBoostingRegressor(loss="quantile", alpha=alpha, n_estimators=110, max_depth=3,
                                            min_samples_leaf=18, learning_rate=0.07, random_state=41).fit(x["training"], target)
                  for target in zt.T]
        for split, estimates in predictions.items():
            estimates.append(np.column_stack([model.predict(x[split]) for model in models]))
    lo_c, _, hi_c = np.sort(predictions["calibration"], axis=0)
    lo_v, middle, hi_v = np.sort(predictions["holdout"], axis=0)

    def inverse(transformed):
        return np.clip(np.expm1(transformed) * TRANSFORM_SCALE, 0, [1, 1, 1, np.inf])

    results = {}
    for method in ("additive", "adaptive"):
        scale_c = np.maximum(hi_c - lo_c, MIN_WIDTH) if method == "adaptive" else np.ones_like(lo_c)
        scale_v = np.maximum(hi_v - lo_v, MIN_WIDTH) if method == "adaptive" else np.ones_like(lo_v)
        scores = np.max(np.maximum(lo_c - zc, zc - hi_c) / scale_c, axis=1)
        lower, upper, corrections = lo_v.copy(), hi_v.copy(), {}
        for regime in REGIMES:
            calibration, holdout = regimes_c == regime, regimes_v == regime
            delta = calibration_correction([scores[calibration & (gc == seed)].max() for seed in np.unique(gc[calibration])])
            lower[holdout] -= delta * scale_v[holdout]
            upper[holdout] += delta * scale_v[holdout]
            corrections[regime] = delta
        slices = {"all": np.ones(len(yv), dtype=bool)} | {k: cohorts == k for k in np.unique(cohorts)}
        slices.update({regime: regimes_v == regime for regime in REGIMES})
        results[method] = {"corrections": corrections, "by_slice": {
            k: interval_metrics(yv[m], uv[m], gv[m], inverse(middle[m]), inverse(lower[m]), inverse(upper[m]))
            for k, m in slices.items()}}

    scales = np.maximum(yt.std(axis=0), 1e-6)
    old_trees = json.loads(ARTIFACT.read_text(encoding="utf-8"))["trees"]
    estimates = {"existing_extra_trees": np.array([forest_predict(old_trees, r) for r in xv.tolist()])}
    for name, train_x, holdout_x in (("wide_features", xt, xv), ("scenario_features", x["training"], x["holdout"])):
        model = ExtraTreesRegressor(n_estimators=48, max_depth=9, min_samples_leaf=4, criterion="absolute_error",
                                    n_jobs=2, random_state=17).fit(train_x, yt / scales)
        estimates[name] = model.predict(holdout_x) * scales
    results["point_model_normalized_mae"] = {name: np.abs(pred - yv).mean(axis=0).tolist() for name, pred in estimates.items()}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory for the generated data splits")
    parser.add_argument("--generate", action="store_true", help="generate the documented seed splits before evaluation")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.generate:
        generate_data(args.directory, args.workers)
    rows = {split: read_rows(args.directory / f"{split}.jsonl.gz") for split in SPLITS}
    evidence = {"metrics_order": METRICS, "coverage_target_per_regime": COVERAGE_TARGET,
                "splits": {split: {"rows": len(data), "seeds": sorted({row["scenario"]["seed"] for row in data}),
                                   "sha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()}
                           for split, data in rows.items()}}
    for split, (wide, mixed) in SPLITS.items():
        expected_rows = len(REGIMES) * (8 * len(wide) + 14 * len(mixed))
        if evidence["splits"][split]["seeds"] != sorted([*wide, *mixed]) or len(rows[split]) != expected_rows:
            raise ValueError(f"The {split} data do not match the documented seed split and sample size.")
    evidence.update(run_experiment(rows))
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
