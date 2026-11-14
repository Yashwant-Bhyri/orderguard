"""`og-lab`: the attack lab's command line.

  og-lab cases                           list the registry
  og-lab estimate --model M --arms ...   expected calls and US$ before any live run
  og-lab run --model M --arms ... --cases all|ids|families
  og-lab adaptive --target-arm full --goals transfer,unlisted_ticker,oversize,sell,false_belief --rounds 5
  og-lab detect --screens M[,M2] [--deberta]
  og-lab tables [--check] [--print]      rebuild docs/RESULTS.md from results/ (offline)
  og-lab doubt | review                  print and hand-review the belief judge
  og-lab sandbox describe [--check]      what a world contains, every knob; writes docs/SANDBOX.md
  og-lab sweep --seeds N --families B,C,D --arms ... --concurrency K [--model M | --policy P] [--resume FILE]
"""
from __future__ import annotations

import argparse
from orderguard_guard.llm import SPEND
import os
import sys

from . import cases as C


def _arms(s: str) -> list[str]:
    arms = [a.strip() for a in s.split(",") if a.strip()]
    bad = [a for a in arms if a not in ("naive", "gate_only", "full")]
    if bad:
        raise SystemExit(f"unknown arm(s) {bad}; use naive, gate_only, full")
    return arms


def cmd_cases(a):
    cs = C.select(a.cases)
    for c in cs:
        print(f"{c.id:22} {c.family:7} {c.surface:6} {c.goal:15} stop={c.expected_stop:5} {c.technique}")
    print(f"{len(cs)} cases: " + ", ".join(f"{k}={v}" for k, v in sorted(C.counts().items())))


def cmd_estimate(a):
    from . import runner
    e = runner.estimate(C.select(a.cases), a.model, _arms(a.arms), a.reps)
    print(runner.format_estimate(e))


def _model(a):
    if getattr(a, "offline", False):
        from .sandbox.policy import PolicyLLM
        return (lambda: PolicyLLM(a.policy)), "offline"
    return a.model, "live"


def cmd_run(a):
    from . import runner
    cs = C.select(a.cases)
    arms = _arms(a.arms)
    model, mode = _model(a)
    if mode == "live":
        e = runner.estimate(cs, a.model, arms, a.reps)
        budget = float(os.environ.get("OG_BUDGET_USD", "0.05"))
        print(runner.format_estimate(e))
        if e["total"]["usd"] > budget and not a.force:
            raise SystemExit(f"estimate US${e['total']['usd']:.3f} exceeds OG_BUDGET_USD US${budget:.3f}; refusing (raise OG_BUDGET_USD or reduce --cases/--reps)")
    prog = lambda i, n, r: print(f"[{i}/{n}] {r['case']} {r['arm']} success={r['success']} stopped_by={r['stopped_by']} err={r['error']}", file=sys.stderr) if a.verbose else None   # noqa: E731
    out, res = runner.run_many(cs, model, arms, a.reps, concurrency=a.concurrency, mode=mode, progress=prog)
    print(f"wrote {out.name}: {len(res)} runs, errors {sum(1 for r in res if r.get('error'))}, "
          f"billed this process US${SPEND.spent_usd:.4f} over {SPEND.calls} live calls "
          f"(transcript cost incl. replayed replies US${sum(r['cost_usd'] for r in res):.4f})")


def cmd_adaptive(a):
    from . import adaptive
    goals = [g.strip() for g in a.goals.split(",")]
    if a.offline:
        raise SystemExit("adaptive campaigns need an attacker model; use a live model (or call adaptive.campaign with a ScriptedLLM in tests)")
    out, res = adaptive.run_campaigns(a.attacker, a.target, goals, a.rounds, a.target_arm, concurrency=a.concurrency)
    for r in res:
        print(f"{r['goal']:16} -> " + (f"SUCCESS round {r['success_round']}" if r["success_round"] else ("attacker refused/broke" if r["incomplete"] else f"held {len(r['rounds'])} rounds")) + f"  refusals={r['refusals']}")
    print(f"wrote {out.name}, billed this process US${SPEND.spent_usd:.4f} over {SPEND.calls} live calls "
          f"(transcript cost incl. replayed replies US${sum(r['cost_usd'] for r in res):.4f})")


def cmd_detect(a):
    from . import detect
    out, rows = detect.run_detect([s for s in a.screens.split(",") if s], deberta=a.deberta)
    for s in sorted({r["screen"] for r in rows}):
        x = [r for r in rows if r["screen"] == s]
        att = [r for r in x if r["label"] == "attack"]
        cl = [r for r in x if r["label"] == "clean"]
        print(f"{s}: recall {sum(r['flagged'] for r in att)}/{len(att)}, false alarms {sum(r['flagged'] for r in cl)}/{len(cl)}")
    print(f"wrote {out.name}")


