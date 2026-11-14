"""`og-risk` (or `python -m orderguard_risk`): build the corpus, train and export the shipped model, run the honest evaluation, and the
one-shot demo.

    og-risk build-data [--runs 48] [--stealth 8]     arena runs -> data/risk/corpus.npz (+ stealth.npz, adaptive colluders held out)
    og-risk train                                    fit on training seeds, calibrate on validation seeds -> data/models/order_risk.json
    og-risk eval                                     every protocol (held-out seeds, regime shift, time split, leave-one-family-out,
                                                     ablations, adaptive colluders, MLP) -> results/risk/eval.json
    og-risk demo-oneshot                             one analyst-labelled stealth order -> how much similar flow is held, at what cost
    og-risk program | oneshot-eval | attack | drain | latency | arena      see docs/RISK.md
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


MODEL_OUT = ROOT / "data" / "models" / "order_risk.json"
V1_MODEL = ROOT / "data" / "models" / "order_risk_v1.json"


def export_model(ft, d, fit_rows) -> dict:
    """Fitted2 -> the JSON the pure-Python scorer loads (format /2)."""
    from . import features as F
    from . import models as M
    from . import pipeline as P
    from . import program as G
    ens = M.TreeEnsemble.from_sklearn(ft.clf, [F.NAMES[c] for c in ft.cols])
    ens.platt = ft.platt
    ix = np.flatnonzero(fit_rows & d.pop)
    rng = np.random.default_rng(0)
    hon = ix[d.y[ix] == 0]
    st = G.honest_stats(d.X[rng.choice(hon, size=min(20_000, len(hon)), replace=False)].astype(float).tolist())
    units = [{"name": u["name"], "family": u["family"], "why": u["why"], "pi": float(pi), "programmed_pi": u["pi"], "terms": [list(t) for t in u["terms"]]}
             for u, pi in zip(G.UNITS, ft.pi)]
    return {"format": "orderguard-order-risk/2", "features": "behavioural (no rationale text)", "cols": ft.cols, "feature_names": [F.NAMES[c] for c in ft.cols],
            "trees": ens.to_json(), "units": units, "combine": "noisy-or: risk = 1 - (1 - learned) * prod(1 - pi_k * u_k)",
            "monotone_increasing": [n for n in P.MONO],
            "thresholds": {"hold": ft.t_hold, "refuse": ft.t_refuse, "operating_budget": P.OPERATING_BUDGET, "refuse_budget": P.REFUSE_BUDGET,
                           "by_honest_hold_budget": {f"{b:.2%}": t for b, t in ft.thr.items()},
                           "calibrated_on": "out-of-fold scores over whole training runs: the honest quantile at each budget"},
            "edit": {"med": [round(v, 6) for v in st["med"]], "scale": [round(v, 6) for v in st["scale"]], "scale_dn": [round(v, 6) for v in st["scale_dn"]], "budget": 0.001, "coords": [n for n, _ in G.EDIT_COORDS]},
            "prototype": _proto_params(d, ft.cols, ix, np.random.default_rng(0)),
            "training": {"rows": ft.info["rows"], "runs": ft.info["runs"], "corpus_rows": int(len(d.y))}}


def _write_model(model: dict, out: Path) -> int:
    blob = json.dumps(model, separators=(",", ":"), sort_keys=True)
    out.write_text(blob)
    out.with_suffix(".sha256").write_text(hashlib.sha256(blob.encode()).hexdigest() + f"  {out.name}\n")
    return len(blob)


def cmd_train(a) -> int:
    """Fit the v2 model and the v1 architecture the same way, and ship v2 only if it wins at the declared operating budget on held-out seeds
    AND on the adaptive colluders (recall not lower, honest holds not higher). Otherwise the current model file is left alone."""
    from . import evaluate as E
    from . import pipeline as P
    from . import dataset as D
    d = P.load_data()
    tr, va, te = P.seed_split(d)
    fit_rows = tr | va
    tei = np.flatnonzero(te & d.pop)
    try:
        ext = P.load_data(D.DATA_DIR / "stealth.npz")
        ei = np.flatnonzero(ext.pop)
    except FileNotFoundError:
        ext = None
    new = P.fit2(d, fit_rows, iters=a.iters)
    old = P.fit2(d, fit_rows, cols=P.V1_COLS, units=False, mono=False, iters=a.iters)
    rep = {}
    for name, ft in (("v2_programmed", new), ("v1_architecture", old)):
        rep[name] = {"held_out_seeds": E.budget_table(P.predict2(ft, d.X[tei]), d, tei, ft.thr, ft.t_refuse),
                     "adaptive_colluders": None if ext is None else E.budget_table(P.predict2(ft, ext.X[ei]), ext, ei, ft.thr, ft.t_refuse)}
    key = f"{P.OPERATING_BUDGET:.2%}"
    wins = {}
    for part in ("held_out_seeds", "adaptive_colluders"):
        if rep["v2_programmed"][part] is None:
            continue
        n, o = rep["v2_programmed"][part]["budgets"][key], rep["v1_architecture"][part]["budgets"][key]
        wins[part] = {"v2": [n["usd_recall"], n["honest_hold_rate"]], "v1": [o["usd_recall"], o["honest_hold_rate"]],
                      "v2_wins": bool(n["usd_recall"] >= o["usd_recall"] and n["honest_hold_rate"] <= o["honest_hold_rate"])}
    ship = all(w["v2_wins"] for w in wins.values()) and not a.no_ship
    model = export_model(new, d, fit_rows)
    model["metrics_held_out_seeds"] = rep["v2_programmed"]["held_out_seeds"]["budgets"][key]
    model["metrics_adaptive_colluders"] = None if ext is None else rep["v2_programmed"]["adaptive_colluders"]["budgets"][key]
    out = MODEL_OUT if ship else MODEL_OUT.with_name("order_risk_candidate.json")
    n = _write_model(model, out)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "shipped_model.json").write_text(json.dumps({"shipped": "v2_programmed" if ship else "unchanged", "operating_budget": P.OPERATING_BUDGET,
                                                           "ship_gate": wins, **rep}, indent=1, sort_keys=True, default=float))
    print(f"wrote {out.relative_to(ROOT)} ({n / 1e6:.2f} MB, {len(model['trees']['trees'])} trees, {len(model['cols'])} features, {len(model['units'])} programmed units)")
    print("ship gate at", key, json.dumps(wins))
    print("SHIPPED v2" if ship else "NOT shipped: the current model file is unchanged; candidate written next to it")
    return 0


def cmd_eval(a) -> int:
    from . import evaluate as E
    from . import pipeline as P
    from . import dataset as D
    d = P.load_data()
    try:
        ext = P.load_data(D.DATA_DIR / "stealth.npz")
    except FileNotFoundError:
        ext = None
    res = E.run_all2(d, ext)
    res["features"] = "behavioural (no rationale text)"
    RESULTS.mkdir(parents=True, exist_ok=True)
    E.dump(RESULTS / "eval.json", res)
    print(f"wrote {(RESULTS / 'eval.json').relative_to(ROOT)}")
    return 0


def cmd_program(a) -> int:
    """The programmed units, their programmed and refitted weights, and how often each fires on honest and on each family (training runs)."""
    from . import pipeline as P
    from . import program as G
    d = P.load_data()
    tr, va, _te = P.seed_split(d)
    m = (tr | va) & d.pop
    U, y, fam, usd = G.units_matrix(d.X[m]), d.y[m], d.fam[m], d.notional[m]
    pi = G.refit_pi(U, y)
    rows = []
    for k, u in enumerate(G.UNITS):
        f = U[:, k] >= 0.5
        rows.append({"unit": u["name"], "family": u["family"], "terms": u["terms"], "programmed_pi": u["pi"], "refitted_pi": pi[k],
                     "honest_fire_rate": round(float(f[y == 0].mean()), 6),
                     "usd_recall_by_family": {fa: round(float(usd[f & (fam == fa)].sum() / usd[fam == fa].sum()), 3) for fa in ("collusion", "compromised", "fat_finger", "runaway", "stale_price")}})
    anyf = U.max(1) >= 0.5
    res = {"units": rows, "any_unit_honest_fire_rate": round(float(anyf[y == 0].mean()), 6), "rows": int(m.sum()), "note": "training and validation runs only"}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "programmed_units.json").write_text(json.dumps(res, indent=1))
    for r in rows:
        print(f"{r['unit']:<24} pi {r['programmed_pi']:.2f} -> {r['refitted_pi']:.3f}  honest fire {r['honest_fire_rate']:.4%}  {r['usd_recall_by_family']}")
    print("any unit, honest:", f"{res['any_unit_honest_fire_rate']:.4%}")
    return 0


def cmd_attack(a) -> int:
    """White-box adaptive attacker against the v2 model and against the v1 architecture; the winners re-measured on fresh seeds by both."""
    from . import adversary as A
    from . import pipeline as P
    d = P.load_data()
    tr, va, _te = P.seed_split(d)
    new = P.fit2(d, tr | va)
    old = P.fit2(d, tr | va, cols=P.V1_COLS, units=False, mono=False)
    B = P.OPERATING_BUDGET
    scorers = {"v2_programmed": (lambda X: P.predict2(new, X), new.thr[B]), "v1_architecture": (lambda X: P.predict2(old, X), old.thr[B]),
               "v1_architecture_at_1pct": (lambda X: P.predict2(old, X), old.thr[0.01])}
    res = {"operating_budget": B, "knobs": A.KNOBS, "naive_adaptive_colluder": {"theta": A.NAIVE, "fresh_seeds": A.remeasure(A.NAIVE, scorers)}}
    for target in ("v2_programmed", "v1_architecture"):
        fn, t = scorers[target]
        s = A.search(fn, t, n_random=a.random, log=(lambda *x: print(target, *x, file=sys.stderr)) if a.verbose else None)
        s["fresh_seeds"] = A.remeasure(s["best_theta"], scorers)
        res["optimised_against_" + target] = s
        print(target, json.dumps(s["best_theta"]), json.dumps(s["fresh_seeds"]))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "adversary.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    print(f"wrote {(RESULTS / 'adversary.json').relative_to(ROOT)}")
    return 0


def cmd_drain(a) -> int:
    """Paradigm (d) prototype: closed-form forecast that an envelope's shared daily budget runs out today, measured on held-out runs."""
    from . import dataset as D
    from . import portfolio as PF
    cols, metas = D.load_corpus()
    runs = sorted(m["run"] for m in metas)
    test = {r for r in runs if r % 4 == 1}
    res = PF.evaluate(cols, metas, set(runs) - test, test)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "drain_forecast.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


