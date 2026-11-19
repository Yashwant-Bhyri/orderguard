"""Featurise the reference corpora and print the T03 sanity numbers.

The labels and ``meta`` fields are read here, for evaluation only.  The feature
module itself never sees them: it calls ``model_view_at`` per action.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

from og_s1.checks import (
    AUTHORITY_SPOOF,
    DRIFT,
    EVIDENCE_QUALITY,
    FEATURE_NAMES,
    GROUPS,
    MISQUOTE,
    POISONED_NOTE,
    STALE_THESIS,
    UNSUPPORTED_CLAIM,
    auroc,
    featurize,
)
from og_s1.schema import Episode

CAUSE_GROUPS = (
    DRIFT,
    UNSUPPORTED_CLAIM,
    MISQUOTE,
    POISONED_NOTE,
    AUTHORITY_SPOOF,
    STALE_THESIS,
)
FAMILIES = (
    "clean",
    DRIFT,
    UNSUPPORTED_CLAIM,
    MISQUOTE,
    "vague_hype",
    POISONED_NOTE,
    AUTHORITY_SPOOF,
    STALE_THESIS,
)


def _path(data_dir: str, family: str, shifted: bool) -> str:
    suffix = ".shifted" if shifted else ""
    return os.path.join(data_dir, f"{family}{suffix}.jsonl")


def _load(path: str, limit: int | None, timings: list[float]):
    rows = []
    labels = []
    total_actions = 0
    episodes = 0
    started = time.perf_counter()
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if limit is not None and episodes >= limit:
                break
            line = line.strip()
            if not line:
                continue
            episode = Episode.from_dict(json.loads(line))
            X, names, groups = featurize(episode, timings=timings)
            rows.append(X)
            labels.extend(int(step.label.y) for step in episode.steps)
            total_actions += len(episode.steps)
            episodes += 1
    elapsed = time.perf_counter() - started
    if rows:
        X = np.vstack(rows)
    else:
        X = np.zeros((0, len(FEATURE_NAMES)), dtype=float)
    y = np.asarray(labels, dtype=float)
    return X, y, episodes, total_actions, elapsed


def _best(group: str, X: np.ndarray, y: np.ndarray):
    indices = [j for j, name in enumerate(FEATURE_NAMES) if GROUPS[name] == group]
    best_value = float("nan")
    best_name = "-"
    for j in indices:
        value = auroc(y, X[:, j])
        if np.isfinite(value) and (not np.isfinite(best_value) or value > best_value):
            best_value = value
            best_name = FEATURE_NAMES[j]
    return best_value, best_name


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/ref")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    timings: list[float] = []
    cache: dict[tuple[str, bool], tuple[np.ndarray, np.ndarray, int, int, float]] = {}

    print("== T03 code checks: reference evaluation ==")
    print(f"features: {len(FEATURE_NAMES)}")
    print(f"data_dir: {args.data_dir}")
    print(f"limit_per_file: {args.limit if args.limit is not None else 'all'}")

    for shifted in (False, True):
        for family in FAMILIES:
            path = _path(args.data_dir, family, shifted)
            X, y, episodes, actions, elapsed = _load(path, args.limit, timings)
            cache[(family, shifted)] = (X, y, episodes, actions, elapsed)

    total_actions = sum(item[3] for item in cache.values())
    total_episodes = sum(item[2] for item in cache.values())
    total_eval_elapsed = sum(item[4] for item in cache.values())
    total_featurise_elapsed = sum(timings)

    print("\n== corpus ==")
    for shifted in (False, True):
        label = "shifted" if shifted else "clean"
        episodes = sum(cache[(f, shifted)][2] for f in FAMILIES)
        actions = sum(cache[(f, shifted)][3] for f in FAMILIES)
        positives = sum(int(cache[(f, shifted)][1].sum()) for f in FAMILIES)
        print(
            f"{label}: episodes={episodes} actions={actions} positives={positives}"
        )
    total_episodes = sum(cache[(f, s)][2] for s in (False, True) for f in FAMILIES)
    total_actions = sum(cache[(f, s)][3] for s in (False, True) for f in FAMILIES)
    total_positives = sum(int(cache[(f, s)][1].sum()) for s in (False, True) for f in FAMILIES)
    print(
        f"total: episodes={total_episodes} actions={total_actions} positives={total_positives}"
    )

    print("\n== label rates ==")
    print("family,shift,episodes,actions,positives,rate")
    for shifted in (False, True):
        label = "shifted" if shifted else "clean"
        for family in FAMILIES:
            _, y, episodes, actions, _ = cache[(family, shifted)]
            positives = int(y.sum()) if y.size else 0
            rate = positives / actions if actions else float("nan")
            print(f"{family},{label},{episodes},{actions},{positives},{rate:.4f}")

    print("\n== latency per action (one CPU core, wall clock) ==")
    if timings:
        arr = np.asarray(timings, dtype=float) * 1000.0
        print(f"timed_actions: {arr.size}")
        print(f"mean_ms: {arr.mean():.4f}")
        print(f"p50_ms: {np.percentile(arr, 50):.4f}")
        print(f"p95_ms: {np.percentile(arr, 95):.4f}")
        print(f"p99_ms: {np.percentile(arr, 99):.4f}")
        print(f"max_ms: {arr.max():.4f}")
    else:
        print("timed_actions: 0")
    print(
        f"total_eval_wall_s: {total_eval_elapsed:.3f} "
        f"eval_episodes_per_s: {total_episodes / total_eval_elapsed:.2f} "
        f"eval_actions_per_s: {total_actions / total_eval_elapsed:.1f} "
        f"(load+parse+featurise)"
    )
    print(
        f"total_featurise_wall_s: {total_featurise_elapsed:.3f} "
        f"featurise_episodes_per_s: {total_episodes / total_featurise_elapsed:.2f} "
        f"featurise_actions_per_s: {total_actions / total_featurise_elapsed:.1f} "
        f"(featurize calls only, summed per-action timings)"
    )

    print("\n== best single feature per cause group (AUROC on that cause's family) ==")
    print("group,family,shift,best_feature,auroc,actions,positives")
    results: dict[tuple[str, bool], tuple[float, str]] = {}
    for group in CAUSE_GROUPS:
        for shifted in (False, True):
            X, y, _, actions, _ = cache[(group, shifted)]
            value, name = _best(group, X, y)
            results[(group, shifted)] = (value, name)
            label = "shifted" if shifted else "clean"
            print(
                f"{group},{group},{label},{name},{_fmt(value)},{actions},{int(y.sum()) if y.size else 0}"
            )

    print("\n== evidence-quality features (descriptive; no single cause family) ==")
    print("shift,best_feature,auroc,actions,positives")
    for shifted in (False, True):
        xs = []
        ys = []
        for family in FAMILIES:
            X, y, _, _, _ = cache[(family, shifted)]
            xs.append(X)
            if family == "clean":
                ys.append(np.zeros(len(y), dtype=float))
            else:
                ys.append(np.ones(len(y), dtype=float))
        X_all = np.vstack(xs)
        y_all = np.concatenate(ys)
        value, name = _best(EVIDENCE_QUALITY, X_all, y_all)
        label = "shifted" if shifted else "clean"
        print(f"{label},{name},{_fmt(value)},{len(y_all)},{int(y_all.sum())}")

    print("\n== deferred ==")
    print(
        "vague_hype: no dedicated structural cause feature; its definition is "
        "wording-based (enthusiasm without a figure), so the cause itself is "
        "left to the T05 text channel. Non-numeric claims without a source or "
        "a usable quote are still caught by unsupported_claim."
    )
    print("\n== claim-support on vague_hype (descriptive; not a pass-bar item) ==")
    print("family,shift,best_feature,auroc,actions,positives")
    for shifted in (False, True):
        X, y, _, actions, _ = cache[("vague_hype", shifted)]
        value, name = _best(UNSUPPORTED_CLAIM, X, y)
        label = "shifted" if shifted else "clean"
        print(
            f"vague_hype,{label},{name},{_fmt(value)},{actions},"
            f"{int(y.sum()) if y.size else 0}"
        )

    print("\n== pass-bar check ==")
    ok = True
    for group in CAUSE_GROUPS:
        value, _ = results[(group, True)]
        status = "PASS" if np.isfinite(value) and value >= 0.80 else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"{group}: shifted_auroc={_fmt(value)} bar=0.80 {status}")
    if timings:
        p99 = float(np.percentile(np.asarray(timings, dtype=float) * 1000.0, 99))
        latency_ok = p99 <= 5.0
        if not latency_ok:
            ok = False
        print(f"p99_ms={p99:.4f} bar=5.0 {'PASS' if latency_ok else 'FAIL'}")
    print(f"OVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
