"""Point-in-time streaming features for order risk.

`FeatureEngine.featurize(ev)` reads state built from events strictly BEFORE `ev` (plus the event's own fields); `update(ev)` then folds the
event in. Nothing looks ahead, nothing reads the gate's decision, so a feature at time t cannot change when later events are appended
(tested). Every window is a deque with an O(1) amortised append/expire and counters, so the cost per order is constant.

Event dict: step, agent, env (envelope name), ticker, side, qty, limit, tp (trusted price or None), notional, key, trig (None/True/False),
text (optional rationale), listed (optional bool). Envelope specs and steps/day are set with `set_envelopes`.
"""
from __future__ import annotations

import math
from collections import Counter, deque

from .text import HASH_DIM, hashed_ngrams, skeleton, stated_usd

W_S, W_M, W_L, W_AG, W_DUP, W_PACE = 10, 60, 250, 20, 60, 50
K_NBR = 6

NAMES = [
    # order vs envelope
    "cap_ratio", "stepup_ratio", "log_notional", "near_cap", "order_share_daily", "env_day_demand", "env_pace", "agent_day_share", "agent_day_n",
    # price
    "limit_dev", "band_pos", "listed", "is_transfer", "trig",
    # agent baseline
    "size_z", "agent_n", "agent_ticker_n", "side_flip", "inter_arrival", "agent_burst", "dup_recent", "dup_key", "agent_capfrac", "agent_nearcap_rate",
    # cross-agent
    "xa_short", "xa_med", "xa_near_env", "sizesim", "same_step", "strong_nbrs", "strong_frac", "side_pressure", "ticker_flow",
    # market
    "vol_short", "vol_ratio",
    # semantic
    "text_logit", "stated_ratio", "has_stated", "script_dup",
]
IX = {n: i for i, n in enumerate(NAMES)}
NF = len(NAMES)
BEHAV = [n for n in NAMES if n not in ("text_logit", "stated_ratio", "has_stated", "script_dup")]


class _Win:
    """Sliding window of (step, agent, bucket) for one key; distinct-agent and size-bucket counters."""
    __slots__ = ("w", "q", "ag", "bk")

    def __init__(self, w: int):
        self.w, self.q, self.ag, self.bk = w, deque(), Counter(), Counter()

    def expire(self, step: int) -> None:
        q, lim = self.q, step - self.w
        while q and q[0][0] <= lim:
            _, a, b = q.popleft()
            self.ag[a] -= 1
            if not self.ag[a]:
                del self.ag[a]
            self.bk[b] -= 1
            if not self.bk[b]:
                del self.bk[b]

    def add(self, step: int, agent, bucket) -> None:
        self.q.append((step, agent, bucket))
        self.ag[agent] += 1
        self.bk[bucket] += 1


class _Agent:
    __slots__ = ("n", "mu", "var", "last_step", "last_side", "tick", "recent", "dups", "dupq", "cf", "nc", "keys", "day", "day_usd", "day_n")

    def __init__(self):
        self.n, self.mu, self.var = 0, 0.0, 0.36
        self.last_step, self.last_side = -10_000, {}
        self.tick: Counter = Counter()
        self.recent: deque = deque()                 # steps of this agent's recent orders (burst)
        self.dups: Counter = Counter()
        self.dupq: deque = deque()
        self.cf, self.nc = 0.05, 0.0
        self.keys: deque = deque(maxlen=32)
        self.day, self.day_usd, self.day_n = -1, 0.0, 0


