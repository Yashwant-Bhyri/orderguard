"""Train reader 3: MiniLM sentence embeddings + logistic regression per feature.

Two holdout numbers are reported per feature:

* a random-row split (the round-1 number, kept for comparison); and
* a template-group split, which holds out whole sentence/doc templates.

The template-group number is the honest transfer number; the row split shares
near-duplicate templates between train and test and is optimistic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold, train_test_split

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1.readers.embed_lr import embed_texts, model_path, pair_features  # noqa: E402


def _load(path: Path) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {"hype": [], "authority_language": [], "support_gap": []}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            groups[row["feature"]].append(row)
    return groups


def _probe(seed: int) -> LogisticRegression:
    return LogisticRegression(
        C=1.0, solver="lbfgs", max_iter=3000, class_weight="balanced", random_state=seed
    )


def _train_one(feature: str, rows: list[dict], seed: int) -> tuple[LogisticRegression, dict]:
    if feature == "support_gap":
        X = pair_features(
            [row["hypothesis"] for row in rows],
            [row["premise"] for row in rows],
        )
    else:
        X = embed_texts([row["text"] for row in rows])
    y = np.asarray([int(row["label"]) for row in rows], dtype=int)
    groups = np.asarray([str(row.get("group", f"{feature}_ungrouped")) for row in rows], dtype=object)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y
    )
    row_probe = _probe(seed)
    row_probe.fit(X_tr, y_tr)
    row_holdout = float(roc_auc_score(y_te, row_probe.predict_proba(X_te)[:, 1]))

    n_groups = len(set(groups.tolist()))
    splitter = StratifiedGroupKFold(
        n_splits=min(5, max(2, n_groups)), shuffle=True, random_state=seed
    )
    g_tr, g_te = next(splitter.split(X, y, groups))
    group_probe = _probe(seed)
    group_probe.fit(X[g_tr], y[g_tr])
    if len(set(y[g_te].tolist())) < 2:
        group_holdout = float("nan")
    else:
        group_holdout = float(roc_auc_score(y[g_te], group_probe.predict_proba(X[g_te])[:, 1]))

    final = _probe(seed)
    final.fit(X, y)
    return final, {
        "n": int(len(y)),
        "n_pos": int(y.sum()),
        "n_neg": int(len(y) - y.sum()),
        "n_groups": int(len(set(groups.tolist()))),
        "n_test_groups": int(len(set(groups[g_te].tolist()))),
        "row_split_holdout_auroc": row_holdout,
        "template_group_holdout_auroc": group_holdout,
        "train_auroc": float(roc_auc_score(y, final.predict_proba(X)[:, 1])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", default="work/T05/train_text/train_text.jsonl")
    parser.add_argument("--out", default=None)
    parser.add_argument("--seed", type=int, default=12345)
    args = parser.parse_args(argv)

    groups = _load(Path(args.train))
    bundle = {"meta": {"seed": args.seed, "train_file": str(args.train)}}
    for feature, rows in groups.items():
        if not rows:
            raise SystemExit(f"no training rows for {feature}")
        model, stats = _train_one(feature, rows, args.seed)
        bundle[feature] = model
        bundle["meta"][feature] = stats
        print(
            f"{feature}: n={stats['n']} pos={stats['n_pos']} neg={stats['n_neg']} "
            f"groups={stats['n_groups']} "
            f"row_holdout_auroc={stats['row_split_holdout_auroc']:.4f} "
            f"template_group_holdout_auroc={stats['template_group_holdout_auroc']:.4f} "
            f"train_auroc={stats['train_auroc']:.4f}"
        )

    bundle["meta"]["model_id"] = "sentence-transformers/all-MiniLM-L6-v2"
    bundle["meta"]["licence"] = "Apache-2.0"
    out = Path(args.out) if args.out else model_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(bundle, out)
    try:
        label = str(out.resolve().relative_to(ROOT))
    except ValueError:
        label = "external path (not recorded)"
    print(f"wrote {label} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
