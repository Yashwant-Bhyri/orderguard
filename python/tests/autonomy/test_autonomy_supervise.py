"""Continuous supervision: leases and epochs, intent records, provenance, drift, herding by behaviour, loops, pacing."""
import random

import numpy as np
import pytest

from autonomy_helpers import Clock
from orderguard_autonomy import supervise as V


def test_leases_expire_and_renew_only_against_current_state():
    clk = Clock(0)
    la = V.LeaseAuthority(clock=clk, lease_seconds=60)
    lease = la.grant("a", "c")
    assert la.check(lease) is None
    la.observe_snapshot("c", 10)
    with pytest.raises(V.LeaseError, match="stale state"):
        la.renew(lease, 9)
    clk.t = 30
    lease2 = la.renew(lease, 10)
    clk.t = 61
    assert la.check(lease) == "lease expired"
    assert la.check(lease2) is None
    clk.t = 200
    with pytest.raises(V.LeaseError):
        la.renew(lease2, 10)


def test_epoch_revocation_ends_a_whole_spawned_chain_but_not_siblings():
    clk = Clock(0)
    la = V.LeaseAuthority(clock=clk, lease_seconds=100)
    root = la.grant("a", "c")
    child = la.grant("a.helper", "c", parent=root)
    grandchild = la.grant("a.helper.sub", "c", parent=child)
    sibling = la.grant("b", "c")
    assert grandchild.expires_at <= child.expires_at <= root.expires_at
    la.revoke_epoch("c", root.epoch, lineage="a")
    assert all(la.check(x) for x in (root, child, grandchild))
    assert la.check(sibling) is None
    with pytest.raises(V.LeaseError, match="quarantined"):
        la.grant("a", "c")                                            # a person must restore it
    la.restore("c", "a")
    fresh = la.grant("a", "c")
    assert fresh.epoch > root.epoch and la.check(fresh) is None
    with pytest.raises(V.LeaseError):
        la.grant("x", "c", parent=child)                              # cannot spawn from a revoked lease
    la.revoke_all("c")                                                # firm-wide kill
    assert la.check(sibling) and la.check(fresh)
    assert la.check(la.grant("b", "c")) is None                      # new leases after the kill are in a new epoch


def test_forged_or_altered_leases_and_deep_delegation_are_refused():
    la = V.LeaseAuthority(clock=Clock(0), lease_seconds=100, max_depth=1)
    root = la.grant("a", "c")
    assert la.check(V.Lease("a", "c", 0, 1e18, lease_id="lease-999")) == "unknown or altered lease"
    from dataclasses import replace
    assert la.check(replace(root, expires_at=1e18)) == "unknown or altered lease"
    child = la.grant("a1", "c", parent=root)
    with pytest.raises(V.LeaseError, match="too deep"):
        la.grant("a2", "c", parent=child)
    with pytest.raises(V.LeaseError, match="contract"):
        la.grant("a3", "other", parent=root)


def test_intent_record_mismatches_are_deterministic():
    rec = V.IntentRecord("a", "c", "obj", "add", "fundamental", "KO", "buy", 10, "t", 30, ("h",))
    assert V.intent_problems(rec, {"symbol": "KO", "side": "buy", "quantity": 10}, "obj") == []
    assert V.intent_problems(rec, {"symbol": "KO", "side": "buy", "quantity": 11}, "obj")
    assert V.intent_problems(rec, {"symbol": "PEP", "side": "buy", "quantity": 1}, "obj")
    assert V.intent_problems(rec, {"symbol": "KO", "side": "sell", "quantity": 1}, "obj")
    assert V.intent_problems(rec, {"symbol": "KO", "side": "buy", "quantity": 1}, "other-objective")
    from dataclasses import replace
    assert V.intent_problems(replace(rec, evidence=()), {"symbol": "KO", "side": "buy", "quantity": 1}, "obj")
    reduce = replace(rec, action="reduce", side="sell")
    assert V.intent_problems(reduce, {"symbol": "KO", "side": "sell", "quantity": 1}, "obj", position_qty=5) == []
    assert V.intent_problems(reduce, {"symbol": "KO", "side": "sell", "quantity": 1}, "obj", position_qty=0)   # would open a short
    assert V.intent_problems(None, {}, "obj") == ["no intent record"]


def test_claim_flags_catch_undeclared_sources_vague_figures_and_missing_units():
    known = {"h1"}
    rec = V.IntentRecord("a", "c", "o", "add", "news", "KO", "buy", 1, "This will skyrocket", 1, ("h1",),
                         (V.Claim("revenue up", 12.0, None, "h1"), V.Claim("deal is a sure thing", None, None, None),
                          V.Claim("margin 30%", 30.0, "%", "nope")))
    flags = V.claim_flags(rec, known)
    assert any("without a unit" in f for f in flags)
    assert any("undeclared source" in f for f in flags)
    assert any("does not exist" in f for f in flags)
    assert any("vague" in f for f in flags)
    clean = V.IntentRecord("a", "c", "o", "add", "fundamental", "KO", "buy", 1, "Cash flow covers the dividend twice", 1, ("h1",),
                           (V.Claim("free cash flow", 9.5, "USD bn", "h1"),))
    assert V.claim_flags(clean, known) == []


