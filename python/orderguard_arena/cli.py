"""`og-arena`: run the arena, replay a recording, benchmark the authority and compute the envelope frontier.

    og-arena run      [--seed 7] [--agents 1000] [--steps 2000] [--routing pinned|tightest_fit] [--agent-share 0.01]
    og-arena frontier [--stream results/arena/<run>.jsonl] [--samples 240] [--max-leak N] [--max-approvals N]
    og-arena bench    [--scales 200,1000,5000] [--steps 1000]
    og-arena record   [--symbols BTCUSDT,ETHUSDT,SOLUSDT] [--seconds 180]       read-only public market data from api.binance.com, no orders
    og-arena replay   --feed data/arena/feeds/<recording>.jsonl [--agents 200]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from orderguard_guard import ROOT

from .arena import ARENA_DIR, ArenaConfig, load_stream, run_arena
from .authority import Authority
from .envelopes import default_envelopes
from .feeds import BinancePublicFeed, RecordedFeed, ReplayFeed
from .frontier import run_frontier

FEEDS_DIR = ROOT / "data" / "arena" / "feeds"


def _money(x) -> str:
    return f"${x:,.0f}"


def print_summary(s: dict) -> None:
    c, L, B = s["config"], s["legit"], s["bad"]
    print(f"arena {s['name']}  seed {c['seed']}  agents {c['agents']}  steps {c['steps']} ({c['days']} days)  digest {s['digest']}")
    print(f"  proposals {s['proposals']:,}   allow {s['decisions']['allow']:,}  hold {s['decisions']['hold']:,}  refuse {s['decisions']['refuse']:,}  (duplicates absorbed {s['replays_absorbed']})")
    print(f"  legit    {L['proposals']:,} proposals  {_money(L['allowed_usd'])} allowed of {_money(L['notional_usd'])}  false refusals {L['false_refusal_rate']:.2%}  held {L['hold_rate']:.2%}")
    print(f"  bad      {B['proposals']:,} proposals  {_money(B['attack_notional_usd'])} attempted  blocked {_money(B['blocked_usd'])} ({B['blocked_share']:.1%})  leaked {_money(B['leaked_usd'])}  executed {_money(B['executed_usd'])}")
    print(f"  refusal reasons {s['refusal_reasons']}")
    t = s["timing"]
    print(f"  authority {t['authority_decisions_per_s']:,} decisions/s  p50 {t['latency_us']['p50']}us  p95 {t['latency_us']['p95']}us  p99 {t['latency_us']['p99']}us  (wall {t['wall_s']}s)")


def cmd_run(a) -> int:
    cfg = ArenaConfig(seed=a.seed, agents=a.agents, steps=a.steps, steps_per_day=a.steps_per_day, routing=a.routing, agent_share=a.agent_share,
                      name=a.name, strict=a.strict)
    r = run_arena(cfg, out_dir=a.out_dir, write=not (a.no_write or a.summary_only))
    print_summary(r.summary)
    if a.summary_only:
        d = Path(a.out_dir or ARENA_DIR)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{r.summary['name']}.summary.json").write_text(json.dumps(r.summary, indent=1, sort_keys=True))
        print(f"  wrote {r.summary['name']}.summary.json (no event log)")
    if r.path:
        print(f"  wrote {r.path.relative_to(ROOT) if r.path.is_relative_to(ROOT) else r.path.name} and its .summary.json")
    return 0


def cmd_replay(a) -> int:
    feed = RecordedFeed(a.feed, steps_per_day=a.steps_per_day)
    name = a.name or f"replay-{Path(a.feed).stem}-k{a.agents}"
    r = run_arena(ArenaConfig(seed=a.seed, agents=a.agents, steps=len(feed), steps_per_day=feed.steps_per_day, name=name), feed=feed, out_dir=a.out_dir, write=not a.no_write)
    print_summary(r.summary)
    return 0


def cmd_record(a) -> int:
    out = Path(a.out) if a.out else FEEDS_DIR / f"binance-public-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl"
    feed = BinancePublicFeed([s.strip() for s in a.symbols.split(",")], interval_s=a.interval, duration_s=a.seconds, record_path=out, steps_per_day=a.steps_per_day, base_url=a.base_url)
    n = 0
    for snap in feed:
        n += 1
    print(f"recorded {n} ticks ({feed.errors} failed polls) of {','.join(feed.symbols)} to {out}")
    return 0


def cmd_frontier(a) -> int:
    path = Path(a.stream) if a.stream else max(ARENA_DIR.glob("arena-*.jsonl"), key=lambda p: p.stat().st_mtime)
    meta, events = load_stream(path)
    f = run_frontier(events, meta, samples=a.samples, seed=a.seed, max_leak_per_day=a.max_leak, max_approvals_per_day=a.max_approvals,
                     max_false_refusal=a.max_false_refusal)
    print(f"frontier over {len(events):,} proposals from {path.name}: {f['candidates']} candidates, {len(f['frontier'])} on the frontier")
    for r in f["frontier"]:
        print(f"  utility {_money(r['utility_per_day_usd']):>12}/day  leak {_money(r['leaked_per_day_usd']):>11}/day  false-refusal {r['false_refusal_rate']:.1%}  approvals {r['approvals_per_day']:.0f}/day  {r['label']}")
    print(f"recommendation: {f['recommendation']['explanation']}")
    out = Path(a.out) if a.out else path.with_name(path.stem + ".frontier.json")
    slim = {k: v for k, v in f.items() if k != "all"}
    slim["all"] = [{k: r[k] for k in ("label", "utility_per_day_usd", "leaked_per_day_usd", "false_refusal_rate", "approvals_per_day", "utility_share", "blocked_share")} for r in f["all"]]
    out.write_text(json.dumps(slim, indent=1, sort_keys=True))
    print(f"wrote {out.name}")
    return 0


def cmd_policy(a) -> int:
    from .policy_review import load_parent, parent_for_review, review_policy
    from .policy_search import search_policies
    from .policy_sim import PolicyScenario

    try:
        batch = a.mode in ("rank", "search")
        if not a.draft and not batch:
            result = parent_for_review(a.source)
        else:
            parent, key, revoked = load_parent(a.source)
            scenario = PolicyScenario(a.seed, a.agents, a.steps, a.regime)
            limits = {k: v for k, v in {"bad_allowed_usd_per_day": a.max_bad, "false_refusal_rate": a.max_refusal,
                                       "holds_per_day": a.max_holds}.items() if v is not None}
            feed = RecordedFeed(a.feed) if a.feed else None
            if batch:
                if a.draft:
                    raise ValueError("Omit --draft when generating candidates with --mode rank or --mode search.")
                result = search_policies(parent, key, revoked, scenario, mode="rank" if a.mode == "rank" else "simulate",
                                         feed=feed, limits=limits)
            else:
                draft = json.loads(Path(a.draft).read_text(encoding="utf-8"))
                result = review_policy(parent, key, revoked, draft, scenario, mode=a.mode, feed=feed, limits=limits)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("fit", {}).get("fits", True) else 1


def cmd_l8(a) -> int:
    """End-to-end check against the real TypeScript receiver: static prices, one envelope, every decision also sent to L8. Needs node and a loopback port."""
    import os
    import tempfile
    from orderguard_guard.receiver_client import Bridge, bridge_available
    from .agents import PopulationConfig, make_population
    from .envelopes import EnvelopeBook, make_envelope, owner_key_from_seed
    ok, why = bridge_available()
    if not ok:
        print(f"l8 check skipped: {why}")
        return 2
    feed = ReplayFeed(a.seed, steps=a.steps, steps_per_day=a.steps, vol_scale=0.0)
    px = next(iter(feed)).trusted()
    syms = feed.symbols
    mand = {"symbols": syms, "sides": ["buy", "sell"], "maxOrderNotionalUsd": 25000, "maxDailyNotionalUsd": 400000, "priceBandPct": 1.0,
            "expiresAt": "2099-01-01T00:00:00Z", "referencePrices": px, "stepUpThresholdUsd": 20000}
    key = owner_key_from_seed("l8")
    book = EnvelopeBook(key.public_key())
    book.add(make_envelope(key, name="core", symbols=syms, per_order=25000, daily=400000, band_pct=1.0, step_up=20000))
    with tempfile.TemporaryDirectory() as d:
        mp = os.path.join(d, "mandate.json")
        Path(mp).write_text(json.dumps(mand))
        with Bridge.start(mp) as b:
            auth = Authority(book, steps_per_day=a.steps, receiver=b.receiver, receiver_sample=1.0)
            ags = make_population(PopulationConfig(n=a.agents, seed=a.seed), {"core": syms}, a.steps)
            r = run_arena(ArenaConfig(agents=a.agents, steps=a.steps, steps_per_day=a.steps, seed=a.seed), feed=feed, book=book, authority=auth, agents=ags)
    print(json.dumps({"decisions": r.summary["decisions"], "l8": r.summary["l8"]}, indent=1))
    l8s = r.summary["l8"]
    ok = bool(l8s["sampled"]) and l8s["disagree"] == 0 and l8s["unreachable"] == 0
    print(f"L8 CHECK {'PASS' if ok else 'FAIL'}: sampled {l8s['sampled']}, agree {l8s['agree']}, disagree {l8s['disagree']}, unreachable {l8s['unreachable']}")
    return 0 if ok else 1


def bench_one(agents: int, steps: int, seed: int = 7) -> dict:
    """Arena run (agents + authority, no event log) then the recorded proposals through a fresh authority in one batch, and a strict (real OrderGate) sample."""
    cfg = ArenaConfig(seed=seed, agents=agents, steps=steps, steps_per_day=max(steps // 4, 1), keep_events=True)
    t0 = time.perf_counter()
    r = run_arena(cfg)
    total = time.perf_counter() - t0
    ev = r.events
    # batch: same orders, fresh authority, one pass (prices set per event from the recorded trusted price)
    book = default_envelopes(ReplayFeed(seed, steps=1).symbols, agents)
    auth = Authority(book, steps_per_day=cfg.steps_per_day)
    items = []
    for e in ev:
        items.append((e["order"], e["key"], book.get(e["sleeve"]), None, e.get("trigger"), e["step"], e["agent"]))
    t = time.perf_counter()
    last = None
    for e, it in zip(ev, items):                       # prices change per proposal: keep the recorded trusted price in force for each decision
        auth.prices.clear()
        if e.get("tp") is not None:
            auth.prices[auth._norm_ticker(e["order"].get("ticker"))[0]] = e["tp"]
        auth.authorize(it[0], key=it[1], envelope=it[2], trigger=it[4], step=it[5], agent=it[6])
    dt_batch = time.perf_counter() - t
    lat = auth.latency_us()
    # strict: the real OrderGate per order on a sample (signature verification skipped: verified once at registration)
    sample = ev[: min(len(ev), 5000)]
    sbook = default_envelopes(ReplayFeed(seed, steps=1).symbols, agents)
    sauth = Authority(sbook, steps_per_day=cfg.steps_per_day, strict=True)
    t = time.perf_counter()
    for e in sample:
        sauth.prices.clear()
        if e.get("tp") is not None:
            sauth.prices[sauth._norm_ticker(e["order"].get("ticker"))[0]] = e["tp"]
        sauth.authorize(e["order"], key=e["key"], envelope=sbook.get(e["sleeve"]), trigger=e.get("trigger"), step=e["step"], agent=e["agent"])
    dt_strict = time.perf_counter() - t
    s = r.summary
    return {"agents": agents, "steps": steps, "proposals": s["proposals"], "decisions": s["decisions"], "digest": s["digest"],
            "arena_wall_s": round(total, 2), "arena_end_to_end_proposals_per_s": s["timing"]["end_to_end_proposals_per_s"],
            "authority_inline_decisions_per_s": s["timing"]["authority_decisions_per_s"],
            "authority_replay_pass_orders_per_s": round(len(ev) / dt_batch), "replay_latency_us": {k: round(v, 2) for k, v in lat.items()},
            "inline_latency_us": s["timing"]["latency_us"],
            "strict_orderGate_orders_per_s": round(len(sample) / dt_strict) if dt_strict else 0, "strict_sample": len(sample)}


def cmd_bench(a) -> int:
    rows = [bench_one(int(n), a.steps, a.seed) for n in a.scales.split(",")]
    print(f"{'agents':>7} {'proposals':>10} {'auth/s inline':>14} {'auth/s replay':>14} {'p50us':>7} {'p95us':>7} {'p99us':>7} {'OrderGate/s':>12} {'e2e prop/s':>11}")
    for r in rows:
        L = r["replay_latency_us"]
        print(f"{r['agents']:>7} {r['proposals']:>10,} {r['authority_inline_decisions_per_s']:>14,} {r['authority_replay_pass_orders_per_s']:>14,} {L['p50']:>7} {L['p95']:>7} {L['p99']:>7} {r['strict_orderGate_orders_per_s']:>12,} {r['arena_end_to_end_proposals_per_s']:>11,}")
    out = Path(a.out) if a.out else ARENA_DIR / "bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"note": "single process, one thread, CPython; authority latency is per decision inside authorize()", "rows": rows}, indent=1))
    print(f"wrote {out.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="og-arena", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    policy = sub.add_parser("policy", help="draft, check, estimate or simulate a mandate within a signed parent")
    policy.add_argument("--source", choices=("demo", "configured"), default="demo")
    policy.add_argument("--draft", help="path to the unsigned draft JSON. Omit to get the parent and a starting draft.")
    policy.add_argument("--mode", choices=("fit", "estimate", "simulate", "rank", "search"), default="fit",
                        help="Rank generates alternatives. Search simulates those alternatives against the supplied limits.")
    policy.add_argument("--seed", type=int, default=7)
    policy.add_argument("--agents", type=int, default=150)
    policy.add_argument("--steps", type=int, default=400)
    policy.add_argument("--regime", choices=("normal", "volatile", "poisoned", "collusion"), default="normal")
    policy.add_argument("--feed", help="optional path to a recorded feed")
    policy.add_argument("--max-bad", type=float)
    policy.add_argument("--max-refusal", type=float)
    policy.add_argument("--max-holds", type=float)
    policy.set_defaults(fn=cmd_policy)
    r = sub.add_parser("run", help="run a seeded arena")
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--agents", type=int, default=200)
    r.add_argument("--steps", type=int, default=2000)
    r.add_argument("--steps-per-day", type=int, default=500)
    r.add_argument("--routing", choices=("pinned", "tightest_fit"), default="pinned")
    r.add_argument("--agent-share", type=float, default=None, help="operator fair-share: max fraction of an envelope's daily cap one agent may use")
    r.add_argument("--strict", action="store_true", help="evaluate every order with the real OrderGate (slower)")
    r.add_argument("--name")
    r.add_argument("--out-dir")
    r.add_argument("--no-write", action="store_true")
    r.add_argument("--summary-only", action="store_true", help="write the summary json but not the event log")
    r.set_defaults(fn=cmd_run)
    f = sub.add_parser("frontier", help="sweep candidate envelopes over a recorded stream")
    f.add_argument("--stream")
    f.add_argument("--samples", type=int, default=240)
    f.add_argument("--seed", type=int, default=0)
    f.add_argument("--max-leak", type=float, default=None, help="risk budget: leaked bad notional per day (USD)")
    f.add_argument("--max-approvals", type=float, default=None, help="risk budget: human approvals per day")
    f.add_argument("--max-false-refusal", type=float, default=0.05)
    f.add_argument("--out")
    f.set_defaults(fn=cmd_frontier)
    b = sub.add_parser("bench", help="throughput and latency at several swarm sizes")
    b.add_argument("--scales", default="200,1000,5000")
    b.add_argument("--steps", type=int, default=1000)
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--out")
    b.set_defaults(fn=cmd_bench)
    l8 = sub.add_parser("l8", help="end-to-end: also send every decision to the real L8 receiver (needs node and a loopback port)")
    l8.add_argument("--agents", type=int, default=60)
    l8.add_argument("--steps", type=int, default=100)
    l8.add_argument("--seed", type=int, default=7)
    l8.set_defaults(fn=cmd_l8)
    rc = sub.add_parser("record", help="record read-only public Binance market data (no orders, no keys)")
    rc.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    rc.add_argument("--seconds", type=float, default=180.0)
    rc.add_argument("--interval", type=float, default=1.0)
    rc.add_argument("--steps-per-day", type=int, default=60)
    rc.add_argument("--base-url", default="https://api.binance.com", choices=("https://api.binance.com", "https://data-api.binance.vision"),
                    help="public market-data host (the .vision host is Binance's market-data-only mirror)")
    rc.add_argument("--out")
    rc.set_defaults(fn=cmd_record)
    rp = sub.add_parser("replay", help="run the arena on a recorded feed")
    rp.add_argument("--feed", required=True)
    rp.add_argument("--agents", type=int, default=200)
    rp.add_argument("--seed", type=int, default=7)
    rp.add_argument("--steps-per-day", type=int, default=None)
    rp.add_argument("--name")
    rp.add_argument("--out-dir")
    rp.add_argument("--no-write", action="store_true")
    rp.set_defaults(fn=cmd_replay)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
