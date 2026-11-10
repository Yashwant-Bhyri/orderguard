"""The grader must not share code with the checker, and it must be able to fail."""
import ast
import sys
from pathlib import Path

from orderguard_verify.grader import canary, score

GRADER = Path(__file__).resolve().parents[1] / "orderguard_verify" / "grader"


def test_the_grader_imports_only_the_standard_library():
    for f in GRADER.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else []
            assert all(n in sys.stdlib_module_names for n in names), f"{f.name} imports {names}"
            if isinstance(node, ast.ImportFrom) and node.level > 1:
                raise AssertionError(f"{f.name} reaches outside the grader package")


def test_the_grader_passes_its_canaries():
    assert canary.failures() == []


def test_an_inverted_grader_fails_the_canaries():
    def inverted(labels, records):
        flipped = [{**r, "claims": [{**c, "verdict": {"wrong": "ok", "ok": "wrong"}.get(c["verdict"], c["verdict"])} for c in r["claims"]]} for r in records]
        return score.score(labels, flipped)
    assert canary.failures(inverted) != []


def test_a_grader_that_counts_unextracted_claims_as_caught_fails_the_canaries():
    def generous(labels, records):
        s = score.score(labels, records)
        s["caught"] = s["false_claims"]
        return s
    assert canary.failures(generous) != []


def test_a_sentence_holding_two_figures_is_flagged_for_both_but_names_neither():
    """One false figure and one true figure in a single quoted sentence, marked wrong as a whole (what a judge model often does)."""
    labels = [{"memo_id": "m", "quote": "revenue of $100 billion", "figure": "$100 billion", "verdict": "false", "borderline": False, "error_class": "wrong_figure"},
              {"memo_id": "m", "quote": "up 5% on the year", "figure": "5%", "verdict": "true", "borderline": False}]
    rec = [{"memo_id": "m", "arm": "x", "action": "block", "claims": [{"quote": "revenue of $100 billion, up 5% on the year", "verdict": "wrong"}]}]
    s = score.score(labels, rec)
    assert (s["flagged"], s["named"]) == (1, 0)
    assert s["caught"] == 0          # the strict one-to-one count gives the sentence to the true neighbour and loses the false figure: the asymmetry
    assert (s["true_flagged"], s["true_flagged_clean"]) == (1, 0)          # the true 5% was flagged only because its neighbour is false
    one_each = [{"memo_id": "m", "arm": "x", "action": "block", "claims": [{"quote": "revenue of $100 billion", "verdict": "wrong"}, {"quote": "up 5% on the year", "verdict": "ok"}]}]
    s = score.score(labels, one_each)
    assert (s["flagged"], s["named"], s["true_flagged"]) == (1, 1, 0)
