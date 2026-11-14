"""First-run help in the MCP server: which mandate is in use, how to configure a client, and a quick check that it starts."""
import io
import json
import sys

from orderguard_mcp import core, server


def test_demo_label_says_so_when_orderguard_home_points_at_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("ORDERGUARD_HOME", str(tmp_path / "typo"))
    core.reset_state()
    r = core.check_order("AAPL", "buy", 10, 222.7)
    label = r["mandate"]["label"]
    assert "DEMO MANDATE" in label and "ORDERGUARD_HOME is set, but that directory has no mandate.json" in label
    assert str(tmp_path) not in json.dumps(r), "the config directory path must never be echoed"
    assert core.mandate_summary()["label"] == label


def test_demo_label_stays_short_when_nothing_is_configured(monkeypatch):
    monkeypatch.delenv("ORDERGUARD_HOME", raising=False)
    monkeypatch.chdir(core.init_cmd.Path(core.__file__).parent)         # a directory with no var/orderguard
    core.reset_state()
    assert core.demo_label() == core.DEMO_LABEL


def test_list_tools_starts_the_server_in_process_and_prints_every_tool(capsys):
    assert server.main(["--list-tools"]) == 0
    out = capsys.readouterr().out
    assert "check_order" in out and "submit_order" in out and "10 tools" in out


def test_print_config_includes_the_config_directory_and_a_claude_code_line(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("ORDERGUARD_HOME", str(tmp_path))
    assert server.main(["--print-config"]) == 0
    captured = capsys.readouterr()
    cfg = json.loads(captured.out)["mcpServers"]["orderguard"]
    assert cfg["command"] == sys.executable and cfg["env"] == {"ORDERGUARD_HOME": str(tmp_path)}
    assert f"claude mcp add --env ORDERGUARD_HOME={tmp_path} orderguard -- {sys.executable} -m orderguard_mcp" in captured.err


def test_started_by_hand_in_a_terminal_it_says_what_it_is_waiting_for(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(sys, "stdin", type("Tty", (io.StringIO,), {"isatty": lambda self: True})())
    monkeypatch.setattr(server, "build_server", lambda: type("S", (), {"run": lambda self, transport: ran.append(transport)})())
    assert server.main([]) == 0 and ran == ["stdio"]
    err = capsys.readouterr().err
    assert "started by an MCP client" in err and "--print-config" in err and "--list-tools" in err


def test_not_in_a_terminal_it_stays_silent_on_stderr(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(server, "build_server", lambda: type("S", (), {"run": lambda self, transport: None})())
    assert server.main([]) == 0
    assert capsys.readouterr().err == ""
