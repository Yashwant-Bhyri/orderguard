import datetime as dt
import random

import pytest

from orderguard_guard.gate import Mandate, generate_keypair, sign_mandate
from orderguard_guard.mandate_fit import check_mandate_fit

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
BASE = {
    "symbols": ["AAPL", "MSFT"], "sides": ["buy"], "maxOrderNotionalUsd": 10_000,
    "maxDailyNotionalUsd": 100_000, "priceBandPct": 3, "stepUpAboveUsd": 5_000,
    "expiresAt": "2026-02-01T00:00:00Z", "referencePrices": {"AAPL": 100, "MSFT": 200},
}


@pytest.fixture
def owner():
    key, pub = generate_keypair()
    return sign_mandate(BASE, key), pub


def fit(owner, draft, **kwargs):
    parent, pub = owner
    return check_mandate_fit(parent, draft, pub, now=NOW, **kwargs)


def test_equal_and_narrower_drafts(owner):
    assert fit(owner, BASE)["fits"]
    draft = BASE | {"symbols": ["AAPL"], "referencePrices": {"AAPL": 100}, "maxOrderNotionalUsd": 4999.99,
                    "maxDailyNotionalUsd": 50_000, "priceBandPct": 2, "expiresAt": "2026-01-15T00:00:00+00:00",
                    "stepUpAboveUsd": None}
    # Dropping the threshold is harmless here because every order is below the parent's approval threshold.
    result = fit(owner, draft)
    assert result["fits"] and result["violations"] == []
    assert "signature" not in result["draft"] and "stepUpAboveUsd" not in result["draft"]
    assert result["parent_id"] == Mandate.from_dict(owner[0]).id


@pytest.mark.parametrize(("edit", "code"), [
    ({"symbols": ["AAPL", "MSFT", "NVDA"]}, "symbols"),
    ({"sides": ["buy", "sell"]}, "sides"),
    ({"maxOrderNotionalUsd": 10_000.01}, "order_cap"),
    ({"maxDailyNotionalUsd": 100_000.01}, "daily_cap"),
    ({"priceBandPct": 3.00001}, "price_band"),
    ({"stepUpAboveUsd": 5_000.01}, "step_up"),
    ({"stepUpAboveUsd": None}, "step_up"),
    ({"expiresAt": "2026-01-31T23:00:01-01:00"}, "expiry"),
    ({"expiresAt": "2026-01-01T00:00:00Z"}, "expiry"),
    ({"referencePrices": {"AAPL": 99, "MSFT": 200}}, "reference_prices"),
    ({"referencePrices": {"AAPL": 100}}, "reference_prices"),
])
def test_authority_expansions_are_refused(owner, edit, code):
    result = fit(owner, BASE | edit)
    assert not result["fits"] and result["draft"] is None
    assert [v["code"] for v in result["violations"]] == [code]


@pytest.mark.parametrize(("field", "value"), [
    ("symbols", ["АAPL"]), ("symbols", ["AAPL", "AAPL"]), ("symbols", "AAPL"),
    ("maxOrderNotionalUsd", True), ("maxOrderNotionalUsd", 0.001), ("maxOrderNotionalUsd", 10**400),
    ("maxDailyNotionalUsd", float("inf")), ("priceBandPct", float("nan")), ("expiresAt", "2026-03-01"),
    ("referencePrices", {"NVDA": 10}), ("signature", "irrelevant"), ("delegation", True),
])
def test_malformed_draft_fails_closed(owner, field, value):
    result = fit(owner, BASE | {field: value})
    assert not result["fits"] and result["violations"][0]["code"] == "invalid_draft"


def test_parent_must_be_signed_current_unmodified_and_pinned(owner):
    parent, pub = owner
    _, other = generate_keypair()
    for raw, trust in ((BASE, pub), (parent, other), (parent | {"maxDailyNotionalUsd": 200_000}, pub)):
        result = fit((raw, trust), BASE)
        assert result["violations"][0]["code"] == "untrusted_parent" and result["parent_id"] is None
    assert not fit(owner, BASE, revoked={Mandate.from_dict(parent).id})["fits"]
    assert not check_mandate_fit(parent, BASE, pub, now=NOW + dt.timedelta(days=35))["fits"]


def test_any_accepted_automatic_order_is_within_parent_approval_threshold(owner):
    rng = random.Random(42)
    for _ in range(100):
        order_cap = rng.randint(1, 10_000)
        step_up = rng.choice([None, rng.randint(0, 10_000)])
        decision = fit(owner, BASE | {"maxOrderNotionalUsd": order_cap, "stepUpAboveUsd": step_up})
        # An executable order just above the parent's approval threshold is the smallest bypass witness.
        witness = BASE["stepUpAboveUsd"] + 0.01
        can_bypass = witness <= order_cap and (step_up is None or witness <= step_up)
        assert decision["fits"] == (not can_bypass)
