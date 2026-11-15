#!/usr/bin/env python3
"""Build site/data.json (and the static Swarm Theater copy in site/theater/) from the committed results.

Every number the launch site shows is computed here from a file in this repository and carries that file's path. The page's own
HTML and JavaScript hold no figures: they place the strings this script formats. Nothing here reads the network or the clock, so
the output is byte-identical for the same inputs.

    .venv/bin/python scripts/build_site_data.py           # write site/data.json and site/theater/
    .venv/bin/python scripts/build_site_data.py --check   # exit 1 if either is stale (CI, tests)
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
OUT = SITE / "data.json"
THEATER_DIR = SITE / "theater"
SCHEMA = "orderguard-site-data/1"

sys.path.insert(0, str(ROOT / "python"))


# ---------------------------------------------------------------------------------------------------------------- reading
class Reader:
    """Reads repository files and remembers each one, so data.json can list (and hash) every input it was built from."""

    def __init__(self) -> None:
        self.used: dict[str, str] = {}

    def path(self, rel: str) -> Path:
        p = ROOT / rel
        self.used[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        return p

    def text(self, rel: str) -> str:
        return self.path(rel).read_text(encoding="utf-8")

    def json(self, rel: str):
        return json.loads(self.text(rel))

    def gz_lines(self, rel: str):
        with gzip.open(self.path(rel), "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


# ---------------------------------------------------------------------------------------------------------------- formatting
def _round_half_up(x: float, nd: int) -> float:
    q = 10 ** nd
    return math.floor(abs(x) * q + 0.5) / q * (1 if x >= 0 else -1)


def num(x: float, nd: int = 0) -> str:
    return f"{_round_half_up(x, nd):,.{nd}f}"


def usd(x: float) -> str:
    return "$" + num(x)


def usd_m(x: float, nd: int = 2) -> str:
    if x == 0:
        return "$0"
    return f"${_round_half_up(x / 1e6, nd):.{nd}f}M"


def usd_short(x: float) -> str:
    """$1.4M, $395k, $131: compact money for chart labels."""
    a = abs(x)
    if a >= 1e6:
        nd = 2 if a < 1e7 else 1
        return f"${_round_half_up(x / 1e6, nd):.{nd}f}M".replace(".0M", "M") if nd == 1 else f"${_round_half_up(x / 1e6, nd):.{nd}f}M"
    if a >= 1e4:
        return f"${_round_half_up(x / 1e3, 0):.0f}k"
    if a >= 1e3:
        return f"${_round_half_up(x / 1e3, 1):.1f}k"
    return f"${_round_half_up(x, 0):.0f}"


def pct(x: float, nd: int = 1) -> str:
    return f"{_round_half_up(100 * x, nd):.{nd}f}%"


def us(x: float) -> str:
    return (f"{_round_half_up(x, 2):g}" if x < 100 else num(x)) + " µs"


def tick_money(v: float) -> str:
    if v == 0:
        return "$0"
    if abs(v) >= 1e6:
        s = f"{v / 1e6:.1f}".rstrip("0").rstrip(".")
        return f"${s}M"
    if abs(v) >= 1e3:
        s = f"{v / 1e3:.1f}".rstrip("0").rstrip(".")
        return f"${s}k"
    return f"${v:g}"


def tick_int(v: float) -> str:
    return f"{v:,.0f}"


def nice_ticks(vmax: float, n: int = 4, fmt=tick_int) -> list[dict]:
    """Round axis ticks from 0 to at least vmax, with their labels."""
    if vmax <= 0:
        return [{"v": 0, "label": fmt(0)}]
    raw = vmax / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    top = math.ceil(vmax / step - 1e-9) * step
    k = int(round(top / step))
    return [{"v": round(i * step, 10), "label": fmt(i * step)} for i in range(k + 1)]


def log_ticks(lo: float, hi: float, fmt) -> list[dict]:
    out, v = [], 10 ** math.floor(math.log10(lo))
    while True:
        out.append({"v": v, "label": fmt(v)})
        if v >= hi * 0.9999:
            return out
        v *= 10


def fact(value, text: str, src: str, ptr: str | None = None) -> dict:
    return {"value": value, "text": text, "src": src, "ptr": ptr}


# ---------------------------------------------------------------------------------------------------------------- markdown helpers
_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)")


def inline(md: str) -> list[dict]:
    """A tiny inline-markdown parser: bold, code and links become segments the page builds as nodes (never as HTML)."""
    segs, pos = [], 0
    for m in _INLINE.finditer(md):
        if m.start() > pos:
            segs.append({"t": md[pos:m.start()]})
        if m.group(1) is not None:
            segs.append({"b": m.group(1)})
        elif m.group(2) is not None:
            segs.append({"code": m.group(2)})
        else:
            segs.append({"a": m.group(3), "href": m.group(4)})
        pos = m.end()
    if pos < len(md):
        segs.append({"t": md[pos:]})
    return segs


def section(md: str, heading: str) -> str:
    m = re.search(r"^## " + re.escape(heading) + r"\s*$(.*?)(?=^## |\Z)", md, re.M | re.S)
    if not m:
        raise KeyError(f"section {heading!r} not found")
    return m.group(1)


def md_table(body: str) -> list[list[str]]:
    rows = [ln for ln in body.splitlines() if ln.startswith("|")]
    out = []
    for ln in rows[2:]:
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip())[1:-1]]
        out.append(cells)
    return out


def rel_link(href: str, base: str) -> str:
    """Resolve a markdown link relative to the file it appeared in, to a path from the repository root."""
    if re.match(r"^[a-z]+:", href) or href.startswith("#"):
        return href
    path, _, frag = href.partition("#")
    parts = (Path(base).parent / path).as_posix().split("/")
    norm: list[str] = []
    for p in parts:
        if p == "..":
            norm.pop()
        elif p not in (".", ""):
            norm.append(p)
    return "/".join(norm) + (("#" + frag) if frag else "")


def fix_links(segs: list[dict], base: str) -> list[dict]:
    for s in segs:
        if "href" in s:
            s["href"] = rel_link(s["href"], base)
    return segs


# ---------------------------------------------------------------------------------------------------------------- sections
def readme_copy(r: Reader) -> dict:
    md = r.text("README.md")
    promise = re.search(r"^\*\*(.+?)\*\*\s*$", md, re.M).group(1)
    intro = re.search(r"^\*\*.+?\*\*[ \t]*\n\n(.+?)\n\n", md, re.M | re.S).group(1).strip()
    scope = []
    for ln in section(md, "Scope of this release").splitlines():
        m = re.match(r"^- \*\*(.+?)\*\*\s*(.*)$", ln)
        if m:
            scope.append({"lead": m.group(1), "text": fix_links(inline(m.group(2)), "README.md")})
    try_md = None
    for h in re.findall(r"^## (Try it in .+)$", md, re.M):
        try_md = h
    try_body = section(md, try_md)
    blocks = re.findall(r"```bash\n(.*?)```", try_body, re.S)
    needs = re.search(r"^(Needs .+?)$", try_body, re.M).group(1)
    after = re.search(r"^(In the dashboard.+?)$", try_body, re.M).group(1)
    watch_body = section(md, "Watch it")
    watch_cmd = re.search(r"```bash\n(.*?)```", watch_body, re.S).group(1).strip()
    watch_lede = watch_body.strip().split("\n\n")[0]
    integ = []
    for cells in md_table(section(md, "Integrate it")):
        integ.append({"surface": cells[0].replace("**", ""), "use": cells[1], "start": fix_links(inline(cells[2]), "README.md")})
    integ_note = section(md, "Integrate it").strip().splitlines()[-1]
    learn = []
    for ln in section(md, "Learn more").splitlines():
        if ln.startswith("- "):
            learn.append(fix_links(inline(ln[2:]), "README.md"))
    proof = {}
    for ln in section(md, "Proof").splitlines():
        m = re.match(r"^- \*\*(.+?)\*\*\s*(.*)$", ln)
        if m:
            body = re.sub(r"\s*\[[^\]]+\]\([^)]+\)(\s*·\s*\[[^\]]+\]\([^)]+\))*\s*$", "", m.group(2))
            proof[m.group(1).rstrip(".")] = inline(body)
    proof_note = section(md, "Proof").strip().split("\n\n")[0]
    licence = re.search(r"^(MIT licence\..*)$", md, re.M).group(1)
    return {
        "promise": promise,
        "intro": intro,
        "scope": scope,
        "try_heading": try_md,
        "try_needs": inline(needs),
        "try_blocks": [b.strip() for b in blocks],
        "try_after": fix_links(inline(after), "README.md"),
        "watch_lede": inline(watch_lede),
        "watch_cmd": watch_cmd,
        "integrations": integ,
        "integrations_note": inline(integ_note),
        "learn": learn,
        "licence": fix_links(inline(licence), "README.md"),
        "proof": proof,
        "proof_note": fix_links(inline(proof_note), "README.md"),
        "src": "README.md",
    }


def product_copy(r: Reader) -> dict:
    md = r.text("docs/PRODUCT.md")
    roll = section(md, "How a desk would roll it out")
    steps = []
    for m in re.finditer(r"^\d+\. \*\*(.+?)\*\*\s*(.+)$", roll, re.M):
        steps.append({"name": m.group(1).rstrip("."), "text": fix_links(inline(m.group(2)), "docs/PRODUCT.md")})
    closing = [ln for ln in roll.strip().splitlines() if ln.startswith("At every stage")][0]
    not_list = []
    for ln in section(md, "What it is not").splitlines():
        m = re.match(r"^- \*\*(.+?)\*\*\s*(.*)$", ln)
        if m:
            not_list.append({"lead": m.group(1), "text": inline(m.group(2))})
    return {"rollout": steps, "rollout_note": inline(closing), "not": not_list, "src": "docs/PRODUCT.md"}


def policy_packs(r: Reader) -> dict:
    packs = []
    for name in ("conservative-equities", "balanced-equities", "active-equities", "crypto-sleeve"):
        rel = f"policies/{name}.json"
        p = r.json(rel)
        packs.append({
            "name": name, "src": rel, "about": p["_about"], "symbols": len(p["symbols"]),
            "per_order": usd(p["maxOrderNotionalUsd"]), "daily": usd(p["maxDailyNotionalUsd"]),
            "per_name": usd(p["maxSymbolDailyNotionalUsd"]), "position": usd(p["maxPositionUsd"]),
            "orders": num(p["maxOrdersPerDay"]), "band": f"{p['priceBandPct']:.1f}%", "step_up": usd(p["stepUpAboveUsd"]),
            "life": f"{p['ttlHours']} h",
            "bar": {"per_order": p["maxOrderNotionalUsd"], "daily": p["maxDailyNotionalUsd"]},
        })
    return {"packs": packs, "src": "policies/README.md"}


def split_example(r: Reader) -> dict:
    """The fake-split order, decided by the real gate against the dashboard's demo mandate (the same call the dashboard makes)."""
    pages = r.text("python/orderguard_app/static/pages.js")
    notice = re.search(r'fake: \["feed", "Fake split notice", \(\) => "(.+?)"\]', pages).group(1)
    pre = re.search(r'split: \{ l: "fake split order", t: "(\w+)", s: "(\w+)", q: (\d+), p: ([\d.]+)', pages)
    order = {"ticker": pre.group(1), "side": pre.group(2), "quantity": int(pre.group(3)), "limit_price": float(pre.group(4))}
    r.path("python/orderguard_app/services.py")
    r.path("python/orderguard_app/models.py")
    from orderguard_app import models as M
    from orderguard_app import services as S
    as_of = M.CheckOrderRequest.model_fields["as_of"].default
    res = S.check_order(S.State(), order, None, None, as_of, 0.0, False)
    mt = res["meters"]
    return {
        "notice": notice,
        "order": {"ticker": order["ticker"], "side": order["side"], "qty": num(order["quantity"]), "limit": f"${order['limit_price']:.2f}"},
        "claimed_notional": usd(mt["limit_notional_usd"]),
        "trusted_price": f"${mt['trusted_price']:.2f}",
        "trusted_notional": usd(mt["notional_usd"]),
        "cap": usd(mt["per_order_cap_usd"]),
        "ratio": f"{mt['notional_usd'] / mt['per_order_cap_usd']:.1f}x",
        "decision": res["decision"],
        "decided_by": res["decided_by"],
        "reasons": res["reasons"],
        "order_text": f"{order['side']} {num(order['quantity'])} {order['ticker']} at ${order['limit_price']:.2f}",
        "claimed_calc": f"{num(order['quantity'])} × ${order['limit_price']:.2f} = {usd(mt['limit_notional_usd'])}",
        "trusted_calc": f"{num(order['quantity'])} × ${mt['trusted_price']:.2f} = {usd(mt['notional_usd'])}",
        "bars": {"claimed": mt["limit_notional_usd"], "trusted": mt["notional_usd"], "cap": mt["per_order_cap_usd"]},
        "src": "python/orderguard_app/services.py",
        "how": "orderguard_app.services.check_order on the dashboard's demo mandate, the same call POST /api/check-order makes",
    }


