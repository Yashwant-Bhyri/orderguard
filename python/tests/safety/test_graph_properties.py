"""L7 trigger graph: randomized properties (fixed seeds)."""
from __future__ import annotations

import random

import pytest

from orderguard_guard.graph import (ROBOTICS, Rule, TriggerGraph, basket_mean_fall, graph_events, honest_events, real_crash_events, standing_rules,
                                    takeover_rule)

VENUES = [f"Venue{c}" for c in "ABCDEFGH"]


def price_rule(inputs, pct, notional=1000):
    return Rule("T1", "test rule", list(inputs), basket_mean_fall(list(inputs), pct), notional, "sell")


def quote_events(rng, tickers, venues, lo, hi):
    return [{"src": v, "type": "quote_change", "ticker": t, "pct": rng.uniform(lo, hi)} for v in venues for t in tickers]


def fired(res, rid):
    return next(r for r in res if r["rule"] == rid)["fires"]


def test_a_rule_never_fires_below_min_sources_of_independent_unquarantined_sources():
    rng = random.Random(1)
    n_fire = 0
    for _ in range(1500):
        inputs = rng.sample(["ISRG", "ROK", "TER", "MSFT"], rng.randint(1, 3))
        min_sources = rng.randint(1, 4)
        owners = {v: rng.choice(["o1", "o2", "o3"]) for v in VENUES} if rng.random() < 0.5 else {}
        g = TriggerGraph([price_rule(inputs, -10)], min_sources=min_sources, groups=owners)
        events = []
        for t in inputs:
            for v in rng.sample(VENUES, rng.randint(0, 6)):
                events.append({"src": v, "type": "quote_change", "ticker": t, "pct": rng.choice([-50.0, -30.0, -5.0, 3.0]),
                               **({"quarantined": True} if rng.random() < 0.2 else {})})
        bad = set(rng.sample(VENUES, rng.randint(0, 3)))
        res = g.evaluate(events, quarantined_sources=bad)
        if fired(res, "T1"):
            n_fire += 1
            for t in inputs:
                groups = {owners.get(e["src"], e["src"]) for e in events if e["ticker"] == t and not e.get("quarantined") and e["src"] not in bad}
                assert len(groups) >= min_sources, (t, groups, min_sources)
    assert n_fire > 100


def test_echoes_from_one_origin_count_once():
    rng = random.Random(2)
    rule = takeover_rule()
    g = TriggerGraph([rule], min_sources=2)
    for _ in range(1000):
        n = rng.randint(1, 12)
        wires = [{"src": f"Wire{i}", "origin": "AgencyX", "type": "headline", "ticker": "AAPL", "text": f"Consortium bid of $400 a share, version {i}"} for i in range(n)]
        assert not fired(g.evaluate(graph_events(wires)), "R2"), n                         # one origin, however many echoes
        second = wires + [{"src": "OtherWire", "origin": "AgencyY", "type": "headline", "ticker": "AAPL", "text": "Apple said to accept $400 buyout"}]
        assert fired(g.evaluate(graph_events(second)), "R2")                                # two independent origins is enough
        # the same independence through the `groups` option rather than the origin tag
        gg = TriggerGraph([rule], min_sources=2, groups={w["src"]: "OwnerZ" for w in wires})
        assert not fired(gg.evaluate(wires), "R2")


def test_one_lying_venue_cannot_move_the_median():
    rng = random.Random(3)
    g = TriggerGraph(standing_rules(), min_sources=2)
    for _ in range(1500):
        n_honest = rng.randint(2, 6)
        honest = rng.sample(VENUES[:-1], n_honest)
        events = quote_events(rng, ROBOTICS, honest, -3.0, 3.0)
        lie = rng.choice([-100.0, -90.0, -48.0, -41.0, 100.0, rng.uniform(-100, 100)])
        events += [{"src": VENUES[-1], "type": "quote_change", "ticker": t, "pct": lie} for t in ROBOTICS]
        res = g.evaluate(events)
        assert not fired(res, "R1"), (lie, n_honest)
        ins = g.read_inputs(events, standing_rules()[0])
        for t in ROBOTICS:
            vals = [e["pct"] for e in events if e["ticker"] == t and e["src"] != VENUES[-1]]
            assert min(vals) <= ins[t]["value"] <= max(vals)                               # the median stays inside the honest range


