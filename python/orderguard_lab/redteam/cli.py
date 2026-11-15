"""`og-lab redteam run|report|repro`."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import replace

from . import campaign as C
from . import report as R

SPEND_NOTE = C.REDTEAM_DIR / "spend.json"
SMOKE = {"feed_inject": (0,), "page_inject": (0,), "fake_figures": (0,), "echo": (0,), "order": (0,), "collusion": (0,), "receiver": (0,)}


def _config(a) -> C.Config:
    cfg = C.Config()
    if C.CAMPAIGN.exists() and not (a.rounds or a.attackers or a.smoke or a.seeds or a.fresh):
        cfg = C.Config.from_dict(json.loads(C.CAMPAIGN.read_text())["config"])      # the recorded campaign, including where live runs ended early
    if a.fresh:
        cfg = replace(cfg, limits={})
    if a.rounds:
        cfg = replace(cfg, rounds=a.rounds)
    if a.attackers:
        cfg = replace(cfg, attackers=tuple(x.strip() for x in a.attackers.split(",") if x.strip()))
    if a.smoke:
        cfg = replace(cfg, seeds=dict(SMOKE))
    if a.seeds:
        cfg = replace(cfg, seeds={f: tuple(range(a.seeds)) for f in cfg.seeds})
    if a.concurrency:
        cfg = replace(cfg, concurrency=a.concurrency)
    return cfg


def _note_spend(rounds_added: int = 0) -> None:
    """Accumulate live spend by provider in results/redteam/spend.json (replays add nothing). Rounds are those added to campaign.json by this session."""
    from orderguard_guard.llm import SPEND, provider
    if SPEND.calls <= 0:
        return
    prev = json.loads(SPEND_NOTE.read_text()) if SPEND_NOTE.exists() else {"live_spend_usd": 0.0, "live_calls": 0, "sessions": 0}
    prev["live_spend_usd"] = round(prev["live_spend_usd"] + SPEND.spent_usd, 4)
    prev["live_calls"] += SPEND.calls
    prev["sessions"] += 1
    bp = prev.setdefault("by_provider", {"openrouter": {"live_spend_usd": round(prev["live_spend_usd"] - SPEND.spent_usd, 4), "live_calls": prev["live_calls"] - SPEND.calls, "rounds_added": None}})
    p = bp.setdefault(provider(), {"live_spend_usd": 0.0, "live_calls": 0, "rounds_added": 0})
    p["live_spend_usd"] = round(p["live_spend_usd"] + SPEND.spent_usd, 4)
    p["live_calls"] += SPEND.calls
    p["rounds_added"] = (p["rounds_added"] or 0) + rounds_added
    SPEND_NOTE.parent.mkdir(parents=True, exist_ok=True)
    SPEND_NOTE.write_text(json.dumps(prev, indent=1, sort_keys=True) + "\n")


def _rounds_on_disk() -> int:
    return sum(len(u["rounds"]) for u in json.loads(C.CAMPAIGN.read_text())["units"]) if C.CAMPAIGN.exists() else 0


def cmd_run(a) -> int:
    from orderguard_guard.llm import SPEND, default_mode
    cfg = _config(a)
    only = [x.strip() for x in a.only.split(",")] if a.only else None
    units = [u for u in C.plan_units(cfg) if not only or u[1] in only]
    print(f"{len(units)} campaigns x {cfg.rounds} rounds ({default_mode()} mode, budget US${SPEND.budget_usd:.2f})", file=sys.stderr)
    if a.estimate:
        return 0
    prog = (lambda m, f, s, r, core: print(f"[{m.split('/')[-1]} {f} s{s} r{r}] hard={core['kinds']} bad=${core['bad_usd']:,.0f}", file=sys.stderr)) if a.verbose else None
    out = C.REDTEAM_DIR / "smoke.json" if a.smoke and not a.out else (None if not a.out else __import__("pathlib").Path(a.out))
    before = _rounds_on_disk()
    camp = C.run(cfg, only=only, progress=prog, out=out)
    _note_spend(max(0, _rounds_on_disk() - before) if out is None else 0)
    S = camp["summary"]
    print(f"{S['units']} campaigns, {S['rounds']} rounds (+{S['failed_rounds']} failed), hard breaches {S['hard_breach_count']}, "
          f"round rate {R.fmt_ci(S['round_rate'])}, complete={camp['complete']}; billed this process US${SPEND.spent_usd:.4f} over {SPEND.calls} live calls; {camp['_wall_s']}s")
    if out is None and not only and not a.no_report:
        R.write(json.loads(C.CAMPAIGN.read_text()))      # from the file, so the page is a pure function of campaign.json
        print("wrote docs/REDTEAM.md")
    return 0


def _load() -> dict:
    if not C.CAMPAIGN.exists():
        raise SystemExit("no results/redteam/campaign.json yet; run `og-lab redteam run`")
    return json.loads(C.CAMPAIGN.read_text())


def cmd_report(a) -> int:
    camp = _load()
    if a.check:
        if R.check(camp):
            print("docs/REDTEAM.md is up to date")
            return 0
        print("docs/REDTEAM.md differs from a fresh render of campaign.json; run `og-lab redteam report`", file=sys.stderr)
        return 1
    if a.print:
        sys.stdout.write(R.render(camp))
        return 0
    R.write(camp)
    print("wrote docs/REDTEAM.md")
    return 0


def cmd_repro(a) -> int:
    camp = _load()
    cfg = C.Config.from_dict(camp["config"])
    bs = camp["summary"]["breaches"]
    if not bs:
        print("campaign.json records no hard breach")
        return 0
    b = bs[a.index]
    out = C.run_family_round(b["family"], b["plan"], b["seed"], cfg)
    hard = [x.to_dict() for x in out["breaches"]]
    print(json.dumps({"family": b["family"], "seed": b["seed"], "hard": hard}, indent=1))
    return 0 if hard else 1


def add_parser(sub) -> None:
    p = sub.add_parser("redteam", help="adaptive LLM attackers against the full stack: run, report, repro")
    p.set_defaults(fn=lambda a: {"run": cmd_run, "report": cmd_report, "repro": cmd_repro}[a.action](a))
    p.add_argument("action", choices=["run", "report", "repro"])
    p.add_argument("--rounds", type=int, default=0)
    p.add_argument("--attackers", default="")
    p.add_argument("--only", default="", help="comma-separated families")
    p.add_argument("--seeds", type=int, default=0, help="use seeds 0..N-1 for every family")
    p.add_argument("--smoke", action="store_true", help="one seed per family, written to results/redteam/smoke.json")
    p.add_argument("--concurrency", type=int, default=0)
    p.add_argument("--out", default="")
    p.add_argument("--estimate", action="store_true")
    p.add_argument("--fresh", action="store_true", help="ignore the stop points recorded in campaign.json (to try the missing rounds live)")
    p.add_argument("--no-report", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--print", action="store_true")
    p.add_argument("--index", type=int, default=0, help="repro: which recorded breach")
