"""On-demand fetching from SEC EDGAR: fetched once and cached, polite about rate limits, clear when it cannot."""
import httpx
import pytest

from orderguard_verify.core.pack import SourceUnavailable
from orderguard_verify.finance import sources
from orderguard_verify.finance.truth_store import TruthStore

FACTS = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
    {"start": "2024-01-01", "end": "2024-12-31", "val": 1000, "accn": "0001-25-000001", "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-01"}]}}}}}
MAP = {"0": {"cik_str": 999, "ticker": "NEWCO", "title": "NewCo"}}


@pytest.fixture
def net(monkeypatch, tmp_path):
    calls = []
    plan = {"facts_status": [200]}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert "OrderGuardVerify" in request.headers["user-agent"] and "@" not in request.headers["user-agent"]   # descriptive, no email
        if "company_tickers" in str(request.url):
            return httpx.Response(200, json=MAP)
        status = plan["facts_status"].pop(0) if len(plan["facts_status"]) > 1 else plan["facts_status"][0]
        return httpx.Response(status, json=FACTS if status == 200 else {})

    real = httpx.Client
    monkeypatch.setattr(sources.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(sources, "VAR", tmp_path)
    monkeypatch.setattr(sources, "PAUSE", 0)
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    return calls, plan


def test_a_new_company_is_fetched_once_then_served_from_the_store(net):
    calls, _ = net
    store = TruthStore(":memory:")
    sources.ensure(store, "newco")
    assert "NEWCO" in store.tickers()
    n = len(calls)
    sources.ensure(store, "NEWCO")
    assert len(calls) == n                                  # cached: no second request


def test_rate_limited_requests_back_off_and_retry(net):
    _, plan = net
    plan["facts_status"] = [429, 503, 200]
    store = TruthStore(":memory:")
    sources.ensure(store, "NEWCO")
    assert "NEWCO" in store.tickers()


def test_unknown_ticker_and_non_gaap_filer_give_a_plain_reason(net):
    _, plan = net
    with pytest.raises(SourceUnavailable, match="not a US-listed ticker"):
        sources.ensure(TruthStore(":memory:"), "ZZZZ")
    plan["facts_status"] = [404]
    with pytest.raises(SourceUnavailable, match="not a US-GAAP filer"):
        sources.ensure(TruthStore(":memory:"), "NEWCO")


def test_the_sec_user_agent_can_be_set_and_defaults_to_one_without_contact_details(monkeypatch):
    from orderguard_verify.finance import edgar
    monkeypatch.delenv("OG_SEC_UA", raising=False)
    assert "@" not in edgar.user_agent() and "OrderGuardVerify" in edgar.user_agent()
    monkeypatch.setenv("OG_SEC_UA", "MyResearch contact-details")
    assert edgar.user_agent() == "MyResearch contact-details"
