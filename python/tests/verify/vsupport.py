"""Helpers shared by the verify tests. Lives in its own module (not conftest) so that `from vsupport import ...` cannot
collide with another suite's conftest when several test directories are collected in one pytest run."""
from datetime import date

from orderguard_verify.finance.models import Mandate
from orderguard_verify.finance.truth_store import Snapshot

DEFAULT_MANDATE = Mandate(allowed_tickers=["ACME"], max_order_shares=1000, max_order_notional=100_000)


def snap(ticker, metric, period, value, as_of, *, duration="FY", period_end=None, claim_type="fundamental", unit="USD"):
    return Snapshot(claim_type=claim_type, ticker=ticker, metric=metric, period=period, duration=duration,
                    period_end=period_end, value=value, unit=unit, as_of=as_of, source="test filing",
                    source_url="https://example.test/filing", hash="h" * 64)


def scripted(claims):
    """An `ask` replacement that returns fixed extractor output, so tests never call a model."""
    def ask(system, user, **kw):
        from orderguard_verify.core.llm import LLMCall
        return {"claims": claims}, LLMCall("fake", 0, 0, 0.0, 0.0, True)
    return ask


def D(s):
    return date.fromisoformat(s)
