"""Optional signed portfolio limits: per-symbol daily cap, net position cap, orders per day.

Gate boundaries (exact and one cent over), fail-closed state, old mandates unchanged, Envelope parity with OrderGate, concurrency in the arena,
sub-mandate containment (mandate_fit), cross-language signing with the TypeScript receiver, and the shipped policy packs.
"""
import base64
import datetime as dt
import hashlib
import json
import random
import shutil
import subprocess
import textwrap
import threading
from pathlib import Path

import pytest

from orderguard_arena.authority import Authority
from orderguard_arena.envelopes import EnvelopeBook, make_envelope, owner_key_from_seed
from orderguard_guard import policy_packs
from orderguard_guard.cli import main as cli_main
from orderguard_guard.gate import (Mandate, MandateInvalid, OrderGate, canonical_json, generate_keypair, private_key_to_b64, public_key_to_b64,
                                   sign_mandate)
from orderguard_guard.mandate_fit import check_mandate_fit
from orderguard_guard.market import SimMarket

ROOT = Path(__file__).resolve().parents[3]
LEGACY = {"symbols": ["AAPL", "MSFT"], "sides": ["buy", "sell"], "maxOrderNotionalUsd": 5000, "maxDailyNotionalUsd": 100000, "priceBandPct": 5,
          "expiresAt": "2099-01-01T00:00:00Z", "referencePrices": {"AAPL": 100, "MSFT": 200}}
BASE_STATE = {"as_of": "2026-03-02", "daily_total_usd": 0.0}


def gate(**limits):
    return OrderGate({**LEGACY, **limits}, SimMarket({"AAPL": 100.0, "MSFT": 200.0}))


def order(qty=1, side="buy", ticker="AAPL", px=100.0):
    return {"ticker": ticker, "side": side, "quantity": qty, "limit_price": px}


def ev(g, o, **state):
    return g.evaluate(o, {**BASE_STATE, **state})


# ---- each limit allows at the boundary and refuses one cent over ---------------------------------------------------------

def test_symbol_daily_cap_boundary_and_one_cent_over():
    g = gate(maxSymbolDailyNotionalUsd=1000)
    assert ev(g, order(5), symbol_daily_usd={"AAPL": 500.0})["decision"] == "allow"            # exactly $1,000
    assert ev(g, order(5), symbol_daily_usd={"AAPL": 500.01})["decision"] == "refuse"          # one cent over
    r = ev(g, order(1), symbol_daily_usd={"AAPL": 950.0, "MSFT": 0.0})
    assert r["decision"] == "refuse" and "per-symbol daily cap" in r["reasons"][0]
    assert ev(g, order(1, ticker="MSFT", px=200.0), symbol_daily_usd={"AAPL": 999.0})["decision"] == "allow"   # another symbol is unaffected
    assert ev(g, order(1), symbol_daily_usd={})["decision"] == "allow"                          # a symbol not listed has placed nothing


def test_position_cap_boundary_and_one_cent_over():
    g = gate(maxPositionUsd=1000)
    assert ev(g, order(4), positions={"AAPL": 6})["decision"] == "allow"                        # 10 shares = $1,000.00
    assert ev(g, order(5), positions={"AAPL": 5, "MSFT": 0})["decision"] == "allow"
    assert ev(g, order(1), positions={"AAPL": 10})["decision"] == "refuse"
    r = OrderGate({**LEGACY, "maxPositionUsd": 1000, "referencePrices": {"AAPL": 100.001}}, SimMarket({"AAPL": 100.001})) \
        .evaluate(order(10, px=100.001), {**BASE_STATE, "positions": {}})                       # $1,000.01
    assert r["decision"] == "refuse" and "position cap" in r["reasons"][0]
    assert ev(g, order(4, side="sell"), positions={"AAPL": -6})["decision"] == "allow"          # short side is symmetric
    assert ev(g, order(5, side="sell"), positions={"AAPL": -6})["decision"] == "refuse"
    assert ev(g, order(20, side="sell"), positions={"AAPL": 10})["decision"] == "allow"         # sells that reduce exposure and land inside the cap
    assert ev(g, order(11, side="sell"), positions={"AAPL": 0})["decision"] == "refuse"


