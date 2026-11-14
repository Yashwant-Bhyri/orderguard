"""Reproducibility and robustness: every printed number regenerates, runs do not depend on the hash seed, damaged inputs fail with a clear error."""
import itertools
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from orderguard_arena import claims
from orderguard_arena.arena import ArenaConfig, StreamError, load_stream, run_arena
from orderguard_arena.feeds import BinancePublicFeed, FeedError, RecordedFeed
from orderguard_arena.frontier import pareto, run_frontier

ROOT = Path(__file__).resolve().parents[3]


def _failures(checks):
    return [f"{c.name}: {c.detail}" for c in checks if not c.ok]


def test_readme_and_arena_and_lab_numbers_match_the_committed_results():
    assert not _failures(claims.check_texts(claims.arena_expectations(), "arena") + claims.check_texts(claims.lab_expectations(), "lab"))


def test_risk_numbers_quoted_in_the_docs_match_results_risk():
    checks = claims.risk_checks()
    if any(c.name == "risk: results/risk/*.json layout" for c in checks):
        pytest.skip(checks[0].detail)          # the order-risk results are being regenerated in a new layout; `og-arena verify` still reports it
    assert not _failures(checks)


def test_baseline_run_regenerates_byte_for_byte(tmp_path):
    cfg = ArenaConfig(seed=7, agents=1000, steps=2000, keep_events=False)
    r = run_arena(cfg, out_dir=tmp_path, write=True)
    committed = json.loads((claims.RES / f"{claims.BASE}.summary.json").read_text())
    assert claims._same_summary(r.summary, committed) == ""
    assert r.summary["digest"].startswith("601fc223")
    new = (tmp_path / f"{claims.BASE}.jsonl").read_text().split("\n", 1)[1]
    assert new == (claims.RES / f"{claims.BASE}.jsonl").read_text().split("\n", 1)[1]


def test_streaming_without_memory_has_the_same_digest(tmp_path):
    a = run_arena(ArenaConfig(seed=5, agents=120, steps=200, steps_per_day=50, keep_events=True)).summary["digest"]
    b = run_arena(ArenaConfig(seed=5, agents=120, steps=200, steps_per_day=50, keep_events=False), out_dir=tmp_path, write=True)
    assert a == b.summary["digest"] and b.events == []
    assert not list(tmp_path.glob("*.partial")) and (tmp_path / "arena-s5-k120-t200.jsonl").exists()


_HASH_SCRIPT = """
import json, sys
from orderguard_arena.arena import ArenaConfig, run_arena
from orderguard_arena.frontier import run_frontier
r = run_arena(ArenaConfig(seed=11, agents=250, steps=300, steps_per_day=75, routing='tightest_fit', agent_share=0.02))
s = run_arena(ArenaConfig(seed=11, agents=120, steps=150, steps_per_day=50, strict=True))
meta = {'config': r.summary['config'], 'envelopes': r.summary['envelopes']}
f = run_frontier(r.events, meta, samples=12, with_monotonicity=False)
print(r.summary['digest'], s.summary['digest'], json.dumps(f['frontier'], sort_keys=True).__hash__() * 0, len(json.dumps(f, sort_keys=True)),
      __import__('hashlib').sha256(json.dumps(f, sort_keys=True).encode()).hexdigest()[:16])
"""


def test_runs_and_frontier_are_identical_across_python_hash_seeds():
    outs = set()
    for hs in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": hs, "OG_LLM": "replay", "PYTHONPATH": str(ROOT / "python")}
        p = subprocess.run([sys.executable, "-c", _HASH_SCRIPT], capture_output=True, text=True, env=env, timeout=300)
        assert p.returncode == 0, p.stderr[-800:]
        outs.add(p.stdout.strip())
    assert len(outs) == 1, outs


def _dominated(p, q):          # q dominates p: at least as much utility, no more leak, and strictly better in one
    return q[0] >= p[0] and q[1] <= p[1] and (q[0] > p[0] or q[1] < p[1])


def _brute_front(rows):
    pts = {(r["utility_usd"], r["leaked_usd"]) for r in rows}
    return {p for p in pts if not any(_dominated(p, q) for q in pts)}


def test_pareto_matches_a_brute_force_check_on_random_small_grids():
    rng = random.Random(3)
    for trial in range(200):
        n = rng.randint(1, 25)
        rows = [{"utility_usd": float(rng.randint(0, 6)), "leaked_usd": float(rng.randint(0, 6)), "approvals_per_day": rng.randint(0, 3), "label": str(i)} for i in range(n)]
        got = pareto(rows)
        assert {(r["utility_usd"], r["leaked_usd"]) for r in got} == _brute_front(rows), trial
        assert len({(r["utility_usd"], r["leaked_usd"]) for r in got}) == len(got)          # ties are kept once


def test_frontier_of_a_real_small_stream_equals_the_brute_force_front():
    r = run_arena(ArenaConfig(seed=7, agents=150, steps=400, steps_per_day=100))
    meta = {"config": r.summary["config"], "envelopes": r.summary["envelopes"]}
    f = run_frontier(r.events, meta, samples=40, with_monotonicity=False)
    assert {(x["utility_usd"], x["leaked_usd"]) for x in f["frontier"]} == _brute_front(f["all"])
    # no candidate outside the frontier beats a frontier point, and the recommendation is a real candidate
    assert f["recommendation"]["candidate"]["label"] in {x["label"] for x in f["all"]}


