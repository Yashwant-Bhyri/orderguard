from og_s1.validate import validate
from og_s1.world import FAMILIES, simulate


def _ep(family="clean", seed=20):
    return simulate(seed, family, 40, False).to_dict()


def test_validate_accepts_every_family():
    for fam in FAMILIES:
        assert validate(_ep(fam, 3)) == [], fam


def test_rejects_missing_key():
    e = _ep()
    del e["owner"]
    assert validate(e)


def test_rejects_missing_new_top_level_keys():
    for key in ("initial_book", "instrument_sectors"):
        e = _ep()
        del e[key]
        assert validate(e)


def test_rejects_bad_enum():
    e = _ep()
    e["owner"]["purpose"] = "yolo"
    assert validate(e)


def test_rejects_missing_sector_band():
    e = _ep()
    del e["owner"]["sector_bands"]["energy"]
    errs = validate(e)
    assert any("missing sectors" in x for x in errs)


def test_rejects_bad_id_ref():
    e = _ep()
    e["steps"][0]["action"]["thesis_id"] = "does_not_exist"
    assert validate(e)


def test_rejects_broken_span():
    e = _ep()
    for st in e["steps"]:
        for c in st["action"]["claims"]:
            if c["quoted_span"]:
                c["quoted_span"] = "zzz not a real span"
                assert validate(e)
                return
    assert False, "no claim with a quoted span found"


def test_rejects_span_without_source():
    e = _ep()
    for st in e["steps"]:
        for c in st["action"]["claims"]:
            if c["quoted_span"]:
                c["source_doc"] = None
                errs = validate(e)
                assert any("quoted_span has no source_doc" in x for x in errs)
                return
    assert False, "no claim with a quoted span found"


def test_rejects_non_monotone_time():
    e = _ep()
    e["steps"][0]["action"]["t"] = 999
    assert validate(e)


def test_rejects_bad_content_hash():
    e = _ep()
    e["documents"][0]["content_hash"] = "0" * 64
    assert validate(e)


def test_rejects_missing_label():
    e = _ep()
    del e["steps"][0]["label"]
    assert validate(e)


def test_rejects_owner_signed_without_signature():
    e = _ep()
    e["initial_notes"][0]["signature_valid"] = False
    assert validate(e)


def test_rejects_too_many_sentences():
    e = _ep()
    e["documents"][0]["text"] = "A. " * 7
    assert validate(e)


def test_rejects_long_rationale():
    e = _ep()
    e["steps"][0]["action"]["rationale"] = "One. Two. Three. Four."
    errs = validate(e)
    assert any("rationale must have 1-3 sentences" in x for x in errs)


def test_accepts_novel_cause():
    e = _ep()
    e["steps"][-1]["label"]["y"] = 1
    e["steps"][-1]["label"]["cause"] = "some_novel_cause"
    assert validate(e) == []


def test_rejects_clean_cause_with_y1():
    e = _ep()
    e["steps"][-1]["label"]["y"] = 1
    e["steps"][-1]["label"]["cause"] = "clean"
    assert validate(e)


def test_rejects_relabelled_drift_positive():
    """Changing a drift positive's y to 0 without changing its cause fails."""
    e = _ep("drift", 3)
    for st in e["steps"]:
        if st["label"]["cause"] == "drift" and st["label"]["y"] == 1:
            st["label"]["y"] = 0
            errs = validate(e)
            assert any("y=0 must have cause clean" in x for x in errs), errs
            return
    assert False, "no drift positive found"


def test_rejects_band_breaching_negative_with_novel_cause():
    """A relabel that hides a mandate breach is caught by the replay itself."""
    e = _ep("drift", 3)
    for st in e["steps"]:
        if st["label"]["cause"] == "drift" and st["label"]["y"] == 1:
            st["label"]["y"] = 0
            st["label"]["cause"] = "some_novel_cause"
            errs = validate(e)
            assert any("y=0 must have cause clean" in x for x in errs), errs
            assert any("above max" in x for x in errs), errs
            return
    assert False, "no drift positive found"


