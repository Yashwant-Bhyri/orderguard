import pytest


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("OG_LLM", "replay")
    yield