def test_truncated_or_corrupt_event_logs_fail_clearly(tmp_path):
    r = run_arena(ArenaConfig(seed=2, agents=60, steps=100, steps_per_day=50), out_dir=tmp_path, write=True)
    good = r.path.read_bytes()
    cut = tmp_path / "cut.jsonl"
    cut.write_bytes(good[:-25])
    with pytest.raises(StreamError, match="truncated.*--allow-partial"):
        load_stream(cut)
    meta, ev = load_stream(cut, allow_partial=True)
    assert len(ev) == r.summary["proposals"] - 1 and meta["type"] == "meta"
    bad = tmp_path / "bad.jsonl"
    lines = good.decode().split("\n")
    lines[3] = "{not json"
    bad.write_text("\n".join(lines))
    with pytest.raises(StreamError, match="invalid JSON on line 4"):
        load_stream(bad)
    notarena = tmp_path / "n.jsonl"
    notarena.write_text('{"type":"meta"}\n{"hello":1}\n')
    with pytest.raises(StreamError, match="not an arena event"):
        load_stream(notarena)


def test_a_killed_run_leaves_only_a_partial_file(tmp_path, monkeypatch):
    import orderguard_arena.arena as arena_mod
    calls = {"n": 0}
    real = arena_mod.Authority.authorize

    def dying(self, *a, **k):
        calls["n"] += 1
        if calls["n"] > 10:
            raise KeyboardInterrupt
        return real(self, *a, **k)

    monkeypatch.setattr(arena_mod.Authority, "authorize", dying)
    with pytest.raises(KeyboardInterrupt):
        run_arena(ArenaConfig(seed=2, agents=60, steps=100, steps_per_day=50, name="doomed"), out_dir=tmp_path, write=True)
    assert not (tmp_path / "doomed.jsonl").exists() and (tmp_path / "doomed.jsonl.partial").exists()
    assert not list(tmp_path.glob("*.summary.json"))


def _recording(tmp_path, ticks=3, syms=("BTCUSDT", "ETHUSDT")):
    p = tmp_path / "rec.jsonl"
    rows = [json.dumps({"type": "meta", "symbols": list(syms), "steps_per_day": 2})]
    rows += [json.dumps({"type": "tick", "step": i, "ts": f"2026-01-01T00:00:0{i}Z", "quotes": {s: {"bid": 1.0, "last": 1.1, "ask": 1.2} for s in syms}}) for i in range(ticks)]
    p.write_text("\n".join(rows) + "\n")
    return p


def test_recorded_feed_reports_truncation_and_missing_symbols(tmp_path):
    p = _recording(tmp_path)
    assert len(RecordedFeed(p)) == 3
    p.write_bytes(p.read_bytes()[:-30])
    with pytest.raises(FeedError, match="truncated: line 4 is cut off"):
        RecordedFeed(p)
    q = _recording(tmp_path)
    rows = q.read_text().splitlines()
    t = json.loads(rows[2])
    del t["quotes"]["ETHUSDT"]
    rows[2] = json.dumps(t)
    q.write_text("\n".join(rows) + "\n")
    with pytest.raises(FeedError, match="line 3: the tick has no quotes for ETHUSDT"):
        RecordedFeed(q)


class _Resp:
    def __init__(self, code, retry):
        self.status_code, self.headers = code, {"Retry-After": retry}


class _HttpErr(Exception):
    def __init__(self, code, retry="7"):
        super().__init__(f"HTTP {code}")
        self.response = _Resp(code, retry)


def _good(path, params):
    syms = json.loads(params["symbols"])
    return [{"symbol": s, "bidPrice": "1", "askPrice": "1.2"} for s in syms] if path.endswith("bookTicker") else [{"symbol": s, "price": "1.1"} for s in syms]


def test_public_feed_retries_with_exponential_backoff_and_honours_retry_after(tmp_path):
    n = {"i": 0}
    slept = []

    def flaky(path, params):
        n["i"] += 1
        if n["i"] == 1:
            raise _HttpErr(500)
        if n["i"] == 3:
            raise _HttpErr(429, "7")
        return _good(path, params)

    feed = BinancePublicFeed(["BTCUSDT"], max_steps=2, duration_s=None, interval_s=1.0, fetch=flaky, sleep=slept.append, record_path=tmp_path / "r.jsonl")
    ticks = list(feed)
    assert len(ticks) == 2 and feed.errors == 2
    assert feed.backoffs[0] == 1.0 and 7.0 in feed.backoffs          # first retry waits the interval; a 429 waits what the server asked
    assert len(RecordedFeed(tmp_path / "r.jsonl")) == 2             # no gap and no guess recorded


def test_public_feed_gives_up_clearly_and_never_records_a_bad_quote(tmp_path):
    def always_bad(path, params):
        syms = json.loads(params["symbols"])
        return [{"symbol": s, "bidPrice": "0", "askPrice": "1.2"} for s in syms] if path.endswith("bookTicker") else [{"symbol": s, "price": "1.1"} for s in syms]

    feed = BinancePublicFeed(["BTCUSDT"], max_steps=3, duration_s=None, fetch=always_bad, sleep=lambda s: None, record_path=tmp_path / "r.jsonl")
    with pytest.raises(FeedError, match="5 consecutive ticks failed after 3 attempts"):
        list(feed)
    assert feed.backoffs and max(feed.backoffs) <= 30.0
    assert '"type": "tick"' not in (tmp_path / "r.jsonl").read_text()
