"""The request-shaped entry points shared by the HTTP API and the MCP tools: validated models in, a plain dict out."""
from __future__ import annotations

from .copilot import review_draft
from .triage import triage

NOTE = "Advice only: it orders the review queue and can add a warning or a hold. It never approves an order, releases a hold or signs or widens a mandate."


class ParentUnavailable(ValueError):
    """The signed parent policy could not be loaded (not configured, or it does not verify)."""


def order_dict(o) -> dict:
    d = o.model_dump(exclude_none=True)
    if d.get("notional_usd") is None:
        d["notional_usd"] = round(d["quantity"] * d.get("trusted_price", d["limit_price"]), 2)
    return d


def triage_request(req) -> dict:
    ctx = None
    if req.context is not None:
        ctx = {"envelope": req.context.envelope.model_dump(exclude_none=True) if req.context.envelope else {},
               "agent_recent": [order_dict(o) for o in req.context.agent_recent], "tape": [order_dict(o) for o in req.context.tape]}
    risk = req.risk.model_dump(exclude_none=True) if req.risk else None
    return {**triage(order_dict(req.held_order), ctx, risk=risk), "note": NOTE}


def draft_request(source: str, draft: dict, purpose: str) -> dict:
    """Raises ParentUnavailable when the parent cannot be loaded and ValueError (naming the purpose) when the purpose is unusable."""
    from orderguard_arena.policy_review import load_parent
    try:
        parent, key, revoked = load_parent(source)
    except ValueError as exc:
        raise ParentUnavailable(str(exc)) from None
    return {**review_draft(parent, draft, purpose, trusted_key=key, revoked=revoked), "note": NOTE}
