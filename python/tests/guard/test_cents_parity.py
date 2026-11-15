"""Python and the TypeScript receiver must agree, checked against the receiver's own code (node --import tsx, no port, no network):

  cents      orderguard_guard.money.notional_cents == valuation.ts notionalCents on random and exact half-cent cases (finding 6)
  decisions  OrderGate and ReceiverCore give the same allow/hold/refuse on half-cent notionals at the caps (finding 6)
  prices     gate.trusted_price_ok and valuation.ts accept and reject the same reference prices (finding 2)
  mandates   a mandate signed by Python (`orderguard init`) is the exact signed bytes the bridge verifies, with stepUpAboveUsd kept (finding 1)
"""
from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from orderguard_guard import ROOT, init_cmd
from orderguard_guard import gate as G
from orderguard_guard.money import notional_cents

PROBE = Path(__file__).with_name("ts_parity.mts")
pytestmark = pytest.mark.skipif(shutil.which("node") is None or not (ROOT / "node_modules" / "tsx").exists(),
                                reason="node and the npm dependencies (npm ci) are needed to run the TypeScript side")


def ts(payload: dict) -> dict:
    r = subprocess.run(["node", "--no-warnings", "--import", "tsx", str(PROBE), str(ROOT)], input=json.dumps(payload), cwd=str(ROOT),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def _cases() -> list[tuple[int, float]]:
    rng = random.Random(20261115)
    cases = [(1, 1.125), (1, 0.005), (3, 0.335), (7, 1.005), (1, 2.675), (10, 0.0005), (1, 112.5 / 100), (44, 222.7), (440, 22.3)]
    for _ in range(4000):                                   # ordinary prices
        cases.append((rng.randint(1, 100_000), round(rng.uniform(0.01, 5_000), rng.choice([2, 3, 4]))))
    for _ in range(4000):                                   # exact half cents: price = whole cents + 0.005, or half-cent products
        cents = rng.randint(1, 10_000_000)
        cases.append((rng.choice([1, 1, 1, 3, 5, 7, 9, 11]), (cents + 0.5) / 100))
    for _ in range(2000):                                   # mills that make an exact half cent at odd quantities
        cases.append((rng.choice([1, 3, 5, 7, 9]), rng.randint(1, 10**7) / 1000 + 0.0005))
    return cases


def test_notional_cents_match_the_receiver_exactly():
    cases = _cases()
    got = ts({"cents": cases})["cents"]
    mismatches = [(q, p, notional_cents(q, p), t) for (q, p), t in zip(cases, got) if notional_cents(q, p) != t]
    assert not mismatches, mismatches[:10]
    # the cases do exercise the bug: Python's round() (half to even) disagrees with the receiver on some of them
    assert sum(round(q * p * 100) != t for (q, p), t in zip(cases, got)) > 100


def test_gate_and_receiver_decide_half_cent_orders_the_same_way():
    class NoQuotes:
        def quote(self, ticker):
            raise G.UnknownTicker(ticker)
    rng = random.Random(7)
    cases = [{"ref": 1.125, "qty": 1, "cap": 1.12, "daily": 100.0, "stepUp": None},
             {"ref": 1.125, "qty": 1, "cap": 1.13, "daily": 100.0, "stepUp": 1.12},
             {"ref": 1.125, "qty": 1, "cap": 1.13, "daily": 1.12, "stepUp": None}]
    for _ in range(300):
        ref = (rng.randint(1, 100_000) + 0.5) / 100
        qty = rng.choice([1, 1, 3, 5])
        c = notional_cents(qty, ref)
        cap = (c + rng.choice([-1, 0, 0, 1])) / 100
        cases.append({"ref": ref, "qty": qty, "cap": cap, "daily": max(cap, (c + rng.choice([-1, 0, 1, 50])) / 100),
                      "stepUp": rng.choice([None, (c + rng.choice([-1, 0])) / 100])})
    got = ts({"decisions": cases})["decisions"]
    word = {"filled": "allow", "held": "hold", "denied": "refuse"}
    for c, t in zip(cases, got):
        m = {"symbols": ["AAPL"], "sides": ["buy"], "maxOrderNotionalUsd": c["cap"], "maxDailyNotionalUsd": c["daily"], "priceBandPct": 5,
             "expiresAt": "2099-01-01T00:00:00Z", "referencePrices": {"AAPL": c["ref"]}, "stepUpAboveUsd": c["stepUp"]}
        res = G.OrderGate({k: v for k, v in m.items() if v is not None}, NoQuotes()).evaluate(
            {"ticker": "AAPL", "side": "buy", "quantity": c["qty"], "limit_price": c["ref"]}, {"as_of": "2024-11-06"})
        assert res["decision"] == word[t["decision"]], (c, res["reasons"], t)
        if t["notionalUsd"] is not None:
            assert res["checks"]["notional_usd"] == t["notionalUsd"], (c, t)
    assert {t["decision"] for t in got} == {"filled", "held", "denied"}


def test_reference_price_acceptance_matches_the_receiver():
    values = [222.7, 0.01, 1e7, 1e7 + 1, 2e7, 1e12, 0, -0.0, -100, -1e-9, 5e-324, "NaN", "Infinity", "-Infinity", True, "222.7", None]
    got = ts({"refs": values})["refs"]
    py = [G.trusted_price_ok(math.nan if v == "NaN" else math.inf if v == "Infinity" else -math.inf if v == "-Infinity" else v) for v in values]
    assert py == got, list(zip(values, py, got))
    assert G.trusted_price_ok(222.7) and not G.trusted_price_ok(-100)


def test_float_reprs_match_python():
    rng = random.Random(3)
    xs = [0.0, -0.0, 1.0, 10000.0, 222.7, 1e16, 1e15, 9999999999999998.0, 1e-4, 1e-5, 1.5e-5, 0.1, 123456789.125, 5e-324, 1.7976931348623157e308,
          -2.5, 1e22, 1e21, 1e-7, 100.0, 0.30000000000000004]
    xs += [rng.uniform(-1e6, 1e6) for _ in range(500)] + [10 ** rng.uniform(-12, 20) for _ in range(500)]
    got = ts({"floats": xs})["floats"]
    assert got == [repr(float(x)) for x in xs]


def test_a_python_signed_mandate_is_what_the_bridge_verifies(tmp_path):
    """`orderguard init` output, re-signed variants with Python float lexemes, nulls and missing referencePrices, then tampering."""
    home = tmp_path / "home"
    init_cmd.init(home, "deepseek")
    pub = (home / init_cmd.PUB_FILE).read_text().strip()
    priv = G.private_key_from_b64((home / init_cmd.KEY_FILE).read_text().strip())
    texts = [(home / init_cmd.MANDATE_FILE).read_text()]
    bodies = [
        {"symbols": ["AAPL", "MSFT"], "sides": ["buy"], "maxOrderNotionalUsd": 10000.0, "maxDailyNotionalUsd": 20000, "priceBandPct": 5.0,
         "expiresAt": "2099-01-01T00:00:00Z", "referencePrices": {"AAPL": 222.7, "MSFT": 420.18}, "stepUpAboveUsd": 9500.0},
        {"symbols": ["AAPL"], "sides": ["buy", "sell"], "maxOrderNotionalUsd": 0.01, "maxDailyNotionalUsd": 1e11, "priceBandPct": 0.0001,
         "expiresAt": "2099-01-01T00:00:00+00:00", "maxOrdersPerDay": 3, "maxPositionUsd": 12345.67, "maxSymbolDailyNotionalUsd": 99.99},
    ]
    for body in bodies:
        signed = G.sign_mandate(body, priv)
        texts.append(json.dumps(signed, indent=1))
        texts.append(json.dumps({**signed, "stepUpAboveUsd": signed.get("stepUpAboveUsd")}))          # an explicit null is not signed
    tampered = json.loads(texts[1])
    tampered["stepUpAboveUsd"] = 95000.0
    texts.append(json.dumps(tampered))
    extra = json.loads(texts[1])
    extra["stepUpThresholdUsd"] = 1e9                     # a field the signature does not cover: refused, not silently ignored
    texts.append(json.dumps(extra))
    got = ts({"mandates": [{"text": t, "pub": pub} for t in texts]})["mandates"]
    for t, g in zip(texts[:-2], got[:-2]):
        m = G.Mandate.from_dict(json.loads(t))
        assert g["ok"], (t, g)
        assert g["parentId"] == m.id
        if m.stepUpAboveUsd is not None:
            assert g["scope"]["stepUpThresholdUsd"] == m.stepUpAboveUsd       # mapped once, in the secure parser
        assert g["scope"]["maxOrderNotionalUsd"] == m.maxOrderNotionalUsd
    assert not got[-2]["ok"] and "did not verify" in got[-2]["error"]
    assert not got[-1]["ok"] and "does not cover" in got[-1]["error"]
