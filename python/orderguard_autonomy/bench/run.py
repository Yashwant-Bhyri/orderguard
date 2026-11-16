"""Run the four-system benchmark (plus the C+ and D_auth variants) over the eight scenarios and write results/vision/.

    PYTHONPATH=python python -m orderguard_autonomy.bench --seeds 20            # full run (results/vision/benchmark.json and .md)
    PYTHONPATH=python python -m orderguard_autonomy.bench --seeds 2 --scenarios delayed_acks --systems C,D --out /tmp/x

Every run is seeded and deterministic apart from the latency figures.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from ..risk import es_factor, var_factor, backtest_var_es
from .audit import audit, measures, limits
from .scenarios import SCENARIOS
from .systems import SYSTEMS, make_system
from .world import STUDENT_DF, SYMBOLS, World

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results" / "vision"


class Run:
    def __init__(self, scenario, system, world):
        self.scenario, self.system, self.world = scenario, system, world
        self.cfg = scenario.cfg
        self.steps = scenario.steps
        self.decisions: list[dict] = []
        self.fills: list[dict] = []
        self._pos: list[dict] = []
        self._marks: list[dict] = []
        self.true_es: list[float] = []
        self.backtest: dict[str, list] = {"loss": [], "var": [], "es": []}

    def positions_at(self, t: int) -> dict:
        return self._pos[min(t, len(self._pos) - 1)]

    def marks_at(self, t: int) -> dict:
        return self._marks[min(t, len(self._marks) - 1)]


def _true_label(p, world, cfg) -> tuple[str, str]:
    """Ground truth for hard limits: would this order take the account's TRUE exposure (broker positions + orders resting at a venue
    + this order) past a signed limit, making that measure worse? Measured with the same arithmetic as the auditor."""
    if p.label == "harmful":
        return p.label, p.harm_kind
    marks = world.marks()
    pos = {s: float(q) for s, q in world.broker.positions.items()}
    for o in world.broker.orders.values():
        if o.arrived and o.status == "new" and o.p.side == p.side:
            pos[o.p.symbol] = pos.get(o.p.symbol, 0.0) + (1 if o.p.side == "buy" else -1) * o.p.qty
    before = measures(pos, marks)
    pos[p.symbol] = pos.get(p.symbol, 0.0) + (1 if p.side == "buy" else -1) * p.qty
    after = measures(pos, marks)
    lim = limits(cfg)
    if any(after[k] > lim[k] + 1e-6 and after[k] > before[k] + 1e-6 for k in after):
        return "harmful", "hard_limit"
    # The risk budget is signed too. Its truth is the simulator's actual covariance (regime included), whatever any model estimates.
    if p.side == "buy":
        es0 = world.true_daily_es({s: q * marks[s] for s, q in pos.items() if s != p.symbol} | {p.symbol: (pos[p.symbol] - p.qty) * marks[p.symbol]})
        es1 = world.true_daily_es({s: q * marks[s] for s, q in pos.items()})
        if es1 > cfg.risk_budget and es1 > es0:
            return "harmful", "over_risk_budget"
    return "legit", p.harm_kind


def run_one(scenario_name: str, system_name: str, seed: int, overrides: dict | None = None) -> dict:
    scn = SCENARIOS[scenario_name](seed)
    for k, v in (overrides or {}).items():
        setattr(scn.cfg, k, v)
    world = World(seed, scn.steps, scn.steps_per_day, delay_fn=scn.delay)
    system = make_system(system_name, scn.cfg, world, scn)
    run = Run(scn, system, world)
    props_of: dict[str, object] = {}
    n = 0
    fill_seq = 0
    model = getattr(system, "model", None)
    for step in range(scn.steps):
        world.step = step
        marks = world.marks()
        system.on_marks(step, marks)
        for r in world.broker.deliver(step):
            p = world.broker.orders[r.oid].p
            system.on_report(r)
            scn.on_report(r, p)
        if step and step % scn.cfg.reconcile_every == 0:
            orders, pos = world.broker.snapshot()
            system.reconcile(orders, pos, step)
        for p in scn.propose(step, world):
            label, kind = _true_label(p, world, scn.cfg)
            p.label, p.harm_kind = label, kind
            n += 1
            oid = f"o{n}"
            d, why = system.submit(oid, p, step)
            notional = p.qty * marks[p.symbol]
            p.mark_notional = notional / p.qty                 # completion is measured at the trusted price, not the fill price
            run.decisions.append({"step": step, "agent": p.agent, "symbol": p.symbol, "side": p.side, "notional": notional,
                                  "label": label, "harm_kind": kind, "decision": d, "why": list(why)[:3]})
            scn.on_decision(p, d, step)
            if d == "allow":
                props_of[oid] = p
                world.broker.send(oid, p, step)
                system.on_sent(oid, p, step)
        flow = np.zeros(len(SYMBOLS))
        w_before = np.array([world.broker.positions.get(s, 0) * marks[s] for s in SYMBOLS])
        for o in world.broker.process(step, world.market, flow):
            fill_seq += 1
            run.fills.append({"seq": fill_seq, "step": step, "agent": o.p.agent, "symbol": o.p.symbol, "side": o.p.side, "qty": o.filled,
                              "price": o.price, "notional": o.filled * o.price, "mark_notional": o.filled * o.p.mark_notional,
                              "label": o.p.label, "harm_kind": o.p.harm_kind,
                              "intent_id": o.p.intent_id})
        if model is not None and scenario_name == "volatility_regime_change":
            w = {s: world.broker.positions.get(s, 0) * marks[s] for s in SYMBOLS}
            vec = np.array([w[s] for s in SYMBOLS])
            stressed = bool(system.regime.stressed)
            cov = model.covariance(SYMBOLS, stressed=stressed) / model.horizon_steps
            sig = math.sqrt(max(float(vec @ cov @ vec), 0.0))
            run.backtest["var"].append(var_factor(0.975, STUDENT_DF) * sig)
            run.backtest["es"].append(es_factor(0.975, STUDENT_DF) * sig)
        world.market.step(flow, scn.exogenous(step, world))
        if model is not None and scenario_name == "volatility_regime_change":
            ret = np.expm1(world.market.returns[-1])
            run.backtest["loss"].append(-float(vec @ ret))
        system.end_step(step)
        run._pos.append({s: float(q) for s, q in world.broker.positions.items()})
        run._marks.append(marks)
        run.true_es.append(world.true_daily_es({s: world.broker.positions.get(s, 0) * marks[s] for s in SYMBOLS}))
    return summarize(run, scenario_name, system_name, seed)


def _usd(rows, **cond):
    return float(sum(r["notional"] for r in rows if all(r.get(k) == v for k, v in cond.items())))


def summarize(run: Run, scenario_name: str, system_name: str, seed: int) -> dict:
    dec, fills = run.decisions, run.fills
    legit = [d for d in dec if d["label"] == "legit"]
    harmful = [d for d in dec if d["label"] == "harmful"]
    lat = np.asarray(run.system.latency_us) if run.system.latency_us else np.zeros(1)
    out = {
        "scenario": scenario_name, "system": system_name, "seed": seed, "steps": run.steps,
        "proposals": len(dec), "legit_proposals": len(legit), "harmful_proposals": len(harmful),
        "legit_proposed_usd": _usd(legit), "legit_executed_usd": float(sum(f["mark_notional"] for f in fills if f["label"] == "legit")),
        "harmful_proposed_usd": _usd(harmful), "harmful_executed_usd": float(sum(f["mark_notional"] for f in fills if f["label"] == "harmful")),
        "legit_held": sum(1 for d in legit if d["decision"] == "hold"), "legit_refused": sum(1 for d in legit if d["decision"] == "refuse"),
        "harmful_allowed": sum(1 for d in harmful if d["decision"] == "allow"),
        "holds": sum(1 for d in dec if d["decision"] == "hold"), "refusals": sum(1 for d in dec if d["decision"] == "refuse"),
        "peak_true_es_usd": float(max(run.true_es)) if run.true_es else 0.0,
        "latency_p50_us": float(np.percentile(lat, 50)), "latency_p99_us": float(np.percentile(lat, 99)),
    }
    out["legit_completion"] = out["legit_executed_usd"] / out["legit_proposed_usd"] if out["legit_proposed_usd"] else None
    out["harmful_blocked_share"] = 1 - out["harmful_executed_usd"] / out["harmful_proposed_usd"] if out["harmful_proposed_usd"] else None
    out.update(audit(fills, run._marks, run.cfg))
    out["harm"] = run.scenario.harm(run)
    if hasattr(run.system, "receipts"):
        out["certificates"] = {"verified_allow": run.system.receipts["allow"], "verified_refuse": run.system.receipts["refuse"],
                               "mean_bytes": float(np.mean(run.system.cert_bytes)) if run.system.cert_bytes else None}
        out["escrow_invariants_ok"] = run.system.root.check_invariants() == []
    if run.backtest["loss"]:
        bt = backtest_var_es(run.backtest["loss"], run.backtest["var"], run.backtest["es"])
        out["es_backtest"] = bt
    return out


# ---------------------------------------------------------------------------------------------------------------------

def _agg(vals: list) -> dict | None:
    v = [x for x in vals if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not v:
        return None
    a = np.asarray(v, dtype=float)
    half = 1.96 * a.std(ddof=1) / math.sqrt(len(a)) if len(a) > 1 else 0.0
    return {"mean": float(a.mean()), "ci95": float(half), "n": len(a), "min": float(a.min()), "max": float(a.max())}


def aggregate(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r["scenario"], {}).setdefault(r["system"], []).append(r)
    agg: dict = {}
    for scn, by in out.items():
        agg[scn] = {}
        for sysname, rs in by.items():
            keys = [k for k, v in rs[0].items() if isinstance(v, (int, float)) and k not in ("seed", "steps")]
            a = {k: _agg([r.get(k) for r in rs]) for k in keys}
            a["harm"] = {k: _agg([r["harm"].get(k) for r in rs]) for k in rs[0]["harm"]}
            if "drift_alarm_after_onset_steps" in rs[0]["harm"]:
                a["harm"]["detection_rate"] = sum(1 for r in rs if r["harm"]["drift_alarm_after_onset_steps"] is not None) / len(rs)
            if "es_backtest" in rs[0]:
                a["es_backtest"] = {k: _agg([r["es_backtest"][k] for r in rs]) for k in ("exceptions", "expected_exceptions", "kupiec_p",
                                                                                      "acerbi_szekely_z2")}
            if "certificates" in rs[0]:
                a["certificates_refused_by_receiver"] = sum(r["certificates"]["verified_refuse"] for r in rs)
                a["certificate_mean_bytes"] = _agg([r["certificates"]["mean_bytes"] for r in rs])
                a["escrow_invariants_ok"] = all(r["escrow_invariants_ok"] for r in rs)
            agg[scn][sysname] = a
    return agg


HEADLINE = {
    "correlated_buying": ("herd_exposure_usd", "exposure the herd built before the shock ($)"),
    "objective_drift": ("off_objective_executed_usd", "off-objective buying after drift began ($)"),
    "coordinated_misinformation": ("rumour_notional_executed_usd", "bought on the false rumour ($)"),
    "delayed_acks": ("duplicate_fill_notional_usd", "duplicate fills ($)"),
    "volatility_regime_change": ("over_budget_executed_usd", "risk added while true ES was over the signed budget ($)"),
    "budget_starvation": ("slow_completion", "slow agents' completion (share)"),
    "cross_venue": ("nvda_over_cap_usd", "NVDA exposure over the cap ($)"),
    "tool_compromise": ("compromised_notional_executed_usd", "compromised orders executed ($)"),
}
HIGHER_IS_BETTER = {"budget_starvation"}


def verdicts(agg: dict) -> dict:
    """For each scenario: does D do better than C, and than C+, on the scenario's own harm measure, with non-overlapping 95% CIs?"""
    out = {}
    for scn, (key, label) in HEADLINE.items():
        if scn not in agg:
            continue
        row = {"measure": label}
        g = lambda s: (agg[scn].get(s) or {}).get("harm", {}).get(key)
        better = (lambda a, b: a > b) if scn in HIGHER_IS_BETTER else (lambda a, b: a < b)
        for base in ("C", "C+"):
            d, c = g("D"), g(base)
            if not d or not c:
                continue
            sep = (d["mean"] + d["ci95"] < c["mean"] - c["ci95"]) if scn not in HIGHER_IS_BETTER else (d["mean"] - d["ci95"] > c["mean"] + c["ci95"])
            row[f"D_vs_{base}"] = {"D": d["mean"], base: c["mean"], "D_better": better(d["mean"], c["mean"]), "separated_95ci": bool(sep)}
        lc, ld = agg[scn].get("C", {}).get("legit_completion"), agg[scn].get("D", {}).get("legit_completion")
        if lc and ld:
            row["legit_completion"] = {"C": lc["mean"], "D": ld["mean"]}
        out[scn] = row
    return out


