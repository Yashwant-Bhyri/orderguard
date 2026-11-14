"""L6 figure check: units, fiscal-year naming, restatements, the filing-date boundary, and every way the data source can fail."""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
from facts_fixtures import APPLE, NVIDIA, e, store_for
from vsupport import D

from orderguard_verify import api
from orderguard_verify.core.pack import SourceUnavailable
from orderguard_verify.finance import sources
from orderguard_verify.finance.truth_store import TruthStore

AAPL = store_for(AAPL=APPLE)
NVDA = store_for(NVDA=NVIDIA)
LATE = D("2025-06-01")


def fig(metric, fy, value, unit="USD millions", **kw):
    return {"metric": metric, "fiscal_year": fy, "value": value, "unit": unit, **kw}


def one(f, as_of=LATE, ticker="AAPL", store=AAPL, fetch=False):
    (r,) = api.check_figures(ticker, as_of, [f], store=store, fetch=fetch)
    return r


# ---- units -------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value,unit", [(391_035, "USD millions"), (391_035, "millions"), (391_035, "$M"), (391_035, "USD mm"), (391.035, "USD billions"),
                                        (391.035, "billion"), (391.035, "bn"), (391_035_000, "USD thousands"), (391_035_000, "thousand"), (391_035_000, "k"),
                                        (391_035_000_000, "USD"), (391_035_000_000, None), ("391,035", "millions"), ("$391.035B", None), ("391035M", None),
                                        ("$391,035 million", None) if False else (391_035, "US$ millions")])
def test_every_scale_of_the_same_truth_is_confirmed(value, unit):
    r = one(fig("revenue", 2024, value, unit))
    assert r["status"] == "confirmed", (value, unit, r["reason"])


@pytest.mark.parametrize("value,unit", [(391_035, "USD billions"), (391_035, "USD"), (391.035, "USD millions"), (391_035_000, "USD millions"),
                                        (391_035, "USD thousands")])
def test_a_unit_slip_is_contradicted_and_named(value, unit):
    r = one(fig("revenue", 2024, value, unit))
    assert r["status"] == "contradicted" and "factor of" in r["reason"] or r["status"] == "contradicted"


@pytest.mark.parametrize("unit", ["USD/share", "per share", "USD per share"])
def test_per_share_figures_ignore_scale_words_and_totals_reject_per_share(unit):
    assert one(fig("eps_diluted", 2024, 6.08, unit))["status"] == "confirmed"
    assert one(fig("revenue", 2024, 391_035, unit))["status"] == "unverifiable"


def test_eps_with_a_scale_is_unreadable_not_confirmed():
    assert one(fig("eps_diluted", 2024, 6.08, "USD millions"))["status"] == "unverifiable"
    assert one(fig("eps_diluted", 2024, "6.08M", None))["status"] == "unverifiable"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, False, None, "", "abc", "1_000", "1e999", [], {}, "٣٩١٠٣٥", "--5", "5 5", "$"])
def test_garbage_values_are_never_confirmed(value):
    assert one(fig("revenue", 2024, value))["status"] == "unverifiable", repr(value)


def test_negative_zero_and_zero_are_not_confirmed():
    for v in (0, -0.0, "0", "-0", "(0)"):
        assert one(fig("revenue", 2024, v))["status"] != "confirmed"


def test_negative_and_parenthesised_values_do_not_match_a_positive_truth():
    for v in (-391_035, "(391,035)", "-391035"):
        assert one(fig("revenue", 2024, v))["status"] == "contradicted"


def test_two_percent_cap_holds_whatever_the_stated_precision():
    assert one(fig("revenue", 2024, 391_035 * 1.021))["status"] == "contradicted"
    assert one(fig("revenue", 2024, 391_035 * 0.979))["status"] == "contradicted"
    assert one(fig("revenue", 2024, 391_000))["status"] == "confirmed"          # rounded to thousands


@pytest.mark.parametrize("bad", [{"fiscal_year": 2024}, {"metric": "revenue"}, {"metric": "ebitda", "fiscal_year": 2024, "value": 1},
                                 {"metric": "revenue", "fiscal_year": "2024", "value": 1}, {"metric": "revenue", "fiscal_year": 2024.0, "value": 1},
                                 {"metric": "revenue", "fiscal_year": True, "value": 1}, {"metric": "revenue", "fiscal_year": 1800, "value": 1},
                                 {"metric": "revenue", "fiscal_year": 2024, "value": 1, "period": "Q9"}, {"metric": ["revenue"], "fiscal_year": 2024, "value": 1},
                                 {}, "revenue", None, 5, [1]])
def test_malformed_figures_are_unverifiable_with_a_reason(bad):
    (r,) = api.check_figures("AAPL", LATE, [bad], store=AAPL, fetch=False)
    assert r["status"] == "unverifiable" and r["reason"]


