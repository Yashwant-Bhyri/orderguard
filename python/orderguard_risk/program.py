"""Programmed weights: what we KNOW about the domain, written directly into units instead of being learned.

A unit is a soft AND of ramps over invariant features (mandate-relative or baseline-relative quantities from `features.py`):

    u(x) = prod_t  clip((x[f_t] - lo_t) / (hi_t - lo_t), 0, 1)            a ramp with hi < lo is a decreasing ramp

Each unit states one attack signature in the mandate's own terms and carries a programmed weight `pi` = the probability that an order
on which the unit fully fires is bad. Units enter the risk by noisy-OR,

    risk = 1 - (1 - p_learned) * prod_k (1 - pi_k * u_k(x))               so   risk >= pi_k * u_k(x)   for every k

which means the learned part (trees fitted on data) can add risk on top of the programmed prior but can never explain it away: a family
with zero training examples is still detected. `refit_pi` moves each pi toward what the data says with a Beta prior centred on the
programmed value (bounded below), so data refines the weights but cannot erase them.

One-shot weight edits (`edit_from_example`) add a new unit computed from ONE labelled example against recent honest flow: the
coordinates where the example is far outside the honest distribution, a threshold at a fraction of the example's own deviation on each,
and the smallest conjunction of them that captures at most a budget of the honest reference. No retraining.

Everything here is plain Python on lists (the scorer's path); `units_matrix` / `edit_fire_matrix` are the numpy mirrors used offline.
"""
from __future__ import annotations

import math

from . import features as F

# name, family, signature in words, terms [(feature, lo, hi)], programmed weight pi
UNITS = [
    {"name": "split_under_threshold", "family": "collusion", "pi": 0.9,
     "why": "several agents send near-identical large slices of the cap on the same ticker and side: one position split to stay under the step-up threshold",
     "terms": [("cap_ratio", 0.3, 0.45), ("sync_size_agents", 2.5, 3.5), ("sizesim", 12.0, 24.0)]},
    {"name": "coordinated_burst", "family": "collusion", "pi": 0.9,
     "why": "this agent is sending a burst of untriggered orders while other agents in the same envelope are doing the same",
     "terms": [("agent_burst", 3.5, 6.0), ("hot_peers", 0.5, 2.5), ("trig", -0.5, -1.0)]},
    {"name": "order_rate", "family": "runaway", "pi": 0.9,
     "why": "an agent sending untriggered orders far faster than any strategy schedule",
     "terms": [("agent_burst", 5.0, 9.0), ("trig", -0.5, -1.0)]},
    {"name": "repeat_loop", "family": "runaway", "pi": 0.95,
     "why": "the same order (ticker, side, quantity, limit) re-sent again and again under fresh keys",
     "terms": [("dup_run", 1.5, 3.5)]},
    {"name": "size_discontinuity", "family": "fat_finger", "pi": 0.9,
     "why": "the order is several times this agent's own usual size",
     "terms": [("size_jump", 0.8, 1.4)]},
    {"name": "limit_far_from_trusted", "family": "stale_price", "pi": 0.85,
     "why": "the limit is far from the trusted price, and further than recent price moves explain",
     "terms": [("abs_dev", 0.03, 0.04), ("dev_vol", 2.0, 5.0)]},
    {"name": "schedule_break", "family": "compromised", "pi": 0.8,
     "why": "an agent with an established schedule sends an order off that schedule",
     "terms": [("off_cadence", 0.0, 1.0)]},
]
PI_FLOOR_FRAC = 0.5                 # refit can at most halve a programmed weight
PRIOR_STRENGTH = 50.0               # pseudo-firings behind each programmed weight

