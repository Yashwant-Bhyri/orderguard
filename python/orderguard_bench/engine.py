"""Shard workers: the real `orderguard_arena.authority.Authority` (one per owner) over a slice of the workload, optionally followed by
the shipped order-risk model, writing a hash-chained decision log for the auditor.

Sharding. State is partitioned by owner: an owner's envelopes, their daily budgets, portfolio state, idempotency keys and the agents
pinned to them all live in exactly one worker process. Nothing mutable is shared between workers. Each worker reads its own copy of
the market data (prices and the news verdicts recorded in the workload). So the gate's decisions do not depend on the number of
workers, which the auditor checks (one digest per run, identical across worker counts). The order-risk model is the exception: its
features include flow across envelopes and tickers, so a sharded scorer sees only its shard's flow and its decisions can differ from
one global scorer. The N=1 run is the reference for the economic numbers.

Per decision, a worker: updates trusted prices at each new step (once per shard), calls `Authority.authorize` (L1 normalisation,
idempotency, L7 verdict, L5 envelope rules at the trusted price, portfolio limits, atomic reservation), optionally scores the order
with `RiskScorer` and applies `tighten` (allow can only become hold or refuse), and appends one JSON record to its decision log,
chained by SHA-256. The log is buffered and not fsynced: it is the auditor's evidence for this benchmark, not a durable ledger (the
TypeScript receiver is the durable effect boundary and is measured separately).

Mutations (`mutation=`) deliberately break one guarantee in the worker process only, so the auditor can be shown to catch it.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np

from orderguard_arena import envelopes as ENV
from orderguard_arena.arena import at_risk
from orderguard_arena.authority import Authority
from orderguard_arena.envelopes import Envelope, split_sleeves

from . import workload as W
from .market import BenchMarket
from .profiles import Profile

GENESIS = "0" * 64
MUTATIONS = ("budget_off", "idempotency_off", "portfolio_off", "revoke_off")


class _P:                         # the shape arena.at_risk expects
    __slots__ = ("order",)

    def __init__(self, order):
        self.order = order


def apply_mutation(name: str | None) -> None:
    """Break one guarantee for this process. Only ever called inside a mutation worker."""
    if not name:
        return
    if name not in MUTATIONS:
        raise ValueError(f"unknown mutation {name!r}")
    if name == "budget_off":
        def reserve(self, day, amount, agent=None, agent_cap=None):
            with self._lock:
                self._used[day] = self._used.get(day, 0) + round(amount * 100)
                return True
        ENV.DailyBudget.reserve = reserve
        check = ENV.Envelope.check

        def no_daily(self, *a, **k):
            r, h, n = check(self, *a, **k)
            return [x for x in r if "daily cap" not in x], h, n
        ENV.Envelope.check = no_daily
    elif name == "idempotency_off":
        class Forgetful(dict):
            def __setitem__(self, k, v):
                pass

            def get(self, k, default=None):
                return default
        orig = Authority.__init__

        def init(self, *a, **k):
            orig(self, *a, **k)
            self._seen = Forgetful()
        Authority.__init__ = init
    elif name == "portfolio_off":
        ENV.portfolio_reasons = lambda *a, **k: []
    elif name == "revoke_off":
        Authority.revoke = lambda self, envelope: None


class DecisionLog:
    """One JSON object per line, prefixed by its chain hash: `<sha256(prev|body)> <body>`."""

    def __init__(self, path: Path | None):
        self.fh = open(path, "w", buffering=1 << 20) if path else None
        self.prev = GENESIS
        self.n = 0

    def append(self, rec: dict) -> None:
        body = json.dumps(rec, separators=(",", ":"), sort_keys=True)
        h = hashlib.sha256((self.prev + "|" + body).encode()).hexdigest()
        self.prev = h
        self.n += 1
        if self.fh:
            self.fh.write(h + " " + body + "\n")

    def close(self) -> str:
        if self.fh:
            self.fh.close()
        return self.prev


class Shard:
    def __init__(self, p: Profile, owners: list[int], market: BenchMarket, *, risk: bool = False, log_path: Path | None = None):
        self.p, self.market = p, market
        sleeves = split_sleeves(market.symbols)
        self.prices: dict = {}
        self.auth: dict[int, Authority] = {}
        self.envs: dict[str, Envelope] = {}
        self.verify_ns: list[int] = []
        for o in owners:
            book = W.owner_book(p, o, sleeves)
            a = Authority(book, steps_per_day=p.steps_per_day)
            a.prices = self.prices                         # one trusted-price table per shard, updated once per step
            a._market.prices = self.prices
            self.auth[o] = a
            for e in book.envelopes():
                self.envs[e.name] = e
                t0 = time.perf_counter_ns()
                e.verify(book.public_key)                 # Ed25519 verification of the signed mandate (done on load, not per order)
                self.verify_ns.append(time.perf_counter_ns() - t0)
        self.scorer = None
        if risk:
            from orderguard_risk.scorer import RiskScorer, tighten
            self.scorer = RiskScorer.load()
            self.scorer.set_envelopes({e.name: {"per_order": e.max_order, "daily": e.budget.cap, "step_up": e.stepup, "band_pct": e.m.priceBandPct}
                                       for e in self.envs.values()}, p.steps_per_day)
            self._tighten = tighten
        self.log = DecisionLog(log_path)
        self.ctl: list[dict] = []

    # ---- control events ------------------------------------------------------------------------------------------------------------
    def control(self, it) -> dict:
        o, name, act = it[W.OWNER], it[W.ENV], it[W.ORDER]["action"]
        a = self.auth[o]
        e = a.book.get(name)
        out = {"action": act, "env": name, "step": it[0][0]}
        if act == "revoke":
            a.revoke(name)
            out["result"] = "revoked"
        elif act == "replay_mandate":
            before = a.book.get(name)
            try:
                after = a.book.add(Envelope(dict(e.mandate), name=e.name, owner=e.owner, purpose=e.purpose))
                out["result"] = "kept existing state" if after is before else "replaced"
            except ValueError as exc:
                out["result"] = "rejected: " + str(exc)[:120]
        elif act in ("tampered_mandate", "foreign_mandate"):
            m = W.tampered_copy(e.mandate) if act == "tampered_mandate" else W.foreign_copy(e.mandate, self.p.seed)
            try:
                a.book.add(Envelope(m, name=e.name, owner=e.owner, purpose=e.purpose))
                out["result"] = "accepted"
            except ValueError as exc:
                out["result"] = "rejected: " + str(exc)[:120]
        self.ctl.append(out)
        return out

    # ---- the hot loop --------------------------------------------------------------------------------------------------------------
    def run(self, items: list, *, stages: dict | None = None) -> dict:
        trusted = self.market.trusted
        prices = self.prices
        auth, log, scorer = self.auth, self.log, self.scorer
        lat_auth = np.empty(len(items), dtype=np.int64)
        lat_all = np.empty(len(items), dtype=np.int64)
        lat_risk = np.empty(len(items), dtype=np.int64) if scorer else None
        lat_log = np.empty(len(items), dtype=np.int64)
        n = 0
        counts = {"allow": 0, "hold": 0, "refuse": 0}
        cur = -1
        pc = time.perf_counter_ns
        t_start = time.monotonic_ns()
        for it in items:
            step = it[0][0]
            if step != cur:
                prices.clear()
                prices.update(trusted[step])
                cur = step
            if it[W.KIND] == "ctl":
                c = self.control(it)
                log.append({"x": "ctl", "t": step, "e": it[W.ENV], "o": it[W.OWNER], "ctl": c["action"], "res": c["result"], "k": it[W.KEY]})
                continue
            o = it[W.OWNER]
            a = auth[o]
            order = it[W.ORDER]
            t0 = pc()
            if stages is not None:
                stages["_cur"] = {}
            d = a.authorize(order, key=it[W.KEY], envelope=self.envs.get(it[W.ENV]), trigger=it[W.TRIG], step=step, agent=it[W.AGENT])
            t1 = pc()
            final, ra = d.decision, None
            tk = order.get("ticker")
            tp = prices.get(tk) if isinstance(tk, str) else None
            if scorer is not None:
                trig = it[W.TRIG]
                side = order.get("side") or ""
                if order.get("type") == "transfer" or "destination_account" in order:
                    side = ""
                ev = {"step": step, "agent": it[W.AGENT], "env": it[W.ENV], "ticker": str(tk or ""), "side": side,
                      "qty": float(order.get("quantity") or 0), "limit": float(order.get("limit_price") or 0.0), "tp": tp,
                      "notional": at_risk(_P(order), tp, prices), "key": it[W.KEY], "trig": None if trig is None else bool(trig.get("confirmed")),
                      "listed": tp is not None}
                r = scorer.score(ev)
                scorer.observe(ev)
                ra = r["action"]
                if d.decision == "allow" and not d.replay:
                    final = self._tighten("allow", r)
            t2 = pc()
            log.append({"i": n, "t": step, "k": it[W.KEY], "e": it[W.ENV], "o": o, "a": it[W.AGENT], "l": it[W.LABEL], "x": it[W.KIND],
                        "q": order, "g": d.decision, "d": final, "r": d.replay, "n": d.notional, "p": d.trusted, "c": d.code, "y": d.layer,
                        "tr": None if it[W.TRIG] is None else bool(it[W.TRIG].get("confirmed")), "nid": None if it[W.TRIG] is None else it[W.TRIG].get("news_id"),
                        "rk": ra})
            t3 = pc()
            lat_auth[n], lat_log[n], lat_all[n] = t1 - t0, t3 - t2, t3 - t0
            if lat_risk is not None:
                lat_risk[n] = t2 - t1
            if stages is not None:
                stages["rows"].append({**stages["_cur"], "authorize": t1 - t0, "risk": (t2 - t1) if scorer else None, "log": t3 - t2})
            counts[final] += 1
            n += 1
        t_end = time.monotonic_ns()
        head = log.close()
        return {"decisions": n, "counts": counts, "t_start": t_start, "t_end": t_end, "head": head, "log_records": log.n,
                "lat_authorize": lat_auth[:n], "lat_pipeline": lat_all[:n], "lat_risk": None if lat_risk is None else lat_risk[:n],
                "lat_log": lat_log[:n], "ctl": self.ctl}


# ---- process orchestration ---------------------------------------------------------------------------------------------------------------
def _worker(p: Profile, gen_dir: str, parts: list[int], log_path: str | None, risk: bool, mutation: str | None, barrier, q, wid: int) -> None:
    try:
        apply_mutation(mutation)
        market = BenchMarket(p.seed, p.steps, p.steps_per_day)
        owners, items = W.load_items(Path(gen_dir), parts)
        shard = Shard(p, owners, market, risk=risk, log_path=Path(log_path) if log_path else None)
        barrier.wait()
        res = shard.run(items)
        res["owners"] = len(owners)
        res["envelopes"] = len(shard.envs)
        res["verify_ns"] = shard.verify_ns
        res["wid"] = wid
        q.put(res)
    except BaseException as exc:            # report, never hang the parent
        q.put({"wid": wid, "error": f"{type(exc).__name__}: {exc}"})
        try:
            barrier.abort()
        except Exception:
            pass


def run_config(p: Profile, gen_dir: Path, log_dir: Path | None, workers: int, *, risk: bool = False, mutation: str | None = None,
               parts: list[int] | None = None) -> dict:
    """Run `workers` shard processes over the generated workload (partitions split round-robin). Returns aggregate stats and log paths."""
    parts = list(range(p.partitions)) if parts is None else parts
    if len(parts) % workers and workers > 1:
        raise ValueError(f"{workers} workers do not divide {len(parts)} partitions")
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(workers)
    q = ctx.Queue()
    procs, logs = [], []
    for w in range(workers):
        mine = [k for i, k in enumerate(parts) if i % workers == w]
        lp = str(log_dir / f"shard-{w}.log") if log_dir else None
        logs.append(lp)
        pr = ctx.Process(target=_worker, args=(p, str(gen_dir), mine, lp, risk, mutation, barrier, q, w), daemon=True)
        pr.start()
        procs.append(pr)
    res = [q.get() for _ in procs]
    for pr in procs:
        pr.join(timeout=60)
    errs = [r["error"] for r in res if "error" in r]
    if errs:
        raise RuntimeError("shard worker failed: " + "; ".join(errs))
    res.sort(key=lambda r: r["wid"])
    wall = (max(r["t_end"] for r in res) - min(r["t_start"] for r in res)) / 1e9
    n = sum(r["decisions"] for r in res)
    cat = lambda k: np.concatenate([r[k] for r in res]) if res and res[0][k] is not None else None
    out = {"workers": workers, "risk": risk, "mutation": mutation, "decisions": n, "wall_s": round(wall, 4),
           "decisions_per_s": round(n / wall) if wall else 0,
           "per_worker": [{"wid": r["wid"], "owners": r["owners"], "envelopes": r["envelopes"], "decisions": r["decisions"],
                           "busy_s": round((r["t_end"] - r["t_start"]) / 1e9, 4),
                           "decisions_per_s": round(r["decisions"] / ((r["t_end"] - r["t_start"]) / 1e9)) if r["t_end"] > r["t_start"] else 0} for r in res],
           "counts": {k: sum(r["counts"][k] for r in res) for k in ("allow", "hold", "refuse")},
           "latency_us": {"authorize": pct(cat("lat_authorize")), "pipeline": pct(cat("lat_pipeline")), "log_append": pct(cat("lat_log"))},
           "verify_us": pct(np.asarray([v for r in res for v in r["verify_ns"]], dtype=np.int64)),
           "logs": [lp for lp in logs if lp], "heads": [r["head"] for r in res], "ctl": [c for r in res for c in r["ctl"]]}
    if risk:
        out["latency_us"]["risk_score"] = pct(cat("lat_risk"))
    return out


def pct(ns) -> dict:
    """p50 / p99 / p99.9 / max / mean in microseconds from nanosecond samples."""
    if ns is None or len(ns) == 0:
        return {"n": 0}
    a = np.asarray(ns, dtype=np.float64) / 1000.0
    q = np.percentile(a, [50, 90, 99, 99.9])
    return {"n": int(len(a)), "p50": round(float(q[0]), 2), "p90": round(float(q[1]), 2), "p99": round(float(q[2]), 2), "p999": round(float(q[3]), 2),
            "max": round(float(a.max()), 2), "mean": round(float(a.mean()), 2)}


# ---- per-stage profile ---------------------------------------------------------------------------------------------------------------------
def stage_profile(p: Profile, gen_dir: Path, limit: int) -> dict:
    """One process, one shard (all owners), the first `limit` decisions, with each stage's real function wrapped by a timer.
    Wrapping adds a little overhead per call; the end-to-end figures come from the unwrapped runs."""
    market = BenchMarket(p.seed, p.steps, p.steps_per_day)
    owners, items = W.load_items(gen_dir, list(range(p.partitions)))
    items = items[: limit]
    stages = {"rows": [], "_cur": {}}
    pc = time.perf_counter_ns
    orig_check, orig_reserve, orig_port = ENV.Envelope.check, ENV.Envelope.reserve, ENV.portfolio_reasons
    state = {"in_reserve": False}

    def port(*a, **k):
        t = pc()
        r = orig_port(*a, **k)
        c = stages["_cur"]
        key = "portfolio_in_reserve" if state["in_reserve"] else "portfolio_in_check"
        c[key] = c.get(key, 0) + pc() - t
        return r

    def check(self, *a, **k):
        t = pc()
        r = orig_check(self, *a, **k)
        c = stages["_cur"]
        c["check"] = c.get("check", 0) + pc() - t
        return r

    def reserve(self, *a, **k):
        state["in_reserve"] = True
        t = pc()
        try:
            return orig_reserve(self, *a, **k)
        finally:
            c = stages["_cur"]
            c["reserve"] = c.get("reserve", 0) + pc() - t
            state["in_reserve"] = False

    ENV.Envelope.check, ENV.Envelope.reserve, ENV.portfolio_reasons = check, reserve, port
    try:
        shard = Shard(p, owners, market, risk=True)
        shard.run(items, stages=stages)
    finally:
        ENV.Envelope.check, ENV.Envelope.reserve, ENV.portfolio_reasons = orig_check, orig_reserve, orig_port
    rows = stages["rows"]

    def col(f):
        return np.asarray([v for v in (f(r) for r in rows) if v is not None and v >= 0], dtype=np.int64)
    out = {
        "decisions": len(rows),
        "verify_mandate": pct(np.asarray(shard.verify_ns, dtype=np.int64)),
        "gate": pct(col(lambda r: (r.get("check", 0) - r.get("portfolio_in_check", 0)) if "check" in r else None)),
        "portfolio_limits": pct(col(lambda r: (r.get("portfolio_in_check", 0) + r.get("portfolio_in_reserve", 0)) if ("portfolio_in_check" in r or "portfolio_in_reserve" in r) else None)),
        "reservation": pct(col(lambda r: (r["reserve"] - r.get("portfolio_in_reserve", 0)) if "reserve" in r else None)),
        "idempotency_and_routing": pct(col(lambda r: r["authorize"] - r.get("check", 0) - r.get("reserve", 0))),
        "authorize_total": pct(col(lambda r: r["authorize"])),
        "risk_score": pct(col(lambda r: r["risk"])),
        "log_append": pct(col(lambda r: r["log"])),
    }
    # per-order signature verification, for context: what it would cost to re-verify the mandate on every order instead of on load
    e = next(iter(shard.envs.values()))
    pub = shard.auth[owners[0]].book.public_key
    ns = []
    for _ in range(2000):
        t = pc()
        e.m.verify(pub)
        ns.append(pc() - t)
    out["verify_per_order_if_reverified"] = pct(np.asarray(ns, dtype=np.int64))
    return out


# ---- how one scorer's cost grows with the share of the swarm it sees ---------------------------------------------------------------------
def scorer_scaling(p: Profile, gen_dir: Path, seconds: float, shares=(1, 2)) -> dict:
    """One gate + risk shard over 1/8 and 2/8 of the owners (4/8 is past the cliff: one 5,000-decision chunk takes minutes; see full-partial.json), each for at most `seconds`: microseconds per decision per 5,000-decision
    chunk and the size of the feature engine's agent co-activity map. Shows where one scorer stops scaling."""
    market = BenchMarket(p.seed, p.steps, p.steps_per_day)
    points = []
    for k in shares:
        parts = list(range(min(k, p.partitions)))
        owners, items = W.load_items(gen_dir, parts)
        shard = Shard(p, owners, market, risk=True)
        rows, t_end = [], time.monotonic() + seconds
        for i in range(0, len(items), 5_000):
            t = time.perf_counter()
            r = shard.run(items[i:i + 5_000])
            dt = time.perf_counter() - t
            rows.append({"decisions_done": i + r["decisions"], "step": items[min(i + 5_000, len(items)) - 1][0][0],
                         "edges": len(shard.scorer.engine.edges), "us_per_decision": round(dt / max(r["decisions"], 1) * 1e6, 1)})
            if time.monotonic() > t_end:
                break
        points.append({"share": f"{len(parts)}/{p.partitions}", "agents_seen": round(p.agents * len(parts) / p.partitions), "chunks": rows,
                       "us_per_decision_last": rows[-1]["us_per_decision"], "edges_last": rows[-1]["edges"], "completed": rows[-1]["decisions_done"] >= len(items)})
    return {"seconds_per_point": seconds, "edge_cap": 400_000, "points": points,
            "note": "orderguard_risk.features prunes its co-activity map by rebuilding it on every update once it holds more than 400,000 edges; "
                    "when nearly all edges are recent, pruning frees nothing and every decision pays the rebuild"}