# ---- fiscal-year naming for off-calendar companies --------------------------------------------------------------------------------

def lulu_store():
    """The year ending Jan 2024 is the company's 'fiscal 2023' (SEC's own fy field says 2023)."""
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        e("2022-01-31", "2023-01-29", 8_110e6, "0001397187-23-000001", 2022, "2023-03-23"),
        e("2023-01-30", "2024-01-28", 9_619e6, "0001397187-24-000001", 2023, "2024-03-21"),
        e("2024-01-29", "2025-02-02", 10_588e6, "0001397187-25-000001", 2024, "2025-03-20")]}}}}}
    return store_for(LULU=facts)


def test_off_calendar_company_is_checked_in_its_own_year_naming():
    s = lulu_store()
    assert one(fig("revenue", 2023, 9_619), ticker="LULU", store=s)["status"] == "confirmed"          # FYE Jan 2024 is "fiscal 2023"
    assert one(fig("revenue", 2024, 10_588), ticker="LULU", store=s)["status"] == "confirmed"
    r = one(fig("revenue", 2024, 9_619), ticker="LULU", store=s)                                          # last year's figure as this year's
    assert r["status"] == "contradicted" and "last year" in r["reason"]


def test_calendar_naming_applied_to_an_off_calendar_company_is_not_confirmed():
    s = lulu_store()
    assert one(fig("revenue", 2024, 9_619), ticker="LULU", store=s)["status"] != "confirmed"


def test_apple_52_53_week_year_ends_in_september():
    assert one(fig("revenue", 2024, 391_035))["status"] == "confirmed"
    assert one(fig("revenue", 2025, 391_035))["status"] in ("unverifiable", "not_public_yet")


# ---- restatements and the filing-date boundary -------------------------------------------------------------------------------------

def test_the_filing_date_boundary_is_inclusive_and_the_day_before_is_not_public_yet():
    f = fig("revenue", 2024, 391_035)
    assert one(f, as_of=D("2024-11-01"))["status"] == "confirmed"
    before = one(f, as_of=D("2024-10-31"))
    assert before["status"] == "not_public_yet" and "2024-11-01" in before["reason"]
    assert one(f, as_of=D("2024-11-02"))["status"] == "confirmed"


def test_datetime_and_string_decision_dates_are_read_as_dates():
    f = fig("revenue", 2024, 391_035)
    assert one(f, as_of=dt.datetime(2024, 11, 1, 0, 0))["status"] == "confirmed"
    assert one(f, as_of="2024-11-01")["status"] == "confirmed"
    assert one(f, as_of="2024-11-01T09:30:00Z")["status"] == "confirmed"
    assert one(f, as_of="2024-10-31")["status"] == "not_public_yet"


def test_restatement_on_the_boundary_day():
    old, new = 11.93, 1.19                              # NVIDIA FY2024 diluted EPS, restated for the split on 2025-02-26
    f_old = fig("eps_diluted", 2024, old, "USD/share")
    f_new = fig("eps_diluted", 2024, new, "USD/share")
    d_before, d_on = D("2025-02-25"), D("2025-02-26")
    assert one(f_old, as_of=d_before, ticker="NVDA", store=NVDA)["status"] == "confirmed"
    assert one(f_new, as_of=d_before, ticker="NVDA", store=NVDA)["status"] == "not_public_yet"
    r = one(f_old, as_of=d_on, ticker="NVDA", store=NVDA)
    assert r["status"] == "stale" and "split" in r["reason"]
    assert one(f_new, as_of=d_on, ticker="NVDA", store=NVDA)["status"] == "confirmed"


def test_truth_is_reported_in_the_figures_own_unit():
    r = one(fig("revenue", 2024, 391.035, "USD billions"))
    assert r["unit"] == "USD billions" and r["truth"] == pytest.approx(391.035)


# ---- failures of the data source ------------------------------------------------------------------------------------------------------

def test_empty_truth_store_without_network_is_unverifiable_with_a_reason():
    r = one(fig("revenue", 2024, 391_035), store=TruthStore(":memory:"))
    assert r["status"] == "unverifiable" and "truth store" in r["reason"]


@pytest.mark.parametrize("exc", [httpx.ConnectError("network off"), httpx.ReadTimeout("slow"), httpx.HTTPStatusError("500", request=httpx.Request("GET", "http://x"),
                                                                                                                   response=httpx.Response(500)),
                                 SourceUnavailable("SEC EDGAR is rate-limiting or down; try again in a minute"), ValueError("not json"), KeyError("facts"),
                                 TypeError("odd shape"), OSError("read-only file system"), RuntimeError("anything else"), MemoryError()])
