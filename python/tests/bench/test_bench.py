"""OrderGuard Bench: the auditor has teeth, a small sharded run is clean and deterministic, and the receiver ledger audit is independent.

Offline and quick (a few seconds). Tests that need Node skip when it is not installed.
"""
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from orderguard_arena.authority import Authority
from orderguard_arena.envelopes import Envelope, EnvelopeBook, make_envelope, owner_key_from_seed
from orderguard_bench import auditor as A
from orderguard_bench import engine as E
from orderguard_bench import profiles
from orderguard_bench import workload as W
from orderguard_bench.market import BenchMarket, pingpong
from orderguard_guard.gate import public_key_to_b64

HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    p = profiles.get("tiny")
    d = tmp_path_factory.mktemp("bench")
    W.write_partitions(p, d / "gen", workers=1)
    m = BenchMarket(p.seed, p.steps, p.steps_per_day)
    return p, d, m, W.registry(p, m)


# ---- a hand-made log with one envelope: every kind of breach the auditor must find ------------------------------------------------------
def _one_envelope(market):
    key = owner_key_from_seed("bench-test")
    env = make_envelope(key, name="t", symbols=["BTCUSDT"], per_order=1000.0, daily=2000.0, band_pct=1.0, max_orders_per_day=5)
    reg = {"t": {"owner": 0, "id": env.id, "public_key": public_key_to_b64(key.public_key()), "mandate": env.mandate}}
    return env, reg


def _rec(i, k, q, g, n, p, step=0, x="orig", r=False, y="L5"):
    return {"i": i, "t": step, "k": k, "e": "t", "o": 0, "a": 1, "l": "legit", "x": x, "q": q, "g": g, "d": g, "r": r, "n": n, "p": p, "c": "",
            "y": y, "tr": None, "nid": None, "rk": None}


def _write(path, recs, tamper_line=None):
    log = E.DecisionLog(path)
    for r in recs:
        log.append(r)
    log.close()
    if tamper_line is not None:
        lines = path.read_text().splitlines()
        h, body = lines[tamper_line].split(" ", 1)
        lines[tamper_line] = h + " " + body.replace('"quantity":1', '"quantity":2')
        path.write_text("\n".join(lines) + "\n")


