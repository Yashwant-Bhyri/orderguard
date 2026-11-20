"""Honest evaluation harness for the OrderGuard System One model zoo.

Usage::

    python -m og_s1.evaluate --train data/ref --test data/ref --out results.json

Training reads only ``data/ref`` episodes whose ``meta.shifted`` is false.
Hyperparameters and probability calibration use a calibration split of that
data.  Every other episode is test, including every shifted episode.  Features
are computed only through ``og_s1.checks.featurize``, which reads
``og_s1.schema.model_view_at`` for each action.  Labels and ``meta`` are read
only for splitting, calibration and scoring.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score

from og_s1.checks import FEATURE_NAMES, GROUPS, featurize
from og_s1.models import (
    BaseModel,
    NoisyAndModel,
    make_models,
)
from og_s1.schema import Episode

# Round 2: the round-1 ref-test attribution rows were inspected after the run,
# so those rows are void under POLICY.md.  The round-2 test split is drawn from
# episodes that were NOT in the round-1 test split (see ``split_records``), with
# a new seed fixed before this round's run.  The round-1 seed is kept only so the
# evaluator can exclude its test keys deterministically.
SPLIT_SEED = 20261120
PREVIOUS_SPLIT_SEED = 20261119
BOOTSTRAP_SEED = 20261119
BOOTSTRAP_N = 1000
TRAIN_SEEDS = (0, 1, 2, 3, 4)
HOLD_TARGET = 0.02
ECE_BINS = 15
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
MODEL_NAMES = ("logistic", "ebm", "hgb", "hgb_monotone", "noisy_and")
CAUSE_TO_GROUP = {
    "drift": "drift",
    "unsupported_claim": "unsupported_claim",
    "misquote": "misquote",
    "poisoned_note": "poisoned_note",
    "authority_spoof": "authority_spoof",
    "stale_thesis": "stale_thesis",
}
CAUSE_GROUPS = (
    "drift",
    "unsupported_claim",
    "misquote",
    "poisoned_note",
    "authority_spoof",
    "stale_thesis",
)


@dataclass
class Record:
    key: str
    path: str
    line_no: int
    family: str
    shifted: bool
    seed: int
    author: str
    X: np.ndarray
    y: np.ndarray
    causes: list[str]
    timings_ms: np.ndarray


def auroc(y: Any, scores: Any) -> float:
    y_arr = np.asarray(y, dtype=float).ravel()
    s_arr = np.asarray(scores, dtype=float).ravel()
    if y_arr.size == 0 or y_arr.size != s_arr.size or np.unique(y_arr).size < 2:
        return float("nan")
    return float(roc_auc_score(y_arr, s_arr))


def brier(y: Any, probs: Any) -> float:
    y_arr = np.asarray(y, dtype=float).ravel()
    p_arr = np.asarray(probs, dtype=float).ravel()
    if y_arr.size == 0 or y_arr.size != p_arr.size:
        return float("nan")
    return float(brier_score_loss(y_arr, p_arr))


def ece_equal_width(y: Any, probs: Any, n_bins: int = ECE_BINS) -> float:
    y_arr = np.asarray(y, dtype=float).ravel()
    p_arr = np.asarray(probs, dtype=float).ravel()
    if y_arr.size == 0 or y_arr.size != p_arr.size:
        return float("nan")
    bins = np.clip(np.floor(p_arr * n_bins).astype(int), 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        mask = bins == b
        if not np.any(mask):
            continue
        total += float(mask.mean()) * abs(float(p_arr[mask].mean()) - float(y_arr[mask].mean()))
    return float(total)


def ece_adaptive(y: Any, probs: Any, n_bins: int = ECE_BINS) -> float:
    y_arr = np.asarray(y, dtype=float).ravel()
    p_arr = np.asarray(probs, dtype=float).ravel()
    if y_arr.size == 0 or y_arr.size != p_arr.size:
        return float("nan")
    order = np.argsort(p_arr, kind="mergesort")
    total = 0.0
    for chunk in np.array_split(order, n_bins):
        if chunk.size == 0:
            continue
        total += float(chunk.size / y_arr.size) * abs(float(p_arr[chunk].mean()) - float(y_arr[chunk].mean()))
    return float(total)


def threshold_for_hold_rate(scores: Any, target: float = HOLD_TARGET) -> float:
    s = np.sort(np.asarray(scores, dtype=float).ravel())
    n = s.size
    if n == 0:
        return float("inf")
    k = int(math.ceil((1.0 - target) * n))
    k = max(1, min(n, k))
    return float(s[k - 1])


def percentile_ci(values: Iterable[float], lo: float = 2.5, hi: float = 97.5) -> tuple[float, float]:
    clean = [float(v) for v in values if np.isfinite(v)]
    if not clean:
        return (float("nan"), float("nan"))
    if len(clean) == 1:
        return (clean[0], clean[0])
    low, high = np.percentile(np.asarray(clean, dtype=float), [lo, hi])
    return (float(low), float(high))


def episode_bootstrap_indices(episode_ids: Sequence[Any], n_boot: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED):
    ids = np.asarray(list(episode_ids), dtype=object)
    unique, inverse = np.unique(ids, return_inverse=True)
    members = [np.where(inverse == k)[0] for k in range(len(unique))]
    rng = np.random.default_rng(seed)
    for _ in range(n_boot):
        chosen = rng.integers(0, len(unique), size=len(unique))
        yield np.concatenate([members[k] for k in chosen])


def bootstrap_episode_values(values: Any, n_boot: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED) -> tuple[tuple[float, float], tuple[float, float]]:
    arr = np.asarray(values, dtype=float).ravel()
    rng = np.random.default_rng(seed)
    means: list[float] = []
    medians: list[float] = []
    for _ in range(n_boot):
        sample = arr[rng.integers(0, arr.size, size=arr.size)] if arr.size else arr
        finite = sample[np.isfinite(sample)]
        if finite.size:
            means.append(float(finite.mean()))
            medians.append(float(np.median(finite)))
    return percentile_ci(means), percentile_ci(medians)


def bootstrap_metrics(
    y: np.ndarray,
    probs: np.ndarray,
    episode_ids: np.ndarray,
    clean_mask: np.ndarray,
    tau: float,
    n_boot: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, tuple[float, float]]:
    buckets: dict[str, list[float]] = {
        "auroc": [],
        "brier": [],
        "ece_15": [],
        "ece_adaptive": [],
        "hold_rate_clean": [],
        "recall": [],
    }
    for idx in episode_bootstrap_indices(episode_ids, n_boot=n_boot, seed=seed):
        yy = y[idx]
        pp = probs[idx]
        cc = clean_mask[idx]
        buckets["auroc"].append(auroc(yy, pp))
        buckets["brier"].append(brier(yy, pp))
        buckets["ece_15"].append(ece_equal_width(yy, pp, ECE_BINS))
        buckets["ece_adaptive"].append(ece_adaptive(yy, pp, ECE_BINS))
        if np.any(cc):
            buckets["hold_rate_clean"].append(float(np.mean(pp[cc] > tau)))
        if np.any(yy == 1.0):
            buckets["recall"].append(float(np.mean(pp[yy == 1.0] > tau)))
    return {name: percentile_ci(values) for name, values in buckets.items()}


def bootstrap_multiplicities(n_units: int, n_boot: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED) -> np.ndarray:
    """Episode multiplicities for each bootstrap resample.

    Row ``b`` counts how often each episode was drawn in resample ``b``.  This is
    the same resampling distribution as ``episode_bootstrap_indices`` (whole
    episodes, ``n_units`` draws with replacement), represented as counts so that
    per-episode sufficient statistics can be aggregated with one matrix product.
    """
    if n_units <= 0 or n_boot <= 0:
        return np.zeros((max(n_boot, 0), max(n_units, 0)), dtype=np.int64)
    rng = np.random.default_rng(seed)
    out = np.empty((n_boot, n_units), dtype=np.int64)
    for b in range(n_boot):
        chosen = rng.integers(0, n_units, size=n_units)
        out[b] = np.bincount(chosen, minlength=n_units)
    return out


def _score_groups(probs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(probs, kind="mergesort")
    sorted_probs = probs[order]
    if sorted_probs.size == 0:
        return order, np.zeros(0, dtype=int)
    starts = np.r_[0, np.flatnonzero(sorted_probs[1:] != sorted_probs[:-1]) + 1]
    return order, starts


def _auroc_from_counts(
    sorted_y: np.ndarray,
    sorted_episode: np.ndarray,
    group_starts: np.ndarray,
    multiplicities: np.ndarray,
) -> float:
    """Exact Mann-Whitney AUROC for an episode-bootstrap multiset.

    The resampled data is the original rows with integer multiplicity per
    episode.  Sorting is done once on the fixed scores; for each resample the
    weighted negative count below each distinct score gives the tie-corrected
    numerator without re-sorting.
    """
    weights = multiplicities[sorted_episode].astype(float)
    neg = sorted_y == 0.0
    w_neg = np.where(neg, weights, 0.0)
    w_pos = weights - w_neg
    neg_groups = np.add.reduceat(w_neg, group_starts)
    pos_groups = np.add.reduceat(w_pos, group_starts)
    prefix_neg = np.r_[0.0, np.cumsum(neg_groups)[:-1]]
    numerator = float(pos_groups @ (prefix_neg + 0.5 * neg_groups))
    n_pos = float(pos_groups.sum())
    n_neg = float(neg_groups.sum())
    if n_pos == 0.0 or n_neg == 0.0:
        return float("nan")
    return numerator / (n_pos * n_neg)


def _adaptive_ece_from_counts(
    sorted_probs: np.ndarray,
    sorted_y: np.ndarray,
    sorted_episode: np.ndarray,
    multiplicities: np.ndarray,
    n_bins: int = ECE_BINS,
) -> float:
    """Adaptive ECE for a bootstrap multiset, without materialising the resample.

    ``ece_adaptive`` cuts the sorted rows into ``n_bins`` equal-count chunks.
    With integer multiplicities the same cut is a position in the weighted
    sorted sequence; prefix sums of ``w*p`` and ``w*y`` give each chunk's
    contribution.  Ties are ordered by the fixed original row order (the point
    metric's stable order); with no ties this is identical to recomputing on the
    resampled array.
    """
    n = sorted_probs.size
    weights = multiplicities[sorted_episode].astype(float)
    total = float(weights.sum())
    if n == 0 or total <= 0.0:
        return float("nan")
    cum_w = np.r_[0.0, np.cumsum(weights)]
    cum_p = np.r_[0.0, np.cumsum(weights * sorted_probs)]
    cum_y = np.r_[0.0, np.cumsum(weights * sorted_y)]
    total_i = int(total)
    sizes = np.full(n_bins, total_i // n_bins, dtype=np.int64)
    sizes[: total_i % n_bins] += 1
    bounds = np.r_[0, np.cumsum(sizes)].astype(float)
    k = np.searchsorted(cum_w, bounds, side="right") - 1
    kk = np.clip(k, 0, n - 1)
    residual = bounds - cum_w[kk]
    prefix_p = cum_p[kk] + residual * sorted_probs[kk]
    prefix_y = cum_y[kk] + residual * sorted_y[kk]
    past_end = k >= n
    prefix_p[past_end] = cum_p[n]
    prefix_y[past_end] = cum_y[n]
    return float(np.abs(np.diff(prefix_p) - np.diff(prefix_y)).sum() / total)


def bootstrap_metrics_fast(
    y: np.ndarray,
    probs: np.ndarray,
    episode_ids: np.ndarray,
    clean_mask: np.ndarray,
    tau: float,
    n_boot: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, tuple[float, float]]:
    """Episode bootstrap with the same metrics as ``bootstrap_metrics``.

    This is the exact same resampling procedure as ``episode_bootstrap_indices``
    (whole episodes, 1,000 draws); the metrics are computed from per-episode
    sufficient statistics and a rank-count formulation, so the cost is linear in
    the corpus instead of re-sorting every resample.  ``bootstrap_metrics``
    remains the naive reference used by the tests.
    """
    y = np.asarray(y, dtype=float).ravel()
    probs = np.asarray(probs, dtype=float).ravel()
    clean_mask = np.asarray(clean_mask, dtype=bool).ravel()
    ids = np.asarray(list(episode_ids), dtype=object)
    unique, inverse = np.unique(ids, return_inverse=True)
    n_units = len(unique)
    if y.size == 0 or n_units == 0:
        return {name: (float("nan"), float("nan")) for name in (
            "auroc", "brier", "ece_15", "ece_adaptive", "hold_rate_clean", "recall"
        )}
    counts = np.bincount(inverse, minlength=n_units).astype(float)
    brier_sq = np.bincount(inverse, weights=(probs - y) ** 2, minlength=n_units)
    clean_count = np.bincount(inverse, weights=clean_mask.astype(float), minlength=n_units)
    clean_hold = np.bincount(
        inverse, weights=((probs > tau) & clean_mask).astype(float), minlength=n_units
    )
    positive_count = np.bincount(inverse, weights=(y == 1.0).astype(float), minlength=n_units)
    positive_hold = np.bincount(
        inverse, weights=((y == 1.0) & (probs > tau)).astype(float), minlength=n_units
    )
    bins = np.clip(np.floor(probs * ECE_BINS).astype(int), 0, ECE_BINS - 1)
    sum_p = np.zeros((n_units, ECE_BINS), dtype=float)
    sum_y = np.zeros((n_units, ECE_BINS), dtype=float)
    for b in range(ECE_BINS):
        mask = bins == b
        if not np.any(mask):
            continue
        sum_p[:, b] = np.bincount(inverse, weights=probs * mask, minlength=n_units)
        sum_y[:, b] = np.bincount(inverse, weights=y * mask, minlength=n_units)

    mult = bootstrap_multiplicities(n_units, n_boot=n_boot, seed=seed)
    n_rows = mult @ counts
    with np.errstate(divide="ignore", invalid="ignore"):
        brier_values = (mult @ brier_sq) / n_rows
        hold_values = np.divide(
            mult @ clean_hold,
            mult @ clean_count,
            out=np.full(len(mult), np.nan),
            where=(mult @ clean_count) > 0,
        )
        recall_values = np.divide(
            mult @ positive_hold,
            mult @ positive_count,
            out=np.full(len(mult), np.nan),
            where=(mult @ positive_count) > 0,
        )
        ece_values = np.abs(mult @ (sum_p - sum_y)).sum(axis=1) / n_rows

    order, starts = _score_groups(probs)
    sorted_y = y[order]
    sorted_episode = inverse[order]
    sorted_probs = probs[order]
    auroc_values = np.array(
        [_auroc_from_counts(sorted_y, sorted_episode, starts, m) for m in mult]
    )
    adaptive_values = np.array(
        [
            _adaptive_ece_from_counts(sorted_probs, sorted_y, sorted_episode, m, ECE_BINS)
            for m in mult
        ]
    )
    return {
        "auroc": percentile_ci(auroc_values),
        "brier": percentile_ci(brier_values),
        "ece_15": percentile_ci(ece_values),
        "ece_adaptive": percentile_ci(adaptive_values),
        "hold_rate_clean": percentile_ci(hold_values),
        "recall": percentile_ci(recall_values),
    }


def point_metrics(y: np.ndarray, probs: np.ndarray, clean_mask: np.ndarray, tau: float) -> dict[str, float]:
    positives = y == 1.0
    return {
        "auroc": auroc(y, probs),
        "brier": brier(y, probs),
        "ece_15": ece_equal_width(y, probs, ECE_BINS),
        "ece_adaptive": ece_adaptive(y, probs, ECE_BINS),
        "hold_rate_clean": float(np.mean(probs[clean_mask] > tau)) if np.any(clean_mask) else float("nan"),
        "recall": float(np.mean(probs[positives] > tau)) if np.any(positives) else float("nan"),
    }


def per_episode_lead(episode_ids: np.ndarray, y: np.ndarray, probs: np.ndarray, tau: float):
    unique, inverse = np.unique(episode_ids, return_inverse=True)
    leads = np.full(len(unique), np.nan, dtype=float)
    early = np.zeros(len(unique), dtype=bool)
    has_failure = np.zeros(len(unique), dtype=bool)
    for k in range(len(unique)):
        idx = np.where(inverse == k)[0]
        yy = y[idx]
        pp = probs[idx]
        positives = np.where(yy == 1.0)[0]
        if positives.size == 0:
            continue
        has_failure[k] = True
        onset = int(positives[0])
        holds = np.where(pp > tau)[0]
        if holds.size == 0:
            continue
        early[k] = bool(holds[0] < onset)
        after = holds[holds >= onset]
        if after.size:
            leads[k] = float(after[0] - onset)
    return unique, leads, early, has_failure


def lead_summary(leads: np.ndarray, early: np.ndarray, has_failure: np.ndarray) -> dict[str, float]:
    finite = leads[np.isfinite(leads)]
    return {
        "n_failure_episodes": int(has_failure.sum()),
        "n_held_after_onset": int(finite.size),
        "n_never_held": int(has_failure.sum() - finite.size),
        "n_early_hold": int(early.sum()),
        "mean_steps": float(finite.mean()) if finite.size else float("nan"),
        "median_steps": float(np.median(finite)) if finite.size else float("nan"),
        "p10_steps": float(np.percentile(finite, 10)) if finite.size else float("nan"),
        "p90_steps": float(np.percentile(finite, 90)) if finite.size else float("nan"),
    }


def attribution_scores(
    causes: np.ndarray,
    contributions: np.ndarray,
    feature_names: Sequence[str],
    groups: Mapping[str, str],
    episode_ids: np.ndarray | None = None,
    n_boot: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    n = contributions.shape[0]
    group_names = sorted(set(groups.get(name, "unmapped") for name in feature_names))
    group_matrix = np.zeros((n, len(group_names)), dtype=float)
    for k, group in enumerate(group_names):
        columns = [j for j, name in enumerate(feature_names) if groups.get(name, "unmapped") == group]
        if columns:
            group_matrix[:, k] = contributions[:, columns].sum(axis=1)
    best = np.argmax(group_matrix, axis=1)
    best_value = group_matrix[np.arange(n), best]
    top = np.array([group_names[int(b)] if best_value[i] > 0.0 else "none" for i, b in enumerate(best)], dtype=object)

    mapped = np.array([CAUSE_TO_GROUP.get(str(c)) for c in causes], dtype=object)
    mappable = np.array([m is not None for m in mapped], dtype=bool)
    overall = float(np.mean(top[mappable] == mapped[mappable])) if np.any(mappable) else float("nan")

    cause_strings = causes.astype(str)
    correct = np.zeros(n, dtype=bool)
    correct[mappable] = top[mappable] == mapped[mappable]
    per_cause: dict[str, Any] = {}
    for cause in sorted(set(str(c) for c in causes)):
        mask = cause_strings == cause
        target = CAUSE_TO_GROUP.get(cause)
        entry: dict[str, Any] = {
            "n": int(mask.sum()),
            "mapped": target is not None,
            "accuracy": float(np.mean(top[mask] == target)) if target is not None and np.any(mask) else None,
        }
        if cause == "vague_hype":
            entry["proxy_evidence_quality_accuracy"] = float(np.mean(top[mask] == "evidence_quality")) if np.any(mask) else None
        per_cause[cause] = entry

    overall_ci = (float("nan"), float("nan"))
    if episode_ids is not None and n_boot > 0 and np.any(mappable):
        ep = np.asarray(list(episode_ids), dtype=object)
        unique_ep, episode_inverse = np.unique(ep, return_inverse=True)
        n_units = len(unique_ep)
        mult = bootstrap_multiplicities(n_units, n_boot=n_boot, seed=seed)

        def _ci(mask: np.ndarray) -> tuple[float, float]:
            hits = np.bincount(episode_inverse[mask & correct], minlength=n_units).astype(float)
            totals = np.bincount(episode_inverse[mask], minlength=n_units).astype(float)
            numerator = mult @ hits
            denominator = mult @ totals
            values = np.divide(
                numerator,
                denominator,
                out=np.full(len(mult), np.nan),
                where=denominator > 0,
            )
            return percentile_ci(values)

        overall_ci = _ci(mappable)
        for cause, entry in per_cause.items():
            if entry["mapped"]:
                entry["accuracy_ci"] = list(_ci(cause_strings == cause))
    return {
        "overall_accuracy": overall,
        "overall_accuracy_ci": [float(overall_ci[0]), float(overall_ci[1])],
        "n_scored": int(mappable.sum()),
        "n_held_positives": int(n),
        "unmapped_causes": sorted(set(str(c) for c in causes[~mappable])),
        "per_cause": per_cause,
        "top_group_counts": {g: int(np.sum(top == g)) for g in group_names + ["none"]},
        "bootstrap_resamples": int(n_boot),
    }


def _discover_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("*.jsonl"))


def load_records(
    path: str | Path,
    *,
    include_shifted: bool = True,
    limit: int | None = None,
    progress: bool = False,
) -> list[Record]:
    root = Path(path)
    records: list[Record] = []
    for file_path in _discover_files(root):
        file_shifted = ".shifted" in file_path.name
        if file_shifted and not include_shifted:
            continue
        with open(file_path, "r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle):
                if limit is not None and len(records) >= limit:
                    return records
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                episode = Episode.from_dict(raw)
                meta = episode.meta or {}
                shifted = bool(meta.get("shifted", file_shifted))
                if shifted and not include_shifted:
                    continue
                timings: list[float] = []
                X, names, _ = featurize(episode, timings=timings)
                if list(names) != list(FEATURE_NAMES):
                    raise RuntimeError("feature names changed under the evaluator")
                y = np.asarray([int(step.label.y) for step in episode.steps], dtype=float)
                causes = [str(step.label.cause) for step in episode.steps]
                records.append(
                    Record(
                        key=f"{file_path.resolve()}::{line_no}",
                        path=str(file_path),
                        line_no=line_no,
                        family=str(meta.get("family", "unknown")),
                        shifted=shifted,
                        seed=int(meta.get("seed", -1)),
                        author=str(meta.get("author", "unknown")),
                        X=X,
                        y=y,
                        causes=causes,
                        timings_ms=np.asarray(timings, dtype=float) * 1000.0,
                    )
                )
        if progress:
            print(f"loaded {file_path.name}: {len(records)} episodes total", file=sys.stderr)
    return records


def split_records(
    records: Sequence[Record],
    *,
    seed: int = SPLIT_SEED,
    fractions: tuple[float, float, float] = (0.6, 0.2, 0.2),
    avoid_test_keys: set[str] | None = None,
) -> dict[str, list[Record]]:
    """Per-family episode split.

    When ``avoid_test_keys`` is supplied, those episodes may enter train or
    calibration but are forbidden from the test split.  Round 2 uses this to
    make the ref test disjoint from the round-1 test whose attribution rows had
    been inspected.
    """
    by_family: dict[str, list[Record]] = {}
    for record in records:
        by_family.setdefault(record.family, []).append(record)
    splits: dict[str, list[Record]] = {"train": [], "cal": [], "test": []}
    avoid = set(avoid_test_keys or ())
    for family in sorted(by_family):
        items = sorted(by_family[family], key=lambda r: r.key)
        rng = random.Random(seed + (zlib.crc32(family.encode("utf-8")) & 0xFFFF))
        n = len(items)
        n_train = min(int(round(n * fractions[0])), n)
        n_cal = min(int(round(n * fractions[1])), n - n_train)
        n_test = n - n_train - n_cal
        if avoid:
            eligible = [r for r in items if r.key not in avoid]
            blocked = [r for r in items if r.key in avoid]
            rng.shuffle(eligible)
            if len(eligible) < n_test:
                raise ValueError(
                    f"family {family}: only {len(eligible)} non-avoided episodes "
                    f"for a test split of {n_test}"
                )
            test = eligible[:n_test]
            rest = eligible[n_test:] + blocked
            rng.shuffle(rest)
            train = rest[:n_train]
            cal = rest[n_train : n_train + n_cal]
        else:
            rng.shuffle(items)
            train = items[:n_train]
            cal = items[n_train : n_train + n_cal]
            test = items[n_train + n_cal :]
        splits["train"].extend(train)
        splits["cal"].extend(cal)
        splits["test"].extend(test)
    for name in splits:
        splits[name] = sorted(splits[name], key=lambda r: r.key)
    return splits


def stack_records(records: Sequence[Record]) -> dict[str, np.ndarray]:
    if not records:
        return {
            "X": np.zeros((0, len(FEATURE_NAMES)), dtype=float),
            "y": np.zeros(0, dtype=float),
            "causes": np.zeros(0, dtype=object),
            "keys": np.zeros(0, dtype=object),
            "families": np.zeros(0, dtype=object),
            "shifted": np.zeros(0, dtype=bool),
            "timings_ms": np.zeros(0, dtype=float),
        }
    X = np.vstack([r.X for r in records])
    y = np.concatenate([r.y for r in records])
    causes = np.concatenate([np.asarray(r.causes, dtype=object) for r in records])
    keys = np.concatenate([np.full(len(r.y), r.key, dtype=object) for r in records])
    families = np.concatenate([np.full(len(r.y), r.family, dtype=object) for r in records])
    shifted = np.concatenate([np.full(len(r.y), r.shifted, dtype=bool) for r in records])
    timings_ms = np.concatenate([r.timings_ms for r in records])
    return {
        "X": X,
        "y": y,
        "causes": causes,
        "keys": keys,
        "families": families,
        "shifted": shifted,
        "timings_ms": timings_ms,
    }


def tune_hyperparameters(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_cal: np.ndarray,
    y_cal: np.ndarray,
    model_names: Sequence[str],
    *,
    quiet: bool = False,
) -> dict[str, dict[str, Any]]:
    from og_s1.models import BoostedTreesModel, LogisticModel

    hyperparameters: dict[str, dict[str, Any]] = {"ebm": {}}
    if "logistic" in model_names:
        best_c, best_score = 1.0, -np.inf
        for C in (0.01, 0.1, 1.0, 10.0):
            model = LogisticModel(C=C, random_state=0).fit(
                X_train, y_train, GROUPS, calibration=(X_cal, y_cal), feature_names=FEATURE_NAMES
            )
            score = auroc(y_cal, model.predict_proba(X_cal))
            if np.isfinite(score) and score > best_score:
                best_c, best_score = C, score
        hyperparameters["logistic"] = {"C": best_c}
        if not quiet:
            print(f"tuned logistic: C={best_c} cal_auroc={best_score:.4f}")
    for name, monotone in (("hgb", False), ("hgb_monotone", True)):
        if name not in model_names:
            continue
        best: tuple[float, int] = (0.1, 200)
        best_score = -np.inf
        for learning_rate, max_iter in ((0.05, 150), (0.1, 200)):
            model = BoostedTreesModel(
                monotone=monotone, learning_rate=learning_rate, max_iter=max_iter, random_state=0
            ).fit(X_train, y_train, GROUPS, calibration=(X_cal, y_cal), feature_names=FEATURE_NAMES)
            score = auroc(y_cal, model.predict_proba(X_cal))
            if np.isfinite(score) and score > best_score:
                best, best_score = (learning_rate, max_iter), score
        hyperparameters[name] = {"learning_rate": best[0], "max_iter": best[1]}
        if not quiet:
            print(f"tuned {name}: learning_rate={best[0]} max_iter={best[1]} cal_auroc={best_score:.4f}")
    if "noisy_and" in model_names:
        best_l2, best_score = 1e-2, -np.inf
        for l2 in (1e-3, 1e-2, 1e-1):
            model = NoisyAndModel(l2=l2, random_state=0).fit(
                X_train, y_train, GROUPS, calibration=(X_cal, y_cal), feature_names=FEATURE_NAMES
            )
            score = auroc(y_cal, model.predict_proba(X_cal))
            if np.isfinite(score) and score > best_score:
                best_l2, best_score = l2, score
        hyperparameters["noisy_and"] = {"l2": best_l2}
        if not quiet:
            print(f"tuned noisy_and: l2={best_l2} cal_auroc={best_score:.4f}")
    return hyperparameters


def latency_summary(model: BaseModel, X: np.ndarray, featurise_ms: np.ndarray, sample_size: int = 1000) -> dict[str, float]:
    n = X.shape[0]
    if n == 0:
        return {"n_actions": 0}
    count = min(int(sample_size), n)
    idx = np.linspace(0, n - 1, count).astype(int)
    predict_ms = np.empty(count, dtype=float)
    for k, i in enumerate(idx):
        started = time.perf_counter()
        model.predict_proba(X[i : i + 1])
        predict_ms[k] = (time.perf_counter() - started) * 1000.0
    total = predict_ms + np.asarray(featurise_ms, dtype=float)[idx]
    return {
        "n_actions": int(count),
        "featurise_p50_ms": float(np.percentile(featurise_ms[idx], 50)),
        "featurise_p99_ms": float(np.percentile(featurise_ms[idx], 99)),
        "predict_p50_ms": float(np.percentile(predict_ms, 50)),
        "predict_p99_ms": float(np.percentile(predict_ms, 99)),
        "total_mean_ms": float(total.mean()),
        "total_p50_ms": float(np.percentile(total, 50)),
        "total_p99_ms": float(np.percentile(total, 99)),
        "total_max_ms": float(total.max()),
    }


def _finite(values: Sequence[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return arr[np.isfinite(arr)]


def aggregate_seed_results(per_seed: Sequence[dict[str, Any]]) -> dict[str, Any]:
    metric_names = ("auroc", "brier", "ece_15", "ece_adaptive", "hold_rate_clean", "recall")
    metrics: dict[str, Any] = {}
    for name in metric_names:
        values = [float(d["point"].get(name, float("nan"))) for d in per_seed]
        cis = [d["ci"].get(name, (float("nan"), float("nan"))) for d in per_seed]
        finite = _finite(values)
        metrics[name] = {
            "mean": float(finite.mean()) if finite.size else float("nan"),
            "std": float(finite.std(ddof=1)) if finite.size > 1 else 0.0,
            "min": float(finite.min()) if finite.size else float("nan"),
            "max": float(finite.max()) if finite.size else float("nan"),
            "per_seed": values,
            "ci_per_seed": [[float(lo), float(hi)] for lo, hi in cis],
            "mean_ci": [
                float(np.nanmean([lo for lo, _ in cis])) if cis else float("nan"),
                float(np.nanmean([hi for _, hi in cis])) if cis else float("nan"),
            ],
        }

    causes = sorted(
        {cause for d in per_seed for cause in d.get("attribution", {}).get("per_cause", {})}
    )
    per_cause: dict[str, Any] = {}
    for cause in causes:
        values: list[float] = []
        ns: list[int] = []
        cis: list[tuple[float, float]] = []
        for d in per_seed:
            entry = d.get("attribution", {}).get("per_cause", {}).get(cause)
            if entry is None:
                continue
            ns.append(int(entry.get("n", 0)))
            if entry.get("accuracy") is not None:
                values.append(float(entry["accuracy"]))
            if entry.get("accuracy_ci") is not None:
                cis.append((float(entry["accuracy_ci"][0]), float(entry["accuracy_ci"][1])))
        finite = _finite(values)
        mean_ci = [
            float(np.nanmean([lo for lo, _ in cis])) if cis else float("nan"),
            float(np.nanmean([hi for _, hi in cis])) if cis else float("nan"),
        ]
        per_cause[cause] = {
            "mean": float(finite.mean()) if finite.size else float("nan"),
            "std": float(finite.std(ddof=1)) if finite.size > 1 else 0.0,
            "per_seed": values,
            "n_mean": float(np.mean(ns)) if ns else float("nan"),
            "mean_ci": mean_ci,
        }
    overall_values = [
        float(d["attribution"]["overall_accuracy"])
        for d in per_seed
        if d.get("attribution") and np.isfinite(d["attribution"].get("overall_accuracy", float("nan")))
    ]
    overall = _finite(overall_values)
    overall_cis = [
        (float(d["attribution"]["overall_accuracy_ci"][0]), float(d["attribution"]["overall_accuracy_ci"][1]))
        for d in per_seed
        if d.get("attribution") and d["attribution"].get("overall_accuracy_ci")
        and np.isfinite(d["attribution"]["overall_accuracy_ci"][0])
    ]
    overall_mean_ci = [
        float(np.nanmean([lo for lo, _ in overall_cis])) if overall_cis else float("nan"),
        float(np.nanmean([hi for _, hi in overall_cis])) if overall_cis else float("nan"),
    ]
    attribution = {
        "overall_accuracy": float(overall.mean()) if overall.size else float("nan"),
        "overall_accuracy_std": float(overall.std(ddof=1)) if overall.size > 1 else 0.0,
        "overall_accuracy_mean_ci": overall_mean_ci,
        "per_cause": per_cause,
    }

    lead_means: list[float] = []
    lead_medians: list[float] = []
    lead_cis: list[tuple[tuple[float, float], tuple[float, float]]] = []
    lead_extras: list[dict[str, Any]] = []
    for d in per_seed:
        lead = d.get("lead_time", {})
        point = lead.get("point", {})
        if np.isfinite(point.get("mean_steps", float("nan"))):
            lead_means.append(float(point["mean_steps"]))
        if np.isfinite(point.get("median_steps", float("nan"))):
            lead_medians.append(float(point["median_steps"]))
        if "ci" in lead:
            lead_cis.append(lead["ci"])
        lead_extras.append(point)
    mean_ci = [
        float(np.nanmean([ci[0][0] for ci in lead_cis])) if lead_cis else float("nan"),
        float(np.nanmean([ci[0][1] for ci in lead_cis])) if lead_cis else float("nan"),
    ]
    median_ci = [
        float(np.nanmean([ci[1][0] for ci in lead_cis])) if lead_cis else float("nan"),
        float(np.nanmean([ci[1][1] for ci in lead_cis])) if lead_cis else float("nan"),
    ]
    lead_time = {
        "mean_steps": float(np.mean(lead_means)) if lead_means else float("nan"),
        "median_steps": float(np.mean(lead_medians)) if lead_medians else float("nan"),
        "mean_ci": mean_ci,
        "median_ci": median_ci,
        "per_seed": lead_extras,
    }

    tau_values = _finite([float(d.get("tau", float("nan"))) for d in per_seed])
    cal_hold = _finite([float(d.get("cal_hold_rate", float("nan"))) for d in per_seed])
    calibration = {
        "tau_mean": float(tau_values.mean()) if tau_values.size else float("nan"),
        "tau_std": float(tau_values.std(ddof=1)) if tau_values.size > 1 else 0.0,
        "cal_hold_rate_mean": float(cal_hold.mean()) if cal_hold.size else float("nan"),
        "cal_hold_rate_std": float(cal_hold.std(ddof=1)) if cal_hold.size > 1 else 0.0,
        "target": HOLD_TARGET,
        "per_seed": [
            {"tau": float(d.get("tau", float("nan"))), "hold_rate": float(d.get("cal_hold_rate", float("nan")))}
            for d in per_seed
        ],
    }
    latency = next((d.get("latency") for d in per_seed if d.get("latency")), None)
    ebm_ok = next((d.get("ebm_monotone") for d in per_seed if d.get("ebm_monotone") is not None), None)
    ebm_details = next((d.get("ebm_monotonicity_details") for d in per_seed if d.get("ebm_monotonicity_details")), None)
    return {
        "metrics": metrics,
        "attribution": attribution,
        "lead_time": lead_time,
        "latency": latency,
        "calibration": calibration,
        "ebm_monotone": ebm_ok,
        "ebm_monotonicity_details": ebm_details,
    }


def _display_path(value: str | Path) -> str:
    path = Path(value)
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return path.name


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# T04 model evaluation — reference world")
    lines.append("")
    lines.append("Every value below is computed by `work/T04/run.sh`.  Cells are")
    lines.append("`mean ± seed spread [mean episode-bootstrap 95% CI]`; `n/a` means")
    lines.append("undefined for that split (for example AUROC when a split has one class).")
    lines.append("")
    lines.append("## Headline table")
    lines.append("")
    lines.append("| Test | Model | AUROC | Brier | ECE-15 | ECE-adaptive | Clean hold | Recall | Lead mean | Lead median | Top-cause acc |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for model_name, tests in payload["results"].items():
        for test_name, result in tests.items():
            m = result["metrics"]
            lead = result["lead_time"]
            attr = result["attribution"]
            def cell(metric: str) -> str:
                entry = m.get(metric, {})
                mean = entry.get("mean")
                std = entry.get("std")
                ci = entry.get("mean_ci", [None, None])
                if mean is None:
                    return "n/a"
                low = "n/a" if ci[0] is None else f"{ci[0]:.4f}"
                high = "n/a" if ci[1] is None else f"{ci[1]:.4f}"
                spread = 0.0 if std is None else std
                return f"{mean:.4f} ± {spread:.4f} [{low}, {high}]"
            def simple(value: Any, digits: int = 3) -> str:
                return "n/a" if value is None or not np.isfinite(value) else f"{value:.{digits}f}"
            lines.append(
                "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                    test_name,
                    model_name,
                    cell("auroc"),
                    cell("brier"),
                    cell("ece_15"),
                    cell("ece_adaptive"),
                    cell("hold_rate_clean"),
                    cell("recall"),
                    simple(lead.get("mean_steps")),
                    simple(lead.get("median_steps")),
                    simple(attr.get("overall_accuracy"), 4),
                )
            )
    lines.append("")
    lines.append("## Split sizes")
    lines.append("")
    lines.append("| Test | Episodes | Actions | Positives | Clean actions |")
    lines.append("|---|---:|---:|---:|---:|")
    for name, counts in payload["test_counts"].items():
        lines.append(
            f"| {name} | {counts['episodes']} | {counts['actions']} | {counts['positives']} | {counts['clean_actions']} |"
        )
    lines.append("")
    lines.append("## EBM monotonicity certificate")
    lines.append("")
    lines.append(f"All main-effect bins monotone: **{payload['ebm_monotone']}**.")
    details = payload.get("ebm_monotonicity_details") or []
    if details:
        worst = min(details, key=lambda d: d.get("min_diff", 0.0))
        lines.append(
            f"Features checked: {len(details)}.  Worst bin-to-bin change: "
            f"{worst.get('min_diff', 0.0):.6g} on `{worst.get('term', '?')}`."
        )
    lines.append("")
    lines.append("## Latency (one core, single-action prediction)")
    lines.append("")
    lines.append("| Model | Actions timed | Featurise p50 | Featurise p99 | Predict p50 | Predict p99 | Total p50 | Total p99 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    latency_rows = []
    for model_name, tests in payload["results"].items():
        result = tests.get("ref_test") or next(iter(tests.values()), {})
        latency_rows.append((model_name, result.get("latency") or {}))
    for model_name, latency in latency_rows:
        if not latency:
            continue
        lines.append(
            "| {} | {} | {:.3f} ms | {:.3f} ms | {:.3f} ms | {:.3f} ms | {:.3f} ms | {:.3f} ms |".format(
                model_name,
                latency.get("n_actions", 0),
                latency.get("featurise_p50_ms", float("nan")),
                latency.get("featurise_p99_ms", float("nan")),
                latency.get("predict_p50_ms", float("nan")),
                latency.get("predict_p99_ms", float("nan")),
                latency.get("total_p50_ms", float("nan")),
                latency.get("total_p99_ms", float("nan")),
            )
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    cpu_started = time.process_time()
    train_path = Path(args.train).resolve()
    model_names = [m.strip() for m in str(args.models).split(",") if m.strip()]
    unknown = [m for m in model_names if m not in MODEL_NAMES]
    if unknown:
        raise SystemExit(f"unknown models: {unknown}")
    seeds = list(TRAIN_SEEDS[: max(1, int(args.seeds))])
    n_boot = 0 if args.no_bootstrap else int(args.bootstrap)

    print(f"loading {_display_path(args.train)} once (unshifted for training, shifted for test)", file=sys.stderr)
    all_records = load_records(args.train, include_shifted=True, progress=not args.quiet)
    train_records = [record for record in all_records if not record.shifted]
    held_shifted = sorted(
        (record for record in all_records if record.shifted), key=lambda r: r.key
    )
    # The round-1 test split was inspected post hoc.  Forbid those episodes from
    # the round-2 test split; they may still be used for training/calibration.
    previous_test_keys = {
        record.key for record in split_records(train_records, seed=PREVIOUS_SPLIT_SEED)["test"]
    }
    splits = split_records(train_records, avoid_test_keys=previous_test_keys)
    test_overlap = sorted(
        {record.key for record in splits["test"]} & previous_test_keys
    )
    if test_overlap:
        raise RuntimeError(f"round-2 test split overlaps the inspected round-1 test: {test_overlap[:3]}")
    if args.max_train_episodes is not None:
        splits["train"] = splits["train"][: int(args.max_train_episodes)]
    if args.max_cal_episodes is not None:
        splits["cal"] = splits["cal"][: int(args.max_cal_episodes)]
    train = stack_records(splits["train"])
    cal = stack_records(splits["cal"])
    if train["X"].shape[0] == 0 or cal["X"].shape[0] == 0:
        raise SystemExit("empty train or calibration split")

    requested_tests = args.test or [args.train]
    test_blocks: dict[str, list[Record]] = {}
    for requested in requested_tests:
        path = Path(requested)
        name = path.stem or "test"
        if path.resolve() == train_path:
            test_blocks["ref_test"] = list(splits["test"])
            if held_shifted:
                test_blocks["ref_shifted"] = list(held_shifted)
        else:
            records = load_records(requested, include_shifted=True)
            has_shifted = any(r.shifted for r in records)
            has_unshifted = any(not r.shifted for r in records)
            if has_shifted and has_unshifted:
                test_blocks[f"{name}_unshifted"] = [r for r in records if not r.shifted]
                test_blocks[f"{name}_shifted"] = [r for r in records if r.shifted]
            else:
                test_blocks[name] = records
    for name in list(test_blocks):
        test_blocks[name] = sorted(test_blocks[name], key=lambda r: r.key)
        if args.max_test_episodes is not None:
            test_blocks[name] = test_blocks[name][: int(args.max_test_episodes)]
    test_arrays = {name: stack_records(records) for name, records in test_blocks.items()}

    print(
        f"split episodes: train={len(splits['train'])} cal={len(splits['cal'])} "
        f"ref_test={len(splits['test'])} tests={ {k: len(v) for k, v in test_blocks.items()} }",
        file=sys.stderr,
    )

    hyperparameters = tune_hyperparameters(
        train["X"], train["y"], cal["X"], cal["y"], model_names, quiet=args.quiet
    )

    per_seed: dict[str, dict[str, list[dict[str, Any]]]] = {
        model: {test_name: [] for test_name in test_blocks} for model in model_names
    }
    ebm_details: list[dict[str, Any]] = []
    ebm_certificate: dict[str, Any] = {}
    ebm_ok: bool | None = None

    for seed in seeds:
        print(f"seed {seed}: fitting models", file=sys.stderr)
        models = make_models(seed, hyperparameters)
        for model_name in model_names:
            model = models[model_name]
            model.fit(
                train["X"],
                train["y"],
                GROUPS,
                calibration=(cal["X"], cal["y"]),
                feature_names=FEATURE_NAMES,
            )
            if model_name == "ebm":
                ok, details = model.monotonicity_report()
                ebm_ok = bool(ok) if ebm_ok is None else (ebm_ok and bool(ok))
                ebm_details = details
                ebm_certificate = dict(getattr(model, "certificate_", {}))
            p_cal = model.predict_proba(cal["X"])
            clean_cal = (cal["families"] == "clean") & (cal["y"] == 0.0)
            if not np.any(clean_cal):
                clean_cal = cal["y"] == 0.0
            tau = threshold_for_hold_rate(p_cal[clean_cal], HOLD_TARGET)
            for test_name, block in test_arrays.items():
                if block["X"].shape[0] == 0:
                    continue
                p_test = model.predict_proba(block["X"])
                clean_mask = block["families"] == "clean"
                point = point_metrics(block["y"], p_test, clean_mask, tau)
                ci = (
                    bootstrap_metrics_fast(
                        block["y"], p_test, block["keys"], clean_mask, tau, n_boot=n_boot, seed=BOOTSTRAP_SEED
                    )
                    if n_boot > 0
                    else {}
                )
                held = p_test > tau
                held_positive = (block["y"] == 1.0) & held
                if np.any(held_positive):
                    contributions = model.explain(block["X"][held_positive])
                    attribution = attribution_scores(
                        block["causes"][held_positive],
                        contributions,
                        FEATURE_NAMES,
                        GROUPS,
                        episode_ids=block["keys"][held_positive],
                        n_boot=n_boot,
                        seed=BOOTSTRAP_SEED,
                    )
                    if isinstance(model, NoisyAndModel):
                        factor = model.factor_contributions(block["X"][held_positive])
                        factor_names = list(model.factor_names_)
                        attribution["factor_mean_contribution"] = {
                            factor_names[k]: float(factor[:, k].mean()) for k in range(factor.shape[1])
                        }
                        top_factor = np.argmax(factor, axis=1)
                        attribution["factor_top_counts"] = {
                            factor_names[k]: int(np.sum(top_factor == k)) for k in range(len(factor_names))
                        }
                else:
                    attribution = {
                        "overall_accuracy": float("nan"),
                        "overall_accuracy_ci": [float("nan"), float("nan")],
                        "n_scored": 0,
                        "n_held_positives": 0,
                        "per_cause": {},
                    }
                unique, leads, early, has_failure = per_episode_lead(block["keys"], block["y"], p_test, tau)
                lead_point = lead_summary(leads, early, has_failure)
                if n_boot > 0:
                    lead_ci = bootstrap_episode_values(leads, n_boot=n_boot, seed=BOOTSTRAP_SEED)
                else:
                    lead_ci = ((float("nan"), float("nan")), (float("nan"), float("nan")))
                latency = None
                if seed == seeds[0] and test_name == "ref_test":
                    latency = latency_summary(model, block["X"], block["timings_ms"])
                per_seed[model_name][test_name].append(
                    {
                        "seed": seed,
                        "tau": float(tau),
                        "cal_hold_rate": float(np.mean(p_cal[clean_cal] > tau)),
                        "point": point,
                        "ci": ci,
                        "attribution": attribution,
                        "lead_time": {"point": lead_point, "ci": lead_ci},
                        "latency": latency,
                        "ebm_monotone": ebm_ok if model_name == "ebm" else None,
                        "ebm_monotonicity_details": ebm_details if model_name == "ebm" else None,
                    }
                )
            print(
                f"  {model_name}: cal_tau={tau:.6f} "
                f"ref_test_auroc={per_seed[model_name].get('ref_test', [{}])[-1].get('point', {}).get('auroc')}",
                file=sys.stderr,
            )

    results: dict[str, Any] = {}
    for model_name in model_names:
        results[model_name] = {
            test_name: aggregate_seed_results(values)
            for test_name, values in per_seed[model_name].items()
            if values
        }

    test_counts = {}
    for name, block in test_arrays.items():
        test_counts[name] = {
            "episodes": len(test_blocks[name]),
            "actions": int(block["y"].size),
            "positives": int(np.sum(block["y"] == 1.0)),
            "clean_actions": int(np.sum(block["families"] == "clean")),
        }
    payload = {
        "task": "T04",
        "config": {
            "train": _display_path(args.train),
            "tests": [_display_path(item) for item in requested_tests],
            "seeds": seeds,
            "bootstrap_resamples": n_boot,
            "bootstrap_unit": "episode",
            "hold_target": HOLD_TARGET,
            "ece_bins": ECE_BINS,
            "split_seed": SPLIT_SEED,
            "previous_split_seed": PREVIOUS_SPLIT_SEED,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "models": model_names,
            "ebm_n_jobs": 1,
        },
        "hyperparameters": hyperparameters,
        "split_provenance": {
            "round2_split_seed": SPLIT_SEED,
            "round1_split_seed": PREVIOUS_SPLIT_SEED,
            "round2_test_episodes": len(splits["test"]),
            "round1_test_keys_forbidden": len(previous_test_keys),
            "round2_test_overlap_with_round1": len(test_overlap),
        },
        "splits": {
            name: {
                "episodes": len(splits[name]),
                "actions": int(sum(len(r.y) for r in splits[name])),
                "positives": int(sum(int(r.y.sum()) for r in splits[name])),
            }
            for name in ("train", "cal", "test")
        },
        "test_counts": test_counts,
        "ebm_monotone": bool(ebm_ok) if ebm_ok is not None else None,
        "ebm_certificate": ebm_certificate,
        "ebm_monotonicity_details": ebm_details,
        "results": results,
        "runtime_seconds": float(time.time() - started),
        "cpu_seconds": float(time.process_time() - cpu_started),
    }
    return _jsonable(payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the OrderGuard System One model zoo.")
    parser.add_argument("--train", default="data/ref")
    parser.add_argument("--test", action="append", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seeds", type=int, default=len(TRAIN_SEEDS))
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP_N)
    parser.add_argument("--no-bootstrap", action="store_true")
    parser.add_argument("--models", default=",".join(MODEL_NAMES))
    parser.add_argument("--max-train-episodes", type=int, default=None)
    parser.add_argument("--max-cal-episodes", type=int, default=None)
    parser.add_argument("--max-test-episodes", type=int, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    payload = run(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    markdown_path = out.with_suffix(".md")
    write_markdown(markdown_path, payload)
    print(f"wrote {_display_path(out)} and {_display_path(markdown_path)}")
    print(markdown_path.read_text(encoding="utf-8"))
    if payload.get("ebm_monotone") is False:
        print("EBM monotonicity certificate FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
