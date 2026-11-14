"""L5 gate edge cases: numeric edge values, ticker corner cases, time boundaries, revocation, step-up, and faults. The gate must never raise and
never allow on a fault."""
from __future__ import annotations

import datetime as dt
import math

import pytest
from safety_common import OWNER_PRIV, OWNER_PUB, make_market, signed

from orderguard_guard.gate import FakeFigureChecker, Mandate, MandateInvalid, OrderGate, _num, normalise_ticker, sign_mandate
from orderguard_guard.market import SimMarket

BASE = {"symbols": ["AAPL", "BRK.B"], "sides": ["buy", "sell"], "maxOrderNotionalUsd": 10_000, "maxDailyNotionalUsd": 25_000, "priceBandPct": 5,
        "expiresAt": "2024-11-07T00:00:00Z", "referencePrices": {}}
STATE = {"as_of": "2024-11-06", "daily_total_usd": 0.0}
MARKET = SimMarket({"AAPL": 100.0, "BRK.B": 400.0})


def gate(mandate=None, **kw):
    m = signed({**BASE, **(mandate or {})})
    return OrderGate(m, kw.pop("market", MARKET), kw.pop("figure_checker", None), public_key=OWNER_PUB, **kw)


def order(**o):
    return {"ticker": "AAPL", "side": "buy", "quantity": 10, "limit_price": 100.0, **o}


def decide(o=None, state=None, **kw):
    return gate(**kw).evaluate(order(**(o or {})), STATE if state is None else state)


# ---- numeric edge values ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -0.0, 0, -1, True, False, None, "", "abc", "nan", "inf", "-5", "1_000",
                                 "١٢٣", "０１２", "1e999", [], {}, 1e400, "0x10", "10 shares", 2.5, "2.5"])
def test_bad_quantities_are_refused(bad):
    r = decide({"quantity": bad})
    assert r["decision"] == "refuse", bad


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.0, 0, -100.0, True, None, "", "abc", "nan", "1_0", "١٠٠", [], {}])
def test_bad_limit_prices_are_refused(bad):
    assert decide({"limit_price": bad})["decision"] == "refuse", bad


@pytest.mark.parametrize("good", [10, 10.0, "10", "1e1", " 10 ", "10.0"])
def test_whole_number_quantities_in_any_plain_form_are_allowed(good):
    assert decide({"quantity": good})["decision"] == "allow"


def test_huge_quantities_are_refused_not_overflowed():
    for q in (1e300, 10 ** 400, "9" * 400, 1.7e308):
        r = decide({"quantity": q})
        assert r["decision"] == "refuse"


def test_exactly_the_per_order_cap_is_allowed_and_one_share_over_is_not():
    assert decide({"quantity": 100})["decision"] == "allow"            # 100 x 100 = 10,000
    assert decide({"quantity": 101})["decision"] == "refuse"


def test_daily_cap_exactly_at_the_limit():
    assert decide(state={**STATE, "daily_total_usd": 15_000})["decision"] == "allow"       # 15,000 + 1,000 = 16,000 < 25,000
    assert gate({"maxDailyNotionalUsd": 11_000}).evaluate(order(quantity=100), {**STATE, "daily_total_usd": 1_000})["decision"] == "allow"
    assert gate({"maxDailyNotionalUsd": 11_000}).evaluate(order(quantity=100), {**STATE, "daily_total_usd": 1_000.01})["decision"] == "refuse"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, "abc", [], {}, True])
def test_unreadable_daily_total_refuses_instead_of_waving_through(bad):
    r = decide(state={**STATE, "daily_total_usd": bad})
    assert r["decision"] == "refuse" and "daily" in " ".join(r["reasons"]).lower()


def test_negative_zero_daily_total_is_zero():
    assert decide(state={**STATE, "daily_total_usd": -0.0})["decision"] == "allow"


@pytest.mark.parametrize("field,val", [("maxOrderNotionalUsd", float("nan")), ("maxDailyNotionalUsd", float("inf")), ("priceBandPct", float("nan")),
                                       ("maxOrderNotionalUsd", "10000"), ("maxOrderNotionalUsd", -5), ("maxOrderNotionalUsd", 0), ("priceBandPct", -1),
                                       ("stepUpAboveUsd", float("nan")), ("maxOrderNotionalUsd", True), ("symbols", []), ("symbols", "AAPL"),
                                       ("sides", [1]), ("expiresAt", "not a date"), ("referencePrices", [])])
def test_a_mandate_with_unusable_limits_refuses_everything(field, val):
    r = decide(mandate={field: val})
    assert r["decision"] == "refuse", (field, val)
    assert r["checks"].get("mandate") == "invalid" or "mandate" in " ".join(r["reasons"]).lower()


