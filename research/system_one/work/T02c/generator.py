"""OrderGuard System One world generator.

``generate(seed, family, shifted=False)`` returns one Episode dict that passes
``og_s1.validate``.  Deterministic for a given seed; only the standard library
is used.
"""
from __future__ import annotations

import fam_clean
import fam_drift
import fam_unsupported
import fam_misquote
import fam_vague
import fam_poisoned
import fam_spoof
import fam_stale
import fam_superseded
import fam_scope

_MODULES = {
    "clean": fam_clean,
    "drift": fam_drift,
    "unsupported_claim": fam_unsupported,
    "misquote": fam_misquote,
    "vague_hype": fam_vague,
    "poisoned_note": fam_poisoned,
    "authority_spoof": fam_spoof,
    "stale_thesis": fam_stale,
    "superseded_source": fam_superseded,
    "wrong_mandate_scope": fam_scope,
}

FAMILIES = [
    "clean",
    "drift",
    "unsupported_claim",
    "misquote",
    "vague_hype",
    "poisoned_note",
    "authority_spoof",
    "stale_thesis",
    "superseded_source",
    "wrong_mandate_scope",
]

NOVEL_CAUSES = ["superseded_source", "wrong_mandate_scope"]


def generate(seed: int, family: str, shifted: bool = False) -> dict:
    mod = _MODULES.get(family)
    if mod is None:
        raise ValueError(f"unknown family: {family}")
    return mod.generate(seed, shifted)
