"""E1 (CPU, runs now). Glass-box vs black-box learners on the reference world.

Question: on data/ref (in-domain and shifted), is the glass-box route
(code checks + monotone additive scorer) competitive with boosted trees and
logistic regression, and can "only tighten" hold by construction without an
accuracy tax?

Kill criteria, stated in advance:
- Kill the glass-box scorer (family 1 hypothesis) if the monotone EBM's
  shifted-test AUROC < 0.80.
- Kill fit-time monotone constraints if the certificate finds any
  non-monotone term cell or if monotonicity costs > 0.03 shifted AUROC
  versus the unconstrained EBM.

Writes results/e1.json and results/e1_sample_scores.json; prints tables.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from interpret.glassbox import ExplainableBoostingClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

import features as F

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


class EBMScorer:
    """Exact additive scorer extracted from a fitted interpret EBM.

    bin_idx = searchsorted(cut_points[i], x, side='right') + 1; the score is
    sigmoid(intercept + sum_i terms[i][bin_idx]). Verified against
    predict_proba on 200 rows during development.
    """

    def __init__(self, ebm):
        self.cut = [np.asarray(b[0], dtype=float) if len(b) else np.array([], dtype=float)
                    for b in ebm.bins_]
        self.terms = [np.asarray(t, dtype=float) for t in ebm.term_scores_]
        self.intercept = float(np.asarray(ebm.intercept_)[0])

    def predict(self, X):
        out = np.full(len(X), self.intercept)
        for i in range(len(self.cut)):
            c = self.cut[i]
            t = self.terms[i]
            if len(c) == 0:
                out += t[1]
                continue
            idx = np.searchsorted(c, X[:, i], side="right") + 1
            idx = np.clip(idx, 0, len(t) - 1)
            out += t[idx]
        return sigmoid(out)

    def contributions(self, X):
        contribs = np.zeros((len(X), len(self.cut)))
        for i in range(len(self.cut)):
            c = self.cut[i]
            t = self.terms[i]
            if len(c) == 0:
                contribs[:, i] = t[1]
                continue
            idx = np.searchsorted(c, X[:, i], side="right") + 1
            idx = np.clip(idx, 0, len(t) - 1)
            contribs[:, i] = t[idx]
        return contribs


def pava(term):
    """Isotonic projection of a 1-D array onto non-decreasing values (PAVA)."""
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
    x = np.arange(len(term))
    return iso.fit_transform(x, term)


def make_iso_scorer(ebm, X_train, y_train):
    """Monotonize an EBM after fitting: project each term table non-decreasing,
    then refit the intercept to restore the mean train logit."""
    base = EBMScorer(ebm)
    scorer = EBMScorer(ebm)
    scorer.terms = [pava(t.copy()) for t in base.terms]
    logit_old = np.log(np.clip(base.predict(X_train), 1e-12, 1 - 1e-12) /
                       np.clip(1 - base.predict(X_train), 1e-12, 1 - 1e-12))
    logit_new_no_int = logit_old - base.intercept + scorer.intercept
    delta = float(np.mean(logit_old - logit_new_no_int))
    scorer.intercept += delta
    return scorer, base


def certificate(scorer):
    """Count non-monotone adjacent cells in every term table. 0 = certified."""
    n_bad = 0
    for t in scorer.terms:
        n_bad += int(np.sum(np.diff(t) < -1e-12))
    return n_bad


def calibration_map(p_train, y_train):
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(p_train, y_train)
    return iso


def metric_row(y, p, y_cal=None, p_cal=None, boot=False):
    row = {
        "n": int(len(y)),
        "auroc": float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "ece_raw": F.ece(y, p),
    }
    if y_cal is not None:
        row["ece_cal"] = F.ece(y_cal, p_cal)
    if boot:
        m, lo, hi = F.bootstrap_auc(y, p)
        row["auroc_ci95"] = [round(lo, 4), round(hi, 4)]
    return row


def topterm_accuracy(scorer, X, causes, family):
    """Fraction of y=1 actions whose largest additive term belongs to the
    true cause's feature set (C2-style attribution)."""
    contribs = scorer.contributions(X)
    names = F.FEATURE_NAMES
    hits = 0
    total = 0
    per_cause = {}
    for r, cause in zip(contribs, causes):
        if cause == "clean":
            continue
        total += 1
        top = names[int(np.argmax(r))]
        ok = top in F.CAUSE_FEATURES.get(cause, [])
        hits += int(ok)
        per_cause.setdefault(cause, [0, 0])
        per_cause[cause][1] += 1
        per_cause[cause][0] += int(ok)
    if total == 0:
        return 0.0, 0, {}
    return hits / total, total, per_cause


def naive_topterm_accuracy(X, X_train, causes):
    """Baseline attribution: the feature with the highest train-percentile rank."""
    ranks = np.zeros_like(X)
    for j in range(X.shape[1]):
        ranks[:, j] = np.searchsorted(
            np.sort(X_train[:, j]), X[:, j], side="right") / max(1, len(X_train))
    names = F.FEATURE_NAMES
    hits = total = 0
    for r, cause in zip(ranks, causes):
        if cause == "clean":
            continue
        total += 1
        top = names[int(np.argmax(r))]
        hits += int(top in F.CAUSE_FEATURES.get(cause, []))
    return hits / total if total else 0.0, total


