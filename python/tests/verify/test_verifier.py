"""Verifier: labels for each kind of claim, including the as-of date behaviour."""
from orderguard_verify.core.models import Claim
from orderguard_verify.finance.verifier import verify

from vsupport import D, scripted

NO_LLM = scripted([])


def claim(metric="revenue", value=5.0e9, period="FY2024", **kw):
    base = dict(id="c1", type="fundamental", text="t", subject="ACME", attribute=metric, period=period, value=value, unit="USD", key=True)
    return Claim(**{**base, **kw})


def label(c, as_of, store):
    return verify(c, D(as_of), store, NO_LLM)


def test_true_figure_is_confirmed(store):
    assert label(claim(), "2025-03-01", store).label == "confirmed"


def test_rounding_within_two_percent_is_confirmed(store):
    assert label(claim(value=5.05e9), "2025-03-01", store).label == "confirmed"


def test_false_figure_is_contradicted_with_evidence(store):
    v = label(claim(value=6.5e9), "2025-03-01", store)
    assert v.label == "contradicted" and v.evidence[0].source_url and v.evidence[0].hash


def test_figure_not_yet_public_is_unverifiable_not_contradicted(store):
    assert label(claim(), "2025-01-10", store).label == "unverifiable"


def test_restatement_respects_the_decision_date(store):
    old_claim = claim(period="FY2023", value=4.0e9)
    assert label(old_claim, "2024-06-01", store).label == "confirmed"      # 4.0B was the filed figure then
    assert label(old_claim, "2025-03-01", store).label == "stale"          # restated to 4.2B since
    assert label(claim(period="FY2023", value=4.2e9), "2024-06-01", store).label == "contradicted"  # 4.2B did not exist yet


def test_latest_quarter_claim_using_an_older_quarter_is_stale(store):
    v = label(claim(period="latest_q", value=1.3e9), "2025-06-01", store)   # 1.3B is Q4 FY2024; Q1 FY2025 is out
    assert v.label == "stale" and "Q4 FY2024" in v.reason


def test_latest_year_claim_matches_newest_filed_year(store):
    assert label(claim(period="latest_fy", value=5.0e9), "2025-06-01", store).label == "confirmed"


def test_growth_is_computed_from_two_filings(store):
    assert label(claim(metric="revenue_growth_yoy", value=0.19, unit="ratio"), "2025-03-01", store).label == "confirmed"  # 5.0 / 4.2 (restated) - 1
    assert label(claim(metric="revenue_growth_yoy", value=0.40, unit="ratio"), "2025-03-01", store).label == "contradicted"


def test_eps_is_compared_to_the_cent(store):
    assert label(claim(metric="eps_diluted", value=2.51, unit="USD/share"), "2025-03-01", store).label == "confirmed"
    assert label(claim(metric="eps_diluted", value=3.10, unit="USD/share"), "2025-03-01", store).label == "contradicted"


def test_unknown_company_and_foreign_currency_are_unverifiable(store):
    assert label(claim(subject="ZZZZ"), "2025-03-01", store).label == "unverifiable"
    assert label(claim(unit="CNY"), "2025-03-01", store).label == "unverifiable"


def test_unsupported_measure_is_unverifiable_via_definition_lookup(store):
    ask = scripted([])  # the lookup model answers with no "metric" key
    v = verify(claim(metric="adjusted_ebitda"), D("2025-03-01"), store, ask)
    assert v.label == "unverifiable"


def test_rumour_and_sentiment_are_unverifiable_by_design(store):
    for t in ("rumour", "sentiment"):
        assert label(Claim(id="c", type=t, text="x", key=True), "2025-03-01", store).label == "unverifiable"


def test_price_claims_use_the_quote_feed(store):
    p = dict(type="price", attribute="price", period=None, unit="USD")
    assert label(claim(value=55.0, **p), "2025-03-04", store).label == "confirmed"
    assert label(claim(value=70.0, **p), "2025-03-04", store).label == "contradicted"
    assert label(claim(value=55.0, **p), "2025-04-30", store).label == "stale"       # newest quote is 8 weeks old