def test_provenance_collapses_reposts_and_near_copies_claiming_distinct_origins():
    ev = V.EvidenceStore()
    root = ev.register("mill", "Company X will announce a buyback of 20 billion tomorrow, people familiar said", 100)
    reposts = [ev.register(f"site{i}", f"Report: Company X will announce a buyback of 20 billion tomorrow, people familiar said ({i})", 101,
                           origin=f"site{i}", derived_from=(root.sha256,)) for i in range(4)]
    laundered = [ev.register(f"acct{i}", "BREAKING company x will announce a buyback of 20 billion tomorrow people familiar said", 102,
                             origin=f"acct{i}") for i in range(4)]
    p = ev.assess([x.sha256 for x in reposts + laundered], now=110, max_age_s=60, min_sources=2)
    assert p.independent_origins == 1 and not p.ok
    a = ev.register("wire", "Company X board approves share repurchase programme", 105)
    b = ev.register("sec", "8-K item 8.01: repurchase authorization of 20 billion dollars", 106)
    assert ev.assess([a.sha256, b.sha256, reposts[0].sha256], 110, 60, 2).independent_origins == 3
    assert not ev.assess(["f" * 64], 110, 60, 1).ok
    assert not ev.assess([root.sha256], 1000, 60, 1).ok                      # stale


def test_bernoulli_cusum_detects_drift_quickly_and_rarely_false_alarms():
    rng = np.random.default_rng(0)
    false_alarms, delays = 0, []
    for trial in range(300):
        det = V.BernoulliCUSUM(0.15, 0.45, 6.0)
        alarmed = any(det.update(rng.random() < 0.12) for _ in range(300))   # in control: 300 risk-adding orders
        false_alarms += alarmed
        det = V.BernoulliCUSUM(0.15, 0.45, 6.0)
        for i in range(400):
            if det.update(rng.random() < 0.5):
                delays.append(i + 1)
                break
    assert false_alarms / 300 < 0.05
    assert len(delays) == 300 and np.median(delays) < 30


def test_sprt_and_cusum_basics():
    s = V.SPRT(0.1, 0.5)
    assert next(r for r in (s.update(1) for _ in range(50)) if r) == "h1"
    s = V.SPRT(0.1, 0.5)
    assert next(r for r in (s.update(0) for _ in range(50)) if r) == "h0"
    c = V.CUSUM(target=0.0, k=0.5, h=3.0)
    assert not any(c.update(0.2) for _ in range(100))
    assert any(c.update(2.0) for _ in range(5))


def test_drift_monitor_flags_style_departure():
    style = {"staples": 0.4, "healthcare": 0.4, "index": 0.2}
    sectors = {"KO": "staples", "JNJ": "healthcare", "SPY": "index", "NVDA": "tech", "TSLA": "consumer"}
    dm = V.DriftMonitor(style, sectors)
    assert dm.check("a", {"KO": 40, "JNJ": 40, "SPY": 20}, ("KO", 10)) == []
    assert dm.check("a", {"NVDA": 80, "TSLA": 20}, ("NVDA", 10))                    # moves an off-style book further away
    assert dm.check("a", {"NVDA": 80, "TSLA": 20}, ("KO", 10)) == []                # moving back toward the style is never held
    small = V.DriftMonitor(style, sectors, min_book_usd=1_000)
    assert small.check("a", {"NVDA": 80}, ("NVDA", 10)) == []                       # too small a book to measure a style
    for i in range(30):
        dm.update("a", "NVDA" if i % 2 else "KO", True, i)
    assert "a" in dm.alarmed