def cmd_latency(a) -> int:
    """Pure-Python scoring latency (features included) over a recorded arena stream -> results/risk/latency.json."""
    from .scorer import RiskScorer, arena_event
    stream = Path(a.stream)
    rows = [json.loads(l) for l in stream.open()]
    meta = json.loads(stream.with_suffix(".summary.json").read_text())
    sc = RiskScorer.load()
    sc.set_envelopes({e["name"]: {"per_order": e["per_order"], "daily": e["daily"], "step_up": e.get("step_up"), "band_pct": e.get("band_pct")} for e in meta["envelopes"]},
                     int((meta.get("config") or {}).get("steps_per_day") or 500))
    lat = []
    for r in rows:
        if "order" not in r:
            continue
        ev = arena_event(r)
        lat.append(sc.score(ev)["latency_us"])
        sc.observe(ev)
    lat.sort()
    n = len(lat)
    res = {"orders": n, "p50_us": lat[n // 2], "p99_us": lat[int(0.99 * n)], "p999_us": lat[int(0.999 * n)], "mean_us": round(sum(lat) / n, 2),
           "model_mb": round(MODEL_OUT.stat().st_size / 1e6, 3), "stream": stream.name, "note": "score() only: featurize + trees + units + reasons; observe() is separate"}
    (RESULTS / "latency.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


def cmd_oneshot_eval(a) -> int:
    """Leave-one-family-out with zero, one and five labelled examples (weight edits) and the full retrain -> results/risk/oneshot.json."""
    from . import evaluate as E
    from . import pipeline as P
    d = P.load_data()
    tr, va, te = P.seed_split(d)
    res = E.lofo(d, tr | va, te)
    RESULTS.mkdir(parents=True, exist_ok=True)
    E.dump(RESULTS / "oneshot.json", res)
    print(f"wrote {(RESULTS / 'oneshot.json').relative_to(ROOT)}")
    return 0


def cmd_demo_oneshot(a) -> int:
    """ONE analyst label on the adaptive-colluder runs, through the shipped scorer's own code path (program.edit_from_example): label a
    stealth order the shipped model missed in one run, measure on the other runs."""
    from . import evaluate as E
    from . import pipeline as P
    from . import dataset as D
    from .models import TreeEnsemble
    from . import program as G
    model = json.loads(MODEL_OUT.read_text())
    d = P.load_data(D.DATA_DIR / "stealth.npz")
    rows = np.flatnonzero(d.pop)
    ens = TreeEnsemble.from_json(model["trees"])
    X = d.X[rows]
    pl = np.array([ens.prob(ens.raw(x)) for x in X[:, model["cols"]].astype(float)])
    units = [{**u, "terms": [tuple(t) for t in u["terms"]]} for u in model.get("units", [])]
    p = P.combine(pl, G.units_matrix(X, units), [u["pi"] for u in units]) if units else pl
    t = model["thresholds"]["hold"]
    m = d.fam[rows] == "stealth"
    res = {"stealth_usd_recall_before": round(float(d.notional[rows][m & (p >= t)].sum() / d.notional[rows][m].sum()), 4),
           "one_label": E.oneshot_trials(d, rows, p, d, rows, p, "stealth", t, k=1, trials=a.trials, seed=a.seed, same_run_excluded=True, stats=model.get("edit")),
           "five_labels": E.oneshot_trials(d, rows, p, d, rows, p, "stealth", t, k=5, trials=a.trials, seed=a.seed, same_run_excluded=True, stats=model.get("edit")),
           "note": "each trial labels missed stealth orders chosen at random from one run and measures only on the other runs"}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "oneshot_demo.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    print(json.dumps(res, indent=1))
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
    p.add_argument("--no-ship", action="store_true", help="write the candidate next to the shipped model whatever the gate says")
    p = sub.add_parser("eval", help="every evaluation protocol -> results/risk/eval.json")
    p.set_defaults(fn=cmd_eval)
    p = sub.add_parser("program", help="the programmed units: weights, honest firing rate, recall by family")
    p.set_defaults(fn=cmd_program)
    p = sub.add_parser("oneshot-eval", help="leave-one-family-out: zero-shot, one-shot and five-shot weight edits, full retrain")
    p.set_defaults(fn=cmd_oneshot_eval)
    p = sub.add_parser("drain", help="portfolio-level prototype: forecast that an envelope's daily budget runs out -> results/risk/drain_forecast.json")
    p.set_defaults(fn=cmd_drain)
    p = sub.add_parser("latency", help="pure-Python scoring latency over a recorded stream -> results/risk/latency.json")
    p.add_argument("--stream", default=str(ROOT / "results" / "arena" / "arena-s7-k1000-t2000.jsonl"))
    p.set_defaults(fn=cmd_latency)
    p = sub.add_parser("attack", help="white-box adaptive attacker and the cost of evasion -> results/risk/adversary.json")
    p.add_argument("--random", type=int, default=40)
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=cmd_attack)
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
