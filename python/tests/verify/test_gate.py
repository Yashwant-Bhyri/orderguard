"""`og gate` must pass on the committed code and fail when the checker is broken."""
from orderguard_verify import gate
from orderguard_verify.finance import verifier


def test_the_gate_passes_on_the_committed_baseline(monkeypatch):
    monkeypatch.setenv("OG_LLM", "replay")
    assert gate.main() == 0


def test_a_broken_checker_fails_the_gate(monkeypatch, capsys):
    monkeypatch.setenv("OG_LLM", "replay")
    monkeypatch.setattr(verifier, "close", lambda *a, **k: True)          # every figure now "matches" its filing
    assert gate.main() == 1
    assert "fell from" in capsys.readouterr().out


def test_a_checker_that_flags_everything_fails_the_gate(monkeypatch, capsys):
    monkeypatch.setenv("OG_LLM", "replay")
    monkeypatch.setattr(verifier, "close", lambda *a, **k: False)         # no figure ever matches
    assert gate.main() == 1
    assert "rose from" in capsys.readouterr().out