def main():
    t0 = time.time()
    print("loading splits...")
    train_l, test_id_l, test_shift_l = F.load_splits()
    X_tr, y_tr, ids_tr, causes_tr, fam_tr = F.build_dataset(train_l)
    X_id, y_id, ids_id, causes_id, fam_id = F.build_dataset(test_id_l)
    X_sh, y_sh, ids_sh, causes_sh, fam_sh = F.build_dataset(test_shift_l)
    print(f"train {X_tr.shape} id-test {X_id.shape} shifted-test {X_sh.shape} "
          f"({time.time()-t0:.0f}s)")

    models = {}

    logreg = LogisticRegression(C=1.0, max_iter=3000)
    logreg.fit(X_tr, y_tr)
    models["logreg"] = lambda X: logreg.predict_proba(X)[:, 1]

    ebm_free = ExplainableBoostingClassifier(interactions=0, max_bins=128,
                                             random_state=0)
    ebm_free.fit(X_tr, y_tr)
    models["ebm_free"] = EBMScorer(ebm_free).predict

    ebm_mono = ExplainableBoostingClassifier(interactions=0, max_bins=128,
                                             random_state=0,
                                             monotone_constraints=[1] * len(F.FEATURE_NAMES))
    ebm_mono.fit(X_tr, y_tr)
    scorer_mono = EBMScorer(ebm_mono)
    models["ebm_mono"] = scorer_mono.predict

    scorer_iso, _ = make_iso_scorer(ebm_free, X_tr, y_tr)
    models["ebm_mono_iso"] = scorer_iso.predict

    lgbm = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05,
                                           max_leaf_nodes=31, random_state=0)
    lgbm.fit(X_tr, y_tr)
    models["lgbm"] = lambda X: lgbm.predict_proba(X)[:, 1]

    print("models fit", flush=True)

    iso_map = calibration_map(models["ebm_mono"](X_tr), y_tr)

    results = {"datasets": {
        "train": {"n": int(len(y_tr)), "pos_rate": float(y_tr.mean())},
        "id": {"n": int(len(y_id)), "pos_rate": float(y_id.mean())},
        "shifted": {"n": int(len(y_sh)), "pos_rate": float(y_sh.mean())},
    }, "models": {}}

    for name, pred_fn in models.items():
        t1 = time.time()
        p_tr = pred_fn(X_tr)
        p_id = pred_fn(X_id)
        p_sh = pred_fn(X_sh)
        results["models"][name] = {
            "id": metric_row(y_id, p_id, y_id, iso_map.predict(p_id)),
            "shifted": metric_row(y_sh, p_sh, y_sh, iso_map.predict(p_sh), boot=True),
            "fit_predict_seconds": round(time.time() - t1, 2),
        }
        print(f"  {name}: id AUC {results['models'][name]['id']['auroc']:.4f} "
              f"shift AUC {results['models'][name]['shifted']['auroc']:.4f}", flush=True)

    # certificates
    results["certificate"] = {
        "ebm_mono_violations": certificate(scorer_mono),
        "ebm_mono_iso_violations": certificate(scorer_iso),
    }
    print("certificate: ebm_mono violations =", results["certificate"]["ebm_mono_violations"],
          "ebm_mono_iso violations =", results["certificate"]["ebm_mono_iso_violations"])

    # attribution (C2-style) on in-domain y=1 actions
    acc, tot, per_cause = topterm_accuracy(scorer_mono, X_id, causes_id, fam_id)
    acc_naive, _ = naive_topterm_accuracy(X_id, X_tr, causes_id)
    results["attribution"] = {
        "ebm_mono_topterm_accuracy": acc,
        "n_flagged": tot,
        "naive_rank_topterm_accuracy": acc_naive,
        "per_cause": {k: {"correct": v[0], "n": v[1]} for k, v in sorted(per_cause.items())},
    }
    print(f"attribution: EBM top-term {acc:.3f} vs naive rank {acc_naive:.3f} (n={tot})")

    # latency: full feature extraction + EBM predict, per action
    lats = []
    scorer = models["ebm_mono"]
    for ep, fam, fidx in test_shift_l[:40]:
        t1 = time.time()
        X, y, idx, c = F.extract_episode_features(ep, fam, file_idx=fidx)
        scorer(X)
        lats.append((time.time() - t1) / max(1, len(y)) * 1000.0)
    lats = np.asarray(lats)
    results["latency_ms_per_action"] = {
        "p50": float(np.percentile(lats, 50)),
        "p99": float(np.percentile(lats, 99)),
        "mean": float(lats.mean()),
    }
    print(f"latency per action (features + monotone EBM predict), CPU: "
          f"p50 {results['latency_ms_per_action']['p50']:.3f} ms "
          f"p99 {results['latency_ms_per_action']['p99']:.3f} ms")

    # feature means by family (evidence that the code checks carry the signal)
    feat_by_fam = {}
    for fam in F.FAMILIES:
        m = np.asarray(fam_tr) == fam
        if m.sum():
            feat_by_fam[fam] = dict(zip(F.FEATURE_NAMES, np.round(X_tr[m].mean(axis=0), 3).tolist()))
    results["feature_means_by_family"] = feat_by_fam

    # save predictions for the judge sample
    sample_ids = F.judge_sample_ids()
    lookup = {i: (x, y) for i, x, y in zip(ids_id, X_id, y_id)}
    lookup.update({i: (x, y) for i, x, y in zip(ids_sh, X_sh, y_sh)})
    sample_scores = {}
    for key in sample_ids:
        k = json.dumps(list(key))
        if key not in lookup:
            sample_scores[k] = None
            continue
        x, y = lookup[key]
        sample_scores[k] = {
            "y": int(y),
            "scores": {name: float(pred_fn(x.reshape(1, -1))[0]) for name, pred_fn in models.items()},
        }
    json.dump(sample_scores, open(RESULTS / "e1_sample_scores.json", "w"), indent=1)
    json.dump(results, open(RESULTS / "e1.json", "w"), indent=1)
    print("wrote results/e1.json and results/e1_sample_scores.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
