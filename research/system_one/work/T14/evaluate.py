"""Evaluate the T14 taint features, gate and single-root-source cap on data/ref.

Labels are read only after ``analyze_taint`` has consumed the causal view.  The
feature module itself never sees labels or ``meta``.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from og_s1.schema import Episode
from og_s1.taint import DEFAULT_CONFIG, TAINT_FEATURES, analyze_taint

FAMILIES = (
    "clean",
    "drift",
    "unsupported_claim",
    "misquote",
    "vague_hype",
    "poisoned_note",
    "authority_spoof",
    "stale_thesis",
)


def _path(data_dir: str, family: str, shifted: bool) -> str:
    suffix = ".shifted" if shifted else ""
    return os.path.join(data_dir, f"{family}{suffix}.jsonl")


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.4f}"


def _load(path: str, limit: int | None, config: dict | None = None):
    xs: list[np.ndarray] = []
    labels: list[int] = []
    holds: list[bool] = []
    cap_flags: list[bool] = []
    actions = 0
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
            result = analyze_taint(episode, config=config)
            xs.append(result.X)
            holds.extend(result.gate_holds)
            cap_flags.extend(bool(detail["flagged"]) for detail in result.root_flags)
            labels.extend(int(step.label.y) for step in episode.steps)
            actions += len(episode.steps)
            episodes += 1
    elapsed = time.perf_counter() - started
    X = np.vstack(xs) if xs else np.zeros((0, len(TAINT_FEATURES)), dtype=float)
    return X, np.asarray(labels, dtype=int), np.asarray(holds, dtype=bool), np.asarray(cap_flags, dtype=bool), episodes, actions, elapsed


def _stats(values: np.ndarray) -> tuple[float, float, float, float, float]:
    if values.size == 0:
        return (float("nan"),) * 5
    return (
        float(values.mean()),
        float(np.percentile(values, 50)),
        float(np.percentile(values, 90)),
        float(np.percentile(values, 99)),
        float(np.mean(values > 0.0)),
    )


def _recall(flags: np.ndarray, y: np.ndarray) -> float:
    positives = int((y == 1).sum())
    if positives == 0:
        return float("nan")
    return float(flags[y == 1].mean())


def _false_positive_rate(flags: np.ndarray, y: np.ndarray) -> float:
    negatives = int((y == 0).sum())
    if negatives == 0:
        return float("nan")
    return float(flags[y == 0].mean())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/ref")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    cache: dict[tuple[str, bool], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, int, float]] = {}

    print("== T14 taint propagation: reference evaluation ==")
    print(f"features: {len(TAINT_FEATURES)} ({', '.join(TAINT_FEATURES)})")
    print(f"data_dir: {args.data_dir}")
    print(f"limit_per_file: {args.limit if args.limit is not None else 'all'}")
    print("config:")
    for key in sorted(DEFAULT_CONFIG):
        print(f"  {key}={DEFAULT_CONFIG[key]}")

    for shifted in (False, True):
        for family in FAMILIES:
            cache[(family, shifted)] = _load(
                _path(args.data_dir, family, shifted), args.limit
            )

    print("\n== corpus ==")
    for shifted in (False, True):
        label = "shifted" if shifted else "clean"
        episodes = sum(cache[(f, shifted)][4] for f in FAMILIES)
        actions = sum(cache[(f, shifted)][5] for f in FAMILIES)
        positives = sum(int(cache[(f, shifted)][1].sum()) for f in FAMILIES)
        print(f"{label}: episodes={episodes} actions={actions} positives={positives}")
    total_episodes = sum(cache[(f, s)][4] for s in (False, True) for f in FAMILIES)
    total_actions = sum(cache[(f, s)][5] for s in (False, True) for f in FAMILIES)
    total_positives = sum(int(cache[(f, s)][1].sum()) for s in (False, True) for f in FAMILIES)
    print(
        f"total: episodes={total_episodes} actions={total_actions} "
        f"positives={total_positives}"
    )

    print("\n== feature distribution per cause family ==")
    print("family,shift,feature,mean,p50,p90,p99,share_nonzero")
    for shifted in (False, True):
        label = "shifted" if shifted else "clean"
        for family in FAMILIES:
            X = cache[(family, shifted)][0]
            for j, name in enumerate(TAINT_FEATURES):
                mean, p50, p90, p99, share = _stats(X[:, j])
                print(
                    f"{family},{label},{name},{_fmt(mean)},{_fmt(p50)},"
                    f"{_fmt(p90)},{_fmt(p99)},{_fmt(share)}"
                )

    print("\n== gate ==")
    print("family,shift,actions,positives,holds,hold_rate,recall")
    gate_rows: dict[tuple[str, bool], tuple[int, int, int, float]] = {}
    for shifted in (False, True):
        label = "shifted" if shifted else "clean"
        for family in FAMILIES:
            _, y, holds, _, _, actions, _ = cache[(family, shifted)]
            positives = int(y.sum())
            hold_rate = float(holds.mean()) if holds.size else float("nan")
            recall = _recall(holds, y)
            gate_rows[(family, shifted)] = (actions, positives, int(holds.sum()), hold_rate)
            print(
                f"{family},{label},{actions},{positives},{int(holds.sum())},"
                f"{_fmt(hold_rate)},{_fmt(recall)}"
            )

    print("\n== single-root-source cap ==")
    print(
        "family,shift,actions,flags,flag_rate,false_positive_rate,"
        "negatives,recall,positives"
    )
    for shifted in (False, True):
        label = "shifted" if shifted else "clean"
        for family in FAMILIES:
            _, y, _, cap_flags, _, actions, _ = cache[(family, shifted)]
            print(
                f"{family},{label},{actions},{int(cap_flags.sum())},"
                f"{_fmt(float(cap_flags.mean()) if actions else float('nan'))},"
                f"{_fmt(_false_positive_rate(cap_flags, y))},"
                f"{int((y == 0).sum())},{_fmt(_recall(cap_flags, y))},"
                f"{int((y == 1).sum())}"
            )

    print("\n== single-root-source cap: all-root default vs untrusted-only ==")
    print("family,shift,actions,all_root_flags,all_root_rate,untrusted_flags,untrusted_rate")
    for shifted in (False, True):
        label = "shifted" if shifted else "clean"
        for family in ("clean", "drift"):
            _, _, _, all_flags, _, actions, _ = cache[(family, shifted)]
            narrow = _load(
                _path(args.data_dir, family, shifted),
                args.limit,
                {"root_cap_include_trusted": False},
            )
            narrow_flags = narrow[3]
            print(
                f"{family},{label},{actions},{int(all_flags.sum())},"
                f"{_fmt(float(all_flags.mean()) if actions else float('nan'))},"
                f"{int(narrow_flags.sum())},"
                f"{_fmt(float(narrow_flags.mean()) if actions else float('nan'))}"
            )

    print("\n== gate on clean reference episodes (pass bar) ==")
    clean_actions = 0
    clean_holds = 0
    for shifted in (False, True):
        _, y, holds, _, _, actions, _ = cache[("clean", shifted)]
        label = "shifted" if shifted else "clean"
        print(
            f"clean,{label},actions={actions},holds={int(holds.sum())},"
            f"hold_rate={_fmt(float(holds.mean()) if actions else float('nan'))}"
        )
        clean_actions += actions
        clean_holds += int(holds.sum())
    clean_rate = clean_holds / clean_actions if clean_actions else float("nan")
    clean_ok = bool(np.isfinite(clean_rate) and clean_rate <= 0.02)
    print(
        f"pooled_clean_hold_rate={_fmt(clean_rate)} bar=0.0200 "
        f"{'PASS' if clean_ok else 'FAIL'}"
    )

    print("\n== taint pass-bar check (gate only; tests are run by run.sh) ==")
    print(
        f"gate_clean_hold_rate={_fmt(clean_rate)} bar=0.0200 "
        f"{'PASS' if clean_ok else 'FAIL'}"
    )
    print(f"gate_overall: {'PASS' if clean_ok else 'FAIL'}")
    return 0 if clean_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
