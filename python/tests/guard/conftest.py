import os

os.environ["OG_LLM"] = "replay"          # tests never reach the network
import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OG_SPEND_FILE", str(tmp_path / "spend.jsonl"))
    monkeypatch.setenv("OG_LLM", "replay")
    yield
