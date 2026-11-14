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
    # invariants (v2): the inputs of the programmed units. Each is a mandate- or baseline-relative quantity, so one threshold means the
    # same thing in every envelope and for every agent.
    "size_jump", "size_vs_max", "rate_break", "agent_rate60", "rate_peer", "usd_peer", "usd_day_peer", "dup_exact", "dup_run",
    "dev_ratio", "dev_vol", "cross_band", "hot_peers", "sync_size_agents", "abs_dev", "new_ticker",
    "off_cadence", "cadence_n", "off_rate",
]
IX = {n: i for i, n in enumerate(NAMES)}
NF = len(NAMES)
BEHAV = [n for n in NAMES if n not in ("text_logit", "stated_ratio", "has_stated", "script_dup")]
BEHAV_V1 = BEHAV[:35]                               # the columns of the first shipped model (kept for the comparison)
W_R, HOT_N = 60, 5                                  # agent/envelope rate window; orders in W_AG steps that make an agent "hot"


class _Win:
    """Sliding window of (step, agent, bucket) for one key; distinct-agent and size-bucket counters."""
    __slots__ = ("w", "q", "ag", "bk", "ba", "bn")

    def __init__(self, w: int):
        self.w, self.q, self.ag, self.bk = w, deque(), Counter(), Counter()
        self.ba, self.bn = {}, {}                    # (bucket, agent) -> count; bucket -> distinct agents

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
            k = (b, a)
            c = self.ba[k] - 1
            if c:
                self.ba[k] = c
            else:
                del self.ba[k]
                c = self.bn[b] - 1
                if c:
                    self.bn[b] = c
                else:
                    del self.bn[b]

    def add(self, step: int, agent, bucket) -> None:
        self.q.append((step, agent, bucket))
        self.ag[agent] += 1
        self.bk[bucket] += 1
        k = (bucket, agent)
        c = self.ba.get(k, 0)
        self.ba[k] = c + 1
        if not c:
            self.bn[bucket] = self.bn.get(bucket, 0) + 1


