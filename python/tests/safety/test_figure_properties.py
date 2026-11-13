"""L6 figure check (orderguard_verify.api.check_figures) on an offline truth store: no network (`fetch=False`, in-memory store)."""
from __future__ import annotations

import functools
import random
from datetime import date

import pytest
from safety_common import OWNER_PUB, make_market, signed

from orderguard_guard.gate import OrderGate
from orderguard_verify import api
from orderguard_verify.finance.truth_store import Snapshot, TruthStore

STATUSES = {"confirmed", "contradicted", "stale", "not_public_yet", "unverifiable"}
LATE = date(2026, 1, 1)


def snap(ticker, metric, period, value, as_of, *, duration="FY", period_end, unit="USD"):
    return Snapshot(claim_type="fundamental", ticker=ticker, metric=metric, period=period, duration=duration, period_end=period_end, value=value, unit=unit,
                    as_of=as_of, source="test filing", source_url="https://example.test/filing/0001", hash="h" * 64)


def world(rng: random.Random):
    """One company with FY2022..FY2024 revenue (FY2023 restated later), a Q4 FY2024 quarter and diluted EPS; values are whole millions."""
    m = lambda: rng.randint(2_000, 900_000) * 1_000_000                       # noqa: E731  USD, whole millions
    fy22, fy23, fy23r, fy24 = m(), m(), m(), m()
    q4 = rng.randint(100, 1_999) * 1_000_000
    s = TruthStore(":memory:")
    for sn in (snap("ACME", "revenue", "FY2022", fy22, "2023-02-15", period_end="2022-12-31"),
               snap("ACME", "revenue", "FY2023", fy23, "2024-02-15", period_end="2023-12-31"),
               snap("ACME", "revenue", "FY2023", fy23r, "2024-09-01", period_end="2023-12-31"),
               snap("ACME", "revenue", "FY2024", fy24, "2025-02-14", period_end="2024-12-31"),
               snap("ACME", "revenue", "Q4 FY2024", q4, "2025-02-14", duration="Q", period_end="2024-12-31"),
               snap("ACME", "eps_diluted", "FY2024", round(rng.uniform(0.5, 30), 2), "2025-02-14", period_end="2024-12-31", unit="USD/share")):
        s.add(sn)
    s.commit()
    return s, {"fy22": fy22, "fy23": fy23, "fy23r": fy23r, "fy24": fy24, "q4": q4}


def check(store, fig, as_of=LATE):
    return api.check_figures("ACME", as_of, [fig], store=store, fetch=False)[0]


def rev(fy, value, unit, **kw):
    return {"metric": "revenue", "fiscal_year": fy, "value": value, "unit": unit, **kw}


UNITS = [("USD", 1.0), ("USD millions", 1e6), ("USD billions", 1e9), ("USD thousands", 1e3)]


def test_the_same_truth_is_confirmed_in_every_unit_and_a_wrong_unit_is_not():
    rng = random.Random(1)
    for _ in range(400):
        store, v = world(rng)
        for unit, scale in UNITS:
            assert check(store, rev(2024, v["fy24"] / scale, unit))["status"] == "confirmed", (unit, v["fy24"])
        wrong = rng.choice([u for u in UNITS if u[0] != "USD millions"])
        # the number is in millions but the stated unit says otherwise: never confirmed
        r = check(store, rev(2024, v["fy24"] / 1e6, wrong[0]))
        assert r["status"] != "confirmed"


def test_a_thousandfold_or_millionfold_unit_slip_is_named_as_a_unit_error():
    rng = random.Random(2)
    n = 0
    for _ in range(400):
        store, v = world(rng)
        r = check(store, rev(2024, v["fy24"] / 1e6, "USD billions"))                   # millions written as billions: x1000 too large
        if r["status"] == "contradicted" and "factor" in r["reason"]:
            n += 1
        assert r["status"] == "contradicted"
    assert n >= 300


def test_a_quarterly_figure_cited_as_annual_is_contradicted():
    rng = random.Random(3)
    for _ in range(400):
        store, v = world(rng)
        r = check(store, rev(2024, v["q4"] / 1e6, "USD millions"))
        assert r["status"] == "contradicted" and "quarterly figure cited as annual" in r["reason"], r["reason"]
        assert check(store, rev(2024, v["q4"] / 1e6, "USD millions", period="Q4"))["status"] == "confirmed"


def test_last_years_figure_cited_as_this_years_is_contradicted():
    rng = random.Random(4)
    n = 0
    for _ in range(400):
        store, v = world(rng)
        if v["fy23r"] == v["fy24"] or v["fy23r"] == v["fy22"]:
            continue
        r = check(store, rev(2024, v["fy23r"] / 1e6, "USD millions"))
        assert r["status"] == "contradicted" and "FY2023" in r["reason"], r["reason"]
        n += 1
    assert n > 350


def test_stale_figures_are_flagged_after_the_restatement_and_confirmed_before_it():
    rng = random.Random(5)
    n = 0
    for _ in range(400):
        store, v = world(rng)
        if v["fy23"] == v["fy23r"]:
            continue
        n += 1
        old, new = v["fy23"] / 1e6, v["fy23r"] / 1e6
        assert check(store, rev(2023, old, "USD millions"), date(2024, 6, 1))["status"] == "confirmed"            # before the restatement
        assert check(store, rev(2023, old, "USD millions"), date(2024, 6, 1))["source"]["filed"] == "2024-02-15"
        assert check(store, rev(2023, old, "USD millions"), LATE)["status"] == "stale"                            # after it
        assert check(store, rev(2023, new, "USD millions"), LATE)["status"] == "confirmed"
        assert check(store, rev(2023, new, "USD millions"), date(2024, 6, 1))["status"] == "not_public_yet"       # the restated value did not exist yet
    assert n > 350


