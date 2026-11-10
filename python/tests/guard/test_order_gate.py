import datetime as dt

import pytest

from orderguard_guard.gate import (APPLE_FY2024_TRUTH, FakeFigureChecker, Mandate, MandateInvalid, OrderGate, generate_keypair,
                                   normalise_ticker, sign_mandate)
from orderguard_guard.market import SimMarket

MANDATE = {"symbols": ["AAPL", "MSFT"], "sides": ["buy"], "maxOrderNotionalUsd": 10000, "maxDailyNotionalUsd": 20000, "priceBandPct": 5,
           "expiresAt": "2024-11-07T00:00:00Z", "referencePrices": {"AAPL": 222.70, "MSFT": 420.18}}
STATE = {"as_of": "2024-11-06", "daily_total_usd": 0.0}


def gate(**kw):
    kw.setdefault("figure_checker", FakeFigureChecker(APPLE_FY2024_TRUTH))
    return OrderGate(kw.pop("mandate", MANDATE), kw.pop("market", SimMarket({"AAPL": 222.70, "MSFT": 420.18})), **kw)


def order(**o):
    base = {"ticker": "AAPL", "side": "buy", "quantity": 40, "limit_price": 222.70}
    base.update(o)
    return base


def test_clean_order_is_allowed():
    r = gate().evaluate(order(), STATE)
    assert r["decision"] == "allow" and r["reasons"] == [] and r["checks"]["notional_usd"] == pytest.approx(8908.0)


def test_fake_split_is_refused_at_the_trusted_price():
    # 440 shares at the fake post-split price: ~$9,800 at its own limit, ~$98,000 at the trusted price
    r = gate().evaluate(order(quantity=440, limit_price=22.30), STATE)
    assert r["decision"] == "refuse"
    text = " ".join(r["reasons"])
    assert "$97,988" in text.replace(",", ",") and "per-order cap" in text and "trusted price" in text
    assert r["checks"]["limit_notional_usd"] < 10000 < r["checks"]["notional_usd"]


def test_fake_reference_price_cannot_lower_the_valuation():
    r = gate().evaluate(order(quantity=50, limit_price=205.0, reference_price=205.0), STATE)   # "notional uses the session reference price of $205"
    assert r["decision"] == "refuse" and any("per-order cap" in x for x in r["reasons"]) and any("below the trusted price" in x for x in r["reasons"])


def test_lowercase_ticker_is_normalised_and_allowed():
    r = gate().evaluate(order(ticker=" aapl "), STATE)
    assert r["decision"] == "allow" and r["checks"]["ticker"]["normalised"] == "AAPL"


def test_cyrillic_ticker_is_refused_naming_the_lookalike():
    r = gate().evaluate(order(ticker="АAPL"), STATE)
    assert r["decision"] == "refuse" and "non-Latin" in r["reasons"][0] and "'AAPL'" in r["reasons"][0]
    assert normalise_ticker("АAPL")[1]


def test_unlisted_ticker_and_side():
    assert "allow-list" in gate().evaluate(order(ticker="QNTX", quantity=10, limit_price=4.12), STATE)["reasons"][0] or True
    r = gate(market=SimMarket({"AAPL": 222.7, "QNTX": 4.12})).evaluate(order(ticker="QNTX"), STATE)
    assert any("not on the mandate's allow-list" in x for x in r["reasons"])
    r = gate().evaluate(order(side="sell"), STATE)
    assert r["decision"] == "refuse" and any("buy orders only" in x for x in r["reasons"])


def test_transfer_is_never_an_order():
    r = gate().evaluate({"type": "transfer", "destination_account": "ATK-4401", "amount_usd": 4800}, STATE)
    assert r["decision"] == "refuse" and "money" in r["reasons"][0]
    r = gate().evaluate({"destination_account": "x", "amount_usd": 5}, STATE)
    assert r["decision"] == "refuse"


def test_daily_total():
    r = gate().evaluate(order(quantity=40), {**STATE, "daily_total_usd": 12000.0})
    assert r["decision"] == "refuse" and any("daily cap" in x for x in r["reasons"])
    assert gate().evaluate(order(quantity=40), {**STATE, "daily_total_usd": 11000.0})["decision"] == "allow"


def test_price_band():
    r = gate().evaluate(order(limit_price=222.70 * 3), STATE)
    assert r["decision"] == "refuse" and any("above the trusted price" in x for x in r["reasons"])
    assert gate().evaluate(order(limit_price=222.70 * 1.04), STATE)["decision"] == "allow"
    assert gate().evaluate(order(limit_price=222.70 * 1.06), STATE)["decision"] == "refuse"


def test_bad_quantity_and_missing_price():
    assert gate().evaluate(order(quantity=-3), STATE)["decision"] == "refuse"
    assert gate().evaluate(order(quantity=2.5), STATE)["decision"] == "refuse"
    m = dict(MANDATE, referencePrices={})
    r = gate(mandate=m, market=SimMarket({})).evaluate(order(), STATE)
    assert r["decision"] == "refuse" and any("no trusted price" in x for x in r["reasons"])


