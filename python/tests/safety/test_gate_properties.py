"""L5 gate: randomized safety invariants (fixed seeds, no network).

Guarantee under test: whatever the agent puts in an order, an `allow` or `hold` never exceeds what the human-signed mandate permits,
valued at the TRUSTED price; any tampering with a signed mandate refuses; the order's own numbers cannot widen anything.
"""
from __future__ import annotations

import base64
import copy
import datetime as dt
import json
import random
import unicodedata

import pytest
from safety_common import AS_OF, OWNER_PRIV, OWNER_PUB, ATTACKER_PRIV, PRICES, make_market, random_mandate, random_order, signed

from orderguard_guard.gate import (APPLE_FY2024_TRUTH, FakeFigureChecker, Mandate, MandateInvalid, OrderGate, canonical_json, sign_mandate)

N = 1500
STATE0 = {"as_of": AS_OF}
CHECKER = FakeFigureChecker(APPLE_FY2024_TRUTH)


def to_float(x):
    """Independent number reader for the oracle: finite floats only, bools and junk are not numbers."""
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(str(x).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def all_ascii_after_nfkc(raw) -> bool:
    return unicodedata.normalize("NFKC", str(raw)).strip().isascii()


def oracle(m: dict, market, order: dict, state: dict, revoked: bool) -> dict:
    """What the mandate permits, written from the spec rather than from gate.py. Returns violations plus whether a hold is due."""
    now = dt.datetime.fromisoformat(AS_OF + "T00:00:00+00:00")
    out = {"violations": [], "hold": False}
    if revoked or now >= dt.datetime.fromisoformat(m["expiresAt"].replace("Z", "+00:00")):
        out["violations"].append("mandate")
        return out
    raw = order.get("ticker")
    norm = unicodedata.normalize("NFKC", str(raw or "")).strip().upper()
    allowed = {unicodedata.normalize("NFKC", s).upper() for s in m["symbols"]}
    if not norm or not norm.isascii() or norm not in allowed:
        out["violations"].append("ticker")
    side = str(order.get("side", "")).strip().lower()
    if side not in ("buy", "sell") or side not in [s.lower() for s in m["sides"]]:
        out["violations"].append("side")
    qty, limit = to_float(order.get("quantity")), to_float(order.get("limit_price"))
    trusted = market.quote(norm)["price"] if norm in PRICES else None
    if qty is None or qty <= 0 or qty != int(qty):
        out["violations"].append("quantity")
    if limit is None or limit <= 0:
        out["violations"].append("limit")
    if trusted is None:
        trusted = m["referencePrices"].get(norm)
    if trusted is None:
        out["violations"].append("no price")
    elif qty is not None and qty > 0 and qty == int(qty):
        notional = round(qty * trusted, 2)
        if notional > m["maxOrderNotionalUsd"]:
            out["violations"].append("per-order cap")
        if state.get("daily_total_usd", 0.0) + notional > m["maxDailyNotionalUsd"]:
            out["violations"].append("daily cap")
        if "stepUpAboveUsd" in m and notional > m["stepUpAboveUsd"]:
            out["hold"] = True
        if limit is not None and limit > 0 and abs((limit - trusted) / trusted) > m["priceBandPct"] / 100 + 1e-12:
            out["violations"].append("band")
    return out


def run_gate(m_signed: dict, market, order: dict, state: dict, *, revoked=False, checker=None, **kw):
    try:
        g = OrderGate(m_signed, market, checker, public_key=OWNER_PUB, **kw)
    except MandateInvalid as e:                 # a mandate missing a required field is rejected at construction: fail closed
        return {"decision": "refuse", "reasons": [str(e)], "checks": {"mandate": "invalid"}}
    if revoked:
        g.revoke()
    return g.evaluate(order, state)


def test_allow_and_hold_never_exceed_the_signed_mandate():
    rng = random.Random(20241106)
    seen = {"allow": 0, "hold": 0, "refuse": 0}
    for _ in range(N):
        raw = random_mandate(rng)
        m = signed(raw)
        market = make_market(rng)
        order = random_order(rng, raw, {t: market.quote(t)["price"] for t in PRICES}, friendly=0.6)
        state = {"as_of": AS_OF, "daily_total_usd": rng.choice([0.0, 0.0, raw["maxDailyNotionalUsd"] * rng.random(), raw["maxDailyNotionalUsd"] * 1.2])}
        revoked = rng.random() < 0.05
        res = run_gate(m, market, order, state, revoked=revoked)
        seen[res["decision"]] += 1
        o = oracle(m, market, order, state, revoked)
        if res["decision"] in ("allow", "hold"):
            assert not o["violations"], (res["decision"], o["violations"], raw, order, state, res["reasons"])
            ticker = res["checks"]["ticker"]["normalised"]
            assert ticker.isascii() and ticker in {unicodedata.normalize("NFKC", s).upper() for s in raw["symbols"]}
            assert res["checks"]["notional_usd"] <= raw["maxOrderNotionalUsd"]
            assert res["checks"]["daily_total_after_usd"] <= raw["maxDailyNotionalUsd"]
            assert abs(res["checks"]["limit_vs_trusted_pct"]) <= raw["priceBandPct"] + 1e-9
            if res["decision"] == "allow" and "stepUpAboveUsd" in raw:
                assert res["checks"]["notional_usd"] <= raw["stepUpAboveUsd"]
        if res["decision"] == "allow":
            assert not o["hold"]
        if not o["violations"]:                          # liveness: a fully permitted order is not refused
            assert res["decision"] == ("hold" if o["hold"] else "allow"), (raw, order, state, res["reasons"])
        else:
            assert res["decision"] == "refuse", (o["violations"], raw, order, state)
    assert min(seen.values()) >= 50, seen                  # the generator really exercises all three outcomes


def test_lookalike_and_invisible_tickers_are_never_allowed():
    rng = random.Random(7)
    market = make_market()
    from safety_common import GREEK, HOMOGLYPHS, ZERO_WIDTH
    n = 0
    for _ in range(N):
        raw = random_mandate(rng, live=True)
        raw["sides"] = ["buy", "sell"]
        raw["maxOrderNotionalUsd"] = raw["maxDailyNotionalUsd"] = 1e9
        raw["priceBandPct"] = 50
        raw.pop("stepUpAboveUsd", None)
        base = rng.choice(raw["symbols"]).upper()
        tweak = rng.choice(["cyr", "greek", "zw"])
        i = rng.randrange(len(base))
        if tweak == "zw":
            t = base[:i] + rng.choice(ZERO_WIDTH) + base[i:]
        else:
            table = HOMOGLYPHS if tweak == "cyr" else GREEK
            if base[i] not in table:
                continue
            t = base[:i] + table[base[i]] + base[i + 1:]
        n += 1
        price = PRICES[base]
        res = run_gate(signed(raw), market, {"ticker": t, "side": "buy", "quantity": 1, "limit_price": price}, STATE0)
        assert res["decision"] == "refuse", (t, res)
    assert n > 500


def test_any_tampering_with_a_signed_mandate_refuses():
    rng = random.Random(99)
    market = make_market()
    good_order = lambda m: {"ticker": m["symbols"][0], "side": m["sides"][0], "quantity": 1, "limit_price": PRICES[m["symbols"][0].upper()]}   # noqa: E731
    fields = ["symbols", "sides", "maxOrderNotionalUsd", "maxDailyNotionalUsd", "priceBandPct", "expiresAt", "referencePrices", "stepUpAboveUsd"]
    for _ in range(N):
        raw = random_mandate(rng, live=True)
        raw["maxOrderNotionalUsd"] = max(raw["maxOrderNotionalUsd"], 5_000)
        raw["maxDailyNotionalUsd"] = max(raw["maxDailyNotionalUsd"], raw["maxOrderNotionalUsd"])
        m = signed(raw)
        order = good_order(raw)
        base = run_gate(m, market, order, STATE0)
        assert base["decision"] in ("allow", "hold"), base          # the untampered mandate works, so a refusal below is the tamper
        t = copy.deepcopy(m)
        kind = rng.choice(["field", "field", "field", "sig_flip", "sig_truncate", "sig_none", "other_key", "foreign_sig", "garbage_sig"])
        if kind == "field":
            f = rng.choice(fields)
            before = canonical_json({k: v for k, v in t.items() if k not in ("signature", "signerPublicKey")})
            if f in ("symbols", "sides"):
                t[f] = t[f] + [rng.choice(["TSLA", "NVDA", "sell", "buy"])]
            elif f in ("maxOrderNotionalUsd", "maxDailyNotionalUsd", "priceBandPct", "stepUpAboveUsd"):
                t[f] = rng.choice([t.get(f, 1) * rng.choice([2, 10, 100, 0.5]) + 1, 1e12, str(t.get(f, 1)), None, True])
                if t[f] is None and f == "stepUpAboveUsd":
                    t.pop(f)                                     # removing a required field would fail at construction; None is the tamper
            elif f == "expiresAt":
                t[f] = rng.choice(["2099-01-01T00:00:00Z", "2024-11-07T00:00:01Z", "2024-11-06"])
            else:
                t[f] = {**t.get("referencePrices", {}), "AAPL": rng.choice([1.0, 9999.0])}
            if canonical_json({k: v for k, v in t.items() if k not in ("signature", "signerPublicKey")}) == before:
                continue
        elif kind == "sig_flip":
            sig = bytearray(base64.b64decode(t["signature"]))
            sig[rng.randrange(len(sig))] ^= 1 << rng.randrange(8)
            t["signature"] = base64.b64encode(bytes(sig)).decode()
        elif kind == "sig_truncate":
            t["signature"] = t["signature"][: rng.randint(0, len(t["signature"]) - 1)]
        elif kind == "sig_none":
            t.pop("signature", None) if rng.random() < 0.5 else t.__setitem__("signature", None)
        elif kind == "other_key":
            t = sign_mandate({k: v for k, v in t.items() if k not in ("signature", "signerPublicKey")}, ATTACKER_PRIV)    # attacker re-signs, owner key pinned
        elif kind == "foreign_sig":
            other = signed(random_mandate(rng, live=True))
            t["signature"] = other["signature"]
        else:
            t["signature"] = rng.choice(["!!notbase64!!", "", "AAAA", base64.b64encode(b"x" * 64).decode()])
        res = run_gate(t, market, order, STATE0)
        assert res["decision"] == "refuse" and res["checks"]["mandate"] == "invalid", (kind, res["decision"], res["reasons"])


def test_unsigned_or_expired_or_revoked_mandates_never_trade():
    rng = random.Random(3)
    market = make_market()
    for _ in range(300):
        raw = random_mandate(rng, live=True)
        order = {"ticker": raw["symbols"][0], "side": raw["sides"][0], "quantity": 1, "limit_price": PRICES[raw["symbols"][0].upper()]}
        m = signed(raw)
        assert run_gate({k: v for k, v in m.items() if k != "signature"}, market, order, STATE0)["decision"] == "refuse"
        assert run_gate(m, market, order, {"as_of": "2024-11-07"})["decision"] == "refuse"            # at the expiry instant
        assert run_gate(m, market, order, {"as_of": "2030-01-01"})["decision"] == "refuse"
        assert run_gate(m, market, order, {**STATE0, "revoked": [Mandate.from_dict(m).id]})["decision"] == "refuse"
        assert run_gate(m, market, order, STATE0, revoked=True)["decision"] == "refuse"


def test_the_orders_own_limit_price_cannot_raise_allowed_notional():
    rng = random.Random(5)
    for _ in range(N):
        raw = random_mandate(rng, live=True)
        market = make_market(rng)
        m = signed(raw)
        order = random_order(rng, raw, {t: market.quote(t)["price"] for t in PRICES})
        notionals, decisions = set(), []
        for limit in (0.01, 1.0, order.get("limit_price"), 222.7, 1e9, None):
            res = run_gate(m, market, {**order, "limit_price": limit}, STATE0)
            if "notional_usd" in res["checks"]:
                notionals.add(res["checks"]["notional_usd"])
            decisions.append(res)
        assert len(notionals) <= 1, notionals                   # valued at the trusted price whatever limit is claimed
        for res in decisions:
            if res["decision"] == "allow":
                assert res["checks"]["notional_usd"] <= raw["maxOrderNotionalUsd"]
                assert abs(res["checks"]["limit_vs_trusted_pct"]) <= raw["priceBandPct"] + 1e-9


def test_extra_order_fields_cannot_change_the_decision():
    rng = random.Random(11)
    junk_keys = ["reference_price", "price", "trusted_price", "market_price", "notional", "notional_usd", "maxOrderNotionalUsd", "mandate", "override",
                 "approved", "step_up_approved", "l7_confirmed", "priceBandPct", "as_of", "daily_total_usd", "quote", "split_adjusted_price"]
    for _ in range(N):
        raw = random_mandate(rng, live=True)
        market = make_market(rng)
        m = signed(raw)
        order = random_order(rng, raw, {t: market.quote(t)["price"] for t in PRICES})
        base = run_gate(m, market, order, STATE0)
        fat = dict(order)
        for k in rng.sample(junk_keys, rng.randint(1, 6)):
            fat[k] = rng.choice([1.0, 0.0001, 1e12, True, "approved", {"x": 1}, -5])
        again = run_gate(m, market, fat, STATE0)
        assert (again["decision"], again["reasons"]) == (base["decision"], base["reasons"]), (order, fat)


def test_evaluate_is_pure_and_deterministic():
    rng = random.Random(13)
    for _ in range(400):
        raw = random_mandate(rng)
        market = make_market(rng)
        m = signed(raw)
        order = random_order(rng, raw, {t: market.quote(t)["price"] for t in PRICES})
        state = {"as_of": AS_OF, "daily_total_usd": 100.0}
        o0, s0, m0 = copy.deepcopy(order), copy.deepcopy(state), copy.deepcopy(m)
        g = OrderGate(m, market, None, public_key=OWNER_PUB)
        a, b = g.evaluate(order, state), g.evaluate(order, state)
        assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
        assert order == o0 or str(order) == str(o0)      # nan != nan, so compare text as well
        assert state == s0 and m == m0


def test_money_movement_is_never_an_order():
    rng = random.Random(17)
    market = make_market()
    for _ in range(300):
        raw = random_mandate(rng, live=True)
        base = {"ticker": raw["symbols"][0], "side": raw["sides"][0], "quantity": 1, "limit_price": PRICES[raw["symbols"][0].upper()]}
        for extra in ({"type": rng.choice(["transfer", "WITHDRAW", "wire", "Transfer_Funds"])}, {"action": "withdrawal"}, {"destination_account": "ATK-4401"}):
            res = run_gate(signed(raw), market, {**base, **extra}, STATE0)
            assert res["decision"] == "refuse" and res["checks"]["kind"] == "money_movement"


def test_cited_figures_fail_closed():
    """Contradicted, stale and not-yet-public figures refuse; a checker that raises refuses; required-but-missing figures refuse."""
    rng = random.Random(19)
    market = make_market()
    raw = {"symbols": ["AAPL"], "sides": ["buy"], "maxOrderNotionalUsd": 10_000, "maxDailyNotionalUsd": 20_000, "priceBandPct": 5, "expiresAt": "2024-11-07T00:00:00Z",
           "referencePrices": {}}
    m = signed(raw)
    order = {"ticker": "AAPL", "side": "buy", "quantity": 10, "limit_price": 222.7}
    true_fig = {"metric": "revenue", "fiscal_year": 2024, "value": 391035, "unit": "USD millions"}
    for _ in range(N):
        kind = rng.choice(["wrong", "stale", "npy", "ok", "unknown", "raise", "none"])
        checker = FakeFigureChecker(APPLE_FY2024_TRUTH, not_public_yet=[("revenue", 2024)] if kind == "npy" else (), stale=[("revenue", 2024)] if kind == "stale" else ())
        fig = dict(true_fig, value=true_fig["value"] * rng.choice([0.5, 0.8, 1.2, 10])) if kind == "wrong" else dict(true_fig)
        if kind == "unknown":
            fig["metric"] = "operating_cash_flow"
        figs = [fig] if kind != "none" else []

        def boom(*a):
            raise RuntimeError("checker down")
        res = run_gate(m, market, {**order, "key_figures": figs}, STATE0, checker=boom if kind == "raise" else checker, require_figures=True)
        expected = {"wrong": "refuse", "stale": "refuse", "npy": "refuse", "ok": "allow", "unknown": "hold", "raise": "refuse", "none": "refuse"}[kind]
        assert res["decision"] == expected, (kind, res)


def test_a_gate_without_a_pinned_key_still_checks_expiry_and_revocation():
    """Documented behaviour: without `public_key` the signature is not checked, but expiry and revocation still are."""
    rng = random.Random(23)
    market = make_market()
    for _ in range(200):
        raw = random_mandate(rng, live=False)
        order = {"ticker": raw["symbols"][0], "side": raw["sides"][0], "quantity": 1, "limit_price": PRICES[raw["symbols"][0].upper()]}
        assert OrderGate(raw, market).evaluate(order, STATE0)["decision"] == "refuse"


def test_a_signed_minimal_mandate_verifies():
    raw = {"symbols": ["AAPL"], "sides": ["buy"], "maxOrderNotionalUsd": 10_000, "maxDailyNotionalUsd": 20_000, "priceBandPct": 5, "expiresAt": "2024-11-07T00:00:00Z"}
    m = signed(raw)
    Mandate.from_dict(m).verify(OWNER_PUB, now=AS_OF)
    order = {"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": PRICES["AAPL"]}
    result = run_gate(m, make_market(), order, STATE0)
    assert result["decision"] == "allow"
    assert result["checks"]["price_source"] == "trusted market quote"


def test_a_mandate_missing_a_required_field_cannot_be_used():
    m = signed({"symbols": ["AAPL"], "sides": ["buy"], "maxOrderNotionalUsd": 1, "maxDailyNotionalUsd": 1, "priceBandPct": 5, "expiresAt": "2024-11-07T00:00:00Z", "referencePrices": {}})
    del m["priceBandPct"]
    with pytest.raises((TypeError, MandateInvalid)):
        OrderGate(m, make_market(), None, public_key=OWNER_PUB).evaluate({"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 222.7}, STATE0)
