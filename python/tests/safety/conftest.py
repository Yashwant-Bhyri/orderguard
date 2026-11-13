import pytest


@pytest.fixture(autouse=True)
def _offline(tmp_path, monkeypatch):
    monkeypatch.setenv("OG_LLM", "replay")
    monkeypatch.setenv("OG_LAB_L6", "facts")
    monkeypatch.setenv("OG_SPEND_FILE", str(tmp_path / "spend.jsonl"))
    monkeypatch.setenv("OG_TRUTH_DB", str(tmp_path / "truth.db"))      # a stray default store would be created here, never in data/
    yield
