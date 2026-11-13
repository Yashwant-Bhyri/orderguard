"""Models: hashed-text logistic, JSON tree ensemble (pure-Python inference), numpy MLP with weight averaging, prototype memory, calibration."""
from __future__ import annotations

import math

import numpy as np

# ---- hashed text model -------------------------------------------------------------------------------------------------------


class TextModel:
    """Logistic regression over hashed word 1-2 grams. Weights are exported dense (HASH_DIM floats); logit(sparse) is a dot product."""

    def __init__(self, w: list[float], b: float):
        self.w, self.b = w, float(b)

    def logit(self, sp: dict) -> float:
        w = self.w
        return self.b + sum(v * w[k] for k, v in sp.items())

    def to_json(self) -> dict:
        return {"w": [round(x, 5) for x in self.w], "b": round(self.b, 5)}

    @classmethod
    def from_json(cls, d: dict) -> "TextModel":
        return cls(d["w"], d["b"])


def fit_text(csr, y, rows, C: float = 1.0, max_honest: int = 120_000, seed: int = 0) -> TextModel:
    from sklearn.linear_model import LogisticRegression
    rng = np.random.default_rng(seed)
    rows = np.asarray(rows)
    pos, neg = rows[y[rows] == 1], rows[y[rows] == 0]
    if len(neg) > max_honest:
        neg = rng.choice(neg, max_honest, replace=False)
    r = np.concatenate([pos, neg])
    clf = LogisticRegression(C=C, max_iter=200, class_weight="balanced").fit(csr[r], y[r])
    return TextModel([float(x) for x in clf.coef_[0]], float(clf.intercept_[0]))


def text_logit_matrix(csr, tm: TextModel) -> np.ndarray:
    return np.asarray(csr @ np.asarray(tm.w) + tm.b).ravel()


# ---- gradient-boosted trees -> JSON ------------------------------------------------------------------------------------------


class TreeEnsemble:
    """Pure-Python inference over trees exported from sklearn's HistGradientBoostingClassifier. raw() is the log-odds before calibration."""

    def __init__(self, base: float, trees: list[dict], names: list[str], platt: tuple[float, float] = (1.0, 0.0)):
        self.base, self.trees, self.names, self.platt = float(base), trees, names, tuple(platt)

    @classmethod
    def from_sklearn(cls, clf, names) -> "TreeEnsemble":
        trees = []
        for pred in clf._predictors:
            nd = pred[0].nodes
            n = len(nd)
            f = [int(x) if not leaf else -1 for x, leaf in zip(nd["feature_idx"], nd["is_leaf"])]
            exp = [0.0] * n
            cnt = nd["count"].astype(float)

            def rec(i):                                      # expected leaf value below each node (for attribution)
                if nd["is_leaf"][i]:
                    exp[i] = float(nd["value"][i])
                else:
                    a, b = rec(int(nd["left"][i])), rec(int(nd["right"][i]))
                    ca, cb = cnt[nd["left"][i]], cnt[nd["right"][i]]
                    exp[i] = (a * ca + b * cb) / max(ca + cb, 1.0)
                return exp[i]
            rec(0)
            trees.append({"f": f, "t": [float(x) for x in nd["num_threshold"]], "l": [int(x) for x in nd["left"]], "r": [int(x) for x in nd["right"]],
                          "v": [float(x) for x in nd["value"]], "e": exp})
        return cls(float(np.ravel(clf._baseline_prediction)[0]), trees, list(names))

    def raw(self, x) -> float:
        s = self.base
        for t in self.trees:
            f, th, l, r = t["f"], t["t"], t["l"], t["r"]
            n = 0
            k = f[0]
            while k >= 0:
                n = l[n] if x[k] <= th[n] else r[n]
                k = f[n]
            s += t["v"][n]
        return s

    def prob(self, raw: float) -> float:
        a, b = self.platt
        z = a * raw + b
        return 1.0 / (1.0 + math.exp(-z)) if z > -700 else 0.0

    def contributions(self, x) -> list[tuple[float, int]]:
        """Saabas path attribution: per-feature sum of (expected value of child - expected value of node) along each tree's path."""
        c: dict[int, float] = {}
        for t in self.trees:
            f, th, l, r, e = t["f"], t["t"], t["l"], t["r"], t["e"]
            n = 0
            while f[n] >= 0:
                k = f[n]
                m = l[n] if x[k] <= th[n] else r[n]
                c[k] = c.get(k, 0.0) + (e[m] - e[n])
                n = m
        return sorted(((v, k) for k, v in c.items()), reverse=True)

    def to_json(self) -> dict:
        return {"base": self.base, "names": self.names, "platt": list(self.platt), "trees": self.trees}

    @classmethod
    def from_json(cls, d: dict) -> "TreeEnsemble":
        return cls(d["base"], d["trees"], d["names"], tuple(d["platt"]))


