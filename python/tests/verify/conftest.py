"""Shared test helpers: a tiny in-memory truth store, a finance pack around it, and a scripted stand-in for the LLM."""
from datetime import date

import pytest

from orderguard_verify.core.gateway import Gateway
from orderguard_verify.finance.models import Mandate
from orderguard_verify.finance.pack import FinancePack
from orderguard_verify.finance.truth_store import Snapshot, TruthStore

DEFAULT_MANDATE = Mandate(allowed_tickers=["ACME"], max_order_shares=1000, max_order_notional=100_000)


def snap(ticker, metric, period, value, as_of, *, duration="FY", period_end=None, claim_type="fundamental", unit="USD"):
    return Snapshot(claim_type=claim_type, ticker=ticker, metric=metric, period=period, duration=duration,
                    period_end=period_end, value=value, unit=unit, as_of=as_of, source="test filing",
                    source_url="https://example.test/filing", hash="h" * 64)


@pytest.fixture
def store():
    s = TruthStore(":memory:")
    for sn in [
        snap("ACME", "revenue", "FY2022", 3.0e9, "2023-02-15", period_end="2022-12-31"),
        snap("ACME", "revenue", "FY2023", 4.0e9, "2024-02-15", period_end="2023-12-31"),
        snap("ACME", "revenue", "FY2023", 4.2e9, "2024-09-01", period_end="2023-12-31"),   # restated later
        snap("ACME", "revenue", "FY2024", 5.0e9, "2025-02-14", period_end="2024-12-31"),
        snap("ACME", "revenue", "Q1 FY2025", 1.4e9, "2025-05-10", duration="Q", period_end="2025-03-31"),
        snap("ACME", "revenue", "Q4 FY2024", 1.3e9, "2025-02-14", duration="Q", period_end="2024-12-31"),
        snap("ACME", "eps_diluted", "FY2024", 2.50, "2025-02-14", period_end="2024-12-31", unit="USD/share"),
        snap("ACME", "price", None, 55.10, "2025-03-03", claim_type="price", duration=None),
    ]:
        s.add(sn)
    return s


@pytest.fixture
def make_pack(store):
    def make(mandate=DEFAULT_MANDATE, db=":memory:"):
        return FinancePack(store, mandate, refresh_fn=None)
    return make


@pytest.fixture
def make_gateway(make_pack):
    def make(claims, mandate=DEFAULT_MANDATE, db=":memory:", clock=lambda: date(2025, 3, 4)):
        return Gateway(make_pack(mandate, db), ask=scripted(claims), db_path=db, clock=clock)
    return make


def scripted(claims):
    """An `ask` replacement that returns fixed extractor output, so tests never call a model."""
    def ask(system, user, **kw):
        from orderguard_verify.core.llm import LLMCall
        return {"claims": claims}, LLMCall("fake", 0, 0, 0.0, 0.0, True)
    return ask


def D(s):
    return date.fromisoformat(s)
