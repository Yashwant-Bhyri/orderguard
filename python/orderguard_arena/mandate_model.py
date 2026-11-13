"""Local estimates of synthetic swarm outcomes from an exported tree ensemble."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from orderguard_guard import ROOT

from .feeds import DEFAULT_SYMBOLS
from .policy_sim import REGIMES, PolicyScenario

ARTIFACT = ROOT / "data" / "models" / "mandate_risk.json"
FORMAT = "orderguard-mandate-risk/1"
METRICS = ("bad_allowed_usd_per_day", "legitimate_allowed_usd_per_day", "false_refusal_rate", "holds_per_day")
FEATURES = ("log_per_order", "log_daily", "price_band", "automatic_share", "log_agents", "log_steps",
            "log_daily_per_agent_tick", "log_daily_over_order", "symbol_count", "buy", "sell",
            *[f"symbol_{s}" for s in DEFAULT_SYMBOLS], *[f"regime_{r}" for r in REGIMES])
DOMAIN = {"agents": (50, 1_000), "steps": (120, 900), "maxOrderNotionalUsd": (200, 50_000),
          "maxDailyNotionalUsd": (500, 5_000_000), "priceBandPct": (0.05, 8)}


def feature_vector(body: dict, scenario: PolicyScenario) -> list[float]:
    per = body["maxOrderNotionalUsd"]
    daily = body["maxDailyNotionalUsd"]
    step = body.get("stepUpAboveUsd")
    automatic = per if step is None else min(step, per)
    symbols, sides = set(body["symbols"]), set(body["sides"])
    return [math.log(per), math.log(daily), body["priceBandPct"], automatic / per, math.log(scenario.agents),
            math.log(scenario.steps), math.log(daily / (scenario.agents * max(scenario.steps // 4, 1))), math.log(daily / per),
            float(len(symbols)), float("buy" in sides), float("sell" in sides),
            *[float(s in symbols) for s in DEFAULT_SYMBOLS], *[float(r == scenario.regime) for r in REGIMES]]


def output_units(body: dict, scenario: PolicyScenario) -> tuple[float, ...]:
    daily = body["maxDailyNotionalUsd"]
    return float(daily), float(daily), 1.0, float(scenario.agents)


def outside_domain(body: dict, scenario: PolicyScenario) -> list[str]:
    values = {**body, "agents": scenario.agents, "steps": scenario.steps}
    fields = [k for k, (lo, hi) in DOMAIN.items() if not lo <= values[k] <= hi]
    if set(body["symbols"]) - set(DEFAULT_SYMBOLS):
        fields.append("symbols")
    if scenario.regime not in REGIMES:
        fields.append("regime")
    return fields


@lru_cache(maxsize=1)
def load_model() -> dict:
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("format") != FORMAT or data.get("features") != list(FEATURES)
            or data.get("metrics") != list(METRICS) or not isinstance(data.get("trees"), list) or not data["trees"]):
        raise ValueError("Unsupported mandate model artifact.")
    return data


def forest_predict(trees: list, features: list[float]) -> list[float]:
    sums = [0.0] * len(METRICS)
    for tree in trees:
        idx = 0
        for _ in range(32):
            node = tree[idx]
            if len(node) == 1:
                for j, x in enumerate(node[0]):
                    sums[j] += x
                break
            f, value, left, right = node
            idx = left if features[f] <= value else right
        else:
            raise ValueError("Invalid mandate model tree.")
    return [x / len(trees) for x in sums]


def estimate_policy(body: dict, scenario: PolicyScenario) -> dict:
    """Give advisory estimates for a verified draft in the training domain."""
    fields = outside_domain(body, scenario)
    if fields:
        return {"status": "outside_training_domain", "fields": fields, "outcomes": None}
    try:
        data = load_model()
        prediction = forest_predict(data["trees"], feature_vector(body, scenario))
        bounds = data["interval_half_widths"]
        target, evidence = data["coverage_target"], data["evidence"]
        if len(bounds) != len(METRICS) or not all(math.isfinite(x) and x >= 0 for x in [*prediction, *bounds]):
            raise ValueError("Invalid mandate model outputs.")
        if type(target) not in (int, float) or not 0 < target <= 1 or not isinstance(evidence, dict):
            raise ValueError("Invalid mandate model evidence.")
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return {"status": "model_unavailable", "outcomes": None}

    result = {}
    for i, (metric, units, point, half_width) in enumerate(zip(METRICS, output_units(body, scenario), prediction, bounds)):
        maximum = float("inf") if metric == "holds_per_day" else 1.0
        lower, estimate, upper = (round(min(maximum, max(0, x)) * units, 5 if i == 2 else 2)
                                  for x in (point - half_width, point, point + half_width))
        result[metric] = {"estimate": estimate, "lower": lower, "upper": upper}
    return {"status": "validated_for_triage" if data.get("validated_for_triage") else "experimental",
            "coverage_target": target, "outcomes": result, "evidence": evidence,
            "scope": "Synthetic swarm estimates. Confirm the draft with an exact simulation before signing."}
