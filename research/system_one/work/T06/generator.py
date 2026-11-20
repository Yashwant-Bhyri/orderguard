"""Deterministic red-team episode generator for OrderGuard System One.

Public API:
    generate(seed, technique) -> dict   # one Episode as a plain dict

The family modules live next to this file; ``TECHNIQUES`` lists every
technique understood by ``generate``.  Text variation is composed inside the
family modules by ``prose.py``; the generator never reads ``label.y`` or
``meta`` to decide what to build.
"""
from __future__ import annotations

import importlib

import common

ATTACK_TECHNIQUES = (
    "prompt_injection",
    "authority_spoof",
    "quote_laundering",
    "persuasive_framing",
    "evidence_flooding",
    "benign_camouflage",
    "vintage_passoff",
    "false_attribution",
)

BENIGN_TECHNIQUES = (
    "benign_signed_approval",
    "benign_exact_quote",
    "benign_enthusiastic_factual",
    "benign_correct_sell",
    "benign_legit_adaptation",
    "benign_many_sources",
    "benign_inert_instruction",
    "benign_scope_matched",
    "benign_large_add",
    "benign_multistep_rebalance",
    "benign_tech_rebalance",
)

TECHNIQUES = ATTACK_TECHNIQUES + BENIGN_TECHNIQUES

_MODULES = {
    "prompt_injection": "fam_prompt_injection",
    "authority_spoof": "fam_authority_spoof",
    "quote_laundering": "fam_quote_laundering",
    "persuasive_framing": "fam_persuasive_framing",
    "evidence_flooding": "fam_evidence_flooding",
    "benign_camouflage": "fam_camouflage",
    "vintage_passoff": "fam_vintage",
    "false_attribution": "fam_attribution",
    "benign_signed_approval": "fam_benign",
    "benign_exact_quote": "fam_benign",
    "benign_enthusiastic_factual": "fam_benign",
    "benign_correct_sell": "fam_benign",
    "benign_legit_adaptation": "fam_benign_more",
    "benign_many_sources": "fam_benign_more",
    "benign_inert_instruction": "fam_benign",
    "benign_scope_matched": "fam_benign",
    "benign_large_add": "fam_benign_more",
    "benign_multistep_rebalance": "fam_benign_more",
    "benign_tech_rebalance": "fam_benign_more",
}


def generate(seed: int, technique: str) -> dict:
    if technique not in _MODULES:
        raise KeyError(f"unknown technique {technique!r}")
    mod = importlib.import_module(_MODULES[technique])
    ep = mod.build(technique, int(seed))
    return common.finalize(ep)
