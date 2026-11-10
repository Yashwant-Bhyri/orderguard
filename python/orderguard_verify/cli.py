"""Command line: `og check`, `og demo`, `og log`, `og eval`, `og native`, `og gate`, `og ingest`, `og run`, `og extractor-eval`."""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from .core import evalrun
from .core.card import text_card
from .core.gateway import Gateway
from .core.llm import DEFAULT_MODEL, ask_json
from .core.pipeline import check
from .finance.evalsetup import CASES, make_gateway
from .finance.pack import make_pack
from .finance.truth_store import TruthStore
from .paths import RESULTS, ROOT


def cmd_ingest(args) -> int:
    from .finance import edgar, quotes
    store = TruthStore()
    counts = edgar.ingest(store, args.tickers or None)
    print(f"loaded {sum(counts.values())} EDGAR snapshots for {len(counts)} companies")
    if not args.tickers:
        print(f"{quotes.load(store)} synthetic quote rows")
    return 0


def cmd_check(args) -> int:
    """Check any memo against SEC filings. Fetches the company's filings on demand. Exit code 0 only for pass."""
    try:
        text = sys.stdin.read() if args.memo == "-" else Path(args.memo).read_text()
    except OSError as e:
        print(f"could not read the memo: {e.strerror or e}: {args.memo}")
        return 1
    from .paths import DB
    ctx = {"ticker": args.ticker.upper(), "as_of": args.as_of}
    gw = Gateway(make_pack(on_demand=True), db_path=DB)
    reply = gw.check(text, ctx)
    result = gw.last if "run_id" in reply else None      # the live result, which still holds this run's model calls
    if result is None:
        print("could not check:", "; ".join(reply["reasons"]))
        return 1
    if args.json:
        print(json.dumps({"action": result.decision.action, "reasons": result.decision.reasons, "coverage": result.coverage,
                          "fix": [c.text for c in result.claims if c.id in result.decision.fix]}, indent=1))
    else:
        print(text_card(result))
        print(f"\n({len(result.calls)} model calls, ${result.cost_usd:.4f}, {result.seconds}s)")
    return 0 if result.decision.action == "pass" else 1


def cmd_run(args) -> int:
    """The gate path: a case file holds a memo and an order. Prints what the gate did with the order."""
    from .paths import DB
    case = json.load(open(args.case))
    day = case["order"].get("as_of")      # a case file is written by the operator, who may replay a date; an agent never can
    gw = Gateway(make_pack(on_demand=True), db_path=DB, clock=(lambda: date.fromisoformat(day)) if day else date.today)
    reply = gw.propose(case["research"], case["order"])
    if "run_id" not in reply:
        print(f"\nORDER: {reply['status'].upper()}: {'; '.join(reply['reasons'])}")
        return 0
    print(text_card(gw.get(reply["run_id"])[0], reply["status"]))
    print(f"\nORDER: {reply['status'].upper()}")
    return 0


def cmd_log(args) -> int:
    """The decision log: what was decided, why, on which evidence."""
    from .core.runs import RunStore
    from .paths import DB
    if not DB.exists():
        print("no decisions yet")
        return 0
    store = RunStore(DB, read_only=True)
    for row in store.all_runs()[: args.n]:
        d = row["decision"]
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["ts"]))
        print(f"{when}  {d['action'].upper():8} {row['status']:16} {row['summary']} (as of {row['as_of']}; {row['coverage']})")
        r, _ = store.get(row["run_id"])
        ev = {v.claim_id: v for v in r.verdicts}
        for reason in d["reasons"][:3]:
            print(f"      why: {reason}")
        for c in r.claims:
            for e in ev[c.id].evidence[:1]:
                if c.id in d["fix"]:
                    print(f"      evidence: {e.source}, public {e.as_of}, hash {e.hash[:12]}  {e.source_url}")
    return 0


def cmd_eval(args) -> int:
    cases = evalrun.load_cases(CASES, args.limit)
    results = evalrun.run_all(cases, make_gateway, ask_json, workers=args.workers)
    summary = evalrun.summarise(results)
    base = {"Allow everything (no gate)": evalrun.summarise(evalrun.baseline(cases, "cleared")),
            "Block everything (distrust all news)": evalrun.summarise(evalrun.baseline(cases, "blocked"))}
    table = evalrun.render(summary, base, os.getenv("OG_MODEL", DEFAULT_MODEL))
    print(table)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "RESULTS.md").write_text(table + "\n")
    (out / "results.json").write_text(json.dumps({"summary": summary, "cases": [dataclasses.asdict(r) for r in results]}, indent=1))
    misses = [r for r in results if not r.passed]
    if misses:
        print(f"\n{len(misses)} case(s) not handled as labelled (details in {out}/results.json):")
        for r in misses:
            print(f"  {r.id}: got {r.action}; {r.note[:110]}")
    return 0


def cmd_native(args) -> int:
    """The native-error test: memos nobody prepared, labels from the filings, four arms, scored by the independent grader."""
    from .native import run
    if args.holdout and args.split == "dev":
        args.split = "holdout"
    if not args.report_only:
        meta = run.run_split(args.split, tuple(args.arms.split(",")), args.workers, args.again, args.suffix)
        if args.split == "holdout" and (meta["dirty"] or "holdout-freeze" not in meta["tags"]):
            print("WARNING: this hold-out run is not from a clean commit tagged holdout-freeze; do not publish it as the hold-out result.")
    text = run.report(args.split, args.borderline, args.suffix)
    print(text)
    out = RESULTS / f"native_{args.split}{args.suffix}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    if not args.suffix:
        out.with_name(f"native_{args.split}_misses.md").write_text(run.misses_report(args.split, "engine", args.borderline))
    return 0


