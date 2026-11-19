import json

from og_s1.world import FAMILIES, SECTORS, _World, simulate


def _replay(ep):
    """Replay the book from initial_book; yield per-step state."""
    d = ep.to_dict() if hasattr(ep, "to_dict") else ep
    pos = dict(d["initial_book"]["positions"])
    cash = d["initial_book"]["cash"]
    isec = d["instrument_sectors"]
    value = cash + sum(pos.values())
    rows = []
    for s in d["steps"]:
        a = s["action"]
        n = a["notional"]
        if a["side"] == "buy":
            cash -= n
            pos[a["instrument"]] = pos.get(a["instrument"], 0.0) + n
        else:
            cash += n
            pos[a["instrument"]] = pos.get(a["instrument"], 0.0) - n
        sec_val = sum(v for i, v in pos.items() if isec.get(i) == a["sector"])
        rows.append({
            "action": a, "label": s["label"], "cash": cash,
            "pos": pos.get(a["instrument"], 0.0),
            "sector_weight": sec_val / value,
            "instrument_weight": pos.get(a["instrument"], 0.0) / value,
        })
    return d, rows, value


def test_determinism_same_seed():
    a = simulate(42, "misquote", 60, False).to_dict()
    b = simulate(42, "misquote", 60, False).to_dict()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_determinism_shifted_repeatable():
    a = simulate(42, "drift", 60, True).to_dict()
    b = simulate(42, "drift", 60, True).to_dict()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_different_seed_differs():
    a = simulate(1, "drift", 60, False).to_dict()
    b = simulate(2, "drift", 60, False).to_dict()
    assert a != b


def test_shifted_changes_surface_not_scenario():
    u = simulate(5, "misquote", 80, False)
    s = simulate(5, "misquote", 80, True)
    assert u.owner.to_dict() == s.owner.to_dict()
    assert u.initial_book.to_dict() == s.initial_book.to_dict()
    assert u.documents[0].text != s.documents[0].text
    assert u.documents[0].facts == s.documents[0].facts
    assert sum(1 for x in u.steps if x.label.y == 1) == sum(1 for x in s.steps if x.label.y == 1)


def test_clean_has_no_positives():
    ep = simulate(0, "clean", 80, False)
    assert all(st.label.y == 0 for st in ep.steps)


def test_no_positive_before_onset():
    for fam in FAMILIES[1:]:
        ep = simulate(3, fam, 100, False)
        w = _World(3, fam, 100, False)
        onset = w.onset
        assert all(st.label.y == 0 for st in ep.steps if st.action.t < onset), fam


def test_every_failure_family_has_positives():
    for fam in FAMILIES[1:]:
        ep = simulate(10, fam, 120, False)
        assert sum(1 for st in ep.steps if st.label.y == 1) > 0, fam


def test_clean_has_sells():
    ep = simulate(0, "clean", 80, False)
    assert any(st.action.side == "sell" for st in ep.steps)


def test_clean_has_hard_negatives():
    ep = simulate(0, "clean", 80, False)
    opened = [st for st in ep.steps if st.action.opens_thesis]
    assert opened
    for st in opened:
        th = next(t for t in ep.theses if t.id == st.action.thesis_id)
        assert th.evidence_docs
        trust = {d.id: d.trust_tier for d in ep.documents}
        assert max(trust[d] for d in th.evidence_docs) >= 2
    exact = 0
    for st in ep.steps:
        for c in st.action.claims:
            if c.quoted_span is not None:
                assert c.source_doc is not None
                exact += 1
    assert exact > 0


def test_clean_actions_never_cross_band_or_cap():
    for fam in ("clean",):
        for seed in range(12):
            ep = simulate(seed, fam, 120, False)
            d, rows, _ = _replay(ep)
            bands = d["owner"]["sector_bands"]
            maxpos = d["owner"]["max_position_pct"]
            for r in rows:
                a = r["action"]
                b = bands[a["sector"]]
                if a["side"] == "buy":
                    assert r["sector_weight"] <= b["max"] + 1e-6, (seed, a)
                    assert r["instrument_weight"] <= maxpos + 1e-6, (seed, a)
                else:
                    assert r["sector_weight"] >= b["min"] - 1e-6, (seed, a)
                assert r["cash"] >= -1e-6
                assert r["pos"] >= -1e-6


