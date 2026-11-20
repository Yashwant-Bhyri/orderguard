"""The frozen evaluation specification and its SHA-256.

``SPEC.md`` is the normative document; ``SPEC.sha256`` is the hash a lane's
report must quote.  ``spec_hash`` reads the file bytes, so it is stable across
runs and platforms.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().with_name("SPEC.md")
HASH_PATH = Path(__file__).resolve().with_name("SPEC.sha256")
_HEX = re.compile(r"^[0-9a-f]{64}$")


def spec_bytes() -> bytes:
    return SPEC_PATH.read_bytes()


def spec_hash() -> str:
    return hashlib.sha256(spec_bytes()).hexdigest()


def expected_hash() -> str | None:
    if not HASH_PATH.exists():
        return None
    value = HASH_PATH.read_text(encoding="utf-8").strip().split()[0]
    return value if _HEX.match(value) else None


def verify_spec() -> tuple[bool, str, str | None]:
    """Return ``(matches, actual, expected)``."""
    actual = spec_hash()
    expected = expected_hash()
    return (expected == actual, actual, expected)