def _fmt(x, money=True):
    if x is None:
        return "n/a"
    m = x["mean"] if isinstance(x, dict) else x
    if money:
        return f"{m:,.0f}" if abs(m) >= 1 or m == 0 else f"{m:.3f}"
    return f"{m:.2f}"


def _m(x) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, (int, float)):
        return f"{x:.2f}"
    v = x["mean"]
    return f"{v:,.0f}" if abs(v) >= 10 else f"{v:.2f}"


def markdown(agg: dict, ver: dict, meta: dict) -> str:
    L = ["# Continuous autonomy control: benchmark results", "",
         f"Generated by `{meta['command']}`. Seeds: {meta['seeds']}. Scripted agents on the orderguard_sim impact market; paper only.",
         "Means over seeds; ± is a 95% confidence half-width. See docs/vision/BENCHMARK.md for the method and its limits.", ""]
    for scn, (key, label) in HEADLINE.items():
        if scn not in agg:
            continue
        S = SCENARIOS[scn]
        L += [f"## {S.title}", "", S.question, "",
              f"| System | {label} | Hard-limit breaches | Legit completion | Legit held | Legit refused | Harmful blocked | p50 µs |",
              "|---|---|---|---|---|---|---|---|"]
        for s in SYSTEMS:
            a = agg[scn].get(s)
            if not a:
                continue
            h = a["harm"].get(key)
            hs = "n/a" if h is None else (f"{h['mean']:.3f} ± {h['ci95']:.3f}" if key in ("slow_completion",) else f"{h['mean']:,.0f} ± {h['ci95']:,.0f}")
            lc = a.get("legit_completion")
            hb = a.get("harmful_blocked_share")
            L.append(f"| {s} | {hs} | {a['hard_limit_breaches']['mean']:.1f} | {'n/a' if not lc else f'{lc['mean']:.1%}'} | "
                     f"{a['legit_held']['mean']:.1f} | {a['legit_refused']['mean']:.1f} | {'n/a' if not hb else f'{max(0.0, hb['mean']):.1%}'} | "
                     f"{a['latency_p50_us']['mean']:.0f} |")
        others = [k for k in (agg[scn].get("D") or {}).get("harm", {}) if k != key]
        if others:
            L += ["", "Other measures (C / D): " + "; ".join(
                f"{k.replace('_', ' ')} {_m(agg[scn].get('C', {}).get('harm', {}).get(k))} / {_m(agg[scn]['D']['harm'].get(k))}" for k in others)]
        bt = (agg[scn].get("D") or {}).get("es_backtest")
        if bt:
            L += ["", f"D's own ES model, one-step backtest: {bt['exceptions']['mean']:.1f} VaR exceptions against {bt['expected_exceptions']['mean']:.2f} "
                      f"expected, Acerbi-Szekely Z2 {bt['acerbi_szekely_z2']['mean']:+.2f} (about 0 when ES is right)."]
        v = ver.get(scn, {})
        for base in ("C", "C+"):
            x = v.get(f"D_vs_{base}")
            if x:
                L.append("")
                L.append(f"D vs {base}: {'better' if x['D_better'] else 'not better'}"
                         f"{' (95% intervals separate)' if x['separated_95ci'] and x['D_better'] else ''}.")
        L.append("")
    return "\n".join(L) + "\n"