def test_price_band_zero_requires_the_exact_trusted_price():
    assert decide(mandate={"priceBandPct": 0})["decision"] == "allow"
    assert decide({"limit_price": 100.01}, mandate={"priceBandPct": 0})["decision"] == "refuse"


def test_num_helper_is_strict():
    assert _num("1,000") == 1000 and _num("$12.50") == 12.5 and _num(3) == 3.0
    for bad in (True, False, "1_0", "１２", "nan", "inf", float("nan"), None, [], "", "1e999"):
        assert _num(bad) is None, bad


# ---- tickers -----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["ＡＡＰＬ", " aapl\n", "aApL"])
def test_fullwidth_whitespace_and_case_normalise_to_the_listed_ticker(raw):
    r = decide({"ticker": raw})
    assert r["decision"] == "allow" and r["checks"]["ticker"]["normalised"] == "AAPL"


@pytest.mark.parametrize("raw", ["AAPL​", "AA​PL", "AAPL MSFT", "AAPL;", "", None, 0, 123, ["AAPL"], {"t": "AAPL"}, "AAPL\x00", "*", "AAPĹ",
                                 "ǺAPL", "ΑAPL", "ᎪAPL", "ААРL", "AАPL", "..", "-"])
def test_odd_tickers_are_refused(raw):
    r = decide({"ticker": raw})
    assert r["decision"] == "refuse", repr(raw)


def test_sharp_s_and_dotless_i_cannot_be_upper_cased_into_a_listed_ticker():
    g = gate({"symbols": ["PASS", "FIX"]}, market=SimMarket({"PASS": 10.0, "FIX": 10.0}))
    for raw in ("paß", "fıx"):
        assert normalise_ticker(raw)[1], raw
        assert g.evaluate(order(ticker=raw, limit_price=10.0), STATE)["decision"] == "refuse"


def test_class_share_ticker_forms_are_distinct_symbols():
    assert decide({"ticker": "BRK.B", "limit_price": 400.0, "quantity": 1})["decision"] == "allow"
    assert decide({"ticker": "BRK-B", "limit_price": 400.0, "quantity": 1})["decision"] == "refuse"       # not the listed spelling, no quote


# ---- time, revocation, step-up ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("as_of,decision", [("2024-11-06T23:59:59Z", "allow"), ("2024-11-06T23:59:59.999999Z", "allow"),
                                            ("2024-11-07T00:00:00Z", "refuse"), ("2024-11-07T00:00:00+00:00", "refuse"),
                                            ("2024-11-07", "refuse"), ("2024-11-08", "refuse"), ("2024-11-06T19:00:00-05:00", "refuse")])
def test_expiry_is_exclusive_at_the_boundary(as_of, decision):
    assert gate().evaluate(order(), {**STATE, "as_of": as_of})["decision"] == decision


def test_naive_and_aware_times_agree_and_garbage_times_refuse():
    assert gate().evaluate(order(), {"as_of": dt.datetime(2024, 11, 6, 12, 0)})["decision"] == "allow"
    assert gate().evaluate(order(), {"as_of": dt.date(2024, 11, 6)})["decision"] == "allow"
    for bad in ("tomorrow", "2024-13-45", 12345, {"a": 1}, "9999-99-99T00:00:00Z"):
        r = gate().evaluate(order(), {"as_of": bad})
        assert r["decision"] == "refuse", bad


def test_revoked_then_replayed_stays_refused():
    g = gate()
    first = g.evaluate(order(), STATE)
    assert first["decision"] == "allow"
    g.revoke()
    for _ in range(3):
        again = g.evaluate(order(), STATE)
        assert again["decision"] == "refuse" and "revoked" in again["reasons"][0]
    # revocation passed through the state by id works too, and a fresh gate on the same mandate honours it
    g2 = gate()
    assert g2.evaluate(order(), {**STATE, "revoked": [g2.mandate.id]})["decision"] == "refuse"
    assert g2.evaluate(order(), {**STATE, "revoked": []})["decision"] == "allow"


@pytest.mark.parametrize("bad", ["abc", 5, b"x"])
def test_unreadable_revocation_list_refuses(bad):
    assert gate().evaluate(order(), {**STATE, "revoked": bad})["decision"] == "refuse"


def test_step_up_exactly_at_the_threshold_is_not_above_it():
    at = gate({"stepUpAboveUsd": 1_000}).evaluate(order(quantity=10), STATE)           # notional exactly 1,000
    over = gate({"stepUpAboveUsd": 999.99}).evaluate(order(quantity=10), STATE)
    assert at["decision"] == "allow" and over["decision"] == "hold"


def test_step_up_never_downgrades_a_refusal():
    r = gate({"stepUpAboveUsd": 1}).evaluate(order(quantity=1000), STATE)
    assert r["decision"] == "refuse"


# ---- signatures, shapes, faults ------------------------------------------------------------------------------------------------------

