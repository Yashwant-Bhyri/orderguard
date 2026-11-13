"""Train and evaluate a mandate surrogate on independently seeded arena worlds."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np

from orderguard_guard import ROOT
from orderguard_arena.feeds import DEFAULT_SYMBOLS
from orderguard_arena.mandate_model import ARTIFACT, DOMAIN, FEATURES, FORMAT, METRICS, feature_vector, forest_predict, output_units
from orderguard_arena.policy_sim import REGIMES, PolicyScenario, policy_metrics, simulate_policy

EVIDENCE = ROOT / "results" / "arena" / "mandate-model-evaluation.json"
COVERAGE_TARGET = 0.90


def simulate_world(job):
    seed, regime, candidates = job
    rng = random.Random(f"orderguard-mandate-1:{seed}:{regime}")
    scenario = PolicyScenario(seed, rng.choice((50, 100, 150, 250, 400, 600, 800, 1_000)),
                              rng.choice((120, 200, 300, 400, 600, 900)), regime)
    feed = scenario.feed()

    def log_sample(field):
        low, high = DOMAIN[field]
        return round(math.exp(rng.uniform(math.log(low), math.log(high))), 2)

    rows = []
    for i in range(candidates):
        per_order = log_sample("maxOrderNotionalUsd")
        daily = max(per_order, log_sample("maxDailyNotionalUsd"))
        symbols = DEFAULT_SYMBOLS if i % 5 == 0 else rng.sample(DEFAULT_SYMBOLS, rng.randint(1, len(DEFAULT_SYMBOLS)))
        body = {"symbols": sorted(symbols), "sides": rng.choice((["buy", "sell"], ["buy", "sell"], ["buy"], ["sell"])),
                "maxOrderNotionalUsd": per_order, "maxDailyNotionalUsd": daily, "priceBandPct": log_sample("priceBandPct"),
                "stepUpAboveUsd": None if i % 4 == 0 else round(rng.uniform(0, 1) * per_order, 2)}
        m = policy_metrics(simulate_policy(body, scenario, feed=feed))
        rows.append({"scenario": asdict(scenario), "mandate": body, "digest": m["digest"], "proposals": m["proposals"],
                     "actual": {k: m[k] for k in METRICS}})
    return rows


def arrays(rows):
    scenarios = [PolicyScenario(**r["scenario"]) for r in rows]
    units = np.array([output_units(r["mandate"], s) for r, s in zip(rows, scenarios)])
    x = np.array([feature_vector(r["mandate"], s) for r, s in zip(rows, scenarios)])
    y = np.array([[r["actual"][k] for k in METRICS] for r in rows]) / units
    return x, y, units, np.array([s.seed for s in scenarios])


def export_trees(model, scales) -> list:
    trees = []
    for estimator in model.estimators_:
        t = estimator.tree_
        nodes = []
        for i in range(t.node_count):
            if t.children_left[i] < 0:
                nodes.append([np.round(t.value[i, :, 0] * scales, 9).tolist()])
            else:
                nodes.append([int(t.feature[i]), float(t.threshold[i]), int(t.children_left[i]), int(t.children_right[i])])
        trees.append(nodes)
    return trees


def conformal_widths(predicted, actual, groups, scales):
    """Calibrate simultaneous bands on the worst standardized residual for each seed."""
    scores = np.max(np.abs(predicted - actual) / scales, axis=1)
    by_seed = sorted(float(np.max(scores[groups == g])) for g in np.unique(groups))
    rank = math.ceil((len(by_seed) + 1) * COVERAGE_TARGET)
    if rank > len(by_seed):
        raise ValueError("Calibration needs at least nine independent seeds for 90% bands.")
    return (scales * by_seed[rank - 1]).tolist()


def _errors(p, y, units):
    error = np.abs(p - y)
    return {k: {"mae": round(float(np.mean(error[:, i] * units[:, i])), 6),
                "mae_normalized": round(float(np.mean(error[:, i])), 6)} for i, k in enumerate(METRICS)}


def evaluate(trees, baselines, xs, ys, units, groups, widths, rows):
    samples = []
    preds = []
    for features in xs.tolist():
        start = time.perf_counter_ns()
        preds.append(forest_predict(trees, features))
        samples.append((time.perf_counter_ns() - start) / 1e6)
    p = np.array(preds)
    inside = np.all(np.abs(p - ys) <= widths, axis=1)
    limits = np.column_stack([np.minimum(0.15, 25_000 / units[:, 0]), np.full(len(p), 0.35), np.full(len(p), 0.06)])
    risk_columns = (0, 2, 3)
    eligible = np.all((p + widths)[:, risk_columns] <= limits, axis=1)
    actually_fit = np.all(ys[:, risk_columns] <= limits, axis=1)
    point_fit = np.all(p[:, risk_columns] <= limits, axis=1)
    return {
        "errors": {"extra_trees": _errors(p, ys, units), **{k: _errors(v, ys, units) for k, v in baselines.items()}},
        "by_regime": {r: _errors(p[ix], ys[ix], units[ix]) for r in REGIMES
                      if (ix := np.array([row["scenario"]["regime"] == r for row in rows])).any()},
        "interval_coverage_rows": float(np.mean(inside)),
        "interval_coverage_seed_groups": float(np.mean([np.all(inside[groups == g]) for g in np.unique(groups)])),
        "triage_check": {"within_limits_by_point_estimate": int(point_fit.sum()), "false_safe_point_estimates": int((point_fit & ~actually_fit).sum()),
                         "within_limits_by_upper_bounds": int(eligible.sum()), "false_safe_upper_bounds": int((eligible & ~actually_fit).sum()),
                         "actual_within_limits": int(actually_fit.sum()), "rows": len(p)},
        "inference_ms": {"p50": float(np.percentile(samples, 50)), "p95": float(np.percentile(samples, 95)), "n": len(samples)},
    }


def train(args):
    from sklearn.ensemble import ExtraTreesRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    split = {"train": list(range(1_000, 1_000 + args.train_seeds)),
             "calibration": list(range(2_000, 2_000 + args.calibration_seeds)),
             "holdout": list(range(args.holdout_start, args.holdout_start + args.holdout_seeds))}
    if any(len(s) >= 1000 for s in split.values()) or min(args.train_seeds, args.holdout_seeds, args.candidates, args.workers) < 1:
        raise ValueError("Choose positive sample sizes and fewer than 1,000 seeds per split.")
    if args.calibration_seeds < 9:
        raise ValueError("Choose at least nine calibration seeds.")
    if len(set().union(*map(set, split.values()))) != sum(map(len, split.values())):
        raise ValueError("Training, calibration and holdout seeds must be disjoint.")
    data = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for name, seeds in split.items():
            jobs = [(s, r, args.candidates) for s in seeds for r in REGIMES]
            data[name] = []
            for i, rows in enumerate(pool.map(simulate_world, jobs), 1):
                data[name].extend(rows)
                if i % 20 == 0 or i == len(jobs):
                    print(f"{name}: {i}/{len(jobs)} worlds, {len(data[name])} simulated policies", flush=True)

    xt, yt, _, _ = arrays(data["train"])
    xc, yc, _, gc = arrays(data["calibration"])
    xv, yv, uv, gv = arrays(data["holdout"])
    scales = np.maximum(yt.std(axis=0), 1e-6)
    model = ExtraTreesRegressor(n_estimators=48, max_depth=9, min_samples_leaf=4, random_state=17, n_jobs=args.workers,
                                criterion=args.criterion)
    model.fit(xt, yt / scales)
    trees = export_trees(model, scales)
    pc = np.array([forest_predict(trees, x) for x in xc.tolist()])
    widths = conformal_widths(pc, yc, gc, scales)
    ridge = make_pipeline(StandardScaler(), Ridge(alpha=10)).fit(xt, yt)
    ridge_preds = np.clip(ridge.predict(xv), 0, [1, 1, 1, np.inf])
    median = np.broadcast_to(np.median(yt, axis=0), yv.shape)
    metrics = evaluate(trees, {"ridge": ridge_preds, "median": median}, xv, yv, uv, gv, widths, data["holdout"])
    e = metrics["errors"]
    target = METRICS[0]
    error = {m: e[m][target]["mae_normalized"] for m in e}
    criteria = {"harm_mae_beats_best_baseline_by_10pct": error["extra_trees"] <= 0.9 * min(error["ridge"], error["median"]),
                "joint_seed_group_coverage_at_least_80pct": metrics["interval_coverage_seed_groups"] >= 0.8,
                "p95_local_inference_below_500_ms": metrics["inference_ms"]["p95"] < 500,
                "no_observed_false_safe_with_at_least_one_eligible_draft": metrics["triage_check"]["false_safe_upper_bounds"] == 0
                and metrics["triage_check"]["within_limits_by_upper_bounds"] > 0}
    serialized = {k: json.dumps(rows, sort_keys=True, separators=(",", ":")) for k, rows in data.items()}
    provenance = {k: {"seeds": split[k], "worlds": len(split[k]) * len(REGIMES), "rows": len(data[k]),
                      "sha256": hashlib.sha256(serialized[k].encode()).hexdigest()} for k in split}
    evidence = {"format": FORMAT, "metrics": metrics, "criteria": criteria, "validated_for_triage": all(criteria.values()),
                "coverage_target": COVERAGE_TARGET, "interval_half_widths": widths, "data": provenance, "domain": DOMAIN,
                "training": {"criterion": args.criterion, "estimators": 48, "max_depth": 9, "min_samples_leaf": 4,
                             "candidates_per_world": args.candidates},
                "validation_limits": "Bad notional ≤15% of daily cap or $25,000, whichever is lower. False refusal ≤35%. Holds per day ≤6% of agent count.",
                "evaluation_scope": "Synthetic arena only. Each row is a full policy rerun. No seed is shared across splits."}
    art = {"format": FORMAT, "features": list(FEATURES), "metrics": list(METRICS), "trees": trees,
           "coverage_target": COVERAGE_TARGET, "interval_half_widths": widths, "validated_for_triage": all(criteria.values()),
           "evidence": {"holdout_worlds": provenance["holdout"]["worlds"], "holdout_rows": provenance["holdout"]["rows"],
                        "joint_seed_group_coverage": metrics["interval_coverage_seed_groups"], "criteria": criteria}}
    for path, value in ((args.out, art), (args.evidence, evidence)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":") if path == args.out else None,
                                   indent=None if path == args.out else 2) + "\n", encoding="utf-8")
    if args.dataset:
        args.dataset.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(args.dataset, "wt", encoding="utf-8") as file:
            for name, rows in data.items():
                for row in rows:
                    file.write(json.dumps({"split": name, **row}, sort_keys=True) + "\n")
    print(json.dumps({"criteria": criteria, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--train-seeds", type=int, default=36)
    p.add_argument("--calibration-seeds", type=int, default=16)
    p.add_argument("--holdout-seeds", type=int, default=20)
    p.add_argument("--holdout-start", type=int, default=3_000)
    p.add_argument("--criterion", choices=("squared_error", "absolute_error"), default="squared_error")
    p.add_argument("--candidates", type=int, default=8)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", type=Path, default=ARTIFACT)
    p.add_argument("--evidence", type=Path, default=EVIDENCE)
    p.add_argument("--dataset", type=Path)
    train(p.parse_args())
