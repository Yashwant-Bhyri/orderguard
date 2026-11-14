"""A white-box adaptive attacker and the cost of evasion.

The attacker controls a group of colluding agents (dataset.AdaptiveColluder), knows the features, the programmed units and the model's
hold threshold, and searches its own parameters to maximise the bad notional that is BOTH allowed by the code gate AND not held by the
risk model, per run-day. Whatever it finds is the model's cost of evasion: the most an attacker who stays under the threshold can still
move, and what it had to give up (rate, size, synchrony) to stay there.

Search: random draws over the knobs, then perturbations of the best few (a small cross-entropy search), on search seeds; the winner is
re-measured on fresh seeds. Nothing here trains or tunes the model.
"""
from __future__ import annotations

import numpy as np

from . import dataset as D
from . import features as F
from . import pipeline as P

KNOBS = {"period": (1, 60), "p": (0.15, 1.0), "lo": (0.02, 0.5), "hi": (0.05, 0.95), "warm": (0.0, 0.08), "aggr": (0.0005, 0.003), "one_ticker": (0, 1),
         "window": (150, 1400), "groups": (1, 3)}
NAIVE = {"period": 1, "p": 0.5, "lo": 0.05, "hi": 0.55, "warm": 0.0, "aggr": 0.001, "one_ticker": 0, "window": 400, "groups": 2}


def draw(rng) -> dict:
    th = {k: float(rng.uniform(*v)) for k, v in KNOBS.items()}
    return _clean(th, rng)


def _clean(th: dict, rng=None) -> dict:
    th = {k: float(min(max(v, KNOBS[k][0]), KNOBS[k][1])) for k, v in th.items()}
    th["period"], th["window"], th["groups"] = int(round(th["period"])), int(round(th["window"])), int(round(th["groups"]))
    th["one_ticker"] = int(th["one_ticker"] >= 0.5)
    if th["hi"] < th["lo"]:
        th["lo"], th["hi"] = th["hi"], th["lo"]
    return th


def perturb(th: dict, rng, scale: float = 0.2) -> dict:
    out = {}
    for k, (a, b) in KNOBS.items():
        out[k] = th[k] + rng.normal() * scale * (b - a) if k != "one_ticker" else (th[k] if rng.random() > 0.15 else 1 - th[k])
    return _clean(out)


def simulate(theta: dict, seed: int, agents: int = 600) -> P.Data:
    """One arena run (4 simulated days) with the attacker's colluders; features computed point-in-time by the streaming engine."""
    spec = {"seed": seed, "agents": agents, "steps": 2000, "steps_per_day": 500, "regime": "adversary", "vol": 1.0, "rate_mult": 1.0,
            "collusion_groups": int(theta["groups"]), "window": int(theta["window"]), "po": 1.0, "dm": 1.0, "bm": 1.0, "fail_prob": 0.15, "adaptive": theta}
    cols, meta = D.run_spec(spec, 0)
    metas = [meta]
    X = F.build_matrix(cols, None, P.env_specs_of(metas), {0: 500})
    lab = np.array(D.LABELS)[cols["label"]]
    fam = np.array([D.FAMILY[l] for l in D.LABELS])[cols["label"]]
    return P.Data(cols, metas, X, None, (lab != "legit").astype(np.int8), fam, (cols["dec"] == 0) & ~cols["replay"], cols["run"], cols["step"],
                  np.array(["adversary"] * len(lab)), cols["notional"].astype(np.float64), env_specs=P.env_specs_of(metas))


def outcome(d: P.Data, score, t_hold: float) -> dict:
    """What the attacker got: gate-allowed colluder dollars, and how many of them the model did not hold, per run-day."""
    rows = np.flatnonzero(d.pop)
    p = score(d.X[rows])
    st = d.fam[rows] == "stealth"
    usd, hon = d.notional[rows], d.y[rows] == 0
    days = 4.0
    n_col = max(len(np.unique(d.cols["agent"][d.fam == "stealth"])), 1)
    passed = float(usd[st & (p < t_hold)].sum())
    tot = float(usd[st].sum())
    return {"gate_allowed_usd_per_day": round(tot / days, 0), "undetected_usd_per_day": round(passed / days, 0), "usd_recall": round(1 - passed / tot, 4) if tot else None,
            "colluding_agents": int(n_col), "undetected_usd_per_agent_day": round(passed / days / n_col, 0), "honest_hold_rate": round(float((p[hon] >= t_hold).mean()), 5),
            "attack_orders_allowed": int(st.sum())}


def search(score, t_hold: float, *, n_random: int = 24, n_top: int = 5, n_refine: int = 4, rounds: int = 2, seed: int = 900, agents: int = 600, log=None) -> dict:
    rng = np.random.default_rng(seed)
    pool = []

    def ev(th):
        o = outcome(simulate(th, seed, agents), score, t_hold)
        pool.append((o["undetected_usd_per_day"], th, o))
        if log:
            log(len(pool), o["undetected_usd_per_day"], o["usd_recall"], th)
    ev(dict(NAIVE))
    for _ in range(n_random):
        ev(draw(rng))
    for r in range(rounds):
        pool.sort(key=lambda t: -t[0])
        for _, th, _ in pool[:n_top]:
            for _ in range(n_refine):
                ev(perturb(th, rng, 0.2 / (r + 1)))
    pool.sort(key=lambda t: -t[0])
    return {"best_theta": pool[0][1], "search_outcome": pool[0][2], "evaluations": len(pool)}


def remeasure(theta: dict, scorers: dict, seeds=(901, 902, 903), agents: int = 600) -> dict:
    """The attack on fresh seeds, scored by every model in `scorers` = {name: (score_fn, t_hold)}; mean over seeds."""
    acc: dict = {k: [] for k in scorers}
    for sd in seeds:
        d = simulate(theta, sd, agents)
        for k, (fn, t) in scorers.items():
            acc[k].append(outcome(d, fn, t))
    out = {}
    for k, rows in acc.items():
        out[k] = {m: round(float(np.mean([r[m] for r in rows])), 4) for m in rows[0] if rows[0][m] is not None}
    return out
