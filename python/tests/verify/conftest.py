"""Shared test helpers: a tiny in-memory truth store, a finance pack around it, and a scripted stand-in for the LLM."""
from datetime import date

import pytest

from orderguard_verify.core.gateway import Gateway
from orderguard_verify.finance.pack import FinancePack
from orderguard_verify.finance.truth_store import TruthStore

from vsupport import D, DEFAULT_MANDATE, scripted, snap  # noqa: F401  (re-exported for fixtures)


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