def fit_platt(raw: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> tuple[float, float]:
    from sklearn.linear_model import LogisticRegression
    lr = LogisticRegression(C=1e4, max_iter=200).fit(raw.reshape(-1, 1), y, sample_weight=w)
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def fit_trees(X, y, w=None, *, iters: int = 80, depth: int = 5, lr: float = 0.15, seed: int = 0, names=None):
    from sklearn.ensemble import HistGradientBoostingClassifier
    clf = HistGradientBoostingClassifier(max_iter=iters, max_depth=depth, learning_rate=lr, max_leaf_nodes=16, min_samples_leaf=40, l2_regularization=1.0,
                                         early_stopping=False, random_state=seed)
    clf.fit(X, y, sample_weight=w)
    return clf


# ---- MLP -------------------------------------------------------------------------------------------------------------------------


class Prep:
    """signed log1p then z-score by honest-train statistics, clipped. Same transform for MLP and prototype embedding."""

    def __init__(self, mu=None, sd=None):
        self.mu, self.sd = mu, sd

    @staticmethod
    def _t(X):
        return np.sign(X) * np.log1p(np.abs(X))

    def fit(self, X):
        T = self._t(X.astype(np.float64))
        self.mu, self.sd = T.mean(0), T.std(0) + 1e-6
        return self

    def __call__(self, X):
        return np.clip((self._t(np.asarray(X, np.float64)) - self.mu) / self.sd, -6, 6).astype(np.float32)

    def to_json(self):
        return {"mu": [float(x) for x in self.mu], "sd": [float(x) for x in self.sd]}

    @classmethod
    def from_json(cls, d):
        return cls(np.array(d["mu"]), np.array(d["sd"]))


class MLP:
    def __init__(self, sizes=(39, 48, 24, 1), seed=0, params=None):
        self.sizes = sizes
        if params is None:
            rng = np.random.default_rng(seed)
            params = {}
            for i, (a, b) in enumerate(zip(sizes[:-1], sizes[1:])):
                params[f"W{i}"] = (rng.standard_normal((a, b)) * math.sqrt(2.0 / a)).astype(np.float32)
                params[f"b{i}"] = np.zeros(b, np.float32)
        self.p = params

    def copy(self) -> "MLP":
        return MLP(self.sizes, params={k: v.copy() for k, v in self.p.items()})

    def logit(self, X):
        h = X
        L = len(self.sizes) - 1
        for i in range(L):
            h = h @ self.p[f"W{i}"] + self.p[f"b{i}"]
            if i < L - 1:
                h = np.maximum(h, 0)
        return h[:, 0]

    def fit(self, X, y, w, epochs=4, lr=2e-3, bs=2048, seed=0, ema: float | None = None):
        """Adam on weighted BCE. With `ema`, returns the exponential moving average of the weights across steps (a within-run soup)."""
        rng = np.random.default_rng(seed)
        L = len(self.sizes) - 1
        m = {k: np.zeros_like(v) for k, v in self.p.items()}
        v2 = {k: np.zeros_like(v) for k, v in self.p.items()}
        t = 0
        avg = {k: v.copy() for k, v in self.p.items()} if ema else None
        n = len(X)
        for _ in range(epochs):
            perm = rng.permutation(n)
            for s in range(0, n, bs):
                ix = perm[s:s + bs]
                xb, yb, wb = X[ix], y[ix].astype(np.float32), w[ix].astype(np.float32)
                hs = [xb]
                h = xb
                for i in range(L):
                    h = h @ self.p[f"W{i}"] + self.p[f"b{i}"]
                    if i < L - 1:
                        h = np.maximum(h, 0)
                    hs.append(h)
                pr = 1.0 / (1.0 + np.exp(-np.clip(h[:, 0], -30, 30)))
                g = ((pr - yb) * wb / wb.sum())[:, None]
                t += 1
                for i in reversed(range(L)):
                    gW, gb = hs[i].T @ g, g.sum(0)
                    if i > 0:
                        g = (g @ self.p[f"W{i}"].T) * (hs[i] > 0)
                    for k, gr in ((f"W{i}", gW), (f"b{i}", gb)):
                        m[k] = 0.9 * m[k] + 0.1 * gr
                        v2[k] = 0.999 * v2[k] + 0.001 * gr * gr
                        self.p[k] -= lr * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v2[k] / (1 - 0.999 ** t)) + 1e-8)
                if avg is not None:
                    for k in avg:
                        avg[k] = ema * avg[k] + (1 - ema) * self.p[k]
        if avg is not None:
            self.p = avg
        return self

    def to_json(self):
        return {"sizes": list(self.sizes), "p": {k: np.round(v, 5).tolist() for k, v in self.p.items()}}

    @classmethod
    def from_json(cls, d):
        return cls(tuple(d["sizes"]), params={k: np.array(v, np.float32) for k, v in d["p"].items()})


