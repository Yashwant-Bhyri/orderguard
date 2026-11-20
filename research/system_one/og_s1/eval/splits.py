"""Group splits for the System One bench.

Splits are assigned to whole groups, never to random rows.  The four group
axes in ``COMBOS.md`` section 4 are company, author, agent and owner.  A split
is a permutation of the unique group ids; every case carrying a group id goes
to that group's split.  If a group appears on both sides the split is invalid
and :func:`assert_group_disjoint` raises.
"""

from __future__ import annotations

import random
from typing import Any, Sequence

import numpy as np

SPLIT_NAMES: tuple[str, ...] = ("train", "cal", "test")
SPLIT_SEED = 20261119
FRACTIONS: tuple[float, float, float] = (0.6, 0.2, 0.2)


def group_split(
    groups: Sequence[Any],
    *,
    fractions: tuple[float, float, float] = FRACTIONS,
    seed: int = SPLIT_SEED,
) -> np.ndarray:
    """Return an int split label (0/1/2) per case, assigned by whole group."""
    keys = [str(g) for g in groups]
    unique = sorted(set(keys))
    if len(unique) < 3:
        raise ValueError(
            f"need at least three groups for a train/cal/test split; got {len(unique)}"
        )
    shuffled = list(unique)
    random.Random(seed).shuffle(shuffled)
    n = len(shuffled)
    n_train = max(1, int(round(fractions[0] * n)))
    n_cal = max(1, int(round(fractions[1] * n)))
    n_test = n - n_train - n_cal
    while n_test < 1:
        if n_train >= n_cal and n_train > 1:
            n_train -= 1
        elif n_cal > 1:
            n_cal -= 1
        n_test = n - n_train - n_cal
    mapping: dict[str, int] = {}
    for i, key in enumerate(shuffled):
        if i < n_train:
            mapping[key] = 0
        elif i < n_train + n_cal:
            mapping[key] = 1
        else:
            mapping[key] = 2
    return np.asarray([mapping[key] for key in keys], dtype=int)


def assert_group_disjoint(groups: Sequence[Any], split: Sequence[int]) -> None:
    """Raise if any group appears in more than one split."""
    if len(groups) != len(split):
        raise AssertionError("groups and split must have the same length")
    seen: dict[str, set[int]] = {}
    for group, label in zip(groups, split):
        seen.setdefault(str(group), set()).add(int(label))
    leaked = sorted(key for key, labels in seen.items() if len(labels) > 1)
    if leaked:
        preview = ", ".join(leaked[:5])
        raise AssertionError(f"group leakage: {len(leaked)} group(s) on both sides ({preview})")
    bad = sorted({int(label) for label in split} - {0, 1, 2})
    if bad:
        raise AssertionError(f"invalid split labels: {bad}")


def assert_episode_disjoint(episode_ids: Sequence[Any], split: Sequence[int]) -> None:
    """Raise if any episode has cases in more than one split.

    This is a stricter check than :func:`assert_group_disjoint` and is the one
    that matters for an unseen-episode estimate: a company-held-out split can
    place two actions of the same episode on opposite sides when an episode
    trades many instruments, while every company key is still disjoint.
    """
    if len(episode_ids) != len(split):
        raise AssertionError("episode ids and split must have the same length")
    seen: dict[str, set[int]] = {}
    for episode, label in zip(episode_ids, split):
        seen.setdefault(str(episode), set()).add(int(label))
    leaked = sorted(key for key, labels in seen.items() if len(labels) > 1)
    if leaked:
        raise AssertionError(
            f"episode leakage: {len(leaked)} episode(s) on both sides ({', '.join(leaked[:5])})"
        )


def split_summary(groups: Sequence[Any], split: Sequence[int]) -> dict[str, Any]:
    """Counts of cases and groups per split, plus the disjointness check."""
    assert_group_disjoint(groups, split)
    labels = np.asarray(split, dtype=int)
    group_arr = np.asarray([str(g) for g in groups], dtype=object)
    out: dict[str, Any] = {}
    for label, name in enumerate(SPLIT_NAMES):
        mask = labels == label
        out[name] = {
            "cases": int(mask.sum()),
            "groups": int(len(set(group_arr[mask]))),
        }
    out["groups_total"] = int(len(set(group_arr)))
    return out