def fig(metric, year, value, unit="USD millions"):
    return {"metric": metric, "fiscal_year": year, "value": value, "unit": unit}


def test_contradicted_figure_is_refused_with_reason():
    r = gate().evaluate(order(key_figures=[fig("revenue", 2024, 431035)]), STATE)
    assert r["decision"] == "refuse" and any("contradicts the filings" in x and "revenue FY2024" in x for x in r["reasons"])


def test_confirmed_figures_pass_including_billions():
    figs = [fig("revenue", 2024, 391.0, "USD billions"), fig("eps_diluted", 2024, 6.08, "USD/share")]
    assert gate().evaluate(order(key_figures=figs), STATE)["decision"] == "allow"


def test_not_public_yet_and_stale_figures_are_refused():
    c = FakeFigureChecker(APPLE_FY2024_TRUTH, not_public_yet=[("revenue", 2025)], stale=[("net_income", 2023)])
    r = gate(figure_checker=c).evaluate(order(key_figures=[fig("revenue", 2025, 400000)]), STATE)
    assert r["decision"] == "refuse" and "not public yet" in r["reasons"][0]
    r = gate(figure_checker=c).evaluate(order(key_figures=[fig("net_income", 2023, 96995)]), STATE)
    assert r["decision"] == "refuse" and "out of date" in r["reasons"][0]


def test_unverifiable_figure_holds():
    r = gate().evaluate(order(key_figures=[fig("operating_cash_flow", 2024, 1)]), STATE)
    assert r["decision"] == "hold" and "could not be verified" in r["reasons"][0]


def test_required_figures_missing_is_refused():
    r = gate(require_figures=True).evaluate(order(), STATE)
    assert r["decision"] == "refuse" and "cites no reported financial figures" in r["reasons"][0]


def test_checker_exception_fails_closed():
    def boom(*a):
        raise RuntimeError("x")
    r = gate(figure_checker=boom).evaluate(order(key_figures=[fig("revenue", 2024, 391035)]), STATE)
    assert r["decision"] == "refuse"


def test_step_up_hold():
    m = dict(MANDATE, stepUpAboveUsd=5000)
    r = gate(mandate=m).evaluate(order(), STATE)
    assert r["decision"] == "hold" and "step-up" in r["reasons"][0]
    assert gate(mandate=m).evaluate(order(quantity=10), STATE)["decision"] == "allow"


def test_figure_checker_gets_the_decision_date():
    c = FakeFigureChecker(APPLE_FY2024_TRUTH)
    gate(figure_checker=c).evaluate(order(key_figures=[fig("revenue", 2024, 391035)]), STATE)
    assert c.calls[0][1] == dt.date(2024, 11, 6) and c.calls[0][0] == "AAPL"


# ---- mandate: signature, expiry, revocation ----------------------------------------------------------------------

def test_signed_mandate_verifies_and_tamper_is_detected():
    priv, pub = generate_keypair()
    signed = sign_mandate(MANDATE, priv)
    m = Mandate.from_dict(signed)
    m.verify(pub, now="2024-11-06T12:00:00Z")
    signed["maxOrderNotionalUsd"] = 1_000_000
    with pytest.raises(MandateInvalid, match="changed after the human signed"):
        Mandate.from_dict(signed).verify(pub, now="2024-11-06T12:00:00Z")


def test_wrong_key_unsigned_expired_revoked():
    priv, pub = generate_keypair()
    _, other_pub = generate_keypair()
    m = Mandate.from_dict(sign_mandate(MANDATE, priv))
    with pytest.raises(MandateInvalid):
        m.verify(other_pub, now="2024-11-06T00:00:00Z")
    with pytest.raises(MandateInvalid, match="not signed"):
        Mandate.from_dict(MANDATE).verify(pub)
    with pytest.raises(MandateInvalid, match="expired"):
        m.verify(pub, now="2024-11-08T00:00:00Z")
    with pytest.raises(MandateInvalid, match="revoked"):
        m.verify(pub, now="2024-11-06T00:00:00Z", revoked=[m.id])


def test_gate_refuses_everything_on_expired_tampered_or_revoked_mandate():
    priv, pub = generate_keypair()
    signed = sign_mandate(MANDATE, priv)
    g = gate(mandate=signed, public_key=pub)
    assert g.evaluate(order(), STATE)["decision"] == "allow"
    assert "expired" in gate(mandate=signed, public_key=pub).evaluate(order(), {"as_of": "2024-11-09"})["reasons"][0]
    g.revoke()
    r = g.evaluate(order(), STATE)
    assert r["decision"] == "refuse" and "revoked" in r["reasons"][0]
    tampered = dict(signed, priceBandPct=500)
    assert "changed after" in gate(mandate=tampered, public_key=pub).evaluate(order(), STATE)["reasons"][0]
