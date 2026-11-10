from orderguard_guard import graph as GR
from orderguard_guard.bucket import RiskBucket


def fired(res):
    return [r["rule"] for r in res if r["fires"]]


def test_honest_morning_fires_nothing():
    assert fired(GR.TriggerGraph().evaluate(GR.honest_events())) == []


def test_single_liar_is_held_by_the_median():
    g = GR.TriggerGraph()
    ev = GR.single_venue_crash_events()
    assert "R1" in fired(GR.TriggerGraph.naive(g.rules, ev))          # a naive rule sells $30,000
    res = g.evaluate(ev)
    assert fired(res) == []
    r1 = next(r for r in res if r["rule"] == "R1")
    assert r1["held_reason"] and "VenueC" in r1["held_reason"]


def test_lone_source_cannot_fire_even_if_nothing_contradicts_it():
    ev = [{"src": "VenueC", "type": "quote_change", "ticker": t, "pct": -50} for t in GR.ROBOTICS]
    r1 = GR.TriggerGraph().evaluate(ev)[0]
    assert not r1["fires"] and "fewer than 2 independent sources" in r1["held_reason"]


def test_real_crash_still_fires():
    res = GR.TriggerGraph().evaluate(GR.real_crash_events())
    assert fired(res) == ["R1"] and res[0]["notional"] == 30000 and res[0]["side"] == "sell"


def test_quarantined_events_and_sources_are_ignored():
    ev = GR.real_crash_events()
    for e in ev:
        if e["src"] != "VenueA" and e["ticker"] in GR.ROBOTICS:
            e["quarantined"] = True
    assert fired(GR.TriggerGraph().evaluate(ev)) == []                       # only one source left
    b = RiskBucket()
    b.add({"source": "VenueB", "ticker": "ISRG", "text": "x"})
    assert fired(GR.TriggerGraph().evaluate(GR.real_crash_events(), quarantined_sources=b.quarantined_sources())) == ["R1"]  # A and C remain


def test_echoed_headline_counts_once_when_wires_share_an_owner():
    ev = GR.takeover_echo_events()
    assert "R2" in fired(GR.TriggerGraph().evaluate(ev))                     # three wires: it fires unless L3 quarantined them
    g = GR.TriggerGraph(groups={"FlashWire": "o", "MarketPulse": "o", "StreetTicker": "o"})
    r2 = next(r for r in g.evaluate(ev) if r["rule"] == "R2")
    assert not r2["fires"] and "independent sources" in r2["held_reason"]
    quarantined = [dict(e, quarantined=True) if e.get("type") == "headline" else e for e in ev]
    assert "R2" not in fired(GR.TriggerGraph().evaluate(quarantined))


def test_blast_radius_one_liar():
    rows = GR.TriggerGraph().blast_radius("VenueC", [-10, -25, -45, -60])
    assert [r["guarded_notional"] for r in rows] == [0, 0, 0, 0]
    assert rows[2]["naive_notional"] >= 30000 and rows[0]["naive_notional"] == 0
