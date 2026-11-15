"""Command line interface for ``og-sim``."""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from orderguard_guard import ROOT

from .engine import SIM_DIR, SimConfig, run_scenario
from .scenarios import SCENARIOS


def _json_files(directory: Path) -> list[tuple[Path, dict]]:
    rows = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("schema") == "orderguard-impact-sim/1":
            rows.append((path, data))
    return rows


def _report_html(results: list[tuple[Path, dict]]) -> str:
    points = []
    for _path, doc in results:
        for p in doc.get("frontier", []):
            points.append({"scenario": doc["scenario"]["kind"], **p})
    xmax = max((float(p["honest_throughput_usd"]) for p in points), default=1.0) or 1.0
    ymax = max((float(p["worst_case_loss_usd"]) for p in points), default=1.0) or 1.0
    w, h, left, top, bottom, right = 900, 440, 82, 26, 70, 30
    colors = {"unguarded": "#9b2c2c", "gate_only": "#d97706", "gate_portfolio": "#2563eb", "full": "#15803d",
              "frontier_tight": "#7c3aed", "frontier_loose": "#0f766e", "frontier_open": "#be185d"}
    x0, x1, y0, y1 = left, w - right, top, h - bottom
    marks = []
    for p in points:
        x = x0 + (x1 - x0) * float(p["honest_throughput_usd"]) / xmax
        y = y1 - (y1 - y0) * float(p["worst_case_loss_usd"]) / ymax
        color = colors.get(p["arm"], "#334155")
        title = html.escape(f"{p['scenario']} / {p['arm']}: honest ${p['honest_throughput_usd']:,.0f}, worst loss ${p['worst_case_loss_usd']:,.0f}")
        marks.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}"><title>{title}</title></circle>')
    svg = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Honest executed notional versus worst observed portfolio drawdown">',
           f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="#64748b"/>',
           f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="#64748b"/>']
    for fraction in (0.25, 0.5, 0.75, 1.0):
        xx = x0 + (x1 - x0) * fraction
        yy = y1 - (y1 - y0) * fraction
        svg.append(f'<line x1="{xx:.1f}" y1="{y0}" x2="{xx:.1f}" y2="{y1}" stroke="#e2e8f0"/>')
        svg.append(f'<text x="{xx:.1f}" y="{y1 + 22}" text-anchor="middle">${xmax * fraction / 1000:,.0f}k</text>')
        svg.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x1}" y2="{yy:.1f}" stroke="#e2e8f0"/>')
        svg.append(f'<text x="{x0 - 10}" y="{yy + 4:.1f}" text-anchor="end">${ymax * fraction / 1000:,.0f}k</text>')
    svg.extend(marks)
    svg.extend([f'<text x="{(x0 + x1) / 2}" y="{h - 15}" text-anchor="middle">Honest notional filled (USD, mean across seeds)</text>',
                f'<text transform="translate(18 {(y0 + y1) / 2}) rotate(-90)" text-anchor="middle">Worst observed portfolio drawdown (USD)</text>', '</svg>'])
    legends = " ".join(f'<span><i style="background:{c}"></i>{html.escape(a)}</span>' for a, c in colors.items())
    table_rows = []
    for path, doc in results:
        for arm, m in doc.get("arms", {}).items():
            table_rows.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in (
                doc["scenario"]["kind"], arm, f"{m['honest_filled_usd']:,.0f}", f"{m['bad_dollars_executed']:,.0f}",
                f"{m['honest_loss_usd']:,.0f}", f"{m['peak_drawdown_pct']:.2%}", m["spread_symbols_over_2sigma"],
                m["contagion_half_life_steps"], f"{m['honest_fills_lost_pct_vs_unguarded']:.2%}",
                f"{m['slippage_usd']:,.0f}", f"{m['orders_per_s']:,.0f}", m["auditor_breaches"])) + "</tr>")
    table = "\n".join(table_rows)
    source = ", ".join(html.escape(p.name) for p, _ in results)
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OrderGuard impact simulator</title>
<style>
body{{max-width:1150px;margin:36px auto;padding:0 22px;font:16px/1.5 system-ui,sans-serif;color:#172033;background:#fff}}
h1,h2{{line-height:1.15}} .lede{{max-width:850px;color:#475569}} svg{{width:100%;height:auto;border:1px solid #e2e8f0;border-radius:10px;background:#fff}}
svg text{{font:12px system-ui,sans-serif;fill:#475569}} .legend{{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0 30px}} .legend i{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:8px;border-bottom:1px solid #e2e8f0;text-align:right;white-space:nowrap}} th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
th{{background:#f8fafc;position:sticky;top:0}} .scroller{{overflow:auto}} .note{{color:#64748b;font-size:14px}}
</style>
<h1>Impact-aware market simulation</h1>
<p class="lede">Offline, seeded stylized runs. Every submitted order is decided by the signed-envelope Authority; the risk scorer can only tighten. Points compare honest filled notional with the worst observed portfolio drawdown. Hover over a point for its values.</p>
{''.join(svg)}<div class="legend">{legends}</div>
<h2>Measured runs</h2><div class="scroller"><table><thead><tr><th>Scenario</th><th>Arm</th><th>Honest filled $</th><th>Bad executed $</th><th>Honest loss $</th><th>Index drawdown</th><th>Spread symbols</th><th>Contagion half-life (steps)</th><th>Honest fills lost</th><th>Slippage $</th><th>Orders/s</th><th>Audit breaches</th></tr></thead><tbody>{table}</tbody></table></div>
<p class="note">Limits: the price process is a square-root impact model with decaying impact, correlated Student-t shocks and persistent volatility; it has no order book or execution queue. A short recorded feed seeds volatility/correlation where symbols overlap. Results are simulation evidence, not exchange forecasts. Inputs: {source}.</p>
</html>"""


def build_report(directory: str | Path = SIM_DIR, out: str | Path | None = None) -> Path:
    directory = Path(directory)
    docs = _json_files(directory)
    if not docs:
        raise ValueError(f"no og-sim result JSON files found in {directory}")
    dest = Path(out) if out else directory / "report.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_report_html(docs), encoding="utf-8")
    return dest


def _profiles(profile: str) -> dict:
    return {"quick": {"agents": 10_000, "steps": 64, "replicates": 3, "activity": 0.0005, "attack_activity": 0.04},
            "slow": {"agents": 100_000, "steps": 256, "replicates": 5, "activity": 0.0005, "attack_activity": 0.025},
            # heavy: about 0.64 million proposals per arm per seed from ordinary flow alone (agents x activity x steps),
            # every one decided individually by the real Authority. Sized for a laptop with several cores.
            "heavy": {"agents": 1_000_000, "steps": 64, "replicates": 3, "activity": 0.01, "attack_activity": 0.06}}[profile]


def cmd_run(args) -> int:
    defaults = _profiles(args.profile)
    cfg = SimConfig(agents=args.agents or defaults["agents"], steps=args.steps or defaults["steps"], seed=args.seed,
                    replicates=args.replicates or defaults["replicates"], activity=args.activity if args.activity is not None else defaults["activity"],
                    attack_activity=args.attack_activity if args.attack_activity is not None else defaults["attack_activity"],
                    envelopes=args.envelopes or 0, steps_per_day=args.steps_per_day or 0, risk_model=args.risk_model)
    output = Path(args.out_dir) if args.out_dir else SIM_DIR
    output.mkdir(parents=True, exist_ok=True)
    tmp = None
    if args.no_logs:
        log_dir = None
    elif args.log_dir:
        log_dir = Path(args.log_dir)
    elif args.profile == "heavy":
        # Heavy order logs are hundreds of megabytes: audit them from a scratch copy, keep the digests in the result.
        import tempfile
        tmp = tempfile.TemporaryDirectory(prefix="og-sim-logs-")
        log_dir = Path(tmp.name)
    else:
        log_dir = output / "logs"
    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    failed = False
    for name in scenarios:
        result = run_scenario(cfg, name, log_dir=log_dir, workers=max(1, args.workers))
        if tmp is not None:
            for stale in log_dir.glob("*.jsonl.gz"):
                stale.unlink()
        out = output / f"{name}-k{cfg.agents}-s{cfg.seed}.json"
        out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        valid = all(m["auditor_valid"] for m in result["arms"].values())
        failed |= not valid
        print(f"{name}: {cfg.agents:,} agents, {cfg.steps} steps, {cfg.replicates} seed(s); auditor {'PASS' if valid else 'FAIL'}")
        for arm in ("unguarded", "gate_only", "gate_portfolio", "full"):
            m = result["arms"][arm]
            print(f"  {arm:16s} honest fills {m['honest_fills']:.1f}, bad $ {m['bad_dollars_executed']:,.0f}, drawdown ${m['worst_case_loss_usd']:,.0f}, spread {m['spread_symbols_over_2sigma']:.1f} symbols")
        sc = result["scale"]
        print(f"  scale: {sc['orders_per_arm_mean']:,.0f} orders/arm, {sc['orders_total']:,} total, {sc['wall_s']:,.0f}s on {sc['workers']} worker(s), "
              f"{sc['aggregate_decisions_per_s']:,.0f} decisions/s aggregate")
        print(f"  wrote {out}")
    if not args.no_report:
        report = build_report(output)
        print(f"wrote {report}")
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="og-sim", description="Offline, impact-aware, multi-symbol OrderGuard market simulator")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one scenario or the complete scenario set")
    run.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    run.add_argument("--agents", type=int)
    run.add_argument("--steps", type=int)
    run.add_argument("--seed", type=int, default=7)
    run.add_argument("--replicates", type=int)
    run.add_argument("--profile", choices=("quick", "slow", "heavy"), default="quick")
    run.add_argument("--activity", type=float)
    run.add_argument("--attack-activity", type=float)
    run.add_argument("--envelopes", type=int, default=0)
    run.add_argument("--steps-per-day", type=int, default=0)
    run.add_argument("--risk-model")
    run.add_argument("--out-dir")
    run.add_argument("--workers", type=int, default=1, help="processes for independent (seed, arm) jobs; changes wall time only")
    run.add_argument("--log-dir", help="keep the gzip order logs here (heavy profile otherwise audits scratch logs and discards them)")
    run.add_argument("--no-logs", action="store_true")
    run.add_argument("--no-report", action="store_true")
    report = sub.add_parser("report", help="build the self-contained offline HTML report from results/sim/*.json")
    report.add_argument("--input-dir", default=str(SIM_DIR))
    report.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            if args.agents is not None and args.agents < 1 or args.steps is not None and args.steps < 1:
                parser.error("--agents and --steps must be positive")
            return cmd_run(args)
        dest = build_report(args.input_dir, args.out)
        print(f"wrote {dest}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"og-sim: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

