"""An independent auditor for the benchmark: it replays the broker's fills (the truth, not any system's view) and checks the signed
hard limits after every fill, at that step's trusted marks. It shares no code with the admission path on purpose: the scenario
arithmetic is restated here in a few lines.

A breach is counted when a fill makes a measure worse AND leaves it above its limit, the same rule the predicates use, so a book
pushed over a cap by prices alone is not counted against any system."""
from __future__ import annotations

from .world import SECTORS, SYMBOLS

AUDIT_SCENARIOS = {
    "market_down_20": {"*": -0.20},
    "tech_down_30": {"*": -0.05, "sector:tech": -0.30},
    "crypto_down_50": {"sector:crypto": -0.50},
    "rates_shock": {"*": -0.08, "sector:financials": -0.15, "sector:energy": 0.05},
    "ai_theme_down_25": {"NVDA": -0.25, "MSFT": -0.25, "GOOGL": -0.25, "AMZN": -0.25, "TSLA": -0.25, "QQQ": -0.2, "AAPL": -0.15},
}


def _shock(shocks: dict, sym: str) -> float:
    if sym in shocks:
        return shocks[sym]
    return shocks.get(f"sector:{SECTORS[sym]}", shocks.get("*", 0.0))


def measures(pos: dict[str, float], marks: dict[str, float]) -> dict[str, float]:
    usd = {s: pos.get(s, 0.0) * marks[s] for s in SYMBOLS}
    out = {f"issuer:{s}": abs(v) for s, v in usd.items()}
    for sec in set(SECTORS.values()):
        out[f"sector:{sec}"] = sum(abs(v) for s, v in usd.items() if SECTORS[s] == sec)
    out["gross"] = sum(abs(v) for v in usd.values())
    for name, sh in AUDIT_SCENARIOS.items():
        out[f"scenario:{name}"] = -sum(v * _shock(sh, s) for s, v in usd.items())
    out["short"] = max(0.0, -min(usd.values()))
    return out


def limits(cfg) -> dict[str, float]:
    lim = {f"issuer:{s}": cfg.issuer_w * cfg.capital for s in SYMBOLS}
    lim.update({f"sector:{sec}": cfg.sector_w * cfg.capital for sec in set(SECTORS.values())})
    lim["gross"] = cfg.capital
    lim.update({f"scenario:{n}": cfg.scenario_loss for n in AUDIT_SCENARIOS})
    lim["short"] = 0.0
    return lim


def audit(fills: list[dict], marks_by_step: list[dict], cfg) -> dict:
    lim = limits(cfg)
    pos: dict[str, float] = {}
    breaches, worst, kinds = 0, 0.0, {}
    for f in sorted(fills, key=lambda x: (x["step"], x["seq"])):
        marks = marks_by_step[f["step"]]
        before = measures(pos, marks)
        pos[f["symbol"]] = pos.get(f["symbol"], 0.0) + (1 if f["side"] == "buy" else -1) * f["qty"]
        after = measures(pos, marks)
        for k, v in after.items():
            if v > lim[k] + 1e-6 and v > before[k] + 1e-6:
                breaches += 1
                kind = k.split(":")[0]
                kinds[kind] = kinds.get(kind, 0) + 1
                worst = max(worst, v - lim[k])
    return {"hard_limit_breaches": breaches, "max_breach_excess_usd": worst, "breaches_by_kind": kinds}