class FeatureEngine:
    def __init__(self, envelopes: dict | None = None, steps_per_day: int = 500, text_model=None):
        self.set_envelopes(envelopes or {}, steps_per_day)
        self.text_model = text_model                 # object with .logit(sparse) or None
        self.reset()

    def set_envelopes(self, envelopes: dict, steps_per_day: int) -> None:
        self.envs, self.spd = envelopes, int(steps_per_day)

    def reset(self) -> None:
        self.agents: dict = {}
        self.win_s: dict = {}
        self.win_m: dict = {}
        self.same: dict = {}
        self.flow: dict = {}                          # ticker -> deque of (step, side)
        self.flow_c: dict = {}
        self.env_near: dict = {}                      # env -> _Win of near-cap orders (long)
        self.env_pace: dict = {}                      # env -> deque (step, notional), sum
        self.env_pace_sum: dict = {}
        self.env_day: dict = {}                       # env -> (day, usd)
        self.edges: dict = {}                         # (a,b) -> [weight, last_step]
        self.px: dict = {}                            # ticker -> [last_tp, ewma_abs_s, ewma_abs_l]
        self.script: deque = deque()
        self.script_c: Counter = Counter()
        self.n_seen = 0

    # ---- helpers ------------------------------------------------------------------------------------------------
    @staticmethod
    def _bucket(ratio: float) -> int:
        return int(math.floor(math.log2(ratio + 1e-6) * 3.0))

    def _spec(self, env):
        s = self.envs.get(env)
        if s is None:
            return 25_000.0, 8_000_000.0, 20_000.0, 1.0
        return s["per_order"], s["daily"], s.get("step_up") or s["per_order"], s.get("band_pct") or 1.0

    def _text(self, ev):
        t = ev.get("text")
        if not t:
            return None, None, None
        lg = self.text_model.logit(hashed_ngrams(t)) if self.text_model is not None else 0.0
        return lg, stated_usd(t), skeleton(t, str(ev.get("ticker") or ""))

    # ---- features -----------------------------------------------------------------------------------------------
    def featurize(self, ev: dict, out: list | None = None, parts: dict | None = None) -> list:
        step, agent, env, tk = ev["step"], ev["agent"], ev.get("env"), ev.get("ticker") or ""
        side = ev.get("side") or ""
        notional = float(ev.get("notional") or 0.0)
        cap, daily, stepup, band = self._spec(env)
        day = step // self.spd
        ratio = notional / cap
        bucket = self._bucket(ratio)
        a = self.agents.get(agent)
        f = [0.0] * NF
        f[0] = ratio
        f[1] = notional / stepup
        f[2] = math.log1p(notional)
        nr = notional / stepup
        f[3] = 1.0 if 0.8 < nr <= 1.0 else 0.0
        f[4] = notional / daily
        ed = self.env_day.get(env)
        f[5] = (ed[1] / daily) if ed and ed[0] == day else 0.0
        pace = self.env_pace_sum.get(env, 0.0)
        pq = self.env_pace.get(env)
        if pq:
            lim = step - W_PACE
            while pq and pq[0][0] <= lim:
                self.env_pace_sum[env] -= pq.popleft()[1]
            pace = self.env_pace_sum[env]
        f[6] = pace / (daily * W_PACE / self.spd)
        f[7] = (a.day_usd / daily * 100.0) if a is not None and a.day == day else 0.0
        f[8] = a.day_n if a is not None and a.day == day else 0
        tp, limit = ev.get("tp"), float(ev.get("limit") or 0.0)
        if tp and limit:
            dev = (limit / tp - 1.0) * (1.0 if side == "buy" else -1.0)
            f[9] = dev
            f[10] = abs(limit / tp - 1.0) * 100.0 / band
        f[11] = 1.0 if ev.get("listed", True) else 0.0
        f[12] = 1.0 if side not in ("buy", "sell") else 0.0
        tg = ev.get("trig")
        f[13] = -1.0 if tg is None else (1.0 if tg else 0.0)
        ln = math.log1p(notional)
        if a is None:
            f[14], f[15], f[16], f[17], f[18] = 0.0, 0.0, 0.0, 0.0, 1000.0
            f[19], f[20], f[21], f[22], f[23] = 1.0, 0.0, 0.0, 0.05, 0.0
            a_n_for_z = 0
        else:
            sd = math.sqrt(max(a.var, 0.04))
            f[14] = (ln - a.mu) / sd if a.n >= 3 else 0.0
            f[15] = math.log1p(a.n)
            f[16] = a.tick.get(tk, 0)
            ls = a.last_side.get(tk)
            f[17] = 1.0 if ls is not None and ls != side else 0.0
            f[18] = min(step - a.last_step, 1000)
            lim = step - W_AG
            q = a.recent
            while q and q[0] <= lim:
                q.popleft()
            f[19] = len(q) + 1
            dk = (tk, side, ev.get("qty"))
            lim = step - W_DUP
            dq = a.dupq
            while dq and dq[0][0] <= lim:
                _, k0 = dq.popleft()
                a.dups[k0] -= 1
            f[20] = a.dups.get(dk, 0)
            f[21] = 1.0 if ev.get("key") in a.keys else 0.0
            f[22] = a.cf
            f[23] = a.nc
        # cross agent
        key = (tk, side)
        ws = self.win_s.get(key)
        wm = self.win_m.get(key)
        if ws is not None:
            ws.expire(step)
            f[24] = len(ws.ag) - (1 if agent in ws.ag else 0)
        if wm is not None:
            wm.expire(step)
            f[25] = len(wm.ag) - (1 if agent in wm.ag else 0)
            f[27] = wm.bk.get(bucket, 0) + wm.bk.get(bucket - 1, 0) + wm.bk.get(bucket + 1, 0)
            # strong co-occurrence neighbours among the K most recent distinct others
            seen, strong = set(), 0
            for _, b, _bk in reversed(wm.q):
                if b == agent or b in seen:
                    continue
                seen.add(b)
                e = self.edges.get((agent, b) if agent < b else (b, agent))
                if e is not None and e[0] >= 3 and step - e[1] <= W_L:
                    strong += 1
                if len(seen) >= K_NBR:
                    break
            f[29] = strong
            f[30] = strong / len(seen) if seen else 0.0
        sm = self.same.get(key)
        f[28] = sm[1] if sm is not None and sm[0] == step else 0
        en = self.env_near.get(env)
        if en is not None:
            en.expire(step)
            f[26] = len(en.ag) - (1 if agent in en.ag else 0)
        fq = self.flow.get(tk)
        if fq:
            lim = step - W_M
            c = self.flow_c[tk]
            while fq and fq[0][0] <= lim:
                s0 = fq.popleft()[1]
                c[s0] -= 1
            tot = c["buy"] + c["sell"]
            f[31] = (c[side] - c["buy" if side == "sell" else "sell"]) / tot if tot and side in ("buy", "sell") else 0.0
            f[32] = math.log1p(tot)
        p = self.px.get(tk)
        if p is not None:
            f[33] = p[1] * 1e4
            f[34] = p[1] / (p[2] + 1e-9)
        lg, stated, sk = self._text(ev)
        if lg is not None:
            f[35] = lg
            if stated:
                f[36] = math.log((notional + 1.0) / (stated + 1.0))
                f[37] = 1.0
            f[38] = self.script_c.get(sk, 0)
        if parts is not None:
            parts["text_present"] = lg is not None
        if out is not None:
            out[:] = f
            return out
        return f

    # ---- update -------------------------------------------------------------------------------------------------
    def update(self, ev: dict) -> None:
        step, agent, env, tk = ev["step"], ev["agent"], ev.get("env"), ev.get("ticker") or ""
        side = ev.get("side") or ""
        notional = float(ev.get("notional") or 0.0)
        cap, daily, _su, _b = self._spec(env)
        nr = notional / _su
        day = step // self.spd
        ratio = notional / cap
        bucket = self._bucket(ratio)
        a = self.agents.get(agent)
        if a is None:
            a = self.agents[agent] = _Agent()
        ln = math.log1p(notional)
        a.n += 1
        d = ln - a.mu
        al = 0.1 if a.n > 1 else 1.0
        a.mu += al * d
        a.var = (1 - al) * (a.var + al * d * d)
        a.last_step = step
        a.last_side[tk] = side
        a.tick[tk] += 1
        a.recent.append(step)
        dk = (tk, side, ev.get("qty"))
        a.dups[dk] += 1
        a.dupq.append((step, dk))
        a.keys.append(ev.get("key"))
        a.cf += 0.1 * (ratio - a.cf)
        a.nc += 0.1 * ((1.0 if 0.8 < nr <= 1.0 else 0.0) - a.nc)
        if a.day != day:
            a.day, a.day_usd, a.day_n = day, 0.0, 0
        a.day_usd += notional
        a.day_n += 1
        ed = self.env_day.get(env)
        self.env_day[env] = (day, notional + (ed[1] if ed and ed[0] == day else 0.0))
        pq = self.env_pace.setdefault(env, deque())
        pq.append((step, notional))
        self.env_pace_sum[env] = self.env_pace_sum.get(env, 0.0) + notional
        key = (tk, side)
        ws = self.win_s.get(key)
        if ws is None:
            ws = self.win_s[key] = _Win(W_S)
            self.win_m[key] = _Win(W_M)
        wm = self.win_m[key]
        # co-occurrence edges with the K most recent distinct others (O(K))
        seen = set()
        for _, b, _bk in reversed(wm.q):
            if b == agent or b in seen:
                continue
            seen.add(b)
            k = (agent, b) if agent < b else (b, agent)
            e = self.edges.get(k)
            if e is None:
                self.edges[k] = [1, step]
            else:
                e[0] = e[0] + 1 if step - e[1] <= W_L else 1
                e[1] = step
            if len(seen) >= K_NBR:
                break
        ws.add(step, agent, bucket)
        wm.add(step, agent, bucket)
        sm = self.same.get(key)
        self.same[key] = [step, (sm[1] + 1) if sm is not None and sm[0] == step else 1]
        if 0.8 < nr <= 1.0:
            en = self.env_near.get(env)
            if en is None:
                en = self.env_near[env] = _Win(W_L)
            en.add(step, agent, bucket)
        if side in ("buy", "sell"):
            fq = self.flow.setdefault(tk, deque())
            c = self.flow_c.setdefault(tk, Counter())
            fq.append((step, side))
            c[side] += 1
        tp = ev.get("tp")
        if tp:
            p = self.px.get(tk)
            if p is None:
                self.px[tk] = [tp, 0.0, 0.0]
            elif p[0] != tp:
                r = abs(tp / p[0] - 1.0)
                p[1] += 0.2 * (r - p[1])
                p[2] += 0.01 * (r - p[2])
                p[0] = tp
        t = ev.get("text")
        if t:
            sk = skeleton(t, tk)
            self.script.append((step, sk))
            self.script_c[sk] += 1
        lim = step - W_L
        while self.script and self.script[0][0] <= lim:
            s0 = self.script.popleft()[1]
            self.script_c[s0] -= 1
        self.n_seen += 1
        if len(self.edges) > 400_000:                      # bound memory: drop stale edges
            self.edges = {k: v for k, v in self.edges.items() if step - v[1] <= W_L}


