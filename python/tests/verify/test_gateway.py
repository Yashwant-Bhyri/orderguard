"""The order step: the mandate, and what each decision about the text means for an order."""
from pathlib import Path

from orderguard_verify.finance.mandate import check_mandate
from orderguard_verify.finance.models import Mandate, Order

MANDATE = Mandate(allowed_tickers=["ACME"], max_order_shares=1000, max_order_notional=100_000)
TRUE_CLAIM = {"text": "revenue of $5.0 billion", "type": "fundamental", "ticker": "ACME", "metric": "revenue",
              "period": "FY2024", "value": 5.0e9, "unit": "USD", "main_reason": True}
FALSE_CLAIM = dict(TRUE_CLAIM, text="revenue of $6.5 billion", value=6.5e9)
RUMOUR = {"text": "ACME is in talks to buy a rival", "type": "rumour", "ticker": "ACME", "key": True}
MEMO = "ACME had revenue of $5.0 billion in fiscal 2024. Buy."


def order(qty=500, **kw):
    return dict(ticker="ACME", side="buy", quantity=qty, as_of="2025-03-04", **kw)


def test_each_decision_maps_to_one_order_status(make_gateway):
    assert make_gateway([TRUE_CLAIM], MANDATE).propose(MEMO, order())["status"] == "cleared"
    assert make_gateway([FALSE_CLAIM], MANDATE).propose(MEMO.replace("5.0", "6.5"), order())["status"] == "blocked"
    held = make_gateway([TRUE_CLAIM, dict(RUMOUR, main_reason=True)], MANDATE).propose(MEMO + " ACME is in talks to buy a rival.", order())
    assert held["status"] == "held"
    returned = make_gateway([TRUE_CLAIM, RUMOUR], MANDATE).propose(MEMO + " ACME is in talks to buy a rival.", order())
    assert returned["status"] == "returned" and returned["fix"] == [{"claim": "ACME is in talks to buy a rival"}]


def test_mandate_violations_block_even_when_every_claim_is_true(make_gateway):
    gw = make_gateway([TRUE_CLAIM], MANDATE)
    assert gw.propose(MEMO, order(qty=1001))["status"] == "blocked"                 # over per-order shares
    assert gw.propose(MEMO, dict(order(), ticker="ZZZZ"))["status"] == "blocked"    # not on the list
    assert gw.propose(MEMO, order(qty=900))["status"] == "cleared"                  # inside every limit


def test_order_size_by_notional(store):
    big = Mandate(allowed_tickers=["ACME"], max_order_shares=10_000, max_order_notional=20_000)
    assert "notional" in check_mandate(Order(**order(qty=400)), big, store)[0]


def test_no_reference_price_fails_closed(store):
    assert "no reference price" in check_mandate(Order(ticker="ACME", side="buy", quantity=1, as_of="2023-01-01"), MANDATE, store)[0]


def test_mandate_details_are_not_leaked_to_the_agent(make_gateway):
    reply = make_gateway([TRUE_CLAIM], MANDATE).propose(MEMO, order(qty=5000))
    assert reply["reasons"][0] == "the request is outside the signed mandate" and "5000" not in " ".join(reply["reasons"])


def test_held_order_waits_for_a_human_then_is_cleared_or_rejected(make_gateway):
    gw = make_gateway([TRUE_CLAIM, dict(RUMOUR, main_reason=True)], MANDATE)
    memo = MEMO + " ACME is in talks to buy a rival."
    reply = gw.propose(memo, order())
    assert reply["status"] == "held" and gw.pending() == [reply["run_id"]]
    assert gw.review(reply["run_id"], approve=True)["status"] == "approved_cleared"
    again = gw.propose(memo, order())
    assert gw.review(again["run_id"], approve=False)["status"] == "rejected"


def test_there_is_no_real_money_path_in_the_source():
    src = "\n".join(p.read_text() for p in Path(__file__).resolve().parents[1].glob("orderguard_verify/**/*.py"))
    assert "TrdEnv" not in src and "place_order" not in src


def test_stale_data_is_refreshed_and_rechecked_once(store):
    """The newest filing in the store is old, so a 'latest quarter' claim is stale -> refresh -> the re-check sees the new filing."""
    from conftest import scripted, snap
    from orderguard_verify.core.gateway import Gateway
    from orderguard_verify.finance.pack import FinancePack

    calls = []
    store.add(snap("ACME", "price", None, 55.10, "2025-09-29", claim_type="price", duration=None))   # a fresh trusted quote for sizing

    def refresh(s, ticker):
        calls.append(ticker)
        s.add(snap("ACME", "revenue", "Q2 FY2025", 1.5e9, "2025-08-08", duration="Q", period_end="2025-06-30"))

    claim = {"text": "latest quarter revenue of $1.5 billion", "type": "fundamental", "ticker": "ACME", "metric": "revenue",
             "period": "latest_q", "value": 1.5e9, "unit": "USD", "main_reason": True}
    gw = Gateway(FinancePack(store, MANDATE, refresh_fn=refresh), ask=scripted([claim]), db_path=":memory:", clock=lambda: __import__("datetime").date(2025, 9, 30))
    assert gw.propose("ACME had latest quarter revenue of $1.5 billion. Buy.", dict(order(), as_of="2025-09-30"))["status"] == "cleared"
    assert calls == ["ACME"]


def test_a_failing_refresh_never_crashes_a_request(store):
    from conftest import scripted, snap
    from orderguard_verify.core.gateway import Gateway
    from orderguard_verify.finance.pack import FinancePack

    store.add(snap("ACME", "price", None, 55.10, "2025-09-29", claim_type="price", duration=None))

    def broken(s, t):
        raise OSError("network down")

    claim = {"text": "latest quarter revenue of $1.5 billion", "type": "fundamental", "ticker": "ACME", "metric": "revenue",
             "period": "latest_q", "value": 1.5e9, "unit": "USD", "main_reason": True}
    gw = Gateway(FinancePack(store, MANDATE, refresh_fn=broken), ask=scripted([claim]), db_path=":memory:", clock=lambda: __import__("datetime").date(2025, 9, 30))
    assert gw.propose("x latest quarter revenue of $1.5 billion", dict(order(), as_of="2025-09-30"))["status"] == "returned"
