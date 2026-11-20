"""T15 tests: causal Case extraction, renderings, metrics, splits and the spec.

Every metric is pinned by a hand-computed example.  The leakage tests mutate
future fields (and labels/meta) and prove that earlier Cases do not move.
"""

from __future__ import annotations

import copy
import inspect
import json
import math
import re

import numpy as np
import pytest

from og_s1.eval import (
    CAUSE_TRUTH_TYPE,
    RENDERINGS,
    Case,
    CodeLogisticReader,
    auroc,
    axes_for_meta,
    bootstrap_ci,
    cases,
    cost_summary,
    coverage_at_false_allow,
    ece,
    escalation_rate,
    expected_hash,
    false_holds_per_1000,
    group_split,
    labels,
    pointer_accuracy,
    reader_inputs,
    render_case,
    render_lengths,
    risk_from_prob,
    select_calibration_threshold,
    select_conformal_threshold,
    spec_hash,
    split_summary,
    tag_shift_axes,
    top_cause_accuracy,
    truth_type_for,
    verify_spec,
)
from og_s1.eval.splits import assert_episode_disjoint, assert_group_disjoint
import importlib

cases_module = importlib.import_module("og_s1.eval.cases")
from og_s1.readers.base import (
    QUESTIONS,
    ConstantReader,
    risk_array,
    scores_array,
    validate_scores,
)
from og_s1.world import simulate


def episode(family: str = "clean", seed: int = 0, n_steps: int = 20, shifted: bool = False):
    return simulate(seed=seed, family=family, n_steps=n_steps, shifted=shifted)


# ---------------------------------------------------------------------------
# Causal extraction
# ---------------------------------------------------------------------------


def test_cases_use_only_model_view_at(monkeypatch):
    calls = {"n": 0}
    original = cases_module.model_view_at

    def counted(ep, i):
        calls["n"] += 1
        return original(ep, i)

    monkeypatch.setattr(cases_module, "model_view_at", counted)
    ep = episode(n_steps=12)
    got = cases(ep, code_features=False)
    assert len(got) == 12
    assert calls["n"] == 12
    calls["n"] = 0
    got = cases(ep, code_features=True)
    assert len(got) == 12
    # cases itself still reads one causal view per action.  featurize has its
    # own imported binding, so it is deliberately not counted here.
    assert calls["n"] == 12


def test_cases_module_has_no_whole_episode_model_view():
    assert not hasattr(cases_module, "model_view")
    source = inspect.getsource(cases_module)
    source = source.replace("model_view_at(", "")
    assert "model_view(" not in source


def test_no_future_field_reaches_case():
    ep = episode(family="clean", n_steps=20)
    before = [c.to_dict() for c in cases(ep)]
    cut = 10
    cut_t = ep.steps[cut].action.t

    for j in range(cut + 1, len(ep.steps)):
        step = ep.steps[j]
        step.action.rationale = "FUTURE_RATIONALE"
        if step.action.claims:
            step.action.claims[0].text = "FUTURE_CLAIM"
        for note in step.new_notes:
            note.text = "FUTURE_NOTE"
        step.label.y = 1 if step.label.y == 0 else 0
        step.label.cause = "future_cause"
        step.label.cause_refs = ["future"]
    for doc in ep.documents:
        if doc.t > cut_t:
            doc.text = "FUTURE_DOC"
            doc.facts = []
    for note in ep.steps[cut].new_notes:
        note.text = "FUTURE_SAME_STEP_NOTE"
    for note in ep.initial_notes:
        note.text = note.text  # no-op: initial notes are visible
    for thesis in ep.theses:
        thesis.status = "invalidated"
    ep.meta = {"author": "FUTURE_AUTHOR", "family": "poisoned_note", "seed": 1, "shifted": True}

    after = [c.to_dict() for c in cases(ep)]
    for i in range(cut + 1):
        assert before[i] == after[i]
        blob = json.dumps(after[i], sort_keys=True)
        assert "FUTURE" not in blob
    for item in after:
        assert not ({"label", "meta", "status"} & set(item))
        if item["thesis"] is not None:
            assert "status" not in item["thesis"]

    # Appending a future step must not change any earlier Case, including its
    # episode key (the key is built from the owner, the first action and the
    # initial book, not from the number of future steps).
    extra = copy.deepcopy(ep.steps[-1])
    extra.action.t += 1
    extra.label.y = 1
    extra.label.cause = "future_cause"
    ep.steps.append(extra)
    appended = [c.to_dict() for c in cases(ep)]
    for i in range(cut + 1):
        assert appended[i] == before[i]


