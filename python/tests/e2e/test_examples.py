"""The integrator examples run as shipped, offline, and show a refusal with its reason: Python agent, HTTP script, MCP stdio client.

Each example prints the output it documents in its own header, so these tests also fail when a header goes stale.
The HTTP script needs a loopback port and skips where binding one is not allowed (a sandbox); the others need none.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from orderguard_guard import ROOT

pytestmark = [pytest.mark.e2e]


def _loopback_ok() -> bool:
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False


needs_loopback = pytest.mark.skipif(not _loopback_ok(), reason="binding a loopback port is not allowed here")
needs_curl = pytest.mark.skipif(shutil.which("curl") is None or shutil.which("sh") is None, reason="curl or sh is not installed")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

REASON = "The order is worth $97,988 at the trusted price of $222.70 (440 shares), above the per-order cap of $10,000."


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in ("ORDERGUARD_HOME", "ORDERGUARD_APP_TOKEN", "ORDERGUARD_APP_URL", "ORDERGUARD_RECEIVER_URL")}
    return {**env, "OG_LLM": "replay", **extra}


def _run(args, **kw):
    return subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=120, env=kw.pop("env", _env()), **kw)


def _header_lines(path: str) -> set[str]:
    """Every line of the file's own header (docstring or leading comments), stripped, so printed output can be matched against it."""
    text = (ROOT / path).read_text()
    return {re.sub(r"^#\s?", "", line).strip() for line in text.splitlines()}


def _assert_documented(stdout: str, path: str, skip=lambda line: False):
    documented = _header_lines(path)
    missing = [line for line in stdout.splitlines() if line.strip() and not skip(line) and line.strip() not in documented]
    assert not missing, f"{path} prints lines its header does not show (update the header): {missing}"


def test_python_guarded_agent_refuses_the_forged_split_with_a_reason():
    out = _run([sys.executable, "examples/python/guarded_agent.py"])
    assert out.returncode == 0, out.stderr
    assert "REFUSE" in out.stdout and REASON in out.stdout
    assert "ALLOW   -> filled on the paper ledger as P-00001" in out.stdout and "HOLD" in out.stdout
    assert "The refused and held orders never reached the broker." in out.stdout
    _assert_documented(out.stdout, "examples/python/guarded_agent.py")


def test_python_example_explains_a_missing_or_altered_mandate(tmp_path):
    out = _run([sys.executable, "examples/python/guarded_agent.py", "--mandate", str(tmp_path / "mandate.json")])
    assert out.returncode == 1 and "No mandate at" in out.stderr and "orderguard init" in out.stderr
    from orderguard_guard import init_cmd
    home = tmp_path / "home"
    init_cmd.init(home, "deepseek")
    pub_missing = tmp_path / "lonely.json"
    shutil.copy(home / "mandate.json", pub_missing)
    out = _run([sys.executable, "examples/python/guarded_agent.py", "--mandate", str(pub_missing)])
    assert out.returncode == 1 and "No owner public key" in out.stderr and "--pub" in out.stderr
    tampered = json.loads((home / "mandate.json").read_text())
    tampered["maxOrderNotionalUsd"] = 9_999_999
    (home / "mandate.json").write_text(json.dumps(tampered))
    out = _run([sys.executable, "examples/python/guarded_agent.py", "--mandate", str(home / "mandate.json")])
    assert out.returncode == 1 and "changed after the human signed" in out.stderr and "orderguard init --resign" in out.stderr


def test_the_example_with_a_real_init_mandate_still_refuses(tmp_path):
    from orderguard_guard import init_cmd
    init_cmd.init(tmp_path / "home", "deepseek")
    out = _run([sys.executable, "examples/python/guarded_agent.py", "--mandate", str(tmp_path / "home" / "mandate.json")])
    assert out.returncode == 0, out.stderr
    assert "REFUSE" in out.stdout and "per-order cap of $1,000" in out.stdout


def test_mcp_stdio_client_starts_the_server_lists_tools_and_gets_a_refusal():
    out = _run([sys.executable, "examples/mcp/list_tools.py"])
    assert out.returncode == 0, out.stderr
    assert "server: orderguard" in out.stdout and "check_order" in out.stdout and "tools (10)" in out.stdout
    assert "check_order buy 440 AAPL @ 22.30 -> REFUSE" in out.stdout and REASON in out.stdout
    _assert_documented(out.stdout, "examples/mcp/list_tools.py")


