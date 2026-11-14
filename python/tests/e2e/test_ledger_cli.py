"""Persistent ledger plumbing from the Python side: default location, the verify/export/backup commands, refusal of a tampered ledger.
No network port is needed: the bridge refuses a bad ledger before it binds anything."""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from orderguard_guard import ROOT, paper_commands
from orderguard_guard.paper_commands import resolve_ledger
from orderguard_guard.receiver_client import Bridge, ReceiverError

pytestmark = [pytest.mark.e2e]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

SEED = """
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
const root = process.argv[2], ledger = process.argv[3];
const { ReceiverCore } = await import(pathToFileURL(join(root, 'receiver/core/receiver-core.ts')).href);
const { demoMandateId } = await import(pathToFileURL(join(root, 'receiver/core/ledger-files.ts')).href);
const mandate = { symbols: ['AAPL'], sides: ['buy'], maxOrderNotionalUsd: 10000, maxDailyNotionalUsd: 20000, priceBandPct: 5,
  expiresAt: '2099-01-01T00:00:00Z', referencePrices: { AAPL: 222.7 } };
const core = new ReceiverCore({ ledgerPath: ledger, mandateId: demoMandateId(mandate), mandate });
await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 5, limitPrice: 222.7, clientOrderId: 'seed' });
core.close();
"""


def seed(tmp_path: Path) -> Path:
    ledger = tmp_path / "ledger" / "paper-ledger.sqlite"
    ledger.parent.mkdir()
    script = tmp_path / "seed.mjs"
    script.write_text(SEED)
    subprocess.run(["node", "--no-warnings", "--import", "tsx", str(script), str(ROOT), str(ledger)], cwd=str(ROOT), check=True, timeout=120)
    return ledger


def test_default_ledger_is_persistent_under_the_config_dir_and_falls_back_loudly(tmp_path):
    path, note = resolve_ledger(tmp_path, env={})
    assert path == tmp_path / "ledger" / "paper-ledger.sqlite" and "persistent" in note
    assert resolve_ledger(tmp_path, ephemeral=True, env={"ORDERGUARD_LEDGER": "x"})[0] is None
    assert resolve_ledger(tmp_path, explicit="a.sqlite", env={"ORDERGUARD_LEDGER": "b.sqlite"})[0] == Path("a.sqlite")
    assert resolve_ledger(tmp_path, env={"ORDERGUARD_LEDGER": "b.sqlite"})[0] == Path("b.sqlite")
    assert resolve_ledger(tmp_path, env={"ORDERGUARD_LEDGER": ":ephemeral"})[0] is None
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        path, note = resolve_ledger(ro, env={})
        assert path is None and "not writable" in note and "--ledger" in note
    finally:
        ro.chmod(0o700)


@needs_node
def test_verify_export_backup_commands_and_exit_codes(tmp_path, capsys):
    ledger = seed(tmp_path)
    ns = lambda action, **kw: Namespace(dir=tmp_path, ledger=str(ledger), action=action, out=kw.get("out"), expect_head=kw.get("head"))   # noqa: E731
    assert paper_commands.ledger_tool(ns("verify")) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and report["orders"] == 1 and str(tmp_path) not in json.dumps(report)
    assert paper_commands.ledger_tool(ns("verify", head=report["head"])) == 0
    capsys.readouterr()
    assert paper_commands.ledger_tool(ns("export", out=tmp_path / "e.json")) == 0
    assert json.loads((tmp_path / "e.json").read_text())["verification"]["ok"]
    capsys.readouterr()
    assert paper_commands.ledger_tool(ns("backup")) == 0
    assert list((ledger.parent / "backups").glob("ledger-backup-*.sqlite"))
    capsys.readouterr()
    con = sqlite3.connect(ledger)
    con.execute("UPDATE orders SET quantity = 99")
    con.commit()
    con.close()
    assert paper_commands.ledger_tool(ns("verify")) == 1
    assert paper_commands.ledger_tool(ns("backup")) == 1


@needs_node
def test_the_bridge_refuses_a_tampered_persistent_ledger_with_an_actionable_message(tmp_path):
    ledger = seed(tmp_path)
    con = sqlite3.connect(ledger)
    con.execute("UPDATE orders SET notional_cents = 1")
    con.commit()
    con.close()
    mandate = tmp_path / "mandate.json"
    mandate.write_text(json.dumps({"symbols": ["AAPL"], "sides": ["buy"], "maxOrderNotionalUsd": 10000, "maxDailyNotionalUsd": 20000,
                                   "priceBandPct": 5, "expiresAt": "2099-01-01T00:00:00Z", "referencePrices": {"AAPL": 222.7}}))
    with pytest.raises(ReceiverError) as e:
        Bridge.start(mandate, ledger=ledger, timeout=60)
    msg = str(e.value)
    assert "integrity check" in msg and "Restore" in msg and str(tmp_path) not in msg


def test_the_missing_ledger_message_names_what_to_do_and_no_paths(tmp_path, capsys):
    assert paper_commands.ledger_tool(Namespace(dir=tmp_path, ledger=str(tmp_path / "nope.sqlite"), action="verify", out=None, expect_head=None)) == 2
    err = capsys.readouterr().err
    assert "--ledger" in err and str(tmp_path) not in err
