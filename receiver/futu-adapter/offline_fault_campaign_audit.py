#!/usr/bin/env python3
"""Read-only integrity audit for schema-v2 offline fault-campaign bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


SOURCE_FILES = {
    "futu-adapter/offline_fault_campaign.py",
    "futu_simulate_adapter.py",
    "futu-adapter/local_sim_venue.py",
    "futu-adapter/config.json",
}
QUOTE_FIXTURE = "futu-adapter/results/offline-quote-fixture.json"
ARCHIVE_PREFIX = "orderguard-source/"


class DuplicateJSONKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKeyError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _load_json_strict(raw: bytes | str) -> Any:
    return json.loads(raw, object_pairs_hook=_unique_object)


def _expected_case_contract() -> dict[str, tuple[str, str | None, dict[str, Any]]]:
    """Frozen case set and observable contract for schema-v2 campaign output."""
    return {
        "recorded_snapshot_fresh_variant": ("fresh SIMULATE quote accepted", "accepted", {}),
        "recorded_snapshot_original_timestamp": (
            "old saved quote refused by 30s gate", "quote_snapshot_invalid", {"dispatches_n": 0}),
        "recorded_snapshot_stale_31s": ("refuse quote older than 30s", "quote_snapshot_invalid", {}),
        "recorded_snapshot_invalid_lot": ("refuse invalid board lot", "quote_snapshot_invalid", {}),
        "quote_timeout": ("fail closed before dispatch", "quote_bridge_internal_error", {}),
        "opend_down_mid_batch": (
            "first order retained; second prepared/no send", "raised_timeout",
            {"inventory_n": 1, "place_calls_n": 1, "second_journal_state": "prepared"}),
        "broker_reject": (
            "rejected; no broker inventory delta", "rejected", {"inventory_n": 0, "place_calls_n": 1}),
        "blocked_order_never_arrives": (
            "no committed authorization; zero venue calls/inventory", "ledger_commit_missing",
            {"inventory_n": 0, "place_calls_n": 0}),
        "venue_lot_reject": (
            "reject invalid board lot with zero inventory", "rejected", {"inventory_n": 0, "place_calls_n": 1}),
        "venue_funds_reject": (
            "reject insufficient local simulated cash", "rejected", {"inventory_n": 0, "place_calls_n": 1}),
        "venue_wrong_account_refused": (
            "wrong account refused before venue call inventory", "account_market_or_environment_mismatch",
            {"inventory_n": 0, "place_calls_n": 0}),
        "venue_real_environment_refused": (
            "REAL environment refused before venue call inventory", "account_market_or_environment_mismatch",
            {"inventory_n": 0, "place_calls_n": 0}),
        "venue_order_lookup_scope": (
            "order lookup filters account and requested date range", "scoped",
            {"exact_n": 1, "foreign_account_n": 0, "future_date_n": 0}),
        "venue_latency_injection": (
            "accepted after >=2ms injected local latency", None,
            {"inventory_n": 1, "place_calls_n": 1, "injected_ms": 3}),
        "partial_fill_reconciliation": (
            "accepted order visible; ledger/Futu mismatch surfaced", "mismatch",
            {"broker_inventory_n": 1, "broker_dealt_qty": 1}),
        "restart_after_reserve_before_place": (
            "resume prepared order once", "accepted", {"inventory_n": 1, "place_calls_n": 1}),
        "duplicate_submit": (
            "one broker order for duplicate idempotency key", "accepted", {"inventory_n": 1, "place_calls_n": 1}),
        "ack_lost_after_broker_accept": (
            "unknown then remark reconciliation; no blind retry", "unknown->accepted",
            {"inventory_n": 1, "place_calls_n": 1}),
    }


def _validate_case_set(cases: list[Any]) -> list[str]:
    errors: list[str] = []
    contract = _expected_case_contract()
    by_name: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"case row {index} is not an object")
            continue
        name = case.get("case")
        if not isinstance(name, str):
            errors.append(f"case row {index} has no string case name")
            continue
        if name in by_name:
            errors.append(f"duplicate case name: {name}")
            continue
        by_name[name] = case

    actual_names = set(by_name)
    expected_names = set(contract)
    for name in sorted(expected_names - actual_names):
        errors.append(f"expected case is missing: {name}")
    for name in sorted(actual_names - expected_names):
        errors.append(f"unexpected case is present: {name}")

    for name, case in by_name.items():
        if name not in contract:
            continue
        expected, observed, required_detail = contract[name]
        if case.get("pass") is not True:
            errors.append(f"{name} did not pass")
        if case.get("expected") != expected:
            errors.append(f"{name} expected description differs")
        if observed is not None and case.get("observed") != observed:
            errors.append(f"{name} observed outcome differs")
        if observed is None:
            actual = case.get("observed")
            if not isinstance(actual, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?ms", actual):
                errors.append(f"{name} observed latency is malformed")
            else:
                latency = float(actual[:-2])
                if latency < 2.0:
                    errors.append(f"{name} observed latency is below 2ms")
        detail = case.get("detail")
        if not isinstance(detail, dict):
            errors.append(f"{name} detail is not an object")
            continue
        for key, value in required_detail.items():
            if detail.get(key) != value:
                errors.append(f"{name} detail.{key} differs")

    partial = by_name.get("partial_fill_reconciliation", {}).get("detail", {})
    partial_counts = partial.get("counts", {}) if isinstance(partial, dict) else {}
    if not isinstance(partial_counts, dict):
        errors.append("partial_fill_reconciliation detail.counts is not an object")
    else:
        expected_counts = {
            "ledger_dispatches": 1, "accepted_orders": 0, "reconciled_strict": 0,
            "reconciled_sim_type_translation": 0, "unknown_orders": 0,
            "order_mismatches": 1, "position_mismatches": 1,
            "account_mismatches": 0, "unresolved_orders": 1,
        }
        for key, value in expected_counts.items():
            if partial_counts.get(key) != value:
                errors.append(f"partial_fill_reconciliation detail.counts.{key} differs")
    return errors


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit(artifact_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        artifact_bytes = artifact_path.read_bytes()
        result = _load_json_strict(artifact_bytes)
    except (OSError, json.JSONDecodeError, DuplicateJSONKeyError) as error:
        return {"audit": "FAIL", "artifact": str(artifact_path), "errors": [f"cannot read artifact: {error}"]}

    if not isinstance(result, dict) or result.get("schema_version") != 2:
        return {"audit": "FAIL", "artifact": str(artifact_path), "errors": ["expected schema_version 2 object"]}
    if result.get("mode") != "offline_fault_campaign":
        errors.append("unexpected campaign mode")

    cases = result.get("cases")
    if not isinstance(cases, list):
        cases = []
        errors.append("cases is not an array")
    passed = sum(isinstance(case, dict) and case.get("pass") is True for case in cases)
    failed = sum(isinstance(case, dict) and case.get("pass") is False for case in cases)
    if any(type(result.get(key)) is not int for key in ("case_n", "passed_n", "failed_n")):
        errors.append("case totals must be integers")
    if result.get("case_n") != len(cases) or result.get("passed_n") != passed or result.get("failed_n") != failed:
        errors.append("case totals do not match the case records")
    if len(cases) != 18 or passed != 18 or failed != 0:
        errors.append("campaign is not 18/18")
    errors.extend(_validate_case_set(cases))
    for key in ("live_opend_calls", "futu_order_submissions", "provider_calls"):
        if type(result.get(key)) is not int or result.get(key) != 0:
            errors.append(f"{key} is nonzero")

    source_hashes = result.get("source_file_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        errors.append("source_file_sha256 is missing")
        source_hashes = {}
    original_source_hashes = source_hashes
    source_hashes = {
        path: expected_hash
        for path, expected_hash in source_hashes.items()
        if isinstance(path, str) and isinstance(expected_hash, str)
    }
    if len(source_hashes) != len(original_source_hashes):
        errors.append("source_file_sha256 contains a non-string path or digest")
    if set(source_hashes) != SOURCE_FILES:
        errors.append("source_file_sha256 does not contain the exact expected source set")
    fixture_hash = result.get("quote_fixture_sha256")
    snapshot = result.get("source_snapshot_archive")
    archive_file: Path | None = None
    archive_bytes: bytes | None = None
    if not isinstance(snapshot, dict) or snapshot.get("format") != "zip" or not isinstance(snapshot.get("file"), str):
        errors.append("source_snapshot_archive metadata is invalid")
    else:
        archive_name = snapshot["file"]
        if PurePosixPath(archive_name).name != archive_name or Path(archive_name).is_absolute():
            errors.append("source archive path must be a sibling filename")
        else:
            archive_file = artifact_path.parent / archive_name
            try:
                archive_bytes = archive_file.read_bytes()
            except OSError as error:
                errors.append(f"cannot read source archive: {error}")
            if archive_bytes is not None and sha256(archive_bytes) != snapshot.get("sha256"):
                errors.append("source archive digest differs from the campaign record")

    archived_files_verified = 0
    archived_fixture_verified = False
    if archive_bytes is not None:
        try:
            with zipfile.ZipFile(archive_file) as bundle:
                names = bundle.namelist()
                if len(names) != len(set(names)):
                    errors.append("source archive contains duplicate paths")
                for name in names:
                    member = PurePosixPath(name)
                    if member.is_absolute() or ".." in member.parts:
                        errors.append(f"unsafe path in source archive: {name}")
                prefix = ARCHIVE_PREFIX
                manifest_name = prefix + "manifest.json"
                if manifest_name not in names:
                    errors.append("source archive has no manifest")
                    manifest: dict[str, Any] = {}
                else:
                    manifest_value = _load_json_strict(bundle.read(manifest_name))
                    if not isinstance(manifest_value, dict):
                        errors.append("source archive manifest is not an object")
                        manifest = {}
                    else:
                        manifest = manifest_value
                manifest_hashes = manifest.get("source_file_sha256", {})
                if not isinstance(manifest_hashes, dict):
                    errors.append("archive source-file manifest is invalid")
                    manifest_hashes = {}
                if manifest_hashes != source_hashes:
                    errors.append("archive and campaign source-file manifests differ")
                if manifest.get("quote_fixture_sha256") != fixture_hash:
                    errors.append("archive and campaign quote-fixture hashes differ")
                if manifest.get("schema_version") != 1:
                    errors.append("archive source-file manifest schema differs")
                expected_members = {manifest_name, prefix + QUOTE_FIXTURE}
                expected_members.update(prefix + path for path in SOURCE_FILES)
                if set(names) != expected_members:
                    errors.append("source archive member set differs from the exact expected bundle")
                for path, expected_hash in source_hashes.items():
                    if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                        errors.append(f"unsafe source path in campaign manifest: {path}")
                        continue
                    member_name = prefix + path
                    if member_name not in names:
                        errors.append(f"source archive is missing {path}")
                        continue
                    if sha256(bundle.read(member_name)) != expected_hash:
                        errors.append(f"source archive hash differs for {path}")
                    else:
                        archived_files_verified += 1
                if prefix + QUOTE_FIXTURE not in names:
                    errors.append("source archive is missing the quote fixture")
                elif sha256(bundle.read(prefix + QUOTE_FIXTURE)) != fixture_hash:
                    errors.append("source archive quote-fixture hash differs")
                else:
                    archived_fixture_verified = True
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError, DuplicateJSONKeyError, KeyError, TypeError) as error:
            errors.append(f"source archive cannot be inspected: {error}")

    return {
        "audit": "FAIL" if errors else "PASS_WITH_LOCAL_PROVENANCE",
        "auditContract": "orderguard-offline-fault-campaign-audit/v2",
        "artifact": str(artifact_path),
        "artifactSha256": sha256(artifact_bytes),
        "sourceArchive": str(archive_file) if archive_file else None,
        "sourceArchiveSha256": sha256(archive_bytes) if archive_bytes is not None else None,
        "sourceFilesVerified": archived_files_verified,
        "quoteFixtureVerified": archived_fixture_verified,
        "caseCount": len(cases),
        "expectedCaseCount": len(_expected_case_contract()),
        "verifiedCaseNames": sorted(
            case.get("case") for case in cases
            if isinstance(case, dict) and isinstance(case.get("case"), str)
        ),
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "limitations": [
            "This is a read-only integrity audit; it does not replay the campaign.",
            "Matching local hashes establish bundle consistency, not publisher authenticity or Futu/OpenD behavior.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a schema-v2 offline campaign JSON and its source ZIP without replaying it.")
    parser.add_argument("artifact", type=Path, help="campaign JSON path")
    args = parser.parse_args()
    report = audit(args.artifact)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    raise SystemExit(0 if report["audit"] != "FAIL" else 1)


if __name__ == "__main__":
    main()
