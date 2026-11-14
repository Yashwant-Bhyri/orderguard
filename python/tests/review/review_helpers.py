"""Test doubles and canned typed answers for the review tests."""

class Fake:
    """A stand-in for `Decisions`: returns canned typed answers (a dict, or a callable of (state, questions)) or raises."""

    def __init__(self, answers=None, raises=None):
        self.answers, self.raises, self.calls = answers, raises, 0

    def ask(self, state, questions):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        a = self.answers(state, questions) if callable(self.answers) else self.answers
        return a


def triage_answers(p=0.9, pattern="collusion_split", urgency=1.5):
    return {"compromised": {"type": "noul", "noul": p},
            "pattern": {"type": "choice", "choice": pattern, "confidence": 0.8, "probabilities": {pattern: 0.8}},
            "urgency": {"type": "score", "score": urgency, "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7}}}


def draft_answers(appropriateness=1.9, match=0.9, concern="none"):
    return {"appropriateness": {"type": "score", "score": appropriateness},
            "scope_match": {"type": "noul", "noul": match},
            "concerns": {"type": "choice", "choice": concern, "confidence": 0.7, "probabilities": {concern: 0.7}}}


ORDER = {"step": 10, "agent": 3, "ticker": "SPY", "side": "buy", "quantity": 20, "limit_price": 500.0, "trusted_price": 500.0, "notional_usd": 10_000.0}
