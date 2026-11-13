"""Generate alternative unsigned mandates from the same signed authority."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_DOWN

from orderguard_guard.mandate_fit import check_mandate_fit

_PROFILES = (
    ("Near parent limits", "0.85", "0.90", "0.90", "1"),
    ("Lower daily spend", "0.85", "0.55", "1", "1"),
    ("Smaller orders", "0.55", "0.85", "1", "1"),
    ("Tighter price band", "0.85", "0.85", "0.50", "1"),
    ("Earlier approval", "0.80", "0.80", "1", "0.70"),
    ("Balanced limits", "0.55", "0.65", "0.70", "0.90"),
    ("Conservative limits", "0.30", "0.40", "0.50", "0.70"),
    ("Small daily budget", "0.20", "0.20", "0.35", "0.50"),
)


class ParentPolicyError(ValueError):
    """The configured parent cannot currently authorize a draft."""


def _scaled(amount: float, factor: str, minimum: float = 0.01) -> float:
    return max(minimum, float((Decimal(str(amount)) * Decimal(factor)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)))


def signed_parent_body(parent: dict, key, revoked=(), *, now: dt.datetime | None = None) -> dict:
    unsigned = {k: v for k, v in parent.items() if k not in ("signature", "signerPublicKey")}
    fit = check_mandate_fit(parent, unsigned, key, revoked=revoked, now=now)
    if not fit["fits"]:
        raise ParentPolicyError(fit["violations"][0]["reason"])
    return fit


def policy_candidates(parent: dict, key, revoked=(), *, now: dt.datetime | None = None) -> dict:
    """Return distinct, verified drafts which preserve the parent's symbols and expiry."""
    now = now or dt.datetime.now(dt.timezone.utc)
    authority = signed_parent_body(parent, key, revoked, now=now)
    body = authority["draft"]
    step_up = body.get("stepUpAboveUsd")
    seen, candidates = [body], []
    for name, order_factor, daily_factor, band_factor, automatic_factor in _PROFILES:
        daily = _scaled(body["maxDailyNotionalUsd"], daily_factor)
        per_order = min(daily, _scaled(body["maxOrderNotionalUsd"], order_factor))
        automatic = per_order if step_up is None else min(step_up, per_order)
        draft = body | {"maxOrderNotionalUsd": per_order, "maxDailyNotionalUsd": daily,
                        "priceBandPct": min(body["priceBandPct"], round(body["priceBandPct"] * float(band_factor), 6)),
                        "stepUpAboveUsd": None if step_up is None and automatic_factor == "1" else
                        _scaled(automatic, automatic_factor, minimum=0.0)}
        fit = check_mandate_fit(parent, draft, key, revoked=revoked, now=now)
        if not fit["fits"]:
            raise ValueError(fit["violations"][0]["reason"])
        if fit["draft"] not in seen:
            seen.append(fit["draft"])
            candidates.append({"name": name, "draft": fit["draft"]})
    return {"parent_id": authority["parent_id"], "candidates": candidates}