# ---- explanations ----------------------------------------------------------------------------------------------------------

def explain(name: str, v: float) -> str:
    t = {
        "cap_ratio": f"the order is {v:.0%} of the per-order cap",
        "stepup_ratio": f"the order is {v:.0%} of the step-up threshold",
        "log_notional": f"a large order (about ${math.expm1(v):,.0f})",
        "near_cap": "its size sits just under the per-order cap",
        "order_share_daily": f"it uses {v:.2%} of the envelope's daily cap",
        "env_day_demand": f"the envelope has already seen {v:.0%} of its daily cap in proposals today",
        "env_pace": f"proposals are arriving at {v:.1f}x the pace that would just exhaust the daily cap",
        "agent_day_share": f"this agent alone has proposed {v:.1f}% of the daily cap today",
        "agent_day_n": f"this agent has placed {v:.0f} orders today",
        "limit_dev": f"the limit is {v:+.1%} through the trusted price",
        "band_pos": f"the limit is {v:.0%} of the way to the price band edge",
        "listed": "the ticker is off the envelope's list",
        "is_transfer": "it is not a trade",
        "trig": "it claims a standing rule",
        "size_z": f"the size is {v:+.1f} standard deviations from this agent's usual",
        "agent_n": "this agent has little history",
        "agent_ticker_n": f"this agent has traded this ticker {v:.0f} times before",
        "side_flip": "the side flipped against this agent's last trade in the ticker",
        "inter_arrival": f"{v:.0f} steps since this agent's last order",
        "agent_burst": f"this agent sent {v:.0f} orders in the last {W_AG} steps",
        "dup_recent": f"{v:.0f} identical orders from this agent in the last {W_DUP} steps",
        "dup_key": "the idempotency key was already used by this agent",
        "agent_capfrac": f"this agent's recent orders average {v:.0%} of the cap",
        "agent_nearcap_rate": f"{v:.0%} of this agent's recent orders sat just under the cap",
        "xa_short": f"{v:.0f} other agents placed the same ticker and side in the last {W_S} steps",
        "xa_med": f"{v:.0f} other agents placed the same ticker and side in the last {W_M} steps",
        "xa_near_env": f"{v:.0f} other agents sent near-cap orders into this envelope in the last {W_L} steps",
        "sizesim": f"{v:.0f} recent orders on the same ticker and side have a near-identical size",
        "same_step": f"{v:.0f} other orders on the same ticker and side in this very step",
        "strong_nbrs": f"it co-moves with {v:.0f} agents it has repeatedly traded alongside",
        "strong_frac": f"{v:.0%} of the agents trading with it are repeat co-movers",
        "side_pressure": f"the flow in this ticker is {v:+.0%} one-sided toward this side",
        "ticker_flow": "unusually heavy flow in this ticker",
        "vol_short": "the market is volatile",
        "vol_ratio": f"volatility is {v:.1f}x its long-run level",
        "text_logit": "the stated rationale reads like known bad scripts",
        "stated_ratio": f"the order is {math.exp(abs(v)):.0f}x {'larger' if v > 0 else 'smaller'} than the size the agent says it intends",
        "has_stated": "the rationale states a size",
        "script_dup": f"the same wording was used {v:.0f} times in the last {W_L} steps",
    }
    return t.get(name, name)


