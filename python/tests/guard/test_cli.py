import json

from orderguard_guard import cli


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
