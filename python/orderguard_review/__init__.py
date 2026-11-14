"""The escalation lane: what happens after code or the risk model holds an order, and before a human signs a new mandate.

Principle: code is the only thing that can say yes. A typed decision model (TypeSafe Jev) returns probabilities and its output here
is advice that can only (a) order the human review queue, (b) add a hold or a warning, or (c) be shown to a human. It never approves,
releases a hold, or signs or widens anything, and any failure of the model degrades to "no advice" with the deterministic path
unchanged.

    triage(held_order, context)           ordering and typed reasons for one held order
    review_draft(parent, draft, purpose)  containment by code, appropriateness of a contained draft by advice
    scope_check(mandate, order, intent)   does the order match what the agent said it was doing (a hold at most)
"""
from .advice import apply_advice, merge_probability, no_advice
from .copilot import review_draft
from .scope import scope_check
from .triage import triage

__all__ = ["apply_advice", "merge_probability", "no_advice", "review_draft", "scope_check", "triage"]