def test_held_orders_count_in_the_direction_that_grows_exposure():
    g = gate(maxPositionUsd=1000)
    held = {"AAPL": {"buy": 6, "sell": 0}}
    assert ev(g, order(5), positions={"AAPL": 0}, held_qty=held)["decision"] == "refuse"       # 6 held + 5 = 11 shares
    assert ev(g, order(4), positions={"AAPL": 0}, held_qty=held)["decision"] == "allow"        # 10 shares
    assert ev(g, order(5, side="sell"), positions={"AAPL": 0}, held_qty=held)["decision"] == "allow"
    assert ev(g, order(1), positions={"AAPL": 0}, held_qty={"AAPL": {"buy": "x"}})["decision"] == "refuse"   # unreadable held tally fails closed


def test_orders_per_day_boundary():
    g = gate(maxOrdersPerDay=3)
    assert ev(g, order(), orders_today=2)["decision"] == "allow"                                # the third order of the day
    r = ev(g, order(), orders_today=3)
    assert r["decision"] == "refuse" and "3 orders per day" in r["reasons"][0]


# ---- missing or invalid state fails closed -------------------------------------------------------------------------------

@pytest.mark.parametrize(("limit", "good", "bad"), [
    ({"maxSymbolDailyNotionalUsd": 1000}, {"symbol_daily_usd": {}}, [{}, {"symbol_daily_usd": None}, {"symbol_daily_usd": [1]},
                                                                      {"symbol_daily_usd": {"AAPL": "x"}}, {"symbol_daily_usd": {"AAPL": -1}},
                                                                      {"symbol_daily_usd": {"AAPL": float("nan")}}, {"symbol_daily_usd": {"AAPL": True}}]),
    ({"maxPositionUsd": 1000}, {"positions": {}}, [{}, {"positions": "none"}, {"positions": {"AAPL": None}}, {"positions": {"AAPL": float("inf")}},
                                                    {"positions": {"AAPL": 0}, "held_qty": "x"}]),
    ({"maxOrdersPerDay": 5}, {"orders_today": 0}, [{}, {"orders_today": None}, {"orders_today": -1}, {"orders_today": 1.5}, {"orders_today": "2"},
                                                    {"orders_today": True}]),
])
def test_missing_or_invalid_state_fails_closed(limit, good, bad):
    g = gate(**limit)
    assert ev(g, order(), **good)["decision"] == "allow"
    for state in bad:
        r = ev(g, order(), **state)
        assert r["decision"] == "refuse" and "cannot be enforced" in " ".join(r["reasons"]), state


def test_mandate_validation_rejects_bad_limits():
    for bad in ({"maxOrdersPerDay": 0}, {"maxOrdersPerDay": 2.5}, {"maxOrdersPerDay": True}, {"maxPositionUsd": 0}, {"maxPositionUsd": float("nan")},
                {"maxSymbolDailyNotionalUsd": -1}, {"maxSymbolDailyNotionalUsd": "5"}):
        r = OrderGate({**LEGACY, **bad}, SimMarket({"AAPL": 100.0})).evaluate(order(), {**BASE_STATE, "orders_today": 0})
        assert r["decision"] == "refuse", bad


# ---- an old mandate behaves exactly as before ----------------------------------------------------------------------------

def test_old_mandate_is_byte_identical_and_ignores_portfolio_state():
    m = Mandate.from_dict(LEGACY)
    assert set(m.to_dict()) == set(LEGACY) | set()                                              # no new key, never a None
    assert m.id == hashlib.sha256(canonical_json(LEGACY)).hexdigest()[:16]
    key, pub = generate_keypair()
    signed = sign_mandate(LEGACY, key)
    assert not ({"maxSymbolDailyNotionalUsd", "maxPositionUsd", "maxOrdersPerDay"} & set(signed))
    Mandate.from_dict(signed).verify(pub, now="2026-03-02T00:00:00Z")
    assert Mandate.from_dict(signed).id == m.id
    g = gate()
    huge = {"symbol_daily_usd": {"AAPL": 1e9}, "positions": {"AAPL": 1e9}, "orders_today": 10**9}
    assert ev(g, order(), **huge) == ev(g, order())                                             # same answer, with and without portfolio state
    assert ev(g, order())["decision"] == "allow"


