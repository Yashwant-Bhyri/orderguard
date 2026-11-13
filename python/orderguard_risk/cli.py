"""`og-risk` (or `python -m orderguard_risk`): build the corpus, train and export the shipped model, run the honest evaluation, and the
one-shot demo.

    og-risk build-data [--runs 48] [--stealth 8]     arena runs -> data/risk/corpus.npz (+ stealth.npz, adaptive colluders held out)
    og-risk train                                    fit on training seeds, calibrate on validation seeds -> data/models/order_risk.json
    og-risk eval                                     every protocol (held-out seeds, regime shift, time split, leave-one-family-out,
                                                     ablations, adaptive colluders, MLP) -> results/risk/eval.json
    og-risk demo-oneshot                             one analyst-labelled stealth order -> how much similar flow is held, at what cost
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "risk"


def _behavioural_cols():
    from . import features as F
    return [F.IX[n] for n in F.BEHAV]


def cmd_build_data(a) -> int:
    from . import dataset as D
    cols, metas = D.build(D.default_specs(a.runs), workers=0, progress=lambda *x: print(*x, file=sys.stderr))
    D.save(D.corpus_path(), cols, metas)
    print(f"wrote {D.corpus_path().relative_to(ROOT)}: {len(cols['run']):,} proposals from {len(metas)} runs")
    if a.stealth:
        cols, metas = D.build(D.stealth_specs(a.stealth), workers=0)
        D.save(D.DATA_DIR / "stealth.npz", cols, metas)
        print(f"wrote stealth.npz: {len(cols['run']):,} proposals from {len(metas)} adaptive-colluder runs")
    return 0


def _proto_params(d, cols, train_rows, rng) -> dict:
    """Standardisation for the one-shot memory and a bandwidth h calibrated so a typical attack prototype captures about 0.5% of honest
    gate-allowed orders (similarity >= tau)."""
    X = d.X[train_rows][:, cols].astype(np.float64)
    Z = np.sign(X) * np.log1p(np.abs(X))
    hon = d.y[train_rows] == 0
    mu, sd = Z[hon].mean(0), Z[hon].std(0) + 1e-6
    E = np.clip((Z - mu) / sd, -6, 6)
    H = E[hon][rng.choice(int(hon.sum()), size=min(20_000, int(hon.sum())), replace=False)]
    B = E[~hon][rng.choice(int((~hon).sum()), size=min(200, int((~hon).sum())), replace=False)]
    q = np.median([np.quantile(np.sqrt(((H - b) ** 2).sum(1)), 0.005) for b in B])
    tau = 0.5
    h = float(q / math.sqrt(2 * math.log(1 / tau)))
    return {"mu": [round(float(x), 6) for x in mu], "sd": [round(float(x), 6) for x in sd], "h": round(h, 6), "tau": tau}


def cmd_train(a) -> int:
    from . import evaluate as E
    from . import pipeline as P
    from . import dataset as D
    d = P.load_data()
    tr, va, te = P.seed_split(d)
    cols = _behavioural_cols()
    ft, X = P.fit(d, tr, va, use=cols, iters=a.iters, seed=0)
    rows = np.flatnonzero(te & d.pop)
    m = E.metrics(P.predict(ft, X, rows), d, rows, ft.t_hold, ft.t_refuse)
    ext = None
    try:
        ext = E.external(ft, P.load_data(D.DATA_DIR / "stealth.npz"))
    except FileNotFoundError:
        pass
    model = {"format": "orderguard-order-risk/1", "features": "behavioural (no rationale text)", "cols": cols,
             "feature_names": [P.F.NAMES[c] for c in cols], "trees": ft.ens.to_json(),
             "thresholds": {"hold": ft.t_hold, "refuse": ft.t_refuse, "calibrated_on": "validation seeds: hold flags 1% of honest allowed orders, refuse 0.05%"},
             "prototype": _proto_params(d, cols, np.flatnonzero(tr & d.pop), np.random.default_rng(0)),
             "training": {"rows": int((tr & d.pop).sum()), "runs": int(len(np.unique(d.run[tr]))), "corpus_rows": int(len(d.y))},
             "metrics_held_out_seeds": {k: m[k] for k in ("pr_auc", "usd_recall_hold_or_refuse", "honest_false_hold_rate", "hold_precision", "ece")},
             "metrics_adaptive_colluders": None if ext is None else {k: ext[k] for k in ("pr_auc", "usd_recall_hold_or_refuse", "honest_false_hold_rate")}}
    out = ROOT / "data" / "models" / "order_risk.json"
    blob = json.dumps(model, separators=(",", ":"), sort_keys=True)
    out.write_text(blob)
    (out.with_suffix(".sha256")).write_text(hashlib.sha256(blob.encode()).hexdigest() + "  order_risk.json\n")
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "shipped_model.json").write_text(json.dumps({"held_out_seeds": m, "adaptive_colluders": ext}, indent=1, sort_keys=True, default=float))
    print(f"wrote {out.relative_to(ROOT)} ({len(blob) / 1e6:.2f} MB, {len(ft.ens.trees)} trees, {len(cols)} behavioural features)")
    print("held-out seeds:", model["metrics_held_out_seeds"])
    if ext:
        print("adaptive colluders (never trained on):", model["metrics_adaptive_colluders"])
    return 0


def cmd_eval(a) -> int:
    from . import evaluate as E
    from . import pipeline as P
    if not a.with_text:
        E.DEFAULT_USE = _behavioural_cols()
    res = E.run_all(P.load_data())
    res["features"] = "all, including synthetic rationale text" if a.with_text else "behavioural (the shipped model's columns)"
    RESULTS.mkdir(parents=True, exist_ok=True)
    E.dump(RESULTS / "eval.json", res)
    print(f"wrote {(RESULTS / 'eval.json').relative_to(ROOT)}")
    return 0


def oneshot(model: dict, d, seed: int = 0) -> dict:
    """Score the adaptive-colluder runs with the shipped model; take ONE missed stealth order from one run as an analyst label; measure what
    the prototype catches in the OTHER runs (dollars of missed stealth flow) and what it costs (honest orders newly held)."""
    from .models import TreeEnsemble
    cols = model["cols"]
    ens = TreeEnsemble.from_json(model["trees"])
    pr = model["prototype"]
    mu, sd, h, tau = np.array(pr["mu"]), np.array(pr["sd"]), pr["h"], pr["tau"]
    rows = np.flatnonzero(d.pop)
    X = d.X[rows][:, cols].astype(np.float64)
    p = np.array([ens.prob(ens.raw(x)) for x in X])
    flagged = p >= model["thresholds"]["hold"]
    y, fam, run, usd = d.y[rows], d.fam[rows], d.run[rows], d.notional[rows]
    missed = np.flatnonzero((fam == "stealth") & ~flagged)
    if not len(missed):
        return {"note": "the model already holds every stealth order; nothing to demonstrate"}
    rng = np.random.default_rng(seed)
    pick = int(rng.choice(missed))
    other = run != run[pick]
    E = np.clip((np.sign(X) * np.log1p(np.abs(X)) - mu) / sd, -6, 6)
    dist = np.sqrt(((E - E[pick]) ** 2).sum(1))
    # Bandwidth chosen at labelling time from what the analyst can see: the orders of the label's own run that were seen BEFORE it and
    # not flagged (mostly honest). The prototype may capture at most `budget` of them. No labels from other runs are used.
    ref = (run == run[pick]) & (d.step[rows] <= d.step[rows][pick]) & ~flagged
    ref[pick] = False
    budget = 0.005
    q = float(np.quantile(dist[ref], budget)) if ref.sum() >= 50 else float(np.quantile(dist, budget))
    h = q / math.sqrt(2 * math.log(1 / tau))
    sim = np.exp(-dist ** 2 / (2 * h ** 2))
    caught = sim >= tau
    st = (fam == "stealth") & other
    hon = (y == 0) & other
    before = float(usd[st & flagged].sum() / usd[st].sum())
    after = float(usd[st & (flagged | caught)].sum() / usd[st].sum())
    return {"label": {"run": int(run[pick]), "notional_usd": round(float(usd[pick]), 2), "risk_before": round(float(p[pick]), 5),
                      "reference_orders": int(ref.sum()), "capture_budget": budget},
            "stealth_usd_recall_other_runs": {"before": round(before, 4), "after_one_label": round(after, 4)},
            "missed_stealth_usd_now_held": round(float(usd[st & ~flagged & caught].sum()), 2),
            "honest_newly_held": int((hon & ~flagged & caught).sum()), "honest_orders": int(hon.sum()),
            "honest_newly_held_rate": round(float((hon & ~flagged & caught).sum() / max(hon.sum(), 1)), 5)}


def cmd_demo_oneshot(a) -> int:
    from . import pipeline as P
    from . import dataset as D
    model = json.loads((ROOT / "data" / "models" / "order_risk.json").read_text())
    d = P.load_data(D.DATA_DIR / "stealth.npz")
    trials = [oneshot(model, d, seed=a.seed + i) for i in range(a.trials)]
    after = sorted(t["stealth_usd_recall_other_runs"]["after_one_label"] for t in trials)
    cost = sorted(t["honest_newly_held_rate"] for t in trials)
    res = {"trials": trials, "summary": {
        "labels": a.trials, "stealth_usd_recall_before": trials[0]["stealth_usd_recall_other_runs"]["before"],
        "after_one_label": {"min": after[0], "median": after[len(after) // 2], "max": after[-1]},
        "honest_newly_held_rate": {"min": cost[0], "median": cost[len(cost) // 2], "max": cost[-1]},
        "note": "each trial labels ONE missed stealth order chosen at random and measures only on the other runs"}}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "oneshot.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    print(json.dumps(res["summary"], indent=1))
    return 0


def replay_arena(stream: Path, model_path: Path | None = None, limit: int | None = None) -> dict:
    """Score a recorded arena decision stream inline (point-in-time, one event at a time) and apply the tighten-only rule.
    Reports bad dollars the gate allowed and how many the risk layer would have held or refused, and the honest cost.
    Budget effects are NOT re-simulated: refusing a colluder would also free daily budget for honest agents, which this undercounts."""
    rows = [json.loads(l) for l in stream.open()]
    meta = json.loads(stream.with_suffix(".summary.json").read_text()) if stream.with_suffix(".summary.json").exists() else (rows[0] if "envelopes" in rows[0] else {})
    events = [r for r in rows if "order" in r][: limit or None]
    res = replay_events(events, meta.get("envelopes", []), int((meta.get("config") or {}).get("steps_per_day") or 500), model_path)
    res["stream"] = stream.name
    return res


def replay_events(events: list[dict], envelopes: list[dict], spd: int, model_path: Path | None = None) -> dict:
    """The arena replay on in-memory events (used by the dashboard API as well as the CLI)."""
    from .scorer import RiskScorer, arena_event, tighten
    envs = {e["name"]: {"per_order": e["per_order"], "daily": e["daily"], "step_up": e.get("step_up"), "band_pct": e.get("band_pct")} for e in envelopes}
    sc = RiskScorer.load(model_path)
    sc.set_envelopes(envs, spd)
    tot = {"bad_allowed_usd": 0.0, "bad_held_usd": 0.0, "bad_refused_usd": 0.0, "honest_allowed": 0, "honest_held": 0, "honest_refused": 0,
           "honest_allowed_usd": 0.0, "honest_tightened_usd": 0.0, "by_label": {}}
    lat = []
    for e in events:
        ev = arena_event(e)
        r = sc.score(ev)
        sc.observe(ev)
        lat.append(r["latency_us"])
        if e.get("d") != "allow" or e.get("replay"):
            continue
        after = tighten("allow", r)
        usd = float(e.get("risk") or 0.0)
        if e["label"] == "legit":
            tot["honest_allowed"] += 1
            tot["honest_allowed_usd"] += usd
            if after != "allow":
                tot["honest_" + ("held" if after == "hold" else "refused")] += 1
                tot["honest_tightened_usd"] += usd
        else:
            tot["bad_allowed_usd"] += usd
            if after != "allow":
                tot["bad_" + ("held" if after == "hold" else "refused") + "_usd"] += usd
            b = tot["by_label"].setdefault(e["label"], {"allowed_usd": 0.0, "stopped_usd": 0.0})
            b["allowed_usd"] += usd
            b["stopped_usd"] += usd if after != "allow" else 0.0
    lat.sort()
    stopped = tot["bad_held_usd"] + tot["bad_refused_usd"]
    tot.update({"events": len(events), "steps_per_day": spd,
                "leak_before_usd": round(tot["bad_allowed_usd"], 2), "leak_after_usd": max(0.0, round(tot["bad_allowed_usd"] - stopped, 2)),
                "bad_stopped_share": round(stopped / tot["bad_allowed_usd"], 4) if tot["bad_allowed_usd"] else None,
                "honest_tightened_rate": round((tot["honest_held"] + tot["honest_refused"]) / max(tot["honest_allowed"], 1), 5),
                "latency_us": {"p50": lat[len(lat) // 2], "p99": lat[int(len(lat) * 0.99)]} if lat else None,
                "caveat": "decision-stream replay: budget a refused colluder would have freed for honest agents is not re-simulated"})
    for b in tot["by_label"].values():
        b["allowed_usd"], b["stopped_usd"] = round(b["allowed_usd"], 2), round(b["stopped_usd"], 2)
    return tot


def cmd_arena(a) -> int:
    res = replay_arena(Path(a.stream), limit=a.limit)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"arena-replay-{Path(a.stream).stem}.json"
    out.write_text(json.dumps(res, indent=1, sort_keys=True))
    print(json.dumps({k: res[k] for k in ("events", "leak_before_usd", "leak_after_usd", "bad_stopped_share", "honest_tightened_rate", "latency_us")}, indent=1))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="og-risk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build-data", help="arena runs -> labelled corpus")
    p.add_argument("--runs", type=int, default=48)
    p.add_argument("--stealth", type=int, default=8)
    p.set_defaults(fn=cmd_build_data)
    p = sub.add_parser("train", help="fit, calibrate and export data/models/order_risk.json")
    p.add_argument("--iters", type=int, default=80)
    p.set_defaults(fn=cmd_train)
    p = sub.add_parser("eval", help="every evaluation protocol -> results/risk/eval.json")
    p.add_argument("--with-text", action="store_true", help="include the synthetic-rationale text features (not the shipped model)")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("demo-oneshot", help="one analyst label, measured on runs it did not come from")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--trials", type=int, default=10)
    p.set_defaults(fn=cmd_demo_oneshot)
    p = sub.add_parser("arena", help="score a recorded arena stream inline and apply the tighten-only rule")
    p.add_argument("--stream", default=str(ROOT / "results" / "arena" / "arena-s7-k1000-t2000.jsonl"))
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(fn=cmd_arena)
    a = ap.parse_args(argv)
    return a.fn(a)
