"""Advisory lower forecasts for outcomes in the seeded paper simulator."""
from __future__ import annotations

import json
import math
from functools import lru_cache

import numpy as np

from orderguard_guard import ROOT

from .mandate_features import CONTEXT_FEATURES, context_vector, scenario_inputs
from .mandate_model import FEATURES, METRICS, feature_vector, outside_domain, output_units
from .policy_sim import PolicyScenario

ARTIFACT = ROOT / "data" / "models" / "mandate_warning.json"
FORMAT = "orderguard-mandate-warning/1"
RISK_COLUMNS = (0, 2, 3)
RISK_METRICS = tuple(METRICS[i] for i in RISK_COLUMNS)
MODEL_FEATURES = (*FEATURES, *CONTEXT_FEATURES)
OUTCOME_PRECISION = np.array([100, 100_000, 100])


@lru_cache(maxsize=1)
def load_warning_model() -> dict:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    if (not isinstance(artifact, dict) or artifact.get("format") != FORMAT or artifact.get("features") != list(MODEL_FEATURES)
            or artifact.get("metrics") != list(RISK_METRICS) or artifact.get("validated") is not True):
        raise ValueError("Unsupported mandate warning artifact.")
    for key in ("scale", "width_floor"):
        values = artifact[key]
        if len(values) != len(RISK_METRICS) or any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("Invalid mandate warning calibration.")
    if not math.isfinite(artifact["adjustment"]) or artifact["adjustment"] < 0:
        raise ValueError("Invalid mandate warning calibration.")
    quantiles = artifact["quantiles"]
    if len(quantiles) != 2 or any(len(group) != len(RISK_METRICS) for group in quantiles):
        raise ValueError("Invalid mandate warning models.")
    for group in quantiles:
        for model in group:
            if not math.isfinite(model["intercept"]) or not isinstance(model["trees"], list) or not model["trees"]:
                raise ValueError("Invalid mandate warning model.")
    return artifact


def predict_boosted(model: dict, row: list[float]) -> float:
    estimate = model["intercept"]
    for tree in model["trees"]:
        index = 0
        for _ in range(32):
            node = tree[index]
            if len(node) == 1:
                estimate += node[0]
                break
            feature, threshold, left, right = node
            index = left if row[feature] <= threshold else right
        else:
            raise ValueError("Invalid mandate warning tree.")
    return estimate


def calibrated_lower(low, width, adjustment, scale, units):
    corrected = np.maximum(low - adjustment * width, 0)
    with np.errstate(over="raise", invalid="raise"):
        values = np.expm1(corrected) * scale * units
        return np.floor(values * OUTCOME_PRECISION) / OUTCOME_PRECISION


def forecast_lower(artifact: dict, features: list[list[float]], units: np.ndarray) -> np.ndarray:
    first, second = (np.array([[predict_boosted(model, row) for model in models] for row in features])
                     for models in artifact["quantiles"])
    if not (np.isfinite(first).all() and np.isfinite(second).all()):
        raise ValueError("Invalid mandate warning outputs.")
    low = np.maximum(0, np.minimum(first, second))
    width = np.maximum(np.maximum(first, second) - low, artifact["width_floor"])
    return calibrated_lower(low, width, artifact["adjustment"], artifact["scale"], units)


def draft_warnings(drafts: list[dict], scenario: PolicyScenario, limits: dict | None) -> list[dict | None]:
    """Return a named limit warning for eligible drafts with a lower forecast above that limit."""
    warnings = [None] * len(drafts)
    if not limits:
        return warnings
    eligible = [(index, draft) for index, draft in enumerate(drafts) if not outside_domain(draft, scenario)]
    if not eligible:
        return warnings
    try:
        artifact = load_warning_model()
        world = scenario_inputs(scenario)
        features = [feature_vector(draft, scenario) + context_vector(draft, world) for _, draft in eligible]
        units = np.array([output_units(draft, scenario) for _, draft in eligible])[:, RISK_COLUMNS]
        lower = forecast_lower(artifact, features, units)
    except (OSError, ValueError, TypeError, KeyError, IndexError, FloatingPointError):
        return warnings
    for (index, _), estimates in zip(eligible, lower):
        exceeded = [(float(value) / max(limits[metric], 1e-12), metric, float(value))
                    for metric, value in zip(RISK_METRICS, estimates) if metric in limits and value > limits[metric]]
        if exceeded:
            _, metric, lower_estimate = max(exceeded, key=lambda item: item[0])
            warnings[index] = {"metric": metric, "lower_estimate": lower_estimate, "limit": limits[metric]}
    return warnings