# Coordinates a one-shot edit may use, with the direction in which "more" means "more suspicious" (+1, -1, or 0 = either side).
EDIT_COORDS = [("cap_ratio", 1), ("stepup_ratio", 1), ("agent_day_share", 1), ("band_pos", 1), ("limit_dev", 0), ("size_z", 0), ("inter_arrival", -1),
               ("agent_burst", 1), ("dup_recent", 1), ("agent_capfrac", 1), ("agent_nearcap_rate", 1), ("xa_short", 1), ("sizesim", 1), ("same_step", 1),
               ("side_pressure", 0), ("size_jump", 0), ("rate_break", 1), ("agent_rate60", 1), ("rate_peer", 1), ("usd_peer", 1), ("usd_day_peer", 1),
               ("dup_exact", 1), ("dup_run", 1), ("dev_ratio", 1), ("dev_vol", 1), ("cross_band", 0), ("hot_peers", 1), ("sync_size_agents", 1), ("abs_dev", 1),
               ("new_ticker", 1), ("off_cadence", 1), ("off_rate", 1), ("is_transfer", 1), ("dup_key", 1)]
EDIT_Z_MIN = 3.0                    # a coordinate is usable when the example is at least this many honest scales out
EDIT_KAPPAS = (0.5, 0.65, 0.8, 0.9, 1.0)
EDIT_MAX_TERMS = 4


def compile_units(units=None) -> list[dict]:
    """Resolve feature names to columns once: [(name, pi, [(col, lo, 1/(hi-lo))...])]."""
    out = []
    for u in (UNITS if units is None else units):
        out.append({"name": u["name"], "family": u.get("family", ""), "why": u.get("why", ""), "pi": float(u["pi"]),
                    "terms": [(F.IX[f], float(lo), 1.0 / (float(hi) - float(lo))) for f, lo, hi in u["terms"]],
                    "spec": [[f, float(lo), float(hi)] for f, lo, hi in u["terms"]]})
    return out


def unit_value(terms, x) -> float:
    u = 1.0
    for c, lo, inv in terms:
        v = (x[c] - lo) * inv
        if v <= 0.0:
            return 0.0
        if v < 1.0:
            u *= v
    return u


def units_matrix(X, units=None):
    """(N, K) activations, numpy."""
    import numpy as np
    cu = compile_units(units)
    U = np.ones((len(X), len(cu)), np.float32)
    for k, u in enumerate(cu):
        for c, lo, inv in u["terms"]:
            U[:, k] *= np.clip((X[:, c] - lo) * inv, 0.0, 1.0)
    return U


def refit_pi(U, y, units=None, strength: float = PRIOR_STRENGTH) -> list[float]:
    """Posterior mean of P(bad | unit fires) under a Beta prior centred on the programmed weight, weighted by activation, floored."""
    import numpy as np
    out = []
    for k, u in enumerate(UNITS if units is None else units):
        a = U[:, k].astype(np.float64)
        fire, bad = float(a.sum()), float(a[y == 1].sum())
        out.append(round(max((strength * u["pi"] + bad) / (strength + fire), PI_FLOOR_FRAC * u["pi"]), 4))
    return out


# ---- one-shot weight edits ----------------------------------------------------------------------------------------------------


def _t(v: float) -> float:
    return math.copysign(math.log1p(abs(v)), v)


