import json

from orderguard_guard import DATA, cli, llm, receiver_client


def test_sign_then_verify(tmp_path, capsys):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"symbols": ["AAPL"], "sides": ["buy"], "maxOrderNotionalUsd": 100, "maxDailyNotionalUsd": 200, "priceBandPct": 5,
                             "expiresAt": "2099-01-01T00:00:00Z", "referencePrices": {"AAPL": 222.7}}))
    key, out = tmp_path / "k", tmp_path / "s.json"
    assert cli.main(["sign-mandate", str(m), "--key", str(key), "--out", str(out)]) == 0
    assert cli.main(["verify-mandate", str(out), "--key", str(key)]) == 0
    signed = json.loads(out.read_text())
    signed["maxOrderNotionalUsd"] = 10 ** 6
    out.write_text(json.dumps(signed))
    assert cli.main(["verify-mandate", str(out), "--key", str(key)]) == 1
    assert "INVALID" in capsys.readouterr().out


def test_check_order_exit_codes(tmp_path, capsys):
    o = tmp_path / "o.json"
    o.write_text(json.dumps({"ticker": "AAPL", "side": "buy", "quantity": 40, "limit_price": 222.7}))
    assert cli.main(["check-order", str(o)]) == 0
    o.write_text(json.dumps({"ticker": "AAPL", "side": "buy", "quantity": 440, "limit_price": 22.3}))
    assert cli.main(["check-order", str(o)]) == 1
    assert "refuse" in capsys.readouterr().out


def test_graph_demo_runs(capsys):
    assert cli.main(["graph-demo"]) == 0
    out = capsys.readouterr().out
    assert "guarded:                   nothing fires" in out and "R1 sell $30,000" in out


def test_scripted_demo_runs_offline_and_every_layer_acts(capsys):
    assert cli.main(["demo", "--scripted"]) == 0
    out = capsys.readouterr().out
    assert "layers that acted: allowed through L5/L6" in out
    assert "L5 refused" in out and "L6 figure check: contradicted" in out
    assert "L2 quarantined (instruction)" in out and "transfer_funds offered: False" in out and "transfer_funds offered: True" not in out
    assert "Ledger snapshot" in out


def test_demo_exits_unsuccessfully_when_recordings_are_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OG_LLM", "replay")
    monkeypatch.setattr(llm, "REPLAY_DIR", tmp_path)
    monkeypatch.setattr(receiver_client, "bridge_available", lambda: (False, "test uses the local ledger"))
    assert cli.main(["demo"]) == 1
    out = capsys.readouterr().out
    assert "ReplayMiss" in out and "Demo incomplete" in out
    assert "Ledger snapshot" in out


def test_demo_replays_the_bundled_deepseek_cases_and_checks_paper_effects(monkeypatch, capsys):
    monkeypatch.setenv("OG_LLM", "replay")
    monkeypatch.setattr(llm, "REPLAY_DIR", DATA / "replay")
    monkeypatch.setattr(receiver_client, "bridge_available", lambda: (False, "test uses local ledgers"))
    ledgers = []
    make_ledger = receiver_client.LocalLedger

    def ledger():
        result = make_ledger()
        ledgers.append(result)
        return result

    monkeypatch.setattr(receiver_client, "LocalLedger", ledger)
    assert cli.main(["demo", "--model", "deepseek/deepseek-v4.1-flash-1017"]) == 0
    assert [len(item.orders) for item in ledgers] == [1, 0, 1, 1]
    out = capsys.readouterr().out
    assert "L5 refused" in out and "L6 figure check: contradicted" in out
    assert "L2 quarantined (instruction)" in out and "ReplayMiss" not in out


# ---- failure paths: one line and a hint, never a traceback ------------------------------------------------------------

def _run_cli(argv, capsys):
    rc = cli.main(argv)
    out = capsys.readouterr()
    return rc, out.out + out.err


def test_bad_inputs_are_one_line_errors_with_exit_2(tmp_path, capsys):
    bad, arr = tmp_path / "bad.json", tmp_path / "arr.json"
    bad.write_text('{"ticker": "AAPL"')
    arr.write_text("[]")
    ok = tmp_path / "ok.json"
    ok.write_text('{"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 222.7}')
    cases = [(["check-order", str(tmp_path / "missing.json")], "not found"), (["check-order", str(bad)], "not valid JSON"),
             (["check-order", str(arr)], "must hold a JSON object"), (["check-order", str(ok), "--prices", "{bad"], "--prices"),
             (["check-order", str(ok), "--prices", '{"AAPL": -1}'], "positive"), (["verify-mandate", str(tmp_path / "nope")], "not found"),
             (["sign-mandate", str(tmp_path / "nope"), "--key", str(tmp_path / "k")], "not found")]
    for argv, text in cases:
        rc, out = _run_cli(argv, capsys)
        assert rc == 2 and text in out and "Traceback" not in out, (argv, out)
        assert out.count("orderguard: error:") == 1


def test_bad_date_option_is_an_argparse_error(tmp_path, capsys):
    import pytest
    with pytest.raises(SystemExit) as e:
        cli.main(["check-order", str(tmp_path / "x.json"), "--as-of", "nope"])
    assert e.value.code == 2 and "YYYY-MM-DD" in capsys.readouterr().err


def test_every_subcommand_has_help(capsys):
    import pytest
    for cmd in ("demo", "check-order", "graph-demo", "sign-mandate", "verify-mandate", "serve", "init", "doctor"):
        with pytest.raises(SystemExit) as e:
            cli.main([cmd, "--help"])
        assert e.value.code == 0
        assert "usage: orderguard" in capsys.readouterr().out
