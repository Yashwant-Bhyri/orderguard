"""OrderGuard System One model zoo.

Every model implements ``fit(X, y, groups)``, ``predict_proba(X)`` and
``explain(X)``.  ``explain`` returns per-feature contributions to the risk
logit (``logit P(y=1)``), so a larger value means more risk.  ``groups`` may be
a ``{feature_name: group}`` mapping such as ``og_s1.checks.GROUPS`` or a
per-feature sequence of group labels; per-sample groups are accepted but only
stored.

All models are calibrated on the calibration split supplied through the
``calibration=(X_cal, y_cal)`` keyword.  ``fit`` without it falls back to
in-sample Platt scaling.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

EPS = 1e-6

FACTOR_GROUPS: dict[str, tuple[str, ...] | None] = {
    "evidence_credibility": ("evidence_quality",),
    "reasoning": ("unsupported_claim", "misquote", "stale_thesis"),
    "objective_fit": ("drift",),
    "owner_fit": ("poisoned_note", "authority_spoof"),
    "unexplained_residual": None,
}

FACTOR_NAMES = tuple(FACTOR_GROUPS)


def _clip01(values: Any, eps: float = EPS) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), eps, 1.0 - eps)


def _feature_group_map(
    groups: Any,
    n_features: int,
    feature_names: Sequence[str] | None = None,
) -> dict[int, str]:
    if groups is None:
        return {}
    if isinstance(groups, Mapping):
        if all(isinstance(k, (int, np.integer)) for k in groups):
            return {int(k): str(v) for k, v in groups.items()}
        if feature_names is not None:
            names = list(feature_names)
            out = {j: str(groups[names[j]]) for j in range(min(n_features, len(names))) if names[j] in groups}
            if out:
                return out
        try:
            return {int(k): str(v) for k, v in groups.items()}
        except (TypeError, ValueError):
            return {}
    seq = list(groups)
    if len(seq) == n_features and all(isinstance(v, str) for v in seq):
        return {i: str(v) for i, v in enumerate(seq)}
    return {}


def fit_platt(scores: Any, y: Any) -> tuple[float, float]:
    s = np.asarray(scores, dtype=float).ravel()
    target = np.asarray(y, dtype=float).ravel()
    if s.size == 0 or np.unique(target).size < 2:
        p = float(np.clip(target.mean() if target.size else 0.5, EPS, 1.0 - EPS))
        return 0.0, float(logit(p))
    mean = float(s.mean())
    std = float(s.std()) or 1.0
    z = (s - mean) / std

    def objective(theta: np.ndarray) -> float:
        a, b = float(theta[0]), float(theta[1])
        t = a * z + b
        return float(np.mean(np.logaddexp(0.0, t) - target * t))

    result = minimize(
        objective,
        x0=np.array([1.0, 0.0]),
        method="L-BFGS-B",
        bounds=[(1e-6, None), (None, None)],
    )
    a = float(result.x[0])
    b = float(result.x[1])
    return a / std, b - a * mean / std


def _isotonic(scores: Any, y: Any) -> IsotonicRegression:
    s = np.asarray(scores, dtype=float).ravel()
    target = np.asarray(y, dtype=float).ravel()
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip", y_min=EPS, y_max=1.0 - EPS)
    return iso.fit(s, target)


def _fit_nonneg_logistic(
    X: np.ndarray,
    y: np.ndarray,
    l2: float = 1e-2,
    maxiter: int = 500,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, d = X.shape
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0.0] = 1.0
    Z = (X - mean) / std
    base = float(np.clip(y.mean(), 1e-4, 1.0 - 1e-4))

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        w = theta[:d]
        b = float(theta[d])
        t = Z @ w + b
        p = expit(t)
        loss = float(np.mean(np.logaddexp(0.0, t) - y * t) + 0.5 * l2 * float(w @ w))
        grad_w = Z.T @ (p - y) / n + l2 * w
        grad_b = float(np.mean(p - y))
        return loss, np.concatenate([grad_w, np.array([grad_b])])

    x0 = np.zeros(d + 1)
    x0[d] = float(logit(base))
    result = minimize(
        objective,
        x0=x0,
        jac=True,
        method="L-BFGS-B",
        bounds=[(0.0, None)] * d + [(None, None)],
        options={"maxiter": maxiter},
    )
    return mean, std, result.x[:d].copy(), float(result.x[d])


class BaseModel:
    name = "base"

    def fit(self, X: Any, y: Any, groups: Any = None, *, calibration: Any = None, feature_names: Sequence[str] | None = None) -> "BaseModel":
        raise NotImplementedError

    def predict_proba(self, X: Any) -> np.ndarray:
        raise NotImplementedError

    def explain(self, X: Any) -> np.ndarray:
        raise NotImplementedError

    def score_with_and_without(self, X: Any, text_feature_idx: Any, baseline: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        X = np.asarray(X, dtype=float)
        idx = np.atleast_1d(np.asarray(text_feature_idx, dtype=int))
        without = X.copy()
        without[:, idx] = float(baseline)
        return self.predict_proba(X), self.predict_proba(without)


class LogisticModel(BaseModel):
    name = "logistic"

    def __init__(self, C: float = 1.0, random_state: int = 0):
        self.C = float(C)
        self.random_state = int(random_state)

    def fit(self, X: Any, y: Any, groups: Any = None, *, calibration: Any = None, feature_names: Sequence[str] | None = None) -> "LogisticModel":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.n_features_ = int(X.shape[1])
        self.feature_names_ = list(feature_names) if feature_names is not None else [f"f{i}" for i in range(self.n_features_)]
        self.feature_groups_ = _feature_group_map(groups, self.n_features_, self.feature_names_)
        self.scaler_ = StandardScaler().fit(X)
        self.clf_ = LogisticRegression(
            C=self.C,
            solver="lbfgs",
            max_iter=5000,
            random_state=self.random_state,
        ).fit(self.scaler_.transform(X), y)
        if calibration is None:
            Xc, yc = X, y
        else:
            Xc, yc = calibration
        self.platt_a_, self.platt_b_ = fit_platt(self._decision(Xc), yc)
        self.base_ = self.platt_a_ * float(self.clf_.intercept_[0]) + self.platt_b_
        return self

    def _decision(self, X: Any) -> np.ndarray:
        return self.clf_.decision_function(self.scaler_.transform(np.asarray(X, dtype=float)))

    def predict_proba(self, X: Any) -> np.ndarray:
        return expit(self.platt_a_ * self._decision(X) + self.platt_b_)

    def explain(self, X: Any) -> np.ndarray:
        Z = self.scaler_.transform(np.asarray(X, dtype=float))
        coef = self.platt_a_ * self.clf_.coef_.ravel()
        return Z * coef[None, :]


class EBMModel(BaseModel):
    name = "ebm"

    def __init__(
        self,
        interactions: int = 10,
        max_bins: int = 256,
        outer_bags: int = 4,
        learning_rate: float = 0.02,
        max_rounds: int = 3000,
        early_stopping_rounds: int = 50,
        random_state: int = 0,
        n_jobs: int = 1,
    ):
        self.interactions = int(interactions)
        self.max_bins = int(max_bins)
        self.outer_bags = int(outer_bags)
        self.learning_rate = float(learning_rate)
        self.max_rounds = int(max_rounds)
        self.early_stopping_rounds = int(early_stopping_rounds)
        self.random_state = int(random_state)
        # One thread makes the EBM bit-reproducible across runs.  The outer bags
        # run sequentially; the reported fit is deterministic given the seed.
        self.n_jobs = int(n_jobs)

    def fit(self, X: Any, y: Any, groups: Any = None, *, calibration: Any = None, feature_names: Sequence[str] | None = None) -> "EBMModel":
        from interpret.glassbox import ExplainableBoostingClassifier

        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.n_features_ = int(X.shape[1])
        self.feature_names_ = list(feature_names) if feature_names is not None else [f"f{i}" for i in range(self.n_features_)]
        self.feature_groups_ = _feature_group_map(groups, self.n_features_, self.feature_names_)
        self.clf_ = ExplainableBoostingClassifier(
            feature_names=self.feature_names_,
            feature_types=["continuous"] * self.n_features_,
            interactions=self.interactions,
            max_bins=self.max_bins,
            outer_bags=self.outer_bags,
            learning_rate=self.learning_rate,
            max_rounds=self.max_rounds,
            early_stopping_rounds=self.early_stopping_rounds,
            monotone_constraints=[1] * self.n_features_,
            random_state=self.random_state,
            n_jobs=self.n_jobs,
            validation_size=0.1,
        ).fit(X, y)
        self.n_interaction_terms_configured_ = int(self.interactions)
        self.interactions_removed_ = enforce_additivity(self.clf_)
        monotonise_ebm(self.clf_)
        if calibration is None:
            Xc, yc = X, y
        else:
            Xc, yc = calibration
        Xc = np.asarray(Xc, dtype=float)
        self.certificate_X_ = Xc[: min(256, Xc.shape[0])].copy()
        self.additivity_max_error_ = additivity_error(self.clf_, self.certificate_X_)
        self.platt_a_, self.platt_b_ = fit_platt(self._raw_logit(Xc), yc)
        self.base_ = self.platt_a_ * float(self.clf_.intercept_[0]) + self.platt_b_
        return self

    def _raw_logit(self, X: Any) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if hasattr(self.clf_, "decision_function"):
            return np.asarray(self.clf_.decision_function(X), dtype=float)
        p = _clip01(self.clf_.predict_proba(X)[:, 1])
        return logit(p)

    def predict_proba(self, X: Any) -> np.ndarray:
        return expit(self.platt_a_ * self._raw_logit(X) + self.platt_b_)

    def explain(self, X: Any) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if any(len(features) != 1 for features in self.clf_.term_features_):
            raise RuntimeError("EBM is not additive; the certificate is invalid")
        terms = np.asarray(self.clf_.eval_terms(X), dtype=float)
        out = np.zeros((X.shape[0], self.n_features_), dtype=float)
        for term_idx, features in enumerate(self.clf_.term_features_):
            out[:, int(features[0])] += terms[:, term_idx]
        return self.platt_a_ * out

    def monotonicity_report(self) -> tuple[bool, list[dict[str, Any]]]:
        ok, details, self.certificate_ = check_ebm_certificate(
            self.clf_,
            X_check=getattr(self, "certificate_X_", None),
            interactions_removed=getattr(self, "interactions_removed_", None),
        )
        return ok, details


class BoostedTreesModel(BaseModel):
    def __init__(
        self,
        monotone: bool = False,
        max_iter: int = 200,
        learning_rate: float = 0.1,
        max_leaf_nodes: int = 31,
        min_samples_leaf: int = 20,
        l2_regularization: float = 0.0,
        random_state: int = 0,
    ):
        self.monotone = bool(monotone)
        self.name = "hgb_monotone" if self.monotone else "hgb"
        self.max_iter = int(max_iter)
        self.learning_rate = float(learning_rate)
        self.max_leaf_nodes = int(max_leaf_nodes)
        self.min_samples_leaf = int(min_samples_leaf)
        self.l2_regularization = float(l2_regularization)
        self.random_state = int(random_state)

    def fit(self, X: Any, y: Any, groups: Any = None, *, calibration: Any = None, feature_names: Sequence[str] | None = None) -> "BoostedTreesModel":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.n_features_ = int(X.shape[1])
        self.feature_names_ = list(feature_names) if feature_names is not None else [f"f{i}" for i in range(self.n_features_)]
        self.feature_groups_ = _feature_group_map(groups, self.n_features_, self.feature_names_)
        constraints = [1] * self.n_features_ if self.monotone else None
        self.clf_ = HistGradientBoostingClassifier(
            max_iter=self.max_iter,
            learning_rate=self.learning_rate,
            max_leaf_nodes=self.max_leaf_nodes,
            min_samples_leaf=self.min_samples_leaf,
            l2_regularization=self.l2_regularization,
            monotonic_cst=constraints,
            early_stopping=True,
            validation_fraction=0.1,
            n_iter_no_change=10,
            random_state=self.random_state,
        ).fit(X, y)
        self._explainer = None
        if calibration is None:
            Xc, yc = X, y
        else:
            Xc, yc = calibration
        self.platt_a_, self.platt_b_ = fit_platt(self.clf_.decision_function(Xc), yc)
        return self

    def predict_proba(self, X: Any) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        return expit(self.platt_a_ * self.clf_.decision_function(X) + self.platt_b_)

    def _shap_values(self, X: np.ndarray) -> np.ndarray:
        if self._explainer is None:
            import shap

            self._explainer = shap.TreeExplainer(self.clf_)
        values = np.asarray(self._explainer.shap_values(X), dtype=float)
        if values.ndim == 3:
            values = values[:, :, 1]
        if values.ndim == 1:
            values = values.reshape(1, -1)
        if values.shape[1] != self.n_features_ and values.shape[0] == self.n_features_:
            values = values.T
        return values

    def explain(self, X: Any) -> np.ndarray:
        return self.platt_a_ * self._shap_values(np.asarray(X, dtype=float))


class _Factor:
    def __init__(
        self,
        name: str,
        indices: np.ndarray,
        mean: np.ndarray,
        std: np.ndarray,
        weights: np.ndarray,
        bias: float,
        iso: IsotonicRegression,
    ):
        self.name = name
        self.indices = indices
        self.mean = mean
        self.std = std
        self.weights = weights
        self.bias = bias
        self.iso = iso

    def raw(self, X: np.ndarray) -> np.ndarray:
        Z = (X[:, self.indices] - self.mean) / self.std
        return Z @ self.weights + self.bias

    def prob(self, X: np.ndarray) -> np.ndarray:
        return _clip01(self.iso.predict(self.raw(X)))


class NoisyAndModel(BaseModel):
    name = "noisy_and"

    def __init__(self, l2: float = 1e-2, random_state: int = 0):
        self.l2 = float(l2)
        self.random_state = int(random_state)

    def fit(self, X: Any, y: Any, groups: Any = None, *, calibration: Any = None, feature_names: Sequence[str] | None = None) -> "NoisyAndModel":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.n_features_ = int(X.shape[1])
        self.feature_names_ = list(feature_names) if feature_names is not None else [f"f{i}" for i in range(self.n_features_)]
        self.feature_groups_ = _feature_group_map(groups, self.n_features_, self.feature_names_)
        if calibration is None:
            Xc, yc = X, y
        else:
            Xc, yc = calibration
        self.factors_: list[_Factor] = []
        for name, group_names in FACTOR_GROUPS.items():
            if group_names is None:
                indices = np.arange(self.n_features_, dtype=int)
            else:
                indices = np.array(
                    [j for j in range(self.n_features_) if self.feature_groups_.get(j) in group_names],
                    dtype=int,
                )
            if indices.size == 0:
                continue
            mean, std, weights, bias = _fit_nonneg_logistic(X[:, indices], y, l2=self.l2)
            raw_cal = ((Xc[:, indices] - mean) / std) @ weights + bias
            iso = _isotonic(raw_cal, yc)
            self.factors_.append(_Factor(name, indices, mean, std, weights, bias, iso))
        self.factor_names_ = tuple(f.name for f in self.factors_)
        self.platt_a_, self.platt_b_ = fit_platt(self._raw_risk_logit(Xc), yc)
        self.base_ = None
        return self

    def _factor_probs(self, X: Any) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        return np.column_stack([f.prob(X) for f in self.factors_]) if self.factors_ else np.zeros((X.shape[0], 0))

    def _risk_parts(self, X: Any) -> tuple[np.ndarray, np.ndarray]:
        probs = self._factor_probs(X)
        if probs.size == 0:
            n = np.asarray(X).shape[0]
            return probs, np.zeros(n, dtype=float)
        endorse = np.prod(1.0 - probs, axis=1)
        base = np.log(np.clip(1.0 - endorse, EPS, 1.0))
        contributions = -np.log(1.0 - probs)
        return probs, base + contributions.sum(axis=1)

    def _raw_risk_logit(self, X: Any) -> np.ndarray:
        return self._risk_parts(X)[1]

    def predict_proba(self, X: Any) -> np.ndarray:
        return expit(self.platt_a_ * self._raw_risk_logit(X) + self.platt_b_)

    def factor_contributions(self, X: Any) -> np.ndarray:
        probs = self._factor_probs(X)
        if probs.size == 0:
            return np.zeros((np.asarray(X).shape[0], 0), dtype=float)
        return self.platt_a_ * (-np.log(1.0 - probs))

    def _base_raw(self, X: Any) -> np.ndarray:
        probs = self._factor_probs(X)
        if probs.size == 0:
            return np.zeros(np.asarray(X).shape[0], dtype=float)
        endorse = np.prod(1.0 - probs, axis=1)
        return np.log(np.clip(1.0 - endorse, EPS, 1.0))

    def explain(self, X: Any) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        probs = self._factor_probs(X)
        out = np.zeros((X.shape[0], self.n_features_), dtype=float)
        if probs.size == 0:
            return out
        contributions = -np.log(1.0 - probs)
        for k, factor in enumerate(self.factors_):
            Z = (X[:, factor.indices] - factor.mean) / factor.std
            active = np.maximum(factor.weights[None, :] * Z, 0.0)
            mass = active.sum(axis=1)
            weights = np.zeros_like(active)
            nonzero = mass > 0.0
            weights[nonzero] = active[nonzero] / mass[nonzero, None]
            if np.any(~nonzero):
                positive = np.maximum(factor.weights, 0.0)
                total = float(positive.sum())
                if total > 0.0:
                    weights[~nonzero] = positive / total
                else:
                    weights[~nonzero] = 1.0 / len(factor.indices)
            out[:, factor.indices] += contributions[:, k][:, None] * weights
        return self.platt_a_ * out


def monotonise_ebm(clf: Any) -> None:
    for term_idx, features in enumerate(clf.term_features_):
        if len(features) != 1:
            continue
        try:
            edges = np.asarray(clf.bins_[term_idx][0], dtype=float)
        except (IndexError, TypeError):
            continue
        scores = np.asarray(clf.term_scores_[term_idx], dtype=float).copy()
        n_valid = min(len(edges) + 1, len(scores) - 1)
        if n_valid <= 1:
            continue
        scores[1 : 1 + n_valid] = np.maximum.accumulate(scores[1 : 1 + n_valid])
        clf.term_scores_[term_idx] = scores


def check_ebm_monotonicity(clf: Any, tol: float = 1e-9) -> tuple[bool, list[dict[str, Any]]]:
    details: list[dict[str, Any]] = []
    ok = True
    for term_idx, features in enumerate(clf.term_features_):
        if len(features) != 1:
            continue
        name = clf.term_names_[term_idx]
        try:
            edges = np.asarray(clf.bins_[term_idx][0], dtype=float)
        except (IndexError, TypeError):
            details.append({"term": name, "bins": 0, "min_diff": 0.0, "monotone": True})
            continue
        scores = np.asarray(clf.term_scores_[term_idx], dtype=float)
        n_valid = min(len(edges) + 1, len(scores) - 1)
        if n_valid <= 1:
            details.append({"term": name, "bins": int(max(n_valid, 0)), "min_diff": 0.0, "monotone": True})
            continue
        diffs = np.diff(scores[1 : 1 + n_valid])
        min_diff = float(diffs.min()) if diffs.size else 0.0
        passed = bool(np.all(diffs >= -tol))
        ok = ok and passed
        details.append({"term": name, "bins": int(n_valid), "min_diff": min_diff, "monotone": passed})
    return ok, details


def enforce_additivity(clf: Any) -> int:
    """Remove every interaction term and prove that the result is additive.

    ``interpret`` 0.7.8 appends interaction terms after the main effects and
    ``remove_terms`` does not update ``bins_``.  We therefore (a) require that
    every interaction is appended after all main effects, (b) remove exactly
    those trailing terms, and (c) assert that the remaining terms are all
    univariate and that ``bins_`` still aligns one-to-one with them.  An error
    is raised rather than swallowed: a certificate over the wrong bins would be
    worse than a failed run.
    """
    term_features = list(clf.term_features_)
    n_main = sum(1 for features in term_features if len(features) == 1)
    n_inter = len(term_features) - n_main
    if any(len(features) != 1 for features in term_features[:n_main]):
        raise RuntimeError("EBM interaction terms are not appended after the main effects")
    if n_inter == 0:
        if len(clf.bins_) != n_main:
            raise RuntimeError(
                f"EBM bins_ has {len(clf.bins_)} entries but there are {n_main} main effects"
            )
        return 0
    try:
        clf.remove_terms(list(range(n_main, len(term_features))))
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError("could not remove EBM interaction terms") from exc
    remaining = list(clf.term_features_)
    if len(remaining) != n_main or any(len(features) != 1 for features in remaining):
        raise RuntimeError("EBM still has interaction terms after removal")
    if len(clf.bins_) != n_main:
        raise RuntimeError(
            f"EBM bins_ has {len(clf.bins_)} entries after removal but there are {n_main} main effects"
        )
    return n_inter


def additivity_error(clf: Any, X: np.ndarray) -> float:
    """Maximum absolute gap between the additive term sum and the fitted logit."""
    X = np.asarray(X, dtype=float)
    if X.shape[0] == 0:
        return 0.0
    terms = np.asarray(clf.eval_terms(X), dtype=float)
    lhs = terms.sum(axis=1) + float(clf.intercept_[0])
    if hasattr(clf, "decision_function"):
        rhs = np.asarray(clf.decision_function(X), dtype=float)
    else:
        rhs = logit(_clip01(clf.predict_proba(X)[:, 1]))
    return float(np.max(np.abs(lhs - rhs)))


def check_ebm_certificate(
    clf: Any,
    X_check: np.ndarray | None = None,
    interactions_removed: int | None = None,
    tol: float = 1e-9,
) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    """Prove monotonicity per bin and additivity of the fitted EBM.

    Returns ``(ok, per_term_details, summary)``.  ``ok`` is true only when every
    term is univariate, ``bins_`` aligns with the terms, every main-effect bin
    sequence is non-decreasing, and (when ``X_check`` is supplied) the additive
    term sum reproduces the model logit within ``1e-8``.
    """
    n_terms = len(clf.term_features_)
    n_main = sum(1 for features in clf.term_features_ if len(features) == 1)
    univariate = n_terms == n_main
    bins_aligned = len(clf.bins_) == n_main
    shapes_aligned = True
    for i in range(n_main):
        try:
            # interpret stores one missing-bin score and one trailing sentinel
            # around the len(bins)+1 real bins for a univariate term.
            shapes_aligned = shapes_aligned and (
                len(clf.term_scores_[i]) == len(clf.bins_[i][0]) + 3
            )
        except (IndexError, TypeError):
            shapes_aligned = False
    mono_ok, details = check_ebm_monotonicity(clf, tol=tol)
    if not univariate:
        details.append({"term": "<interaction>", "bins": 0, "min_diff": 0.0, "monotone": False})
    add_err = additivity_error(clf, X_check) if X_check is not None else None
    additivity_ok = add_err is None or add_err <= 1e-8
    summary = {
        "n_terms": int(n_terms),
        "n_main_effects": int(n_main),
        "univariate": bool(univariate),
        "bins_aligned": bool(bins_aligned),
        "bins_shapes_aligned": bool(shapes_aligned),
        "interactions_removed": int(interactions_removed) if interactions_removed is not None else None,
        "additivity_max_error": float(add_err) if add_err is not None else None,
        "features_checked": int(len(details)),
        "all_bins_monotone": bool(mono_ok),
    }
    ok = bool(univariate and bins_aligned and shapes_aligned and mono_ok and additivity_ok)
    return ok, details, summary


def make_models(seed: int, hyperparameters: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, BaseModel]:
    hp = dict(hyperparameters or {})
    logistic_hp = dict(hp.get("logistic", {}))
    hgb_hp = dict(hp.get("hgb", {}))
    hgb_mono_hp = dict(hp.get("hgb_monotone", {}))
    noisy_hp = dict(hp.get("noisy_and", {}))
    ebm_hp = dict(hp.get("ebm", {}))
    return {
        "logistic": LogisticModel(C=float(logistic_hp.get("C", 1.0)), random_state=seed),
        "ebm": EBMModel(random_state=seed, **ebm_hp),
        "hgb": BoostedTreesModel(monotone=False, random_state=seed, **hgb_hp),
        "hgb_monotone": BoostedTreesModel(monotone=True, random_state=seed, **hgb_mono_hp),
        "noisy_and": NoisyAndModel(l2=float(noisy_hp.get("l2", 1e-2)), random_state=seed),
    }
