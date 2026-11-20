"""Verify that every emitted episode regenerates exactly from its seed.

Usage: python3 check_determinism.py out/redteam.jsonl
"""
from __future__ import annotations

import json
import sys

import generator


def technique_of(ep: dict) -> str:
    family = ep["meta"]["family"]
    if family in generator.ATTACK_TECHNIQUES:
        return family
    return ep["meta"]["benign_family"]


def main(path: str) -> int:
    checked = 0
    bad = 0
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        ep = json.loads(line)
        tech = technique_of(ep)
        again = generator.generate(ep["meta"]["seed"], tech)
        checked += 1
        if again != ep:
            bad += 1
            print(f"MISMATCH {tech} seed {ep['meta']['seed']}")
    print(f"determinism: {checked - bad}/{checked} episodes regenerate exactly")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "out/redteam.jsonl"))