def test_auditor_passes_a_clean_log_and_catches_each_seeded_breach(tmp_path):
    m = BenchMarket(11, 50, 25)
    env, reg = _one_envelope(m)
    px = m.trusted[0]["BTCUSDT"]
    q = lambda n: {"ticker": "BTCUSDT", "side": "buy", "quantity": n, "limit_price": round(px, 2)}
    cents = lambda n: round(n * px * 100) / 100
    clean = [_rec(0, "a", q(1), "allow", cents(1), px), _rec(1, "a", q(1), "allow", cents(1), px, r=True), _rec(2, "b", q(2), "refuse", None, None)]
    _write(tmp_path / "clean.log", clean)
    a = A.audit_logs([str(tmp_path / "clean.log")], reg, m, procs=1)
    assert a["breach_total"] == 0 and a["checked"]["reproduced_by_order_gate"] == 1 and a["checked"]["replays_identical"] == 1

    big = int(990 // px)                             # just under the per-order cap; three of them pass the $2,000 daily cap
    seeded = {
        "daily_cap": [_rec(i, f"k{i}", q(big), "allow", cents(big), px) for i in range(3)],
        "double_execution": [_rec(0, "a", q(1), "allow", cents(1), px), _rec(1, "a", q(1), "allow", cents(1), px, x="retry")],
        "key_conflict_not_refused": [_rec(0, "a", q(1), "allow", cents(1), px), _rec(1, "a", q(3), "allow", cents(3), px, x="conflict")],
        "effect_after_revoke": [{"x": "ctl", "t": 0, "e": "t", "o": 0, "ctl": "revoke", "res": "revoked", "k": "c"}, _rec(0, "a", q(1), "allow", cents(1), px)],
        "price_band": [_rec(0, "a", {**q(1), "limit_price": round(px * 1.2, 2)}, "allow", cents(1), px)],
        "trusted_price": [_rec(0, "a", q(1), "allow", cents(1), px * 0.5)],
        "orders_per_day": [_rec(i, f"k{i}", q(1), "allow", cents(1), px) for i in range(6)],
        "forged_mandate_accepted": [{"x": "ctl", "t": 0, "e": "t", "o": 0, "ctl": "tampered_mandate", "res": "accepted", "k": "c"}],
    }
    for breach, recs in seeded.items():
        path = tmp_path / f"{breach}.log"
        _write(path, recs)
        a = A.audit_logs([str(path)], reg, m, procs=1)
        assert a["breaches"].get(breach), (breach, a["breaches"])
    _write(tmp_path / "chain.log", clean, tamper_line=0)
    assert A.audit_logs([str(tmp_path / "chain.log")], reg, m, procs=1)["breaches"].get("chain")


def test_a_tampered_mandate_fails_the_signature_check():
    m = BenchMarket(11, 10, 5)
    env, reg = _one_envelope(m)
    assert A.verify_signature(reg["t"]["mandate"], reg["t"]["public_key"])
    assert not A.verify_signature(W.tampered_copy(reg["t"]["mandate"]), reg["t"]["public_key"])
    assert not A.verify_signature(W.foreign_copy(reg["t"]["mandate"], 11), reg["t"]["public_key"])


def test_a_replayed_signed_mandate_keeps_its_budget_and_its_revocation():
    key = owner_key_from_seed("bench-test")
    book = EnvelopeBook(key.public_key())
    e = book.add(make_envelope(key, name="x", symbols=["AAPL"], per_order=1000, daily=3000, band_pct=1))
    a = Authority(book, steps_per_day=100)
    a.set_prices({"AAPL": 100.0})
    o = {"ticker": "AAPL", "side": "buy", "quantity": 5, "limit_price": 100}
    assert a.authorize(o, key="1", envelope="x").decision == "allow"
    a.revoke("x")
    again = book.add(Envelope(dict(e.mandate), name="x"))
    assert again is e and again.revoked and again.budget.used(0) == 500.0
    assert a.authorize(o, key="2", envelope="x").decision == "refuse"


def test_pingpong_never_jumps():
    idx = [pingpong(t, 5) for t in range(20)]
    assert idx[:10] == [0, 1, 2, 3, 4, 3, 2, 1, 0, 1]
    assert all(abs(a - b) == 1 for a, b in zip(idx, idx[1:]))


# ---- a small sharded run -------------------------------------------------------------------------------------------------------------------
def test_tiny_run_is_clean_and_sharding_does_not_change_a_decision(tiny):
    p, d, m, reg = tiny
    digests = set()
    for n in (1, 2):
        out = d / f"n{n}"
        out.mkdir()
        r = E.run_config(p, d / "gen", out, n)
        a = A.audit_logs(r["logs"], reg, m, procs=2)
        assert a["breach_total"] == 0, a["examples"]
        assert a["checked"]["reproduced_by_order_gate"] > 1000 and a["checked"]["key_conflicts_refused"] > 0 and a["checked"]["forged_mandates_rejected"] == 2
        digests.add(a["gate_digest"])
    assert len(digests) == 1


@pytest.mark.parametrize("mutation", E.MUTATIONS)
def test_every_python_mutation_is_caught(tiny, mutation):
    p, d, m, reg = tiny
    out = d / f"mut-{mutation}"
    out.mkdir()
    r = E.run_config(p, d / "gen", out, 1, mutation=mutation)
    assert A.audit_logs(r["logs"], reg, m, procs=1)["breach_total"] > 0


def test_thread_race_is_exact_and_the_lock_off_mutation_is_caught():
    from orderguard_bench import pyrace
    m = BenchMarket(11, 10, 5)
    ok = pyrace.thread_race(m, 8, 20)
    assert ok["allowed_fresh"] == ok["entitled_fills"] and ok["audit"]["breach_total"] == 0
    assert pyrace.thread_race(m, 8, 20, lock_off=True)["audit"]["breaches"].get("daily_cap")


# ---- the receiver ledger audit, on ledgers written here without Node ----------------------------------------------------------------------
def _ledger(path, rows, *, tamper=False):
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
      CREATE TABLE orders (seq INTEGER PRIMARY KEY, order_id TEXT NOT NULL, client_order_id TEXT NOT NULL, action_hash TEXT NOT NULL, symbol TEXT NOT NULL,
        side TEXT NOT NULL, quantity INTEGER NOT NULL, limit_price REAL NOT NULL, trusted_price REAL NOT NULL, notional_cents INTEGER NOT NULL,
        status TEXT NOT NULL, fill_price REAL, day TEXT NOT NULL);
      CREATE TABLE events (seq INTEGER PRIMARY KEY, type TEXT NOT NULL, order_id TEXT, payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);""")
    prev = "0" * 64
    for i, (coid, qty, px) in enumerate(rows, 1):
        payload = json.dumps({"clientOrderId": coid})
        h = hashlib.sha256("|".join([prev, str(i), "filled", f"og_{i}", payload]).encode()).hexdigest()
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (i, "filled", f"og_{i}", payload, prev, h))
        db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (i, f"og_{i}", coid, "x", "BTCUSDT", "buy", qty, px, px, round(qty * px * 100), "filled", px, "2026-01-05"))
        prev = h
    if tamper:
        db.execute("UPDATE events SET payload = '{}' WHERE seq = 1")
    db.commit()
    db.close()


def test_ledger_audit_recomputes_the_chain_and_the_caps(tmp_path):
    mandate = {"symbols": ["BTCUSDT"], "sides": ["buy"], "maxOrderNotionalUsd": 10_000.0, "maxDailyNotionalUsd": 20_000.0, "priceBandPct": 1.0,
               "expiresAt": "2099-01-01T00:00:00Z", "referencePrices": {}}
    _ledger(tmp_path / "ok.sqlite", [("a", 100, 73.77), ("b", 100, 73.77)])
    ok = A.audit_ledger(tmp_path / "ok.sqlite", mandate, acked={"a": "filled", "b": "filled"})
    assert ok["breach_total"] == 0 and ok["checked"]["reproduced_by_order_gate"] == 2
    _ledger(tmp_path / "over.sqlite", [(f"k{i}", 100, 73.77) for i in range(3)])
    assert A.audit_ledger(tmp_path / "over.sqlite", mandate)["breaches"].get("daily_cap")
    _ledger(tmp_path / "dup.sqlite", [("a", 10, 73.77), ("a", 10, 73.77)])
    assert A.audit_ledger(tmp_path / "dup.sqlite", mandate)["breaches"].get("double_execution")
    _ledger(tmp_path / "tamper.sqlite", [("a", 10, 73.77)], tamper=True)
    assert A.audit_ledger(tmp_path / "tamper.sqlite", mandate)["breaches"].get("ledger_chain")
    _ledger(tmp_path / "lost.sqlite", [("a", 10, 73.77)])
    assert A.audit_ledger(tmp_path / "lost.sqlite", mandate, acked={"a": "filled", "b": "filled"})["breaches"].get("acked_effect_lost")


@pytest.mark.skipif(not HAS_NODE, reason="node is not installed")
def test_exact_limit_probes_agree_across_python_order_gate_and_receiver(tmp_path):
    from orderguard_bench import edges
    r = edges.run(BenchMarket(11, 50, 25), tmp_path)
    assert r["all_ok"], [x for x in r["rows"] if not x["ok"]]


def test_report_is_self_contained(tmp_path):
    from orderguard_bench import report
    src = Path(__file__).resolve().parents[3] / "results" / "bench"
    for name in ("quick.json", "full.json"):
        if (src / name).exists():
            (tmp_path / name).write_text((src / name).read_text())
    page = report.write(tmp_path).read_text()
    assert "<script src" not in page and "<link" not in page and "http://" not in page.replace("http://www.w3.org", "")
    assert "prefers-color-scheme:dark" in page
