import os

os.environ["OG_LLM"] = "replay"           # tests never reach the network
import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OG_SPEND_FILE", str(tmp_path / "spend.jsonl"))
    monkeypatch.setenv("OG_LLM", "replay")
    monkeypatch.setenv("OG_LAB_L6", "verify")      # the recordings were made with the real L6 (local truth store; no network)
    monkeypatch.delenv("ORDERGUARD_APP_TOKEN", raising=False)
    monkeypatch.delenv("ORDERGUARD_RECEIVER_URL", raising=False)
    yield
