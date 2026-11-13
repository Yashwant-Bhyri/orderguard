"""Feature matrix, splits and fit/predict helpers shared by training and evaluation."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from . import dataset as D
from . import features as F
from . import models as M
from .text import HASH_DIM, hashed_ngrams

IX_TEXT = F.IX["text_logit"]
TEXT_COLS = [F.IX[n] for n in ("text_logit", "stated_ratio", "has_stated", "script_dup")]
CROSS_COLS = [F.IX[n] for n in ("xa_short", "xa_med", "xa_near_env", "sizesim", "same_step", "strong_nbrs", "strong_frac", "side_pressure", "ticker_flow")] + TEXT_COLS
ENV_COLS = [F.IX[n] for n in ("cap_ratio", "stepup_ratio", "log_notional", "near_cap", "order_share_daily", "limit_dev", "band_pos", "listed", "is_transfer", "trig")]


@dataclass
class Data:
    cols: dict
    metas: list
    X: np.ndarray
    csr: object
    y: np.ndarray                      # 1 = any bad label
    fam: np.ndarray                    # family name per row
    pop: np.ndarray                    # gate-allowed, not an idempotent replay: the population the model is judged on
    run: np.ndarray
    step: np.ndarray
    regime: np.ndarray
    notional: np.ndarray
    spd: int = 500
    env_specs: dict = field(default_factory=dict)

    def runs_where(self, f) -> np.ndarray:
        return np.array([m["run"] for m in self.metas if f(m["spec"])])


def load_data(path=None, cache: bool = True) -> Data:
    import scipy.sparse as sp
    cols, metas = D.load(path) if path else D.load_corpus()
    n = len(cols["run"])
    cpath = D.DATA_DIR / ".cache" / f"feat-{n}.npz"
    if cache and cpath.exists():
        z = np.load(cpath)
        X = z["X"]
        csr = sp.csr_matrix((z["data"], z["indices"], z["indptr"]), shape=(n, HASH_DIM))
    else:
        tx = D.texts(cols)
        es, spd = env_specs_of(metas), {m["run"]: m["spec"]["steps_per_day"] for m in metas}
        X = F.build_matrix(cols, tx, es, spd)
        indptr, ind, dat = [0], [], []
        for t in tx:
            h = hashed_ngrams(t)
            ind.extend(h.keys())
            dat.extend(h.values())
            indptr.append(len(ind))
        csr = sp.csr_matrix((np.array(dat, np.float32), np.array(ind, np.int32), np.array(indptr, np.int64)), shape=(n, HASH_DIM))
        if cache:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            np.savez(cpath, X=X, data=csr.data, indices=csr.indices, indptr=csr.indptr)
    lab = np.array(D.LABELS)[cols["label"]]
    fam = np.array([D.FAMILY[l] for l in D.LABELS])[cols["label"]]
    regime = {m["run"]: m["spec"]["regime"] for m in metas}
    return Data(cols, metas, X, csr, (lab != "legit").astype(np.int8), fam, (cols["dec"] == 0) & ~cols["replay"], cols["run"], cols["step"],
                np.array([regime[r] for r in cols["run"]]), cols["notional"].astype(np.float64), env_specs=env_specs_of(metas))


def env_specs_of(metas) -> dict:
    return {m["run"]: {e["name"]: e for e in m["envelopes"]} for m in metas}


def seed_split(d: Data, test_every: int = 4, val_every: int = 7) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    runs = sorted({m["run"] for m in d.metas})
    test = [r for r in runs if r % test_every == 1]
    val = [r for r in runs if r % val_every == 3 and r not in test]
    train = [r for r in runs if r not in test and r not in val]
    return tuple(np.isin(d.run, g) for g in (train, val, test))


@dataclass
class Fitted:
    kind: str
    tm: M.TextModel | None
    ens: M.TreeEnsemble | None
    mlp: M.MLP | None
    prep: M.Prep | None
    cols: list
    t_hold: float = 1.0
    t_refuse: float = 1.0
    info: dict = field(default_factory=dict)


def text_column(d: Data, rows: np.ndarray, train_rows: np.ndarray, fold_runs: np.ndarray, seed: int = 0, nfold: int = 3) -> tuple[np.ndarray, M.TextModel]:
    """text_logit for every row in `rows`: OOF (run-grouped folds) for rows in train_rows, the full-train text model for the others."""
    out = np.zeros(len(d.y), np.float32)
    tr = np.flatnonzero(train_rows)
    runs = np.unique(d.run[tr])
    rng = np.random.default_rng(seed)
    rng.shuffle(runs)
    for k in range(nfold):
        held = np.isin(d.run, runs[k::nfold]) & train_rows
        fit_rows = np.flatnonzero(train_rows & ~held)
        tm = M.fit_text(d.csr, d.y, fit_rows, max_honest=50_000, seed=seed)
        ix = np.flatnonzero(held)
        out[ix] = M.text_logit_matrix(d.csr[ix], tm)
    tm = M.fit_text(d.csr, d.y, tr, max_honest=50_000, seed=seed)
    rest = np.flatnonzero(rows & ~train_rows)
    out[rest] = M.text_logit_matrix(d.csr[rest], tm)
    return out, tm


def fit(d: Data, train: np.ndarray, val: np.ndarray, *, kind="trees", use=None, exclude_family: str | None = None, seed=0, bad_w=3.0, iters=80,
        calib_hold=0.01, calib_refuse=0.0005) -> tuple[Fitted, np.ndarray]:
    """Fit on gate-allowed rows of `train`; Platt + thresholds on `val`. Returns (fitted, X_with_text) where X has the text column filled for all rows."""
    cols = list(range(F.NF)) if use is None else list(use)
    keep = np.ones(len(d.y), bool)
    if exclude_family:
        keep = d.fam != exclude_family
    tr = train & d.pop & keep
    va = val & d.pop & keep
    X = d.X.copy()
    tm = None
    if IX_TEXT in cols:
        col, tm = text_column(d, d.pop & (train | val | True), tr, None, seed)
        X[:, IX_TEXT] = col
    tri, vai = np.flatnonzero(tr), np.flatnonzero(va)
    w = np.where(d.y[tri] == 1, bad_w, 1.0)
    ft = Fitted(kind, tm, None, None, None, cols)
    if kind == "trees":
        clf = M.fit_trees(X[tri][:, cols], d.y[tri], w, iters=iters, seed=seed)
        ens = M.TreeEnsemble.from_sklearn(clf, [F.NAMES[c] for c in cols])
        rv = clf.decision_function(X[vai][:, cols])
        ens.platt = M.fit_platt(rv, d.y[vai], np.where(d.y[vai] == 1, 1.0, 1.0))
        ft.ens = ens
        ft.info["clf"] = clf
    else:
        prep = M.Prep().fit(X[tri][:, cols])
        mlp = M.MLP((len(cols), 48, 24, 1), seed=seed).fit(prep(X[tri][:, cols]), d.y[tri], w, epochs=4, seed=seed)
        ft.mlp, ft.prep = mlp, prep
    pv = predict(ft, X, vai)
    hon = pv[d.y[vai] == 0]
    ft.t_hold = float(np.quantile(hon, 1 - calib_hold))
    ft.t_refuse = float(np.quantile(hon, 1 - calib_refuse))
    return ft, X


def predict(ft: Fitted, X: np.ndarray, rows) -> np.ndarray:
    Xs = X[rows][:, ft.cols]
    if ft.kind == "trees":
        raw = ft.info["clf"].decision_function(Xs)
        a, b = ft.ens.platt
        return 1.0 / (1.0 + np.exp(-(a * raw + b)))
    z = ft.mlp.logit(ft.prep(Xs))
    return 1.0 / (1.0 + np.exp(-z))
