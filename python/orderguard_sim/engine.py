"""Impact-market run loop: sparse agent orders -> real authority -> market impact."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from orderguard_arena.authority import Authority
from orderguard_arena.envelopes import EnvelopeBook, make_envelope, owner_key_from_seed
from orderguard_arena.feeds import DEFAULT_SYMBOLS, Snapshot
from orderguard_guard.money import notional_cents, usd_cents
from orderguard_risk.scorer import RiskScorer, tighten

from .market import DEFAULT_RECORDING, ImpactMarket
from .population import VectorPopulation
from .scenarios import Scenario, build_scenario

SIM_DIR = Path(__file__).resolve().parents[2] / "results" / "sim"
ARMS = ("unguarded", "gate_only", "gate_portfolio", "full", "frontier_tight", "frontier_loose", "frontier_open")


@dataclass(frozen=True)
class SimConfig:
    agents: int = 10_000
    steps: int = 64
    seed: int = 7
    replicates: int = 3
    activity: float = 0.0005
    attack_activity: float = 0.04
    envelopes: int = 0                       # 0 = one envelope per ~1,000 agents, up to 1,000
    steps_per_day: int = 0                   # 0 = one simulated session
    impact_eta: float = 1.0
    impact_decay: float = 0.82
    risk_model: str | None = None

    def effective_envelopes(self) -> int:
        return int(self.envelopes or min(1000, max(1, math.ceil(self.agents / 1000))))

    def day_steps(self) -> int:
        return int(self.steps_per_day or max(self.steps, 1))


def _caps_for(agents_per_envelope: int, cfg: SimConfig, variant: str) -> dict:
    base_order = 25_000.0
    base_daily = max(base_order * 2.0, agents_per_envelope * cfg.activity * cfg.steps * 4_000.0 * 0.7)
    if variant == "frontier_tight":
        po, daily, sym, pos = base_order * 0.65, base_daily * 0.55, 0.55, 0.65
    elif variant == "frontier_loose":
        po, daily, sym, pos = base_order * 1.6, base_daily * 1.8, 0.85, 1.2
    elif variant == "frontier_open":
        po, daily, sym, pos = base_order * 2.0, base_daily * 6.0, 0.90, 1.5
    else:
        po, daily, sym, pos = base_order, base_daily, 0.60, 0.80
    daily = max(po * 1.2, daily)
    return {"per_order": float(po), "daily": float(daily), "symbol_daily": float(max(po, daily * sym)),
            "position": float(max(po, daily * pos)), "step_up": None, "band_pct": 2.5}


def _build_book(symbols: list[str], cfg: SimConfig, arm: str) -> tuple[EnvelopeBook, dict[str, dict], dict[str, object]]:
    nenv = cfg.effective_envelopes()
    each = int(math.ceil(cfg.agents / nenv))
    variant = arm if arm in ("frontier_tight", "frontier_loose", "frontier_open") else "balanced"
    limits = _caps_for(each, cfg, variant)
    if arm == "unguarded":
        limits = {"per_order": 1e15, "daily": 1e16, "symbol_daily": None, "position": None, "step_up": None, "band_pct": 999.0}
    portfolio = arm in ("gate_portfolio", "full", "frontier_tight", "frontier_loose", "frontier_open")
    key = owner_key_from_seed(f"og-sim-owner-{cfg.seed}")
    book = EnvelopeBook(key.public_key())
    specs: dict[str, dict] = {}
    envelope_by_index: dict[str, object] = {}
    for i in range(nenv):
        # Limits vary by one part per million so each envelope has a distinct
        # signed mandate id while remaining operationally equivalent.
        daily = limits["daily"] * (1.0 + (i + 1) * 1e-6)
        sym_daily = limits["symbol_daily"]
        position = limits["position"]
        env = make_envelope(key, name=f"desk-{i:04d}", owner="simulation", purpose="simulated signed desk mandate",
                            symbols=symbols, per_order=limits["per_order"], daily=daily, band_pct=limits["band_pct"],
                            step_up=limits["step_up"], max_symbol_daily=sym_daily if portfolio else None,
                            max_position=position if portfolio else None)
        book.add(env)
        specs[env.name] = {"per_order": limits["per_order"], "daily": daily, "step_up": limits["step_up"],
                           "band_pct": limits["band_pct"], "max_symbol_daily": sym_daily if portfolio else None,
                           "max_position": position if portfolio else None}
        envelope_by_index[str(i)] = env
    return book, specs, envelope_by_index


def _news(scenario: Scenario, step: int) -> list[dict]:
    if step != scenario.headline_step:
        return []
    if scenario.kind == "fake_headline":
        return [{"src": "RumourMill", "type": "headline", "ticker": scenario.target_symbol,
                 "text": f"Unverified report: {scenario.target_symbol} faces a sudden corporate event", "origin": "RumourMill",
                 "news_id": scenario.news_id, "pct": 12.0}]
    if scenario.kind == "real_crash":
        return [{"src": wire, "type": "headline", "ticker": scenario.target_symbol,
                 "text": f"{scenario.target_symbol} shares fall after a confirmed market shock", "origin": wire,
                 "news_id": scenario.news_id, "pct": -8.0} for wire in ("WireOne", "WireTwo", "WireThree")]
    return []


def _snapshot(market: ImpactMarket, scenario: Scenario, step: int, steps_per_day: int) -> Snapshot:
    quotes = {}
    for j, sym in enumerate(market.symbols):
        p = float(market.mid[j])
        c = market.quote(sym, lag=scenario.stale_lag) if scenario.kind == "stale_feed" and sym == scenario.target_symbol else p
        quotes[sym] = {"VenueA": p, "VenueB": p, "VenueC": c}
    day, sid = divmod(step, steps_per_day)
    news = _news(scenario, step)
    return Snapshot(step, day, f"2026-01-{5 + day:02d}T00:{sid % 60:02d}:00Z", quotes, news, {})


def _round_money(x: float) -> float:
    return round(float(x), 2)


def _iter_log(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def audit_order_log(events: Iterable[dict], envelope_specs: dict[str, dict]) -> dict:
    """Independent replay of mandate caps from the raw decision log.

    The auditor does not call Authority, Envelope, or the simulator's reserve
    methods. It rebuilds per-order, daily, per-symbol, order-count, and net
    position state from the recorded authority decisions.
    """
    daily: dict[tuple[str, int], int] = {}
    by_symbol: dict[tuple[str, int, str], int] = {}
    net: dict[tuple[str, str], int] = {}
    held: dict[tuple[str, str], dict[str, int]] = {}
    breaches: list[dict] = []
    checked = 0
    for ev in events:
        checked += 1
        if ev.get("replay"):
            continue
        final = ev.get("decision")
        auth = ev.get("authority_decision")
        if final == "allow" and auth != "allow":
            breaches.append({"i": ev.get("i"), "reason": "executed without an authority allow"})
        spec = envelope_specs.get(ev.get("envelope"))
        if not spec:
            if final == "allow":
                breaches.append({"i": ev.get("i"), "reason": "executed order has no signed envelope"})
            continue
        reserve = auth == "allow" or (auth == "hold" and ev.get("authority_layer") == "L5")
        if not reserve:
            continue
        order = ev["order"]
        sym, side = str(order["ticker"]).upper(), str(order["side"]).lower()
        qty, tp = int(order["quantity"]), float(ev["tp"])
        cents = notional_cents(qty, tp)
        env, day = ev["envelope"], int(ev["step"]) // int(ev.get("steps_per_day", 1))
        dkey, skey, pkey = (env, day), (env, day, sym), (env, sym)
        used = daily.get(dkey, 0)
        sym_used = by_symbol.get(skey, 0)
        if cents > usd_cents(spec["per_order"]):
            breaches.append({"i": ev.get("i"), "reason": "per-order cap exceeded"})
        if used + cents > usd_cents(spec["daily"]):
            breaches.append({"i": ev.get("i"), "reason": "daily cap exceeded"})
        if spec.get("max_symbol_daily") is not None and sym_used + cents > usd_cents(spec["max_symbol_daily"]):
            breaches.append({"i": ev.get("i"), "reason": "per-symbol daily cap exceeded"})
        side_qty = qty if side == "buy" else -qty
        if spec.get("max_position") is not None:
            old = net.get(pkey, 0)
            h = held.get(pkey, {"buy": 0, "sell": 0})
            exposure = max(abs(old + h["buy"] + side_qty), abs(old - h["sell"] + side_qty))
            if notional_cents(exposure, tp) > usd_cents(spec["max_position"]):
                breaches.append({"i": ev.get("i"), "reason": "position cap exceeded"})
        daily[dkey] = used + cents
        by_symbol[skey] = sym_used + cents
        if auth == "allow":
            net[pkey] = net.get(pkey, 0) + side_qty
        elif ev.get("authority_layer") == "L5":
            held.setdefault(pkey, {"buy": 0, "sell": 0})[side] += qty
    return {"valid": not breaches, "orders_checked": checked, "cap_breaches": len(breaches), "breaches": breaches[:20]}


def run_arm(cfg: SimConfig, scenario: Scenario, arm: str, *, log_path: str | Path | None = None) -> dict:
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}")
    wall0 = time.perf_counter()
    symbols = list(DEFAULT_SYMBOLS)
    nenv = cfg.effective_envelopes()
    book, specs, env_by_index = _build_book(symbols, cfg, arm)
    auth = Authority(book, steps_per_day=cfg.day_steps(), routing="pinned")
    scorer = None
    if arm in ("full", "frontier_tight", "frontier_loose", "frontier_open"):
        scorer = RiskScorer.load(cfg.risk_model)
        scorer.set_envelopes(specs, steps_per_day=cfg.day_steps())
    step_seconds = 6.5 * 3600 / cfg.day_steps()
    market = ImpactMarket.from_recording(symbols, cfg.seed, DEFAULT_RECORDING, simulation_step_seconds=step_seconds,
                                         impact_eta=cfg.impact_eta, impact_decay=cfg.impact_decay)
    pop = VectorPopulation(cfg.agents, symbols, nenv, cfg.seed, activity=cfg.activity)
    population_cap = 25_000.0 if arm == "unguarded" else float(specs["desk-0000"]["per_order"])
    counts = {"proposals": 0, "fills": 0, "allow": 0, "hold": 0, "refuse": 0, "risk_hold": 0, "risk_refuse": 0,
              "honest_proposals": 0, "honest_fills": 0, "honest_notional_usd": 0.0, "honest_filled_usd": 0.0,
              "bad_notional_usd": 0.0, "bad_filled_usd": 0.0, "bad_dollars_executed": 0.0,
              "slippage_usd": 0.0, "honest_slippage_usd": 0.0, "bad_slippage_usd": 0.0}
    by_label: dict[str, dict] = {}
    net_flow = np.zeros(len(symbols), dtype=np.float64)
    gross_flow = np.zeros(len(symbols), dtype=np.float64)
    total_pos = np.zeros(len(symbols), dtype=np.float64)
    total_cash = 0.0
    equity_peak = 0.0
    portfolio_dd_usd = 0.0
    index_peak = 1.0
    index_dd = 0.0
    shock_base = None
    spread_by_step: list[int] = []
    peak_spread = 0
    events: list[dict] = []
    digest = hashlib.sha256()
    log_file = None
    if log_path is not None:
        pth = Path(log_path)
        pth.parent.mkdir(parents=True, exist_ok=True)
        log_file = gzip.open(pth, "wt", encoding="utf-8")
    steps_per_day = cfg.day_steps()
    try:
        for step in range(cfg.steps):
            snap = _snapshot(market, scenario, step, steps_per_day)
            auth.on_snapshot(snap)
            if step == scenario.shock_step:
                shock_base = market.mid.copy()
            batch = pop.propose(market, step, scenario, per_order_cap=population_cap)
            net_flow.fill(0.0)
            gross_flow.fill(0.0)
            for j in range(len(batch)):
                counts["proposals"] += 1
                aid, si = int(batch.agent[j]), int(batch.symbol[j])
                sym, side = symbols[si], "buy" if int(batch.side[j]) > 0 else "sell"
                qty, limit = int(batch.quantity[j]), float(batch.limit_price[j])
                env = env_by_index[str(int(batch.envelope[j]))]
                order = {"ticker": sym, "side": side, "quantity": qty, "limit_price": round(limit, 4)}
                trigger = batch.trigger[j]
                if arm == "unguarded":
                    trigger = None                         # L7 is deliberately absent in the counterfactual arm.
                dec = auth.authorize(order, key=str(batch.key[j]), envelope=env, trigger=trigger, step=step, agent=aid)
                auth_decision, auth_layer = dec.decision, dec.layer
                tp = float(auth.prices.get(sym, market.mid[si]))
                notional = notional_cents(qty, tp) / 100.0
                final_decision = auth_decision
                risk_result = None
                risk_event = None
                if scorer is not None and auth_decision == "allow" and not dec.replay:
                    risk_event = {"step": step, "agent": aid, "env": env.name, "ticker": sym, "side": side, "qty": qty, "limit": limit,
                                  "tp": tp, "notional": notional, "key": str(batch.key[j]), "trig": None if trigger is None else True, "listed": True}
                    risk_result = scorer.score(risk_event)
                    final_decision = tighten(auth_decision, risk_result)
                    scorer.observe(risk_event)
                    if final_decision == "hold":
                        counts["risk_hold"] += 1
                    elif final_decision == "refuse":
                        counts["risk_refuse"] += 1
                counts[final_decision] += 1
                label = str(batch.label[j])
                bl = by_label.setdefault(label, {"proposals": 0, "allowed": 0, "held": 0, "refused": 0,
                                                  "notional_usd": 0.0, "filled_usd": 0.0, "fills": 0})
                bl["proposals"] += 1
                bl["notional_usd"] += notional
                bl[{"allow": "allowed", "hold": "held", "refuse": "refused"}[final_decision]] += 1
                if label == "legit":
                    counts["honest_proposals"] += 1
                    counts["honest_notional_usd"] += notional
                else:
                    counts["bad_notional_usd"] += notional
                fill_price = None
                executed = final_decision == "allow" and not dec.replay
                if executed:
                    gross_flow[si] += notional
                    net_flow[si] += int(batch.side[j]) * notional
                    slip = market.slippage_fraction(sym, gross_flow[si])
                    fill_price = tp * math.exp(int(batch.side[j]) * slip)
                    impact_cost = abs(fill_price - tp) * qty
                    pop.on_fill(aid, si, int(batch.side[j]), qty, fill_price)
                    total_pos[si] += int(batch.side[j]) * qty
                    total_cash -= int(batch.side[j]) * qty * fill_price
                    counts["fills"] += 1
                    bl["fills"] += 1
                    bl["filled_usd"] += notional
                    counts["slippage_usd"] += impact_cost
                    if label == "legit":
                        counts["honest_fills"] += 1
                        counts["honest_filled_usd"] += notional
                        counts["honest_slippage_usd"] += impact_cost
                    else:
                        counts["bad_filled_usd"] += notional
                        counts["bad_dollars_executed"] += notional
                        counts["bad_slippage_usd"] += impact_cost
                event = {"i": counts["proposals"], "step": step, "steps_per_day": steps_per_day, "agent": aid, "envelope": env.name,
                         "label": label, "order": order, "key": str(batch.key[j]), "tp": tp, "notional": notional,
                         "authority_decision": auth_decision, "authority_layer": auth_layer, "decision": final_decision,
                         "risk": None if risk_result is None else risk_result["risk"],
                         "risk_action": None if risk_result is None else risk_result["action"], "replay": bool(dec.replay),
                         "executed": bool(executed), "fill_price": fill_price}
                if trigger is not None:
                    event["trigger"] = trigger
                line = json.dumps(event, sort_keys=True, separators=(",", ":"))
                digest.update(line.encode("utf-8"))
                if log_file:
                    log_file.write(line + "\n")
                else:
                    events.append(event)
            market.step(net_flow, scenario.exogenous_log_return(step))
            index_value = float(np.mean(market.mid / market.initial_prices))
            index_peak = max(index_peak, index_value)
            index_dd = max(index_dd, 1.0 - index_value / index_peak)
            equity = total_cash + float(np.dot(total_pos, market.mid))
            equity_peak = max(equity_peak, equity)
            portfolio_dd_usd = max(portfolio_dd_usd, equity_peak - equity)
            if shock_base is not None and step >= scenario.shock_step:
                elapsed = max(1, step - scenario.shock_step + 1)
                direction = -1 if scenario.kind == "real_crash" else scenario.headline_side
                move = direction * np.log(market.mid / shock_base)
                threshold = 2.0 * market.sigma * np.sqrt(elapsed)
                si_target = market.index.get(scenario.target_symbol, -1)
                if si_target >= 0:
                    move[si_target] = 0.0
                spread = int(np.count_nonzero(move > threshold))
                spread_by_step.append(spread)
                peak_spread = max(peak_spread, spread)
    finally:
        if log_file:
            log_file.close()

    if log_path is not None:
        audit = audit_order_log(_iter_log(Path(log_path)), specs)
    else:
        audit = audit_order_log(events, specs)
    final_value = market.mid.copy()
    agent_pnl = pop.cash + pop.position @ final_value
    honest_pnl = float(agent_pnl[pop.honest_mask].sum())
    honest_loss = max(0.0, -honest_pnl)
    half_life = None
    if peak_spread > 0:
        peak_at = spread_by_step.index(peak_spread)
        threshold_half = peak_spread / 2.0
        half_life = next((i - peak_at for i in range(peak_at + 1, len(spread_by_step)) if spread_by_step[i] <= threshold_half), None)
    wall = max(time.perf_counter() - wall0, 1e-9)
    totals = {k: round(v, 5) if isinstance(v, float) else int(v) for k, v in counts.items()}
    totals.update({"honest_loss_usd": _round_money(honest_loss), "honest_net_pnl_usd": _round_money(honest_pnl),
                   "peak_drawdown_pct": round(index_dd, 7), "peak_drawdown_usd": _round_money(portfolio_dd_usd),
                   "spread_symbols_over_2sigma": peak_spread, "contagion_half_life_steps": half_life,
                   "wall_s": round(wall, 6), "orders_per_s": round(counts["proposals"] / wall, 1),
                   "agents_per_s": round(cfg.agents / wall, 1), "agent_steps_per_s": round(cfg.agents * cfg.steps / wall, 1),
                   "agents": cfg.agents, "steps": cfg.steps,
                   "envelopes": nenv, "digest": digest.hexdigest()[:32], "audit": audit,
                   "caps": specs["desk-0000"]})
    totals["by_label"] = {k: {kk: (_round_money(vv) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in by_label.items()}
    totals["authority_decisions"] = dict(auth.counts)
    totals["authority_refusals_by_code"] = dict(auth.codes)
    totals["log_path"] = f"logs/{Path(log_path).name}" if log_path else None
    return totals


def _mean(vals: list[float]) -> float:
    return float(np.mean(vals)) if vals else 0.0


def _pareto(points: list[dict]) -> list[dict]:
    ordered = sorted(points, key=lambda p: (-p["honest_throughput_usd"], p["worst_case_loss_usd"]))
    result, best_loss = [], float("inf")
    for p in ordered:
        if p["worst_case_loss_usd"] < best_loss:
            result.append(p)
            best_loss = p["worst_case_loss_usd"]
    return sorted(result, key=lambda p: p["worst_case_loss_usd"])


def _arm_job(job: tuple) -> tuple[int, str, dict]:
    """Top-level so a process pool can run one (seed, arm) pair; arms never share state."""
    cfg_dict, scenario_name, seed, arm, path = job
    cfg = SimConfig(**cfg_dict)
    scenario = build_scenario(scenario_name, cfg.steps, attack_activity=cfg.attack_activity, seed=seed)
    return seed, arm, run_arm(cfg, scenario, arm, log_path=path)


def run_scenario(cfg: SimConfig, scenario_name: str, *, log_dir: str | Path | None = None, workers: int = 1) -> dict:
    """Run paired seeds through four guard arms plus three cap-sizing candidates.

    Every (seed, arm) pair is an independent process-safe job with its own authority, so ``workers`` changes only
    wall time: decisions, digests and audits are identical for any worker count.
    """
    wall0 = time.perf_counter()
    jobs = []
    for rep in range(cfg.replicates):
        seed = cfg.seed + rep
        for arm in ARMS:
            path = None
            if log_dir is not None:
                path = str(Path(log_dir) / f"{scenario_name}-k{cfg.agents}-s{seed}-{arm}.jsonl.gz")
            jobs.append((asdict(cfg) | {"seed": seed, "replicates": 1}, scenario_name, seed, arm, path))
    done: dict[tuple[int, str], dict] = {}
    if workers > 1 and len(jobs) > 1:
        import os
        from concurrent.futures import ProcessPoolExecutor
        # One BLAS thread per worker: the jobs are the parallelism, and oversubscribed threads slow the risk scorer badly.
        for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
            os.environ.setdefault(var, "1")
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            for seed, arm, row in pool.map(_arm_job, jobs):
                done[(seed, arm)] = row
    else:
        for job in jobs:
            seed, arm, row = _arm_job(job)
            done[(seed, arm)] = row
    all_runs: list[dict] = []
    for rep in range(cfg.replicates):
        seed = cfg.seed + rep
        run_rows = {arm: done[(seed, arm)] for arm in ARMS}
        base_fills = run_rows["unguarded"]["honest_fills"]
        for row in run_rows.values():
            row["honest_fills_lost_vs_unguarded"] = max(0, base_fills - row["honest_fills"])
            row["honest_fills_lost_pct_vs_unguarded"] = round(max(0, base_fills - row["honest_fills"]) / max(base_fills, 1), 6)
        all_runs.append({"seed": seed, "arms": run_rows})
    total_orders = sum(int(r["proposals"]) for run in all_runs for r in run["arms"].values())
    wall = max(time.perf_counter() - wall0, 1e-9)
    scale = {"agents": cfg.agents, "steps": cfg.steps, "seeds": cfg.replicates, "arms": len(ARMS), "workers": int(max(1, workers)),
             "orders_per_arm_mean": round(total_orders / max(1, cfg.replicates * len(ARMS)), 1),
             "orders_total": total_orders, "wall_s": round(wall, 2), "aggregate_decisions_per_s": round(total_orders / wall, 1)}

    arms_summary = {}
    metric_keys = ("proposals", "fills", "allow", "hold", "refuse", "honest_proposals", "honest_fills", "honest_filled_usd",
                   "honest_fills_lost_vs_unguarded", "honest_fills_lost_pct_vs_unguarded", "bad_dollars_executed", "bad_filled_usd",
                   "honest_loss_usd", "peak_drawdown_pct", "peak_drawdown_usd", "spread_symbols_over_2sigma", "contagion_half_life_steps",
                   "orders_per_s", "agents_per_s", "agent_steps_per_s", "slippage_usd")
    for arm in ARMS:
        rows = [r["arms"][arm] for r in all_runs]
        avg = {}
        for k in metric_keys:
            present = [float(x[k]) for x in rows if isinstance(x.get(k), (int, float))]
            avg[k] = round(_mean(present), 5) if present else None
        avg["worst_case_loss_usd"] = max((float(x["peak_drawdown_usd"]) for x in rows), default=0.0)
        avg["auditor_breaches"] = sum(int(x["audit"]["cap_breaches"]) for x in rows)
        avg["auditor_valid"] = all(x["audit"]["valid"] for x in rows)
        avg["orders_audited"] = sum(int(x["audit"]["orders_checked"]) for x in rows)
        arms_summary[arm] = avg
    candidates = []
    for arm in ARMS:
        m = arms_summary[arm]
        actual_caps = all_runs[0]["arms"][arm]["caps"] if all_runs else {}
        candidates.append({"arm": arm, "honest_throughput_usd": round(m["honest_filled_usd"], 2),
                           "worst_case_loss_usd": round(m["worst_case_loss_usd"], 2),
                           "bad_dollars_executed_usd": round(m["bad_dollars_executed"], 2),
                           "honest_fills_lost_pct": round(m["honest_fills_lost_pct_vs_unguarded"], 6),
                           "caps": actual_caps})
    safe_cfg = asdict(cfg)
    if safe_cfg["risk_model"]:
        safe_cfg["risk_model"] = Path(safe_cfg["risk_model"]).name
    return {"schema": "orderguard-impact-sim/1", "scale": scale, "scenario": build_scenario(scenario_name, cfg.steps, attack_activity=cfg.attack_activity, seed=cfg.seed).as_dict(),
            "config": safe_cfg | {"effective_envelopes": cfg.effective_envelopes(), "steps_per_day_effective": cfg.day_steps()},
            "arms": arms_summary, "runs": all_runs, "frontier": _pareto(candidates), "frontier_candidates": candidates,
            "method": {"authority": "Every emitted order receives one individual orderguard_arena.authority.Authority decision.",
                       "risk": "The shipped orderguard_risk RiskScorer scores gate-allowed orders in full; tighten() can only make them stricter.",
                       "aggregation": "Only authorized signed dollar flow is netted by symbol for the market step. Per-order eligibility and budget/portfolio reservations are never aggregated.",
                       "order_activity": "Population state is vectorized; only sparse active orders are materialized. Activity probability is recorded in config.",
                       "impact": "Square-root temporary impact with exponential decay; no order book, latency queue, or execution venue simulation."}}

