"""orderguard_verify.api (CONTRACT 5.2), offline against hand-built companyfacts for Apple and NVIDIA."""
from datetime import date

import pytest
from vsupport import D, scripted
from facts_fixtures import APPLE, NVIDIA, store_for

from orderguard_verify import api

AAPL = store_for(AAPL=APPLE)
NVDA = store_for(NVDA=NVIDIA)
LATE = D("2025-06-01")


def one(figure, as_of=LATE, ticker="AAPL", store=AAPL):
    (r,) = api.check_figures(ticker, as_of, [figure], store=store, fetch=False)
    return r


def fig(metric, fy, value, unit="USD millions", **kw):
    return {"metric": metric, "fiscal_year": fy, "value": value, "unit": unit, **kw}


def test_apple_figures_from_both_years_are_confirmed_with_their_filing():
    for f in (fig("revenue", 2024, 391_035), fig("revenue", 2023, 383_285), fig("net_income", 2024, 93_736), fig("net_income", 2023, 96_995),
              fig("eps_diluted", 2024, 6.08, "USD/share"), fig("eps_diluted", 2023, 6.13, "USD/share")):
        r = one(f)
        assert r["status"] == "confirmed", (f, r["reason"])
    r = one(fig("revenue", 2024, 391_035))
    assert r["truth"] == 391_035 and r["unit"] == "USD millions" and r["source"]["form"] == "10-K"
    assert r["source"]["filed"] == "2024-11-01" and r["source"]["accession"] == "0000320193-24-000123" and "sec.gov" in r["source"]["url"]


def test_units_are_normalised():
    assert one(fig("revenue", 2024, 391.035, "USD billions"))["status"] == "confirmed"
    assert one(fig("revenue", 2024, 391_035_000_000, "USD"))["status"] == "confirmed"
    assert one(fig("revenue", 2024, "$391.0B", None))["status"] == "confirmed"
    assert one(fig("revenue", 2024, "$94.9B", None, period="Q4"))["status"] == "confirmed"      # model-ish input, quarter
    assert one(fig("revenue", 2024, 391.035, "$B"))["status"] == "confirmed"
    assert one(fig("eps_diluted", 2024, "$6.08", None))["unit"] == "USD/share"
    assert one(fig("revenue", 2024, 391_035, "USD billions"))["status"] == "contradicted"        # wrong unit: a million times too big
    assert "factor" in one(fig("revenue", 2024, 391_035, "USD billions"))["reason"]
    assert one(fig("revenue", 2024, 5, "furlongs"))["status"] == "unverifiable"
    assert one(fig("eps_diluted", 2024, 6.08, "USD millions"))["status"] == "unverifiable"


def test_tolerance_follows_the_precision_the_figure_states():
    assert one(fig("revenue", 2024, "$391B", None))["status"] == "confirmed"              # 391.035 rounds to 391
    assert one(fig("revenue", 2024, "$391.1B", None))["status"] == "contradicted"        # one decimal stated: 391.1 is not 391.035
    assert one(fig("revenue", 2024, 391_036))["status"] == "contradicted"                 # exact to the million: off by one is wrong
    assert one(fig("eps_diluted", 2024, 6.1, "USD/share"))["status"] == "confirmed"
    assert one(fig("eps_diluted", 2024, 6.13, "USD/share"))["status"] == "contradicted"   # to the cent, 5 cents off


def test_a_quarterly_figure_cited_as_annual_is_contradicted():
    r = one(fig("revenue", 2024, 94_930))
    assert r["status"] == "contradicted" and "Q4 FY2024" in r["reason"] and "quarterly figure cited as annual" in r["reason"]
    assert one(fig("revenue", 2024, 94_930, period="Q4"))["status"] == "confirmed"


def test_last_years_figure_cited_as_this_year_is_contradicted_and_names_the_year():
    r = one(fig("revenue", 2024, 383_285))
    assert r["status"] == "contradicted" and "FY2023" in r["reason"] and "last year" in r["reason"] and r["truth"] == 391_035
    r = one(fig("eps_diluted", 2023, 6.08, "USD/share"))
    assert r["status"] == "contradicted" and "FY2024" in r["reason"]


