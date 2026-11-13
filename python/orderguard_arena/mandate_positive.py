"""Portable scores for forecasts of useful drafts meeting the operator's limits."""
from __future__ import annotations

import numpy as np

from .mandate_features import RUNAWAY_FEATURES
from .mandate_warning import MODEL_FEATURES, predict_boosted

FORMAT = "orderguard-mandate-positive/1"
POSITIVE_FEATURES = (*MODEL_FEATURES, *RUNAWAY_FEATURES)


def apply_headroom(limits: np.ndarray, active: np.ndarray, headroom: tuple[float, float]) -> np.ndarray:
    """Reduce the entered refusal and hold ceilings in their log-scaled representation."""
    if not any(headroom):
        return limits
    adjusted = limits.copy()
    for column, fraction in enumerate(headroom, 1):
        if fraction:
            enabled = active[:, column]
            adjusted[enabled, column] = np.log1p(np.expm1(limits[enabled, column]) * (1 - fraction))
    return adjusted


def forecast_scores(artifact: dict, features: np.ndarray, limits: np.ndarray, active: np.ndarray) -> np.ndarray:
    """Sum the estimated chances of failing any entered limit or producing no legitimate fills."""
    def failure_probability(model, inputs):
        logits = np.array([predict_boosted(model, row) for row in inputs])
        if not np.isfinite(logits).all():
            raise ValueError("Invalid positive mandate forecast.")
        return np.exp(-np.logaddexp(0, logits))

    loss = failure_probability(artifact["fill"], features.tolist())
    for column, model in enumerate(artifact["limits"]):
        enabled = active[:, column]
        if enabled.any():
            inputs = np.column_stack([features[enabled], limits[enabled, column]])
            loss[enabled] += failure_probability(model, inputs.tolist())
    return -loss