def test_no_future_field_of_any_kind_reaches_case():
    """Exhaustive future-field probe: every future field class that could leak.

    The earlier test mutates text, facts, rationale, labels, ``meta`` and thesis
    ``status``.  This one also creates a future thesis and mutates every future
    thesis, document, note and action field a Case could conceivably read.
    """
    ep = episode(family="unsupported_claim", seed=31, n_steps=20)
    before = [c.to_dict() for c in cases(ep, code_features=False)]
    before_with_features = [c.to_dict() for c in cases(ep, code_features=True)]
    cut = 9
    cut_t = ep.steps[cut].action.t

    # (a) A thesis opened strictly after the cut must not appear anywhere.
    from og_s1.schema import Thesis

    ep.theses.append(
        Thesis(
            id="FUTURE_THESIS_ID",
            statement="FUTURE_THESIS_STATEMENT",
            sector="energy",
            opened_t=cut_t + 5,
            evidence_docs=["FUTURE_EVIDENCE_DOC"],
            invalidation="FUTURE_INVALIDATION",
            invalidation_trigger={"field": "FUTURE_TRIGGER", "op": ">", "value": 1.0},
            status="active",
        )
    )

    # (b) Every existing future thesis: statement, sector, evidence, invalidation.
    for thesis in ep.theses:
        if thesis.opened_t > cut_t:
            thesis.statement = "FUTURE_THESIS_STATEMENT"
            thesis.sector = "FUTURE_SECTOR"
            thesis.evidence_docs = ["FUTURE_EVIDENCE_DOC"]
            thesis.invalidation = "FUTURE_INVALIDATION"
            thesis.invalidation_trigger = {"field": "FUTURE_TRIGGER", "op": ">", "value": 1.0}
            thesis.status = "FUTURE_STATUS"

    # (c) Future documents: publisher, trust tier, kind, facts, text, hash.
    for doc in ep.documents:
        if doc.t > cut_t:
            doc.publisher = "FUTURE_PUBLISHER"
            doc.trust_tier = -99
            doc.kind = "FUTURE_KIND"
            doc.facts = [{"name": "FUTURE_FACT", "value": -1.0, "unit": "x"}]
            doc.text = "FUTURE_DOC_TEXT"
            doc.content_hash = "FUTURE_DOC_HASH"

    # (d) Future notes: writer, signature, citations, text.
    def mutate_future_notes(notes):
        for note in notes:
            if note.t > cut_t:
                note.written_by = "FUTURE_WRITER"
                note.signature_valid = not note.signature_valid
                note.cites = ["FUTURE_CITED_DOC"]
                note.text = "FUTURE_NOTE_TEXT"

    mutate_future_notes(ep.initial_notes)
    for j, step in enumerate(ep.steps):
        if j > cut:
            mutate_future_notes(step.pre_notes)
            mutate_future_notes(step.new_notes)
        else:
            # This step's *new* notes are written after its action, so they are
            # future to that action too; at j == cut they must not leak either.
            mutate_future_notes(step.new_notes)
    # The cut step's new notes are future to its own action and to every
    # earlier case; mutate their non-text fields explicitly.
    for note in ep.steps[cut].new_notes:
        note.written_by = "FUTURE_WRITER"
        note.signature_valid = not note.signature_valid
        note.cites = ["FUTURE_CITED_DOC"]
        note.text = "FUTURE_NOTE_TEXT"

    # (e) Future actions: notional, sector, instrument, side, thesis id, notes.
    for step in ep.steps[cut + 1 :]:
        step.action.notional = -12345.0
        step.action.sector = "FUTURE_SECTOR"
        step.action.instrument = "FUTURE_TICKER"
        step.action.side = "sell" if step.action.side == "buy" else "buy"
        step.action.thesis_id = "FUTURE_THESIS_ID"
        step.action.cites_notes = ["FUTURE_NOTE_ID"]
        step.action.rationale = "FUTURE_RATIONALE"
        if step.action.claims:
            step.action.claims[0].text = "FUTURE_CLAIM"
            step.action.claims[0].source_doc = "FUTURE_DOC_ID"
            step.action.claims[0].quoted_span = "FUTURE_SPAN"
        step.label.y = 1 - int(step.label.y)
        step.label.cause = "FUTURE_CAUSE"
        step.label.cause_refs = ["FUTURE_REF"]

    ep.meta = {
        "author": "FUTURE_AUTHOR",
        "family": "poisoned_note",
        "seed": 999,
        "shifted": True,
        "agent_id": "FUTURE_AGENT",
    }

    after = [c.to_dict() for c in cases(ep, code_features=False)]
    after_with_features = [c.to_dict() for c in cases(ep, code_features=True)]
    assert len(after) == len(before)
    for i in range(cut + 1):
        assert before[i] == after[i], f"case {i} changed when only future fields moved"
        assert before_with_features[i] == after_with_features[i], (
            f"case {i} code features changed when only future fields moved"
        )
        blob = json.dumps(after[i], sort_keys=True)
        assert "FUTURE" not in blob
        assert "FUTURE_THESIS_ID" not in blob
    for item in after:
        assert not ({"label", "meta", "status"} & set(item))
        if item["thesis"] is not None:
            assert "status" not in item["thesis"]


