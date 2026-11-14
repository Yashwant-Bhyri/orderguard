import json
import os
import stat

import pytest

from orderguard_guard import init_cmd
from orderguard_guard.gate import Mandate, public_key_from_b64


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "ORDERGUARD_APP_TOKEN", "ORDERGUARD_RECEIVER_URL", "OG_PROVIDER", "ORDERGUARD_HOME"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OG_LLM", "live")


def test_init_creates_files_with_permissions(tmp_path):
    d = tmp_path / "cfg"
    assert init_cmd.main(["--dir", str(d), "--provider", "deepseek"]) == 0
    for n in ("signing.key", ".env"):
        assert stat.S_IMODE((d / n).stat().st_mode) == 0o600
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    env = (d / ".env").read_text()
    assert "DEEPSEEK_API_KEY=\n" in env and "OG_PROVIDER=deepseek" in env and "ORDERGUARD_APP_TOKEN=" in env


def test_signed_mandate_verifies_and_key_not_printed(tmp_path, capsys):
    d = tmp_path / "cfg"
    init_cmd.main(["--dir", str(d)])
    assert "OG_PROVIDER=deepseek" in (d / ".env").read_text()
    out = capsys.readouterr().out
    secret = (d / "signing.key").read_text().strip()
    assert secret not in out
    m = Mandate.load(d / "mandate.json")
    m.verify(public_key_from_b64((d / "signing.pub").read_text().strip()))
    assert m.maxOrderNotionalUsd <= m.maxDailyNotionalUsd


def test_refuses_overwrite_without_force(tmp_path, capsys):
    d = tmp_path / "cfg"
    init_cmd.main(["--dir", str(d)])
    before = (d / "signing.key").read_text()
    assert init_cmd.main(["--dir", str(d)]) == 1
    assert (d / "signing.key").read_text() == before
    assert init_cmd.main(["--dir", str(d), "--force"]) == 0
    assert (d / "signing.key").read_text() != before


def test_home_env_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDERGUARD_HOME", str(tmp_path / "h"))
    assert init_cmd.default_dir() == tmp_path / "h"


def test_doctor_reports_missing_key_without_leaking(tmp_path, monkeypatch):
    d = tmp_path / "cfg"
    init_cmd.init(d)
    monkeypatch.setenv("ORDERGUARD_APP_TOKEN", "tok-secret-value")
    probs = init_cmd.doctor(d)
    assert any("DEEPSEEK_API_KEY is not set" in p for p in probs)
    assert not any("tok-secret-value" in p for p in probs)
    secret = (d / "signing.key").read_text().strip()
    assert not any(secret in p for p in init_cmd.doctor(d))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    assert init_cmd.doctor(d) == []


def test_doctor_detects_tamper_expiry_loose_perms_and_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("ORDERGUARD_APP_TOKEN", "t")
    assert "does not exist" in init_cmd.doctor(tmp_path / "nope")[0]
    d = tmp_path / "cfg"
    init_cmd.init(d)
    m = json.loads((d / "mandate.json").read_text())
    m["maxOrderNotionalUsd"] = 10**9
    (d / "mandate.json").write_text(json.dumps(m))
    assert any("changed after the human signed" in p for p in init_cmd.doctor(d))
    init_cmd.main(["--dir", str(d), "--resign"])
    assert init_cmd.doctor(d) == []
    assert any("expired" in p for p in init_cmd.doctor(d, now="2099-01-01T00:00:00Z"))
    os.chmod(d / "signing.key", 0o644)
    assert any("readable by other users" in p for p in init_cmd.doctor(d))


def test_doctor_unreachable_receiver(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("ORDERGUARD_APP_TOKEN", "t")
    d = tmp_path / "cfg"
    init_cmd.init(d)
    monkeypatch.setenv("ORDERGUARD_RECEIVER_URL", "http://127.0.0.1:1")
    assert any("receiver" in p and "unreachable" in p for p in init_cmd.doctor(d))
    assert init_cmd.doctor(d, check_receiver=False) == []


def test_doctor_cli_treats_missing_optional_settings_as_notes(tmp_path, monkeypatch, capsys):
    from orderguard_guard.cli import main
    monkeypatch.setenv("OG_LLM", "live")
    for v in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "ORDERGUARD_APP_TOKEN", "ORDERGUARD_RECEIVER_URL", "OG_PROVIDER"):
        monkeypatch.delenv(v, raising=False)
    d = tmp_path / "cfg"
    init_cmd.init(d)
    assert main(["doctor", "--dir", str(d)]) == 0
    out = capsys.readouterr().out
    assert "note:" in out and "problem:" not in out and "ok:" in out
    assert main(["doctor", "--dir", str(d), "--strict"]) == 1
    (d / "signing.key").write_text("junk\n")
    assert main(["doctor", "--dir", str(d)]) == 1 and "problem:" in capsys.readouterr().out


def test_resign_errors_say_what_to_do(tmp_path, capsys):
    from orderguard_guard.cli import main
    assert main(["init", "--resign", "--dir", str(tmp_path / "none")]) == 1
    assert "run `orderguard init` first" in capsys.readouterr().out
    d = tmp_path / "cfg"
    init_cmd.init(d)
    (d / "mandate.json").write_text("{broken")
    assert main(["init", "--resign", "--dir", str(d)]) == 1
    assert "not valid JSON" in capsys.readouterr().out
