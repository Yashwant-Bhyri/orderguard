import json
from pathlib import Path

import pytest

from og_s1.coherence import (
    FINDING_KINDS,
    case_for_step,
    coherence,
    finding_kinds,
)
from og_s1.schema import Episode
from og_s1.world import BINDING_ERROR, FAMILIES, FAMILIES_V21, simulate

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "data" / "ref"


def _episode(family, seed, shifted, coherent):
    return simulate(seed, family, 120, shifted, coherent=coherent)


def _rows(ep):
    for i, step in enumerate(ep.steps):
        yield i, step, coherence(step.action, case_for_step(ep, i))


def test_v2_reproduces_exactly():
    """The default generator still produces the v2 reference byte for byte."""
    for family in FAMILIES:
        path = REF / f"{family}.jsonl"
        if not path.exists():
            pytest.skip("reference corpus not present")
        lines = path.read_text(encoding="utf-8").splitlines()
        for i in range(3):
            expected = lines[i].strip()
            got = json.dumps(_episode(family, FAMILIES.index(family) * 1000 + i,
                                      False, False).to_dict())
            assert got == expected, (family, "unshifted", i)
        path = REF / f"{family}.shifted.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        for i in range(3):
            expected = lines[i].strip()
            got = json.dumps(_episode(family, FAMILIES.index(family) * 1000 + i,
                                      True, False).to_dict())
            assert got == expected, (family, "shifted", i)


def test_v21_clean_actions_have_zero_findings():
    for family in FAMILIES_V21:
        for shifted in (False, True):
            seed = 8000 if family == BINDING_ERROR else 0
            ep = _episode(family, seed, shifted, True)
            dirty = [(i, finding_kinds(fs)) for i, step, fs in _rows(ep)
                     if step.label.y == 0 and fs]
            assert not dirty, (family, shifted, dirty[:3])


def test_v21_non_binding_failures_are_coherent():
    """In v2.1 only binding_error may be incoherent."""
    for family in FAMILIES:
        for shifted in (False, True):
            ep = _episode(family, 1, shifted, True)
            dirty = [(i, finding_kinds(fs)) for i, step, fs in _rows(ep)
                     if step.label.y == 1 and fs]
            assert not dirty, (family, shifted, dirty[:3])


def test_binding_error_positives_have_findings_that_point_at_cause_refs():
    for shifted in (False, True):
        for seed in (8000, 8001, 8002, 8003):
            ep = _episode(BINDING_ERROR, seed, shifted, True)
            positives = 0
            for i, step, fs in _rows(ep):
                if step.label.y != 1:
                    continue
                positives += 1
                assert step.label.cause == BINDING_ERROR
                assert step.label.cause_refs
                assert fs, (seed, i)
                refs = {r for f in fs for r in f["refs"]}
                assert refs & set(step.label.cause_refs), (seed, i, fs, step.label.cause_refs)
            assert positives > 0, seed


def test_binding_error_hard_negatives_have_zero_findings():
    hard = 0
    for shifted in (False, True):
        ep = _episode(BINDING_ERROR, 8000, shifted, True)
        for i, step, fs in _rows(ep):
            if step.label.y == 0:
                assert not fs, (shifted, i, fs)
                if "versus" in step.action.rationale:
                    hard += 1
        assert hard > 0


def test_reference_episode_57_step_80_is_incoherent():
    path = REF / "clean.jsonl"
    if not path.exists():
        pytest.skip("reference corpus not present")
    ep = Episode.from_dict(json.loads(path.read_text(encoding="utf-8").splitlines()[57]))
    step = ep.steps[80]
    assert step.action.instrument == "PEP" and step.action.side == "sell"
    kinds = set(finding_kinds(coherence(step.action, case_for_step(ep, 80))))
    assert "rationale_direction" in kinds
    assert "rationale_foreign_instrument" in kinds
    assert "claim_not_about_trade" in kinds


def test_labels_do_not_enter_the_check():
    ep = _episode("clean", 0, False, True)
    before = [finding_kinds(fs) for _, _, fs in _rows(ep)]
    for step in ep.steps:
        step.label.y = 1
        step.label.cause = BINDING_ERROR
        step.label.cause_refs = ["d0"]
    after = [finding_kinds(fs) for _, _, fs in _rows(ep)]
    assert before == after


def test_meta_shift_flag_does_not_enter_the_check():
    """The surface form is inferred from text, not read from meta."""
    for shifted in (False, True):
        ep = _episode("clean", 0, shifted, True)
        before = [finding_kinds(fs) for _, _, fs in _rows(ep)]
        ep.meta["shifted"] = not shifted
        after = [finding_kinds(fs) for _, _, fs in _rows(ep)]
        assert before == after


def test_explicit_relative_value_is_not_foreign():
    ep = _episode(BINDING_ERROR, 8000, False, True)
    seen = False
    for i, step, fs in _rows(ep):
        if "versus" in step.action.rationale and step.label.y == 0:
            seen = True
            assert "rationale_foreign_instrument" not in finding_kinds(fs)
            assert "claim_foreign_instrument" not in finding_kinds(fs)
    assert seen


def test_direction_flips_are_detected():
    ep = _episode("clean", 0, False, True)
    index, step = next((i, s) for i, s in enumerate(ep.steps) if s.action.side == "buy")
    step.action.rationale = "Taking some of the position off the table after the run."
    assert "rationale_direction" in finding_kinds(
        coherence(step.action, case_for_step(ep, index))
    )


def test_finding_kinds_are_stable():
    assert set(FINDING_KINDS) == {
        "rationale_direction",
        "rationale_foreign_instrument",
        "claim_not_about_trade",
        "claim_foreign_instrument",
        "claim_source_entity_mismatch",
        "claim_stale_period",
    }