SENSITIVITY = {
    "correlated_buying": ("herding_cap_w", (0.05, 0.10, 0.15, 0.25, 0.40)),
    "objective_drift": ("drift_h", (3.0, 4.5, 6.0, 8.0, 10.0)),
}


def sensitivity(seeds: int, first: int, out: Path) -> dict:
    """D's two model-dependent knobs that carry its wins in herding and drift, swept on their own scenarios (C for reference)."""
    res: dict = {}
    for scn, (knob, values) in SENSITIVITY.items():
        key = HEADLINE[scn][0]
        rows = [run_one(scn, "C", s) for s in range(first, first + seeds)]
        res[scn] = {"knob": knob, "measure": HEADLINE[scn][1], "C": {"harm": _agg([r["harm"][key] for r in rows]),
                                                                      "legit_completion": _agg([r["legit_completion"] for r in rows])}, "D": []}
        for v in values:
            rows = [run_one(scn, "D", s, {knob: v}) for s in range(first, first + seeds)]
            entry = {knob: v, "harm": _agg([r["harm"][key] for r in rows]), "legit_completion": _agg([r["legit_completion"] for r in rows]),
                     "legit_held": _agg([r["legit_held"] for r in rows])}
            if scn == "objective_drift":
                entry["drift_false_alarms"] = _agg([r["harm"]["drift_false_alarms"] for r in rows])
                entry["drift_alarm_after_onset_steps"] = _agg([r["harm"]["drift_alarm_after_onset_steps"] for r in rows])
                entry["detection_rate"] = sum(1 for r in rows if r["harm"]["drift_alarm_after_onset_steps"] is not None) / len(rows)
            res[scn]["D"].append(entry)
            print(f"sensitivity {scn} {knob}={v}", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sensitivity.json").write_text(json.dumps({"command": f"PYTHONPATH=python python -m orderguard_autonomy.bench --sensitivity --seeds {seeds}",
                                                      "seeds": f"{first}..{first + seeds - 1}", "results": res}, indent=1, sort_keys=True))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m orderguard_autonomy.bench", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--first-seed", type=int, default=1)
    ap.add_argument("--scenarios", default="all")
    ap.add_argument("--systems", default=",".join(SYSTEMS))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--sensitivity", action="store_true", help="sweep D's herding cap and drift threshold instead of the main run")
    a = ap.parse_args(argv)
    if a.sensitivity:
        sensitivity(a.seeds, a.first_seed, Path(a.out))
        return 0
    scns = list(SCENARIOS) if a.scenarios == "all" else a.scenarios.split(",")
    syss = a.systems.split(",")
    rows = []
    t0 = time.time()
    for scn in scns:
        for s in syss:
            t1 = time.time()
            for seed in range(a.first_seed, a.first_seed + a.seeds):
                rows.append(run_one(scn, s, seed))
            print(f"{scn:28s} {s:7s} {time.time() - t1:6.1f}s", flush=True)
    agg = aggregate(rows)
    ver = verdicts(agg)
    cmd = "PYTHONPATH=python python -m orderguard_autonomy.bench --seeds {}".format(a.seeds) + \
          ("" if a.scenarios == "all" else f" --scenarios {a.scenarios}") + ("" if a.systems == ",".join(SYSTEMS) else f" --systems {a.systems}")
    meta = {"command": cmd, "seeds": f"{a.first_seed}..{a.first_seed + a.seeds - 1}", "wall_s": round(time.time() - t0, 1),
            "note": "latency figures depend on the machine; every other figure is deterministic for its seed"}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benchmark.json").write_text(json.dumps({"meta": meta, "verdicts": ver, "aggregate": agg}, indent=1, sort_keys=True))
    (out / "benchmark_runs.json").write_text(json.dumps(rows, indent=None, sort_keys=True, separators=(",", ":")))
    (out / "benchmark.md").write_text(markdown(agg, ver, meta))
    print(f"wrote {out}/benchmark.json, benchmark_runs.json, benchmark.md in {meta['wall_s']}s")
    return 0