def test_new_fields_are_signed_and_tampering_is_caught():
    key, pub = generate_keypair()
    signed = sign_mandate({**LEGACY, "maxOrdersPerDay": 5, "maxPositionUsd": 1000, "maxSymbolDailyNotionalUsd": 2000}, key)
    Mandate.from_dict(signed).verify(pub, now="2026-03-02T00:00:00Z")
    for k, v in (("maxOrdersPerDay", 500), ("maxPositionUsd", 10**6)):
        with pytest.raises(MandateInvalid):
            Mandate.from_dict({**signed, k: v}).verify(pub, now="2026-03-02T00:00:00Z")
    with pytest.raises(MandateInvalid):                                                         # dropping a limit after signing is a changed body too
        Mandate.from_dict({k: v for k, v in signed.items() if k != "maxOrdersPerDay"}).verify(pub, now="2026-03-02T00:00:00Z")


# ---- Envelope parity with OrderGate ----------------------------------------------------------------------------------------

def test_envelope_check_agrees_with_order_gate_on_random_states():
    rng = random.Random(11)
    key = owner_key_from_seed("pl")
    prices = {"AAPL": 100.0, "MSFT": 200.0}
    for limits in ({"max_symbol_daily": 3000}, {"max_position": 2500}, {"max_orders_per_day": 4},
                   {"max_symbol_daily": 3000, "max_position": 2500, "max_orders_per_day": 4}):
        env = make_envelope(key, name="p", symbols=("AAPL", "MSFT"), per_order=2000, daily=1e6, band_pct=2, **limits)
        g = OrderGate(env.m, SimMarket(prices))
        refused = 0
        for _ in range(1500):
            t = rng.choice(["AAPL", "MSFT"])
            q = rng.choice([1, 2, 5, 9, 10, 15, 20])
            side = rng.choice(["buy", "sell"])
            state = {"symbol_daily_usd": {s: rng.choice([0, 500, 1000, 2400, 2999.99, 3000]) for s in prices},
                     "positions": {s: rng.choice([-30, -12, -5, 0, 5, 12, 30]) for s in prices},
                     "held_qty": {s: {"buy": rng.choice([0, 0, 3, 8]), "sell": rng.choice([0, 0, 2, 9])} for s in prices},
                     "orders_today": rng.randrange(0, 7)}
            if rng.random() < 0.1:
                state.pop(rng.choice(list(state)))                                              # missing state must agree too (both fail closed)
            o = order(q, side, t, prices[t])
            r_gate = g.evaluate(o, {**BASE_STATE, **state})
            r, h, _ = env.check(t, None, side, q, prices[t], prices[t], 0.0, state)
            assert (r_gate["decision"] == "refuse") == bool(r), (limits, o, state, r_gate, r)
            refused += bool(r)
        assert 100 < refused < 1400                                                             # the sample exercises both outcomes


def _book(**limits):
    key = owner_key_from_seed("pl2")
    book = EnvelopeBook(key.public_key())
    book.add(make_envelope(key, name="one", symbols=("AAPL", "MSFT"), per_order=5000, daily=1e6, band_pct=5, step_up=limits.pop("step_up", None), **limits))
    a = Authority(book, steps_per_day=100)
    a.set_prices({"AAPL": 100.0, "MSFT": 200.0})
    return a, book