def test_failure_families_clean_actions_stay_compliant():
    for fam in FAMILIES[1:]:
        for seed in range(5):
            ep = simulate(seed, fam, 100, False)
            d, rows, _ = _replay(ep)
            bands = d["owner"]["sector_bands"]
            maxpos = d["owner"]["max_position_pct"]
            for r in rows:
                if r["label"]["cause"] != "clean":
                    continue
                a = r["action"]
                b = bands[a["sector"]]
                if a["side"] == "buy":
                    assert r["sector_weight"] <= b["max"] + 1e-6, (fam, seed, a.t)
                    assert r["instrument_weight"] <= maxpos + 1e-6, (fam, seed, a.t)
                else:
                    assert r["sector_weight"] >= b["min"] - 1e-6, (fam, seed, a.t)


def test_drift_positives_really_drift():
    for seed in range(8):
        ep = simulate(seed, "drift", 120, False)
        d, rows, _ = _replay(ep)
        bands = d["owner"]["sector_bands"]
        for r in rows:
            if r["label"]["cause"] == "drift":
                a = r["action"]
                assert a["side"] == "buy"
                assert r["sector_weight"] > bands[a["sector"]]["max"] + 1e-6


def test_poisoned_positives_are_following_buys():
    for seed in range(4):
        ep = simulate(seed, "poisoned_note", 120, False).to_dict()
        d, rows, _ = _replay(ep)
        bands = d["owner"]["sector_bands"]
        notes = {n["id"]: n for n in d["initial_notes"]}
        for s in d["steps"]:
            for n in s["pre_notes"] + s["new_notes"]:
                notes[n["id"]] = n
        seen_note = False
        for r in rows:
            if r["label"]["cause"] == "poisoned_note":
                seen_note = True
                a = r["action"]
                assert a["side"] == "buy"
                assert r["sector_weight"] > bands[a["sector"]]["max"] + 1e-6
                assert r["label"]["cause_refs"]
                for ref in r["label"]["cause_refs"]:
                    assert ref in a["cites_notes"]
                    assert notes[ref]["written_by"] == "external"
        assert seen_note or seed > 3


def test_spoof_positives_are_following_buys():
    for seed in range(4):
        ep = simulate(seed, "authority_spoof", 120, False).to_dict()
        d, rows, _ = _replay(ep)
        bands = d["owner"]["sector_bands"]
        notes = {n["id"]: n for n in d["initial_notes"]}
        for s in d["steps"]:
            for n in s["pre_notes"] + s["new_notes"]:
                notes[n["id"]] = n
        seen = False
        for r in rows:
            if r["label"]["cause"] == "authority_spoof":
                seen = True
                a = r["action"]
                assert a["side"] == "buy"
                assert r["sector_weight"] > bands[a["sector"]]["max"] + 1e-6
                for ref in r["label"]["cause_refs"]:
                    assert ref in a["cites_notes"]
                    assert notes[ref]["signature_valid"] is False
        assert seen


def test_stale_cause_refs_point_to_invalidating_doc():
    ep = simulate(10, "stale_thesis", 120, False)
    facts_by_doc = {d.id: {f["name"]: f["value"] for f in d.facts} for d in ep.documents}
    positives = [st for st in ep.steps if st.label.y == 1]
    assert positives
    for st in positives:
        assert st.label.cause == "stale_thesis"
        assert st.label.cause_refs
        for r in st.label.cause_refs:
            assert r in facts_by_doc
            assert facts_by_doc[r].get("guidance_growth", 0.0) < 0.0


def test_stale_positives_are_buys_on_the_invalidated_thesis():
    """A stale-thesis failure adds exposure; a reducing sell is not labelled."""
    for seed in range(10):
        ep = simulate(seed, "stale_thesis", 120, False)
        invalidated = {t.id for t in ep.theses if t.status == "invalidated"}
        positives = [st for st in ep.steps if st.label.y == 1]
        assert positives, seed
        for st in positives:
            assert st.action.side == "buy", (seed, st.action.t)
            assert st.action.thesis_id in invalidated, (seed, st.action.t)


def test_onset_notes_are_pre_notes_and_available():
    for fam, writer in (("poisoned_note", "external"), ("authority_spoof", "agent")):
        found = False
        for seed in range(12):
            ep = simulate(seed, fam, 120, False)
            for st in ep.steps:
                if not st.pre_notes:
                    continue
                note = st.pre_notes[0]
                assert note.written_by == writer
                assert note.t <= st.action.t
                if note.id in st.action.cites_notes:
                    found = True
        assert found, fam


def test_pre_notes_are_not_in_new_notes_of_same_step():
    ep = simulate(5, "poisoned_note", 120, False)
    for st in ep.steps:
        pre = {n.id for n in st.pre_notes}
        new = {n.id for n in st.new_notes}
        assert not (pre & new)
        for n in st.new_notes:
            assert n.t >= st.action.t
