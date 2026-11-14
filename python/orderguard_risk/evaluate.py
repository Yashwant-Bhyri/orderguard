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


# ---- v2 evaluation: fixed honest-hold budgets, leave-one-family-out with zero/one/few-shot, calibration --------------------------


def clean_agent_mask(d: P.Data) -> np.ndarray:
    """True where the order's agent has NO bad-labelled proposal anywhere in its run. Orders labelled legit that come from an agent in the
    middle of an attack (a colluder's own strategy orders) are honest by label but not by agent; this mask separates the two."""
    key = d.run.astype(np.int64) * 1_000_000 + d.cols["agent"]
    return ~np.isin(key, np.unique(key[d.y == 1]))


def budget_table(p: np.ndarray, d: P.Data, rows: np.ndarray, thr: dict, t_refuse: float | None = None) -> dict:
    from .models import ece
    y, usd, fam = d.y[rows], d.notional[rows], d.fam[rows]
    bad, clean = y == 1, clean_agent_mask(d)[rows]
    nd = max(len({(r, s // d.spd) for r, s in zip(d.run[rows], d.step[rows])}), 1)
    out = {"n": int(len(rows)), "bad_n": int(bad.sum()), "bad_usd": round(float(usd[bad].sum()), 0), "brier": round(float(np.mean((p - y) ** 2)), 5),
           "ece": round(ece(p, y), 5), "budgets": {}}
    for b, t in thr.items():
        f = p >= t
        row = {"threshold": round(float(t), 6), "usd_recall": round(float(usd[f & bad].sum() / usd[bad].sum()), 4) if bad.any() else None,
               "count_recall": round(float((f & bad).sum() / max(bad.sum(), 1)), 4), "honest_hold_rate": round(float(f[~bad].mean()), 5),
               "honest_hold_rate_clean_agents": round(float(f[~bad & clean].mean()), 5), "hold_precision": round(float((f & bad).sum() / max(f.sum(), 1)), 4),
               "honest_holds_per_run_day": round(float((f & ~bad).sum() / nd), 1), "missed_bad_usd_per_run_day": round(float(usd[~f & bad].sum() / nd), 0),
               "by_family": {fa: round(float(usd[f & bad & (fam == fa)].sum() / usd[bad & (fam == fa)].sum()), 4) for fa in D.FAMILIES if (bad & (fam == fa)).any()}}
        out["budgets"][f"{b:.2%}"] = row
    if t_refuse is not None:
        f = p >= t_refuse
        out["refuse"] = {"usd_recall": round(float(usd[f & bad].sum() / usd[bad].sum()), 4) if bad.any() else None, "honest_refuse_rate": round(float(f[~bad].mean()), 5)}
    return out


def train_honest_stats(d: P.Data, fit_rows: np.ndarray, n: int = 20_000) -> dict:
    """The honest statistics a model file carries for one-shot edits: from honest gate-allowed orders of the fitting runs only."""
    from . import program as G
    ix = np.flatnonzero(fit_rows & d.pop & (d.y == 0))
    return G.honest_stats(d.X[np.random.default_rng(0).choice(ix, size=min(n, len(ix)), replace=False)].astype(float).tolist())


def oneshot_trials(d_lab: P.Data, lab_rows: np.ndarray, p_lab: np.ndarray, d_test: P.Data, test_rows: np.ndarray, p_test: np.ndarray, family: str, t_hold: float,
                   k: int = 1, trials: int = 20, budget: float = 0.001, seed: int = 0, same_run_excluded: bool = False, stats: dict | None = None) -> dict:
    """k labelled examples of `family` -> k weight edits (program.edit_from_example), measured on rows the labels did not come from.
    Labels are drawn from orders of the family that the base model MISSED in the labelling runs; the reference flow for each edit is what an
    analyst has at that moment: earlier orders of the same run that the base model did not flag (no labels). Each edit gets budget / k."""
    from . import program as G
    rng = np.random.default_rng(seed)
    fam_l, flag_l = d_lab.fam[lab_rows], p_lab >= t_hold
    cand = np.flatnonzero((fam_l == family) & ~flag_l)
    pool = "missed by the base model"
    if len(cand) < max(5, k):
        cand, pool = np.flatnonzero(fam_l == family), "any order of the family (the base model missed too few)"
    if len(cand) == 0:
        return {"note": "no examples"}
    run_l, step_l, ag_l = d_lab.run[lab_rows], d_lab.step[lab_rows], d_lab.cols["agent"][lab_rows]
    Xl = d_lab.X[lab_rows]
    Xt, yt, ft, ut, rt = d_test.X[test_rows], d_test.y[test_rows], d_test.fam[test_rows], d_test.notional[test_rows], d_test.run[test_rows]
    flag_t = p_test >= t_hold
    rec, cost, written, terms = [], [], [], []
    for _ in range(trials):
        picks = rng.choice(cand, size=min(k, len(cand)), replace=False)
        fire = np.zeros(len(test_rows), bool)
        nw = 0
        for pk in picks:
            ref = np.flatnonzero((run_l == run_l[pk]) & (step_l <= step_l[pk]) & ~flag_l & (ag_l != ag_l[pk]))   # the labelled agent's own orders are not honest reference
            ref = ref[-5000:]
            if len(ref) < 200:
                continue
            e = G.edit_from_example([float(v) for v in Xl[pk]], Xl[ref].astype(float).tolist(), stats=stats, budget=budget / k)
            if e is None:
                continue
            nw += 1
            terms.append("+".join(t["f"] for t in e["terms"]))
            fire |= G.edit_fire_matrix(e, Xt)
        ev = np.ones(len(test_rows), bool)
        if same_run_excluded:
            ev = ~np.isin(rt, np.unique(run_l[picks]))
        m = (ft == family) & ev
        rec.append(float(ut[m & (flag_t | fire)].sum() / max(ut[m].sum(), 1e-9)))
        cost.append(float((fire & ~flag_t & (yt == 0) & ev).sum() / max(((yt == 0) & ev).sum(), 1)))
        written.append(nw)
    q = lambda v: [round(float(x), 4) for x in np.quantile(v, [0.25, 0.5, 0.75])]
    top = {}
    for t in terms:
        top[t] = top.get(t, 0) + 1
    return {"k": k, "trials": trials, "label_pool": pool, "usd_recall_q25_median_q75": q(rec), "honest_newly_held_rate_q25_median_q75": [round(float(x), 5) for x in np.quantile(cost, [0.25, 0.5, 0.75])],
            "honest_newly_held_rate_max": round(float(max(cost)), 5), "edits_written_mean": round(float(np.mean(written)), 2),
            "most_common_edit_terms": sorted(top.items(), key=lambda kv: -kv[1])[:4]}


def lofo(d: P.Data, fit_rows: np.ndarray, test: np.ndarray, families=("collusion", "compromised", "fat_finger", "runaway", "stale_price"), log=print, full=None) -> dict:
    """Leave one family out, at the operating budget: learned-only vs programmed prior (zero-shot), then one and five labelled examples as
    weight edits on each, and the full retrain (the model that trained on the family)."""
    B = P.OPERATING_BUDGET
    te = np.flatnonzero(test & d.pop)
    lab = np.flatnonzero(fit_rows & d.pop)
    stats = train_honest_stats(d, fit_rows)
    full = full or P.fit2(d, fit_rows)
    pf = P.predict2(full, d.X[te])
    usd, fam = d.notional[te], d.fam[te]
    out = {}
    for f in families:
        m = fam == f
        r = {"test_orders": int(m.sum()), "test_usd": round(float(usd[m].sum()), 0), "full_retrain": round(float(usd[m & (pf >= full.thr[B])].sum() / usd[m].sum()), 4)}
        for name, kw in (("v1_learned_only", {"cols": P.V1_COLS, "units": False, "mono": False}), ("learned_only", {"units": False}), ("programmed", {})):
            ft = P.fit2(d, fit_rows, exclude_family=f, **kw)
            pt = P.predict2(ft, d.X[te])
            flag = pt >= ft.thr[B]
            r[name] = {"zero_shot": round(float(usd[m & flag].sum() / usd[m].sum()), 4), "honest_hold_rate": round(float(flag[d.y[te] == 0].mean()), 5)}
            if name != "v1_learned_only":
                pl = P.predict2(ft, d.X[lab])
                for k in (1, 5):
                    r[name][f"{k}_shot"] = oneshot_trials(d, lab, pl, d, te, pt, f, ft.thr[B], k=k, stats=stats)
        out[f] = r
        log("LOFO", f, {k: (v["zero_shot"], v.get("1_shot", {}).get("usd_recall_q25_median_q75"), v.get("5_shot", {}).get("usd_recall_q25_median_q75")) if isinstance(v, dict) else v for k, v in r.items()})
    return out


def run_all2(d: P.Data, ext: P.Data | None, log=print) -> dict:
    """Everything published about the v2 model, next to the v1 architecture fitted and thresholded the same way."""
    tr, va, te = P.seed_split(d)
    fit_rows = tr | va
    tei = np.flatnonzero(te & d.pop)
    res = {"operating_budget": P.OPERATING_BUDGET, "protocol": "trees fitted on train+validation runs; Platt and thresholds from out-of-fold scores over whole runs; "
           "test runs and the adaptive set touched only to report"}
    variants = {"v2_programmed": {}, "v1_architecture": {"cols": P.V1_COLS, "units": False, "mono": False}, "v2_learned_only": {"units": False},
                "v2_no_schedule_features": {"cols": [c for c in P.V2_COLS if P.F.NAMES[c] not in ("off_cadence", "cadence_n", "off_rate")],
                                            "unit_specs": [u for u in __import__("orderguard_risk.program", fromlist=["UNITS"]).UNITS if u["name"] != "schedule_break"]},
                "v2_not_monotone": {"mono": False}}
    fitted = {}
    for name, kw in variants.items():
        ft = fitted[name] = P.fit2(d, fit_rows, **kw)
        r = {"held_out_seeds": budget_table(P.predict2(ft, d.X[tei]), d, tei, ft.thr, ft.t_refuse)}
        if ext is not None:
            ei = np.flatnonzero(ext.pop)
            r["adaptive_colluders"] = budget_table(P.predict2(ft, ext.X[ei]), ext, ei, ft.thr, ft.t_refuse)
        r["programmed_weights"] = ft.pi
        res[name] = r
        log(name, {k: {b: (v["usd_recall"], v["honest_hold_rate"]) for b, v in r[k]["budgets"].items()} for k in r if k != "programmed_weights"})
    full = fitted["v2_programmed"]
    for name, (a, b, c) in protocol_splits(d).items():
        if name == "held_out_seeds":
            continue
        ft = P.fit2(d, a | b)
        ci = np.flatnonzero(c & d.pop)
        res[name] = budget_table(P.predict2(ft, d.X[ci]), d, ci, ft.thr, ft.t_refuse)
        log(name, {k: (v["usd_recall"], v["honest_hold_rate"]) for k, v in res[name]["budgets"].items()})
    res["leave_one_family_out"] = lofo(d, fit_rows, te, log=log, full=full)
    if ext is not None:                                   # the adaptive colluders as a held-out family: labels from one run, measured on the others
        ei = np.flatnonzero(ext.pop)
        st = {}
        for name in ("v2_learned_only", "v2_programmed"):
            ft = fitted[name]
            pe = P.predict2(ft, ext.X[ei])
            m = ext.fam[ei] == "stealth"
            st[name] = {"zero_shot": round(float(ext.notional[ei][m & (pe >= ft.thr[P.OPERATING_BUDGET])].sum() / ext.notional[ei][m].sum()), 4)}
            for k in (1, 5):
                st[name][f"{k}_shot"] = oneshot_trials(ext, ei, pe, ext, ei, pe, "stealth", ft.thr[P.OPERATING_BUDGET], k=k, same_run_excluded=True,
                                                      stats=train_honest_stats(d, fit_rows))
        # full retrain: half the adaptive runs join training, the other half are the test
        runs = np.unique(ext.run)
        half = np.isin(ext.run, runs[::2])
        both = _concat(d, ext)
        nd = len(d.y)
        rows = np.r_[fit_rows, half]
        ft = P.fit2(both, rows)
        ti = nd + np.flatnonzero(~half & ext.pop)
        pt = P.predict2(ft, both.X[ti])
        m = both.fam[ti] == "stealth"
        st["full_retrain_half_the_adaptive_runs"] = round(float(both.notional[ti][m & (pt >= ft.thr[P.OPERATING_BUDGET])].sum() / both.notional[ti][m].sum()), 4)
        res["leave_one_family_out"]["adaptive_colluders"] = st
        log("LOFO stealth", st)
    return res


def _concat(a: P.Data, b: P.Data) -> P.Data:
    """Two corpora as one (run ids of the second are offset so they stay distinct)."""
    off = int(a.run.max()) + 1
    cols = {k: np.concatenate([a.cols[k], b.cols[k] + (off if k == "run" else 0)]) for k in ("run", "agent", "step")}
    return P.Data(cols, [], np.vstack([a.X, b.X]), None, np.r_[a.y, b.y], np.r_[a.fam, b.fam], np.r_[a.pop, b.pop], cols["run"], cols["step"],
                  np.r_[a.regime, b.regime], np.r_[a.notional, b.notional])
