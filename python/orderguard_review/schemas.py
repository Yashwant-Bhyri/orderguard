"""Request models for the escalation lane, shared by the HTTP API and the MCP tools. Sizes are capped like every other request."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Price = Annotated[float, Field(gt=0, lt=1e9, allow_inf_nan=False)]
MAX_STR, MAX_KEYS, MAX_DEPTH = 2_000, 200, 8


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _bounded(value: Any, what: str, depth: int = 0) -> Any:
    import math
    if depth > MAX_DEPTH:
        raise ValueError(f"{what} is nested deeper than {MAX_DEPTH} levels")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{what} contains a non-finite number (NaN or Infinity)")
    if isinstance(value, str) and len(value) > MAX_STR:
        raise ValueError(f"{what} contains a string longer than {MAX_STR} characters")
    if isinstance(value, dict):
        if len(value) > MAX_KEYS:
            raise ValueError(f"{what} has more than {MAX_KEYS} keys in one object")
        for v in value.values():
            _bounded(v, what, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_KEYS * 10:
            raise ValueError(f"{what} has too many list items")
        for v in value:
            _bounded(v, what, depth + 1)
    return value


Ticker = Annotated[str, Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9._-]+$")]


class OrderLine(_Strict):
    step: Optional[int] = Field(default=None, ge=0, le=10**9)
    agent: Optional[Annotated[str, Field(max_length=40, pattern=r"^[A-Za-z0-9._-]+$")] | int] = None
    ticker: Ticker
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0, lt=1e12, allow_inf_nan=False)
    limit_price: Price
    notional_usd: Optional[float] = Field(default=None, ge=0, le=1e12, allow_inf_nan=False, description="order value at the trusted price; default quantity x trusted price (or limit price)")
    trusted_price: Optional[Price] = None


class ReviewEnvelope(_Strict):
    name: Optional[str] = Field(default=None, max_length=40, pattern=r"^[A-Za-z0-9 ._-]+$")
    per_order: Optional[float] = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    step_up: Optional[float] = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    daily: Optional[float] = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    band_pct: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)


class ReviewContext(_Strict):
    envelope: Optional[ReviewEnvelope] = None
    agent_recent: list[OrderLine] = Field(default_factory=list, max_length=20, description="this agent's most recent orders, oldest first")
    tape: list[OrderLine] = Field(default_factory=list, max_length=50, description="recent orders by all agents on the same ticker, oldest first")


class RiskInput(_Strict):
    risk: float = Field(ge=0, le=1, allow_inf_nan=False, description="the order-risk model's probability that the order is bad")
    action: Optional[Literal["none", "hold", "refuse"]] = None
    reasons: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=10)


class TriageRequest(_Strict):
    held_order: OrderLine
    context: Optional[ReviewContext] = None
    risk: Optional[RiskInput] = Field(default=None, description="the risk model's result for this order, merged into p_bad by noisy-OR")


class DraftReviewRequest(_Strict):
    source: Literal["demo", "configured"] = "demo"
    draft: dict[str, Any]
    purpose: str = Field(min_length=1, max_length=2000, description="what the draft is for, in the author's words")

    @field_validator("draft")
    @classmethod
    def _draft(cls, v):
        return _bounded(v, "draft")

    @field_validator("purpose")
    @classmethod
    def _purpose(cls, v):
        if not v.strip():
            raise ValueError("the purpose must not be blank")
        return v
