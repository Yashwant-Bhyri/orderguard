"""Check whether an unsigned draft stays within a human's signed mandate.

This checks one draft against one parent, without signing or activating it.
It does not allocate a shared parent budget across multiple drafts.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from decimal import Decimal
from typing import Iterable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .gate import Mandate, MandateInvalid, public_key_to_b64

_FIELDS = frozenset(Mandate.__dataclass_fields__)
_SIGNATURE_FIELDS = {"signature", "signerPublicKey"}
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,31}")
_MAX_MONEY = 1_000_000_000_000  # leaves room for integer-cent arithmetic across Python and TypeScript


class PolicyInputError(ValueError):
    def __init__(self, field: str, reason: str):
        self.field = field
        super().__init__(reason)


def _number(value, field: str, *, maximum=_MAX_MONEY, cents=False, zero=False) -> Decimal:
    if type(value) not in (int, float) or abs(value) > maximum or not math.isfinite(value):
        raise PolicyInputError(field, "Use a finite number within the supported range.")
    n = Decimal(str(value))
    if n < 0 or (n == 0 and not zero):
        raise PolicyInputError(field, "Use a non-negative number." if zero else "Use a positive number.")
    if cents and n * 100 != int(n * 100):
        raise PolicyInputError(field, "Use an amount in whole cents.")
    return n


def _choices(value, field: str, predicate) -> set[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 100 or any(
        not isinstance(x, str) or not predicate(x) for x in value
    ):
        raise PolicyInputError(field, "Provide a non-empty list of canonical values.")
    if len(set(value)) != len(value):
        raise PolicyInputError(field, "Each value must appear only once.")
    return set(value)


def _expiry(value) -> dt.datetime:
    if not isinstance(value, str) or "T" not in value:
        raise PolicyInputError("expiresAt", "Use an ISO timestamp with a timezone.")
    try:
        expiry = dt.datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
    except ValueError:
        raise PolicyInputError("expiresAt", "Use an ISO timestamp with a timezone.") from None
    if expiry.utcoffset() is None:
        raise PolicyInputError("expiresAt", "Use an ISO timestamp with a timezone.")
    return expiry


def _parse(raw: dict, *, signed: bool) -> tuple[Mandate, dt.datetime]:
    if not isinstance(raw, dict):
        raise PolicyInputError("mandate", "Use a mandate object.")
    allowed = _FIELDS if signed else _FIELDS - _SIGNATURE_FIELDS
    if raw.keys() - allowed:
        raise PolicyInputError("mandate", "Unsupported mandate fields. A draft must be unsigned.")
    symbols = _choices(raw.get("symbols"), "symbols", _SYMBOL.fullmatch)
    _choices(raw.get("sides"), "sides", {"buy", "sell"}.__contains__)
    per_order = _number(raw.get("maxOrderNotionalUsd"), "maxOrderNotionalUsd", cents=True)
    daily = _number(raw.get("maxDailyNotionalUsd"), "maxDailyNotionalUsd", cents=True)
    if per_order > daily:
        raise PolicyInputError("maxOrderNotionalUsd", "The per-order cap must not exceed the daily cap.")
    _number(raw.get("priceBandPct"), "priceBandPct", maximum=100, zero=True)
    if raw.get("stepUpAboveUsd") is not None:
        _number(raw["stepUpAboveUsd"], "stepUpAboveUsd", cents=True, zero=True)
    for name in ("maxSymbolDailyNotionalUsd", "maxPositionUsd"):
        if raw.get(name) is not None:
            _number(raw[name], name, cents=True)
    if raw.get("maxOrdersPerDay") is not None:
        n = raw["maxOrdersPerDay"]
        if type(n) is not int or not 1 <= n <= 1_000_000_000:
            raise PolicyInputError("maxOrdersPerDay", "Use a positive whole number.")
    refs = raw.get("referencePrices", {})
    if not isinstance(refs, dict) or refs.keys() - symbols:
        raise PolicyInputError("referencePrices", "Reference prices must be keyed by an allowed symbol.")
    for value in refs.values():
        _number(value, "referencePrices")
    expiry = _expiry(raw.get("expiresAt"))
    if signed:
        for field in _SIGNATURE_FIELDS:
            if raw.get(field) is not None and not isinstance(raw[field], str):
                raise PolicyInputError(field, "Use a base64 string.")
    return Mandate.from_dict(raw), expiry


def _automatic_cap(mandate: Mandate) -> float:
    if mandate.stepUpAboveUsd is None:
        return mandate.maxOrderNotionalUsd
    return min(mandate.maxOrderNotionalUsd, mandate.stepUpAboveUsd)


def _tighter(child, parent) -> bool:
    """An optional limit: the parent has none -> anything goes; the parent has one -> the child must have one and not exceed it."""
    return parent is None or (child is not None and child <= parent)


def check_mandate_fit(parent: dict, draft: dict, trusted_key: Ed25519PublicKey, *, now: dt.datetime | None = None,
                      revoked: Iterable[str] = ()) -> dict:
    """Return reasons why the draft cannot be used under this parent, or its canonical unsigned body."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("the evaluation clock must have a timezone")

    def invalid(code: str, field: str, reason: str, parent_id: str | None = None) -> dict:
        return {"fits": False, "parent_id": parent_id, "draft": None,
                "violations": [{"code": code, "field": field, "reason": reason}]}

    try:
        maximum, expires = _parse(parent, signed=True)
        if maximum.signerPublicKey is not None and maximum.signerPublicKey != public_key_to_b64(trusted_key):
            raise MandateInvalid("The parent identifies a different signer than the pinned owner key.")
        maximum.verify(trusted_key, now=now, revoked=revoked)
    except PolicyInputError as exc:
        return invalid("invalid_parent", exc.field, str(exc))
    except (MandateInvalid, TypeError, ValueError, OverflowError) as exc:
        return invalid("untrusted_parent", "parent", str(exc) if isinstance(exc, MandateInvalid) else "The parent signature is invalid.")

    try:
        candidate, end = _parse(draft, signed=False)
    except PolicyInputError as exc:
        return invalid("invalid_draft", exc.field, str(exc), maximum.id)

    conditions = (
        ("symbols", "symbols", set(candidate.symbols) <= set(maximum.symbols), "The draft adds symbols outside the parent allow-list."),
        ("sides", "sides", set(candidate.sides) <= set(maximum.sides), "The draft adds an order side outside the parent grant."),
        ("order_cap", "maxOrderNotionalUsd", candidate.maxOrderNotionalUsd <= maximum.maxOrderNotionalUsd, "The draft raises the per-order cap."),
        ("daily_cap", "maxDailyNotionalUsd", candidate.maxDailyNotionalUsd <= maximum.maxDailyNotionalUsd, "The draft raises the daily cap."),
        ("price_band", "priceBandPct", candidate.priceBandPct <= maximum.priceBandPct, "The draft widens the price band."),
        ("step_up", "stepUpAboveUsd", _automatic_cap(candidate) <= _automatic_cap(maximum), "The draft permits larger orders without human approval."),
        ("symbol_daily_cap", "maxSymbolDailyNotionalUsd", _tighter(candidate.maxSymbolDailyNotionalUsd, maximum.maxSymbolDailyNotionalUsd),
         "The draft raises or drops the parent's per-symbol daily cap."),
        ("position_cap", "maxPositionUsd", _tighter(candidate.maxPositionUsd, maximum.maxPositionUsd),
         "The draft raises or drops the parent's position cap."),
        ("order_count_cap", "maxOrdersPerDay", _tighter(candidate.maxOrdersPerDay, maximum.maxOrdersPerDay),
         "The draft raises or drops the parent's orders-per-day cap."),
        ("expiry", "expiresAt", now < end <= expires, "The draft must be active and expire no later than the parent."),
        ("reference_prices", "referencePrices",
         candidate.referencePrices == {s: maximum.referencePrices[s] for s in candidate.symbols if s in maximum.referencePrices},
         "The draft must preserve the parent's reference prices for its allowed symbols."),
    )
    violations = [{"code": code, "field": field, "reason": why} for code, field, ok, why in conditions if not ok]
    return {"fits": not violations, "parent_id": maximum.id,
            "draft": candidate.to_dict(with_signature=False) if not violations else None, "violations": violations}