def test_document_time_boundary_is_causal():
    ep = episode(family="misquote", seed=3, n_steps=8)
    baseline = cases(ep, code_features=False)
    first_t = ep.steps[0].action.t
    case0 = baseline[0]
    claim_index, claim = next(
        (j, c) for j, c in enumerate(case0.claims)
        if c.source_available and c.source_t == first_t
    )
    at_t = next(d for d in ep.documents if d.id == claim.source_doc)
    after_t = next(d for d in ep.documents if d.t > first_t)
    original_text = at_t.text
    at_t.text = "VISIBLE_CHANGE"
    after_t.text = "INVISIBLE_CHANGE"
    changed = cases(ep, code_features=False)
    assert changed[0].claims[claim_index].source_text == "VISIBLE_CHANGE"
    # The document after the action time is not in any earlier case.
    for old, new in zip(baseline, changed):
        if old.index <= 0:
            assert "INVISIBLE_CHANGE" not in json.dumps(new.to_dict(), sort_keys=True)
    at_t.text = original_text


def test_case_holds_claims_notes_and_trust():
    ep = episode(family="clean", seed=7, n_steps=10)
    cs = cases(ep, code_features=False)
    case = next(c for c in cs if c.claims and c.notes)
    assert case.claims
    claim = case.claims[0]
    if claim.source_available:
        doc = next(d for d in ep.documents if d.id == claim.source_doc)
        assert claim.source_text == doc.text
        assert list(claim.source_facts) == [dict(f) for f in doc.facts]
    note = case.notes[0]
    assert note.available
    assert note.text
    assert case.trust["owner_key"] == ep.owner.signing_key_id
    if case.thesis is not None:
        assert not hasattr(case.thesis, "status")


def test_case_serialisation_has_no_eval_fields():
    for family in ("clean", "misquote", "poisoned_note"):
        cs = cases(episode(family=family, seed=11, n_steps=8))
        for case in cs:
            item = case.to_dict()
            assert "label" not in item
            assert "meta" not in item
            assert "status" not in json.dumps(item)
            assert set(item["action"]).isdisjoint({"label", "meta"})


# ---------------------------------------------------------------------------
# Renderings
# ---------------------------------------------------------------------------


