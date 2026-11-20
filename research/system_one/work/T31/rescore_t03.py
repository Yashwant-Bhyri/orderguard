"""Measure v2 binding coherence and re-score T03 with incoherent negatives removed.

Reads the v2 reference corpora, runs ``og_s1.coherence`` causally per action,
prints the rate of each finding per family and split, then recomputes T03's
best-single-feature AUROC per cause group with every y=0 action that has a
coherence finding removed.  T03's files are imported, never edited.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1.checks import (  # noqa: E402
    AUTHORITY_SPOOF,
    DRIFT,
    FEATURE_NAMES,
    GROUPS,
    MISQUOTE,
    POISONED_NOTE,
    STALE_THESIS,
    UNSUPPORTED_CLAIM,
    auroc,
    featurize,
)
from og_s1.coherence import (  # noqa: E402
    FINDING_KINDS,
    build_context,
    case_for_step,
    coherence,
    finding_kinds,
)
from og_s1.schema import Episode  # noqa: E402
from og_s1.world import FAMILIES  # noqa: E402

CAUSE_GROUPS = (
    DRIFT,
    UNSUPPORTED_CLAIM,
    MISQUOTE,
    POISONED_NOTE,
    AUTHORITY_SPOOF,
    STALE_THESIS,
)
BRIEF_THREE = (
    "rationale_direction",
    "rationale_foreign_instrument",
    "claim_not_about_trade",
)
DATA_DIR = ROOT / "data" / "ref"


def _path(family: str, shifted: bool) -> Path:
    return DATA_DIR / f"{family}{'.shifted' if shifted else ''}.jsonl"


def _load(family: str, shifted: bool):
    X_rows = []
    ys = []
    keep_any = []
    keep_brief3 = []
    stats = {
        "actions": 0,
        "positives": 0,
        "negatives": 0,
        "dirty_actions": 0,
        "dirty_negatives": 0,
        "brief_three_actions": 0,
        "brief_three_negatives": 0,
        "kinds": Counter(),
        "kind_negatives": Counter(),
        "kind_positives": Counter(),
        "structure_signature": [],
        "finding_signature": [],
    }
    with _path(family, shifted).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            episode = Episode.from_dict(json.loads(line))
            ctx = build_context(episode)
            X, _names, _groups = featurize(episode)
            y = np.asarray([int(step.label.y) for step in episode.steps], dtype=float)
            for i, step in enumerate(episode.steps):
                kinds = set(finding_kinds(coherence(step.action, case_for_step(episode, i, context=ctx))))
                stats["actions"] += 1
                stats["structure_signature"].append((
                    int(step.action.t), str(step.action.instrument), str(step.action.side),
                    round(float(step.action.notional), 2), str(step.action.thesis_id),
                    len(step.action.claims), int(step.label.y), str(step.label.cause),
                ))
                stats["finding_signature"].append(tuple(sorted(kinds)))
                if y[i] == 0:
                    stats["negatives"] += 1
                else:
                    stats["positives"] += 1
                if kinds:
                    stats["dirty_actions"] += 1
                    for kind in kinds:
                        stats["kinds"][kind] += 1
                    if y[i] == 0:
                        stats["dirty_negatives"] += 1
                        for kind in kinds:
                            stats["kind_negatives"][kind] += 1
                    else:
                        for kind in kinds:
                            stats["kind_positives"][kind] += 1
                if kinds & set(BRIEF_THREE):
                    stats["brief_three_actions"] += 1
                    if y[i] == 0:
                        stats["brief_three_negatives"] += 1
                keep_any.append(not (y[i] == 0 and bool(kinds)))
                keep_brief3.append(not (y[i] == 0 and bool(set(kinds) & set(BRIEF_THREE))))
            X_rows.append(X)
            ys.append(y)
    X = np.vstack(X_rows) if X_rows else np.zeros((0, len(FEATURE_NAMES)))
    y = np.concatenate(ys) if ys else np.zeros(0)
    return (
        X,
        y,
        np.asarray(keep_any, dtype=bool),
        np.asarray(keep_brief3, dtype=bool),
        stats,
    )


def _best(group: str, X: np.ndarray, y: np.ndarray) -> tuple[float, str]:
    indices = [j for j, name in enumerate(FEATURE_NAMES) if GROUPS[name] == group]
    best_value = float("nan")
    best_name = "-"
    for j in indices:
        value = auroc(y, X[:, j]) if y.size else float("nan")
        if np.isfinite(value) and (not np.isfinite(best_value) or value > best_value):
            best_value = value
            best_name = FEATURE_NAMES[j]
    return best_value, best_name


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.4f}"


def main() -> int:
    caches = {}
    print("== v2 coherence rates per family and split ==")
    print("all-action finding counts are labelled *_all and include y=1 actions;")
    print("negative-only counts and rates are in the next table.")
    print("family,shift,actions,positives,negatives,dirty_actions,dirty_negatives,brief3_actions,brief3_negatives," +
          ",".join(f"{k}_all" for k in FINDING_KINDS))
    for shifted in (False, True):
        label = "shifted" if shifted else "unshifted"
        for family in FAMILIES:
            X, y, keep_any, keep_brief3, stats = _load(family, shifted)
            caches[(family, shifted)] = (X, y, keep_any, keep_brief3, stats)
            print(
                f"{family},{label},{stats['actions']},{stats['positives']},{stats['negatives']},"
                f"{stats['dirty_actions']},{stats['dirty_negatives']},"
                f"{stats['brief_three_actions']},{stats['brief_three_negatives']},"
                + ",".join(str(stats["kinds"].get(k, 0)) for k in FINDING_KINDS)
            )

    print("\n== v2 pooled over all families ==")
    print("shift,negatives,any,brief3,direction,rationale_foreign,no_claim,claim_foreign,stale")
    for shifted in (False, True):
        label = "shifted" if shifted else "unshifted"
        agg = {"negatives": 0, "dirty_negatives": 0, "brief3_negatives": 0, "kinds": Counter()}
        for family in FAMILIES:
            stats = caches[(family, shifted)][4]
            agg["negatives"] += stats["negatives"]
            agg["dirty_negatives"] += stats["dirty_negatives"]
            agg["brief3_negatives"] += stats["brief_three_negatives"]
            agg["kinds"].update(stats["kind_negatives"])
        n = agg["negatives"]
        def pct(key):
            return f"{100 * agg[key] / n:.1f}%" if n else "nan"
        print(
            f"{label},{n},{pct('dirty_negatives')},{pct('brief3_negatives')},"
            f"{100 * agg['kinds'].get('rationale_direction', 0) / n:.1f}%,"
            f"{100 * agg['kinds'].get('rationale_foreign_instrument', 0) / n:.1f}%,"
            f"{100 * agg['kinds'].get('claim_not_about_trade', 0) / n:.1f}%,"
            f"{100 * agg['kinds'].get('claim_foreign_instrument', 0) / n:.1f}%,"
            f"{100 * agg['kinds'].get('claim_stale_period', 0) / n:.1f}%"
        )

    print("\n== v2: finding count among negatives (y=0) and rate per action ==")
    print("family,shift,negatives," + ",".join(f"{k}_n,{k}_rate" for k in FINDING_KINDS))
    for shifted in (False, True):
        label = "shifted" if shifted else "unshifted"
        for family in FAMILIES:
            stats = caches[(family, shifted)][4]
            n = stats["negatives"]
            cells = []
            for kind in FINDING_KINDS:
                count = stats["kind_negatives"].get(kind, 0)
                cells.extend([str(count), f"{(count / n if n else 0.0):.4f}"])
            print(f"{family},{label},{n}," + ",".join(cells))

    print("\n== v2: finding count among positives (y=1) ==")
    print("family,shift,positives," + ",".join(f"{k}_n" for k in FINDING_KINDS))
    for shifted in (False, True):
        label = "shifted" if shifted else "unshifted"
        for family in FAMILIES:
            stats = caches[(family, shifted)][4]
            n = stats["positives"]
            print(
                f"{family},{label},{n},"
                + ",".join(str(stats["kind_positives"].get(k, 0)) for k in FINDING_KINDS)
            )

    print("\n== v2 split symmetry (shifted vs unshifted) ==")
    print("family,actions_equal,structure_equal,findings_equal")
    for family in FAMILIES:
        u = caches[(family, False)][4]
        s = caches[(family, True)][4]
        print(
            f"{family},{u['actions'] == s['actions']},"
            f"{u['structure_signature'] == s['structure_signature']},"
            f"{u['finding_signature'] == s['finding_signature']}"
        )

    print("\n== T03 re-score with incoherent v2 negatives removed ==")
    print("group,shift,best_feature,baseline_auroc,filtered_any_feature,filtered_any_auroc,delta_any,"
          "filtered_brief3_feature,filtered_brief3_auroc,delta_brief3,n_pos,n_neg,n_neg_removed_any,"
          "n_neg_removed_brief3")
    ok = True
    for group in CAUSE_GROUPS:
        for shifted in (False, True):
            X, y, keep_any, keep_brief3, _stats = caches[(group, shifted)]
            base, base_name = _best(group, X, y)
            any_v, any_name = _best(group, X[keep_any], y[keep_any])
            b3_v, b3_name = _best(group, X[keep_brief3], y[keep_brief3])
            n_neg = int((y == 0).sum())
            n_any_kept = int((y[keep_any] == 0).sum())
            n_b3_kept = int((y[keep_brief3] == 0).sum())
            print(
                f"{group},{'shifted' if shifted else 'unshifted'},{base_name},{_fmt(base)},"
                f"{any_name},{_fmt(any_v)},{_fmt(any_v - base)},"
                f"{b3_name},{_fmt(b3_v)},{_fmt(b3_v - base)},"
                f"{int((y == 1).sum())},{n_neg},{n_neg - n_any_kept},{n_neg - n_b3_kept}"
            )
            if shifted and not (np.isfinite(any_v) and any_v >= 0.80
                                and np.isfinite(b3_v) and b3_v >= 0.80):
                ok = False
    print(f"\nT03 shifted pass bar (>=0.80 after removal): {'PASS' if ok else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
