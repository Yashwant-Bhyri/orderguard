"""Prioritize contained drafts and check them on the same paper market."""
from __future__ import annotations

import math
from dataclasses import asdict

from .feeds import DEFAULT_SYMBOLS, RecordedFeed
from .mandate_model import METRICS, feature_vector, forest_predict, load_model, outside_domain, output_units
from .mandate_warning import draft_warnings
from .policy_candidates import policy_candidates
from .policy_review import check_limits, validate_limits
from .policy_sim import PolicyScenario, policy_metrics, shared_policy_feed, simulate_policy


def point_risk(body: dict, scenario: PolicyScenario, limits: dict, trees: list) -> float:
    prediction = forest_predict(trees, feature_vector(body, scenario))
    units = output_units(body, scenario)
    return max(estimate / max(limits[name] / unit, 1e-12)
               for name, estimate, unit in zip(METRICS, prediction, units) if name in limits)


def prioritize(candidates: list, scenario: PolicyScenario, limits: dict, *, recorded: bool) -> tuple[list, dict]:
    if not limits or not candidates:
        return candidates, {"method": "generated_order", "reason": "no_limits" if not limits else "no_candidates"}
    if recorded or any(outside_domain(c["draft"], scenario) for c in candidates):
        return candidates, {"method": "generated_order", "reason": "outside_training_domain"}
    try:
        trees = load_model()["trees"]
        scores = [point_risk(c["draft"], scenario, limits, trees) for c in candidates]
        if any(not math.isfinite(score) or score < 0 for score in scores):
            raise ValueError("Invalid model output.")
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return candidates, {"method": "generated_order", "reason": "model_unavailable"}
    order = sorted(range(len(scores)), key=scores.__getitem__)
    return [candidates[i] for i in order], {"method": "point_forecast"}


def search_policies(parent: dict, key, revoked: tuple, scenario: PolicyScenario, *, mode: str = "simulate",
                    limits: dict | None = None, feed: RecordedFeed | None = None) -> dict:
    """Compare the drafts and identify the matching option with the highest positive legitimate fill value."""
    if mode not in ("rank", "simulate"):
        raise ValueError("Choose rank or simulate.")
    validate_limits(limits)
    limits = limits or {}
    generated = policy_candidates(parent, key, revoked)
    candidates, ranking = prioritize(generated["candidates"], scenario, limits, recorded=feed is not None)
    symbols = feed.symbols if feed is not None else DEFAULT_SYMBOLS
    unobserved = sorted(set(candidates[0]["draft"]["symbols"]) - set(symbols)) if candidates else []
    ordered = [candidate | {"rank": rank, "simulation": None} for rank, candidate in enumerate(candidates, 1)]
    if mode == "rank" and feed is None:
        warnings = draft_warnings([candidate["draft"] for candidate in ordered], scenario, limits)
        for candidate, warning in zip(ordered, warnings):
            if warning:
                candidate["warning"] = warning
    matches = []
    simulated = 0
    if mode == "simulate" and ordered:
        market = shared_policy_feed(scenario, feed)
        for candidate in ordered:
            metrics = policy_metrics(simulate_policy(candidate["draft"], scenario, feed=market))
            checks = check_limits(metrics, limits) if limits else None
            candidate["simulation"] = {"metrics": metrics, "limits": checks}
            simulated += 1
            if checks is not None and checks["met"]:
                matches.append((metrics["legitimate_filled_usd_per_day"], metrics["legitimate_allowed_usd_per_day"],
                                -metrics["bad_allowed_usd_per_day"], -candidate["rank"]))
    best = max(matches, default=None)
    selected = -best[-1] if best is not None and best[0] > 0 else None
    return {"parent_id": generated["parent_id"], "candidates": ordered, "ranking": ranking, "simulated": simulated,
            "selected_rank": selected, "match_count": len(matches) if limits and mode == "simulate" else None,
            "limits": limits, "mode": mode, "unobserved_symbols": unobserved,
            "scenario": asdict(scenario) | {"steps": len(feed) if feed is not None else scenario.steps},
            "feed": feed.path.name if feed is not None else "synthetic"}
