"""Envelopes (tightest fit), the frontier (monotonicity, Pareto, recommendation) and the bench smoke test."""
import pytest

from orderguard_arena.api import router
from orderguard_arena.cli import bench_one
from orderguard_arena.envelopes import EnvelopeBook, make_envelope, owner_key_from_seed
from orderguard_arena.frontier import Candidate, evaluate, pareto, run_frontier, stream_profile, proposed_mandate


def _book3():
    key = owner_key_from_seed("fit")
    b = EnvelopeBook(key.public_key())
    b.add(make_envelope(key, name="small", symbols=["AAPL"], per_order=2000, daily=10000, band_pct=1))
    b.add(make_envelope(key, name="mid", symbols=["AAPL", "MSFT"], per_order=5000, daily=10000, band_pct=1))
    b.add(make_envelope(key, name="wide", symbols=["AAPL", "MSFT", "NVDA"], per_order=20000, daily=100000, band_pct=3, step_up=10000))
    return b


def test_fit_and_tightest_fit():
    b = _book3()
    o = {"ticker": "AAPL", "side": "buy", "quantity": 5, "limit_price": 200.0}               # $1,000
    assert {e.name for e in b.fit(o, 200.0)} == {"small", "mid", "wide"}
    assert b.tightest_fit(o, 200.0).name == "small"                                           # smallest headroom: 2000-1000
    o2 = {**o, "quantity": 15}                                                                 # $3,000: over small's per-order cap
    assert {e.name for e in b.fit(o2, 200.0)} == {"mid", "wide"} and b.tightest_fit(o2, 200.0).name == "mid"
    o3 = {"ticker": "NVDA", "side": "buy", "quantity": 10, "limit_price": 200.0}
    assert [e.name for e in b.fit(o3, 200.0)] == ["wide"]
    assert b.tightest_fit({"ticker": "TSLA", "side": "buy", "quantity": 1, "limit_price": 200.0}, 200.0) is None
    assert b.tightest_fit({**o, "limit_price": 230.0}, 200.0) is None                         # 15% off the trusted price: outside every band
    big = {**o, "quantity": 70}                                                                # $14,000 -> wide, but over its $10,000 step-up: held, not allowed
    assert b.fit(big, 200.0) == [] and [e.name for e in b.fit(big, 200.0, include_holds=True)] == ["wide"]


def test_tightest_fit_accounts_for_the_remaining_daily_budget():
    b = _book3()
    o = {"ticker": "AAPL", "side": "buy", "quantity": 5, "limit_price": 200.0}
    b.get("small").budget.reserve(0, 9500.0)                       # small has only $500 left today: it no longer authorizes this order
    b.get("mid").budget.reserve(0, 9500.0)
    assert [e.name for e in b.fit(o, 200.0)] == ["wide"] and b.tightest_fit(o, 200.0).name == "wide"


def test_unsigned_or_tampered_envelope_is_refused():
    key = owner_key_from_seed("fit")
    b = EnvelopeBook(key.public_key())
    env = make_envelope(key, name="x", symbols=["AAPL"], per_order=1000, daily=1000, band_pct=1)
    env.mandate["maxOrderNotionalUsd"] = 10_000_000.0            # someone widens it after the human signed
    from orderguard_arena.envelopes import Envelope
    with pytest.raises(ValueError):
        b.add(Envelope(env.mandate, name="x"))


def _synthetic_stream():
    """Hand-made stream without budget interaction (huge daily cap in the sweep) so monotonicity is exact."""
    ev, i = [], 0
    for step in range(40):
        for notional, label, tickerr in ((500, "legit", "AAPL"), (3000, "legit", "MSFT"), (9000, "fat_finger", "AAPL"), (900, "stale_price", "MSFT"), (700, "legit", "NVDA")):
            i += 1
            tp = 100.0
            lim = 100.0 * (1.08 if label == "stale_price" else 1.002)
            ev.append({"i": i, "step": step, "agent": i % 7, "sleeve": "core", "label": label, "key": f"k{i}", "tp": tp, "risk": float(notional), "d": "-", "env": None, "code": "",
                       "order": {"ticker": tickerr, "side": "buy", "quantity": int(notional / tp), "limit_price": lim}})
    return ev