def cmd_tables(a):
    from . import tables
    if a.check:
        problems = tables.integrity_problems()
        for x in problems:
            print(f"results integrity: {x}", file=sys.stderr)
        if problems:
            print("a raw result file is damaged or holds a ReplayMiss; restore it from version control or re-record it. Tables skip such lines silently, so the check refuses.", file=sys.stderr)
            return 1
        if tables.check():
            print("docs/RESULTS.md is up to date")
            return 0
        print("docs/RESULTS.md differs from a fresh rebuild; run `og-lab tables`", file=sys.stderr)
        return 1
    if a.print:
        sys.stdout.write(tables.build())
        return 0
    print("wrote", tables.write().name)
    return 0


def cmd_doubt(a):
    from . import judge
    print(judge.doubt_report())


def cmd_review(a):
    from . import judge, tables
    lines = judge.review_lines(tables.load_runs())
    print("\n".join(lines) if lines else "no belief judgements recorded yet")


def cmd_sandbox(a):
    from .sandbox import manifest
    if a.action == "describe":
        if a.check:
            if manifest.check():
                print("docs/SANDBOX.md is up to date")
                return 0
            print("docs/SANDBOX.md is stale; run `og-lab sandbox describe`", file=sys.stderr)
            return 1
        print(manifest.describe_text())
        print("\nwrote", manifest.write().name)
    return 0


def cmd_sweep(a):
    from pathlib import Path
    from .sandbox import sweep
    names = sweep.technique_names(a.families, a.techniques)
    arms = _arms(a.arms)
    model = None if a.model in (None, "", "offline") else a.model
    jobs = [(s, n, ar, None) for s in range(a.seed0, a.seed0 + a.seeds) for n in names for ar in arms]
    est = sweep.sweep_estimate(jobs, model)
    print(f"{len(names)} techniques x {a.seeds} seeds x {len(arms)} arms = {len(jobs)} jobs ({2 * len(jobs)} runs with twins); "
          + ("offline policy agent, US$0" if model is None else f"estimated US${est['usd']:.3f}, {est['calls']} calls"))
    if a.estimate_only:
        return 0
    prog = (lambda i, n, r: print(f"[{i}/{n}]", end="\r", file=sys.stderr)) if a.verbose else None
    try:
        out, res, info = sweep.run_sweep(a.seeds, names, arms, model=model, policy=a.policy, concurrency=a.concurrency, resume=Path(a.resume) if a.resume else None,
                                         fixed=sweep.parse_fixed(a.fix), seed0=a.seed0, reps=a.reps, progress=prog)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"wrote {out.name}: ran {info['ran']}, skipped {info['skipped']} already done")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="og-lab", description="OrderGuard attack lab")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        p = sub.add_parser(name, help=help)
        p.set_defaults(fn=fn)
        return p

    p = add("cases", cmd_cases, "list cases")
    p.add_argument("--cases", default="all")
    p = add("estimate", cmd_estimate, "expected calls and US$")
    p.add_argument("--model", default="deepseek/deepseek-v4.1-flash-1017")
    p.add_argument("--arms", default="naive,gate_only,full")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--cases", default="all")
    p = add("run", cmd_run, "run cases through the arms")
    p.add_argument("--model", default=os.environ.get("OG_MODEL", "deepseek/deepseek-v4.1-flash-1017"))
    p.add_argument("--arms", default="naive,gate_only,full")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--cases", default="all")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--offline", action="store_true", help="scripted policy agent instead of a model (zero spend)")
    p.add_argument("--policy", default="mixed", choices=["cautious", "credulous", "mixed"])
    p.add_argument("--force", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p = add("adaptive", cmd_adaptive, "adaptive attacker campaigns")
    p.add_argument("--attacker", default=os.environ.get("OG_MODEL", "deepseek/deepseek-v4.1-flash-1017"))
    p.add_argument("--target", default=os.environ.get("OG_MODEL", "deepseek/deepseek-v4.1-flash-1017"))
    p.add_argument("--target-arm", default="full", choices=["naive", "gate_only", "full"])
    p.add_argument("--goals", default="transfer,unlisted_ticker,oversize,sell,false_belief")
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--offline", action="store_true")
    p = add("detect", cmd_detect, "detector test")
    p.add_argument("--screens", default="deepseek/deepseek-v4.1-flash-1017")
    p.add_argument("--deberta", action="store_true")
    p = add("tables", cmd_tables, "rebuild docs/RESULTS.md")
    p.add_argument("--check", action="store_true")
    p.add_argument("--print", action="store_true")
    add("doubt", cmd_doubt, "print the doubt list")
    add("review", cmd_review, "list belief judgements for hand review")
    p = add("sandbox", cmd_sandbox, "sandbox manifest")
    p.add_argument("action", choices=["describe"])
    p.add_argument("--check", action="store_true")
    p = add("sweep", cmd_sweep, "sandbox sweep")
    p.add_argument("--seeds", type=int, default=10)
    p.add_argument("--seed0", type=int, default=0)
    p.add_argument("--families", default=None)
    p.add_argument("--techniques", default=None)
    p.add_argument("--arms", default="naive,gate_only,full")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--model", default=None, help="omit for the offline policy agent")
    p.add_argument("--policy", default="mixed", choices=["cautious", "credulous", "mixed"])
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--fix", default=None, help="pin parameters: key=value,key=value")
    p.add_argument("--resume", default=None)
    p.add_argument("--estimate-only", action="store_true")
    p.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)
    rc = a.fn(a)
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