def test_herding_is_keyed_on_behaviour_not_declared_identity():
    rng = random.Random(0)
    orders = []
    for step in range(40):
        for name in ("value-fund-7", "momentum-bot", "macro_desk_b", "contrarian_x"):          # different declared identities
            orders.append({"agent": name, "symbol": rng.choice(["NVDA", "MSFT", "AMZN"]), "side": "buy", "notional": 1000})
        orders.append({"agent": "independent", "symbol": rng.choice(["KO", "XOM"]), "side": rng.choice(["buy", "sell"]), "notional": 1000})
    clusters = V.herding_clusters(orders, min_similarity=0.7)
    assert {"value-fund-7", "momentum-bot", "macro_desk_b", "contrarian_x"} in clusters
    assert all("independent" not in g for g in clusters)
    shared = {a: ["root-rumour"] for a in ("value-fund-7", "momentum-bot", "macro_desk_b", "contrarian_x")}
    assert V.herding_signal(orders, shared) > V.herding_signal(orders, {}) > 0.3
    sectors = {"NVDA": "tech", "MSFT": "tech", "AMZN": "consumer", "KO": "staples", "XOM": "energy"}
    hm = V.HerdingMonitor(sectors, cluster_cap_usd=20_000, refresh=10, min_similarity=0.7)
    for o in orders:
        hm.observe(o["agent"], o["symbol"], o["side"], o["notional"], root="independent-doc" if o["agent"] == "independent" else "rumour")
    assert hm.check("momentum-bot", "NVDA", "buy", 1000)
    assert hm.check("independent", "NVDA", "buy", 1000) is None
    assert hm.check("momentum-bot", "NVDA", "sell", 1000) is None                       # reducing is never held
    # the same flows on independent sources are a diversified population, not a herd
    hm2 = V.HerdingMonitor(sectors, cluster_cap_usd=20_000, refresh=10, min_similarity=0.7)
    for i, o in enumerate(orders):
        hm2.observe(o["agent"], o["symbol"], o["side"], o["notional"], root=f"doc-{i % 12}")
    assert hm2.cluster_of("momentum-bot") is None


def test_loop_signal_counts_near_identical_repeats():
    assert V.loop_signal([("order", "KO buy 10 61.02")] * 3) == 0.0
    loop = [("order", f"KO buy 10 61.0{i % 2}") for i in range(10)]
    assert V.loop_signal(loop) >= 0.8
    varied = [("order", f"{s} buy {q} 100") for s, q in zip("ABCDEFGHIJ", range(10, 110, 10))]
    assert V.loop_signal(varied) == 0.0


def test_pacing_guarantees_each_agent_its_share_and_releases_unclaimed_capacity():
    p = V.PacingController(budget_usd=70_000, steps=100, agents=("fast",) + tuple(f"s{i}" for i in range(6)))
    fast = 0
    for step in range(20):
        if p.check("fast", step, 5_000) is None:
            p.record("fast", 5_000)
            fast += 5_000
    assert fast <= 10_000 + 70_000 * 0.2 + 5_000                 # its own share plus what the fading reservations released
    for i in range(6):                                           # every slow agent still finds its full share at step 20
        assert p.check(f"s{i}", 20, 8_000) is None
        p.record(f"s{i}", 8_000)
    late = V.PacingController(budget_usd=70_000, steps=100, agents=("fast", "idle"))
    assert late.check("fast", 99, 60_000) is None                 # at the end of the day nothing is held back for an idle agent
    assert V.PacingController(100_000, 100, ("x", "y")).check("x", 0, 50_000) is None   # inside its own share: never paced


def test_step_escalation_ladder():
    C = V.Control
    assert V.step({}) == C.CONTINUE
    assert V.step({"herding": 0.5}) == C.TIGHTEN
    assert V.step({"pacing": "ahead"}) == C.TIGHTEN
    assert V.step({"drift_alarm": True, "herding": 0.5}) == C.REVIEW
    assert V.step({"judgement_p": 0.7}) == C.REVIEW
    assert V.step({"provenance_problems": ["x"]}) == C.REVIEW
    assert V.step({"lease_problem": "expired", "drift_alarm": True}) == C.SUSPEND_NEW_RISK
    assert V.step({"loop": 0.9}) == C.SUSPEND_NEW_RISK
    with pytest.raises(TypeError):
        V.step(None)


def test_loop_signal_uses_a_time_window():
    same = [("order", "KO buy 100 62.1")] * 6
    assert V.loop_signal(same, times=[0, 10, 20, 30, 40, 50]) >= 0.8                 # six identical calls in a minute
    assert V.loop_signal(same, times=[0, 3600, 7200, 10800, 14400, 18000]) == 0.0    # the same trade once an hour is not a loop
    with pytest.raises(ValueError):
        V.loop_signal(same, times=[0])


def test_theme_herd_buying_different_names_clusters_at_sector_level():
    sectors = {"NVDA": "tech", "MSFT": "tech", "GOOGL": "tech", "AMZN": "consumer", "TSLA": "consumer"}
    rng = random.Random(3)
    orders = []
    for _ in range(12):
        for a in ("h1", "h2", "h3"):
            orders.append({"agent": a, "symbol": rng.choice(list(sectors)), "side": "buy", "notional": 1000, "root": "note"})
    assert V.herding_clusters(orders, 0.75, 3, require_shared_source=True, key=sectors.get)


def test_pacing_counts_net_exposure_so_rotation_is_free():
    p = V.PacingController(budget_usd=20_000, steps=100, agents=("a", "b"))
    for _ in range(10):                                           # buy 5k, sell 5k, ten times: turnover 100k, net 0
        assert p.check("a", 1, 5_000) is None
        p.record("a", 5_000)
        p.record("a", -5_000)
    assert p.spent["a"] == 0
