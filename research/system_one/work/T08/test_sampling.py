#!/usr/bin/env python3
"""Tests for the fund-level flagged/clean sampling rules. Run: python test_sampling.py"""

import sys

from score import select_samples


def c(key, cat, share, core, robust=False):
    return {
        "series_key": key, "series_id": key, "series_name": key,
        "accession_number": "0000000000-26-000001", "category": cat,
        "share": share, "share_core": core, "net_assets_usd": 1.0,
        "filing_date": "2026-01-01", "cik": "1", "link": "x",
        "strong": True, "robust": robust,
    }


def main():
    candidates = [
        # A is flagged on equity, clean on bond. It must not enter clean.
        c("A", "equity", 0.50, 0.40, True),
        c("A", "bond", 0.90, 0.90),
        # B is clean in both; its row is the lower share (0.85).
        c("B", "equity", 0.85, 0.85),
        c("B", "bond", 0.95, 0.95),
        # C is a headline flag that is not robust. It belongs in flagged, not robust.
        c("C", "bond", 0.79, 0.90, False),
        # D is clean but close to the line.
        c("D", "municipal", 0.801, 0.801),
    ]
    s = select_samples(candidates, seed=7)
    bad = 0
    flagged_keys = {x["series_key"] for x in s["flagged"]}
    clean_keys = {x["series_key"] for x in s["clean"]}
    robust_keys = {x["series_key"] for x in s["robust"]}
    if flagged_keys != {"A", "C"}:
        bad += 1
        print("FAIL flagged frame:", sorted(flagged_keys))
    if clean_keys != {"B", "D"}:
        bad += 1
        print("FAIL clean frame must exclude any headline-flagged fund:", sorted(clean_keys))
    if robust_keys != {"A"}:
        bad += 1
        print("FAIL robust frame:", sorted(robust_keys))
    b = next(x for x in s["clean"] if x["series_key"] == "B")
    if b["share"] != 0.85:
        bad += 1
        print("FAIL clean row must be the fund's lowest strong share, got", b["share"])
    a = next(x for x in s["flagged"] if x["series_key"] == "A")
    if a["share"] != 0.50:
        bad += 1
        print("FAIL flagged row must be the fund's worst strong share, got", a["share"])
    rng = select_samples(candidates, seed=7)
    if [x["series_key"] for x in rng["flagged_sample"]] != [x["series_key"] for x in s["flagged_sample"]]:
        bad += 1
        print("FAIL sampler is not deterministic for a fixed seed")
    if bad:
        sys.exit(f"{bad} sampling failures")
    print("PASS sampling: fund-level clean, headline flagged frame, robust subset, fixed seed")


if __name__ == "__main__":
    main()
