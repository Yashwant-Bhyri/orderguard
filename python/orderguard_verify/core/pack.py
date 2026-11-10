"""The seam between the domain-neutral core and a domain pack (finance is the first).

The core reads a text, extracts claims, asks the pack to verify each one against its trusted sources, decides
pass / revise / block / escalate for the text, shows a card and runs the eval. Everything that knows what a source or a
limit actually is lives in the pack, and so does the map from a decision to an action in the world."""
from __future__ import annotations

from datetime import date
from typing import Any, Callable, Protocol

from pydantic import BaseModel

from .models import Claim, Decision, Verdict


class Pack(Protocol):
    name: str
    Context: type[BaseModel]                # what the text is about and when it was written (checked on arrival)
    Proposal: type[BaseModel]               # a Context plus a request the text supports (an outside agent's ask)
    hard_types: frozenset[str]              # claim types a source can settle; one confirmed is required to pass
    never_key_types: frozenset[str]         # claim types (opinions) that can never be decisive on their own
    unconfirmable_types: frozenset[str]     # claim types no source can confirm (rumours)
    form_fields: str                        # HTML inputs for the review page's paste box (names = Context fields)
    form_hint: str                          # one line under the paste box

    def extraction_prompt(self, text: str, context: Any) -> tuple[str, str]: ...
    def claim_from_raw(self, raw: dict, index: int, context: Any) -> Claim: ...   # raises on an invalid claim
    def describe(self, context: Any) -> str: ...                                  # one line for cards and logs
    def decision_date(self, context: Any) -> date: ...                            # what "known at the time" means
    def prepare(self, context: Any) -> None: ...                                  # make sure the sources are loaded; raises SourceUnavailable
    def verify(self, claim: Claim, context: Any, ask: Callable) -> Verdict: ...
    def refresh(self, subject: str) -> None: ...                                  # re-fetch stale source data
    def violations(self, proposal: Any) -> list[str]: ...                         # outside what the human signed
    def step(self, decision: Decision, violations: list[str]) -> tuple[str, list[str]]: ...  # (status, extra reasons)
    def register_tools(self, mcp: Any, gateway: Any, call: Callable) -> None: ...  # the MCP tools this domain exposes


class SourceUnavailable(RuntimeError):
    """The trusted sources for this text cannot be reached or do not cover it. The result is escalate, never a silent pass."""
