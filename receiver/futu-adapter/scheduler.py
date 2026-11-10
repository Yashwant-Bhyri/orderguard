#!/usr/bin/env python3
"""Recurring fail-closed W2 Futu SIMULATE session runner (HK time)."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import errno
import fcntl
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PACKAGE_DIR = Path(__file__).resolve().parent
MESH_ROOT = PACKAGE_DIR.parent
ROOM_ROOT = Path(os.environ["ORDERGUARD_ROOM_ROOT"]).expanduser() if os.environ.get("ORDERGUARD_ROOM_ROOT") else None
ROOM_PY = ROOM_ROOT / "room/room.py" if ROOM_ROOT else None
ENV_FILE = Path(os.environ.get(
    "ORDERGUARD_FUTU_ENV_FILE", str(PACKAGE_DIR / "provider-keys.local")
)).expanduser()
SESSIONS_CSV = Path(os.environ.get(
    "ORDERGUARD_FUTU_SESSIONS_CSV", str(PACKAGE_DIR / "results" / "futu-sessions.csv")
)).expanduser()
CONFIG = PACKAGE_DIR / "config.json"
CLI = PACKAGE_DIR / "cli.py"
DEMO = PACKAGE_DIR / "demo.py"
PYTHON = PACKAGE_DIR / ".venv/bin/python"
TZ = ZoneInfo("Asia/Hong_Kong")
KEY_NAMES = {"OPENROUTER_API_KEY", "OPENAI_API_KEY", "LIQUID_API_KEY", "TYPESAFE_API_KEY"}
STATE_DIR = Path(os.environ.get(
    "ORDERGUARD_FUTU_SCHEDULER_STATE_DIR",
    str(Path.home() / ".cache" / "orderguard-futu"),
)).expanduser()
LEGACY_STATE_DIR = Path(os.environ.get(
    "ORDERGUARD_FUTU_SCHEDULER_LEGACY_STATE_DIR",
    str(STATE_DIR),
)).expanduser()
STATE_FILE = STATE_DIR / "scheduler-state.json"
PID_FILE = STATE_DIR / "scheduler.pid"
LOG_FILE = STATE_DIR / "scheduler.log"
DAEMON_LOCK_FILE = STATE_DIR / "scheduler.lock"
STATE_LOCK_FILE = STATE_DIR / "scheduler-state.lock"
LAUNCH_AGENT = PACKAGE_DIR / "com.orderguard.futu.sessions.plist"
LAUNCH_LABEL = "com.orderguard.futu.sessions"
CSV_HEADER = [
    "date", "session", "placed", "blocked", "blocked_sent_to_futu",
    "reconcile_mismatches", "p50_ms", "p95_ms", "run_id", "status", "health_code",
]
SESSIONS = {
    "morning": {"start": (9, 30), "end": (12, 0), "expected_market": "MORNING", "last_start": (10, 15)},
    "afternoon": {"start": (13, 0), "end": (16, 0), "expected_market": "AFTERNOON", "last_start": (13, 45)},
}
MAX_QUOTE_AGE_SECONDS = 60
MAX_QUOTE_FUTURE_SKEW_SECONDS = 5


class HealthFailure(Exception):
    def __init__(self, code: str, fix: str):
        super().__init__(code)
        self.code = code
        self.fix = fix


def quote_timestamp_status(
    value: Any,
    *,
    now: dt.datetime,
    max_age_seconds: int = MAX_QUOTE_AGE_SECONDS,
    future_skew_seconds: int = MAX_QUOTE_FUTURE_SKEW_SECONDS,
) -> tuple[str, dt.datetime | None]:
    """Classify an OpenD quote timestamp against the current HK clock.

    Futu commonly returns a naive local market timestamp; treat those as
    Asia/Hong_Kong. ISO timestamps with an offset (including ``Z``) retain
    their explicit timezone. Invalid, stale, and materially future quotes
    fail closed before the scheduler starts a batch.
    """
    if not isinstance(value, str) or not value.strip():
        return "invalid", None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return "invalid", None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=TZ)
    parsed = parsed.astimezone(TZ)
    if now.tzinfo is None or now.utcoffset() is None:
        now = now.replace(tzinfo=TZ)
    age_seconds = (now.astimezone(TZ) - parsed).total_seconds()
    if age_seconds < -future_skew_seconds:
        return "future", parsed
    if age_seconds > max_age_seconds:
        return "stale", parsed
    return "fresh", parsed


def safe_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in KEY_NAMES}
    env.update({
        "ORDERGUARD_FUTU_SIMULATE_ENABLED": "1",
        "ORDERGUARD_FUTU_CONFIG": str(CONFIG),
        "ORDERGUARD_DISABLE_LOCAL_ENV": "1",
    })
    return env


def json_command(command: list[str], *, input_text: str | None = None, timeout: int = 45) -> tuple[int, dict[str, Any]]:
    try:
        result = subprocess.run(
            command, cwd=str(MESH_ROOT), env=safe_env(), input=input_text,
            text=True, capture_output=True, timeout=timeout, check=False,
        )
        payload = json.loads(result.stdout.strip()) if result.stdout.strip() else {}
        return result.returncode, payload if isinstance(payload, dict) else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return 70, {"ok": False, "code": "health_command_failed"}


def check_health(session_name: str, *, deadline: dt.datetime) -> dict[str, Any]:
    expected = SESSIONS[session_name]["expected_market"]
    while dt.datetime.now(TZ) <= deadline:
        checked_at = dt.datetime.now(TZ).isoformat(timespec="seconds")
        code, preflight = json_command([str(PYTHON), str(CLI), "preflight"], timeout=30)
        if code != 0 or preflight.get("ok") is not True:
            reason = str(preflight.get("code", "opend_preflight_failed"))
            if reason in {"hk_market_closed", "hk_market_not_open"}:
                time.sleep(30)
                continue
            raise HealthFailure(reason, "Restore OpenD at 127.0.0.1:11111 and verify its read-only quote/trading login plus one active HK STOCK SIMULATE account; do not unlock.")
        if preflight.get("endpoint") != "127.0.0.1:11111" or preflight.get("trd_env") != "SIMULATE" \
                or preflight.get("account_type") != "STOCK" or preflight.get("unlock_called") is not False:
            raise HealthFailure("paper_account_gate_failed", "Restore the HK STOCK SIMULATE account selection and confirm no unlock path was used.")
        if preflight.get("quote_logged_in") is not True or preflight.get("trading_logged_in") is not True:
            raise HealthFailure("opend_login_gate_failed", "Sign OpenD into quote and trading read-only sessions, then leave SIMULATE selected; no trading password or unlock is allowed.")
        if preflight.get("market_hk") != expected:
            if preflight.get("market_hk") in {"REST", None, ""}:
                time.sleep(30)
                continue
            raise HealthFailure("unexpected_hk_market_session", "Check the HK session clock and rerun only in the matching morning or afternoon window.")

        try:
            config = json.loads(CONFIG.read_text(encoding="utf-8"))
            symbol_routes = config.get("symbols")
            if config.get("trd_env") != "SIMULATE" or not isinstance(symbol_routes, dict):
                raise ValueError("invalid route config")
            routes = {
                str(alias): str(route["code"])
                for alias, route in symbol_routes.items()
                if isinstance(route, dict) and route.get("market") == "HK" and isinstance(route.get("code"), str)
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raise HealthFailure("symbol_map_invalid", "Repair futu-adapter/config.json so all MANDATE-M1 HK aliases have mapped HK codes and trd_env=SIMULATE.")
        code, quote_result = json_command([str(PYTHON), str(CLI)], input_text='{"action":"quotes","call_site":"scheduler_health"}\n')
        if code != 0 or quote_result.get("ok") is not True or quote_result.get("trd_env") != "SIMULATE":
            reason = str(quote_result.get("code", "mapped_quote_health_failed"))
            if reason == "hk_market_closed":
                time.sleep(30)
                continue
            raise HealthFailure(reason, "Refresh OpenD's HK market snapshot and confirm every mapped route has a fresh, nonsuspended quote and valid board lot; check the configured HK tickers.")
        quote_rows = quote_result.get("quotes") if isinstance(quote_result.get("quotes"), list) else []
        by_code = {str(row.get("code")): row for row in quote_rows if isinstance(row, dict)}
        if set(by_code) != set(routes.values()):
            raise HealthFailure("mapped_quote_snapshot_incomplete", "Check the HK symbol map and OpenD simulator quote permissions; every configured HK code must return a fresh snapshot.")
        bad = [code for code, row in by_code.items() if isinstance(row.get("lot_size"), bool)
               or not isinstance(row.get("lot_size"), int) or row["lot_size"] < 1
               or row.get("suspension") is True]
        if bad:
            raise HealthFailure("mapped_quote_or_lot_invalid", "Verify the mapped HK simulator tickers, board lots, and suspension status before retrying.")
        freshness_now = dt.datetime.now(TZ)
        timestamp_status = {
            code: quote_timestamp_status(row.get("update_time"), now=freshness_now)[0]
            for code, row in by_code.items()
        }
        if any(status == "invalid" for status in timestamp_status.values()):
            raise HealthFailure("mapped_quote_timestamp_invalid", "Refresh OpenD's HK quote snapshot and confirm each update_time is a parseable ISO timestamp or local HK timestamp.")
        if any(status == "future" for status in timestamp_status.values()):
            raise HealthFailure("mapped_quote_timestamp_future", "Check the OpenD host clock and quote timestamp timezone; timestamps more than five seconds ahead of HK time are rejected.")
        if any(status == "stale" for status in timestamp_status.values()):
            raise HealthFailure("mapped_quote_stale", "Refresh OpenD's HK market snapshot; every mapped quote must be at most 60 seconds old before a batch starts.")
        health = {
            "ok": True, "checked_at_hkt": freshness_now.isoformat(timespec="seconds"), "endpoint": preflight["endpoint"],
            "trd_env": "SIMULATE", "account_type": "STOCK", "market_hk": expected,
            "unlock_called": False,
            "routes": [{"mandate_symbol": alias, "futu_code": futu_code,
                        "lot_size": by_code[futu_code]["lot_size"],
                        "update_time": by_code[futu_code]["update_time"]}
                       for alias, futu_code in sorted(routes.items())],
        }
        return health
    raise HealthFailure("market_open_timeout", "Confirm whether HKEX is on a trading holiday; if it is a trading day, restore OpenD connectivity and rerun the missed session before its window closes.")


def read_state(path: Path | None = None) -> dict[str, Any]:
    path = path or STATE_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and isinstance(value.get("sessions"), dict) else {"sessions": {}}
    except (OSError, json.JSONDecodeError):
        return {"sessions": {}}


def write_state(state: dict[str, Any], path: Path | None = None) -> None:
    path = path or STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def claim_session(session_date: dt.date, session_name: str) -> bool:
    """Atomically claim a session so concurrent scheduler copies fail closed."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(STATE_LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        state = read_state()
        sessions = state.setdefault("sessions", {})
        key = f"{session_date.isoformat()}:{session_name}"
        if key in sessions:
            return False
        sessions[key] = {
            "status": "running",
            "started_at_hkt": dt.datetime.now(TZ).isoformat(timespec="seconds"),
            "pid": os.getpid(),
        }
        write_state(state)
        return True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def reserve_legacy_sessions(now: dt.datetime) -> bool:
    """Pre-claim upcoming dates for older daemon copies that lack flock guards."""
    if LEGACY_STATE_DIR.resolve() == STATE_DIR.resolve():
        return True
    try:
        LEGACY_STATE_DIR.mkdir(parents=True, exist_ok=True)
        lock_path = LEGACY_STATE_DIR / "scheduler-state.lock"
        state_path = LEGACY_STATE_DIR / "scheduler-state.json"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            state = read_state(state_path)
            sessions = state.setdefault("sessions", {})
            changed = False
            for day_offset in range(0, 4):
                day = now.date() + dt.timedelta(days=day_offset)
                if day.weekday() >= 5:
                    continue
                for name in SESSIONS:
                    start, _deadline, _end = slot_times(day, name)
                    key = f"{day.isoformat()}:{name}"
                    if start > now and key not in sessions:
                        sessions[key] = {
                            "status": "reserved_for_singleton_runner",
                            "reserved_at_hkt": now.isoformat(timespec="seconds"),
                            "reserved_by_pid": os.getpid(),
                        }
                        changed = True
            if changed:
                write_state(state, state_path)
            return True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    except OSError:
        return False


