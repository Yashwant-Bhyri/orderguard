"""Read a pinned parent policy and review an unsigned draft for paper simulation."""
from __future__ import annotations

import json
import math
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from orderguard_guard import init_cmd
from orderguard_guard.gate import public_key_from_b64, sign_mandate
from orderguard_guard.mandate_fit import check_mandate_fit

from .envelopes import owner_key_from_seed
from .feeds import DEFAULT_SYMBOLS, RecordedFeed
from .mandate_model import estimate_policy
from .mandate_warning import draft_warnings
from .policy_candidates import signed_parent_body
from .policy_sim import PolicyScenario, compare_policies

_DEMO = {"symbols": DEFAULT_SYMBOLS, "sides": ["buy", "sell"], "maxOrderNotionalUsd": 40_000,
         "maxDailyNotionalUsd": 1_200_000, "priceBandPct": 5, "stepUpAboveUsd": 35_000,
         "expiresAt": "2099-01-01T00:00:00Z"}
RISK_LIMITS = {"bad_allowed_usd_per_day": 1e12, "false_refusal_rate": 1.0, "holds_per_day": 1e9}


def load_parent(source: str, directory: Path | None = None) -> tuple:
    if source == "demo":
        key = owner_key_from_seed("review-demo")
        return sign_mandate(_DEMO, key), key.public_key(), ()
    if source != "configured":
        raise ValueError("Choose the demo or configured parent policy.")
    root = directory if directory is not None else init_cmd.default_dir()
    try:
        parent = json.loads((root / init_cmd.MANDATE_FILE).read_text(encoding="utf-8"))
        key = public_key_from_b64((root / init_cmd.PUB_FILE).read_text(encoding="utf-8").strip())
        revoked_path = root / "revoked-mandates.json"
        try:
            revoked = json.loads(revoked_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            revoked = []
        if not isinstance(parent, dict) or not isinstance(revoked, list) or any(not isinstance(x, str) for x in revoked):
            raise ValueError("Invalid parent policy configuration.")
    except (ValueError, OSError, TypeError):
        raise ValueError("Configure a signed mandate and its pinned public key with orderguard init, then check the files with orderguard doctor.") from None
    return parent, key, tuple(revoked)


def _smaller(amount: float, multiplier: str) -> float:
    return max(0.01, float((Decimal(str(amount)) * Decimal(multiplier)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)))


def draft_from_parent(parent: dict) -> dict:
    """An editable starting point with narrower limits and the parent's authority fields."""
    draft = dict(parent)
    draft["maxDailyNotionalUsd"] = _smaller(parent["maxDailyNotionalUsd"], "0.40")
    draft["maxOrderNotionalUsd"] = min(_smaller(parent["maxOrderNotionalUsd"], "0.30"), draft["maxDailyNotionalUsd"])
    draft["priceBandPct"] = round(parent["priceBandPct"] * 0.5, 6)
    if parent.get("stepUpAboveUsd") is not None:
        draft["stepUpAboveUsd"] = min(parent["stepUpAboveUsd"], _smaller(draft["maxOrderNotionalUsd"], "0.70"))
    return draft


def parent_for_review(source: str, directory: Path | None = None) -> dict:
    parent, key, revoked = load_parent(source, directory)
    fit = signed_parent_body(parent, key, revoked)
    body = fit["draft"]
    return {"source": source, "parent_id": fit["parent_id"], "parent": body, "suggested_draft": draft_from_parent(body)}


def validate_limits(limits: dict | None) -> None:
    for name, maximum in (limits or {}).items():
        if name not in RISK_LIMITS or type(maximum) not in (int, float) or not 0 <= maximum <= RISK_LIMITS[name] or not math.isfinite(maximum):
            raise ValueError("Use finite, non-negative risk limits. The false refusal rate is a fraction between zero and one.")


def check_limits(observed: dict, limits: dict) -> dict:
    comparison = {name: {"observed": observed[name], "maximum": maximum, "met": observed[name] <= maximum}
                  for name, maximum in limits.items()}
    return {"met": all(check["met"] for check in comparison.values()), "checks": comparison}


def review_policy(parent: dict, key, revoked: tuple, draft: dict, scenario: PolicyScenario, *, mode: str,
                  feed: RecordedFeed | None = None, limits: dict | None = None) -> dict:
    validate_limits(limits)
    if mode == "simulate":
        result = compare_policies(parent, draft, key, scenario, revoked=revoked, feed=feed)
        simulation = result["simulation"]
        if simulation is not None and limits:
            simulation["limits"] = check_limits(simulation["results"]["draft"], limits)
        return result | {"estimate": None}
    fit = check_mandate_fit(parent, draft, key, revoked=revoked)
    estimate = None
    if fit["fits"] and mode == "estimate":
        if feed is not None:
            estimate = {"status": "outside_training_domain", "fields": ["feed"], "outcomes": None}
        else:
            estimate = estimate_policy(fit["draft"], scenario)
            warning, = draft_warnings([fit["draft"]], scenario, limits)
            if warning:
                estimate["warning"] = warning
    return {"fit": fit, "estimate": estimate, "simulation": None}
