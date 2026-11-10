#!/usr/bin/env python3
"""Prove isolated CP2 mesh startup on ten fresh paper-ledger databases.

This is a local loopback startup check only. It does not call OpenD, Futu,
providers, or any order route.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


MESH_ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(__file__).resolve().parent / "config.json"
KEY_NAMES = ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "LIQUID_API_KEY", "TYPESAFE_API_KEY")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="og-w2-cp2-startup-"))
    env = dict(os.environ)
    for name in KEY_NAMES:
        env.pop(name, None)
    env.update({
        "ORDERGUARD_DISABLE_LOCAL_ENV": "1",
        "ORDERGUARD_FUTU_SIMULATE_ENABLED": "1",
        "ORDERGUARD_FUTU_CONFIG": str(CONFIG),
    })
    rows: list[dict[str, object]] = []
    try:
        for attempt in range(1, 11):
            ledger = scratch / f"ledger-{attempt}.sqlite"
            port = free_port()
            run_env = dict(
                env,
                ORDERGUARD_HOST="127.0.0.1",
                ORDERGUARD_PORT=str(port),
                ORDERGUARD_LEDGER_DB=str(ledger),
            )
            process = subprocess.Popen(
                [str(MESH_ROOT / "node_modules/.bin/tsx"), "server.ts"],
                cwd=MESH_ROOT,
                env=run_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            http_status: int | None = None
            live = False
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                            http_status = response.status
                            live = True
                            break
                    except urllib.error.HTTPError as error:
                        http_status = error.code
                        live = True
                        break
                    except (urllib.error.URLError, TimeoutError, OSError):
                        time.sleep(0.15)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
                if process.stderr:
                    process.stderr.close()

            integrity = "missing"
            orders: int | None = None
            if ledger.exists():
                with sqlite3.connect(ledger) as database:
                    integrity = str(database.execute("PRAGMA integrity_check").fetchone()[0])
                    tables = {row[0] for row in database.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )}
                    if "paper_orders" in tables:
                        orders = int(database.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0])
            rows.append({
                "attempt": attempt,
                "http": http_status,
                "server_was_live": live,
                "exit": process.returncode,
                "ledger_exists": ledger.exists(),
                "sqlite_integrity": integrity,
                "paper_orders": orders,
                "stderr_empty": not stderr,
            })

        passed = sum(
            row["http"] == 200 and row["server_was_live"] is True and row["exit"] == 0
            and row["ledger_exists"] is True and row["sqlite_integrity"] == "ok"
            and row["paper_orders"] == 0 and row["stderr_empty"] is True
            for row in rows
        )
        output = {
            "mode": "fresh_ledger_loopback_startup_only",
            "n": len(rows),
            "k": passed,
            "provider_key_names_absent": all(name not in env for name in KEY_NAMES),
            "opend_calls": 0,
            "futu_order_submissions": 0,
            "provider_calls": 0,
            "rows": rows,
        }
        print(json.dumps(output, separators=(",", ":")))
        return 0 if passed == 10 and output["provider_key_names_absent"] else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