class _Agent:
    __slots__ = ("n", "mu", "var", "last_step", "last_side", "tick", "recent", "dups", "dupq", "cf", "nc", "keys", "day", "day_usd", "day_n",
                 "first", "maxn", "r60", "u60", "u60s", "dx", "sig", "run", "dev", "rmu", "c0", "g", "cn", "offr")

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
        self.first, self.maxn = -1, 0.0              # first step seen; largest notional so far
        self.r60: deque = deque()                    # steps of this agent's orders in the last W_R steps
        self.u60: deque = deque()                    # (step, notional) in the last W_R steps, and their sum
        self.u60s = 0.0
        self.dx: Counter = Counter()                 # exact (ticker, side, qty, limit) repeats inside W_DUP
        self.sig, self.run = None, 0                 # last exact order signature and the length of the run of consecutive repeats
        self.dev = 0.002                             # EW mean of |limit / trusted - 1|: the agent's usual distance from the price
        self.rmu = 0.0                               # robust size baseline: like mu, but one outlier moves it by at most 0.05 nats
        self.c0, self.g, self.cn, self.offr = -1, 0, 0, 0.0   # cadence: first untriggered step, gcd of its gaps, orders folded, EW off-cadence rate


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
        self.env_w: dict = {}                         # env -> [deque (step, agent, notional), Counter agents, usd sum]
        self.env_ag: dict = {}                        # env -> [day, set of agents seen today]
        self.hot: dict = {}                           # env -> {agent: last step it was hot (>= HOT_N orders in W_AG steps)}

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
                _, k0, s0 = dq.popleft()
                a.dups[k0] -= 1
                a.dx[s0] -= 1
                if not a.dx[s0]:
                    del a.dx[s0]
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
        # ---- invariants (v2) ----
        adev = abs(limit / tp - 1.0) if tp and limit else 0.0
        ew = self.env_w.get(env)
        if ew is not None:
            q, c = ew[0], ew[1]
            lim = step - W_R
            while q and q[0][0] <= lim:
                _, a0, u0 = q.popleft()
                ew[2] -= u0
                c[a0] -= 1
                if not c[a0]:
                    del c[a0]
            n_act = len(c) + (0 if agent in c else 1)
            peer_n, peer_usd = (len(q) + 1.0) / n_act, (ew[2] + notional) / n_act
        else:
            peer_n, peer_usd = 1.0, notional
        ea = self.env_ag.get(env)
        if a is None:
            f[42], f[43], f[44], f[45] = 1.0, 1.0 / peer_n, notional / (peer_usd + 1.0), 1.0
            f[48] = 1.0
        else:
            if a.n >= 3:
                f[39] = ln - a.rmu
                f[40] = math.log((notional + 1.0) / (a.maxn + 1.0))
                f[48] = adev / (a.dev + 5e-4)
            else:
                f[48] = 1.0
            q = a.r60
            lim = step - W_R
            while q and q[0] <= lim:
                q.popleft()
            uq = a.u60
            while uq and uq[0][0] <= lim:
                a.u60s -= uq.popleft()[1]
            n60 = len(q) + 1
            old_n = a.n - len(a.recent)
            old_age = step - W_AG - a.first
            f[41] = f[19] / (W_AG * (old_n + 1.0) / (max(old_age, 0) + 50.0) + 1.0)
            f[42] = n60
            f[43] = n60 / peer_n
            f[44] = (a.u60s + notional) / (peer_usd + 1.0)
            if ed and ed[0] == day and ea is not None and ea[0] == day:
                nd = len(ea[1]) + (0 if agent in ea[1] else 1)
                f[45] = ((a.day_usd if a.day == day else 0.0) + notional) / ((ed[1] + notional) / nd + 1.0)
            else:
                f[45] = 1.0
            sg = (tk, side, ev.get("qty"), limit)
            f[46] = a.dx.get(sg, 0)
            f[47] = a.run if a.sig == sg and step - a.last_step <= 2 else 0
            f[54] = 1.0 if a.n >= 10 and tk not in a.tick else 0.0
            if tg is None and a.cn >= 4 and a.g >= 5:
                df = step - a.c0
                if df % a.g and math.gcd(a.g, df) < max(10, a.g // 4):
                    f[55] = 1.0                      # the agent has a schedule and this order is off it
            f[56] = math.log1p(a.cn)
            f[57] = a.offr
        f[49] = adev / (p[1] + 1e-3) if p is not None else adev / 1e-3
        f[50] = f[9] * 100.0 / band
        f[53] = adev
        hs = self.hot.get(env)
        if hs:
            lim = step - W_R
            f[51] = sum(1 for b, st in hs.items() if st > lim and b != agent)
        if wm is not None and ratio >= 0.2:
            bn = wm.bn
            k = bn.get(bucket, 0) + bn.get(bucket - 1, 0) + bn.get(bucket + 1, 0)
            if k:
                ba = wm.ba
                k -= (1 if (bucket, agent) in ba else 0) + (1 if (bucket - 1, agent) in ba else 0) + (1 if (bucket + 1, agent) in ba else 0)
            f[52] = k
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
        # ---- invariants (v2) state ----
        if a.first < 0:
            a.first = step
        if notional > a.maxn:
            a.maxn = notional
        lim = step - W_R
        q = a.r60
        while q and q[0] <= lim:
            q.popleft()
        q.append(step)
        uq = a.u60
        while uq and uq[0][0] <= lim:
            a.u60s -= uq.popleft()[1]
        uq.append((step, notional))
        a.u60s += notional
        limit = float(ev.get("limit") or 0.0)
        sg = (tk, side, ev.get("qty"), limit)
        a.run = a.run + 1 if a.sig == sg and step - a.last_step <= 2 else 1
        a.sig = sg
        tp0 = ev.get("tp")
        if tp0 and limit:
            a.dev += 0.1 * (min(abs(limit / tp0 - 1.0), 0.05) - a.dev)
        ew = self.env_w.get(env)
        if ew is None:
            ew = self.env_w[env] = [deque(), Counter(), 0.0]
        ew[0].append((step, agent, notional))
        ew[1][agent] += 1
        ew[2] += notional
        ea = self.env_ag.get(env)
        if ea is None or ea[0] != day:
            ea = self.env_ag[env] = [day, set()]
        ea[1].add(agent)
        rq = a.recent
        lim = step - W_AG
        while rq and rq[0] <= lim:
            rq.popleft()
        if len(rq) + 1 >= HOT_N and ev.get("trig") is None:
            hs = self.hot.get(env)
            if hs is None:
                hs = self.hot[env] = {}
            hs[agent] = step
            if len(hs) > 48:
                lim = step - W_R
                self.hot[env] = {b: st for b, st in hs.items() if st > lim}
        if ev.get("trig") is None:
            if a.c0 < 0:
                a.c0, a.cn = step, 1
            else:
                df = step - a.c0
                g2 = math.gcd(a.g, df)
                if a.cn >= 4 and a.g >= 5 and df % a.g and g2 < max(10, a.g // 4):
                    a.offr += 0.2 * (1.0 - a.offr)   # off schedule: remembered, not folded into the schedule
                else:
                    a.g, a.cn = g2, a.cn + 1
                    a.offr -= 0.2 * a.offr
        if a.n == 0:
            a.rmu = ln
        else:
            a.rmu += 0.1 * max(-0.5, min(0.5, ln - a.rmu))
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
        a.dx[sg] += 1
        a.dupq.append((step, dk, sg))
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

_EXPLAIN = {
    "cap_ratio": lambda v: f"the order is {v:.0%} of the per-order cap",
    "stepup_ratio": lambda v: f"the order is {v:.0%} of the step-up threshold",
    "log_notional": lambda v: f"a large order (about ${math.expm1(v):,.0f})",
    "near_cap": lambda v: "its size sits just under the per-order cap",
    "order_share_daily": lambda v: f"it uses {v:.2%} of the envelope's daily cap",
    "env_day_demand": lambda v: f"the envelope has already seen {v:.0%} of its daily cap in proposals today",
    "env_pace": lambda v: f"proposals are arriving at {v:.1f}x the pace that would just exhaust the daily cap",
    "agent_day_share": lambda v: f"this agent alone has proposed {v:.1f}% of the daily cap today",
    "agent_day_n": lambda v: f"this agent has placed {v:.0f} orders today",
    "limit_dev": lambda v: f"the limit is {v:+.1%} through the trusted price",
    "band_pos": lambda v: f"the limit is {v:.0%} of the way to the price band edge",
    "listed": lambda v: "the ticker is off the envelope's list",
    "is_transfer": lambda v: "it is not a trade",
    "trig": lambda v: "it claims a standing rule",
    "size_z": lambda v: f"the size is {v:+.1f} standard deviations from this agent's usual",
    "agent_n": lambda v: "this agent has little history",
    "agent_ticker_n": lambda v: f"this agent has traded this ticker {v:.0f} times before",
    "side_flip": lambda v: "the side flipped against this agent's last trade in the ticker",
    "inter_arrival": lambda v: f"{v:.0f} steps since this agent's last order",
    "agent_burst": lambda v: f"this agent sent {v:.0f} orders in the last {W_AG} steps",
    "dup_recent": lambda v: f"{v:.0f} identical orders from this agent in the last {W_DUP} steps",
    "dup_key": lambda v: "the idempotency key was already used by this agent",
    "agent_capfrac": lambda v: f"this agent's recent orders average {v:.0%} of the cap",
    "agent_nearcap_rate": lambda v: f"{v:.0%} of this agent's recent orders sat just under the cap",
    "xa_short": lambda v: f"{v:.0f} other agents placed the same ticker and side in the last {W_S} steps",
    "xa_med": lambda v: f"{v:.0f} other agents placed the same ticker and side in the last {W_M} steps",
    "xa_near_env": lambda v: f"{v:.0f} other agents sent near-cap orders into this envelope in the last {W_L} steps",
    "sizesim": lambda v: f"{v:.0f} recent orders on the same ticker and side have a near-identical size",
    "same_step": lambda v: f"{v:.0f} other orders on the same ticker and side in this very step",
    "strong_nbrs": lambda v: f"it co-moves with {v:.0f} agents it has repeatedly traded alongside",
    "strong_frac": lambda v: f"{v:.0%} of the agents trading with it are repeat co-movers",
    "side_pressure": lambda v: f"the flow in this ticker is {v:+.0%} one-sided toward this side",
    "ticker_flow": lambda v: "unusually heavy flow in this ticker",
    "vol_short": lambda v: "the market is volatile",
    "vol_ratio": lambda v: f"volatility is {v:.1f}x its long-run level",
    "text_logit": lambda v: "the stated rationale reads like known bad scripts",
    "stated_ratio": lambda v: f"the order is {math.exp(abs(v)):.0f}x {'larger' if v > 0 else 'smaller'} than the size the agent says it intends",
    "has_stated": lambda v: "the rationale states a size",
    "script_dup": lambda v: f"the same wording was used {v:.0f} times in the last {W_L} steps",
    "size_jump": lambda v: f"the order is {math.exp(v):.1f}x this agent's usual size",
    "size_vs_max": lambda v: f"the order is {math.exp(v):.1f}x the largest this agent has sent before",
    "rate_break": lambda v: f"this agent is sending orders at {v:.1f}x its own long-run rate",
    "agent_rate60": lambda v: f"this agent sent {v:.0f} orders in the last {W_R} steps",
    "rate_peer": lambda v: f"this agent is sending {v:.1f}x as many orders as the average active agent in the envelope",
    "usd_peer": lambda v: f"this agent moved {v:.1f}x the notional of the average active agent in the last {W_R} steps",
    "usd_day_peer": lambda v: f"this agent has used {v:.1f}x the average agent's share of today's flow",
    "dup_exact": lambda v: f"{v:.0f} orders with the same ticker, side, quantity and limit from this agent in the last {W_DUP} steps",
    "dup_run": lambda v: f"the same order has been re-sent {v:.0f} times in a row",
    "dev_ratio": lambda v: f"the limit is {v:.1f}x further from the trusted price than this agent's usual",
    "dev_vol": lambda v: f"the limit is {v:.1f}x further from the trusted price than recent price moves explain",
    "cross_band": lambda v: f"the limit crosses the trusted price by {v:.0%} of the price band",
    "hot_peers": lambda v: f"{v:.0f} other agents in this envelope are also sending bursts of orders",
    "sync_size_agents": lambda v: f"{v:.0f} other agents sent near-identical large sizes on the same ticker and side in the last {W_M} steps",
    "abs_dev": lambda v: f"the limit is {v:.1%} away from the trusted price",
    "new_ticker": lambda v: "an established agent is trading a ticker it has never traded",
    "off_cadence": lambda v: "the order arrives off this agent's established schedule",
    "cadence_n": lambda v: "this agent has an established schedule",
    "off_rate": lambda v: f"{v:.0%} of this agent's recent orders were off its schedule",
}


def explain(name: str, v: float) -> str:
    """One feature value in plain English (only the requested entry is formatted)."""
    fn = _EXPLAIN.get(name)
    if fn is None:
        return name
    try:
        return fn(v)
    except (OverflowError, ValueError):
        return name


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
