"""A memo with one false revenue number is blocked with evidence, and unusable input gives a clear escalate, never a trace or a pass."""
from conftest import scripted

from orderguard_verify.core.card import text_card
from orderguard_verify.core.llm import LLMUnavailable
from orderguard_verify.core.pipeline import check
from orderguard_verify.finance.models import Memo

MEMO = ("ACME closed fiscal 2024 with revenue of $6.5 billion. EPS was $2.50. "
        "Sources say ACME is in talks to buy a rival. Analysts are bullish.")
CLAIMS = [
    {"text": "revenue of $6.5 billion", "type": "fundamental", "ticker": "ACME", "metric": "revenue", "period": "FY2024", "value": 6.5e9, "unit": "USD", "main_reason": True},
    {"text": "EPS was $2.50", "type": "fundamental", "ticker": "ACME", "metric": "eps_diluted", "period": "FY2024", "value": 2.5, "unit": "USD/share"},
    {"text": "Sources say ACME is in talks to buy a rival", "type": "rumour", "ticker": "ACME"},
    {"text": "Analysts are bullish", "type": "sentiment", "ticker": "ACME"},
]
CTX = Memo(ticker="ACME", as_of="2025-03-04")


def test_false_revenue_is_blocked_with_evidence(make_pack):
    r = check(MEMO, CTX, make_pack(), ask=scripted(CLAIMS))
    labels = {c.text[:12]: v.label for c, v in zip(r.claims, r.verdicts)}
    assert labels == {"revenue of $": "contradicted", "EPS was $2.5": "confirmed", "Sources say ": "unverifiable", "Analysts are": "unverifiable"}
    assert r.decision.action == "block" and r.decision.alert
    assert "CONTRADICTED" in text_card(r) and "https://example.test/filing" in text_card(r)
    assert r.coverage == "2 of 2 checkable claims could be checked"


def test_extractor_drops_claims_whose_quote_is_not_in_the_memo(make_pack):
    r = check(MEMO, CTX, make_pack(), ask=scripted(CLAIMS + [{"text": "ACME won a huge contract", "type": "fundamental", "ticker": "ACME"}]))
    assert len(r.claims) == 4 and r.dropped[0]["why"] == "quote not found in text"


def test_the_honest_twin_passes(make_pack):
    claims = [dict(CLAIMS[0], value=5.0e9, text="revenue of $5.0 billion"), CLAIMS[1]]
    assert check(MEMO.replace("$6.5 billion", "$5.0 billion"), CTX, make_pack(), ask=scripted(claims)).decision.action == "pass"


def test_a_rumour_is_always_key_even_when_the_model_says_it_is_not(make_pack):
    claims = [dict(CLAIMS[0], value=5.0e9, text="revenue of $5.0 billion"), dict(CLAIMS[2], key=False)]
    r = check("ACME had revenue of $5.0 billion. Sources say ACME is in talks to buy a rival.", CTX, make_pack(), ask=scripted(claims))
    assert r.claims[1].key and r.decision.action == "revise"


def test_a_memo_the_sources_cannot_cover_is_escalated_with_the_reason(make_pack):
    r = check("ZZZZ made $1 billion.", Memo(ticker="ZZZZ", as_of="2025-03-04"), make_pack(), ask=scripted([]))
    assert r.decision.action == "escalate" and "not in the truth store" in r.error


def test_model_failure_and_empty_text_escalate_instead_of_raising(make_pack):
    def down(system, user, **kw):
        raise LLMUnavailable("no OPENROUTER_API_KEY")
    r = check(MEMO, CTX, make_pack(), ask=down)
    assert r.decision.action == "escalate" and "model was unavailable" in r.error and "OPENROUTER_API_KEY" in r.error
    assert check("   ", CTX, make_pack(), ask=scripted([])).decision.action == "escalate"
    assert check("Just vibes.", CTX, make_pack(), ask=scripted([])).decision.action == "escalate"


def test_a_check_with_no_order_is_saved_and_returns_the_fix_list(make_gateway):
    reply = make_gateway(CLAIMS, db=":memory:").check(MEMO, {"ticker": "ACME", "as_of": "2025-03-04"})
    assert reply["action"] == "block" and reply["status"] == "checked" and reply["fix"] == [{"claim": "revenue of $6.5 billion"}]


def test_an_old_decision_log_is_set_aside_not_crashed_on(tmp_path):
    import sqlite3
    from orderguard_verify.core.runs import RunStore
    db = tmp_path / "old.db"
    sqlite3.connect(db).executescript("CREATE TABLE runs (run_id TEXT, outcome TEXT); INSERT INTO runs VALUES ('x', 'old');")
    RunStore(db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT run_id FROM runs_legacy").fetchall() == [("x",)] and con.execute("SELECT count(*) FROM runs").fetchone() == (0,)


def test_a_figure_from_after_the_decision_date_is_revised_not_passed(make_pack):
    """The north-star failure: a memo dated before a filing quotes that filing. ACME's FY2024 results were filed 2025-02-14."""
    claims = [{"text": "fiscal 2024 revenue was $5.0 billion", "type": "fundamental", "ticker": "ACME", "metric": "revenue", "period": "FY2024", "value": 5.0e9, "unit": "USD"},
              {"text": "fiscal 2023 revenue was $4.2 billion", "type": "fundamental", "ticker": "ACME", "metric": "revenue", "period": "FY2023", "value": 4.2e9, "unit": "USD"}]
    memo = "ACME: fiscal 2024 revenue was $5.0 billion and fiscal 2023 revenue was $4.2 billion."
    r = check(memo, Memo(ticker="ACME", as_of="2024-12-01"), make_pack(), ask=scripted(claims))
    assert r.decision.action == "revise" and r.decision.fix == ["c1"]
    assert "not public on the decision date" in r.decision.reasons[0] and "2025-02-14" in r.decision.reasons[0]
    # the same memo dated after the filing passes: only the date made the difference
    assert check(memo, Memo(ticker="ACME", as_of="2025-03-04"), make_pack(), ask=scripted(claims)).decision.action == "pass"
