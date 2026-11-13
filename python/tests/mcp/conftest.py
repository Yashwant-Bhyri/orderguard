import os

os.environ["OG_LLM"] = "replay"           # a recorded or scripted model only; the MCP tests never reach the network
import pytest

from orderguard_mcp import core


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OG_SPEND_FILE", str(tmp_path / "spend.jsonl"))
    monkeypatch.setenv("OG_LLM", "replay")
    monkeypatch.setenv("ORDERGUARD_HOME", str(tmp_path / "no-config"))      # no mandate.json here: the labelled demo mandate
    for v in ("ORDERGUARD_RECEIVER_URL", "ORDERGUARD_REQUIRE_FIGURES", "ORDERGUARD_OFFLINE", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "OG_ENV_FILE"):
        monkeypatch.delenv(v, raising=False)
    core.reset_state()
    yield
    core.reset_state()


@pytest.fixture()
def configured(tmp_path, monkeypatch):
    """A real `orderguard init` directory: signed mandate (AAPL, $1,000 per order, reference price $200), returns its path."""
    from orderguard_guard import init_cmd
    d = tmp_path / "home"
    init_cmd.init(d, "deepseek")
    monkeypatch.setenv("ORDERGUARD_HOME", str(d))
    core.reset_state()
    return d
