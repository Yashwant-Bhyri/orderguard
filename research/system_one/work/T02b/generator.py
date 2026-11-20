"""OrderGuard System One world generator.

Deterministic per (seed, family, shifted). Only the standard library is used.
"""
from __future__ import annotations

import importlib
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

FAMILIES = [
    "clean",
    "drift",
    "unsupported_claim",
    "misquote",
    "vague_hype",
    "poisoned_note",
    "authority_spoof",
    "stale_thesis",
    "evidence_inversion",
    "model_risk_ignored",
]

_MODULES = {
    "clean": "fam_clean",
    "drift": "fam_drift",
    "unsupported_claim": "fam_unsupported",
    "misquote": "fam_misquote",
    "vague_hype": "fam_vague",
    "poisoned_note": "fam_poisoned",
    "authority_spoof": "fam_authority",
    "stale_thesis": "fam_stale",
    "evidence_inversion": "fam_evidence",
    "model_risk_ignored": "fam_modelrisk",
}


def generate(seed: int, family: str, shifted: bool = False) -> dict:
    """Return one Episode dict for ``family`` at ``seed``."""
    if family not in _MODULES:
        raise ValueError(f"unknown family {family!r}")
    module = importlib.import_module(_MODULES[family])
    return module.generate(int(seed), shifted)


def all_families():
    return list(FAMILIES)