def test_renderings_are_deterministic_distinct_and_measured():
    cs = cases(episode(family="unsupported_claim", seed=5, n_steps=6), code_features=False)
    case = cs[-1]
    texts = {name: render_case(case, name) for name in RENDERINGS}
    for name in RENDERINGS:
        assert texts[name] == render_case(case, name)
        assert texts[name]
    assert len({texts[name] for name in RENDERINGS}) == 4
    lengths = render_lengths(case)
    for name in RENDERINGS:
        assert lengths[name]["chars"] == len(texts[name])
        assert lengths[name]["tokens"] == len(texts[name].split())


def test_render_rejects_unknown_kind():
    case = cases(episode(n_steps=2), code_features=False)[0]
    with pytest.raises(ValueError):
        render_case(case, "no_such_rendering")


# ---------------------------------------------------------------------------
# Reader interface
# ---------------------------------------------------------------------------


class _OneNoneReader:
    name = "one_none"

    def score(self, cases, rendering="raw"):
        n = len(cases)
        return {
            "supported": [0.9] * n,
            "hype": [None] * n,
            "authority": [0.1] * n,
            "addresses_reviewer": [0.0] * n,
        }


def test_reader_contract_keeps_none_and_rejects_bad_values():
    cs = cases(episode(n_steps=3), code_features=False)
    scores = validate_scores(_OneNoneReader().score(cs), len(cs))
    assert scores["hype"] == [None, None, None]
    assert scores_array(scores, "hype").shape == (3,)
    assert np.isnan(scores_array(scores, "hype")).all()
    # supported is oriented as risk = 1 - p
    assert np.allclose(risk_array(scores, "supported"), 0.1)
    assert np.allclose(risk_array(scores, "hype", ), np.nan, equal_nan=True)

    bad = {
        "supported": [0.5] * 3,
        "hype": [0.5] * 2,
        "authority": [0.5] * 3,
        "addresses_reviewer": [0.5] * 3,
    }
    with pytest.raises(ValueError):
        validate_scores(bad, 3)
    bad["hype"] = [0.5] * 3
    bad["authority"] = [1.5, 0.5, 0.5]
    with pytest.raises(ValueError):
        validate_scores(bad, 3)
    del bad["authority"]
    with pytest.raises(KeyError):
        validate_scores(bad, 3)


def test_constant_reader_answers_all_questions():
    cs = cases(episode(n_steps=4), code_features=False)
    reader = ConstantReader(0.25)
    scores = validate_scores(reader.score(cs), len(cs))
    for question in QUESTIONS:
        assert scores[question] == [0.25] * 4
    assert reader.cause_scores(cs) is None
    assert reader.pointers(cs) is None


def test_code_logistic_reader_runs_on_small_episodes():
    train = cases(episode(family="misquote", seed=21, n_steps=10))
    test = cases(episode(family="clean", seed=22, n_steps=10))
    y = [1 if c.claims and any(not c.quoted_span_in_source for c in c.claims) else 0 for c in train]
    if len(set(y)) < 2:
        y = [i % 2 for i in range(len(train))]
    reader = CodeLogisticReader()
    reader.fit(train, y)
    scores = validate_scores(reader.score(test), len(test))
    for question in QUESTIONS:
        arr = np.asarray(scores[question], dtype=float)
        assert arr.shape == (len(test),)
        assert np.all((arr >= 0) & (arr <= 1))
    causes = reader.cause_argmax(test)
    assert len(causes) == len(test)
    assert all(c in CAUSE_TRUTH_TYPE for c in causes)
    pointers = reader.pointers(test)
    assert pointers is not None and len(pointers) == len(test)


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


def test_group_split_is_deterministic_and_disjoint():
    groups = [f"g{i % 100}" for i in range(500)]
    split = group_split(groups)
    assert (split == group_split(groups)).all()
    assert_group_disjoint(groups, split)
    summary = split_summary(groups, split)
    assert summary["train"]["cases"] + summary["cal"]["cases"] + summary["test"]["cases"] == 500
    assert summary["groups_total"] == 100
    assert all(summary[name]["groups"] > 0 for name in ("train", "cal", "test"))


