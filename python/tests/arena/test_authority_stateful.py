"""Seeded model-based interleavings for shared budget and portfolio reservations."""
from __future__ import annotations

import random

import pytest

from orderguard_arena.authority import Authority
from orderguard_arena.envelopes import EnvelopeBook, make_envelope, owner_key_from_seed

PRICE = 100.0
STEPS_PER_DAY = 10
PER_ORDER, DAILY, SYMBOL_DAILY, POSITION, ORDER_COUNT, STEP_UP = 1000.0, 2500.0, 1500.0, 1000.0, 4, 300.0


def operation_sequence(seed: int = 774192, count: int = 240) -> list[dict]:
    """Pre-generate every input so a failing prefix can be replayed exactly."""
    rng = random.Random(seed)
    return [{"choice": rng.random(), "roll": rng.randint(STEPS_PER_DAY, 2 * STEPS_PER_DAY),
             "approval_pick": rng.randrange(1_000_000), "qty": rng.randint(1, 15),
             "side": rng.choice(("buy", "sell"))} for _ in range(count)]


def run_against_model(operations: list[dict]) -> None:
    key = owner_key_from_seed("state-machine")
    book = EnvelopeBook(key.public_key())
    book.add(make_envelope(key, name="state", symbols=("AAPL",), per_order=PER_ORDER, daily=DAILY,
                           band_pct=5.0, step_up=STEP_UP, reference_prices={"AAPL": PRICE},
                           max_symbol_daily=SYMBOL_DAILY, max_position=POSITION, max_orders_per_day=ORDER_COUNT))
    authority = Authority(book, steps_per_day=STEPS_PER_DAY)
    authority.set_prices({"AAPL": PRICE})
    model = {"revoked": False, "used": {}, "symbol_used": {}, "orders": {}, "net": 0,
             "held_buy": 0, "held_sell": 0, "pending": {}}
    step = 0

    def authorize_model(qty: int, side: str, day: int) -> str:
        notional = qty * PRICE
        if model["revoked"] or notional > PER_ORDER:
            return "refuse"
        if model["used"].get(day, 0.0) + notional > DAILY:
            return "refuse"
        if model["symbol_used"].get((day, "AAPL"), 0.0) + notional > SYMBOL_DAILY:
            return "refuse"
        if model["orders"].get(day, 0) + 1 > ORDER_COUNT:
            return "refuse"
        signed_qty = qty if side == "buy" else -qty
        exposure = max(abs(model["net"] + model["held_buy"] + signed_qty),
                       abs(model["net"] - model["held_sell"] + signed_qty))
        if exposure * PRICE > POSITION:
            return "refuse"
        model["used"][day] = model["used"].get(day, 0.0) + notional
        model["symbol_used"][(day, "AAPL")] = model["symbol_used"].get((day, "AAPL"), 0.0) + notional
        model["orders"][day] = model["orders"].get(day, 0) + 1
        if notional > STEP_UP:
            model["held_buy" if side == "buy" else "held_sell"] += qty
            return "hold"
        model["net"] += signed_qty
        return "allow"

    def assert_state(day: int, turn: int) -> None:
        env = book.get("state")
        assert env is not None, turn
        assert env.budget.used(day) == model["used"].get(day, 0.0), turn
        assert env.budget.total_by_day() == model["used"], turn
        actual = env.portfolio_state(day)
        expected_symbol = {"AAPL": model["symbol_used"][(day, "AAPL")]} if (day, "AAPL") in model["symbol_used"] else {}
        assert actual["symbol_daily_usd"] == expected_symbol, turn
        assert actual["orders_today"] == model["orders"].get(day, 0), turn
        normalized_net = {k: v for k, v in actual["positions"].items() if v}
        assert normalized_net == ({"AAPL": model["net"]} if model["net"] else {}), turn
        actual_held = {ticker: {side: qty for side, qty in sides.items() if qty}
                       for ticker, sides in actual["held_qty"].items() if any(sides.values())}
        expected_held = {"AAPL": {side: qty for side, qty in (("buy", model["held_buy"]), ("sell", model["held_sell"])) if qty}}
        assert actual_held == (expected_held if model["held_buy"] or model["held_sell"] else {}), turn
        assert set(authority.pending) == set(model["pending"]), turn

    for turn, op in enumerate(operations):
        choice = op["choice"]
        if choice < 0.12:
            step += op["roll"]
        elif choice < 0.20 and not model["revoked"]:
            authority.revoke("state")
            model["revoked"] = True
        elif choice < 0.42:
            if model["pending"]:
                pending_key = sorted(model["pending"])[op["approval_pick"] % len(model["pending"])]
                expected = model["pending"].pop(pending_key)
                decision = authority.approve(pending_key, step=step)
                if model["revoked"] or expected["decision"] == "refuse":
                    assert decision.decision == "refuse", (turn, decision)
                else:
                    assert decision.decision == "allow", (turn, decision)
                    model["held_buy"] -= expected["qty"] if expected["side"] == "buy" else 0
                    model["held_sell"] -= expected["qty"] if expected["side"] == "sell" else 0
                    model["net"] += expected["qty"] if expected["side"] == "buy" else -expected["qty"]
            else:
                assert authority.approve("missing", step=step).decision == "refuse", turn
        else:
            order_key = f"model-{turn}"
            qty, side = op["qty"], op["side"]
            day = step // STEPS_PER_DAY
            expected = authorize_model(qty, side, day)
            actual = authority.authorize({"ticker": "AAPL", "side": side, "quantity": qty, "limit_price": PRICE},
                                         key=order_key, step=step)
            assert actual.decision == expected, (turn, day, qty, side, expected, actual)
            if expected == "hold":
                model["pending"][order_key] = {"decision": expected, "qty": qty, "side": side}
        assert_state(step // STEPS_PER_DAY, turn)


def test_random_reserve_hold_approve_revoke_and_day_rollover_match_reference_model():
    operations = operation_sequence()
    try:
        run_against_model(operations)
    except AssertionError as original:
        # A failing prefix remains failing, so bisection finds the first operation that breaks parity.
        low, high = 1, len(operations)
        while low < high:
            middle = (low + high) // 2
            try:
                run_against_model(operations[:middle])
            except AssertionError:
                high = middle
            else:
                low = middle + 1
        pytest.fail(f"reference-model mismatch after operation {low}: {original}; operation={operations[low - 1]!r}")