def honest_stats(rows: list[list[float]]) -> dict:
    """Robust centre and one-sided scales of every edit coordinate over honest reference rows (transformed by signed log1p). The scale on
    each side is the wider of a third of that side's 99.9% half-range and that side's root-mean-square deviation, so a heavy tail on one
    side does not hide an excursion on the other."""
    med, up, dn = [], [], []
    for name, _ in EDIT_COORDS:
        c = F.IX[name]
        v = sorted(_t(r[c]) for r in rows)
        n = len(v)
        m = v[n // 2]
        hi = [a - m for a in v if a > m]
        lo = [m - a for a in v if a < m]
        up.append(max((v[min(n - 1, int(0.999 * n))] - m) / 3.0, math.sqrt(sum(a * a for a in hi) / n), 0.05))
        dn.append(max((m - v[int(0.001 * n)]) / 3.0, math.sqrt(sum(a * a for a in lo) / n), 0.05))
        med.append(m)
    return {"med": med, "scale": up, "scale_dn": dn}


def edit_from_example(x: list[float], ref: list[list[float]], stats: dict | None = None, budget: float = 0.001, hint: list[str] | None = None,
                      note: str = "", min_terms: int = 1, kappas=EDIT_KAPPAS) -> dict | None:
    """ONE labelled example -> a new unit.

    1. z_j = (t(x_j) - honest median_j) / honest scale_j on each edit coordinate; keep those with |z_j| >= EDIT_Z_MIN in the suspicious
       direction (or only the coordinates named in `hint`, a short structured description from the analyst).
    2. The unit fires when every chosen coordinate is at least kappa of the way from the honest median to the example.
    3. Choose the FEWEST coordinates (most extreme first) and the smallest kappa that capture at most `budget` of the honest reference
       `ref` (recent orders the model did not flag). Fewer coordinates and a lower kappa generalise further; the budget is the brake.
    Returns None when the example is not outside honest flow on any coordinate (the caller falls back to a nearest-neighbour prototype)."""
    st = stats or honest_stats(ref)
    cand = []
    for j, (name, direction) in enumerate(EDIT_COORDS):
        if hint is not None and name not in hint:
            continue
        dv = _t(x[F.IX[name]]) - st["med"][j]
        sc = st["scale"][j] if dv >= 0 else st.get("scale_dn", st["scale"])[j]
        z = dv / sc
        if direction and z * direction < 0:
            continue
        if abs(z) >= (1.0 if hint is not None else EDIT_Z_MIN):
            cand.append((abs(z), j, 1.0 if z > 0 else -1.0, sc))
    if not cand:
        return None
    cand.sort(reverse=True)
    cand = cand[:8]
    # per reference row, the fraction of the example's deviation reached on each candidate coordinate
    fr = []
    for az, j, sgn, s in cand:
        c, m = F.IX[EDIT_COORDS[j][0]], st["med"][j]
        fr.append([sgn * (_t(r[c]) - m) / s / az for r in ref])
    n = max(len(ref), 1)
    allow = int(budget * n)
    best = None
    for k in range(min(min_terms, len(cand)), min(len(cand), EDIT_MAX_TERMS) + 1):
        mins = [min(fr[i][r] for i in range(k)) for r in range(len(ref))]
        for kappa in kappas:
            cap = sum(1 for v in mins if v >= kappa)
            if cap <= allow:
                best = (k, kappa, cap)
                break
        if best:
            break
    if best is None:
        k, kappa = min(len(cand), EDIT_MAX_TERMS), 1.0
        mins = [min(fr[i][r] for i in range(k)) for r in range(len(ref))]
        best = (k, kappa, sum(1 for v in mins if v >= kappa))
        if best[2] > max(allow, 0) + max(1, int(0.002 * n)):
            return None                               # even the tightest conjunction looks like honest flow: refuse to write the edit
    k, kappa, cap = best
    terms = []
    for az, j, sgn, sc in cand[:k]:
        name = EDIT_COORDS[j][0]
        # threshold in transformed space: median + sgn * kappa * az * scale   (a weight sgn/scale and a bias, written directly)
        terms.append({"f": name, "sign": sgn, "thr": st["med"][j] + sgn * kappa * az * sc, "z": round(sgn * az, 2)})
    return {"terms": terms, "kappa": kappa, "captured_reference": cap, "reference_orders": len(ref), "budget": budget, "note": note}


def edit_fires(edit: dict, x: list[float]) -> bool:
    for t in edit["terms"]:
        if t["sign"] * (_t(x[F.IX[t["f"]]]) - t["thr"]) < 0:
            return False
    return True


def edit_fire_matrix(edit: dict, X):
    import numpy as np
    m = np.ones(len(X), bool)
    for t in edit["terms"]:
        v = X[:, F.IX[t["f"]]].astype(np.float64)
        m &= t["sign"] * (np.sign(v) * np.log1p(np.abs(v)) - t["thr"]) >= 0
    return m


def edit_reasons(edit: dict, x: list[float]) -> list[str]:
    return [F.explain(t["f"], x[F.IX[t["f"]]]) for t in edit["terms"]]
