"""Regression tests for the pre-release authorization review (findings 2, 3, 4 and 6 on the Python side).

2  a non-positive, absurd or unlisted reference price can never size an order (it used to approve an over-cap buy at notional -$100,000)
3  run_agent's daily total survives across calls on the same environment, including concurrent runs
4  signature verification can be required, and `orderguard check-order` never reports a plain allow it could not verify
6  notionals round to integer cents exactly as the TypeScript receiver does (Math.round(qty * price * 100))
"""
from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path

import pytest

from orderguard_guard import cli, init_cmd
from orderguard_guard import gate as G
from orderguard_guard.agent import run_agent
from orderguard_guard.llm import ScriptedLLM
from orderguard_guard.mandate_fit import check_mandate_fit
from orderguard_guard.market import SimMarket, UnknownTicker
from orderguard_guard.money import js_round, notional_cents, usd_cents
from orderguard_arena.envelopes import Envelope, make_envelope, owner_key_from_seed

EX = Path(__file__).resolve().parents[3] / "examples" / "python" / "guarded_agent.py"
FAR = "2099-01-01T00:00:00Z"


class NoQuotes:
    """A trusted market with no quote for anything: the gate falls back to the mandate's reference price."""
    def quote(self, ticker):
        raise UnknownTicker(ticker)


def _body(**over):
    return {"symbols": ["AAPL"], "sides": ["buy"], "maxOrderNotionalUsd": 100, "maxDailyNotionalUsd": 100, "priceBandPct": 300,
            "expiresAt": FAR, "referencePrices": {"AAPL": 222.7}, **over}


# ---- finding 2: reference prices --------------------------------------------------------------------------------------

def test_the_reviewers_negative_reference_price_repro_is_refused():
    priv, pub = G.generate_keypair()
    m = G.sign_mandate(_body(referencePrices={"AAPL": -100}), priv)
    res = G.OrderGate(m, NoQuotes(), public_key=pub).evaluate({"ticker": "AAPL", "side": "buy", "quantity": 1000, "limit_price": 100})
    assert res["decision"] == "refuse", res
    assert "reference price" in res["reasons"][0]
    assert res["checks"].get("notional_usd") is None


@pytest.mark.parametrize("refs", [{"AAPL": -100}, {"AAPL": 0}, {"AAPL": -0.0}, {"AAPL": float("nan")}, {"AAPL": float("inf")},
                                  {"AAPL": 1e8}, {"AAPL": True}, {"AAPL": "222.7"}, {"AAPL": None}, {"TSLA": 250.0}, {"aapl ": 222.7}])
def test_mandate_validation_rejects_unusable_reference_prices(refs):
    with pytest.raises(G.MandateInvalid, match="reference price"):
        G.Mandate.from_dict(_body(referencePrices=refs)).validate()


def test_reference_keys_must_be_listed_symbols():
    G.Mandate.from_dict(_body(symbols=["AAPL", "MSFT"], referencePrices={"AAPL": 222.7, "MSFT": 1e7})).validate()   # 1e7 is the largest
    G.Mandate.from_dict(_body(symbols=["aapl"], referencePrices={"AAPL": 222.7})).validate()      # folded as the gate folds tickers
    with pytest.raises(G.MandateInvalid, match="does not list"):
        G.Mandate.from_dict(_body(symbols=["AAPL", "MSFT"], referencePrices={"TSLA": 222.7})).validate()


