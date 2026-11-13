"""Honest evaluation: metrics a fraud team reads, four split protocols, and offline replay of the arena decision stream with risk tightening."""
from __future__ import annotations

import json
import time

import numpy as np

from . import dataset as D
from . import pipeline as P


def metrics(p: np.ndarray, d: P.Data, rows: np.ndarray, t_hold: float, t_refuse: float) -> dict:
    """Metrics on the gate-ALLOWED population `rows` (index array) given scores p aligned with rows."""
    from sklearn.metrics import average_precision_score, roc_auc_score
    y = d.y[rows]
    usd = d.notional[rows]
    flag = p >= t_hold
    ref = p >= t_refuse
    bad = y == 1
    nd = max(len({(r, s // d.spd) for r, s in zip(d.run[rows], d.step[rows])}), 1)
    out = {"n": int(len(rows)), "bad_n": int(bad.sum()), "bad_usd": round(float(usd[bad].sum()), 2),
           "pr_auc": round(float(average_precision_score(y, p)), 4) if bad.any() else None,
           "roc_auc": round(float(roc_auc_score(y, p)), 4) if bad.any() and (~bad).any() else None,
           "usd_recall_hold_or_refuse": round(float(usd[flag & bad].sum() / usd[bad].sum()), 4) if bad.any() else None,
           "usd_recall_refuse_only": round(float(usd[ref & bad].sum() / usd[bad].sum()), 4) if bad.any() else None,
           "count_recall": round(float((flag & bad).sum() / bad.sum()), 4) if bad.any() else None,
           "honest_false_hold_rate": round(float((flag & ~bad).sum() / max((~bad).sum(), 1)), 5),
           "honest_false_refuse_rate": round(float((ref & ~bad).sum() / max((~bad).sum(), 1)), 5),
           "hold_precision": round(float((flag & bad).sum() / max(flag.sum(), 1)), 4), "flags_per_run_day": round(float(flag.sum() / nd), 2),
           "brier": round(float(np.mean((p - y) ** 2)), 5), "ece": round(__import__("orderguard_risk.models", fromlist=["ece"]).ece(p, y), 5)}
    fam = {}
    for f in D.FAMILIES:
        m = bad & (d.fam[rows] == f)
        if m.any():
            fam[f] = {"n": int(m.sum()), "usd": round(float(usd[m].sum()), 0), "usd_recall": round(float(usd[flag & m].sum() / usd[m].sum()), 4)}
    out["by_family"] = fam
    return out


# Columns every protocol uses unless an experiment names its own. The CLI sets this to the behavioural columns so the published protocols
# describe the shipped model (no rationale text: the synthetic rationales are generated from the label and would flatter the scores).
DEFAULT_USE = None


def run_experiment(d: P.Data, train, val, test, *, kind="trees", use=None, exclude_family=None, seed=0, iters=80) -> tuple[dict, P.Fitted]:
    use = DEFAULT_USE if use is None else use
    ft, X = P.fit(d, train, val, kind=kind, use=use, exclude_family=exclude_family, seed=seed, iters=iters)
    te = np.flatnonzero(test & d.pop)
    p = P.predict(ft, X, te)
    m = metrics(p, d, te, ft.t_hold, ft.t_refuse)
    m["thresholds"] = {"hold": round(ft.t_hold, 5), "refuse": round(ft.t_refuse, 5)}
    return m, ft


def external(ft: P.Fitted, d_ext: P.Data) -> dict:
    """Score a dataset the model never saw (e.g. the adaptive-colluder runs) with the thresholds fixed on validation seeds."""
    X = d_ext.X.copy()
    if ft.tm is not None:
        X[:, P.IX_TEXT] = P.M.text_logit_matrix(d_ext.csr, ft.tm)
    rows = np.flatnonzero(d_ext.pop)
    p = P.predict(ft, X, rows)
    m = metrics(p, d_ext, rows, ft.t_hold, ft.t_refuse)
    m["thresholds"] = {"hold": round(ft.t_hold, 5), "refuse": round(ft.t_refuse, 5)}
    return m


def protocol_splits(d: P.Data) -> dict:
    tr, va, te = P.seed_split(d)
    calm_norm = np.isin(d.regime, ["calm", "normal"])
    runs_va = np.isin(d.run, d.runs_where(lambda s: s["regime"] in ("calm", "normal") and s["seed"] % 5 == 0))
    st = d.step
    return {
        "held_out_seeds": (tr, va, te),
        "regime_shift_volatile": (calm_norm & ~runs_va, calm_norm & runs_va, d.regime == "volatile"),
        "regime_shift_shifted": (calm_norm & ~runs_va, calm_norm & runs_va, d.regime == "shifted"),
        "time_split": (st < 960, (st >= 960) & (st < 1200), st >= 1200),
    }


def run_all(d: P.Data, log=print) -> dict:
    res = {}
    for name, (tr, va, te) in protocol_splits(d).items():
        m, _ = run_experiment(d, tr, va, te)
        res[name] = m
        log(name, {k: m[k] for k in ("pr_auc", "usd_recall_hold_or_refuse", "honest_false_hold_rate", "hold_precision")})
    tr, va, te = res_split = P.seed_split(d)
    loao = {}
    for fam in ("collusion", "fat_finger", "runaway", "compromised", "stale_price"):
        m, _ = run_experiment(d, tr, va, te, exclude_family=fam)
        loao[fam] = {k: m[k] for k in ("pr_auc", "usd_recall_hold_or_refuse", "honest_false_hold_rate", "hold_precision", "bad_n", "bad_usd")} | {"family": m["by_family"].get(fam)}
        log("LOAO", fam, loao[fam]["family"], m["honest_false_hold_rate"])
    res["loao"] = loao
    abl = {}
    for name, use in (("full", list(range(len(P.F.NAMES)))), ("no_text", [i for i in range(len(P.F.NAMES)) if i not in P.TEXT_COLS]),
                      ("no_cross_agent_no_text", [i for i in range(len(P.F.NAMES)) if i not in P.CROSS_COLS]), ("envelope_only", P.ENV_COLS)):
        m, _ = run_experiment(d, tr, va, te, use=use)
        abl[name] = {k: m[k] for k in ("pr_auc", "usd_recall_hold_or_refuse", "honest_false_hold_rate", "hold_precision")} | {"collusion": m["by_family"].get("collusion")}
        log("ablation", name, abl[name])
    res["ablation_held_out_seeds"] = abl
    m0, ft0 = run_experiment(d, tr, va, te)
    try:
        ext = P.load_data(D.DATA_DIR / "stealth.npz")
        res["adaptive_colluder_ood"] = external(ft0, ext)
        log("stealth", {k: res["adaptive_colluder_ood"][k] for k in ("usd_recall_hold_or_refuse", "honest_false_hold_rate")})
    except FileNotFoundError:
        pass
    m, _ = run_experiment(d, tr, va, te, kind="mlp")
    res["mlp_held_out_seeds"] = m
    return res


def dump(path, obj) -> None:
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True, default=lambda o: o.item() if hasattr(o, "item") else str(o))
