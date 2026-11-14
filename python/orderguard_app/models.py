"""Request models. Sizes are capped so one request cannot make the service do unbounded work."""
from __future__ import annotations

import math
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TEXT = 100_000
MAX_JSON_DEPTH, MAX_JSON_KEYS, MAX_JSON_STR = 8, 200, 2_000

Price = Annotated[float, Field(gt=0, lt=1e9, allow_inf_nan=False)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _bounded(value: Any, what: str, depth: int = 0) -> Any:
    """Free-form JSON the services pass on to the guard: finite numbers only, bounded depth, width and string length."""
    if depth > MAX_JSON_DEPTH:
        raise ValueError(f"{what} is nested deeper than {MAX_JSON_DEPTH} levels")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{what} contains a non-finite number (NaN or Infinity)")
    if isinstance(value, str) and len(value) > MAX_JSON_STR:
        raise ValueError(f"{what} contains a string longer than {MAX_JSON_STR} characters")
    if isinstance(value, dict):
        if len(value) > MAX_JSON_KEYS:
            raise ValueError(f"{what} has more than {MAX_JSON_KEYS} keys in one object")
        for v in value.values():
            _bounded(v, what, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_JSON_KEYS * 10:
            raise ValueError(f"{what} has too many list items")
        for v in value:
            _bounded(v, what, depth + 1)
    return value


class ScreenRequest(_Strict):
    text: str = Field(max_length=MAX_TEXT)
    kind: Literal["doc", "web", "feed", "tool"] = "tool"


class MandateUpload(_Strict):
    mandate: dict[str, Any]

    @field_validator("mandate")
    @classmethod
    def _m(cls, v):
        return _bounded(v, "mandate")

    public_key: Optional[str] = Field(default=None, max_length=256, description="base64 Ed25519 public key; without it only integrity is checked")


class CheckOrderRequest(_Strict):
    order: dict[str, Any]
    mandate: Optional[MandateUpload] = None
    prices: Optional[dict[Annotated[str, Field(max_length=16)], Price]] = Field(
        default=None, max_length=500, description="trusted prices, e.g. {'AAPL': 222.7}; default: the demo market")
    as_of: str = Field(default="2024-11-06", pattern=r"^\d{4}-\d{2}-\d{2}$")
    daily_total_usd: float = Field(default=0.0, ge=0, le=1e12)
    require_figures: bool = False

    @field_validator("order")
    @classmethod
    def _o(cls, v):
        return _bounded(v, "order")

    @field_validator("as_of")
    @classmethod
    def _d(cls, v):
        import datetime as dt
        try:
            dt.date.fromisoformat(v)
        except ValueError:
            raise ValueError("as_of must be a real calendar date, YYYY-MM-DD") from None
        return v


class TriggerGraphRequest(_Strict):
    rules: Optional[list[dict[str, Any]]] = Field(default=None, max_length=50, description="rule specs; default: the three standing rules")
    events: Optional[list[dict[str, Any]]] = Field(default=None, max_length=2000)

    @field_validator("rules", "events")
    @classmethod
    def _free(cls, v):
        return _bounded(v, "rules/events") if v is not None else v

    preset: Optional[Literal["honest", "single_venue_crash", "real_crash", "takeover_echo"]] = None
    quarantined_sources: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=50)
    blast_source: Optional[str] = Field(default=None, max_length=80)
    lies: list[Annotated[float, Field(ge=-100, le=1000, allow_inf_nan=False)]] = Field(
        default_factory=lambda: [-10.0, -25.0, -45.0, -60.0], max_length=12, description="percent moves a lying source reports (-100..1000)")


class ScenarioRequest(_Strict):
    scenario: str = Field(min_length=1, max_length=80)
    arm: Optional[Literal["naive", "gate_only", "full"]] = None


# ---- escalation lane: the request models live with the package so the MCP tools use the same ones ------------------------------------
from orderguard_review.schemas import DraftReviewRequest, OrderLine, ReviewContext, ReviewEnvelope, RiskInput, TriageRequest  # noqa: E402,F401