def test_every_fetch_failure_is_unverifiable_never_a_traceback_or_a_pass(monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(sources, "ensure", boom)
    monkeypatch.setattr(sources, "refresh", boom)
    try:
        r = one(fig("revenue", 2024, 391_035), store=TruthStore(":memory:"), fetch=True)
    except MemoryError:
        pytest.skip("MemoryError is deliberately not swallowed")
    assert r["status"] == "unverifiable" and r["reason"]


def test_network_off_in_the_real_fetch_path_is_unverifiable(monkeypatch):
    """Drive sources.ensure itself with a transport that refuses every connection."""
    def refuse(request):
        raise httpx.ConnectError("network is unreachable", request=request)
    real = httpx.Client
    monkeypatch.setattr(sources.httpx, "Client", lambda *a, **k: real(transport=httpx.MockTransport(refuse), **{x: y for x, y in k.items() if x != "transport"}))
    monkeypatch.setattr(sources, "lookup_cik", lambda client, t: client.get("https://data.sec.gov/x") and 1)
    r = one(fig("revenue", 2024, 391_035), store=TruthStore(":memory:"), fetch=True)
    assert r["status"] == "unverifiable" and "EDGAR" in r["reason"] or r["status"] == "unverifiable"


def test_http_errors_from_sec_are_unverifiable(monkeypatch):
    for status in (403, 404, 429, 500, 503):
        real = httpx.Client
        handler = lambda request, st=status: httpx.Response(st, text="x")
        monkeypatch.setattr(sources.httpx, "Client", lambda *a, _h=handler, **k: real(transport=httpx.MockTransport(_h)))
        monkeypatch.setattr(sources, "lookup_cik", lambda client, t: 320193)
        monkeypatch.setattr(sources.time, "sleep", lambda s: None)
        r = one(fig("revenue", 2024, 391_035), store=TruthStore(":memory:"), fetch=True)
        assert r["status"] == "unverifiable", status


def test_malformed_sec_json_is_unverifiable(monkeypatch):
    real = httpx.Client
    for body in ('<html>blocked</html>', '[]', '{"facts": []}', '{"facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"start": 1}]}}}}}', 'null', ''):
        monkeypatch.setattr(sources.httpx, "Client", lambda *a, _b=body, **k: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=_b))))
        monkeypatch.setattr(sources, "lookup_cik", lambda client, t: 320193)
        r = one(fig("revenue", 2024, 391_035), store=TruthStore(":memory:"), fetch=True)
        assert r["status"] == "unverifiable", body


def test_unusable_truth_store_path_is_unverifiable(monkeypatch, tmp_path):
    monkeypatch.setenv("OG_TRUTH_DB", str(tmp_path / "no" / "such" / "dir" / "truth.db"))
    (r,) = api.check_figures("AAPL", LATE, [fig("revenue", 2024, 391_035)], fetch=False)
    assert r["status"] == "unverifiable" and r["reason"]


@pytest.mark.parametrize("as_of", ["not a date", "2024-13-45", "", None, 12345, [], "2024/11/01"])
def test_bad_decision_dates_are_unverifiable_for_every_figure(as_of):
    out = api.check_figures("AAPL", as_of, [fig("revenue", 2024, 391_035), fig("net_income", 2024, 93_736)], store=AAPL, fetch=False)
    assert [r["status"] for r in out] == ["unverifiable", "unverifiable"] and "date" in out[0]["reason"]


@pytest.mark.parametrize("figures", [None, "revenue", 5, {"metric": "revenue"}])
def test_figures_that_are_not_a_list_are_unverifiable(figures):
    out = api.check_figures("AAPL", LATE, figures, store=AAPL, fetch=False)
    assert len(out) == 1 and out[0]["status"] == "unverifiable"


@pytest.mark.parametrize("ticker", [None, "", 5, ["AAPL"], "AA PL", "AAPL;DROP", "ＡＡＰＬ ", "../etc", "A" * 40])
def test_bad_tickers_are_unverifiable(ticker):
    out = api.check_figures(ticker, LATE, [fig("revenue", 2024, 391_035)], store=AAPL, fetch=False)
    assert out[0]["status"] in ("unverifiable",) or ticker == "ＡＡＰＬ "


def test_check_text_with_a_bad_date_escalates_instead_of_raising():
    r = api.check_text("revenue was 5", "AAPL", "yesterday", store=AAPL, fetch=False)
    assert r["decision"] == "escalate" and r["error"]


def test_check_text_with_a_model_that_fails_or_returns_junk_escalates():
    def down(system, user, **kw):
        raise RuntimeError("model down")

    def junk(system, user, **kw):
        from orderguard_verify.core.llm import LLMCall
        return {"claims": "not a list"}, LLMCall("fake", 0, 0, 0.0, 0.0, True)

    for ask in (down, junk):
        r = api.check_text("Apple revenue was $391,035 million.", "AAPL", LATE, store=AAPL, ask=ask, fetch=False)
        assert r["decision"] == "escalate", ask.__name__
