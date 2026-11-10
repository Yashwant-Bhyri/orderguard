"""Router: which trusted source can settle which kind of claim. Code only.

Rumours and sentiment have no source on purpose. A rumour can only be confirmed by the event itself,
and an opinion is not a fact, so both come back 'unverifiable' rather than being guessed at.
"""
from __future__ import annotations

from ..core.models import Claim

ROUTES = {
    "fundamental": "edgar",   # SEC filings in the truth store
    "price": "quotes",        # quote snapshots in the truth store
    "rumour": None,
    "sentiment": None,
}

NO_SOURCE_REASON = {
    "rumour": "a rumour: no trusted source can confirm an unreported event",
    "sentiment": "an opinion or forecast: not a checkable fact",
}


def route(claim: Claim) -> str | None:
    return ROUTES[claim.type]