# ---------------------------------------------------------------------------------------------------------------- the recorded swarm
THEATER_STATES = ("allow", "hold", "refuse", "stopped_by_risk", "leak", "bad_hold", "bad_refuse", "duplicate", "honest_tightened")


def swarm(r: Reader) -> dict:
    """Per-bin decision counts of the recorded 1,000-agent run, decoded from the theater timeline (one state per order)."""
    tl = r.json("results/theater/timeline.json")
    assert tuple(tl["states"]) == THEATER_STATES, tl["states"]
    raw = base64.b64decode(tl["events"])
    codes = [struct.unpack_from("<H", raw, 2 * i)[0] >> 10 for i in range(len(raw) // 2)]
    per_step = tl["per_step"]
    steps = len(per_step)
    assert sum(per_step) == len(codes)
    bins = 160
    width = steps / bins
    keys = ("allow", "hold", "refuse", "gate", "risk", "leak", "dup")
    kind = {0: "allow", 1: "hold", 8: "hold", 2: "refuse", 5: "gate", 6: "gate", 3: "risk", 4: "leak", 7: "dup"}
    counts = [[0] * len(keys) for _ in range(bins)]
    i = 0
    for st, n in enumerate(per_step):
        b = min(bins - 1, int(st / width))
        for _ in range(n):
            counts[b][keys.index(kind[codes[i]])] += 1
            i += 1
    s = tl["series"]
    bad_cents = [0] * bins
    leak_cents = [0] * bins
    for st in range(steps):
        b = min(bins - 1, int(st / width))
        bad_cents[b] += s["bad_usd"][st]
        leak_cents[b] += s["bad_leak_usd"][st]
    facts = tl["facts"]
    summ = r.json("results/arena/arena-s7-k1000-t2000.summary.json")
    risk = r.json("results/risk/arena-replay-arena-s7-k1000-t2000.json")
    honest_to_human = sum(c[keys.index("hold")] for c in counts)
    run = tl["run"]
    # The market the agents traded on: the trusted price the guard sized each order at, last value per bin,
    # as a percent move from the first one; and how many orders per bin named each of these symbols.
    market_syms = ("AAPL", "MSFT", "SPY", "NVDA", "TSLA", "BTC-USD")
    last = {s: [None] * bins for s in market_syms}
    sym_counts = [[0] * (len(market_syms) + 1) for _ in range(bins)]
    with r.path("results/arena/arena-s7-k1000-t2000.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("type") == "meta":
                continue
            b = min(bins - 1, int(row["step"] / width))
            t = row["order"].get("ticker")
            k = market_syms.index(t) if t in market_syms else len(market_syms)
            sym_counts[b][k] += 1
            if k < len(market_syms) and isinstance(row.get("tp"), (int, float)) and row["tp"] > 0:
                last[t][b] = row["tp"]
    market = []
    for s in market_syms:
        series, prev = [], None
        for v in last[s]:
            prev = v if v is not None else prev
            series.append(prev)
        first = next(v for v in series if v is not None)
        series = [first if v is None else v for v in series]
        moves = [round((v / first - 1) * 100, 3) for v in series]
        market.append({"sym": s, "pct": moves, "last": f"{moves[-1]:+.1f}%"})
    return {
        "src": "results/theater/timeline.json",
        "run": run["name"],
        "agents": num(run["agents"]),
        "days": num(run["days"]),
        "steps": steps,
        "steps_per_day": run["steps_per_day"],
        "bins": bins,
        "keys": list(keys),
        "counts": counts,
        "bad_usd_cents": bad_cents,
        "leak_usd_cents": leak_cents,
        "orders": num(len(codes)),
        "orders_n": len(codes),
        "bad_total": usd_m(summ["bad"]["attack_notional_usd"]),
        "honest_to_human_n": honest_to_human,
        "market": market,
        "market_src": "results/arena/arena-s7-k1000-t2000.jsonl",
        "sym_counts": sym_counts,
        "facts": {
            "agents": fact(run["agents"], num(run["agents"]), "results/theater/timeline.json", "/run/agents"),
            "orders": fact(len(codes), num(len(codes)), "results/theater/timeline.json", "/events"),
            "bad_reached": fact(summ["bad"]["attack_notional_usd"], usd_m(summ["bad"]["attack_notional_usd"]),
                                "results/arena/arena-s7-k1000-t2000.summary.json", "/bad/attack_notional_usd"),
            "leak_after": fact(risk["leak_after_usd"], usd(risk["leak_after_usd"]), "results/risk/arena-replay-arena-s7-k1000-t2000.json", "/leak_after_usd"),
            "fit_mandate": fact(risk["bad_allowed_usd"], usd_m(risk["bad_allowed_usd"]), "results/risk/arena-replay-arena-s7-k1000-t2000.json", "/bad_allowed_usd"),
            "honest_tightened": fact(risk["honest_tightened_rate"], pct(risk["honest_tightened_rate"], 2),
                                     "results/risk/arena-replay-arena-s7-k1000-t2000.json", "/honest_tightened_rate"),
            "collusion": fact(summ["by_label"]["collusion"]["allow_usd"], usd_m(summ["by_label"]["collusion"]["allow_usd"]),
                              "results/arena/arena-s7-k1000-t2000.summary.json", "/by_label/collusion/allow_usd"),
            "fake_news_orders": fact(summ["by_label"]["fake_news"]["n"], num(summ["by_label"]["fake_news"]["n"]),
                                     "results/arena/arena-s7-k1000-t2000.summary.json", "/by_label/fake_news/n"),
            "fake_news_usd": fact(summ["by_label"]["fake_news"]["notional"], usd_m(summ["by_label"]["fake_news"]["notional"]),
                                  "results/arena/arena-s7-k1000-t2000.summary.json", "/by_label/fake_news/notional"),
            "fake_news_held": fact(summ["by_label"]["fake_news"]["hold"], num(summ["by_label"]["fake_news"]["hold"]),
                                   "results/arena/arena-s7-k1000-t2000.summary.json", "/by_label/fake_news/hold"),
            "theater_secs": fact(None, re.search(r"(\d+)-second", r.text("README.md")).group(1), "README.md", None),
        },
        "caption": (f"Replay of the recorded run {run['name']}: {num(run['agents'])} simulated agents, {num(len(codes))} orders over {num(run['days'])} days "
                    f"in {num(len(tl['envelopes']))} signed envelopes. Each dot is one recorded order; diamonds are bad orders, coloured by what stopped them."),
        "envelopes": [{"name": e["name"], "id": e["id"], "per_order": usd_short(e["per_order"]), "daily": usd_m(e["daily"], 0),
                       "band": f"±{e['band_pct']:g}%", "symbols": num(len(e["symbols"]))} for e in tl["envelopes"]],
    }


# ---------------------------------------------------------------------------------------------------------------- proof: bench
MUTATION_NAMES = {
    "budget_off": "Daily budget check and reservation",
    "idempotency_off": "Idempotency",
    "portfolio_off": "Portfolio limits",
    "revoke_off": "Revocation",
    "thread_race_lock_off": "Budget lock, threads racing one envelope",
    "budgetLockOff": "Budget lock, processes racing one ledger",
    "idempotencyOff": "Idempotency, processes sending the same keys",
}
BREACH_WORDS = {"daily_cap": "daily-cap breaches", "double_execution": "double executions", "orders_per_day": "order-count breaches",
                "position_cap": "position-cap breaches", "effect_after_revoke": "orders after revoke"}
SECONDARY = {"not_reproducible_by_order_gate", "idempotent_replay", "key_conflict_not_refused"}


def bench(r: Reader) -> dict:
    S = "results/bench/summary.json"
    F = "results/bench/full-partial.json"
    Q = "results/bench/quick.json"
    s, full, q = r.json(S), r.json(F), r.json(Q)
    at, head = s["at_scale"], s["headline"]
    runs = sorted(full["gate_runs"], key=lambda x: x["workers"])
    breaches = at["breaches"] + sum(x["audit_breaches"] for x in runs)
    vmax = max(x["decisions_per_s"] for x in runs)
    scaling = {
        "title": "Decisions per second by process count",
        "desc": f"Gate-only decisions per second on {at['decisions'] / 1e6:.2f}M orders from {num(at['agents'])} agents, at 1 to 8 processes on one laptop.",
        "src": [F],
        "bars": [{"x": f"{x['workers']}", "v": x["decisions_per_s"], "label": num(x["decisions_per_s"]), "breaches": num(x["audit_breaches"]),
                  "digest": x["gate_digest_prefix"]} for x in runs],
        "ticks": nice_ticks(vmax, 4),
        "digest": runs[0]["gate_digest_prefix"],
        "identical": bool(full["gate_digest_identical_across_worker_counts"]),
    }
    run1 = next(x for x in q["runs"] if x["workers"] == 1 and not x["risk"] and x["mutation"] is None)
    a = run1["latency_us"]["authorize"]
    rs = q["stages_python"]["risk_score"]
    pts = [("p50", "p50"), ("p90", "p90"), ("p99", "p99"), ("p99.9", "p999")]
    latency = {
        "title": "Latency per decision, percentiles",
        "desc": "Microseconds per decision for the mandate gate alone and for the order-risk score, one process, quick profile. Log scale.",
        "src": [Q],
        "rows": [
            {"name": "Mandate gate decision", "pts": [{"q": k, "v": a[f], "label": us(a[f])} for k, f in pts]},
            {"name": "Order-risk score", "pts": [{"q": k, "v": rs[f], "label": us(rs[f])} for k, f in pts]},
        ],
        "ticks": log_ticks(1, max(a["p999"], rs["p999"]), lambda v: f"{v:g} µs"),
    }
    muts = []
    for m in q["mutations"]:
        parts = [f"{num(v)} {BREACH_WORDS.get(k, k.replace('_', ' '))}" for k, v in m["breaches"].items() if k not in SECONDARY]
        muts.append({"name": MUTATION_NAMES.get(m["mutation"], m["mutation"]), "where": "Python authority" if m["layer"] == "python authority" else "TypeScript receiver",
                     "found": " and ".join(parts), "caught": bool(m["caught"])})
    eco = q["economics"]
    facts = {
        "agents": fact(at["agents"], num(at["agents"]), S, "/at_scale/agents"),
        "envelopes": fact(at["envelopes"], num(at["envelopes"]), S, "/at_scale/envelopes"),
        "orders": fact(at["decisions"], f"{at['decisions'] / 1e6:.2f}M", S, "/at_scale/decisions"),
        "breaches": fact(breaches, num(breaches), S, "/at_scale/breaches"),
        "dps": fact(at["decisions_per_s"], num(at["decisions_per_s"]), S, "/at_scale/decisions_per_s"),
        "mutations": fact(head["mutations"], num(head["mutations"]), S, "/headline/mutations"),
        "caught": fact(head["mutations_caught"], num(head["mutations_caught"]), S, "/headline/mutations_caught"),
        "procs_lo": fact(runs[0]["workers"], num(runs[0]["workers"]), F, "/gate_runs/0/workers"),
        "procs_hi": fact(runs[-1]["workers"], num(runs[-1]["workers"]), F, "/gate_runs/-1/workers"),
        "p99": fact(head["p99_us"], us(head["p99_us"]), S, "/headline/p99_us"),
        "audited": fact(head["decisions_audited"], num(head["decisions_audited"]), S, "/headline/decisions_audited"),
        "bad_stopped": fact(eco["bad"]["stopped_share"], pct(eco["bad"]["stopped_share"]), Q, "/economics/bad/stopped_share"),
    }
    return {"scaling": scaling, "latency": latency, "mutations": {"rows": muts, "src": [Q]}, "facts": facts}


def arena_speed(r: Reader) -> dict:
    B = "results/arena/bench.json"
    row = next(x for x in r.json(B)["rows"] if x["agents"] == 1000)
    return {"agents": fact(row["agents"], num(row["agents"]), B, "/rows/1/agents"),
            "strict": fact(row["strict_orderGate_orders_per_s"], num(row["strict_orderGate_orders_per_s"]), B, "/rows/1/strict_orderGate_orders_per_s"),
            "p99": fact(row["inline_latency_us"]["p99"], us(row["inline_latency_us"]["p99"]) + " p99", B, "/rows/1/inline_latency_us/p99")}


# ---------------------------------------------------------------------------------------------------------------- proof: red team
LAYER_NAMES = {"L1": "L1 normalise", "L2": "L2 model screen", "L3": "L3 risk bucket", "L5": "L5 order gate", "L6": "L6 figure check",
               "L7": "L7 trigger graph", "L8": "L8 receiver", "risk": "Order-risk layer", "model": "Agent ignored the bait"}


def redteam(r: Reader) -> dict:
    C = "results/redteam/campaign.json"
    camp = r.json(C)
    S, cfg, units = camp["summary"], camp["config"], camp["units"]
    planned, done = len(units) * cfg["rounds"], S["rounds"] + S["failed_rounds"]
    lay = S["layers"]
    groups = []
    for key, title in (("channel_rounds", "Fake-information rounds"),
                       ("swarm_orders", "Swarm attacker orders"),
                       ("receiver_ops", "Receiver abuse operations")):
        items = sorted(lay.get(key, {}).items(), key=lambda kv: (-kv[1], kv[0]))
        groups.append({"title": title, "bars": [{"name": LAYER_NAMES.get(k, k), "code": k, "v": v, "label": num(v)} for k, v in items]})
    gmax = max((b["v"] for g in groups for b in g["bars"]), default=1)
    fam = []
    for name, f in sorted(S["families"].items()):
        units_f = [u for u in units if u["family"] == name]
        f_planned = cfg["rounds"] * len(units_f)
        f_done = sum(len(u["rounds"]) for u in units_f)
        fam.append({"name": name, "layers": f["layers"], "done": f_done, "planned": f_planned, "label": f"{num(f_done)} of {num(f_planned)}",
                    "soft": f["soft_rounds"], "hard": f["hard_rounds"], "soft_label": num(f["soft_rounds"]), "hard_label": num(f["hard_rounds"])})
    swarm_bad = sum(f["bad_usd"] for f in S["families"].values() if f["kind"] == "swarm")
    rr, cr = S["round_rate"], S["campaign_rate"]
    rx = [u for u in units if u["family"] == "receiver"]
    facts = {
        "hard": fact(S["hard_breach_count"], num(S["hard_breach_count"]), C, "/summary/hard_breach_count"),
        "rounds": fact(S["rounds"], num(S["rounds"]), C, "/summary/rounds"),
        "round_hi": fact(rr["hi"], pct(rr["hi"]), C, "/summary/round_rate/hi"),
        "campaigns": fact(cr["n"], num(cr["n"]), C, "/summary/campaign_rate/n"),
        "campaign_hi": fact(cr["hi"], pct(cr["hi"]), C, "/summary/campaign_rate/hi"),
        "done": fact(done, num(done), C, "/summary/rounds + /summary/failed_rounds"),
        "planned": fact(planned, num(planned), C, "/units, /config/rounds"),
        "soft_rounds": fact(sum(f["soft_rounds"] for f in S["families"].values()), num(sum(f["soft_rounds"] for f in S["families"].values())), C, "/summary/families/*/soft_rounds"),
        "swarm_bad": fact(swarm_bad, usd(swarm_bad), C, "/summary/families/{order,collusion}/bad_usd"),
        "rx_done": fact(sum(len(u["rounds"]) for u in rx), num(sum(len(u["rounds"]) for u in rx)), C, "/units[family=receiver]/rounds"),
        "rx_planned": fact(cfg["rounds"] * len(rx), num(cfg["rounds"] * len(rx)), C, "/config/rounds"),
        "spend": fact(S["cost_recorded_usd"]["total"], f"US${S['cost_recorded_usd']['total']:.2f}", C, "/summary/cost_recorded_usd/total"),
    }
    attackers = [a.split("/")[0] for a in cfg["attackers"]]
    soft_text = (f"Measured at a small attacker budget: two low-cost models over {num(cfg['rounds'] * len(camp['units']))} planned rounds. "
                 f"Every round is broken down by family and by the layer that stopped it in the report.")
    return {
        "complete": bool(camp["complete"]),
        "attackers": [{"id": a, "org": a.split("/")[0]} for a in cfg["attackers"]],
        "attacker_orgs": sorted(set(attackers)),
        "groups": groups,
        "group_ticks": nice_ticks(gmax, 4),
        "bound": {"title": "Hard-breach rate per round, 95% Wilson interval", "k": rr["k"], "n": rr["n"], "lo": rr["lo"], "hi": rr["hi"],
                  "lo_label": pct(rr["lo"]), "hi_label": pct(rr["hi"]), "ticks": [{"v": t["v"] / 100, "label": t["label"]} for t in nice_ticks(100 * max(rr["hi"], cr["hi"]), 5, lambda v: f"{v:g}%")],
                  "desc": "Each bar is the 95% Wilson interval for the true hard-breach rate, given none observed. A shorter bar is stronger evidence.",
                  "round_label": f"Per round, {num(rr['n'])} usable rounds", "campaign_label": f"Per campaign, {num(cr['n'])} campaigns",
                  "campaign": {"lo": cr["lo"], "hi": cr["hi"], "hi_label": pct(cr["hi"]), "n": cr["n"]}},
        "families": fam,
        "soft_text": soft_text,
        "facts": facts,
        "src": [C, "docs/REDTEAM.md"],
    }


# ---------------------------------------------------------------------------------------------------------------- proof: simulation
ARM_NAMES = {"unguarded": "Wide-open signed envelope", "gate_only": "Gate only", "gate_portfolio": "Gate + portfolio limits", "full": "Full guard"}
SCENARIOS = (("fake_headline", "Fake headline"), ("real_crash", "Confirmed 8% crash"), ("collusion_ring", "Three-name collusion ring"),
             ("stale_feed", "Stale venue feed"), ("crowded_momentum", "Crowded momentum"))


def simulation(r: Reader) -> dict:
    # -- the tremor: where bad flow executes, by symbol and step, in one ring run (seed 7) -------------------------------------
    ring = r.json("results/sim/collusion_ring-k10000-s7.json")
    run7 = next(x for x in ring["runs"] if x["seed"] == 7)
    arms = ("unguarded", "gate_only", "full")
    cells: dict[str, dict[tuple[str, int], float]] = {}
    symbols: set[str] = set()
    steps = ring["config"]["steps"]
    for arm in arms:
        rel = "results/sim/" + run7["arms"][arm]["log_path"]
        acc: dict[tuple[str, int], float] = defaultdict(float)
        for e in r.gz_lines(rel):
            symbols.add(e["order"]["ticker"])
            if e["executed"] and e["label"] != "legit":
                acc[(e["order"]["ticker"], int(e["step"]))] += float(e["notional"])
        cells[arm] = acc
    ring_syms = ring["scenario"]["ring_symbols"]
    order = ring_syms + sorted(s for s in symbols if s not in ring_syms)
    vmax = max(max(c.values(), default=0) for c in cells.values())
    tremor = {
        "title": "Bad dollars executed, by symbol and step",
        "desc": (f"One seeded run (seed {run7['seed']}, {num(ring['config']['agents'])} agents, {steps} steps): a coordinated ring buys "
                 f"{', '.join(ring_syms)} from step {ring['scenario']['attack_start']} to {ring['scenario']['attack_end']}. Each cell is the bad notional that executed "
                 f"in that symbol and step; darker is more."),
        "src": ["results/sim/collusion_ring-k10000-s7.json"] + ["results/sim/" + run7["arms"][a]["log_path"] for a in arms],
        "symbols": order, "ring": ring_syms, "steps": steps,
        "attack": [ring["scenario"]["attack_start"], ring["scenario"]["attack_end"]],
        "vmax": vmax, "vmax_label": usd_short(vmax),
        "arms": [{"arm": a, "name": ARM_NAMES[a],
                  "cells": [[order.index(sym), st, round(v, 2), usd(v)] for (sym, st), v in sorted(cells[a].items(), key=lambda kv: (order.index(kv[0][0]), kv[0][1]))],
                  "total": usd_short(sum(cells[a].values())), "total_v": round(sum(cells[a].values()), 2)}
                 for a in arms],
    }
    # -- every scenario, bad dollars executed per arm (means over seeds) ---------------------------------------------------------
    rows = []
    for key, name in SCENARIOS:
        rel = f"results/sim/{key}-k10000-s7.json"
        d = r.json(rel)
        rows.append({"key": key, "name": name, "src": rel, "seeds": [x["seed"] for x in d["runs"]],
                     "vals": [{"arm": a, "v": d["arms"][a]["bad_dollars_executed"], "label": usd_short(d["arms"][a]["bad_dollars_executed"])}
                              for a in ("unguarded", "gate_only", "full")]})
    allv = [v["v"] for row in rows for v in row["vals"] if v["v"] > 0]
    scen = {"title": "Bad dollars executed per scenario", "desc": "Mean over three seeds, 10,000 agents and 64 steps per run; log scale.",
            "src": [x["src"] for x in rows], "rows": rows, "arms": [{"arm": a, "name": ARM_NAMES[a]} for a in ("unguarded", "gate_only", "full")],
            "ticks": log_ticks(min(allv), max(allv), tick_money)}
    seeds = rows[0]["seeds"]
    scen["desc"] = f"Mean over seeds {', '.join(map(str, seeds[:-1]))} and {seeds[-1]}, {num(ring['config']['agents'])} agents and {steps} steps per run. Log scale."
    # -- crowding: slippage, drawdown and honest fills under a crowded momentum stress ----------------------------------------
    CR = "results/sim/crowded_momentum-k10000-s7.json"
    cm = r.json(CR)
    carms = ("unguarded", "gate_only", "gate_portfolio", "full")
    crowd = {
        "title": "Crowding: slippage and worst drawdown by control",
        "desc": ("Crowded momentum stress, mean over three seeds; each panel has its own scale. Most of the honest fills lost come from the shared daily cap, "
                 "which is sized to ordinary activity: a desk that wants more capacity signs a larger budget and accepts the frontier above."),
        "src": [CR],
        "panels": [
            {"metric": "Modeled slippage", "rows": [{"arm": a, "name": ARM_NAMES[a], "v": cm["arms"][a]["slippage_usd"], "label": usd(cm["arms"][a]["slippage_usd"])} for a in carms]},
            {"metric": "Worst portfolio drawdown", "rows": [{"arm": a, "name": ARM_NAMES[a], "v": cm["arms"][a]["worst_case_loss_usd"], "label": usd(cm["arms"][a]["worst_case_loss_usd"])} for a in carms]},
            {"metric": "Honest fills lost vs wide-open", "rows": [{"arm": a, "name": ARM_NAMES[a], "v": cm["arms"][a]["honest_fills_lost_pct_vs_unguarded"],
                                                                    "label": pct(cm["arms"][a]["honest_fills_lost_pct_vs_unguarded"])} for a in carms]},
        ],
    }
    fr_names = {"frontier_tight": "Tight", "full": "Base", "frontier_loose": "Loose", "frontier_open": "Open capacity", "unguarded": "Wide-open control"}
    pts = []
    for a in ("frontier_tight", "full", "frontier_loose", "frontier_open", "unguarded"):
        x = cm["arms"][a]
        pts.append({"arm": a, "name": fr_names[a], "x": x["honest_filled_usd"], "y": x["worst_case_loss_usd"],
                    "x_label": usd_short(x["honest_filled_usd"]), "y_label": usd_short(x["worst_case_loss_usd"])})
    frontier = {"title": "The sizing frontier: honest notional filled against worst drawdown",
                "desc": "Five signed sizings of the same desk under the crowded momentum stress. Both axes log scale.",
                "src": [CR], "points": pts,
                "x_ticks": log_ticks(min(p["x"] for p in pts), max(p["x"] for p in pts), tick_money),
                "y_ticks": log_ticks(min(p["y"] for p in pts), max(p["y"] for p in pts), tick_money)}
    MR = "results/sim/fake_headline-k1000000-s99.json"
    mr = r.json(MR)
    facts = {
        "ring_unguarded": fact(ring["arms"]["unguarded"]["bad_dollars_executed"], usd_short(ring["arms"]["unguarded"]["bad_dollars_executed"]),
                               "results/sim/collusion_ring-k10000-s7.json", "/arms/unguarded/bad_dollars_executed"),
        "ring_full": fact(ring["arms"]["full"]["bad_dollars_executed"], usd_short(ring["arms"]["full"]["bad_dollars_executed"]),
                          "results/sim/collusion_ring-k10000-s7.json", "/arms/full/bad_dollars_executed"),
        "ring_seeds": fact([x["seed"] for x in ring["runs"]], ", ".join(str(x["seed"]) for x in ring["runs"][:-1]) + f" and {ring['runs'][-1]['seed']}",
                           "results/sim/collusion_ring-k10000-s7.json", "/runs/*/seed"),
        "million_agents": fact(mr["config"]["agents"], num(mr["config"]["agents"]), MR, "/config/agents"),
        "million_orders": fact(mr["scale"]["orders_per_arm_mean"], num(mr["scale"]["orders_per_arm_mean"]), MR, "/scale/orders_per_arm_mean"),
        "million_orders_total": fact(mr["scale"]["orders_total"], num(mr["scale"]["orders_total"]), MR, "/scale/orders_total"),
        "million_seeds": fact(mr["scale"]["seeds"], num(mr["scale"]["seeds"]), MR, "/scale/seeds"),
        "million_dps": fact(mr["scale"]["aggregate_decisions_per_s"], num(mr["scale"]["aggregate_decisions_per_s"]), MR, "/scale/aggregate_decisions_per_s"),
        "million_breaches": fact(sum(x["audit"]["cap_breaches"] for run in mr["runs"] for x in run["arms"].values()),
                                 num(sum(x["audit"]["cap_breaches"] for run in mr["runs"] for x in run["arms"].values())), MR, "/runs/*/arms/*/audit/cap_breaches"),
        "crowd_slip_open": fact(cm["arms"]["unguarded"]["slippage_usd"], usd(cm["arms"]["unguarded"]["slippage_usd"]), CR, "/arms/unguarded/slippage_usd"),
        "crowd_slip_full": fact(cm["arms"]["full"]["slippage_usd"], usd(cm["arms"]["full"]["slippage_usd"]), CR, "/arms/full/slippage_usd"),
    }
    return {"tremor": tremor, "scenarios": scen, "crowding": crowd, "frontier": frontier, "facts": facts}


# ---------------------------------------------------------------------------------------------------------------- proof: swarm results
def swarm_results(r: Reader) -> dict:
    A7 = "results/risk/arena-replay-arena-s7-k1000-t2000.json"
    AB = "results/risk/arena-replay-replay-binance-public-20261111T000117Z-k1000.json"
    S7 = "results/arena/arena-s7-k1000-t2000.summary.json"
    SB = "results/arena/replay-binance-public-20261111T000117Z-k1000.summary.json"
    Q = "results/bench/quick.json"
    rows = []
    for name, rp, sp, agents in (("Synthetic swarm, seed 7", A7, S7, None), ("Recorded Binance prices", AB, SB, None)):
        rk, sm = r.json(rp), r.json(sp)
        bad = sm["bad"]
        total = bad["attack_notional_usd"]
        gate = bad["blocked_usd"] + bad["duplicates_absorbed_usd"]
        risk_stop = rk["bad_allowed_usd"] - rk["leak_after_usd"]
        rows.append({"name": name, "agents": num(sm["config"]["agents"]) if "config" in sm and "agents" in sm["config"] else None,
                     "total": total, "total_label": usd_m(total),
                     "segs": [{"k": "gate", "v": gate, "label": usd_m(gate)}, {"k": "risk", "v": risk_stop, "label": usd_m(risk_stop)},
                              {"k": "leak", "v": rk["leak_after_usd"], "label": usd_m(rk["leak_after_usd"])}],
                     "stopped_label": pct((gate + risk_stop) / total),
                     "honest": rk["honest_tightened_rate"], "honest_label": pct(rk["honest_tightened_rate"], 2),
                     "honest_what": "of the honest orders the gate allowed, held or refused by the risk layer",
                     "src": [sp, rp]})
    q = r.json(Q)
    e = q["economics"]
    rows.append({"name": f"Exchange-scale bench, {num(e['agents'])} agents", "total": e["bad"]["proposed_usd"], "total_label": usd_m(e["bad"]["proposed_usd"], 1),
                 "segs": [{"k": "gate", "v": e["bad"]["stopped_by_gate_usd"], "label": usd_m(e["bad"]["stopped_by_gate_usd"], 1)},
                          {"k": "risk", "v": e["bad"]["stopped_by_risk_usd"], "label": usd_m(e["bad"]["stopped_by_risk_usd"], 1)},
                          {"k": "leak", "v": e["bad"]["let_through_usd"], "label": usd_m(e["bad"]["let_through_usd"])}],
                 "stopped_label": pct(e["bad"]["stopped_share"]),
                 "honest": e["honest"]["held_share"], "honest_label": pct(e["honest"]["held_share"]),
                 "honest_what": "of all honest orders, held for a human by the gate's step-up or the risk layer",
                 "src": [Q]})
    hmax = max(x["honest"] for x in rows)
    return {"title": "Bad dollars stopped, and the honest orders it cost",
            "desc": "Each bar is all the bad notional that reached the gate, split by what stopped it. The dot beside it is the share of honest orders sent to a person.",
            "rows": rows, "honest_ticks": nice_ticks(hmax * 100, 3, lambda v: f"{v:g}%"),
            "src": [A7, AB, S7, SB, Q]}


# ---------------------------------------------------------------------------------------------------------------- proof: review lane
def review(r: Reader) -> dict:
    T = "results/review/triage.json"
    t = r.json(T)
    qd = t["queues"]["model_flagged"]
    rc = qd["reviews_to_catch"]
    names = (("fifo", "First in, first out"), ("notional", "Biggest notional first"), ("jev", "Typed model advice alone"),
             ("jev+model", "Advice + risk model"), ("model", "Risk model: expected bad dollars"))
    rows = [{"k": k, "name": n, "v": rc[k]["90%"], "label": num(rc[k]["90%"]), "v99": rc[k]["99%"], "label99": num(rc[k]["99%"])} for k, n in names]
    vmax = max(x["v99"] for x in rows)
    facts = {
        "orders": fact(qd["orders"], num(qd["orders"]), T, "/queues/model_flagged/orders"),
        "model": fact(rc["model"]["90%"], num(rc["model"]["90%"]), T, "/queues/model_flagged/reviews_to_catch/model/90%"),
        "fifo": fact(rc["fifo"]["90%"], num(rc["fifo"]["90%"]), T, "/queues/model_flagged/reviews_to_catch/fifo/90%"),
        "saved": fact(1 - rc["model"]["90%"] / rc["fifo"]["90%"], pct(1 - rc["model"]["90%"] / rc["fifo"]["90%"], 0), T, "derived: 1 - model/fifo"),
        "cost": fact(t["jev_cost"]["cost_per_1000_usd"], f"US${t['jev_cost']['cost_per_1000_usd']:.3f}", T, "/jev_cost/cost_per_1000_usd"),
    }
    q90, q99 = sorted(rc["fifo"])                    # the study's own keys: "90%" and "99%" of bad dollars opened
    return {"q90": q90, "q99": q99, "title": "Reviews needed to open 90% of bad dollars", "desc": f"A queue of {num(qd['orders'])} flagged orders over {num(qd['hours'])} simulated hours. "
            "Bars: reviews to open 90% of the bad dollars; tick: 99%.", "src": [T], "rows": rows, "ticks": nice_ticks(vmax, 4), "facts": facts}


# ---------------------------------------------------------------------------------------------------------------- proof: lab
def lab(r: Reader) -> dict:
    """The two attack-lab headlines, read from the claims the README's checker rebuilds (og-arena verify)."""
    from orderguard_arena import claims
    r.path("python/orderguard_arena/claims.py")
    want = {}
    for doc, label, text in claims.lab_expectations():
        if doc.endswith("index.html") and label in ("home attacks", "home honest"):
            want[label] = text
    pv = {k: re.search(r'<span class="pv">(.+?)</span>', v).group(1) for k, v in want.items()}
    pl = {k: re.search(r'<span class="pl">(.+?)</span>', v).group(1) for k, v in want.items()}
    for p in ("results/runs/20261110T230149.jsonl", "results/sweeps/20261110T230155.jsonl"):
        r.path(p)
    def split(t: str) -> tuple[str, str]:
        head, _, bare = t.partition(" Bare model:")
        return head, "Bare model:" + bare
    a, h = split(pl["home attacks"]), split(pl["home honest"])
    return {"attacks": {"value": pv["home attacks"], "text": a[0], "bare": a[1], "src": "results/runs/20261110T230149.jsonl"},
            "honest": {"value": pv["home honest"], "text": h[0], "bare": h[1], "src": "results/sweeps/20261110T230155.jsonl"}}


# ---------------------------------------------------------------------------------------------------------------- the theater copy
THEATER_FILES = ("theme.js", "app.css", "theater.css", "ui.js", "theater.js")


def theater_files(r: Reader) -> dict[str, bytes]:
    """A static copy of the Swarm Theater: the app's own files, with the two API calls served from files next to it."""
    st = "python/orderguard_app/static/"
    html = r.text(st + "theater.html")
    html = html.replace('src="/static/', 'src="./').replace('href="/static/', 'href="./')
    html = html.replace('<a class="th-brand" href="/">', '<a class="th-brand" href="../">')
    html = html.replace('<a class="th-link" href="/#arena">Run your own arena</a>', '<a class="th-link" href="../#try">Run it yourself</a>')
    html = html.replace('<script src="./theater.js"></script>', '<script src="./static-shim.js"></script>\n<script src="./theater.js"></script>')
    out = {"index.html": html.encode("utf-8")}
    for f in THEATER_FILES:
        out[f] = r.path(st + f).read_bytes()
    from orderguard_app import theater as TH
    r.path("python/orderguard_app/theater.py")
    out["bench.json"] = (json.dumps(TH.bench_headline(), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    out["timeline.json"] = r.path("results/theater/timeline.json").read_bytes()
    out["static-shim.js"] = SHIM.encode("utf-8")
    return out


SHIM = """/* Static hosting shim for the Swarm Theater (generated by scripts/build_site_data.py; do not edit).
   The app serves the timeline from /api/theater/*; here the same files sit next to this page. Source links that the app serves
   under /evidence/ point at the repository instead. */
(function () {
  var real = window.fetch.bind(window);
  var map = { "/api/theater/timeline": "./timeline.json", "/api/theater/bench": "./bench.json" };
  window.fetch = function (url, init) {
    var u = typeof url === "string" ? url : url.url;
    if (map[u]) return real(map[u]);
    return real(url, init);
  };
  function repoBase() {
    var m = document.querySelector('meta[name="og-repo"]');
    var v = m && m.content ? m.content : "";
    if (!v && /\\.github\\.io$/.test(location.hostname)) {
      var seg = location.pathname.split("/").filter(Boolean)[0];
      if (seg) v = location.hostname.split(".")[0] + "/" + seg;
    }
    return v ? "https://github.com/" + v + "/blob/main/" : "../../";
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    var h = a.getAttribute("href");
    if (h.indexOf("/evidence/") === 0) a.setAttribute("href", repoBase() + h.slice(10));
    else if (h.indexOf("/api/theater/source") === 0) a.setAttribute("href", repoBase() + "data/models/order_risk.json");
    else if (h === "/" || h.indexOf("/#") === 0) a.setAttribute("href", "../" + h.slice(1));
  }, true);
})();
"""


# ---------------------------------------------------------------------------------------------------------------- the build
def build() -> tuple[dict, dict[str, bytes]]:
    r = Reader()
    swarm_doc = swarm(r)
    doc = {
        "schema": SCHEMA,
        "readme": readme_copy(r),
        "product": product_copy(r),
        "policies": policy_packs(r),
        "split": split_example(r),
        "swarm": swarm_doc,
        "bench": bench(r),
        "arena_speed": arena_speed(r),
        "redteam": redteam(r),
        "sim": simulation(r),
        "swarm_results": swarm_results(r),
        "review": review(r),
        "lab": lab(r),
    }
    theater = theater_files(r)
    doc["inputs"] = [{"path": p, "sha256": h} for p, h in sorted(r.used.items())]
    return doc, theater


def serialise(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if site/data.json or site/theater/ is stale; write nothing")
    args = ap.parse_args(argv)
    doc, theater = build()
    text = serialise(doc)
    if args.check:
        stale = [] if OUT.exists() and OUT.read_text(encoding="utf-8") == text else ["site/data.json"]
        for name, body in sorted(theater.items()):
            p = THEATER_DIR / name
            if not p.exists() or p.read_bytes() != body:
                stale.append(f"site/theater/{name}")
        if stale:
            print("stale: " + ", ".join(stale) + ". Run: .venv/bin/python scripts/build_site_data.py", file=sys.stderr)
            return 1
        print("site data is current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    THEATER_DIR.mkdir(parents=True, exist_ok=True)
    for name, body in sorted(theater.items()):
        (THEATER_DIR / name).write_bytes(body)
    print(f"wrote site/data.json ({len(text.encode('utf-8')):,} bytes, {len(doc['inputs'])} inputs) and site/theater/ ({len(theater)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