def test_malformed_signatures_refuse_without_raising():
    m = signed(BASE)
    for sig in ("", "!!!notbase64", "AAAA", None, 12345, "A" * 200, [], "="):
        bad = {**m, "signature": sig}
        r = OrderGate(bad, MARKET, public_key=OWNER_PUB).evaluate(order(), STATE)
        assert r["decision"] == "refuse", sig


@pytest.mark.parametrize("o", [None, [], "buy AAPL", 5, [("ticker", "AAPL")]])
def test_non_dict_orders_are_refused(o):
    assert gate().evaluate(o, STATE)["decision"] == "refuse"


@pytest.mark.parametrize("s", ["x", [], 5])
def test_non_dict_state_is_refused(s):
    assert gate().evaluate(order(), s)["decision"] == "refuse"


def test_evaluate_never_raises_on_random_garbage():
    import random
    rng = random.Random(21)
    junk = [None, True, 1, -1, 0.0, float("nan"), float("inf"), "", "x", "AAPL", [], {}, [1], {"a": 1}, b"b", object(), "\ud800", 10 ** 500]
    for _ in range(3000):
        o = {k: rng.choice(junk + [v]) for k, v in order().items()}
        o.update({k: rng.choice(junk) for k in ("key_figures", "type", "destination_account") if rng.random() < 0.3})
        s = {k: rng.choice(junk) for k in ("as_of", "now", "daily_total_usd", "revoked", "l7_confirmed") if rng.random() < 0.5}
        r = gate(figure_checker=FakeFigureChecker({})).evaluate(o, s)
        assert r["decision"] in ("allow", "hold", "refuse") and isinstance(r["reasons"], list)
        if r["decision"] == "allow":
            assert normalise_ticker(o.get("ticker"))[0] == "AAPL" or normalise_ticker(o.get("ticker"))[0] == "BRK.B"


def test_market_that_raises_or_returns_garbage_never_allows():
    class Boom:
        def quote(self, t):
            raise RuntimeError("feed down")

        def status(self, t):
            return {}

    class Junk:
        def quote(self, t):
            return {"price": float("nan")}

        def status(self, t):
            return {}

    for market in (Boom(), Junk(), SimMarket({})):
        r = gate(market=market).evaluate(order(), STATE)
        assert r["decision"] == "refuse", type(market).__name__


# ---- the figure checker contract --------------------------------------------------------------------------------------------------------

FIG = {"metric": "revenue", "fiscal_year": 2024, "value": 391035, "unit": "USD millions"}
CHECKED = {"revenue": 391035.0}


def with_checker(checker, figs=(FIG,), **kw):
    return gate(figure_checker=checker, **kw).evaluate(order(key_figures=list(figs)), STATE)


def test_checker_that_raises_times_out_or_returns_nothing_refuses_with_a_fix():
    def raises(*a):
        raise TimeoutError("sec down")

    for checker in (raises, lambda *a: [], lambda *a: None, lambda *a: "ok", lambda *a: [None], lambda *a: [{"status": "confirmed"}, {"status": "confirmed"}]):
        r = with_checker(checker)
        assert r["decision"] == "refuse", checker
        assert "could not be checked" in " ".join(r["reasons"]) and "key_figures" in " ".join(r["reasons"])


def test_unknown_or_missing_status_is_never_confirmed():
    for status in ("looks fine", "", None, "CONFIRMED", 1, "confirmed "):
        r = with_checker(lambda t, d, f, s=status: [{"figure": f[0], "status": s}])
        assert r["decision"] == "refuse", repr(status)
    ok = with_checker(lambda t, d, f: [{"figure": f[0], "status": "confirmed"}])
    assert ok["decision"] == "allow"


def test_key_figures_that_are_not_a_list_refuse():
    for bad in ("revenue 5", {"metric": "revenue"}, 5, True):
        r = gate(figure_checker=FakeFigureChecker({})).evaluate(order(key_figures=bad), STATE)
        assert r["decision"] == "refuse", bad


def test_required_figures_with_no_checker_hold_and_with_no_figures_refuse():
    g = gate(require_figures=True)
    assert g.evaluate(order(), STATE)["decision"] == "refuse"
    assert g.evaluate(order(key_figures=[FIG]), STATE)["decision"] == "hold"


def test_blocking_statuses_refuse_and_unverifiable_holds():
    for st, want in (("contradicted", "refuse"), ("stale", "refuse"), ("not_public_yet", "refuse"), ("unverifiable", "hold")):
        assert with_checker(lambda t, d, f, st=st: [{"figure": f[0], "status": st, "reason": "r"}])["decision"] == want, st


def test_figure_checker_sees_the_normalised_ticker_and_decision_date():
    seen = []
    with_checker(lambda t, d, f: seen.append((t, d)) or [{"figure": f[0], "status": "confirmed"}])
    assert seen == [("AAPL", dt.date(2024, 11, 6))]
