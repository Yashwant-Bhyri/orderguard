"""Finance-specific types: the memo being checked, the order an outside agent proposes with it, and the mandate."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,9}")


def normalise_ticker(raw: str) -> str | None:
    """Trim, NFKC, uppercase, and accept only plain ASCII symbols (so a Cyrillic or full-width look-alike is refused, not guessed at).
    Returns None when the text is not a plain symbol."""
    t = unicodedata.normalize("NFKC", str(raw or "")).strip().upper()
    return t if t.isascii() and SYMBOL.fullmatch(t) else None


class Memo(BaseModel):
    """What a research text is about and when it was written. Nothing here is trusted."""
    ticker: str
    as_of: date | None = None  # the date the text was written; defaults to today. Lets us replay history.

    @field_validator("ticker")
    @classmethod
    def _plain_symbol(cls, v: str) -> str:
        t = normalise_ticker(v)
        if t is None:
            raise ValueError("ticker must be a plain ASCII symbol such as AAPL")
        return t


class Order(Memo):
    """The order an outside agent proposes with its memo. Nothing here is trusted."""
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    limit_price: float | None = None


class AgentOrder(BaseModel):
    """What an outside agent may say about an order. The decision date is deliberately not a field: the server sets it."""
    ticker: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    limit_price: float | None = None


class Mandate(BaseModel):
    """What the human signed. The gateway enforces it; the agent never sees it."""
    allowed_tickers: list[str]
    allowed_sides: list[str] = ["buy", "sell"]
    max_order_shares: int = 1000
    max_order_notional: float = 100_000.0
    price_band_pct: float = 5.0   # the order's limit price must be within this many percent of the TRUSTED quote
    signed_by: str = "human"
