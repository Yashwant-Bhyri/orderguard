"""Paradigm (d): a mathematical risk model for a PORTFOLIO-level safety signal, small enough to run on the order path.

Signal: will this envelope's shared daily budget run out before the day ends? When it does, every honest agent drawing on it is refused
for the rest of the day (the arena's "starvation"). No per-order classifier sees this; it is a property of the envelope's state.

Model (closed form, no training): reserved budget grows like a compound process with recent mean rate m and standard deviation s per step.
With R = remaining budget and T = steps left in the day,

    P(exhaust) = Phi((m * T - R) / (s * sqrt(T)))                 normal approximation of the sum of T future steps

`drain_probability` is that formula; `DrainForecaster` keeps the O(1) state. `evaluate` replays the corpus (the simulator is the ground
truth: did the gate refuse an order for the daily cap later that day?) and compares the formula with a distilled logistic model fitted on
simulated days (training runs only), on held-out runs.
"""
from __future__ import annotations

import math
from collections import deque

W = 50          # steps of recent reservations used for the rate


def drain_probability(used: float, cap: float, rate_mean: float, rate_sd: float, steps_left: int) -> float:
    R = cap - used
    if R <= 0:
        return 1.0
    if steps_left <= 0:
        return 0.0
    z = (rate_mean * steps_left - R) / (max(rate_sd, 1e-9 * cap, 1e-9) * math.sqrt(steps_left))
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class DrainForecaster:
    """Streaming state for one envelope: reserved dollars today and the per-step reservations of the last W steps."""

    def __init__(self, cap: float, steps_per_day: int):
        self.cap, self.spd = float(cap), int(steps_per_day)
        self.day, self.used = -1, 0.0
        self.q: deque = deque()                     # (step, usd reserved in that step)
        self.s1 = self.s2 = 0.0

    def _roll(self, step: int) -> None:
        d = step // self.spd
        if d != self.day:
            self.day, self.used = d, 0.0
        lim = step - W
        while self.q and self.q[0][0] <= lim:
            v = self.q.popleft()[1]
            self.s1 -= v
            self.s2 -= v * v

    def observe(self, step: int, reserved_usd: float) -> None:
        """Call for every order the gate allowed or held (they reserve budget)."""
        self._roll(step)
        self.used += reserved_usd
        if self.q and self.q[-1][0] == step:
            old = self.q[-1][1]
            self.q[-1] = (step, old + reserved_usd)
            self.s1 += reserved_usd
            self.s2 += (old + reserved_usd) ** 2 - old * old
        else:
            self.q.append((step, reserved_usd))
            self.s1 += reserved_usd
            self.s2 += reserved_usd * reserved_usd

    def state(self, step: int) -> tuple[float, float, float, int]:
        self._roll(step)
        n = min(W, step - self.day * self.spd + 1)   # steps with no reservation count as zeros
        m = self.s1 / n
        var = max(self.s2 / n - m * m, 0.0)
        return self.used, m, math.sqrt(var), (self.day + 1) * self.spd - step - 1

    def probability(self, step: int) -> float:
        used, m, s, left = self.state(step)
        return drain_probability(used, self.cap, m, s, left)


def evaluate(cols: dict, metas: list, train_runs, test_runs, every: int = 10) -> dict:
    """Sample every `every` steps of every envelope-day; label = the gate refused at least one order for the daily cap LATER that day."""
    import time

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    from . import dataset as D
    from .models import ece
    rows = {"train": [], "test": []}
    lead = []
    run = cols["run"]
    starts = np.flatnonzero(np.r_[True, run[1:] != run[:-1]])
    ends = np.r_[starts[1:], len(run)]
    for s, e in zip(starts, ends):
        r = int(run[s])
        part = "train" if r in train_runs else "test" if r in test_runs else None
        if part is None:
            continue
        meta = metas[r]
        spd, steps = meta["spec"]["steps_per_day"], meta["spec"]["steps"]
        for ei, env in enumerate(meta["envelopes"]):
            if env["name"] not in D.ENVS:
                continue
            m = np.flatnonzero(cols["env"][s:e] == D.ENVS.index(env["name"])) + s
            st, dec, usd, code, rep = cols["step"][m], cols["dec"][m], cols["notional"][m].astype(float), cols["code"][m], cols["replay"][m]
            fc = DrainForecaster(env["daily"], spd)
            first_refuse = {}
            for i in np.flatnonzero((dec == 2) & (code == "daily")):
                first_refuse.setdefault(int(st[i]) // spd, int(st[i]))
            j, n = 0, len(m)
            alarm = {}
            for step in range(steps):
                while j < n and st[j] <= step:
                    if dec[j] != 2 and not rep[j]:
                        fc.observe(int(st[j]), usd[j])
                    j += 1
                if step % every:
                    continue
                day = step // spd
                fr = first_refuse.get(day)
                if fr is not None and fr <= step:
                    continue                                  # already exhausted: nothing left to forecast
                used, mu, sd, left = fc.state(step)
                p = drain_probability(used, fc.cap, mu, sd, left)
                rows[part].append((p, used / fc.cap, mu * left / fc.cap, sd * math.sqrt(max(left, 1)) / fc.cap, left / spd, 1 if fr is not None else 0))
                if part == "test" and fr is not None and p >= 0.5 and day * 10_000 + r * 1_000_000 + ei * 100_000_000 not in alarm:
                    alarm[day * 10_000 + r * 1_000_000 + ei * 100_000_000] = 1
                    lead.append(fr - step)
    tr, te = np.array(rows["train"]), np.array(rows["test"])
    y = te[:, 5]
    out = {"signal": "the envelope's shared daily budget will be exhausted before the day ends", "samples": {"train": int(len(tr)), "test": int(len(te))},
           "base_rate": round(float(y.mean()), 4)}

    def stats(p):
        return {"roc_auc": round(float(roc_auc_score(y, p)), 4), "brier": round(float(np.mean((p - y) ** 2)), 4), "ece": round(ece(p, y), 4),
                "recall_at_p>=0.5": round(float(((p >= 0.5) & (y == 1)).sum() / max(y.sum(), 1)), 4),
                "precision_at_p>=0.5": round(float(((p >= 0.5) & (y == 1)).sum() / max((p >= 0.5).sum(), 1)), 4)}
    out["closed_form"] = stats(te[:, 0])
    out["closed_form"]["median_lead_steps_first_alarm_to_first_refusal"] = float(np.median(lead)) if lead else None
    out["naive_used_fraction"] = {"roc_auc": round(float(roc_auc_score(y, te[:, 1])), 4)}
    lr = LogisticRegression(C=10.0, max_iter=500).fit(tr[:, 1:5], tr[:, 5])
    out["distilled_logistic"] = stats(lr.predict_proba(te[:, 1:5])[:, 1])
    out["distilled_logistic"]["weights"] = {"used_frac": round(float(lr.coef_[0][0]), 3), "projected_demand_frac": round(float(lr.coef_[0][1]), 3),
                                            "projected_sd_frac": round(float(lr.coef_[0][2]), 3), "day_left_frac": round(float(lr.coef_[0][3]), 3), "bias": round(float(lr.intercept_[0]), 3)}
    fc = DrainForecaster(1e6, 500)
    for i in range(2000):
        fc.observe(i // 4, 500.0)
    t0 = time.perf_counter_ns()
    for i in range(20000):
        fc.probability(499)
    out["latency_us_per_call"] = round((time.perf_counter_ns() - t0) / 20000 / 1000, 2)
    return out
