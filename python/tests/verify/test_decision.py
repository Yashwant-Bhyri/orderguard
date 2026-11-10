"""The decision table is the part that must never be wrong, so every rule and its precedence is tested.
It is tested against a stub pack, which also shows the core needs nothing finance-specific."""
from orderguard_verify.core.decision import decide
from orderguard_verify.core.models import Claim, Verdict


class StubPack:
    hard_types = frozenset({"fact"})
    never_key_types = frozenset({"opinion"})
    unconfirmable_types = frozenset({"rumour"})


def claim(cid, type_="fact", key=True, main=False):
    return Claim(id=cid, type=type_, text=f"claim {cid}", subject="X", key=key, main_reason=main)


def run(pairs):
    claims = [c for c, _ in pairs]
    return decide(StubPack(), claims, [Verdict(claim_id=c.id, label=lab, reason="r") for c, lab in pairs])


def test_all_confirmed_passes():
    d = run([(claim("a"), "confirmed"), (claim("b"), "confirmed")])
    assert (d.action, d.alert, d.fix) == ("pass", False, [])


def test_key_contradicted_blocks_alerts_and_names_the_claim():
    d = run([(claim("a"), "confirmed"), (claim("b"), "contradicted")])
    assert (d.action, d.alert, d.fix) == ("block", True, ["b"])


def test_contradiction_beats_stale_and_unverifiable():
    d = run([(claim("a"), "contradicted"), (claim("b"), "stale"), (claim("c", "rumour", main=True), "unverifiable")])
    assert d.action == "block"


def test_stale_key_means_revise_with_a_refresh_request():
    d = run([(claim("a"), "confirmed"), (claim("b"), "stale")])
    assert (d.action, d.fix, d.refresh) == ("revise", ["b"], ["X"])


def test_unverifiable_main_reason_escalates():
    assert run([(claim("a", main=True), "unverifiable"), (claim("b"), "confirmed")]).action == "escalate"


def test_a_rumour_inside_a_verified_memo_means_revise():
    d = run([(claim("a"), "confirmed"), (claim("b", "rumour"), "unverifiable")])
    assert (d.action, d.fix) == ("revise", ["b"])


def test_a_figure_nobody_can_check_does_not_stop_a_memo_that_has_a_verified_fact():
    assert run([(claim("a"), "confirmed"), (claim("b"), "unverifiable")]).action == "pass"


def test_opinion_or_rumour_alone_escalates():
    assert run([(claim("a", "opinion", main=True), "unverifiable")]).action == "escalate"
    assert run([(claim("a", "rumour", key=False), "unverifiable")]).action == "escalate"


def test_nothing_extracted_escalates():
    assert run([]).action == "escalate"


def test_opinion_is_never_a_key_claim_even_if_marked_so():
    assert run([(claim("a"), "confirmed"), (claim("b", "opinion", key=True), "unverifiable")]).action == "pass"


def test_contradicted_side_claim_means_revise_not_block():
    d = run([(claim("a"), "confirmed"), (claim("b", key=False), "contradicted")])
    assert (d.action, d.fix) == ("revise", ["b"])