def test_a_figure_filed_after_the_decision_date_is_not_public_yet():
    r = one(fig("revenue", 2024, 391_035), as_of=D("2024-10-15"))
    assert r["status"] == "not_public_yet" and "2024-11-01" in r["reason"] and r["truth"] is None
    assert one(fig("revenue", 2024, 391_035), as_of=D("2024-11-01"))["status"] == "confirmed"
    assert one(fig("revenue", 2023, 383_285), as_of=D("2024-10-15"))["status"] == "confirmed"


def test_an_unknown_year_or_metric_or_company_is_unverifiable_never_a_crash():
    assert one(fig("revenue", 2031, 1))["status"] == "unverifiable"
    assert one(fig("ebitda", 2024, 1))["status"] == "unverifiable"
    assert one(fig("gross_profit", 2024, 1))["status"] == "unverifiable"          # not in this company's filings fixture
    assert one(fig("revenue", 2024, 1), ticker="ZZZZ")["status"] == "unverifiable"
    assert one(fig("revenue", 2024, 1), ticker="АAPL")["status"] == "unverifiable"
    assert api.check_figures("AAPL", LATE, [None, {"metric": "revenue"}], store=AAPL, fetch=False)[1]["status"] == "unverifiable"


def test_lowercase_ticker_and_iso_date_string_work():
    (r,) = api.check_figures(" aapl ", "2025-06-01", [fig("revenue", 2024, 391_035)], store=AAPL, fetch=False)
    assert r["status"] == "confirmed"


def test_split_adjusted_eps_original_value_is_confirmed_then_stale_after_the_split_restatement():
    f = fig("eps_diluted", 2024, 11.93, "USD/share")
    assert one(f, as_of=D("2024-08-01"), ticker="NVDA", store=NVDA)["status"] == "confirmed"       # as originally filed, before the restatement
    r = one(f, as_of=D("2025-06-01"), ticker="NVDA", store=NVDA)
    assert r["status"] == "stale" and r["truth"] == 1.19 and "split" in r["reason"] and "2025-02-26" in r["reason"]
    assert one(fig("eps_diluted", 2024, 1.19, "USD/share"), as_of=D("2025-06-01"), ticker="NVDA", store=NVDA)["status"] == "confirmed"
    assert one(fig("eps_diluted", 2024, 1.19, "USD/share"), as_of=D("2024-08-01"), ticker="NVDA", store=NVDA)["status"] == "not_public_yet"
    assert one(fig("eps_diluted", 2024, 5.00, "USD/share"), as_of=D("2025-06-01"), ticker="NVDA", store=NVDA)["status"] == "contradicted"


def test_fiscal_years_use_the_companys_own_naming():
    r = one(fig("revenue", 2024, 60_922), ticker="NVDA", store=NVDA)      # NVIDIA's fiscal 2024 ended 28 January 2024
    assert r["status"] == "confirmed" and "FY2024" in r["reason"]
    assert one(fig("revenue", 2025, 130_497), ticker="NVDA", store=NVDA)["status"] == "confirmed"


def test_check_text_runs_the_memo_pipeline_offline():
    claim = {"text": "revenue of $383.3 billion", "type": "fundamental", "ticker": "AAPL", "metric": "revenue", "period": "FY2024",
             "value": 383.3e9, "unit": "USD", "key": True, "main_reason": True}
    out = api.check_text("Apple had revenue of $383.3 billion in fiscal 2024.", "AAPL", LATE, store=AAPL, ask=scripted([claim]), fetch=False)
    assert out["decision"] == "block" and out["claims"][0]["status"] == "contradicted" and out["error"] is None
    assert api.check_text("", "AAPL", LATE, store=AAPL, ask=scripted([]), fetch=False)["decision"] == "escalate"
    assert api.check_text("x", "АAPL", LATE, store=AAPL, ask=scripted([]), fetch=False)["decision"] == "escalate"


def test_the_signature_matches_the_contract():
    import inspect
    assert list(inspect.signature(api.check_figures).parameters)[:3] == ["ticker", "as_of", "figures"]
    assert list(inspect.signature(api.check_text).parameters)[:3] == ["text", "ticker", "as_of"]