def soup(models: list[MLP], weights=None) -> MLP:
    """Uniform (or weighted) weight average of MLPs sharing an initialisation."""
    w = np.ones(len(models)) / len(models) if weights is None else np.asarray(weights) / np.sum(weights)
    return MLP(models[0].sizes, params={k: sum(float(wi) * m.p[k] for wi, m in zip(w, models)) for k in models[0].p})


# ---- one-shot prototype memory -------------------------------------------------------------------------------------------------


class PrototypeMemory:
    """Analyst-labelled attack events embedded in the standardised feature space. similarity(x) in (0, 1] is exp(-d^2 / (2 h^2)) to the nearest
    prototype, with d the weighted Euclidean distance. A similarity above `tau` raises the risk to `lift` (it can only raise it).
    h is set from the honest data (median honest distance to the prototype scale) so a prototype is neither a point nor the whole space."""

    def __init__(self, prep: Prep, weights: np.ndarray, h: float = 1.0, tau: float = 0.5):
        self.prep, self.wt, self.h, self.tau = prep, np.asarray(weights, np.float32), float(h), float(tau)
        self.protos: list[np.ndarray] = []
        self.notes: list[str] = []

    def embed(self, X) -> np.ndarray:
        return self.prep(X) * self.wt

    def add(self, x, note: str = "") -> None:
        self.protos.append(self.embed(np.asarray(x, np.float64).reshape(1, -1))[0])
        self.notes.append(note)

    def similarity(self, X) -> np.ndarray:
        X = np.atleast_2d(X)
        if not self.protos:
            return np.zeros(len(X))
        E = self.embed(X)
        P = np.stack(self.protos)
        d2 = ((E[:, None, :] - P[None]) ** 2).sum(-1).min(1)
        return np.exp(-d2 / (2 * self.h ** 2))

    def sim_one(self, x) -> float:
        if not self.protos:
            return 0.0
        e = (np.sign(x) * np.log1p(np.abs(x)) - self.prep.mu) / self.prep.sd
        e = np.clip(e, -6, 6) * self.wt
        d2 = min(float(((e - p) ** 2).sum()) for p in self.protos)
        return math.exp(-d2 / (2 * self.h ** 2))


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error with equal-mass bins."""
    if len(p) == 0:
        return 0.0
    o = np.argsort(p)
    e = 0.0
    for ch in np.array_split(o, bins):
        if len(ch):
            e += len(ch) / len(p) * abs(p[ch].mean() - y[ch].mean())
    return float(e)
