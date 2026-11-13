"""The arena: feed ticks -> agents propose -> the authority decides -> simulated fills -> metrics and an event log.

Deterministic for a seed (agents, feed, fills and the event stream; wall-clock timing is reported separately and is not part of
the digest). Ground truth for the metrics (which proposals are legitimate) comes from the agents' labels, an ORACLE the authority
never sees.

Definitions used in the summary:
  legit            proposals labelled "legit": honest strategy orders (including the first order of a runaway loop)
  bad              every other label: honest-agent errors (fat finger, stale price, off-list), compromised agents, runaway repeats,
                   colluders and orders triggered by fake news. "attack $" below means the notional of these.
  attack notional  quantity x TRUSTED price (a homoglyph ticker is priced as the symbol it imitates; an unlisted ticker and a transfer
                   are valued at their own stated limit price / amount, because no trusted price exists)
  blocked / leaked bad notional the authority refused or held / allowed. A repeated idempotency key returns the first decision and
                   moves nothing, so a duplicate is counted as absorbed, not leaked.
  false refusal    a legit proposal that was refused (a hold is reported separately as a human-approval load)
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from orderguard_guard import ROOT
from orderguard_guard.normalise import fold_confusables

from .agents import Agent, Ctx, PopulationConfig, Proposal, make_population
from .authority import Authority
from .envelopes import EnvelopeBook, default_envelopes, split_sleeves
from .feeds import MarketFeed, ReplayFeed

ARENA_DIR = Path(os.getenv("OG_ARENA_DIR", ROOT / "results" / "arena"))


@dataclass
class ArenaConfig:
    seed: int = 7
    agents: int = 200
    steps: int = 2000
    steps_per_day: int = 500
    routing: str = "pinned"                       # pinned | tightest_fit
    rates: dict | None = None
    fail_prob: float = 0.15
    slippage_bps: float = 3.0
    revoke: dict | None = None                    # {"step": N, "envelope": "tactical"}
    strict: bool = False
    agent_share: float | None = None              # optional operator fair-share policy (see authority.py)
    paired_fills: bool = False                  # stable fill draws for the same proposal in policy comparisons
    name: str | None = None
    keep_events: bool = True


@dataclass
class ArenaResult:
    summary: dict
    events: list = field(default_factory=list)
    authority: Authority | None = None
    agents: list = field(default_factory=list)
    path: Path | None = None


def at_risk(p: Proposal, tp: float | None, prices: dict) -> float:
    """Notional of a proposal for the oracle (see the module docstring)."""
    o = p.order
    if o.get("type") == "transfer" or "destination_account" in o:
        return float(o.get("amount_usd") or 0.0)
    q = float(o.get("quantity") or 0)
    px = tp
    if px is None:
        t = str(o.get("ticker") or "")
        px = prices.get(fold_confusables(t).upper()) or float(o.get("limit_price") or 0.0)
    return round(q * px, 2)


def _collude_caps(book: EnvelopeBook, symbols: list[str]) -> tuple[dict, dict]:
    """What colluders are assumed to know (worst case): the per-order cap, lowered to the step-up threshold, and the daily cap."""
    caps, daily = {}, {}
    for s in symbols:
        e = book.home_for(s)
        if e is not None:
            caps[s] = min(e.max_order, e.stepup) if e.stepup is not None else e.max_order
            daily[s] = e.budget.cap
    return caps, daily


def baseline_spec(book: EnvelopeBook) -> list[dict]:
    return [{"name": e.name, "id": e.id, "symbols": sorted(e.allowed), "per_order": e.max_order, "daily": e.budget.cap, "band_pct": e.m.priceBandPct,
             "step_up": e.stepup, "purpose": e.purpose} for e in book.envelopes()]


def run_arena(cfg: ArenaConfig | None = None, *, feed: MarketFeed | None = None, book: EnvelopeBook | None = None,
              authority: Authority | None = None, agents: list[Agent] | None = None, out_dir: str | Path | None = None,
              write: bool = False, attach_receiver: bool = True) -> ArenaResult:
    cfg = cfg or ArenaConfig()
    feed = feed or ReplayFeed(cfg.seed, steps=cfg.steps, steps_per_day=cfg.steps_per_day)
    steps_total = len(feed) if hasattr(feed, "__len__") else cfg.steps
    spd = getattr(feed, "steps_per_day", cfg.steps_per_day)
    book = book or default_envelopes(feed.symbols, cfg.agents)
    build_authority = Authority.from_env if attach_receiver else Authority
    auth = authority or build_authority(book, steps_per_day=spd, routing=cfg.routing, strict=cfg.strict, agent_share=cfg.agent_share)
    sleeves = split_sleeves(feed.symbols)
    pcfg = PopulationConfig(n=cfg.agents, seed=cfg.seed, fail_prob=cfg.fail_prob)
    if cfg.rates is not None:
        pcfg.rates = dict(cfg.rates)
    agents = agents if agents is not None else make_population(pcfg, sleeves, steps_total)
    ctx = Ctx(steps_total, *_collude_caps(book, feed.symbols))
    rng = random.Random(cfg.seed * 7 + 3)
    home = {n: book.get(n) for n in sleeves}
    by_id = {a.id: a for a in agents}

    events: list[dict] = []
    digest = hashlib.sha256()
    by_label: dict[str, dict] = {}
    by_code: dict[str, int] = {}
    util: list[dict] = []
    cash = {a.id: 0.0 for a in agents}
    env_cash: dict[str, float] = {e.name: 0.0 for e in book.envelopes()}
    env_pos: dict[str, dict] = {e.name: {} for e in book.envelopes()}
    executed_bad = absorbed_bad = 0.0
    broker_rejects = unfilled = filled = 0
    proposals = 0
    liar_ticks = 0
    wall0 = time.perf_counter()
    decide_ns = 0
    path = None
    fh = None
    name = cfg.name or f"arena-s{cfg.seed}-k{cfg.agents}-t{steps_total}"
    if write:
        d = Path(out_dir or ARENA_DIR)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.jsonl"
        fh = path.open("w")
        fh.write(json.dumps({"type": "meta", "name": name, "config": asdict(cfg) | {"steps": steps_total, "steps_per_day": spd},
                             "symbols": feed.symbols, "agents": len(agents), "envelopes": baseline_spec(book),
                             "note": "simulated agents; every field is synthetic"}, sort_keys=True) + "\n")
    last_prices: dict = {}
    for snap in feed:
        step = snap.step
        auth.on_snapshot(snap)
        last_prices = dict(auth.prices)
        ctx.update(step, auth.prices, snap.meta.get("fake_news", ()))
        if snap.meta.get("liars"):
            liar_ticks += 1
        if cfg.revoke and step == cfg.revoke["step"]:
            auth.revoke(cfg.revoke["envelope"])
        props: list[Proposal] = []
        for a in agents:
            props.extend(a.propose(ctx, snap, step))
        occurrences: dict[tuple, int] = {}
        for p in props:
            proposals += 1
            fill_rng = rng
            if cfg.paired_fills:
                o = p.order
                terms = (p.agent, o.get("ticker"), o.get("side"), o.get("quantity"), o.get("limit_price"))
                occurrence = occurrences.get(terms, 0)
                occurrences[terms] = occurrence + 1
                fill_rng = random.Random(json.dumps([cfg.seed, step, terms, occurrence], separators=(",", ":")))
            env = home.get(p.sleeve) if cfg.routing == "pinned" else None
            trig = None
            if p.trigger is not None:
                ok, why = auth.confirm_trigger(p.trigger, p.order["ticker"], p.order["side"])
                trig = {**p.trigger, "confirmed": ok}
            t0 = time.perf_counter_ns()
            d = auth.authorize(p.order, key=p.key, envelope=env, owner=None, trigger=trig, step=step, agent=p.agent)
            decide_ns += time.perf_counter_ns() - t0
            tp = auth.prices.get(str(p.order.get("ticker"))) if p.order.get("ticker") else None
            risk = at_risk(p, tp, auth.prices)
            bl = by_label.setdefault(p.label, {"n": 0, "allow": 0, "hold": 0, "refuse": 0, "notional": 0.0, "allow_usd": 0.0, "hold_usd": 0.0,
                                               "refuse_usd": 0.0, "replays": 0, "replay_usd": 0.0})
            bl["n"] += 1
            bl["notional"] += risk
            if d.replay:                        # a repeated key returns the first answer and moves nothing: neither leak nor block
                bl["replays"] += 1
                bl["replay_usd"] += risk
            else:
                bl[d.decision] += 1
                bl[d.decision + "_usd"] += risk
            if d.reasons:
                by_code[d.code] = by_code.get(d.code, 0) + 1
            if d.replay and p.label != "legit":
                absorbed_bad += risk
            fill = None
            if d.decision == "allow" and not d.replay:
                ag = by_id[p.agent]
                px = _fill_price(p, tp, fill_rng, cfg.slippage_bps)
                if p.order["side"] == "sell" and ag.pos.get(p.order["ticker"], 0) < p.order["quantity"]:
                    broker_rejects += 1
                elif px is None:
                    unfilled += 1
                else:
                    q, side, sym = int(p.order["quantity"]), p.order["side"], p.order["ticker"]
                    ag.on_fill(sym, side, q)
                    sgn = -1.0 if side == "buy" else 1.0
                    cash[ag.id] += sgn * q * px
                    en = d.envelope
                    env_cash[en] += sgn * q * px
                    env_pos[en][sym] = env_pos[en].get(sym, 0) + (q if side == "buy" else -q)
                    filled += 1
                    fill = px
                    if p.label != "legit":
                        executed_bad += risk
            if cfg.keep_events or fh:
                ev = {"i": proposals, "step": step, "agent": p.agent, "sleeve": p.sleeve, "label": p.label, "order": p.order, "key": p.key,
                      "tp": tp, "risk": risk, "d": d.decision, "env": d.envelope, "code": d.code, "replay": d.replay}
                if cfg.paired_fills:
                    ev["fill_price"] = fill
                if trig is not None:
                    ev["trigger"] = trig
                if p.note:
                    ev["note"] = p.note
                line = json.dumps(ev, sort_keys=True, separators=(",", ":"))
                digest.update(line.encode())
                if cfg.keep_events:
                    events.append(ev)
                if fh:
                    fh.write(line + "\n")
            else:
                digest.update(f"{p.key}|{d.decision}|{d.envelope}|{d.code}".encode())
        if step % max(spd // 10, 1) == 0:
            day = step // spd
            util.append({"step": step, "day": day, **{e.name: round(e.budget.used(day) / e.budget.cap, 4) for e in book.envelopes()}})
    wall = time.perf_counter() - wall0

    final_px = last_prices
    pnl_agent = {a.id: cash[a.id] + sum(q * final_px.get(s, 0.0) for s, q in a.pos.items()) for a in agents}
    pnl_arch: dict[str, float] = {}
    for a in agents:
        pnl_arch[a.archetype] = pnl_arch.get(a.archetype, 0.0) + pnl_agent[a.id]
    pnl_env = {n: env_cash[n] + sum(q * final_px.get(s, 0.0) for s, q in env_pos[n].items()) for n in env_cash}

    legit = by_label.get("legit", {"n": 0, "allow": 0, "hold": 0, "refuse": 0, "notional": 0.0, "allow_usd": 0.0, "hold_usd": 0.0, "refuse_usd": 0.0})
    bad = {k: sum(v[k] for l, v in by_label.items() if l != "legit") for k in ("n", "allow", "hold", "refuse", "notional", "allow_usd", "hold_usd", "refuse_usd")}
    ndays = max(1, -(-steps_total // spd))
    lat = auth.latency_us()
    summary = {
        "name": name,
        "config": asdict(cfg) | {"steps": steps_total, "steps_per_day": spd, "days": ndays},
        "digest": digest.hexdigest()[:32],
        "proposals": proposals,
        "decisions": dict(auth.counts),
        "replays_absorbed": sum(v["replays"] for v in by_label.values()),
        "refusal_reasons": dict(sorted(by_code.items(), key=lambda kv: -kv[1])),
        "legit": {"proposals": legit["n"], "allowed": legit["allow"], "held": legit["hold"], "refused": legit["refuse"],
                  "notional_usd": round(legit["notional"], 2), "allowed_usd": round(legit["allow_usd"], 2),
                  "held_usd": round(legit["hold_usd"], 2), "refused_usd": round(legit["refuse_usd"], 2),
                  "false_refusal_rate": round(legit["refuse"] / legit["n"], 5) if legit["n"] else 0.0,
                  "hold_rate": round(legit["hold"] / legit["n"], 5) if legit["n"] else 0.0},
        "bad": {"proposals": bad["n"], "allowed": bad["allow"], "held": bad["hold"], "refused": bad["refuse"],
                "attack_notional_usd": round(bad["notional"], 2), "blocked_usd": round(bad["refuse_usd"] + bad["hold_usd"], 2),
                "leaked_usd": round(bad["allow_usd"], 2), "executed_usd": round(executed_bad, 2), "duplicates_absorbed_usd": round(absorbed_bad, 2),
                "leak_per_day_usd": round(bad["allow_usd"] / ndays, 2), "blocked_share": round((bad["refuse_usd"] + bad["hold_usd"]) / bad["notional"], 5) if bad["notional"] else 1.0},
        "by_label": {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in sorted(by_label.items())},
        "approvals_per_day": round(auth.counts["hold"] / ndays, 2),
        "fills": {"filled": filled, "unfilled": unfilled, "rejected_by_broker": broker_rejects},
        "utilisation_peak": {e.name: round(max((u[e.name] for u in util), default=0.0), 4) for e in book.envelopes()},
        "utilisation_series": util[:: max(1, len(util) // 60)],
        "pnl_usd": {"by_archetype": {k: round(v, 2) for k, v in sorted(pnl_arch.items())}, "by_envelope": {k: round(v, 2) for k, v in pnl_env.items()}},
        "envelopes": baseline_spec(book),
        "feed": {"liar_ticks": liar_ticks, "symbols": feed.symbols},
        "timing": {"wall_s": round(wall, 3), "authority_decisions_per_s": round(proposals / (decide_ns / 1e9)) if decide_ns else 0,
                   "end_to_end_proposals_per_s": round(proposals / wall) if wall else 0, "latency_us": {k: round(v, 2) for k, v in lat.items()}},
        "l8": auth.l8 if auth.receiver is not None else None,
        "caveats": ["agents are simulated; labels are the arena's ground truth", "fills use trusted price +/- slippage; PnL is mark-to-market at the last trusted price",
                    "budget counts authorized notional (reserved at allow), not filled notional"],
    }
    if fh:
        fh.close()
        (path.with_suffix(".summary.json")).write_text(json.dumps(summary, indent=1, sort_keys=True))
    return ArenaResult(summary, events, auth, agents, path)


def _fill_price(p: Proposal, tp: float | None, rng: random.Random, slip_bps: float) -> float | None:
    """Simulated broker: marketable limits fill at trusted price +/- slippage; passive ones fill at the limit with probability 0.4."""
    if tp is None:
        return None
    o = p.order
    s = rng.uniform(0.2, 2.0) * slip_bps / 10_000.0
    buy = o["side"] == "buy"
    px = tp * (1 + s if buy else 1 - s)
    lim = float(o["limit_price"])
    if (buy and lim >= px) or (not buy and lim <= px):
        return round(px, 4)
    return round(lim, 4) if rng.random() < 0.4 else None


def load_stream(path: str | Path) -> tuple[dict, list[dict]]:
    """(meta, events) from an event log written by run_arena(write=True)."""
    meta, events = {}, []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("type") == "meta":
            meta = d
        else:
            events.append(d)
    return meta, events