def test_frontier_monotone_in_stateless_knobs_and_pareto_is_nondominated():
    ev = _synthetic_stream()
    prof = stream_profile(ev, 10)
    big = 1e12
    rows = {}
    for po in (400, 1000, 4000, 10000):
        rows[("po", po)] = evaluate(ev, Candidate(po, big, 20.0, 3, None), prof, 10)
    for band in (0.1, 1.0, 5.0, 10.0):
        rows[("band", band)] = evaluate(ev, Candidate(10000, big, band, 3, None), prof, 10)
    for n in (0, 1, 2, 3):
        rows[("n", n)] = evaluate(ev, Candidate(10000, big, 20.0, n, None), prof, 10)
    for knob in ("po", "band", "n"):
        seq = [r for (k, _), r in rows.items() if k == knob]
        for a, b in zip(seq, seq[1:]):                                     # looser -> never less utility, never less leak
            assert b["utility_usd"] >= a["utility_usd"] and b["leaked_usd"] >= a["leaked_usd"], knob
    assert rows[("po", 400)]["utility_usd"] == 0 or rows[("po", 10000)]["utility_usd"] > rows[("po", 400)]["utility_usd"]
    assert rows[("n", 0)]["utility_usd"] == 0 == rows[("n", 0)]["leaked_usd"]            # an empty allow-list authorizes nothing
    fr = pareto(list(rows.values()))
    for p in fr:                                                              # nobody on the frontier is beaten on both axes
        assert not any(q["utility_usd"] >= p["utility_usd"] and q["leaked_usd"] < p["leaked_usd"] for q in rows.values())


def test_daily_cap_is_monotone_in_total_authorized_notional_on_a_real_stream(small_run):
    ev = small_run.events
    prof = stream_profile(ev, 100)
    prev = -1.0
    for f in (0.25, 0.5, 1.0, 2.0, 4.0):
        r = evaluate(ev, Candidate(60000, prof["legit_daily_usd"] * f, 10.0, len(prof["ranked_symbols"]), None), prof, 100)
        total = r["utility_usd"] + r["leaked_usd"]
        assert total >= prev - 1e-6
        prev = total


def test_run_frontier_on_a_small_stream_recommends_within_budget_and_stays_advice(small_run):
    meta = {"config": {"agents": 150, "steps_per_day": 100}, "envelopes": small_run.summary["envelopes"]}
    f = run_frontier(small_run.events, meta, samples=30, max_leak_per_day=1e12, max_approvals_per_day=1e9, max_false_refusal=1.0)
    rec = f["recommendation"]
    assert rec["feasible"] and rec["candidate"]["utility_usd"] == max(r["utility_usd"] for r in f["all"])
    m = rec["proposed_mandate"]
    assert "signature" not in m and "signerPublicKey" not in m and m["expiresAt"].startswith("<")      # unsigned: the human signs
    assert "you review and sign" in rec["explanation"] or "you sign" in rec["explanation"]
    tight = run_frontier(small_run.events, meta, samples=30, max_leak_per_day=0.0, max_approvals_per_day=0.0, max_false_refusal=1.0, with_monotonicity=False)
    assert tight["recommendation"]["candidate"]["leaked_usd"] == 0 or not tight["recommendation"]["feasible"]
    assert f["baseline"]["utility_usd"] > 0 and f["monotonicity"] is not None


def test_bench_smoke():
    r = bench_one(30, 120)
    assert r["proposals"] > 0 and r["authority_inline_decisions_per_s"] > 1000 and r["authority_replay_pass_orders_per_s"] > 1000
    assert r["replay_latency_us"]["p99"] >= r["replay_latency_us"]["p50"] > 0 and r["strict_orderGate_orders_per_s"] > 0


def test_api_router_endpoints():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    r = c.get("/api/arena/run", params={"agents": 60, "steps": 120}).json()
    assert r["summary"]["proposals"] > 0 and len(r["events"]) <= 400 and r["events_total"] >= len(r["events"])
    e = c.get("/api/arena/envelopes", params={"ticker": "AAPL", "quantity": 5}).json()
    assert {x["name"] for x in e["envelopes"]} == {"core", "tactical", "crypto"} and e["fit"]["tightest"] == "core"
    f = c.get("/api/arena/frontier", params={"agents": 60, "steps": 120, "samples": 8}).json()
    assert f["frontier"] and "explanation" in f["recommendation"]
    from orderguard_arena.api import MAX_AGENTS, MAX_WORK
    big = c.get("/api/arena/run", params={"agents": MAX_AGENTS, "steps": 2000}).json()
    cfg = big["summary"]["config"]
    assert cfg["agents"] <= MAX_AGENTS and cfg["agents"] * cfg["steps"] <= MAX_WORK          # one request stays bounded
    assert big["ran"] == {"agents": cfg["agents"], "steps": cfg["steps"], "feed": "synthetic"} and big["latency_us_samples"]
    feeds = c.get("/api/arena/feeds").json()
    assert "feeds" in feeds and feeds["limits"]["agents"] == MAX_AGENTS
    assert c.get("/api/arena/run", params={"feed": "../../pyproject.toml"}).status_code == 404     # feed names only, no paths
    assert all(isinstance(x, dict) and "leaked_per_day_usd" in x for x in f["candidates"])