def test_group_split_requires_three_groups():
    with pytest.raises(ValueError):
        group_split(["a", "a", "b"])


def test_random_row_split_is_rejected():
    groups = [f"g{i % 40}" for i in range(400)]
    rng = np.random.default_rng(0)
    split = rng.integers(0, 3, size=len(groups))
    with pytest.raises(AssertionError):
        assert_group_disjoint(groups, split)


def test_manual_group_leak_is_rejected():
    groups = ["a", "a", "b", "b", "c"]
    split = [0, 1, 0, 0, 2]
    with pytest.raises(AssertionError):
        assert_group_disjoint(groups, split)


def test_episode_leak_is_rejected_even_when_group_keys_are_disjoint():
    # Two episodes trade the same two companies.  A company split is
    # group-key-disjoint but puts each episode on both sides.
    companies = ["A", "B", "A", "B"]
    episodes = ["e1", "e1", "e2", "e2"]
    split = [0, 2, 0, 2]
    assert_group_disjoint(companies, split)  # passes: A->0, B->2
    with pytest.raises(AssertionError):
        assert_episode_disjoint(episodes, split)


def test_owner_and_episode_splits_keep_episodes_together():
    episodes = [f"e{i // 120}" for i in range(1200)]
    owners = [f"o{i // 120}" for i in range(1200)]
    for groups in (episodes, owners):
        split = group_split(groups)
        assert_group_disjoint(groups, split)
        assert_episode_disjoint(episodes, split)


# ---------------------------------------------------------------------------
# Metrics: hand-computed examples
# ---------------------------------------------------------------------------


def test_auroc_hand_computed():
    metric = auroc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8], n_boot=0)
    assert metric.n == 4
    assert metric.value == pytest.approx(0.75)
    assert math.isnan(metric.lo) and math.isnan(metric.hi)


def test_ece_hand_computed():
    metric = ece([0, 1], [0.0, 0.2], n_bins=10, n_boot=0)
    assert metric.value == pytest.approx(0.4)
    zero = ece([0, 0, 1, 1], [0.0, 0.0, 1.0, 1.0], n_bins=2, n_boot=0)
    assert zero.value == pytest.approx(0.0)


def _coverage_example():
    y_cal = [0] * 20 + [1]
    s_cal = [0.01 * i for i in range(1, 21)] + [0.99]
    y_test = [0, 0, 0, 1]
    s_test = [0.01, 0.20, 0.99, 0.50]
    return y_cal, s_cal, y_test, s_test


def test_empirical_threshold_uses_midpoint_candidates():
    # The largest feasible observed score is 0.20, but the largest feasible
    # threshold below the bad 0.99 is the midpoint 0.595.  The old observed-only
    # rule understated coverage for continuous scores.
    y_cal, s_cal = _coverage_example()[0], _coverage_example()[1]
    picked = select_calibration_threshold(y_cal, s_cal)
    assert picked["tau"] == pytest.approx(0.595)
    assert picked["allowed"] == 20
    assert picked["bad"] == 0
    assert picked["upper"] == pytest.approx(1.0 / 21.0)
    assert picked["rule"] == "empirical_add_one"

    metric = coverage_at_false_allow(
        y_cal,
        s_cal,
        [0, 0, 0, 1],
        [0.1, 0.2, 0.5, 0.99],
        rule="empirical",
        n_boot=0,
    )
    assert metric.value == pytest.approx(1.0)
    assert metric.extra["tau"] == pytest.approx(0.595)
    assert metric.extra["good_allowed_test"] == 3


