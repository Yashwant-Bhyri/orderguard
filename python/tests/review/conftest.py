import os

os.environ["OG_LLM"] = "replay"           # a recorded answer or none; the review tests never reach the network
import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OG_SPEND_FILE", str(tmp_path / "spend.jsonl"))
    monkeypatch.setenv("OG_LLM", "replay")
    for v in ("OPENROUTER_API_KEY", "OG_ENV_FILE", "OG_REVIEW_MODEL"):
        monkeypatch.delenv(v, raising=False)
    yield