def append_csv(row: dict[str, Any]) -> bool:
    SESSIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with SESSIONS_CSV.open("a+", newline="", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        has_header = bool(stream.readline())
        if not has_header:
            stream.seek(0)
            csv.writer(stream).writerow(CSV_HEADER)
        stream.seek(0)
        existing = list(csv.DictReader(stream)) if has_header else []
        if any(old.get("date") == row["date"] and old.get("session") == row["session"] for old in existing):
            return False
        stream.seek(0, os.SEEK_END)
        csv.writer(stream).writerow([row.get(key, "") for key in CSV_HEADER])
        stream.flush()
        os.fsync(stream.fileno())
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return True


def post_failure(session_date: str, session_name: str, code: str, fix: str) -> None:
    if ROOM_PY is None or ROOM_ROOT is None or not ROOM_PY.is_file():
        return
    title = f"W2 {session_date} {session_name} session stopped: {code}"
    body = f"{session_date} HKT {session_name}: health/proof gate `{code}` stopped the run. Fix: {fix}"
    subprocess.run([
        sys.executable, str(ROOM_PY), "post", "--from", "futu", "--to", "yash,claude",
        "--type", "note", "--ref", "B5", "--title", title, "--body", body,
    ], cwd=str(ROOM_ROOT), env=safe_env(), stdin=subprocess.DEVNULL,
      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)


def artifact_numbers(output_dir: Path) -> tuple[dict[str, Any], Path | None]:
    stdout_path = output_dir / "demo.stdout.txt"
    artifact_path: Path | None = None
    if stdout_path.is_file():
        for raw in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("artifact"), str):
                candidate = Path(value["artifact"])
                if candidate.is_file():
                    artifact_path = candidate
            if isinstance(value, dict) and isinstance(value.get("futu_order_list_delta"), dict):
                candidate = Path(str(value.get("artifact", "")))
                if candidate.is_file():
                    artifact_path = candidate
    if artifact_path is None and output_dir.exists():
        candidates = sorted(output_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        artifact_path = candidates[0] if candidates else None
    if artifact_path is None:
        return {}, None
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, artifact_path
    rows = artifact.get("results") if isinstance(artifact, dict) and isinstance(artifact.get("results"), list) else []
    def is_blocked(row: dict[str, Any]) -> bool:
        receiver = row.get("receiver") if isinstance(row.get("receiver"), dict) else {}
        if row.get("dispatch_attempted") is True:
            return False
        return bool(row.get("state") == "mandate_blocked"
                    or row.get("receiver_block_kind") in {"mandate_receiver_denial", "mandate_price_band_denial", "second_lock_hold", "saved_attack_bank_review_hold"}
                    or receiver.get("result") in {"receiver_denial", "second_lock_hold", "pretool_hold"})
    blocked_rows = [row for row in rows if isinstance(row, dict) and is_blocked(row)]
    raw_blocked_sent = artifact.get("blocked_orders_sent_to_futu")
    blocked_sent: int | str = raw_blocked_sent if isinstance(raw_blocked_sent, int) and not isinstance(raw_blocked_sent, bool) and raw_blocked_sent >= 0 else ""
    placed = sum(1 for row in rows if isinstance(row, dict) and row.get("dispatch_attempted") is True and row.get("state") == "futu_accepted")
    counts = (artifact.get("reconciliation") or {}).get("counts", {}) if isinstance(artifact.get("reconciliation"), dict) else {}
    mismatches = sum(int(counts.get(key, 0) or 0) for key in ("order_mismatches", "position_mismatches", "account_mismatches"))
    latency = artifact.get("latency_agent_to_futu_ack_ms") if isinstance(artifact.get("latency_agent_to_futu_ack_ms"), dict) else {}
    values = {
        "date": dt.datetime.now(TZ).date().isoformat(),
        "placed": placed, "blocked": len(blocked_rows), "blocked_sent_to_futu": blocked_sent,
        "reconcile_mismatches": mismatches,
        "p50_ms": latency.get("p50", ""), "p95_ms": latency.get("p95", ""),
        "run_id": artifact.get("run_id", ""),
        "status": "completed" if artifact.get("ok") is True and blocked_sent == 0 and (artifact.get("broker_order_inventory_delta") or {}).get("proof_state") == "matched" else "proof_failed",
        "health_code": "",
    }
    return values, artifact_path


def run_session(session_date: dt.date, session_name: str) -> None:
    slot = SESSIONS[session_name]
    key = f"{session_date.isoformat()}:{session_name}"
    state = read_state()
    if not claim_session(session_date, session_name):
        return
    started = dt.datetime.now(TZ)
    state = read_state()
    sessions = state.setdefault("sessions", {})
    output_dir = PACKAGE_DIR / "results" / "scheduled" / session_date.isoformat() / session_name
    output_dir.mkdir(parents=True, exist_ok=True)
    start_deadline = dt.datetime.combine(session_date, dt.time(*slot["last_start"]), tzinfo=TZ)
    try:
        health = check_health(session_name, deadline=start_deadline)
        print(json.dumps({"event": "health_check_pass", "date": session_date.isoformat(), "session": session_name, **health}, separators=(",", ":")), flush=True)
    except HealthFailure as failure:
        if failure.code == "market_open_timeout":
            row = {"date": session_date.isoformat(), "session": session_name, "placed": "", "blocked": "",
                   "blocked_sent_to_futu": "", "reconcile_mismatches": "", "p50_ms": "", "p95_ms": "",
                   "run_id": "", "status": "market_closed_or_holiday", "health_code": failure.code}
            appended = append_csv(row)
            sessions[key] = {"status": "market_closed_or_holiday", "code": failure.code,
                             "finished_at_hkt": dt.datetime.now(TZ).isoformat(timespec="seconds"), "csv_appended": appended}
            write_state(state)
            print(json.dumps({"event": "market_session_skipped", "date": session_date.isoformat(), "session": session_name,
                              "code": failure.code, "csv_appended": appended}, separators=(",", ":")), flush=True)
            return
        row = {"date": session_date.isoformat(), "session": session_name, "placed": "", "blocked": "",
               "blocked_sent_to_futu": "", "reconcile_mismatches": "", "p50_ms": "", "p95_ms": "",
               "run_id": "", "status": "health_failed", "health_code": failure.code}
        appended = append_csv(row)
        sessions[key] = {"status": "health_failed", "code": failure.code, "finished_at_hkt": dt.datetime.now(TZ).isoformat(timespec="seconds"), "csv_appended": appended}
        write_state(state)
        post_failure(session_date.isoformat(), session_name, failure.code, failure.fix)
        print(json.dumps({"event": "health_check_failed", "date": session_date.isoformat(), "session": session_name, "code": failure.code, "fix": failure.fix, "csv_appended": appended}, separators=(",", ":")), flush=True)
        return

    spend_csv = Path(os.environ.get(
        "ORDERGUARD_ROOM_SPEND_CSV", str(PACKAGE_DIR / "results" / "SPEND.csv")
    )).expanduser()
    command = [sys.executable, str(DEMO), "--python", str(PYTHON), "--env-file", str(ENV_FILE),
               "--spend-csv", str(spend_csv), "--output-dir", str(output_dir)]
    remaining = (dt.datetime.combine(session_date, dt.time(*slot["end"]), tzinfo=TZ) - dt.datetime.now(TZ)).total_seconds()
    if remaining < 60:
        failure = HealthFailure("session_window_too_short", "Restart the scheduler before the next HK session; do not start a shortened or partial order batch.")
        row = {"date": session_date.isoformat(), "session": session_name, "placed": "", "blocked": "",
               "blocked_sent_to_futu": "", "reconcile_mismatches": "", "p50_ms": "", "p95_ms": "",
               "run_id": "", "status": "health_failed", "health_code": failure.code}
        appended = append_csv(row)
        sessions[key] = {"status": "health_failed", "code": failure.code, "finished_at_hkt": dt.datetime.now(TZ).isoformat(timespec="seconds"), "csv_appended": appended}
        write_state(state)
        post_failure(session_date.isoformat(), session_name, failure.code, failure.fix)
        print(json.dumps({"event": "session_stopped", "date": session_date.isoformat(), "session": session_name, "code": failure.code}, separators=(",", ":")), flush=True)
        return

    try:
        completed = subprocess.run(command, cwd=str(MESH_ROOT), env=safe_env(), text=True,
                                   capture_output=True, timeout=max(60, int(remaining)), check=False)
        (output_dir / "demo.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (output_dir / "demo.stderr.txt").write_text(completed.stderr, encoding="utf-8")
        (output_dir / "demo.exit_code").write_text(str(completed.returncode) + "\n", encoding="utf-8")
        print(completed.stdout, end="", flush=True)
        numbers, artifact_path = artifact_numbers(output_dir)
        row = {"date": session_date.isoformat(), "session": session_name, **numbers}
        row.setdefault("placed", "")
        row.setdefault("blocked", "")
        row.setdefault("blocked_sent_to_futu", "")
        row.setdefault("reconcile_mismatches", "")
        row.setdefault("p50_ms", "")
        row.setdefault("p95_ms", "")
        row.setdefault("run_id", "")
        row.setdefault("health_code", "")
        if completed.returncode != 0:
            row["status"] = row.get("status", "run_failed")
            row["health_code"] = "demo_exit_" + str(completed.returncode)
        appended = append_csv(row)
        final_status = "completed" if completed.returncode == 0 and row.get("status") == "completed" else "run_failed"
        sessions[key] = {"status": final_status, "finished_at_hkt": dt.datetime.now(TZ).isoformat(timespec="seconds"),
                         "exit_code": completed.returncode, "artifact": str(artifact_path) if artifact_path else None,
                         "csv_appended": appended, "health": health}
        write_state(state)
        if final_status != "completed":
            post_failure(session_date.isoformat(), session_name, str(row.get("health_code") or "proof_artifact_failed"),
                         "Inspect the session stdout, pinned proposal bank, OpenD SIMULATE order-list delta, and reconciliation artifact; fix the reported gate before a later session.")
        print(json.dumps({"event": "session_finished", "date": session_date.isoformat(), "session": session_name,
                          "status": final_status, "exit_code": completed.returncode, "csv_appended": appended,
                          "artifact": str(artifact_path) if artifact_path else None,
                          "numbers": {key: row.get(key) for key in CSV_HEADER}}, separators=(",", ":")), flush=True)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode("utf-8", "replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
        (output_dir / "demo.stdout.txt").write_text(stdout, encoding="utf-8")
        row = {"date": session_date.isoformat(), "session": session_name, "placed": "", "blocked": "",
               "blocked_sent_to_futu": "", "reconcile_mismatches": "", "p50_ms": "", "p95_ms": "",
               "run_id": "", "status": "run_failed", "health_code": "demo_timeout"}
        appended = append_csv(row)
        sessions[key] = {"status": "run_failed", "code": "demo_timeout", "finished_at_hkt": dt.datetime.now(TZ).isoformat(timespec="seconds"), "csv_appended": appended}
        write_state(state)
        post_failure(session_date.isoformat(), session_name, "demo_timeout", "Inspect the isolated ledger and Futu SIMULATE order inventory before any retry; never blindly replay a timed-out batch.")
        print(json.dumps({"event": "session_failed", "date": session_date.isoformat(), "session": session_name, "code": "demo_timeout"}, separators=(",", ":")), flush=True)


def slot_times(day: dt.date, name: str) -> tuple[dt.datetime, dt.datetime, dt.datetime]:
    slot = SESSIONS[name]
    start = dt.datetime.combine(day, dt.time(*slot["start"]), tzinfo=TZ)
    deadline = dt.datetime.combine(day, dt.time(*slot["last_start"]), tzinfo=TZ)
    end = dt.datetime.combine(day, dt.time(*slot["end"]), tzinfo=TZ)
    return start, deadline, end


def daemon_loop() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(DAEMON_LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        print(json.dumps({"event": "scheduler_singleton_refused", "lock_file": str(DAEMON_LOCK_FILE)}, separators=(",", ":")), flush=True)
        return 0
    own_pid = os.getpid()
    PID_FILE.write_text(str(own_pid) + "\n", encoding="utf-8")
    print(json.dumps({"event": "scheduler_started", "pid": own_pid, "timezone": "Asia/Hong_Kong",
                      "sessions": list(SESSIONS), "keys_loaded": False}, separators=(",", ":")), flush=True)
    try:
        while True:
            now = dt.datetime.now(TZ)
            if not reserve_legacy_sessions(now):
                print(json.dumps({"event": "legacy_scheduler_reservation_failed"}, separators=(",", ":")), flush=True)
                time.sleep(30)
                continue
            if now.weekday() < 5:
                for name in SESSIONS:
                    start, deadline, _end = slot_times(now.date(), name)
                    key = f"{now.date().isoformat()}:{name}"
                    state = read_state()
                    existing = state.get("sessions", {}).get(key)
                    if existing:
                        if existing.get("status") == "running":
                            existing.update({"status": "interrupted_no_retry", "finished_at_hkt": now.isoformat(timespec="seconds")})
                            appended = append_csv({
                                "date": now.date().isoformat(), "session": name, "placed": "", "blocked": "",
                                "blocked_sent_to_futu": "", "reconcile_mismatches": "", "p50_ms": "", "p95_ms": "",
                                "run_id": "", "status": "interrupted_no_retry", "health_code": "scheduler_restarted_during_session",
                            })
                            existing["csv_appended"] = appended
                            write_state(state)
                            post_failure(now.date().isoformat(), name, "scheduler_restarted_during_session",
                                         "Inspect the saved run output and Futu SIMULATE order list before deciding whether a new session is needed; automatic retry is disabled to avoid duplicates.")
                        continue
                    if now >= start:
                        if now <= deadline:
                            run_session(now.date(), name)
                        else:
                            row = {"date": now.date().isoformat(), "session": name, "placed": "", "blocked": "",
                                   "blocked_sent_to_futu": "", "reconcile_mismatches": "", "p50_ms": "", "p95_ms": "",
                                   "run_id": "", "status": "missed", "health_code": "scheduler_late"}
                            appended = append_csv(row)
                            state.setdefault("sessions", {})[key] = {"status": "missed", "finished_at_hkt": now.isoformat(timespec="seconds"), "csv_appended": appended}
                            write_state(state)
                            post_failure(now.date().isoformat(), name, "scheduler_late", "Keep the scheduler process running; the next configured HK session starts at its next open and this missed batch will not be replayed automatically.")
            now = dt.datetime.now(TZ)
            future = []
            for day_offset in range(0, 3):
                day = now.date() + dt.timedelta(days=day_offset)
                if day.weekday() >= 5:
                    continue
                for name in SESSIONS:
                    start, _, _ = slot_times(day, name)
                    if start > now:
                        future.append(start)
            if future:
                delay = max(1, min(30, (min(future) - now).total_seconds()))
            else:
                delay = 30
            time.sleep(delay)
    finally:
        try:
            if PID_FILE.read_text(encoding="utf-8").strip() == str(own_pid):
                PID_FILE.unlink()
        except OSError:
            pass
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
    return 0


def pid_status(pid: int) -> str:
    """Return alive/dead/unknown without equating EPERM with scheduler identity."""
    try:
        os.kill(pid, 0)
        return "alive"
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "unknown"
    except OSError as error:
        return "dead" if error.errno == errno.ESRCH else "unknown"


def pid_blocks_duplicate_start(status: str) -> bool:
    """Fail closed for launch deduplication unless the recorded PID is gone."""
    return status != "dead"


def start_daemon() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    launchctl = shutil.which("launchctl")
    if sys.platform == "darwin" and launchctl:
        domain = f"gui/{os.getuid()}"
        service = f"{domain}/{LAUNCH_LABEL}"
        loaded = subprocess.run([launchctl, "print", service], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if loaded.returncode == 0:
            print(json.dumps({"state": "already_running", "supervisor": "launchd", "service": service,
                              "log_file": str(LOG_FILE)}, separators=(",", ":")))
            return 0
        if PID_FILE.exists():
            try:
                existing_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                existing_pid = -1
            if existing_pid > 0:
                existing_status = pid_status(existing_pid)
                if pid_blocks_duplicate_start(existing_status):
                    state = "already_running" if existing_status == "alive" else "process_status_unverified"
                    print(json.dumps({"state": state, "supervisor": "process", "pid": existing_pid,
                                      "pid_status": existing_status, "pid_file": str(PID_FILE),
                                      "log_file": str(LOG_FILE)}, separators=(",", ":")))
                    return 0 if existing_status == "alive" else 3
        environment_variables = {
            "ORDERGUARD_FUTU_SIMULATE_ENABLED": "1",
            "ORDERGUARD_FUTU_CONFIG": str(CONFIG),
            "ORDERGUARD_DISABLE_LOCAL_ENV": "1",
            "ORDERGUARD_FUTU_SCHEDULER_STATE_DIR": str(STATE_DIR),
            "ORDERGUARD_FUTU_SCHEDULER_LEGACY_STATE_DIR": str(LEGACY_STATE_DIR),
        }
        for name in (
            "ORDERGUARD_FUTU_ENV_FILE", "ORDERGUARD_FUTU_SESSIONS_CSV",
            "ORDERGUARD_ROOM_ROOT", "ORDERGUARD_ROOM_SPEND_CSV",
        ):
            value = os.environ.get(name)
            if value:
                environment_variables[name] = str(Path(value).expanduser())
        config = {
            "Label": LAUNCH_LABEL,
            "ProgramArguments": [sys.executable, str(Path(__file__).resolve()), "daemon"],
            "WorkingDirectory": str(MESH_ROOT),
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 30,
            "ProcessType": "Background",
            "Umask": 63,
            "StandardOutPath": str(LOG_FILE),
            "StandardErrorPath": str(LOG_FILE),
            "EnvironmentVariables": environment_variables,
        }
        LAUNCH_AGENT.write_bytes(plistlib.dumps(config, fmt=plistlib.FMT_XML, sort_keys=True))
        boot = subprocess.run([launchctl, "bootstrap", domain, str(LAUNCH_AGENT)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, check=False)
        if boot.returncode != 0:
            loaded = subprocess.run([launchctl, "print", service], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if loaded.returncode == 0:
                print(json.dumps({"state": "already_running", "supervisor": "launchd", "service": service,
                                  "log_file": str(LOG_FILE)}, separators=(",", ":")))
                return 0
            diagnostic = (boot.stderr or boot.stdout or "").strip()[:240]
            print(json.dumps({"state": "launchd_unavailable", "service": service,
                              "bootstrap_exit": boot.returncode, "bootstrap_diagnostic": diagnostic,
                              "fallback": "detached_process", "keys_loaded": False}, separators=(",", ":")), flush=True)
            # LaunchAgent bootstrap can fail in managed desktop sessions. Fall
            # through to the detached PID-file supervisor below so this
            # scheduler outlives the command/session that started it.
        else:
            print(json.dumps({"state": "started", "supervisor": "launchd", "service": service,
                              "first_session": "next eligible HK session after start",
                              "schedule": "weekdays 09:30–12:00 and 13:00–16:00 HKT",
                              "keys_loaded": False, "plist": str(LAUNCH_AGENT), "log_file": str(LOG_FILE)}, separators=(",", ":")))
            return 0

    if PID_FILE.exists():
        try:
            old_value = PID_FILE.read_text(encoding="utf-8").strip()
            old_pid = int(old_value.split(":", 1)[1]) if old_value.startswith("starting:") else int(old_value)
        except (OSError, ValueError):
            old_pid = -1
        if old_pid > 0:
            old_status = pid_status(old_pid)
            if pid_blocks_duplicate_start(old_status):
                state = "already_running" if old_status == "alive" else "process_status_unverified"
                print(json.dumps({"state": state, "pid": old_pid, "pid_status": old_status,
                                  "pid_file": str(PID_FILE)}, separators=(",", ":")))
                return 0 if old_status == "alive" else 3
        PID_FILE.unlink(missing_ok=True)
    try:
        fd = os.open(PID_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(fd, f"starting:{os.getpid()}\n".encode("ascii"))
        os.close(fd)
    except FileExistsError:
        print(json.dumps({"state": "already_running", "pid_file": str(PID_FILE)}, separators=(",", ":")))
        return 0
    log = LOG_FILE.open("a", encoding="utf-8")
    env = safe_env()
    try:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "daemon"], cwd=str(MESH_ROOT),
                                 env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                 close_fds=True, start_new_session=True)
    except OSError:
        log.close()
        PID_FILE.unlink(missing_ok=True)
        print(json.dumps({"state": "start_failed", "reason": "scheduler_process_start_failed"}, separators=(",", ":")))
        return 2
    log.close()
    for _ in range(30):
        try:
            recorded_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            recorded_pid = None
        if recorded_pid == child.pid:
            break
        if child.poll() is not None:
            PID_FILE.unlink(missing_ok=True)
            print(json.dumps({"state": "start_failed", "exit_code": child.returncode, "log_file": str(LOG_FILE)}, separators=(",", ":")))
            return 2
        time.sleep(0.1)
    if recorded_pid != child.pid:
        try:
            child.terminate()
        except OSError:
            pass
        PID_FILE.unlink(missing_ok=True)
        print(json.dumps({"state": "start_failed", "reason": "scheduler_pid_handshake_timeout", "log_file": str(LOG_FILE)}, separators=(",", ":")))
        return 2
    print(json.dumps({"state": "started", "pid": child.pid, "first_session": "2026-10-30 morning 09:30 HKT",
                      "schedule": "weekdays 09:30–12:00 and 13:00–16:00 HKT", "keys_loaded": False,
                      "pid_file": str(PID_FILE), "log_file": str(LOG_FILE)}, separators=(",", ":")))
    return 0


def print_status() -> int:
    alive = False
    pid: int | None = None
    supervisor = "process"
    if sys.platform == "darwin" and shutil.which("launchctl"):
        service = f"gui/{os.getuid()}/{LAUNCH_LABEL}"
        loaded = subprocess.run([shutil.which("launchctl") or "launchctl", "print", service],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, check=False)
        if loaded.returncode == 0:
            alive = True
            supervisor = "launchd"
    process_status = "no_pid"
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        process_status = pid_status(pid)
        alive = alive or process_status == "alive"
    except (OSError, ValueError):
        pass
    state = "running" if alive else ("unverified" if process_status == "unknown" else "stopped")
    print(json.dumps({"state": state, "supervisor": supervisor, "pid": pid,
                      "pid_status": process_status,
                      "sessions": read_state().get("sessions", {}), "pid_file": str(PID_FILE),
                      "log_file": str(LOG_FILE)}, separators=(",", ":")))
    return 0


def stop_daemon() -> int:
    if sys.platform == "darwin" and shutil.which("launchctl"):
        service = f"gui/{os.getuid()}/{LAUNCH_LABEL}"
        stopped = subprocess.run([shutil.which("launchctl") or "launchctl", "bootout", service],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, check=False)
        if stopped.returncode == 0:
            print(json.dumps({"state": "stop_sent", "supervisor": "launchd", "service": service}, separators=(",", ":")))
            return 0
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        print(json.dumps({"state": "stopped", "reason": "no_pid_file"}, separators=(",", ":")))
        return 0
    status = pid_status(pid)
    if status == "unknown":
        print(json.dumps({"state": "stop_unverified", "pid": pid,
                          "reason": "process_identity_unavailable"}, separators=(",", ":")))
        return 3
    if status == "dead":
        PID_FILE.unlink(missing_ok=True)
        print(json.dumps({"state": "stopped", "reason": "stale_pid_file"}, separators=(",", ":")))
        return 0
    os.kill(pid, signal.SIGTERM)
    print(json.dumps({"state": "stop_sent", "pid": pid}, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "daemon", "status", "stop"))
    args = parser.parse_args()
    if args.action == "start":
        return start_daemon()
    if args.action == "status":
        return print_status()
    if args.action == "stop":
        return stop_daemon()
    return daemon_loop()


if __name__ == "__main__":
    raise SystemExit(main())