def test_conformal_bound_hand_computed():
    # 200 clean at 0.10, 5 clean at 0.20, 5 bad at 0.30.  The grid threshold
    # 0.29 is the most permissive point below the bad 0.30: B=0, A=205, and the
    # CP upper bound is under 0.05.  The grid point 0.30 includes the 5 bad
    # cases (B=5, A=210) and its bound exceeds 0.05, so tau*=0.29.
    y_cal = [0] * 200 + [0] * 5 + [1] * 5
    s_cal = [0.10] * 200 + [0.20] * 5 + [0.30] * 5
    picked = select_conformal_threshold(y_cal, s_cal)
    assert picked["rule"] == "clopper_pearson_bonferroni"
    assert picked["candidates"] == 101
    assert picked["tau"] == pytest.approx(0.29)
    assert picked["allowed"] == 205
    assert picked["bad"] == 0
    assert picked["upper"] <= 0.05
    assert picked["hold_all"] is False

    metric = coverage_at_false_allow(
        y_cal,
        s_cal,
        [0, 0, 0, 1],
        [0.10, 0.20, 0.25, 0.30],
        n_boot=0,
    )
    assert metric.value == pytest.approx(1.0)
    assert metric.extra["tau"] == pytest.approx(0.29)
    assert metric.extra["rule"] == "clopper_pearson_bonferroni"
    assert metric.extra["cal_upper"] <= 0.05


def test_coverage_holds_everything_when_no_threshold_is_feasible():
    metric = coverage_at_false_allow(
        [0, 1],
        [0.5, 0.9],
        [0, 1],
        [0.5, 0.9],
        n_boot=0,
    )
    assert metric.value == 0.0
    assert metric.extra["tau"] == -math.inf
    assert metric.extra["hold_all"] is True
    picked = select_conformal_threshold([0, 1], [0.5, 0.9])
    assert picked["tau"] == -math.inf
    assert picked["hold_all"] is True
    feasible = select_calibration_threshold(_coverage_example()[0], _coverage_example()[1])
    assert feasible["hold_all"] is False


def test_none_scores_fail_closed_in_coverage():
    # Reviewer's concrete case: abstaining on two clean test cases must not
    # remove them from the denominator.  With tau=0.595 the only answered
    # clean case (0.1) is allowed, so coverage is 1/3, not 1.0.
    y_cal, s_cal = _coverage_example()[0], _coverage_example()[1]
    metric = coverage_at_false_allow(
        y_cal,
        s_cal,
        [0, 0, 0, 1],
        [0.1, float("nan"), float("nan"), 0.5],
        tau=0.595,
        n_boot=0,
    )
    assert metric.extra["n_good_test"] == 3
    assert metric.extra["good_allowed_test"] == 1
    assert metric.value == pytest.approx(1.0 / 3.0)
    assert metric.extra["bad_allowed_test"] == 1
    assert metric.extra["n_abstained_clean_test"] == 2
    assert metric.extra["abstention_rate_clean_test"] == pytest.approx(2.0 / 3.0)


def test_supplied_tau_is_honoured_for_slice_comparability():
    y_cal, s_cal, y_test, s_test = _coverage_example()
    metric = coverage_at_false_allow(
        y_cal,
        s_cal,
        y_test,
        s_test,
        tau=0.595,
        n_boot=0,
    )
    assert metric.extra["tau"] == pytest.approx(0.595)
    assert metric.extra["hold_all"] is False
    assert metric.value == pytest.approx(2.0 / 3.0)
    # A fixed hold-all threshold must be explicit, not nan.
    hold = coverage_at_false_allow(
        y_cal, s_cal, y_test, s_test, tau=-math.inf, n_boot=0
    )
    assert hold.value == 0.0
    assert hold.extra["hold_all"] is True


def test_auroc_and_ece_fail_closed_on_abstention():
    # One clean case abstains.  Fail-closed ranks it above all answered risks,
    # so the single positive (0.9) beats 0.1 but loses to the abstention:
    # AUROC = 1/2.  The answered subset is a perfect 1.0 and is reported
    # separately, so the abstention cannot be mistaken for an improvement.
    metric = auroc([0, 1, 0], [float("nan"), 0.9, 0.1], n_boot=0)
    assert metric.value == pytest.approx(0.5)
    assert metric.extra["n_abstained"] == 1
    assert metric.extra["abstention_rate"] == pytest.approx(1.0 / 3.0)
    assert metric.extra["answered_value"] == pytest.approx(1.0)
    # ECE sees the abstention as maximal risk, not as a dropped row.
    cal = ece([0, 1, 0], [float("nan"), 0.9, 0.1], n_bins=10, n_boot=0)
    assert cal.extra["n_abstained"] == 1
    assert cal.n == 3
    assert cal.value > 0.0


