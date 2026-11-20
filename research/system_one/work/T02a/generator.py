"""Public entry point: generate(seed, family, shifted=False) -> Episode dict."""
from __future__ import annotations

import fam_clean
import fam_drift
import fam_unsupported
import fam_misquote
import fam_hype
import fam_poisoned
import fam_spoof
import fam_stale
import fam_liquidity
import fam_withdrawn

from og_s1.validate import validate as _validate_episode

FAMILIES = [
    "clean", "drift", "unsupported_claim", "misquote", "vague_hype",
    "poisoned_note", "authority_spoof", "stale_thesis",
    "liquidity_breach", "withdrawn_target",
]

MODULES = {
    "clean": fam_clean,
    "drift": fam_drift,
    "unsupported_claim": fam_unsupported,
    "misquote": fam_misquote,
    "vague_hype": fam_hype,
    "poisoned_note": fam_poisoned,
    "authority_spoof": fam_spoof,
    "stale_thesis": fam_stale,
    "liquidity_breach": fam_liquidity,
    "withdrawn_target": fam_withdrawn,
}


def generate(seed: int, family: str, shifted: bool = False) -> dict:
    if family not in MODULES:
        raise ValueError(f"unknown family {family!r}")
    # A rare book can leave no band-safe way to build the planted breach (or no
    # way to place the novel liquidity trade).  Retry with a derived internal
    # seed rather than emitting a malformed or unlabelled episode.  The result
    # stays deterministic for the requested seed, and meta.seed records the
    # seed the caller asked for.
    for attempt in range(16):
        inner = int(seed) if attempt == 0 else int(seed) + 1000003 * attempt
        try:
            ep = MODULES[family].generate(inner, bool(shifted))
        except RuntimeError:
            continue
        if _validate_episode(ep):
            continue
        pos = sum(st["label"]["y"] for st in ep["steps"])
        if not ((family == "clean" and pos == 0)
                or (family != "clean" and pos == 1)):
            continue
        book = ep["initial_book"]
        value = book["cash"] + sum(book["positions"].values())
        if any(st["action"]["notional"] < 0.005 * value for st in ep["steps"]):
            # A sub-0.5%-of-book trade is not a realistic proposal; retry with
            # a derived seed instead of emitting it.
            continue
        ep["meta"]["seed"] = int(seed)
        return ep
    raise RuntimeError(f"could not build a valid {family} episode for seed {seed}")
