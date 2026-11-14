"""og-bench: OrderGuard Bench.

    og-bench run --profile quick           CI-sized (under two minutes): writes results/bench/quick.json and results/bench/report.html
    og-bench run --profile full            exchange-scale (100,000 agents, 1,200 envelopes, about twenty minutes)
    og-bench http --profile quick          the receiver over its real loopback HTTP bridge (needs permission to bind a local port)
    og-bench report                        rebuild results/bench/report.html (and print the markdown tables) from the JSON results

Every run: generate the workload -> sharded authority runs at several worker counts (gate only, and gate + order-risk model) ->
an independent audit of every run -> per-stage profile -> mutation runs the auditor must catch -> thread and process races ->
receiver in-process, kill/restart and HTTP runs, each ledger audited -> exact-at-limit probes -> economics -> JSON + HTML.
Intermediate files (decision logs, SQLite ledgers) go to a temporary directory that is removed at the end (keep it with --keep DIR).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from orderguard_guard import ROOT

from . import auditor as A
from . import economics, edges, engine as E, profiles, pyrace, receiver as R, report
from . import workload as W
from .market import BenchMarket

OUT = ROOT / "results" / "bench"


def machine() -> dict:
    cpu = platform.processor() or platform.machine()
    try:
        r = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            cpu = r.stdout.strip()
    except Exception:
        pass
    try:
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        mem = None
    import cryptography
    return {"os": platform.platform(), "machine": platform.machine(), "cpu": cpu, "logical_cpus": os.cpu_count(),
            "memory_gib": round(mem, 1) if mem else None, "python": platform.python_version(), "python_impl": platform.python_implementation(),
            "numpy": np.__version__, "cryptography": cryptography.__version__, "python_sqlite": sqlite3.sqlite_version, "node": R.node_version()}


class Log:
    def __init__(self, quiet: bool):
        self.quiet, self.t0, self.phases = quiet, time.perf_counter(), {}
        self._last = self.t0

    def __call__(self, msg: str) -> None:
        if not self.quiet:
            print(f"[{time.perf_counter() - self.t0:7.1f}s] {msg}", flush=True)

    def phase(self, name: str) -> None:
        now = time.perf_counter()
        self.phases[name] = round(now - self._last, 2)
        self._last = now


def _slim(run: dict) -> dict:
    return {k: v for k, v in run.items() if k not in ("logs", "heads", "ctl")}


def _audit_summary(a: dict) -> dict:
    return {k: a[k] for k in ("breach_total", "breaches", "checked", "notes", "examples", "envelopes", "gate_digest", "final_digest", "totals")}


def run(p: profiles.Profile, out_dir: Path, *, keep: Path | None = None, quiet: bool = False, skip_http: bool = False) -> dict:
    log = Log(quiet)
    work = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="og-bench-"))
    work.mkdir(parents=True, exist_ok=True)
    res: dict = {"profile": p.to_dict(), "machine": machine(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        log(f"profile {p.name}: {p.agents:,} agents, {p.owners * 3:,} envelopes, {p.steps:,} steps; work dir {work}")
        gen = work / "gen"
        res["workload"] = W.write_partitions(p, gen)
        market = BenchMarket(p.seed, p.steps, p.steps_per_day)
        reg = W.registry(p, market)
        res["market"] = market.describe()
        res["workload"].update({"agents": p.agents, "owners": p.owners, "envelopes": len(reg),
                                "envelopes_with_portfolio_limits": sum(1 for r in reg.values() if r["mandate"].get("maxPositionUsd") is not None)})
        log(f"workload: {res['workload']['items']:,} items")
        log.phase("generate")

        runs, audits, n1 = [], [], {}
        for risk, counts in ((False, p.workers), (True, p.risk_workers)):
            for n in counts:
                d = work / f"{'risk' if risk else 'gate'}-n{n}"
                d.mkdir(exist_ok=True)
                r = E.run_config(p, gen, d, n, risk=risk)
                a = A.audit_logs(r["logs"], reg, market)
                log(f"{'gate+risk' if risk else 'gate     '} N={n}: {r['decisions']:,} decisions in {r['wall_s']:.2f}s = {r['decisions_per_s']:,}/s; "
                    f"audit: {a['breach_total']} breaches, digest {a['gate_digest'][:12]}")
                runs.append(_slim(r))
                audits.append({"workers": n, "risk": risk, **_audit_summary(a)})
                if n == min(counts):
                    n1["risk" if risk else "gate"] = r
                elif not keep:
                    shutil.rmtree(d, ignore_errors=True)
        res["runs"], res["audits"] = runs, audits
        res["ctl"] = n1["gate"]["ctl"]
        gd = {a["gate_digest"] for a in audits}
        rd = {a["final_digest"] for a in audits if a["risk"]}
        res["determinism"] = {"gate_digest_identical_across_runs": len(gd) == 1, "gate_digests": sorted(gd),
                              "risk_final_digests": sorted(rd), "risk_final_identical_across_worker_counts": len(rd) <= 1}
        log.phase("authority_runs")

        if p.scorer_scaling_s:
            res["risk_scorer_scaling"] = E.scorer_scaling(p, gen, p.scorer_scaling_s)
            log("risk scorer scaling: " + "; ".join(f"{x['share']} of the swarm: {x['us_per_decision_last']} us/decision, {x['edges_last']:,} edges"
                                                    for x in res["risk_scorer_scaling"]["points"]))
        res["stages_python"] = E.stage_profile(p, gen, p.stage_sample)
        log(f"stage profile: gate p50 {res['stages_python']['gate'].get('p50')} us, risk p50 {res['stages_python']['risk_score'].get('p50')} us")
        log.phase("stage_profile")

        muts = []
        mw = max(w for w in p.workers if w <= 4)
        for m in E.MUTATIONS:
            d = work / f"mut-{m}"
            d.mkdir(exist_ok=True)
            r = E.run_config(p, gen, d, mw, mutation=m)
            a = A.audit_logs(r["logs"], reg, market)
            muts.append({"layer": "python authority", "mutation": m, "decisions": r["decisions"], "caught": a["breach_total"] > 0,
                         "breaches": a["breaches"], "example": a["examples"][:1]})
            log(f"mutation {m}: {a['breach_total']} breaches found -> {'CAUGHT' if a['breach_total'] else 'MISSED'}")
            if not keep:
                shutil.rmtree(d, ignore_errors=True)
        res["thread_race"] = [pyrace.thread_race(market, p.thread_race, 40), pyrace.thread_race(market, p.thread_race, 40, lock_off=True)]
        muts.append({"layer": "python authority", "mutation": "thread_race_lock_off", "caught": res["thread_race"][1]["audit"]["breach_total"] > 0,
                     "breaches": res["thread_race"][1]["audit"]["breaches"]})
        log(f"thread race: intact {res['thread_race'][0]['allowed_fresh']} of {res['thread_race'][0]['entitled_fills']} entitled fills, "
            f"{res['thread_race'][0]['audit']['breach_total']} breaches; lock off {res['thread_race'][1]['audit']['breach_total']} breaches")
        log.phase("mutations_python")

        days = p.steps / p.steps_per_day
        res["economics"] = economics.outcome(n1["risk"]["logs"], market.trusted, agents=p.agents, days=days)
        res["economics"]["risk_workers"] = n1["risk"]["workers"]
        log(f"economics: bad stopped {res['economics']['bad']['stopped_share']}, review load {res['economics']['review_load']['holds_per_day']}/day")
        log.phase("economics")

        res["edges"] = edges.run(market, work)
        log(f"edges: {sum(r['ok'] for r in res['edges']['rows'])}/{res['edges']['probes']} probes agree across Python, OrderGate and receiver")
        log.phase("edges")

        envs = R.pick_envelopes(n1["gate"]["logs"], p.receiver_envelopes)
        rxw = work / "receiver-workload.jsonl"
        res["receiver_workload"] = R.export_workload(n1["gate"]["logs"], reg, market, envs, rxw, p.receiver_max_orders)
        res["receiver"] = R.inprocess(rxw, reg, work, durable_max=max(2000, min(p.receiver_max_orders // 10, 25_000)))
        log(f"receiver in-process: fast {res['receiver']['fast']['decisions_per_s']:,}/s, durable {res['receiver']['durable']['decisions_per_s']:,}/s; "
            f"audit {res['receiver']['audit']['fast']['breach_total']} + {res['receiver']['audit']['durable']['breach_total']} breaches")
        g = R.growth(work, p.growth_orders, max(p.growth_orders // 10, 500))
        res["receiver_growth"] = g
        w = g["with_portfolio_limits"]
        log(f"receiver growth: propose p50 {w[0]['p50']} us at {w[0]['rows_before']:,} rows -> {w[-1]['p50']} us at {w[-1]['rows_before']:,} rows (portfolio limits on)")
        log.phase("receiver_inprocess")

        races = [R.race(work, p.race_procs, p.race_orders, shared_keys=False, tag="race-budget"),
                 R.race(work, p.race_procs, p.race_orders, shared_keys=True, tag="race-dupkeys"),
                 R.race(work, p.race_procs, p.race_orders, shared_keys=False, mutation="budgetLockOff", tag="race-budget-mut"),
                 R.race(work, p.race_procs, p.race_orders, shared_keys=True, mutation="idempotencyOff", tag="race-dupkeys-mut")]
        res["process_race"] = races
        for r in races[2:]:
            muts.append({"layer": "typescript receiver", "mutation": r["mutation"], "caught": r["audit"]["breach_total"] > 0, "breaches": r["audit"]["breaches"],
                         "example": r["audit"]["examples"][:1]})
        log("process race: " + "; ".join(f"{'dup keys' if r['shared_keys'] else 'budget'}{'/' + r['mutation'] if r['mutation'] else ''}: "
                                          f"{r['ledger_rows']} rows, {r['audit']['breach_total']} breaches" for r in races))
        log.phase("process_race")

        res["fault"] = R.fault(rxw, reg, R.busiest(rxw), work, p.fault_cycles, p.fault_orders, seed=p.seed)
        f = res["fault"]
        log(f"fault: {f['kills']} kills, {f['opens_verified']}/{f['opens']} opens verified, {f['commits_landed_without_ack']} commits landed without an ack, "
            f"audit {f['audit']['breach_total']} breaches")
        log.phase("fault")

        res["mutations"] = muts
        if skip_http:
            res["http"] = {"skipped": True, "reason": "--skip-http"}
        else:
            res["http"] = R.http(rxw, reg, R.busiest(rxw), work / "http.json", p.http_requests, p.http_concurrency)
            log("http: " + (f"skipped ({res['http'].get('reason')})" if res["http"].get("skipped") else
                            f"{res['http']['requests_per_s']:,} req/s, p50 {res['http']['latency_us']['p50']} us, p99 {res['http']['latency_us']['p99']} us"))
        log.phase("http")
        res["verdict"] = verdict(res)
        res["phases_s"] = log.phases
        res["total_s"] = round(time.perf_counter() - log.t0, 1)
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{p.name}.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    if res.get("http") and not res["http"].get("skipped"):
        (out_dir / "http.json").write_text(json.dumps({**res["http"], "profile": p.name, "machine": res["machine"]}, indent=1, sort_keys=True))
    report.write(out_dir)
    log(f"verdict: {res.get('verdict', {}).get('summary')}; wrote {out_dir / (p.name + '.json')} and {out_dir / 'report.html'}")
    return res


def verdict(res: dict) -> dict:
    checks = {
        "every run audited with zero breaches": all(a["breach_total"] == 0 for a in res["audits"]),
        "gate decisions identical at every worker count": res["determinism"]["gate_digest_identical_across_runs"],
        "every mutation caught by the auditor": all(m["caught"] for m in res["mutations"]),
        "thread race: exact entitlement, zero breaches": res["thread_race"][0]["audit"]["breach_total"] == 0 and res["thread_race"][0]["allowed_fresh"] == res["thread_race"][0]["entitled_fills"],
        "process race: zero breaches with the lock and idempotency on": all(r["audit"]["breach_total"] == 0 for r in res["process_race"] if not r["mutation"]),
        "receiver ledgers audited with zero breaches": all(v["breach_total"] == 0 for v in res["receiver"]["audit"].values()),
        "kill/restart: chain verified on every reopen, zero breaches, no acknowledged effect lost": res["fault"]["audit"]["breach_total"] == 0
            and res["fault"]["opens_verified"] == res["fault"]["opens"] and res["fault"]["completed"] and res["fault"]["acked_effect_mismatches"] == 0,
        "exact-at-limit probes agree across Python, OrderGate and receiver": res["edges"]["all_ok"],
        "forged and replayed mandates did not take": all(c["result"].startswith("rejected") or c["action"] in ("revoke", "replay_mandate") for c in res["ctl"])
            and all(c["result"] == "kept existing state" for c in res["ctl"] if c["action"] == "replay_mandate"),
    }
    ok = all(checks.values())
    return {"checks": checks, "pass": ok, "summary": "PASS: every guarantee held and every mutation was caught" if ok else
            "FAIL: " + "; ".join(k for k, v in checks.items() if not v)}


def cmd_run(a) -> int:
    p = profiles.get(a.profile, seed=a.seed)
    res = run(p, Path(a.out), keep=Path(a.keep) if a.keep else None, quiet=a.quiet, skip_http=a.skip_http)
    return 0 if res.get("verdict", {}).get("pass") else 1


def cmd_http(a) -> int:
    """The HTTP bridge bench on its own: a small workload, the busiest envelope's orders, N requests over loopback."""
    p = profiles.get(a.profile, seed=a.seed)
    work = Path(tempfile.mkdtemp(prefix="og-bench-http-"))
    try:
        sp = profiles.Profile(**{**p.to_dict(), "agents": min(p.agents, 20_000), "owners": min(p.owners, 80), "steps": min(p.steps, 400),
                                 "steps_per_day": min(p.steps_per_day, 200)})
        W.write_partitions(sp, work / "gen")
        market = BenchMarket(sp.seed, sp.steps, sp.steps_per_day)
        reg = W.registry(sp, market)
        r = E.run_config(sp, work / "gen", work, 1)
        envs = R.pick_envelopes(r["logs"], 1)
        rxw = work / "rx.jsonl"
        R.export_workload(r["logs"], reg, market, envs, rxw, 50_000)
        res = R.http(rxw, reg, R.busiest(rxw), work / "http.json", a.requests or p.http_requests, a.concurrency or p.http_concurrency)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    res.update({"profile": p.name, "machine": machine()})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "http.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    print(json.dumps({k: res.get(k) for k in ("skipped", "reason", "requests_per_s", "latency_us", "ledger_integrity", "double_executions", "within_daily_cap")}, indent=1))
    report.write(out)
    return 0 if res.get("skipped") or (res.get("ledger_integrity") and res.get("double_executions") == 0 and res.get("within_daily_cap")) else 1


def cmd_report(a) -> int:
    report.write(Path(a.out))
    if a.markdown:
        print(report.markdown(Path(a.out)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="og-bench", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the benchmark")
    r.add_argument("--profile", default="quick", choices=sorted(profiles.PROFILES))
    r.add_argument("--seed", type=int)
    r.add_argument("--out", default=str(OUT))
    r.add_argument("--keep", help="keep decision logs and ledgers in this directory")
    r.add_argument("--skip-http", action="store_true")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(fn=cmd_run)
    h = sub.add_parser("http", help="receiver over its real HTTP bridge (binds a loopback port)")
    h.add_argument("--profile", default="quick", choices=sorted(profiles.PROFILES))
    h.add_argument("--seed", type=int)
    h.add_argument("--requests", type=int)
    h.add_argument("--concurrency", type=int)
    h.add_argument("--out", default=str(OUT))
    h.set_defaults(fn=cmd_http)
    rp = sub.add_parser("report", help="rebuild report.html from the JSON results")
    rp.add_argument("--out", default=str(OUT))
    rp.add_argument("--markdown", action="store_true", help="also print the results tables as markdown")
    rp.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
