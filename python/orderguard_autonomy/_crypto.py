"""Small shared helpers: canonical JSON, content hashes and Ed25519 signatures.

Keys made by `key_from_label` are SIMULATED keys derived from a public label so runs reproduce. They are not secrets and must never be
used outside simulation; a deployment loads its keys from its own key store.
"""
from __future__ import annotations

import base64
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical_json(obj) -> bytes:
    """Sorted keys, no whitespace, UTF-8. The one byte form every signature and hash in this package is taken over."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_hex(data: bytes | str | dict | list) -> str:
    if isinstance(data, (dict, list)):
        data = canonical_json(data)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def key_from_label(label: str) -> Ed25519PrivateKey:
    """A deterministic SIMULATED key from a public label (reproducible runs and tests only)."""
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(("orderguard-autonomy-sim:" + label).encode()).digest())


def public_b64(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    pub = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return base64.b64encode(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def sign_b64(key: Ed25519PrivateKey, payload) -> str:
    return base64.b64encode(key.sign(canonical_json(payload))).decode()


def verify_b64(public_key_b64: str, signature_b64: str, payload) -> bool:
    """True only for a well-formed key, a well-formed signature and a matching payload. Never raises."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        pub.verify(base64.b64decode(signature_b64, validate=True), canonical_json(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def flatten_sections(sections: dict[str, dict]) -> dict:
    """{"trading": {"max_order_usd": 1}} -> {"trading.max_order_usd": 1}. One level only: values inside a section are leaves."""
    return {f"{sec}.{k}": v for sec, body in sections.items() for k, v in (body or {}).items()}