def test_t11_question_orientation_is_pinned():
    # T11: supported is a good property; hype, authority and
    # addresses_reviewer are all bad-property questions.
    assert risk_from_prob("supported", 0.9) == pytest.approx(0.1)
    for question in ("hype", "authority", "addresses_reviewer"):
        assert risk_from_prob(question, 0.9) == pytest.approx(0.9)
    # A reader that gives high P(yes) to bad cases and low P(yes) to good
    # cases scores AUROC 1.0 for every bad-property question.
    metric = auroc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9], n_boot=0)
    assert metric.value == pytest.approx(1.0)


def test_top_cause_accuracy_hand_computed():
    metric = top_cause_accuracy(
        [1, 1, 1, 1],
        ["a", "a", "b", "b"],
        ["a", "b", "a", "b"],
        [True, True, True, True],
        groups=[0, 1, 2, 3],
        n_boot=0,
    )
    assert metric.n == 4
    assert metric.value == pytest.approx(0.5)


def test_pointer_accuracy_hand_computed():
    metric = pointer_accuracy(
        [1, 1, 1, 1],
        [["d1"], ["d2"], [], ["d3"]],
        [["d1", "d9"], ["d9"], ["d2"], ["d3"]],
        [True, True, True, True],
        groups=[0, 1, 2, 3],
        n_boot=0,
    )
    assert metric.n == 3
    assert metric.value == pytest.approx(2.0 / 3.0)


def test_pointer_oversized_set_and_missing_prediction_are_misses():
    # A prediction that names every document must not score.  The size cap is
    # max(1, len(true_refs)) + 2 = 3 here.
    metric = pointer_accuracy(
        [1, 1],
        [["d1"], ["d2"]],
        [["d1", "d2", "d3", "d4"], None],
        [True, True],
        groups=[0, 1],
        n_boot=0,
    )
    assert metric.n == 2
    assert metric.value == 0.0
    assert metric.extra["n_missing_prediction"] == 1


def test_top_cause_missing_prediction_counts_as_miss():
    metric = top_cause_accuracy(
        [1, 1],
        ["a", "b"],
        ["a", None],
        [True, True],
        groups=[0, 1],
        n_boot=0,
    )
    assert metric.n == 2
    assert metric.value == pytest.approx(0.5)
    assert metric.extra["n_missing_prediction"] == 1


def test_false_holds_and_escalation_hand_computed():
    fh = false_holds_per_1000([0, 0, 0, 1], [True, False, False, False], n_boot=0)
    assert fh.value == pytest.approx(250.0)
    assert fh.n == 4
    er = escalation_rate([True, False, False, False], n_boot=0)
    assert er.value == pytest.approx(0.25)


def test_cost_summary_hand_computed():
    costs = cost_summary([0.01, 0.02, 0.03, 0.04], n_decisions=4, gpu_seconds=2.0, n_boot=0)
    assert costs["mean_ms"] == pytest.approx(25.0)
    assert costs["p50_ms"] == pytest.approx(25.0)
    assert costs["p99_ms"] == pytest.approx(39.7)
    assert costs["gpu_seconds_per_1000"] == pytest.approx(500.0)


def test_bootstrap_ci_is_deterministic_and_brackets_mean():
    values = [0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0]
    groups = [0, 0, 1, 1, 2, 2, 3, 3]
    first = bootstrap_ci(values, groups, n_boot=100, seed=7)
    second = bootstrap_ci(values, groups, n_boot=100, seed=7)
    assert first == second
    assert first[0] <= np.mean(values) <= first[1]


