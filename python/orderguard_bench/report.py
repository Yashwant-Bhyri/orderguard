"""Self-contained HTML report (inline CSS and SVG, no network, light and dark) and markdown tables, from results/bench/*.json."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

ORDER = ("full", "quick", "tiny")


def load(out_dir: Path) -> tuple[list[dict], dict | None]:
    runs = []
    for name in ORDER:
        p = out_dir / f"{name}.json"
        if p.exists():
            runs.append(json.loads(p.read_text()))
    hp = out_dir / "http.json"
    return runs, (json.loads(hp.read_text()) if hp.exists() else None)


def e(x) -> str:
    return html.escape(str(x))


def n0(x) -> str:
    return "-" if x is None else f"{x:,.0f}"


def us(x) -> str:
    if x is None:
        return "-"
    return f"{x:,.1f}" if x < 100 else f"{x:,.0f}"


def usd(x) -> str:
    return "-" if x is None else (f"${x / 1e6:,.2f}M" if abs(x) >= 1e6 else f"${x:,.0f}")


def pc(x, nd=2) -> str:
    return "-" if x is None else f"{100 * x:.{nd}f}%"


def badge(ok: bool, yes="pass", no="FAIL") -> str:
    return f'<span class="badge {"good" if ok else "bad"}">{"&#10003; " + yes if ok else "&#10007; " + no}</span>'


# ---- charts ---------------------------------------------------------------------------------------------------------------------------
def bars_grouped(groups: list[str], series: list[tuple[str, list[float | None]]], *, unit: str, width: int = 640, height: int = 240) -> str:
    """Grouped vertical bars (one colour slot per series, fixed order), native tooltips, value labels on the tallest bar per series."""
    pad_l, pad_b, pad_t = 64, 28, 12
    vmax = max((v for _, vals in series for v in vals if v), default=1) * 1.12
    vmax = _nice(vmax)
    pw, ph = width - pad_l - 8, height - pad_b - pad_t
    gw = pw / max(len(groups), 1)
    bw = min(34, (gw - 16) / max(len(series), 1) - 2)
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart" aria-label="grouped bar chart">']
    for i in range(5):
        v = vmax * i / 4
        y = pad_t + ph - ph * i / 4
        out.append(f'<line x1="{pad_l}" x2="{width - 8}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{pad_l - 6}" y="{y + 4:.1f}" class="tick" text-anchor="end">{_short(v)}</text>')
    for gi, g in enumerate(groups):
        x0 = pad_l + gi * gw + (gw - (bw + 2) * len(series)) / 2
        for si, (name, vals) in enumerate(series):
            v = vals[gi]
            if not v:
                continue
            h = ph * v / vmax
            x = x0 + si * (bw + 2)
            y = pad_t + ph - h
            r = min(4, bw / 2, h)
            out.append(f'<path d="M{x:.1f},{pad_t + ph:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} H{x + bw - r:.1f} Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} V{pad_t + ph:.1f} Z" '
                       f'class="s{si + 1} mark"><title>{e(name)}, {e(g)}: {n0(v)} {e(unit)}</title></path>')
        out.append(f'<text x="{pad_l + gi * gw + gw / 2:.1f}" y="{height - 8}" class="tick" text-anchor="middle">{e(g)}</text>')
    out.append(f'<line x1="{pad_l}" x2="{width - 8}" y1="{pad_t + ph}" y2="{pad_t + ph}" class="axis"/></svg>')
    legend = "".join(f'<span class="key"><i class="s{i + 1}"></i>{e(n)}</span>' for i, (n, _) in enumerate(series))
    return f'<div class="legend">{legend}</div>' + "".join(out)


def stacked_h(rows: list[tuple[str, list[float]]], names: list[str], *, width: int = 640) -> str:
    """Horizontal 100% stacked bars (share of each family's proposed dollars), 2px surface gaps, native tooltips."""
    lab, bh, gap = 150, 18, 10
    height = len(rows) * (bh + gap) + 8
    pw = width - lab - 60
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart" aria-label="stacked bars">']
    for ri, (label, vals) in enumerate(rows):
        y = 4 + ri * (bh + gap)
        tot = sum(vals) or 1
        x = lab
        out.append(f'<text x="{lab - 8}" y="{y + bh - 5}" class="tick" text-anchor="end">{e(label)}</text>')
        for si, v in enumerate(vals):
            w = pw * v / tot
            if w <= 0:
                continue
            out.append(f'<rect x="{x:.1f}" y="{y}" width="{max(w - 2, 0.5):.1f}" height="{bh}" rx="2" class="s{si + 1} mark">'
                       f'<title>{e(label)}: {e(names[si])} {usd(v)} ({pc(v / tot, 1)})</title></rect>')
            x += w
        out.append(f'<text x="{lab + pw + 6}" y="{y + bh - 5}" class="tick">{usd(tot)}</text>')
    out.append("</svg>")
    legend = "".join(f'<span class="key"><i class="s{i + 1}"></i>{e(n)}</span>' for i, n in enumerate(names))
    return f'<div class="legend">{legend}</div>' + "".join(out)


def latency_h(rows: list[tuple[str, dict]], *, width: int = 640) -> str:
    """Per stage: a bar to p99 on a log scale with a tick at p50 and a dot at p99.9."""
    lab, bh, gap = 190, 14, 12
    rows = [(n, d) for n, d in rows if d and d.get("n")]
    height = len(rows) * (bh + gap) + 30
    pw = width - lab - 16
    lo, hi = 0.1, max([d.get("p999", 1) for _, d in rows] + [10])
    hi = 10 ** math.ceil(math.log10(hi))
    X = lambda v: lab + pw * (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart" aria-label="latency per stage, log scale">']
    d = lo
    while d <= hi * 1.001:
        out.append(f'<line x1="{X(d):.1f}" x2="{X(d):.1f}" y1="0" y2="{height - 22}" class="grid"/>'
                   f'<text x="{X(d):.1f}" y="{height - 6}" class="tick" text-anchor="middle">{_short(d)} µs</text>')
        d *= 10
    for i, (name, s) in enumerate(rows):
        y = 4 + i * (bh + gap)
        out.append(f'<text x="{lab - 8}" y="{y + bh - 3}" class="tick" text-anchor="end">{e(name)}</text>')
        out.append(f'<rect x="{lab}" y="{y + 3}" width="{X(s["p99"]) - lab:.1f}" height="{bh - 6}" rx="2" class="s1 mark soft">'
                   f'<title>{e(name)}: p50 {us(s["p50"])} µs, p99 {us(s["p99"])} µs, p99.9 {us(s["p999"])} µs</title></rect>')
        out.append(f'<line x1="{X(s["p50"]):.1f}" x2="{X(s["p50"]):.1f}" y1="{y}" y2="{y + bh}" class="p50"/>')
        out.append(f'<circle cx="{X(s["p999"]):.1f}" cy="{y + bh / 2}" r="4" class="s2 mark ring"><title>p99.9 {us(s["p999"])} µs</title></circle>')
    out.append("</svg>")
    return ('<div class="legend"><span class="key"><i class="s1"></i>bar to p99</span><span class="key"><i class="tickkey"></i>p50</span>'
            '<span class="key"><i class="s2 dot"></i>p99.9</span></div>' + "".join(out))


def _nice(v: float) -> float:
    if v <= 0:
        return 1
    m = 10 ** math.floor(math.log10(v))
    for s in (1, 2, 2.5, 5, 10):
        if v <= s * m:
            return s * m
    return 10 * m


def _short(v: float) -> str:
    if v >= 1e6:
        return f"{v / 1e6:g}M"
    if v >= 1e3:
        return f"{v / 1e3:g}k"
    return f"{v:g}"


def table(head: list[str], rows: list[list], cls: str = "") -> str:
    th = "".join(f"<th>{h}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


# ---- one profile -----------------------------------------------------------------------------------------------------------------------
def section(r: dict, http: dict | None) -> str:
    p, m, v = r["profile"], r["machine"], r.get("verdict", {})
    gate = [x for x in r["runs"] if not x["risk"]]
    risk = [x for x in r["runs"] if x["risk"]]
    ns = sorted({x["workers"] for x in r["runs"]})
    total_aud = sum(a["totals"]["decisions"] for a in r["audits"])
    breaches = sum(a["breach_total"] for a in r["audits"])
    best = max(gate, key=lambda x: x["decisions_per_s"])
    n1 = next(x for x in gate if x["workers"] == 1)
    muts = r["mutations"]
    caught = sum(1 for x in muts if x["caught"])
    rx = r["receiver"]
    eco = r["economics"]
    tiles = [
        (n0(total_aud), "decisions audited", f"{len(r['audits'])} runs, {r['workload']['envelopes']:,} envelopes"),
        (str(breaches), "guarantee breaches", "in every intact run, Python and receiver"),
        (f"{caught}/{len(muts)}", "mutations caught", "each deliberately broken guarantee was flagged"),
        (n0(best["decisions_per_s"]), f"decisions/s at N={best['workers']}", f"{n0(n1['decisions_per_s'])}/s on one core"),
        (us(n1["latency_us"]["authorize"]["p99"]) + " µs", "p99 authorize (Python)", f"p50 {us(n1['latency_us']['authorize']['p50'])} µs"),
        (pc(eco["bad"]["stopped_share"], 1), "bad dollars stopped", f"gate + risk; gate alone {pc(eco['bad']['stopped_share_gate_only'], 1)}"),
    ]
    out = [f'<section id="{e(p["name"])}"><h2>Profile <code>{e(p["name"])}</code> <small>{p["agents"]:,} agents · {r["workload"]["envelopes"]:,} envelopes · '
           f'{r["workload"]["items"]:,} orders · {p["steps"]:,} steps ({p["steps"] / p["steps_per_day"]:g} days)</small></h2>',
           f'<div class="verdict {"good" if v.get("pass") else "bad"}">{"&#10003;" if v.get("pass") else "&#10007;"} {e(v.get("summary", ""))}</div>',
           '<div class="tiles">' + "".join(f'<div class="tile"><b>{a}</b><span>{e(b)}</span><small>{e(c)}</small></div>' for a, b, c in tiles) + "</div>"]
    out.append("<h3>What the auditor proved</h3><p>An independent auditor recomputed every run from the decision logs, the signed mandates and the raw venue "
               "quotes (never the system's own counters). The strict <code>OrderGate</code> re-evaluated every allow and every step-up hold from the signed mandate.</p>")
    out.append(table(["check", "result"], [[e(k), badge(ok)] for k, ok in v.get("checks", {}).items()]))
    rows = []
    for a in r["audits"]:
        c = a["checked"]
        rows.append([f"{'gate + risk' if a['risk'] else 'gate'}, N={a['workers']}", n0(a["totals"]["decisions"]), n0(c.get("reproduced_by_order_gate")),
                     n0(c.get("replays_identical")), n0(c.get("key_conflicts_refused")), n0(c.get("chain_links")), n0(c.get("signature")),
                     badge(a["breach_total"] == 0, "0", str(a["breach_total"])), f"<code>{a['gate_digest'][:12]}</code>"])
    out.append(table(["run", "decisions", "allows/holds reproduced by OrderGate", "duplicate deliveries replayed", "key conflicts refused", "chain links",
                      "signatures", "breaches", "gate digest"], rows))
    out.append("<h3>Throughput and scaling</h3><p>Shards own whole owners (their envelopes, budgets, portfolio state, idempotency keys and pinned agents); "
               "nothing mutable is shared between processes. Wall clock from a common start barrier to the last worker's end.</p>")
    out.append(bars_grouped([f"N={n}" for n in ns], [("gate only", [next((x["decisions_per_s"] for x in gate if x["workers"] == n), None) for n in ns]),
                                                     ("gate + order-risk model", [next((x["decisions_per_s"] for x in risk if x["workers"] == n), None) for n in ns])],
                            unit="decisions/s"))
    out.append(table(["run", "workers", "decisions", "wall s", "decisions/s", "per worker /s (min-max)", "authorize p50 / p99 / p99.9 µs", "pipeline p50 / p99 / p99.9 µs"],
                     [[("gate + risk" if x["risk"] else "gate"), x["workers"], n0(x["decisions"]), f"{x['wall_s']:.2f}", n0(x["decisions_per_s"]),
                       f"{n0(min(w['decisions_per_s'] for w in x['per_worker']))}-{n0(max(w['decisions_per_s'] for w in x['per_worker']))}",
                       " / ".join(us(x["latency_us"]["authorize"][k]) for k in ("p50", "p99", "p999")),
                       " / ".join(us(x["latency_us"]["pipeline"][k]) for k in ("p50", "p99", "p999"))] for x in r["runs"]]))
    sp = r["stages_python"]
    py_rows = [("verify mandate (on load)", sp["verify_mandate"]), ("idempotency + routing", sp["idempotency_and_routing"]), ("gate (L5 rules)", sp["gate"]),
               ("portfolio limits", sp["portfolio_limits"]), ("reservation", sp["reservation"]), ("risk score", sp["risk_score"]), ("log append (sha256)", sp["log_append"])]
    ds = rx.get("durable_profile", {}).get("stages_us", {})
    fs = rx.get("fast_profile", {}).get("stages_us", {})
    rx_rows = [("shape + normalise", fs.get("shape")), ("idempotency lookup", fs.get("idempotency_lookup")), ("scope at trusted price", fs.get("scope_at_trusted_price")),
               ("budget query", fs.get("budget")), ("portfolio queries", fs.get("portfolio")), ("insert + hash chain", fs.get("insert_and_chain")),
               ("commit tx (fast)", fs.get("commit")), ("commit tx (durable, fsync)", ds.get("commit"))]
    out.append("<h3>Latency per stage</h3><p>Each stage's real function wrapped by a timer on a separate pass (wrapping adds a fraction of a microsecond per call).</p>")
    out.append("<h4>Python authority</h4>" + latency_h(py_rows))
    out.append("<h4>TypeScript receiver (in-process)</h4>" + latency_h(rx_rows))
    out.append(table(["stage", "n", "p50 µs", "p99 µs", "p99.9 µs"], [[e(k), n0(s.get("n")), us(s.get("p50")), us(s.get("p99")), us(s.get("p999"))]
                                                                   for k, s in py_rows + [("receiver: " + a, b) for a, b in rx_rows] if s and s.get("n")]))
    out.append("<h3>The receiver: the durable effect boundary</h3>")
    out.append(table(["mode", "orders", "decisions/s (1 process)", "propose p50 / p99 / p99.9 µs", "agree with Python (first deliveries)", "ledger audit"],
                     [[mode, n0(rx[mode]["orders"]), n0(rx[mode]["decisions_per_s"]), " / ".join(us(rx[mode]["latency_us"][k]) for k in ("p50", "p99", "p999")),
                       f"{rx[mode]['agreement']['first']['agree']:,} / {rx[mode]['agreement']['first']['agree'] + rx[mode]['agreement']['first']['disagree']:,}",
                       badge(rx["audit"][mode]["breach_total"] == 0, f"0 breaches, {rx['audit'][mode]['ledger_rows']:,} rows", f"{rx['audit'][mode]['breach_total']} breaches")]
                      for mode in ("fast", "durable")]))
    g = r.get("receiver_growth")
    if g:
        out.append("<h4>Latency as one day's ledger grows (one envelope, fast storage)</h4>")
        out.append(table(["rows already in the ledger", "p50 µs (no portfolio limits)", "p99 µs", "p50 µs (portfolio limits on)", "p99 µs"],
                         [[n0(a["rows_before"]), us(a["p50"]), us(a["p99"]), us(b["p50"]), us(b["p99"])]
                          for a, b in zip(g["without_portfolio_limits"], g["with_portfolio_limits"])]))
    vo = rx.get("verify_on_open", {})
    out.append(f'<p class="note">Fast: <code>synchronous=OFF</code>, journal in memory (throw-away ledgers). Durable: WAL, <code>synchronous=FULL</code>. '
               f'Verify on open re-hashed {n0(vo.get("events"))} events in {vo.get("open_and_verify_ms")} ms ({us((vo.get("us_per_event") or {}).get("p50"))} µs/event median).</p>')
    if http and not http.get("skipped"):
        out.append(table(["HTTP bridge", "requests", "concurrency", "req/s", "p50 / p99 / p99.9 µs", "integrity", "double executions"],
                         [["loopback", n0(http["requests"]), http["concurrency"], n0(http["requests_per_s"]), " / ".join(us(http["latency_us"][k]) for k in ("p50", "p99", "p999")),
                           badge(bool(http["ledger_integrity"])), str(http["double_executions"])]]))
    else:
        reason = (http or r.get("http") or {}).get("reason", "not run")
        out.append(f'<p class="note"><b>HTTP bridge:</b> skipped ({e(reason)}). Run it outside the sandbox with <code>.venv/bin/og-bench http --profile {e(p["name"])}</code>.</p>')
    out.append("<h3>Races, crashes and mutations</h3>")
    tr = r["thread_race"]
    race_rows = [[f"{t['threads']} threads, one envelope{' (lock off)' if t['lock_off'] else ''}", n0(t["attempts"]), f"{t['allowed_fresh']} (entitled {t['entitled_fills']})",
                  badge(t["audit"]["breach_total"] == 0, "0", str(t["audit"]["breach_total"]))] for t in tr]
    for x in r["process_race"]:
        race_rows.append([f"{x['processes']} processes, one SQLite ledger, {'same keys' if x['shared_keys'] else 'one budget'}{' (' + x['mutation'] + ')' if x['mutation'] else ''}",
                          n0(x["attempts"]), f"{x['ledger_rows']} rows" + (f" (entitled {x['entitled_fills']})" if x["entitled_fills"] else f" ({x['distinct_keys']} distinct keys)"),
                          badge(x["audit"]["breach_total"] == 0, "0", str(x["audit"]["breach_total"]))])
    out.append(table(["race", "attempts", "effects", "breaches found"], race_rows))
    f = r["fault"]
    out.append(f'<p>Kill/restart: a durable receiver on envelope <code>{e(f["envelope"])}</code> was killed with SIGKILL {f["kills"]} times at random moments and restarted; '
               f'{f["opens_verified"]}/{f["opens"]} opens verified the hash chain before serving; {f["commits_landed_without_ack"]} commits had landed without the client hearing the '
               f'acknowledgement and were re-sent ({f["resent_replays"]} answered as replays); {f["acked_effect_mismatches"]} acknowledged effects changed; '
               f'ledger audit {badge(f["audit"]["breach_total"] == 0, "0 breaches", str(f["audit"]["breach_total"]) + " breaches")}.</p>')
    out.append(table(["layer", "mutation", "auditor"], [[e(x["layer"]), f"<code>{e(x['mutation'])}</code>", badge(x["caught"], "caught: " + ", ".join(f"{k} {v}" for k, v in x["breaches"].items()), "MISSED")]
                                                         for x in muts]))
    out.append("<h3>Orders exactly at the limits</h3>")
    out.append(table(["envelope", "probe", "required", "Python", "OrderGate", "receiver", ""], [[e(x["envelope"]), e(x["probe"]), x["expected"], x["python"], x["order_gate"], x["receiver"], badge(x["ok"])]
                                                                                             for x in r["edges"]["rows"]]))
    out.append("<h3>Economic outcome</h3><p>From the single-process gate + risk run (one global scorer, shipped model and thresholds). First deliveries only; "
               "notional at the trusted price. Bursts, probes and key conflicts are system traffic and are excluded.</p>")
    fams = sorted(eco["by_family"].items(), key=lambda kv: -kv[1]["proposed_usd"])
    out.append(stacked_h([(k, [v["gate_refused_usd"] + v["gate_held_usd"], v["risk_held_usd"] + v["risk_refused_usd"], v["let_through_usd"]]) for k, v in fams],
                         ["stopped by the gate", "stopped by the risk model", "let through"]))
    out.append(table(["family", "proposals", "proposed", "gate stopped", "risk stopped", "let through", "stopped"],
                     [[e(k), n0(v["proposals"]), usd(v["proposed_usd"]), usd(v["gate_refused_usd"] + v["gate_held_usd"]), usd(v["risk_held_usd"] + v["risk_refused_usd"]),
                       usd(v["let_through_usd"]), pc(v["stopped_share"], 1)] for k, v in fams] +
                     [["<b>all bad</b>", "", usd(eco["bad"]["proposed_usd"]), usd(eco["bad"]["stopped_by_gate_usd"]), usd(eco["bad"]["stopped_by_risk_usd"]),
                       usd(eco["bad"]["let_through_usd"]), pc(eco["bad"]["stopped_share"], 1)]]))
    h = eco["honest"]
    out.append(table(["honest orders", "allowed", "held (step-up / news / risk)", "refused (gate / risk)", "holds per day", "human review load"],
                     [[n0(h["proposals"]), pc(h["allowed_share"]), f"{h['held_gate_stepup']:,} / {h['held_gate_l7']:,} / {h['held_risk']:,}",
                       f"{h['refused_gate']:,} / {h['refused_risk']:,}", n0(h["holds_per_day"]),
                       f"{eco['review_load']['holds_per_day']:,} holds/day ({eco['review_load']['holds_per_day_per_1000_agents']:,} per 1,000 agents)"]]))
    out.append(f'<p class="note">Machine: {e(m["cpu"])}, {m["logical_cpus"]} logical CPUs, {e(m.get("memory_gib"))} GiB, {e(m["os"])}; CPython {e(m["python"])}, '
               f'numpy {e(m["numpy"])}, Node {e(m["node"])}, SQLite {e(m["python_sqlite"])} (Python). Run took {r.get("total_s")} s, started {e(r.get("started_utc"))}.</p></section>')
    return "".join(out)


CSS = """
:root{--surface-0:#f4f4f2;--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;--muted:#8a8984;--grid:#e6e5e1;--axis:#b9b8b2;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--good:#0ca30c;--critical:#d03b3b;--good-bg:#e9f6e9;--bad-bg:#fbeaea;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface-0:#111110;--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--muted:#8f8e86;
--grid:#2c2c2a;--axis:#4a4a46;--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--good:#0ca30c;--critical:#e66767;--good-bg:#132713;--bad-bg:#2d1515;color-scheme:dark}}
:root[data-theme="dark"]{--surface-0:#111110;--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--muted:#8f8e86;--grid:#2c2c2a;--axis:#4a4a46;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--good:#0ca30c;--critical:#e66767;--good-bg:#132713;--bad-bg:#2d1515;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--surface-0);color:var(--text-primary);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 64px}h1{font-size:28px;margin:8px 0 4px}h2{font-size:21px;margin:40px 0 12px;border-top:1px solid var(--grid);padding-top:24px}
h2 small{display:block;font-size:13px;color:var(--text-secondary);font-weight:400}h3{font-size:17px;margin:28px 0 8px}h4{font-size:14px;margin:16px 0 4px;color:var(--text-secondary)}
p{color:var(--text-secondary);max-width:860px}code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace}.lede{font-size:16px}
nav a{color:var(--series-1);margin-right:14px}.verdict{padding:12px 14px;border-radius:8px;font-weight:600;margin:8px 0 16px}.verdict.good{background:var(--good-bg)}.verdict.bad{background:var(--bad-bg)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.tile{background:var(--surface-1);border:1px solid var(--grid);border-radius:10px;padding:12px}
.tile b{display:block;font-size:24px;font-variant-numeric:tabular-nums}.tile span{display:block;font-size:13px}.tile small{color:var(--muted);font-size:12px}
.tw{overflow-x:auto;margin:8px 0 12px;background:var(--surface-1);border:1px solid var(--grid);border-radius:10px}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--grid);white-space:nowrap}th{color:var(--text-secondary);font-weight:600}td{font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}.badge{font-weight:600;font-size:12px}.badge.good{color:var(--good)}.badge.bad{color:var(--critical)}
.chart{width:100%;height:auto;background:var(--surface-1);border:1px solid var(--grid);border-radius:10px;margin:4px 0 8px}.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--axis)}
.tick{fill:var(--text-secondary);font-size:11px}.mark{stroke:var(--surface-1);stroke-width:0}.mark:hover{opacity:.82}.s1{fill:var(--series-1);background:var(--series-1)}
.s2{fill:var(--series-2);background:var(--series-2)}.s3{fill:var(--series-3);background:var(--series-3)}.soft{opacity:.85}.ring{stroke:var(--surface-1);stroke-width:2}
.p50{stroke:var(--text-primary);stroke-width:2}.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-secondary);margin-top:8px}
.key i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}.key i.dot{border-radius:50%}.key i.tickkey{width:2px;background:var(--text-primary)}
.note{font-size:13px}details{margin-top:24px}summary{cursor:pointer;color:var(--series-1);font-weight:600}
"""


def at_scale(partial: dict) -> str:
    g = partial["gate_runs"]
    out = [f'<section id="full"><h2>At scale: {partial["agents"]:,} agents, {partial["envelopes"]:,} envelopes <small>{e(partial["status"])}</small></h2>',
           bars_grouped([f"N={x['workers']}" for x in g], [("gate only", [x["decisions_per_s"] for x in g])], unit="decisions/s"),
           table(["workers", "decisions", "wall s", "decisions/s", "audit breaches", "gate digest"],
                 [[x["workers"], n0(x["decisions"]), f"{x['wall_s']:.2f}", n0(x["decisions_per_s"]), badge(x["audit_breaches"] == 0, "0", str(x["audit_breaches"])),
                   f"<code>{e(x['gate_digest_prefix'])}</code>"] for x in g])]
    sc = partial["risk_scorer_scaling"]
    out.append("<h3>Where one order-risk scorer stops scaling</h3><p>" + e(sc["finding"]) + "</p>")
    out.append(table(["share of the swarm in one scorer", "agents", "decisions so far", "co-activity edges", "µs per decision"],
                     [[x["share_of_swarm"], n0(x["agents_seen"]), n0(x["decisions_done"]), n0(x["edges"]), us(x["us_per_decision"])] for x in sc["points"]]))
    return "".join(out) + "</section>"


def page(runs: list[dict], http: dict | None, partial: dict | None = None) -> str:
    head = runs[0] if runs else None
    body = ["<main><h1>OrderGuard Bench</h1>",
            '<p class="lede">Does the pre-trade authority keep its guarantees at exchange scale? A swarm of simulated agents trades real recorded Binance price '
            "paths and a seeded synthetic book under thousands of human-signed envelopes, mixed with every attack family and with traffic aimed at the system "
            "itself (retries, duplicate deliveries, tampered retries, replayed and forged mandates, budget races across threads and processes, a receiver killed "
            "mid-commit). An independent auditor recomputes every run. Method and limits: <code>docs/BENCH.md</code>.</p>"]
    if not runs:
        body.append("<p>No results yet: run <code>og-bench run --profile quick</code>.</p>")
    else:
        body.append("<nav>" + "".join(f'<a href="#{e(r["profile"]["name"])}">{e(r["profile"]["name"])}</a>' for r in runs)
                    + ('<a href="#full">100,000 agents</a>' if partial else "") + "</nav>")
        body.append(section(head, http))
        if partial:
            body.append(at_scale(partial))
        for r in runs[1:]:
            body.append(f'<details><summary>Profile {e(r["profile"]["name"])}</summary>{section(r, http)}</details>')
    body.append('<p class="note">Simulated agents and fills; no order was sent anywhere. Throughput is CPython and Node on one laptop: production '
                "pre-trade risk gateways at venues are usually described in single-digit microseconds or less, on purpose-built native or hardware paths. "
                "This bench shows what this implementation does and proves, not that it matches those.</p></main>")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>OrderGuard Bench</title><style>{CSS}</style></head><body>" + "".join(body) + "</body></html>")


def summary(runs: list[dict], partial: dict | None) -> dict:
    """The headline the web theater reads. Every field in `headline` describes ONE complete, audited run (the largest one available);
    `at_scale` adds the 100,000-agent gate runs when only those finished."""
    out: dict = {"schema": "orderguard-bench-summary/1"}
    if runs:
        r = runs[0]
        gate = [x for x in r["runs"] if not x["risk"]]
        best = max(gate, key=lambda x: x["decisions_per_s"])
        one = next(x for x in gate if x["workers"] == 1)
        out["headline"] = {
            "profile": r["profile"]["name"], "agents": r["profile"]["agents"], "envelopes": r["workload"]["envelopes"],
            "decisions_per_s": best["decisions_per_s"], "workers": best["workers"], "decisions_per_s_one_core": one["decisions_per_s"],
            "p99_us": one["latency_us"]["authorize"]["p99"], "p50_us": one["latency_us"]["authorize"]["p50"],
            "breaches": sum(a["breach_total"] for a in r["audits"]) + sum(v["breach_total"] for v in r["receiver"]["audit"].values()) + r["fault"]["audit"]["breach_total"],
            "decisions_audited": sum(a["totals"]["decisions"] for a in r["audits"]),
            "mutations_caught": sum(1 for m in r["mutations"] if m["caught"]), "mutations": len(r["mutations"]),
            "bad_dollars_stopped_share": r["economics"]["bad"]["stopped_share"], "verdict": r.get("verdict", {}).get("summary"),
            "p99_note": "Python Authority.authorize, one process; latency of the decision only (not the risk model or the receiver)",
            "machine": r["machine"]["cpu"], "started_utc": r.get("started_utc")}
    if partial:
        best = max(partial["gate_runs"], key=lambda x: x["decisions_per_s"])
        out["at_scale"] = {"profile": "full (gate runs only)", "agents": partial["agents"], "envelopes": partial["envelopes"],
                           "decisions": best["decisions"], "decisions_per_s": best["decisions_per_s"], "workers": best["workers"],
                           "breaches": sum(x["audit_breaches"] for x in partial["gate_runs"]),
                           "identical_decisions_at_every_worker_count": partial["gate_digest_identical_across_worker_counts"]}
    return out


def write(out_dir: Path) -> Path:
    runs, http = load(out_dir)
    pp = out_dir / "full-partial.json"
    partial = json.loads(pp.read_text()) if pp.exists() else None
    p = out_dir / "report.html"
    p.write_text(page(runs, http, partial), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary(runs, partial), indent=1, sort_keys=True))
    return p


def markdown(out_dir: Path) -> str:
    runs, http = load(out_dir)
    lines = []
    for r in runs:
        nm = r["profile"]["name"]
        lines.append(f"### Profile `{nm}`\n")
        lines.append("| run | workers | decisions | wall s | decisions/s | authorize p50 / p99 / p99.9 µs | pipeline p50 / p99 / p99.9 µs | audit breaches |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for x, a in zip(r["runs"], r["audits"]):
            lines.append(f"| {'gate + risk' if x['risk'] else 'gate'} | {x['workers']} | {x['decisions']:,} | {x['wall_s']:.2f} | {x['decisions_per_s']:,} | "
                         + " / ".join(us(x["latency_us"]["authorize"][k]) for k in ("p50", "p99", "p999")) + " | "
                         + " / ".join(us(x["latency_us"]["pipeline"][k]) for k in ("p50", "p99", "p999")) + f" | {a['breach_total']} |")
        sp = r["stages_python"]
        lines.append("\n| Python stage | p50 µs | p99 µs | p99.9 µs |\n|---|---|---|---|")
        for k in ("verify_mandate", "verify_per_order_if_reverified", "idempotency_and_routing", "gate", "portfolio_limits", "reservation", "authorize_total", "risk_score", "log_append"):
            s = sp[k]
            lines.append(f"| {k.replace('_', ' ')} | {us(s.get('p50'))} | {us(s.get('p99'))} | {us(s.get('p999'))} |")
        rx = r["receiver"]
        lines.append("\n| receiver stage (in-process) | fast p50 / p99 / p99.9 µs | durable p50 / p99 / p99.9 µs |\n|---|---|---|")
        for k in ("shape", "idempotency_lookup", "scope_at_trusted_price", "budget", "portfolio", "insert_and_chain", "commit", "tx_begin_commit_fsync", "total"):
            f_, d_ = rx["fast_profile"]["stages_us"].get(k, {}), rx["durable_profile"]["stages_us"].get(k, {})
            lines.append(f"| {k.replace('_', ' ')} | " + " / ".join(us(f_.get(q)) for q in ("p50", "p99", "p999")) + " | " + " / ".join(us(d_.get(q)) for q in ("p50", "p99", "p999")) + " |")
        lines.append("\n| receiver mode | orders | decisions/s | propose p50 / p99 / p99.9 µs | agree with Python (first deliveries) | ledger audit breaches |\n|---|---|---|---|---|---|")
        for mode in ("fast", "durable"):
            x = rx[mode]
            fa = x["agreement"]["first"]
            lines.append(f"| {mode} | {x['orders']:,} | {x['decisions_per_s']:,} | " + " / ".join(us(x["latency_us"][q]) for q in ("p50", "p99", "p999"))
                         + f" | {fa['agree']:,} of {fa['agree'] + fa['disagree']:,} | {rx['audit'][mode]['breach_total']} |")
        g = r.get("receiver_growth")
        if g:
            lines.append("\n| rows already in the day's ledger | p50 / p99 µs (no portfolio limits) | p50 / p99 µs (portfolio limits on) |\n|---|---|---|")
            for a, b in zip(g["without_portfolio_limits"], g["with_portfolio_limits"]):
                lines.append(f"| {a['rows_before']:,} | {us(a['p50'])} / {us(a['p99'])} | {us(b['p50'])} / {us(b['p99'])} |")
        lines.append("\n| mutation | layer | auditor found |\n|---|---|---|")
        for x in r["mutations"]:
            lines.append(f"| `{x['mutation']}` | {x['layer']} | {'caught: ' + ', '.join(f'{k} {v}' for k, v in x['breaches'].items()) if x['caught'] else 'MISSED'} |")
        eco = r["economics"]
        lines.append("\n| family | proposals | proposed | stopped by gate | stopped by risk | let through | stopped |\n|---|---|---|---|---|---|---|")
        for k, v in sorted(eco["by_family"].items(), key=lambda kv: -kv[1]["proposed_usd"]):
            lines.append(f"| {k} | {v['proposals']:,} | {usd(v['proposed_usd'])} | {usd(v['gate_refused_usd'] + v['gate_held_usd'])} | {usd(v['risk_held_usd'] + v['risk_refused_usd'])} | "
                         f"{usd(v['let_through_usd'])} | {pc(v['stopped_share'], 1)} |")
        b = eco["bad"]
        lines.append(f"| **all bad** | | {usd(b['proposed_usd'])} | {usd(b['stopped_by_gate_usd'])} | {usd(b['stopped_by_risk_usd'])} | {usd(b['let_through_usd'])} | {pc(b['stopped_share'], 1)} |")
        lines.append("")
    if http and not http.get("skipped"):
        lines.append(f"HTTP: {http['requests_per_s']:,} req/s, p50 {us(http['latency_us']['p50'])} µs, p99 {us(http['latency_us']['p99'])} µs")
    return "\n".join(lines)