def test_a_non_usd_source_is_compared_in_its_own_currency(store):
    from vsupport import snap
    store.add(snap("9999.HK", "revenue", "FY2023", 120_000e6, "2024-03-20", period_end="2023-12-31", unit="CNY"))
    ok = claim(subject="9999.HK", period="FY2023", value=120.0e9, unit="CNY")
    assert label(ok, "2024-04-10", store).label == "confirmed"
    assert label(claim(subject="9999.HK", period="FY2023", value=700e9, unit="CNY"), "2024-04-10", store).label == "contradicted"
    assert label(claim(subject="9999.HK", period="FY2023", value=120.0e9, unit="USD"), "2024-04-10", store).label == "unverifiable"


def test_tolerance_follows_the_precision_the_memo_states(store):
    # "$4,981 million" is stated to the million, so 4.981B is not the filed 5.0B...
    assert label(claim(value=4.981e9, text="revenue of $4,981 million"), "2025-03-01", store).label == "contradicted"
    # ...but "$5.0 billion" is stated to 0.1B, so it is the same figure
    assert label(claim(value=5.0e9, text="revenue of $5.0 billion"), "2025-03-01", store).label == "confirmed"
    assert label(claim(value=4.9e9, text="revenue of $4.9 billion"), "2025-03-01", store).label == "confirmed"      # rounded down by one unit
    assert label(claim(value=4.7e9, text="revenue of $4.7 billion"), "2025-03-01", store).label == "contradicted"


def test_margins_and_free_cash_flow_are_worked_out_in_code_from_stored_figures(store):
    from vsupport import snap
    for metric, v in (("gross_profit", 2.0e9), ("operating_cash_flow", 1.5e9), ("capex", 0.3e9)):
        store.add(snap("ACME", metric, "FY2024", v, "2025-02-14", period_end="2024-12-31"))

    def run(text, value, attr=None):
        c = Claim(id="c1", type="fundamental", text=text, subject="ACME", attribute=attr, period="FY2024", value=value, unit="ratio" if value < 5 else "USD", key=True)
        return verify(c, D("2025-03-04"), store, ask=lambda *a, **k: ({"metric": None}, None)).label
    assert run("Gross margin was 40%", 0.40, "gross_profit") == "confirmed"          # 2.0 / 5.0
    assert run("Gross margin was 46%", 0.46) == "contradicted"
    assert run("Free cash flow was $1.2 billion", 1.2e9) == "confirmed"              # 1.5 - 0.3
    assert run("Free cash flow was $1.5 billion", 1.5e9) == "contradicted"
    assert run("Cash flow was $1.2 billion", 1.2e9) == "unverifiable"                # ambiguous, never guessed


def test_a_january_year_end_company_keeps_its_own_fiscal_year_names():
    """Lululemon-style: the year ending January 2024 is 'fiscal 2023'. SEC's own fy field in the 10-K says so."""
    from orderguard_verify.finance.edgar import snapshots_from_facts

    def fact(end, start, fy, accn, filed, val):
        return {"start": start, "end": end, "val": val, "accn": accn, "fy": fy, "fp": "FY", "form": "10-K", "filed": filed}
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        fact("2023-01-29", "2022-01-31", 2022, "0001-23-000001", "2023-03-28", 8.1e9),
        fact("2024-01-28", "2023-01-30", 2023, "0001-24-000001", "2024-03-27", 9.6e9),
        fact("2023-01-29", "2022-01-31", 2023, "0001-24-000001", "2024-03-27", 8.1e9)]}}}}}
    got = {s.period: s.value for s in snapshots_from_facts("LULU", 1, facts)}
    assert got == {"FY2022": 8.1e9, "FY2023": 9.6e9}