def test_mcp_client_warns_when_the_config_directory_has_no_mandate(tmp_path):
    out = _run([sys.executable, "examples/mcp/list_tools.py", "--home", str(tmp_path / "typo")])
    assert out.returncode == 1
    assert "ORDERGUARD_HOME is set, but that directory has no mandate.json" in out.stdout and str(tmp_path) not in out.stdout


def test_server_list_tools_flag_is_a_one_command_smoke_test():
    out = _run([sys.executable, "-m", "orderguard_mcp", "--list-tools"])
    assert out.returncode == 0, out.stderr
    assert "check_order" in out.stdout and "submit_order" in out.stdout and "10 tools" in out.stdout


def test_print_config_gives_a_working_command_and_the_claude_code_line(tmp_path):
    out = _run([sys.executable, "-m", "orderguard_mcp", "--print-config"], env=_env(ORDERGUARD_HOME=str(tmp_path)))
    cfg = json.loads(out.stdout)["mcpServers"]["orderguard"]
    assert cfg["command"] == sys.executable and cfg["args"] == ["-m", "orderguard_mcp"] and cfg["env"]["ORDERGUARD_HOME"] == str(tmp_path)
    assert out.stderr.startswith("# Claude Code: claude mcp add --env ORDERGUARD_HOME=")
    bare = _run([sys.executable, "-m", "orderguard_mcp", "--print-config"])
    assert "env" not in json.loads(bare.stdout)["mcpServers"]["orderguard"] and "ORDERGUARD_HOME" in bare.stderr


def test_the_shipped_mcp_config_matches_what_the_server_expects():
    cfg = json.loads((ROOT / "examples/mcp/claude_desktop_config.json").read_text())["mcpServers"]["orderguard"]
    assert cfg["args"] == ["-m", "orderguard_mcp"] and cfg["command"].endswith("/.venv/bin/python")
    assert (ROOT / "python" / "orderguard_mcp" / "__main__.py").is_file()


# ---- the HTTP example against a real `orderguard serve`-style server ------------------------------------------------------

def _serve(token: str | None):
    import uvicorn
    from orderguard_app.app import create_app
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(token=token), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            return server, thread, f"http://127.0.0.1:{port}"
        time.sleep(0.05)
    raise RuntimeError("the test server did not start")


@pytest.fixture()
def http_server():
    server, thread, url = _serve(None)
    yield url
    server.should_exit = True
    thread.join(5)


@pytest.fixture()
def token_server():
    server, thread, url = _serve("test-token-not-a-secret")
    yield url
    server.should_exit = True
    thread.join(5)


@needs_loopback
@needs_curl
def test_http_example_allows_refuses_and_holds(http_server):
    out = _run(["sh", "examples/http/check_order.sh", http_server])
    assert out.returncode == 0, out.stdout + out.stderr
    lines = out.stdout.splitlines()
    assert lines[0].startswith("allow ") and "refuse " in out.stdout and "hold " in out.stdout
    assert REASON in out.stdout and "OK: the three orders were allowed, refused and held as expected." in out.stdout
    _assert_documented(out.stdout, "examples/http/check_order.sh")


@needs_loopback
@needs_curl
def test_http_example_awk_fallback_matches_the_jq_path(http_server, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("sh", "sed", "awk", "curl", "printf", "tail", "cat", "env"):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    out = _run(["/bin/sh", "examples/http/check_order.sh", http_server], env=_env(PATH=str(bin_dir)))
    assert out.returncode == 0, out.stdout + out.stderr
    assert REASON in out.stdout


@needs_loopback
@needs_curl
def test_http_example_explains_a_missing_token_and_sends_a_right_one(token_server):
    out = _run(["sh", "examples/http/check_order.sh", token_server])
    assert out.returncode == 2 and "Export ORDERGUARD_APP_TOKEN" in out.stderr
    out = _run(["sh", "examples/http/check_order.sh", token_server], env=_env(ORDERGUARD_APP_TOKEN="test-token-not-a-secret"))
    assert out.returncode == 0 and REASON in out.stdout


@needs_curl
def test_http_example_explains_a_server_that_is_not_running():
    out = _run(["sh", "examples/http/check_order.sh", "http://127.0.0.1:9"])
    assert out.returncode == 2
    assert "could not reach http://127.0.0.1:9" in out.stderr and "orderguard serve" in out.stderr


@needs_node
def test_node_receiver_bridge_names_the_missing_mandate_flag():
    out = _run(["node", "receiver/bridge/serve.mjs"])
    assert out.returncode == 1 and "--mandate FILE is required" in out.stderr and "orderguard init" in out.stderr