def test_a_figure_cannot_be_used_before_its_filing_date():
    rng = random.Random(6)
    for _ in range(300):
        store, v = world(rng)
        r = check(store, rev(2024, v["fy24"] / 1e6, "USD millions"), date(2025, 2, 13))
        assert r["status"] == "not_public_yet"
        assert check(store, rev(2024, v["fy24"] / 1e6, "USD millions"), date(2025, 2, 14))["status"] == "confirmed"


def test_more_than_two_percent_off_is_never_confirmed_and_exact_always_is():
    rng = random.Random(7)
    for _ in range(1500):
        store, v = world(rng)
        err = rng.choice([-1, 1]) * rng.uniform(0.0201, 0.9)
        wrong = v["fy24"] * (1 + err)
        assert check(store, rev(2024, wrong, "USD"))["status"] != "confirmed", err
        assert check(store, rev(2024, v["fy24"], "USD"))["status"] == "confirmed"
        assert check(store, rev(2024, v["fy24"] * (1 + 1e-12), "USD"))["status"] == "confirmed"


def test_figure_checking_never_raises_on_garbage_and_never_confirms_it():
    rng = random.Random(8)
    store, v = world(rng)
    junk_values = [None, "", "abc", "1e999", float("nan"), float("inf"), -1, 0, True, [1], {"v": 1}, "$", "((5))", "5 furlongs", "9" * 400, 10 ** 30]
    junk_metrics = [None, "", "revenu", "EPS", "net sales", 5, "revenue; DROP TABLE", "price"]
    junk_units = [None, "", "furlongs", "USD/share", 7, "USD millions millions", "$M", "bn"]
    junk_fy = [None, "2024", 2024.5, 1800, 3000, True, -1, "FY2024", 2024]
    seen = set()
    for _ in range(3000):
        fig = {k: rng.choice(opts) for k, opts in (("metric", junk_metrics + ["revenue"] * 4), ("value", junk_values + [v["fy24"]]), ("unit", junk_units + ["USD"]),
                                                    ("fiscal_year", junk_fy))}
        if rng.random() < 0.1:
            fig = rng.choice([None, 5, "x", [], {}])
        out = api.check_figures(rng.choice(["ACME", "acme", "", None, "A C", "ZZZZ", "../x"]), rng.choice([LATE, "2025-06-01"]), [fig], store=store, fetch=False)
        assert len(out) == 1 and out[0]["status"] in STATUSES
        seen.add(out[0]["status"])
        if out[0]["status"] == "confirmed":
            assert fig["metric"] == "revenue" and fig["fiscal_year"] == 2024 and fig["value"] == v["fy24"] and fig["unit"] == "USD"
    assert {"unverifiable", "confirmed"} <= seen


def test_an_unknown_company_is_unverifiable_not_confirmed_and_never_fetches():
    store, v = world(random.Random(9))
    for t in ("NOPE", "QNTX", "AAPL"):
        r = api.check_figures(t, LATE, [rev(2024, 1, "USD millions")], store=store, fetch=False)[0]
        assert r["status"] == "unverifiable" and "truth store" in r["reason"]


def test_figure_results_have_the_documented_shape():
    store, v = world(random.Random(10))
    r = check(store, rev(2024, v["fy24"] / 1e6, "USD millions"))
    assert set(r) == {"figure", "status", "truth", "unit", "source", "reason"} and r["unit"] == "USD millions" and r["truth"] == pytest.approx(v["fy24"] / 1e6)
    assert set(r["source"]) == {"form", "filed", "url", "accession"}


def test_the_gate_never_lets_a_contradicted_stale_or_future_figure_through():
    """L6 behind L5 with the real checker on the offline store: random figures on random orders; only confirmed figures may allow."""
    rng = random.Random(11)
    market = make_market()
    market.set("ACME", 100.0)
    mandate = signed({"symbols": ["ACME"], "sides": ["buy"], "maxOrderNotionalUsd": 1e9, "maxDailyNotionalUsd": 1e9, "priceBandPct": 5, "expiresAt": "2030-01-01T00:00:00Z",
                      "referencePrices": {}})
    for _ in range(400):
        store, v = world(rng)
        checker = functools.partial(api.check_figures, store=store, fetch=False)
        kind = rng.choice(["ok", "quarter", "lastyear", "unit", "stale", "future"])
        as_of = "2026-01-01"
        fig = {"ok": rev(2024, v["fy24"] / 1e6, "USD millions"), "quarter": rev(2024, v["q4"] / 1e6, "USD millions"),
               "lastyear": rev(2024, v["fy23r"] / 1e6, "USD millions"), "unit": rev(2024, v["fy24"] / 1e6, "USD billions"),
               "stale": rev(2023, v["fy23"] / 1e6, "USD millions"), "future": rev(2024, v["fy24"] / 1e6, "USD millions")}[kind]
        if kind == "future":
            as_of = "2025-01-01"
        if kind == "lastyear" and v["fy23r"] in (v["fy24"], v["fy22"]):
            continue
        if kind == "stale" and v["fy23"] == v["fy23r"]:
            continue
        res = OrderGate(mandate, market, checker, public_key=OWNER_PUB, require_figures=True).evaluate(
            {"ticker": "ACME", "side": "buy", "quantity": 1, "limit_price": 100.0, "key_figures": [fig]}, {"as_of": as_of})
        assert (res["decision"] == "allow") == (kind == "ok"), (kind, res["decision"], res["reasons"])
