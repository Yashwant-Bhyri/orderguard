"""The grader must be able to FAIL. A gate that lets everything through, or distrusts everything, has to score badly."""
from orderguard_verify.core import evalrun


def case(group, honest=False, expect=("blocked",), **kw):
    return {"id": f"{group}-{kw.pop('i', 0)}", "group": group, "honest": honest, "expect": list(expect), **kw}


FALSE_NUMBER = dict(planted={"attribute": "revenue", "false_value": 6.5e9}, right_reason={"kind": "claim", "label": "contradicted"})
CASES = (
    [case("Honest", True, ["cleared"], i=i) for i in range(5)]
    + [case("False number", i=i, **FALSE_NUMBER) for i in range(3)]
    + [case("Stale", expect=["held", "blocked"], planted={"attribute": "revenue", "false_value": 4.0e9}, right_reason={"kind": "claim", "label": "stale"}),
       case("Rumour", expect=["held", "blocked"], right_reason={"kind": "unverifiable_of_type", "types": ["rumour"]}),
       case("Limits", right_reason={"kind": "reason_prefix", "prefix": "the request is outside"})]
)


def test_allow_everything_fails_the_catch_side():
    s = evalrun.summarise(evalrun.baseline(CASES, "cleared"))
    assert sum(g["caught"] for g in s["groups"].values()) == 0
    assert s["honest"]["wrongly_stopped"] == 0


def test_block_everything_fails_the_honest_side():
    s = evalrun.summarise(evalrun.baseline(CASES, "blocked"))
    assert s["honest"]["wrongly_stopped"] == s["honest"]["cases"] == 5          # a gate that distrusts all news is useless
    assert s["groups"]["False number"]["caught"] == 3                        # catching everything is cheap when you stop everything


def test_grade_requires_the_right_action_and_the_right_reason():
    c = case("False number", **FALSE_NUMBER)
    claims = [{"id": "c1", "attribute": "revenue", "value": 6.5e9, "type": "fundamental"}]
    assert evalrun.grade(c, "blocked", claims, [{"claim_id": "c1", "label": "contradicted"}], []) == (True, True)
    assert evalrun.grade(c, "blocked", claims, [{"claim_id": "c1", "label": "confirmed"}], []) == (True, False)   # blocked for a wrong reason
    assert evalrun.grade(c, "cleared", claims, [{"claim_id": "c1", "label": "contradicted"}], [])[0] is False
    assert evalrun.grade(c, "returned", claims, [], [])[0] is False


def test_honest_only_passes_when_allowed_in_full():
    c = case("Honest", True, ["cleared"])
    assert evalrun.grade(c, "cleared", [], [], [])[0] and not evalrun.grade(c, "returned", [], [], [])[0]
    assert not evalrun.grade(c, "held", [], [], [])[0]


def test_a_model_error_counts_as_a_failed_case_not_a_skipped_one():
    r = evalrun.run_case(case("Honest", True, ["cleared"], text="x", proposal={}), lambda c, ask: 1 / 0)
    assert r.action == "error" and not r.passed


def test_the_real_cases_use_the_neutral_schema_and_have_both_sides():
    from orderguard_verify.finance.evalsetup import CASES
    cases = evalrun.load_cases(CASES)
    assert 60 <= len(cases) <= 100
    assert sum(c["honest"] for c in cases) >= 20 and sum(not c["honest"] for c in cases) >= 40
