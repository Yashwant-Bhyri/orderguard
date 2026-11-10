#!/usr/bin/env python3
"""Start a loopback mesh and run the model-driven Futu SIMULATE proof."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
MESH_ROOT = PACKAGE_DIR.parent
ENV_FILE = Path(os.environ.get(
    "ORDERGUARD_FUTU_ENV_FILE", str(PACKAGE_DIR / "provider-keys.local")
)).expanduser()
ROOM_SPEND = Path(os.environ.get(
    "ORDERGUARD_ROOM_SPEND_CSV", str(PACKAGE_DIR / "results" / "SPEND.csv")
)).expanduser()
KEYS = ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "LIQUID_API_KEY", "TYPESAFE_API_KEY")
MODEL = "gpt-6-luna"


def _load_keys(path: Path) -> dict[str, str]:
    """Read only the four required keys and return them for child-process env."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or key not in KEYS:
            continue
        raw_value = raw_value.strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
            try:
                decoded = ast.literal_eval(raw_value) if raw_value[0] == '"' else raw_value[1:-1]
            except (SyntaxError, ValueError):
                decoded = raw_value[1:-1]
            values[key] = str(decoded)
        else:
            values[key] = raw_value.split(" #", 1)[0].rstrip()
    missing = [key for key in KEYS if not values.get(key)]
    if missing:
        raise RuntimeError("required provider keys missing from env file: " + ",".join(missing))
    return values


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _has_futu_sdk(python: str) -> bool:
    try:
        result = subprocess.run(
            [python, "-c", "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('futu') else 1)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5, check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _select_python(configured: str) -> str:
    if configured:
        if _has_futu_sdk(configured):
            return configured
        raise RuntimeError("The selected Python has no futu-api SDK; install futu-adapter/requirements.txt in that environment.")
    candidates = [str(PACKAGE_DIR / ".venv" / "bin" / "python"), sys.executable]
    for candidate in candidates:
        if _has_futu_sdk(candidate):
            return candidate
    raise RuntimeError("No Python with the pinned futu-api SDK was found. Run: python3 -m venv futu-adapter/.venv && futu-adapter/.venv/bin/python -m pip install -r futu-adapter/requirements.txt")


def _wait_for_server(process: subprocess.Popen[bytes], base_url: str, timeout: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(base_url + "/", timeout=1.0):
                return True
        except urllib.error.HTTPError:
            return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)
    return False


def _read_inventory(python: str, env: dict[str, str]) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [python, str(PACKAGE_DIR / "cli.py"), "inventory"],
            cwd=str(MESH_ROOT), env=env, text=True, capture_output=True,
            timeout=45, check=False,
        )
        result = json.loads(completed.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {"ok": False, "state": "unknown", "code": "order_inventory_unavailable"}
    return result if isinstance(result, dict) and completed.returncode == 0 else {
        "ok": False, "state": "unknown", "code": "order_inventory_unavailable",
    }


def _read_mapping_health(python: str, env: dict[str, str]) -> dict[str, object]:
    """Read all configured HK routes; the CLI enforces quote age and lot shape."""
    try:
        config = json.loads((PACKAGE_DIR / "config.json").read_text(encoding="utf-8"))
        symbols = config.get("symbols") if isinstance(config, dict) else None
        if not isinstance(symbols, dict):
            return {"ok": False, "state": "unknown", "code": "symbol_map_invalid"}
        routes: dict[str, str] = {
            str(alias): str(route["code"])
            for alias, route in symbols.items()
            if isinstance(route, dict) and route.get("market") == "HK" and isinstance(route.get("code"), str)
        }
        completed = subprocess.run(
            [python, str(PACKAGE_DIR / "cli.py")],
            input='{"action":"quotes"}\n', cwd=str(MESH_ROOT), env=env,
            text=True, capture_output=True, timeout=45, check=False,
        )
        result = json.loads(completed.stdout.strip())
        quotes = result.get("quotes") if isinstance(result, dict) and isinstance(result.get("quotes"), list) else []
        by_code = {str(row.get("code")): row for row in quotes if isinstance(row, dict)}
        expected = set(routes.values())
        if completed.returncode != 0 or result.get("ok") is not True or result.get("trd_env") != "SIMULATE" or set(by_code) != expected:
            return {"ok": False, "state": "refused", "code": result.get("code", "mapped_quote_snapshot_incomplete")}
        if any(
            isinstance(row.get("lot_size"), bool) or not isinstance(row.get("lot_size"), int) or row["lot_size"] < 1
            or row.get("suspension") is True or not isinstance(row.get("update_time"), str)
            for row in by_code.values()
        ):
            return {"ok": False, "state": "refused", "code": "mapped_quote_lot_or_suspension_invalid"}
        return {
            "ok": True, "state": "ready", "trd_env": "SIMULATE",
            "endpoint": result.get("endpoint"),
            "routes": [{
                "mandate_symbol": alias, "futu_code": code,
                "lot_size": by_code[code]["lot_size"], "update_time": by_code[code]["update_time"],
            } for alias, code in sorted(routes.items())],
        }
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError, ValueError):
        return {"ok": False, "state": "unknown", "code": "mapped_quote_health_check_failed"}


def _inventory_digest(orders: list[dict[str, object]]) -> str:
    signature = sorted(
        f"{row.get('order_id', '')}|{row.get('remark', '')}"
        for row in orders
    )
    return hashlib.sha256("\n".join(signature).encode("utf-8")).hexdigest()


def _attach_inventory_evidence(output_path: Path, before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    if not output_path.is_file():
        return {
            "proof_state": "artifact_missing", "before_order_count": len(before.get("orders", [])) if isinstance(before.get("orders"), list) else None,
            "after_order_count": len(after.get("orders", [])) if isinstance(after.get("orders"), list) else None,
            "blocked_futu_submissions": None,
        }
    data = json.loads(output_path.read_text(encoding="utf-8"))
    before_orders = before.get("orders") if isinstance(before.get("orders"), list) else []
    after_orders = after.get("orders") if isinstance(after.get("orders"), list) else []
    before_rows = [row for row in before_orders if isinstance(row, dict)]
    after_rows = [row for row in after_orders if isinstance(row, dict)]
    before_ids = {str(row.get("order_id")) for row in before_rows}
    after_by_id = {str(row.get("order_id")): row for row in after_rows}
    new_rows = [row for row in after_rows if str(row.get("order_id")) not in before_ids]
    new_by_id = {str(row.get("order_id")): row for row in new_rows}
    if data.get("state") == "refused":
        no_order_delta = not new_rows
        evidence = {
            "proof_state": "pre_dispatch_refusal" if no_order_delta else "unexpected_inventory_delta",
            "before_order_count": len(before_rows),
            "after_order_count": len(after_rows),
            "new_order_ids": sorted(str(row.get("order_id")) for row in new_rows),
            "dispatches_n": 0,
            "blocked_futu_submissions": 0 if no_order_delta else None,
        }
        data["broker_order_inventory_delta"] = evidence
        data["blocked_futu_submissions"] = evidence["blocked_futu_submissions"]
        output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return evidence
    dispatch_log = data.get("adapter_dispatch_log") if isinstance(data.get("adapter_dispatch_log"), list) else []
    dispatch_entries = [
        row for row in dispatch_log
        if isinstance(row, dict) and row.get("dispatch_attempted") is True
    ]
    results = data.get("results") if isinstance(data.get("results"), list) else []
    approved_control_dispatches = [
        row for row in results if isinstance(row, dict)
        and row.get("class") == "approved" and row.get("dispatch_attempted") is True
    ]
    expected = {
        str(row.get("broker_order_id")): str(row.get("idempotency_remark"))
        for row in dispatch_entries if row.get("broker_order_id") and row.get("idempotency_remark")
    }
    dispatch_log_complete = (
        len(expected) == len(dispatch_entries)
        and all(row.get("adapter_state") == "accepted" for row in dispatch_entries)
    )
    expected_ids = set(expected)
    new_ids = set(new_by_id)
    missing_approved = sorted(expected_ids - new_ids)
    unexpected_new = sorted(new_ids - expected_ids)
    remark_match = all(
        str(new_by_id[order_id].get("remark") or "") == expected[order_id]
        for order_id in expected_ids & new_ids
    )
    blocked_dispatch_attempts = sum(
        1 for row in results if isinstance(row, dict)
        and row.get("dispatch_attempted") is True
        and isinstance(row.get("receiver"), dict)
        and row["receiver"].get("result") in {"receiver_denial", "second_lock_hold"}
    )
    unauthorized_dispatch_attempts = sum(
        1 for row in results if isinstance(row, dict)
        and row.get("dispatch_attempted") is True
        and (not isinstance(row.get("receiver"), dict)
             or row["receiver"].get("result") != "authorized_commit")
    )
    dispatch_authorization_complete = all(
        isinstance(row, dict) and isinstance(row.get("receiver"), dict)
        and row["receiver"].get("result") == "authorized_commit"
        for row in results if isinstance(row, dict) and row.get("dispatch_attempted") is True
    )
    inventory_matches = expected_ids == new_ids and remark_match and dispatch_log_complete
    proof_pass = (
        data.get("ok") is True and inventory_matches and blocked_dispatch_attempts == 0
        and unauthorized_dispatch_attempts == 0 and dispatch_authorization_complete
    )
    safe_new_rows = [{
        "order_id": str(row.get("order_id") or ""),
        "code": str(row.get("code") or ""),
        "trd_side": row.get("trd_side"),
        "qty": row.get("qty"),
        "price": row.get("price"),
        "order_type_raw": row.get("order_type_raw"),
        "order_status": row.get("order_status"),
    } for row in new_rows]
    evidence = {
        "proof_state": "matched" if proof_pass else "mismatch",
        "before_order_count": len(before_rows),
        "after_order_count": len(after_rows),
        "before_order_ids_and_remarks_sha256": _inventory_digest(before_rows),
        "after_order_ids_and_remarks_sha256": _inventory_digest(after_rows),
        "new_order_ids": sorted(new_ids),
        "dispatch_order_ids": sorted(expected_ids),
        "dispatches_n": len(dispatch_entries),
        "approved_control_order_ids": sorted(
            str(row.get("broker_order_id")) for row in approved_control_dispatches if row.get("broker_order_id")
        ),
        "approved_control_dispatches_n": len(approved_control_dispatches),
        "adapter_dispatch_log_complete": dispatch_log_complete,
        "missing_dispatch_order_ids": missing_approved,
        "unexpected_new_order_ids": unexpected_new,
        "new_order_rows": safe_new_rows,
        "new_order_remarks_match_adapter_log": remark_match,
        "blocked_proposal_dispatch_attempts": blocked_dispatch_attempts,
        "unauthorized_dispatch_attempts": unauthorized_dispatch_attempts,
        "dispatch_authorization_complete": dispatch_authorization_complete,
        "blocked_futu_submissions": 0 if proof_pass else None,
    }
    data["broker_order_inventory_delta"] = evidence
    data["blocked_futu_submissions"] = evidence["blocked_futu_submissions"]
    data["ok"] = data.get("ok") is True and proof_pass
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(ENV_FILE))
    parser.add_argument("--spend-csv", default=str(ROOM_SPEND))
    parser.add_argument("--output-dir", default=str(PACKAGE_DIR / "results"))
    parser.add_argument("--python", default=os.environ.get("ORDERGUARD_FUTU_PYTHON", ""),
                        help="Python interpreter with the pinned futu-api package installed")
    args = parser.parse_args()
    try:
        args.python = _select_python(args.python)
    except RuntimeError as error:
        parser.error(str(error))

    preflight_env = os.environ.copy()
    preflight_env.update({
        "ORDERGUARD_FUTU_SIMULATE_ENABLED": "1",
        "ORDERGUARD_FUTU_CONFIG": str(PACKAGE_DIR / "config.json"),
    })
    preflight = subprocess.run(
        [args.python, str(PACKAGE_DIR / "cli.py"), "preflight"],
        cwd=str(MESH_ROOT), env=preflight_env, text=True,
        capture_output=True, timeout=30, check=False,
    )
    print(preflight.stdout.strip() or '{"ok":false,"state":"unknown","code":"preflight_output_missing"}', flush=True)
    if preflight.returncode != 0:
        return preflight.returncode
    try:
        preflight_result = json.loads(preflight.stdout.strip())
    except json.JSONDecodeError:
        print('{"ok":false,"state":"refused","code":"preflight_response_invalid"}', flush=True)
        return 2
    if preflight_result.get("market_hk") not in {"MORNING", "AFTERNOON"}:
        print('{"ok":false,"state":"refused","code":"hk_market_not_open"}', flush=True)
        return 2

    mapping_health = _read_mapping_health(args.python, preflight_env)
    print(json.dumps({"state": "mapped_quote_health_check", **mapping_health}, separators=(",", ":")), flush=True)
    if mapping_health.get("ok") is not True:
        return 2

    inventory_before = _read_inventory(args.python, preflight_env)
    if inventory_before.get("ok") is not True:
        print('{"ok":false,"state":"refused","code":"order_inventory_unavailable"}', flush=True)
        return 2
    before_orders = inventory_before.get("orders") if isinstance(inventory_before.get("orders"), list) else []
    print(json.dumps({
        "state": "futu_order_inventory_before",
        "trd_env": "SIMULATE",
        "order_count": len(before_orders),
        "inventory_sha256": _inventory_digest([row for row in before_orders if isinstance(row, dict)]),
    }, separators=(",", ":")), flush=True)

    try:
        provider_keys = _load_keys(Path(args.env_file).expanduser())
    except (OSError, RuntimeError):
        print('{"ok":false,"state":"refused","code":"provider_env_unavailable"}')
        return 2

    run_id = "w2-futu-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_dir = Path(__file__).resolve().parents[2] / ".orderguard" / "futu-demo" / run_id
    ledger_dir.mkdir(parents=True, exist_ok=False)
    ledger = ledger_dir / "paper-ledger.sqlite"
    output = output_dir / (run_id + ".json")
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    server_env = os.environ.copy()
    server_env.update(provider_keys)
    # The TypeScript SIMULATE quote and dispatch bridges resolve `python3`
    # from PATH. Keep that child process on the same pinned futu-api interpreter
    # used by this runner's preflight and replay driver.
    python_bin_dir = str(Path(args.python).expanduser().resolve().parent)
    server_env["PATH"] = python_bin_dir + os.pathsep + server_env.get("PATH", "")
    server_env.update({
        "ORDERGUARD_HOST": "127.0.0.1",
        "ORDERGUARD_PORT": str(port),
        "ORDERGUARD_LEDGER_DB": str(ledger),
        "ORDERGUARD_FUTU_SIMULATE_ENABLED": "1",
        "ORDERGUARD_FUTU_CONFIG": str(PACKAGE_DIR / "config.json"),
        "ORDERGUARD_FUTU_PYTHON": str(Path(args.python).expanduser().resolve()),
        "ORDERGUARD_OPENAI_MODEL": MODEL,
    })
    server = subprocess.Popen(
        [str(MESH_ROOT / "node_modules" / ".bin" / "tsx"), "server.ts"],
        cwd=str(MESH_ROOT), env=server_env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for_server(server, base_url):
            print('{"ok":false,"state":"failed","code":"mesh_start_failed"}')
            return 3

        replay_env = os.environ.copy()
        replay_env.update({
            "ORDERGUARD_FUTU_SIMULATE_ENABLED": "1",
            "ORDERGUARD_LEDGER_DB": str(ledger),
            "ORDERGUARD_FUTU_CONFIG": str(PACKAGE_DIR / "config.json"),
        })
        command = [
            sys.executable, str(PACKAGE_DIR / "replay.py"),
            "--url", base_url,
            "--ledger", str(ledger),
            "--python", args.python,
            "--output", str(output),
            "--spend-csv", args.spend_csv,
        ]
        completed = subprocess.run(command, cwd=str(MESH_ROOT), env=replay_env, check=False)
        inventory_after = _read_inventory(args.python, preflight_env)
        if inventory_after.get("ok") is not True:
            print('{"ok":false,"state":"failed","code":"order_inventory_after_unavailable"}', flush=True)
            return completed.returncode or 4
        evidence = _attach_inventory_evidence(output, inventory_before, inventory_after)
        print(json.dumps({"futu_order_list_delta": evidence, "artifact": str(output)}, separators=(",", ":")), flush=True)
        if completed.returncode == 0 and evidence.get("proof_state") != "matched":
            return 4
        return completed.returncode
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
