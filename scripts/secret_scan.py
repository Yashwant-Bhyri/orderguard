#!/usr/bin/env python3
"""Scan release files for credential-like material without printing values."""

from __future__ import annotations

import json
import math
from collections import Counter
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("provider_key_sk", re.compile(r"\bsk-(?:or-v1-)?[A-Za-z0-9_-]{8,}\b")),
    ("github_token", re.compile(r"\b(?:gho|ghp)_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA)[A-Z0-9]{16}\b")),
    (
        "aws_secret_access_key",
        re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{32,})"),
    ),
    (
        "binance_credential_assignment",
        re.compile(
            r"(?i)binance.{0,40}?(?:api[_ -]?key|secret)\s*[:=]\s*['\"]?([A-Za-z0-9_+/=-]{16,})"
        ),
    ),
    ("bearer_header", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    (
        "url_query_token",
        re.compile(
            r"(?i)[?&](?:access[_-]?token|api[_-]?key|token|secret|signature|auth|password|key)=([^&#\s]+)"
        ),
    ),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|private[_-]?key)"
            r"\s*[:=]\s*['\"]([A-Za-z0-9._~+/=-]{12,})['\"]"
        ),
    ),
)

TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9/+_=-]{32,}(?![A-Za-z0-9])")
URL_RE = re.compile(r"https?://[^\s)<>]+", re.IGNORECASE)
HIGH_ENTROPY_MIN_BITS_PER_CHAR = 4.8
HASH_FIELD_CONTEXT_RE = re.compile(
    r"(?i)(?:sha(?:1|224|256|384|512)?|checksum|digest|integrity)"
    r"(?:[\"']?\s*[:=]\s*[\"']?|[-_:])$"
)
W6_LEDGER_IDENTIFIER_FILES = {
    "benign-m1-replay-validated.jsonl",
    "tiered-attack-runs.jsonl",
    "tiered-replay-runs.jsonl",
}


def shannon_entropy(value: str) -> float:
    length = len(value)
    counts = Counter(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def files_under(root: Path):
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name != ".git")
        base = Path(current)
        for name in sorted(names):
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            yield path


def is_known_public_hkex_reference(line: str, start: int, end: int) -> bool:
    """Allow HKEX's public opaque product IDs; sensitive query names still match above."""
    for match in URL_RE.finditer(line):
        if not (match.start() <= start < end <= match.end()):
            continue
        parts = urlsplit(match.group(0))
        keys = {key.lower() for key, _ in parse_qsl(parts.query, keep_blank_values=True)}
        return (
            parts.hostname == "www.hkex.com.hk"
            and parts.path.endswith("historicalDataProfile.aspx")
            and bool(keys & {"productid", "schemeid"})
            and keys <= {"productid", "schemeid", "isprint"}
        )
    return False


def is_known_w6_synthetic_identifier(path: Path, field: str, value: str) -> bool:
    """Allow documented synthetic digest/ID formats only in sanitized W6 evidence logs."""
    if path.name not in W6_LEDGER_IDENTIFIER_FILES or "evidence/w6/results" not in path.as_posix():
        return False
    field_name = field.rsplit(".", 1)[-1]
    urlsafe = re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None
    if field_name in {"sha256", "intentHash", "orderHash"}:
        return urlsafe and len(value) == 43
    if field_name == "orderId":
        return urlsafe and len(value) == 39
    return False


def string_values(value, field: str = ""):
    """Yield JSON string values with their key path, without exposing them in output."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from string_values(child, f"{field}.{key}" if field else str(key))
    elif isinstance(value, list):
        for child in value:
            yield from string_values(child, field)
    elif isinstance(value, str):
        yield field, value


def is_json_digest_field(field: str, value: str) -> bool:
    """Recognize standard encoded digest shapes in structured JSON fields."""
    name = field.rsplit(".", 1)[-1].lower()
    if name not in {
        "sha1", "sha224", "sha256", "sha384", "sha512",
        "checksum", "digest", "integrity", "intenthash", "orderhash",
    }:
        return False
    return (
        re.fullmatch(r"[A-Fa-f0-9]{64}", value) is not None
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is not None
    )


def is_base64_prose(token: str) -> bool:
    """A base64 run that decodes to plain English text (e.g. the lab's encoded attack payloads) is not a key."""
    import base64
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), validate=True)
        text = raw.decode("ascii")
    except Exception:
        return False
    words = [w for w in text.split() if w.isalpha()]
    return len(text) >= 24 and all(32 <= ord(c) < 127 for c in text) and len(words) >= 0.6 * len(text.split())


OPENROUTER_GENERATION_ID_RE = re.compile(r'"id": "gen-\d{10}-[A-Za-z0-9]{20}",')


def high_entropy_hits(path: Path, line: str) -> bool:
    """Return whether a line has a high-entropy candidate outside documented data fields."""
    if path.suffix.lower() == ".jsonl":
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            for field, value in string_values(parsed):
                if is_known_w6_synthetic_identifier(path, field, value):
                    continue
                if is_json_digest_field(field, value):
                    continue
                for match in TOKEN_RE.finditer(value):
                    if shannon_entropy(match.group(0)) >= HIGH_ENTROPY_MIN_BITS_PER_CHAR and not is_base64_prose(match.group(0)):
                        return True
            return False

    if path.suffix.lower() == ".json" and OPENROUTER_GENERATION_ID_RE.fullmatch(line.strip()):
        return False   # an OpenRouter response id in a recorded reply: random, public, not a credential
    for match in TOKEN_RE.finditer(line):
        token = match.group(0)
        if shannon_entropy(token) < HIGH_ENTROPY_MIN_BITS_PER_CHAR:
            continue
        if is_base64_prose(token):
            continue
        prefix = line[:match.start()].rstrip()
        if HASH_FIELD_CONTEXT_RE.search(prefix):
            continue
        if is_known_public_hkex_reference(line, match.start(), match.end()):
            continue
        if is_release_mapping_path(path, line, match.start(), match.end()):
            continue
        return True
    return False


def is_release_mapping_path(path: Path, line: str, start: int, end: int) -> bool:
    """Treat a path token in the copied W6 source-to-destination map as a path, not a key."""
    if not path.as_posix().endswith("/lab/orderguard/vulnbench/RELEASE-FILES.md"):
        return False
    if "→" not in line or "/" not in line[start:end]:
        return False
    return any(match.start() <= start < end <= match.end() for match in re.finditer(r"`[^`]*`", line))


def scan_file(path: Path) -> list[tuple[str, int]]:
    try:
        content = path.read_bytes().decode("utf-8", errors="ignore")
    except OSError:
        return [("unreadable_file", 1)]

    hits: set[tuple[str, int]] = set()
    for line_number, line in enumerate(content.splitlines(), start=1):
        for name, pattern in PATTERNS:
            if pattern.search(line):
                hits.add((name, line_number))

        if high_entropy_hits(path, line):
            hits.add(("high_entropy_string", line_number))
    return sorted(hits)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: secret_scan.py PATH", file=sys.stderr)
        return 2

    root = Path(argv[1]).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print("secret_scan: expected an existing directory", file=sys.stderr)
        return 2

    findings: list[tuple[str, int, str]] = []
    scanned = 0
    for path in files_under(root):
        scanned += 1
        for pattern_name, line_number in scan_file(path):
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                relative = path.name
            findings.append((relative, line_number, pattern_name))

    if findings:
        for relative, line_number, pattern_name in sorted(findings):
            print(f"{relative}:{line_number}: {pattern_name}")
        print(f"secret_scan: files={scanned} findings={len(findings)}")
        return 1

    print(f"secret_scan: clean files={scanned} findings=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