@pytest.mark.parametrize("price", [-5.0, 0.0, 2e7, float("nan")])
def test_a_non_positive_or_absurd_market_quote_refuses_instead_of_falling_back(price):
    m = _body(maxOrderNotionalUsd=10_000, maxDailyNotionalUsd=20_000, priceBandPct=5)
    res = G.OrderGate(m, SimMarket({"AAPL": price})).evaluate({"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 222.7})
    assert res["decision"] == "refuse" and res["checks"]["trusted_price"] is None
    assert any("not a usable trusted price" in r for r in res["reasons"]), res["reasons"]


def test_envelopes_refuse_bad_reference_prices_and_bad_feed_prices():
    key = owner_key_from_seed("review")
    with pytest.raises((G.MandateInvalid, ValueError), match="reference price"):
        make_envelope(key, name="bad", symbols=["AAPL"], per_order=100, daily=100, band_pct=300, reference_prices={"AAPL": -100})
    with pytest.raises((G.MandateInvalid, ValueError), match="reference price"):
        Envelope(G.sign_mandate(_body(referencePrices={"AAPL": -100}), key))
    env = make_envelope(key, name="ok", symbols=["AAPL"], per_order=100, daily=100, band_pct=300)
    for bad in (-100.0, 0.0, 2e7):
        reasons, _, notional = env.check("AAPL", None, "buy", 1000, 100.0, bad, 0.0)
        assert reasons and notional is None, (bad, reasons)


def test_mandate_fit_rejects_absurd_reference_prices():
    priv, pub = G.generate_keypair()
    ok = _body(maxDailyNotionalUsd=1000, priceBandPct=5)
    parent = G.sign_mandate(ok, priv)
    assert check_mandate_fit(parent, ok, pub)["fits"] is True
    assert check_mandate_fit(parent, {**ok, "referencePrices": {"AAPL": 2e7}}, pub)["violations"][0]["code"] == "invalid_draft"
    bad_parent = G.sign_mandate({**ok, "referencePrices": {"AAPL": 2e7}}, priv)
    assert check_mandate_fit(bad_parent, ok, pub)["violations"][0]["code"] == "invalid_parent"


# ---- finding 6: one cents rule ------------------------------------------------------------------------------------------

def test_js_round_matches_math_round_on_the_hard_cases():
    # Math.round: ties toward +infinity, and exact (0.49999999999999994 + 0.5 is 1.0 in floating point, Math.round gives 0)
    cases = {0.5: 1, 1.5: 2, 2.5: 3, 112.5: 113, -0.5: 0, -1.5: -1, -2.5: -2, 0.49999999999999994: 0, 4503599627370497.0: 4503599627370497,
             1e300: int(1e300), 0.0: 0, 112.49999999999999: 112}
    for x, want in cases.items():
        assert js_round(x) == want, x
    assert notional_cents(1, 1.125) == 113 and usd_cents(1.12) == 112
    assert round(1 * 1.125 * 100) == 112          # Python's banker's rounding: the rule this replaces


def test_half_cent_notional_is_refused_like_the_receiver():
    m = _body(maxOrderNotionalUsd=1.12, maxDailyNotionalUsd=100, priceBandPct=5, referencePrices={"AAPL": 1.125})
    res = G.OrderGate(m, NoQuotes()).evaluate({"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 1.125})
    assert res["decision"] == "refuse" and res["checks"]["notional_usd"] == 1.13
    env = make_envelope(owner_key_from_seed("cents"), name="c", symbols=["AAPL"], per_order=1.12, daily=100, band_pct=5)
    reasons, _, notional = env.check("AAPL", None, "buy", 1, 1.125, 1.125, 0.0)
    assert reasons and notional == 1.13


def test_step_up_compares_integer_cents():
    m = _body(maxOrderNotionalUsd=100, maxDailyNotionalUsd=100, priceBandPct=5, referencePrices={"AAPL": 1.125}, stepUpAboveUsd=1.12)
    res = G.OrderGate(m, NoQuotes()).evaluate({"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 1.125})
    assert res["decision"] == "hold"


# ---- finding 3: run_agent's daily total ---------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ex():
    spec = importlib.util.spec_from_file_location("guarded_agent_example_review", EX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mandate(ex, priv):
    body = {k: v for k, v in ex.DEMO_MANDATE.items() if k != "stepUpAboveUsd"}      # $10,000 per order, $20,000 per day, no hold
    return G.sign_mandate(body, priv)


def _orders(ex, n):
    buy = {"ticker": "AAPL", "side": "buy", "key_figures": ex.FIGURES, "quantity": 40, "limit_price": 222.70}   # $8,908 each
    return [[("place_order", dict(buy))] for _ in range(n)] + ["done"]


def test_two_runs_on_one_broker_cannot_each_spend_the_daily_cap(ex):
    priv, pub = G.generate_keypair()
    broker = ex.ToyBroker(_mandate(ex, priv))
    for _ in range(2):
        run_agent(ScriptedLLM(_orders(ex, 2)), "Buy Apple.", broker, arm="gate_only", public_key=pub)
    assert len(broker.filled) == 2, "two $8,908 orders fit under $20,000; the second run must find the day already spent"
    second = run_agent(ScriptedLLM(_orders(ex, 1)), "Buy Apple.", broker, arm="gate_only", public_key=pub)
    gate = second["calls"][0]["gate"]
    assert gate["decision"] == "refuse" and any("daily cap" in r for r in gate["reasons"])


def test_concurrent_runs_on_one_broker_share_one_daily_cap(ex):
    priv, pub = G.generate_keypair()
    broker = ex.ToyBroker(_mandate(ex, priv))
    lock = threading.Lock()
    calls = broker.call

    def slow_call(name, args):          # widen the window between the check and the fill
        with lock:
            return calls(name, args)
    broker.call = slow_call
    start = threading.Barrier(8)

    def one():
        start.wait()
        run_agent(ScriptedLLM(_orders(ex, 1)), "Buy Apple.", broker, arm="gate_only", public_key=pub)
    threads = [threading.Thread(target=one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(broker.filled) == 2
    assert sum(usd_cents(40 * 222.70) for _ in broker.filled) <= usd_cents(20_000)


def test_an_explicit_budget_is_shared_across_brokers_and_a_new_day_starts_fresh(ex):
    from orderguard_guard.agent import DailyBudget
    priv, pub = G.generate_keypair()
    budget = DailyBudget()
    a, b = ex.ToyBroker(_mandate(ex, priv)), ex.ToyBroker(_mandate(ex, priv))
    run_agent(ScriptedLLM(_orders(ex, 2)), "Buy Apple.", a, arm="gate_only", public_key=pub, budget=budget)
    run_agent(ScriptedLLM(_orders(ex, 2)), "Buy Apple.", b, arm="gate_only", public_key=pub, budget=budget)
    assert len(a.filled) + len(b.filled) == 2
    tomorrow = ex.ToyBroker(_mandate(ex, priv))
    tomorrow.as_of = "2024-11-07"
    run_agent(ScriptedLLM(_orders(ex, 1)), "Buy Apple.", tomorrow, arm="gate_only", public_key=pub, budget=budget)
    assert len(tomorrow.filled) == 1


def test_a_failed_fill_releases_its_reservation(ex):
    priv, pub = G.generate_keypair()
    broker = ex.ToyBroker(_mandate(ex, priv))
    real = broker.call
    broker.call = lambda name, args: {"status": "rejected", "ledger_effect": False}
    run_agent(ScriptedLLM(_orders(ex, 3)), "Buy Apple.", broker, arm="gate_only", public_key=pub)
    broker.call = real
    run_agent(ScriptedLLM(_orders(ex, 2)), "Buy Apple.", broker, arm="gate_only", public_key=pub)
    assert len(broker.filled) == 2


# ---- finding 4: required signatures --------------------------------------------------------------------------------------

def test_require_signature_refuses_without_a_pinned_key_or_signature():
    priv, pub = G.generate_keypair()
    order = {"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 222.7}
    m = _body(maxOrderNotionalUsd=1000, maxDailyNotionalUsd=1000, priceBandPct=5)
    assert G.OrderGate(m, NoQuotes()).evaluate(order)["decision"] == "allow"                          # lab default unchanged
    res = G.OrderGate(m, NoQuotes(), require_signature=True).evaluate(order)
    assert res["decision"] == "refuse" and "owner's public key" in res["reasons"][0]
    assert G.OrderGate(m, NoQuotes(), public_key=pub, require_signature=True).evaluate(order)["decision"] == "refuse"
    assert G.OrderGate(G.sign_mandate(m, priv), NoQuotes(), public_key=pub, require_signature=True).evaluate(order)["decision"] == "allow"


def test_run_agent_with_a_key_requires_the_signature(ex, monkeypatch):
    seen = {}
    real = G.OrderGate.__init__

    def spy(self, *a, **kw):
        seen.update(kw)
        real(self, *a, **kw)
    monkeypatch.setattr(G.OrderGate, "__init__", spy)
    priv, pub = G.generate_keypair()
    run_agent(ScriptedLLM(["done"]), "Nothing.", ex.ToyBroker(_mandate(ex, priv)), arm="gate_only", public_key=pub)
    assert seen.get("require_signature") is True


def _order_file(tmp_path, quantity=3, limit=200):
    p = tmp_path / "o.json"
    p.write_text(json.dumps({"ticker": "AAPL", "side": "buy", "quantity": quantity, "limit_price": limit}))
    return str(p)


def test_check_order_cli_never_reports_a_plain_allow_it_could_not_verify(tmp_path, capsys):
    home = tmp_path / "home"
    init_cmd.init(home, "deepseek")
    args = ["check-order", _order_file(tmp_path, 1), "--mandate", str(home / "mandate.json"), "--prices", '{"AAPL": 200}']
    assert cli.main(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "allow" and out["signature_verified"] is True
    (home / "signing.pub").unlink()
    assert cli.main(args) == cli.EXIT_ALLOW_UNVERIFIED == 3
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["decision"] == "allow (advisory: mandate signature not verified)" and out["signature_verified"] is False
    assert "NOT checked" in captured.err
    # the built-in demo mandate is unsigned: an allow under it is advisory too
    assert cli.main(["check-order", _order_file(tmp_path, 1, 222.7)]) == 3
    assert json.loads(capsys.readouterr().out)["decision"].startswith("allow (advisory")


def _spy_gates(monkeypatch):
    seen = []
    real = G.OrderGate.__init__

    def spy(self, *a, **kw):
        seen.append(kw)
        real(self, *a, **kw)
    monkeypatch.setattr(G.OrderGate, "__init__", spy)
    return seen


def test_the_mcp_check_order_tool_requires_the_signature(monkeypatch, tmp_path):
    from orderguard_mcp import core
    monkeypatch.setenv("ORDERGUARD_HOME", str(tmp_path / "no-config"))
    core.reset_state()
    seen = _spy_gates(monkeypatch)
    r = core.check_order("AAPL", "buy", 1, 222.7, None, as_of="2024-11-06")
    assert r["mandate"]["signature_verified"] is True and seen and all(kw.get("require_signature") is True for kw in seen)
    core.reset_state()


def test_the_app_check_order_endpoint_requires_the_signature_when_a_key_is_configured(monkeypatch):
    from orderguard_app import services as S
    seen = _spy_gates(monkeypatch)
    state = S.State()
    S.check_order(state, {"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 222.7}, None, None, "2024-11-06", 0.0, False)
    assert seen[-1].get("require_signature") is True


# ---- finding 5 (Python side): paper-receiver always configures a readable revocation list -----------------------------------

def test_paper_receiver_starts_an_empty_revocation_list_but_never_overwrites_one(tmp_path):
    from orderguard_guard.paper_commands import REVOCATIONS, _ensure_revocation_list
    path = tmp_path / REVOCATIONS
    _ensure_revocation_list(path)
    assert json.loads(path.read_text()) == []
    path.write_text('["abc123"]')
    _ensure_revocation_list(path)
    assert json.loads(path.read_text()) == ["abc123"]
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(ValueError, match="revocation list"):
            _ensure_revocation_list(ro / REVOCATIONS)
    finally:
        ro.chmod(0o700)
