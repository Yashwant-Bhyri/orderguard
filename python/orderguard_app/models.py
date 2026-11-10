"""Request models. Sizes are capped so one request cannot make the service do unbounded work."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

MAX_TEXT = 100_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScreenRequest(_Strict):
    text: str = Field(max_length=MAX_TEXT)
    kind: Literal["doc", "web", "feed", "tool"] = "tool"


class MandateUpload(_Strict):
    mandate: dict[str, Any]
    public_key: Optional[str] = Field(default=None, max_length=256, description="base64 Ed25519 public key; without it only integrity is checked")


class CheckOrderRequest(_Strict):
    order: dict[str, Any]
    mandate: Optional[MandateUpload] = None
    prices: Optional[dict[str, float]] = Field(default=None, description="trusted prices, e.g. {'AAPL': 222.7}; default: the demo market")
    as_of: str = Field(default="2024-11-06", pattern=r"^\d{4}-\d{2}-\d{2}$")
    daily_total_usd: float = Field(default=0.0, ge=0)
    require_figures: bool = False


class TriggerGraphRequest(_Strict):
    rules: Optional[list[dict[str, Any]]] = Field(default=None, max_length=50, description="rule specs; default: the three standing rules")
    events: Optional[list[dict[str, Any]]] = Field(default=None, max_length=2000)
    preset: Optional[Literal["honest", "single_venue_crash", "real_crash", "takeover_echo"]] = None
    quarantined_sources: list[str] = Field(default_factory=list, max_length=50)
    blast_source: Optional[str] = Field(default=None, max_length=80)
    lies: list[float] = Field(default_factory=lambda: [-10.0, -25.0, -45.0, -60.0], max_length=12)


class ScenarioRequest(_Strict):
    scenario: str = Field(max_length=80)
    arm: Optional[Literal["naive", "gate_only", "full"]] = None
