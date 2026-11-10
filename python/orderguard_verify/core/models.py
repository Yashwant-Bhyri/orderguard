"""Domain-neutral data types. A claim is something a text asserts; a verdict says what a trusted source made of it;
a decision says what to do with the request the text was supporting. Nothing here knows what the request is."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

Label = Literal["confirmed", "contradicted", "stale", "unverifiable"]
Action = Literal["pass", "revise", "block", "escalate"]


class Claim(BaseModel):
    """One checkable statement, as read by the extractor (an LLM). `type` and the field meanings belong to the domain pack."""
    id: str
    type: str
    text: str                       # verbatim quote from the source text
    subject: str | None = None      # who or what the claim is about
    attribute: str | None = None    # which measure
    period: str | None = None
    period_end: date | None = None
    value: float | None = None
    unit: str | None = None
    key: bool = False               # the request depends on this claim
    main_reason: bool = False       # this claim is the main reason for the request


class Evidence(BaseModel):
    """One record from a trusted source, quoted back to the human."""
    value: float
    unit: str
    period: str | None = None
    as_of: str
    source: str
    source_url: str
    hash: str


class Verdict(BaseModel):
    claim_id: str
    label: Label
    reason: str
    evidence: list[Evidence] = []
    premature: bool = False         # the source proves the fact did not exist yet at the decision date (a figure from the future)


class Decision(BaseModel):
    """What to do with the text. pass: nothing wrong found. revise: fix the listed claims and resubmit. block: a key claim
    is contradicted. escalate: a human must look (the case cannot be settled by checking)."""
    action: Action
    reasons: list[str]
    alert: bool = False
    fix: list[str] = []             # ids of the claims to fix (revise) or that caused the block
    refresh: list[str] = []         # subjects whose source data should be re-fetched