def test_a_real_crash_on_every_venue_still_fires_even_with_one_contrary_liar():
    rng = random.Random(4)
    g = TriggerGraph(standing_rules(), min_sources=2)
    for _ in range(500):
        pct = rng.uniform(-90, -41)
        events = real_crash_events(pct) + [{"src": "VenueX", "type": "quote_change", "ticker": t, "pct": rng.uniform(0, 100)} for t in ROBOTICS]
        assert fired(g.evaluate(events), "R1")


def test_quarantined_events_and_sources_are_inert():
    rng = random.Random(5)
    g = TriggerGraph(standing_rules(), min_sources=2)
    for _ in range(500):
        base = honest_events() if rng.random() < 0.5 else real_crash_events(-45.0)
        before = g.evaluate(base)
        noise = [{"src": "Liar", "type": "quote_change", "ticker": t, "pct": rng.uniform(-100, 100), "quarantined": True} for t in ROBOTICS * 3]
        noise += [{"src": "BadSource", "type": "quote_change", "ticker": t, "pct": -99.0} for t in ROBOTICS]
        after = g.evaluate(base + noise, quarantined_sources={"BadSource"})
        assert [(r["rule"], r["fires"]) for r in before] == [(r["rule"], r["fires"]) for r in after]


def test_blast_radius_is_monotone_in_the_size_of_the_lie():
    rng = random.Random(6)
    for _ in range(300):
        n = rng.randint(1, 4)
        base = quote_events(rng, ROBOTICS + ["MSFT"], VENUES[:n], -70.0, 5.0)
        g = TriggerGraph(standing_rules(), min_sources=rng.randint(1, 3), baseline=base)
        lies = sorted(rng.uniform(-100, 20) for _ in range(8))                             # most negative = biggest lie
        rep = g.blast_radius("LiarVenue", lies)
        naive = [r["naive_notional"] for r in rep]
        guarded = [r["guarded_notional"] for r in rep]
        assert naive == sorted(naive, reverse=True) and guarded == sorted(guarded, reverse=True)


def test_with_two_honest_venues_a_single_liar_has_zero_guarded_blast_radius():
    rng = random.Random(7)
    base = honest_events()
    g = TriggerGraph(standing_rules(), min_sources=2, baseline=base)
    rep = g.blast_radius("VenueC", [rng.uniform(-100, -41) for _ in range(200)])
    assert all(r["guarded_notional"] == 0 for r in rep)
    assert any(r["naive_notional"] > 0 for r in rep)


def test_permuting_events_from_distinct_sources_does_not_change_the_outcome():
    rng = random.Random(8)
    g = TriggerGraph(standing_rules(), min_sources=2)
    for _ in range(300):
        events = real_crash_events(rng.uniform(-80, -41)) if rng.random() < 0.5 else honest_events() + [
            {"src": "VenueC", "type": "quote_change", "ticker": t, "pct": -48.0} for t in ROBOTICS]
        shuffled = list(events)
        rng.shuffle(shuffled)
        a = [(r["rule"], r["fires"]) for r in g.evaluate(events)]
        b = [(r["rule"], r["fires"]) for r in g.evaluate(shuffled)]
        assert a == b


def test_a_rule_with_a_missing_input_never_fires():
    rng = random.Random(9)
    g = TriggerGraph([price_rule(ROBOTICS, -10)], min_sources=2)
    for _ in range(500):
        events = quote_events(rng, rng.sample(ROBOTICS, 2), VENUES[:4], -90.0, -50.0)          # one basket name has no print at all
        assert not fired(g.evaluate(events), "T1")