def build_matrix(cols: dict, texts: list[str] | None, env_specs: dict[int, dict], spd: dict[int, int], text_model=None, idx_runs=None):
    """Run the streaming engine over every run in a corpus and return the (N, NF) float32 matrix, in row order. One engine per run."""
    import numpy as np
    from .dataset import ENVS
    run = cols["run"]
    n = len(run)
    X = np.zeros((n, NF), np.float32)
    starts = np.flatnonzero(np.r_[True, run[1:] != run[:-1]])
    ends = np.r_[starts[1:], n]
    eng = FeatureEngine(text_model=text_model)
    sides = ("buy", "sell", "", "")
    steps, agents, envi, qty, lim, tp, notional, kid, trig, ticker, side = (cols[k] for k in ("step", "agent", "env", "qty", "limit", "tp", "notional", "kid", "trig", "ticker", "side"))
    for s, e in zip(starts, ends):
        r = int(run[s])
        eng.set_envelopes(env_specs[r], spd[r])
        eng.reset()
        for i in range(s, e):
            tpi = float(tp[i])
            ev = {"step": int(steps[i]), "agent": int(agents[i]), "env": ENVS[envi[i]], "ticker": str(ticker[i]), "side": sides[side[i]], "qty": float(qty[i]),
                  "limit": float(lim[i]), "tp": None if tpi != tpi else tpi, "notional": float(notional[i]), "key": int(kid[i]),
                  "trig": None if trig[i] < 0 else bool(trig[i]), "listed": tpi == tpi}
            if texts is not None:
                ev["text"] = texts[i]
            X[i] = eng.featurize(ev)
            eng.update(ev)
    return X