def test_fast_path_and_strict_gate_agree_through_the_authority_with_state_accumulating():
    rng = random.Random(3)
    lim = dict(max_symbol_daily=2500, max_position=1500, max_orders_per_day=25, step_up=1200)
    fast, _ = _book(**lim)
    _, strict_book = _book(**lim)
    strict = Authority(strict_book, steps_per_day=100, strict=True)
    strict.set_prices({"AAPL": 100.0, "MSFT": 200.0})
    kinds = set()
    for i in range(600):
        t = rng.choice(["AAPL", "MSFT"])
        o = order(rng.choice([1, 3, 5, 8, 12, 14]), rng.choice(["buy", "buy", "sell"]), t, {"AAPL": 100.0, "MSFT": 200.0}[t])
        step = (i // 40) * 100                                                                  # a new day every 40 orders
        a = fast.authorize(o, key=f"k{i}", step=step)
        b = strict.authorize(o, key=f"k{i}", step=step)
        assert a.decision == b.decision, (i, o, a, b)
        kinds.add(a.decision)
    assert {"allow", "refuse", "hold"} <= kinds


def test_approving_a_hold_moves_its_shares_into_the_position():
    a, book = _book(max_position=1000, step_up=500)
    env = book.envelopes()[0]
    assert a.authorize(order(6), key="h", step=0).decision == "hold"
    assert a.authorize(order(5), key="x", step=0).decision == "refuse"                          # 6 held + 5 > 10
    assert a.approve("h", step=0).decision == "allow"
    assert env.portfolio_state(0)["positions"] == {"AAPL": 6} and env.portfolio_state(0)["held_qty"]["AAPL"]["buy"] == 0
    assert a.authorize(order(4), key="y", step=0).decision == "allow"
    assert a.authorize(order(1), key="z", step=0).decision == "refuse"


# ---- concurrency: N parallel orders can never together pass a cap -----------------------------------------------------------

@pytest.mark.parametrize(("limits", "expect"), [({"max_symbol_daily": 1000}, 10), ({"max_position": 700}, 7), ({"max_orders_per_day": 9}, 9)])
def test_parallel_orders_never_pass_the_portfolio_caps(limits, expect):
    a, book = _book(**limits)
    out = []

    def agent(i):
        for j in range(60):
            out.append(a.authorize(order(1), key=f"{i}-{j}", step=0, agent=i).decision)

    ts = [threading.Thread(target=agent, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out.count("allow") == expect and len(out) == 720


# ---- sub-mandate containment (mandate_fit) -----------------------------------------------------------------------------------

NOW = dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)
PARENT = {**LEGACY, "expiresAt": "2026-04-01T00:00:00Z", "maxSymbolDailyNotionalUsd": 20000, "maxPositionUsd": 30000, "maxOrdersPerDay": 50}


def fit(parent, draft):
    key, pub = generate_keypair()
    return check_mandate_fit(sign_mandate(parent, key), draft, pub, now=NOW)


def test_draft_may_be_equal_or_tighter_and_may_add_limits_to_a_parent_without_them():
    assert fit(PARENT, PARENT)["fits"]
    tight = {**PARENT, "maxSymbolDailyNotionalUsd": 19999.99, "maxPositionUsd": 1, "maxOrdersPerDay": 1}
    assert fit(PARENT, tight)["fits"]
    plain = {**LEGACY, "expiresAt": "2026-04-01T00:00:00Z"}
    assert fit(plain, plain | {"maxPositionUsd": 500, "maxOrdersPerDay": 2, "maxSymbolDailyNotionalUsd": 900})["fits"]


@pytest.mark.parametrize(("edit", "code"), [
    ({"maxSymbolDailyNotionalUsd": 20000.01}, "symbol_daily_cap"), ({"maxPositionUsd": 30000.01}, "position_cap"),
    ({"maxOrdersPerDay": 51}, "order_count_cap"), ({"maxSymbolDailyNotionalUsd": None}, "symbol_daily_cap"),
    ({"maxPositionUsd": None}, "position_cap"), ({"maxOrdersPerDay": None}, "order_count_cap"),
])
def test_draft_cannot_loosen_or_drop_a_parent_limit(edit, code):
    r = fit(PARENT, PARENT | edit)
    assert not r["fits"] and code in [v["code"] for v in r["violations"]]
    dropped = {k: v for k, v in PARENT.items() if k not in edit}                                 # absent, not just null
    assert not fit(PARENT, dropped)["fits"]


@pytest.mark.parametrize("bad", [{"maxOrdersPerDay": 0}, {"maxOrdersPerDay": 1.5}, {"maxOrdersPerDay": True}, {"maxPositionUsd": 0},
                                 {"maxSymbolDailyNotionalUsd": 10.001}, {"maxPositionUsd": "9"}])
def test_malformed_limits_in_a_draft_fail_closed(bad):
    r = fit(PARENT, PARENT | bad)
    assert not r["fits"] and r["violations"][0]["code"] == "invalid_draft"


# ---- cross-language: Python signs, TypeScript verifies, and the reverse -----------------------------------------------------

NODE = shutil.which("node")
TSX = ROOT / "node_modules" / ".bin" / "tsx"
needs_node = pytest.mark.skipif(not (NODE and TSX.exists()), reason="node and tsx are needed for the cross-language check")


def _run_ts(script: str, tmp_path: Path, *args: str) -> str:
    f = tmp_path / "x.mts"
    f.write_text(script)
    r = subprocess.run([NODE, "--no-warnings", "--import", "tsx", str(f), *args], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


@needs_node
def test_python_signed_mandate_with_the_new_fields_verifies_in_typescript(tmp_path):
    key, pub = generate_keypair()
    signed = sign_mandate({**LEGACY, "expiresAt": "2099-01-01T00:00:00Z", "stepUpAboveUsd": 4000, "maxSymbolDailyNotionalUsd": 20000.5,
                           "maxPositionUsd": 30000, "maxOrdersPerDay": 50}, key)
    mid = Mandate.from_dict(signed).id
    proof = {"payload": base64.b64encode(canonical_json(Mandate.from_dict(signed).to_dict(with_signature=False))).decode(), "signature": signed["signature"]}
    script = textwrap.dedent(f"""
        import {{ SignedPaperPolicy }} from '{ROOT}/receiver/core/paper-policy.ts';
        const p = new SignedPaperPolicy({json.dumps(proof)}, {json.dumps(public_key_to_b64(pub))});
        console.log(JSON.stringify({{ id: p.parentId, scope: p.parent }}));
    """)
    out = json.loads(_run_ts(script, tmp_path))
    assert out["id"] == mid
    assert (out["scope"]["maxSymbolDailyNotionalUsd"], out["scope"]["maxPositionUsd"], out["scope"]["maxOrdersPerDay"]) == (20000.5, 30000, 50)
    tampered = {**proof, "payload": base64.b64encode(canonical_json({**Mandate.from_dict(signed).to_dict(with_signature=False), "maxOrdersPerDay": 5000})).decode()}
    bad = script.replace(json.dumps(proof), json.dumps(tampered))
    with pytest.raises(AssertionError, match="signature did not verify"):
        _run_ts(bad, tmp_path)


@needs_node
def test_typescript_signed_mandate_with_the_new_fields_verifies_in_python(tmp_path):
    script = textwrap.dedent("""
        import { generateKeyPairSync, sign } from 'node:crypto';
        const keys = generateKeyPairSync('ed25519');
        const sorted = (o: Record<string, unknown>) => Object.fromEntries(Object.entries(o).sort(([a], [b]) => (a < b ? -1 : 1)));
        const body = sorted({ symbols: ['AAPL', 'MSFT'], sides: ['buy', 'sell'], maxOrderNotionalUsd: 5000, maxDailyNotionalUsd: 100000, priceBandPct: 5,
          expiresAt: '2099-01-01T00:00:00Z', referencePrices: { AAPL: 100, MSFT: 200 }, maxSymbolDailyNotionalUsd: 20000.5, maxPositionUsd: 30000,
          maxOrdersPerDay: 50 });
        const bytes = Buffer.from(JSON.stringify(body));
        console.log(JSON.stringify({ body, signature: sign(null, bytes, keys.privateKey).toString('base64'),
          pub: Buffer.from(keys.publicKey.export({ format: 'jwk' }).x!, 'base64url').toString('base64') }));
    """)
    out = json.loads(_run_ts(script, tmp_path))
    m = Mandate.from_dict({**out["body"], "signature": out["signature"]})
    from orderguard_guard.gate import public_key_from_b64
    m.verify(public_key_from_b64(out["pub"]), now="2026-03-02T00:00:00Z")
    assert (m.maxSymbolDailyNotionalUsd, m.maxPositionUsd, m.maxOrdersPerDay) == (20000.5, 30000, 50)


# ---- policy packs ------------------------------------------------------------------------------------------------------------

NEW = ("maxSymbolDailyNotionalUsd", "maxPositionUsd", "maxOrdersPerDay")


def test_all_shipped_templates_build_are_coherent_and_use_the_portfolio_limits():
    assert policy_packs.names() == ["active-equities", "balanced-equities", "conservative-equities", "crypto-sleeve"]
    for n in policy_packs.names():
        raw = policy_packs.load(n)
        assert raw["_about"] and raw["ttlHours"] > 0 and "expiresAt" not in raw and "signature" not in raw
        m = policy_packs.build_mandate(n, now=NOW)
        assert all(getattr(m, f) is not None for f in NEW) and m.expiresAt.endswith("Z")
        assert dt.datetime.fromisoformat(m.expiresAt.replace("Z", "+00:00")) - NOW == dt.timedelta(hours=raw["ttlHours"])
    tiers = [policy_packs.build_mandate(n, now=NOW) for n in ("conservative-equities", "balanced-equities", "active-equities")]
    assert [t.maxOrderNotionalUsd for t in tiers] == sorted(t.maxOrderNotionalUsd for t in tiers)       # the three tiers are ordered by risk


def test_cli_list_show_and_sign_produce_a_mandate_the_gate_accepts(tmp_path, capsys):
    key, pub = generate_keypair()
    keyfile, out = tmp_path / "k", tmp_path / "m.json"
    keyfile.write_text(private_key_to_b64(key) + "\n")
    assert cli_main(["policy", "list"]) == 0 and "crypto-sleeve" in capsys.readouterr().out
    assert cli_main(["policy", "show", "balanced-equities"]) == 0 and json.loads(capsys.readouterr().out)["maxOrdersPerDay"] == 30
    assert cli_main(["policy", "sign", "balanced-equities", "--key", str(keyfile), "--out", str(out), "--symbols", "aapl", "msft"]) == 0
    signed = json.loads(out.read_text())
    assert signed["symbols"] == ["AAPL", "MSFT"] and "ttlHours" not in signed and "_about" not in signed
    m = Mandate.from_dict(signed)
    m.verify(pub)
    g = OrderGate(m, SimMarket({"AAPL": 100.0}), public_key=pub)
    assert g.evaluate(order(10), {"as_of": dt.date.today().isoformat(), "daily_total_usd": 0.0, "symbol_daily_usd": {}, "positions": {}, "orders_today": 0})["decision"] == "allow"


def test_cli_refuses_incoherent_templates_missing_keys_and_unknown_names(tmp_path, monkeypatch, capsys):
    key, _ = generate_keypair()
    keyfile = tmp_path / "k"
    keyfile.write_text(private_key_to_b64(key))
    packs = tmp_path / "packs"
    packs.mkdir()
    good = policy_packs.load("conservative-equities")
    for name, edit in (("per-order-over-daily", {"maxOrderNotionalUsd": 20000}), ("symbol-over-daily", {"maxSymbolDailyNotionalUsd": 20000}),
                       ("symbol-below-order", {"maxSymbolDailyNotionalUsd": 100}), ("position-below-order", {"maxPositionUsd": 100}),
                       ("stepup-over-order", {"stepUpAboveUsd": 99999}), ("bad-orders", {"maxOrdersPerDay": 0}), ("no-ttl", {"ttlHours": None}),
                       ("has-expiry", {"expiresAt": "2099-01-01T00:00:00Z"}), ("stray", {"mystery": 1})):
        (packs / f"{name}.json").write_text(json.dumps({**good, **edit}))
        monkeypatch.setattr(policy_packs, "packs_dir", lambda: packs)
        out = tmp_path / f"{name}.out"
        assert cli_main(["policy", "sign", name, "--key", str(keyfile), "--out", str(out)]) == 2, name
        assert not out.exists(), name
    monkeypatch.undo()
    assert cli_main(["policy", "sign", "nope", "--key", str(keyfile)]) == 2
    assert cli_main(["policy", "sign", "crypto-sleeve", "--key", str(tmp_path / "missing")]) == 2
    assert cli_main(["policy", "sign", "crypto-sleeve", "--key", str(keyfile), "--symbols", "АAPL"]) == 2      # a look-alike symbol is refused
    assert cli_main(["policy", "show", "../x"]) == 2
    capsys.readouterr()


def test_templates_are_packaged_into_the_wheel():
    toml = (ROOT / "pyproject.toml").read_text()
    assert '"policies" = "orderguard_guard/policies"' in toml and "force-include" in toml
    assert len(list((ROOT / "policies").glob("*.json"))) == 4 and (ROOT / "policies" / "README.md").is_file()