def cmd_gate(args) -> int:
    """Fail on regression, offline, from recorded model answers."""
    from . import gate
    return gate.main(args.update)


def cmd_extractor_eval(args) -> int:
    from .finance import extractor_eval
    rep = extractor_eval.run(ask_json, workers=args.workers)
    print(f"{rep['cases']} memos, {rep['gold_claims']} labelled claims: found {rep['found']}, "
          f"every field right {rep['exactly_right']}, extra numeric claims {rep['extra_numeric_claims']}")
    for cid, quote, why in rep["failures"]:
        print(f"  {cid}: {quote[:60]!r}: {why}")
    print(f"cost ${rep['cost_usd']:.4f}; model time {rep['seconds']:.0f}s")
    return 0


def cmd_demo(args) -> int:
    """One command: gateway + review page + an outside agent over MCP, three scenarios, then the results table."""
    from .paths import DB
    DB.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), "PYTHONUNBUFFERED": "1"}
    sys.stdout.reconfigure(line_buffering=True)
    port, ui = int(env.get("OG_GATEWAY_PORT", "8765")), int(env.get("OG_UI_PORT", "8766"))
    procs = [subprocess.Popen([sys.executable, "-m", "orderguard_verify.serve", name], cwd=ROOT, env=env) for name in ("gateway", "ui")]
    try:
        for p_ in (port, ui):
            for _ in range(100):
                try:
                    socket.create_connection(("127.0.0.1", p_), timeout=0.3).close()
                    break
                except OSError:
                    time.sleep(0.2)
        print(f"gateway (MCP) on :{port}, review page on http://127.0.0.1:{ui}\n")
        for title, packet in [("1. An honest memo: the real 10-K figures", "honest"),
                              ("2. The same story with a made-up revenue figure and a rumour", "poisoned"),
                              ("3. A rumour-led memo: nothing verifiable is the reason to trade", "rumour_led")]:
            print("=" * 78 + f"\n{title}\n" + "=" * 78)
            subprocess.run([sys.executable, "-m", "orderguard_verify.finance.agent", f"data/verify/demo/packets/{packet}.txt"], cwd=ROOT, env=env, check=False)
            print()
        print("=" * 78 + "\nDecision log (og log)\n" + "=" * 78)
        subprocess.run([sys.executable, "-m", "orderguard_verify.cli", "log"], cwd=ROOT, env=env)
        from .native import run as native_run
        if (native_run.OUT / "holdout_engine.json").exists():
            print("\n" + "=" * 78 + "\nHow it did on memos nobody prepared (`og native --holdout`)\n" + "=" * 78 + "\n" + native_run.headline("holdout"))
        if not args.no_wait:
            input(f"\nReview page: http://127.0.0.1:{ui}  (the third memo is waiting for you). Press Enter to stop. ")
    finally:
        for p_ in procs:
            p_.terminate()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="og", description="OrderGuard Verify (unaffiliated research prototype)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_, *arguments):
        s = sub.add_parser(name, help=help_)
        for a, kw in arguments:
            s.add_argument(a, **kw)
        s.set_defaults(fn=fn)

    add("ingest", cmd_ingest, "load SEC EDGAR fundamentals and synthetic quotes into the truth store", ("tickers", {"nargs": "*"}))
    add("check", cmd_check, "check a memo against SEC filings (fetched on demand)", ("memo", {"help": "text file, or - for stdin"}),
        ("--ticker", {"required": True}), ("--as-of", {"help": "date the memo was written, YYYY-MM-DD (default today)"}),
        ("--json", {"action": "store_true"}))
    add("run", cmd_run, "run a case file (memo + order) through the gate", ("case", {}))
    add("log", cmd_log, "show the decision log", ("-n", {"type": int, "default": 10}))
    add("eval", cmd_eval, "run the labelled eval cases and print the results table",
        ("--limit", {"type": int}), ("--workers", {"type": int, "default": 4}), ("--out", {"default": str(RESULTS)}))
    add("native", cmd_native, "native-error test: score the arms on memos drafted from memory",
        ("--split", {"default": "dev", "choices": ["dev", "holdout"]}), ("--holdout", {"action": "store_true", "help": "same as --split holdout"}),
        ("--arms", {"default": "none,judge_same,judge_other,engine"}), ("--workers", {"type": int, "default": 4}),
        ("--again", {"action": "store_true", "help": "repeat a hold-out run (recorded)"}), ("--report-only", {"action": "store_true"}),
        ("--borderline", {"action": "store_true", "help": "include claims the labeller marked borderline"}),
        ("--suffix", {"default": "", "help": "write records under a different name (a rerun after the hold-out was seen); never overwrites the frozen ones"}))
    add("gate", cmd_gate, "fail on regression against the recorded baseline (offline)", ("--update", {"action": "store_true"}))
    add("extractor-eval", cmd_extractor_eval, "score the claim extractor against hand-labelled memos", ("--workers", {"type": int, "default": 4}))
    add("demo", cmd_demo, "run the full demo: gateway, review page, outside agent over MCP",
        ("--no-wait", {"action": "store_true", "help": "exit when the scenarios finish instead of leaving the review page up"}))
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