def test_rejects_claim_citing_future_document():
    e = _ep()
    action_t = e["steps"][0]["action"]["t"]
    future = next((d for d in e["documents"] if d["t"] > action_t), None)
    assert future is not None
    for st in e["steps"]:
        for c in st["action"]["claims"]:
            if c["source_doc"] is not None:
                c["source_doc"] = future["id"]
                c["quoted_span"] = None
                errs = validate(e)
                assert any("not yet available" in x for x in errs)
                return
    assert False, "no sourced claim found"


def test_rejects_action_citing_future_note():
    ep = simulate(7, "poisoned_note", 60, False).to_dict()
    poison = None
    for st in ep["steps"]:
        for n in st["pre_notes"] + st["new_notes"]:
            if n["written_by"] == "external":
                poison = n
                break
        if poison:
            break
    assert poison is not None and poison["t"] > 0
    ep["steps"][0]["action"]["cites_notes"] = [poison["id"]]
    errs = validate(ep)
    assert any("not yet available" in x for x in errs)


def test_rejects_note_citing_unknown_document():
    e = _ep()
    e["initial_notes"][0]["cites"] = ["no_such_doc"]
    errs = validate(e)
    assert any("cites unknown document" in x for x in errs)


def test_rejects_duplicate_document_id_nonadjacent():
    e = _ep()
    e["documents"][0]["id"] = e["documents"][-1]["id"]
    errs = validate(e)
    assert any("duplicate document id" in x for x in errs)


def test_same_step_pre_note_reference_is_accepted():
    e = _ep()
    st = e["steps"][5]
    t = st["action"]["t"]
    note = {
        "id": "n_pre_test", "t": t, "text": "The tool confirms the position.",
        "written_by": "tool", "signature_valid": False, "cites": [],
    }
    st["pre_notes"].append(note)
    st["action"]["cites_notes"].append("n_pre_test")
    assert validate(e) == []


def test_same_step_new_note_reference_is_rejected():
    e = _ep()
    st = e["steps"][5]
    t = st["action"]["t"]
    note = {
        "id": "n_new_test", "t": t, "text": "A note written after the trade.",
        "written_by": "agent", "signature_valid": False, "cites": [],
    }
    st["new_notes"].append(note)
    st["action"]["cites_notes"].append("n_new_test")
    errs = validate(e)
    assert any("same-step new note" in x for x in errs)


def test_later_step_note_reference_is_rejected():
    e = _ep()
    later = e["steps"][-1]
    note = {
        "id": "n_later", "t": later["action"]["t"], "text": "A later note.",
        "written_by": "agent", "signature_valid": False, "cites": [],
    }
    later["pre_notes"].append(note)
    e["steps"][0]["action"]["cites_notes"].append("n_later")
    errs = validate(e)
    assert any("not yet available" in x for x in errs)


def test_rejects_clean_sell_crossing_sector_minimum():
    e = _ep()
    for st in e["steps"]:
        a = st["action"]
        if st["label"]["cause"] == "clean" and a["side"] == "sell":
            # Size the sale far beyond any plausible floor.
            a["notional"] = 900000.0
            errs = validate(e)
            assert any("below min" in x or "negative" in x for x in errs)
            return
    assert False, "no clean sell found"


def test_rejects_clean_buy_crossing_sector_maximum():
    e = _ep()
    for st in e["steps"]:
        a = st["action"]
        if st["label"]["cause"] == "clean" and a["side"] == "buy":
            a["notional"] = 2000000.0
            errs = validate(e)
            assert any("above max" in x or "negative" in x for x in errs)
            return
    assert False, "no clean buy found"


def test_rejects_drift_label_on_non_buy():
    e = _ep("drift", 3)
    for st in e["steps"]:
        if st["label"]["cause"] == "drift":
            st["action"]["side"] = "sell"
            errs = validate(e)
            assert any("drift label on a non-buy" in x for x in errs)
            return
    assert False, "no drift positive found"


def test_rejects_initial_book_inconsistent_sectors():
    e = _ep()
    sec = next(iter(e["initial_book"]["sectors"]))
    e["initial_book"]["sectors"][sec] += 5000.0
    errs = validate(e)
    assert any("does not equal the sum" in x for x in errs)


def test_rejects_missing_instrument_sector():
    e = _ep()
    inst = next(iter(e["initial_book"]["positions"]))
    del e["instrument_sectors"][inst]
    errs = validate(e)
    assert any("no instrument_sectors entry" in x for x in errs)