def test_metric_ci_brackets_point_estimate():
    metric = auroc([0, 0, 1, 1, 0, 1], [0.1, 0.4, 0.35, 0.8, 0.2, 0.9], groups=[0, 0, 1, 1, 2, 2], n_boot=50)
    assert metric.lo <= metric.value <= metric.hi


# ---------------------------------------------------------------------------
# Truth types and axes
# ---------------------------------------------------------------------------


def test_every_label_carries_a_truth_type():
    ep = episode(family="drift", seed=9, n_steps=12)
    records = labels(ep)
    assert len(records) == len(ep.steps)
    for record, step in zip(records, ep.steps):
        assert record.y == int(step.label.y)
        assert record.cause == step.label.cause
        assert record.truth_type in ("formal", "evidential", "preference")
        assert record.source == "synthetic_reference"
        if record.y == 0:
            assert record.truth_type == "preference"
        else:
            assert record.truth_type != "preference"


def test_truth_type_mapping():
    assert truth_type_for("clean") == "preference"
    assert truth_type_for("drift") == "formal"
    assert truth_type_for("authority_spoof") == "formal"
    for cause in ("unsupported_claim", "misquote", "vague_hype", "poisoned_note", "stale_thesis"):
        assert truth_type_for(cause) == "evidential"
    assert truth_type_for("novel_cause") == "evidential"
    # No real preference positives exist in the reference labels.
    for family in ("clean", "drift", "unsupported_claim", "vague_hype"):
        ep = episode(family=family, seed=2, n_steps=8)
        for step in ep.steps:
            if step.label.y == 1:
                assert truth_type_for(step.label.cause) != "preference"


def test_shift_axes_are_evaluation_only():
    assert axes_for_meta({"family": "clean", "shifted": False}) == ()
    assert axes_for_meta({"family": "clean", "shifted": True}) == ("semantic",)
    assert axes_for_meta({"family": "stale_thesis", "shifted": False}) == ("temporal",)
    assert axes_for_meta({"family": "poisoned_note", "shifted": False}) == ("adversarial",)
    assert axes_for_meta({"family": "stale_thesis", "shifted": True}) == ("semantic", "temporal")
    ep = episode(family="poisoned_note", seed=4, n_steps=6)
    cs = cases(ep, code_features=False)
    tagged = tag_shift_axes(cs, ep.meta)
    assert all(c.shift_axes == ("adversarial",) for c in tagged)
    assert all(c.shift_axes == () for c in reader_inputs(tagged))
    # Tagging must not change any causal field.
    stripped = reader_inputs(tagged)
    for a, b in zip(cs, stripped):
        assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------------------
# Fixtures and artifact checks
# ---------------------------------------------------------------------------


def test_fact_match_requires_the_same_unit():
    fact = {"name": "revenue", "value": 10.0, "unit": "USD"}
    assert cases_module._fact_matches(10.0, "USD", [fact]) is True
    assert cases_module._fact_matches(10.0, None, [fact]) is False
    assert cases_module._fact_matches(10.0, "EUR", [fact]) is False
    unitless = [{"name": "revenue", "value": 10.0, "unit": None}]
    assert cases_module._fact_matches(10.0, None, unitless) is True
    assert cases_module._fact_matches(10.0, "USD", unitless) is False


def test_artifact_scan_covers_the_whole_readers_package():
    import importlib.util

    path = __file__.replace("tests/test_eval.py", "check_artifacts.py")
    spec = importlib.util.spec_from_file_location("t15_check_artifacts", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    roots = {str(root).replace("\\", "/") for root in module.SCAN_ROOTS}
    assert any(root.endswith("/og_s1") or root.endswith("og_s1") for root in roots)
    assert any(root.endswith("/work/T15") or root.endswith("T15") for root in roots)


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def test_spec_hash_is_stable_and_matches_the_committed_hash():
    first = spec_hash()
    second = spec_hash()
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert expected_hash() == first
    ok, actual, expected = verify_spec()
    assert ok and actual == expected == first
