"""The messages a first-time user meets (no mandate, altered mandate, no key, no recording) say what to do next."""
import json

import pytest

from orderguard_guard import cli, init_cmd, llm

ORDER = {"ticker": "AAPL", "side": "buy", "quantity": 3, "limit_price": 200}


def _order(tmp_path):
    p = tmp_path / "o.json"
    p.write_text(json.dumps(ORDER))
    return str(p)


def test_check_order_without_a_mandate_says_it_used_the_demo_one(tmp_path, capsys):
    assert cli.main(["check-order", _order(tmp_path)]) in (0, 1, 2)
    err = capsys.readouterr().err
    assert "no --mandate given" in err and "demo mandate" in err and "orderguard init" in err


def test_check_order_verifies_the_signature_when_signing_pub_sits_next_to_the_mandate(tmp_path, capsys):
    home = tmp_path / "home"
    init_cmd.init(home, "deepseek")
    assert cli.main(["check-order", _order(tmp_path), "--mandate", str(home / "mandate.json"), "--prices", '{"AAPL": 200}']) == 2   # a $600 order: hold
    assert "NOT checked" not in capsys.readouterr().err
    tampered = json.loads((home / "mandate.json").read_text())
    tampered["maxOrderNotionalUsd"] = 1_000_000
    (home / "mandate.json").write_text(json.dumps(tampered))
    assert cli.main(["check-order", _order(tmp_path), "--mandate", str(home / "mandate.json")]) == 1
    assert "changed after the human signed" in capsys.readouterr().out


def test_check_order_says_when_the_signature_could_not_be_checked(tmp_path, capsys):
    home = tmp_path / "home"
    init_cmd.init(home, "deepseek")
    (home / "signing.pub").unlink()
    cli.main(["check-order", _order(tmp_path), "--mandate", str(home / "mandate.json")])
    err = capsys.readouterr().err
    assert "signature was NOT checked" in err and "--pub" in err
    assert cli.main(["check-order", _order(tmp_path), "--mandate", str(home / "mandate.json"), "--pub", str(home / "nope.pub")]) == 2
    assert "public key file not found" in capsys.readouterr().err


def test_missing_key_message_names_the_file_the_init_command_made(monkeypatch, tmp_path):
    monkeypatch.setenv("OG_LLM", "live")
    for v in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OG_ENV_FILE"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("OG_SPEND_FILE", str(tmp_path / "spend.jsonl"))
    with pytest.raises(llm.NoApiKey) as e:
        llm.LLM("deepseek/deepseek-v4.1-flash-1017").chat([{"role": "user", "content": "hi"}])
    msg = str(e.value)
    assert "no DEEPSEEK_API_KEY in the environment" in msg and "OG_ENV_FILE=var/orderguard/.env" in msg and "OG_LLM=replay" in msg


def test_replay_miss_points_at_the_own_agent_example(monkeypatch, tmp_path):
    monkeypatch.setenv("OG_LLM", "replay")
    monkeypatch.setattr(llm, "REPLAY_DIR", tmp_path)
    with pytest.raises(llm.ReplayMiss) as e:
        llm.LLM("deepseek/deepseek-v4.1-flash-1017").chat([{"role": "user", "content": "hi"}])
    msg = str(e.value)
    assert msg.startswith("OG_LLM=replay and no recorded response") and "examples/python/guarded_agent.py" in msg and "OG_LLM=record" in msg


def test_init_next_steps_do_not_promise_that_the_env_file_is_read_automatically(tmp_path, capsys):
    assert init_cmd.main(["--dir", str(tmp_path / "h")]) == 0
    out = capsys.readouterr().out
    assert f"OG_ENV_FILE={tmp_path / 'h' / '.env'}" in out and "reads the environment, not that file" in out
