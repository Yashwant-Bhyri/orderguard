"""Reproducible out-of-sample probe for the generated world.

Generates ``--n`` seeds (0..n-1) for every family, both ``shifted`` values,
validates each episode in memory and checks the structural invariants the
REPORT relies on. Prints a summary and exits non-zero on any violation.

Usage: python probe.py --n 1000
"""
from __future__ import annotations

import argparse

import generator
from og_s1.validate import validate


def _replay_check(ep, cause):
    """Return True if the planted failure really breaches the stated limit."""
    book = ep["initial_book"]
    isec = ep["instrument_sectors"]
    total = book["cash"] + sum(book["positions"].values())
    pos = {k: float(v) for k, v in book["positions"].items()}
    bands = ep["owner"]["sector_bands"]
    maxpos = ep["owner"]["max_position_pct"]
    ok = True
    for s in ep["steps"]:
        a = s["action"]
        n = float(a["notional"])
        inst, sec = a["instrument"], a["sector"]
        if a["side"] == "buy":
            pos[inst] = pos.get(inst, 0.0) + n
        else:
            pos[inst] = pos.get(inst, 0.0) - n
        if s["label"]["y"] != 1 or s["label"]["cause"] != cause:
            continue
        sec_w = sum(v for k, v in pos.items() if isec.get(k) == sec) / total
        inst_w = pos.get(inst, 0.0) / total
        if cause in ("drift", "authority_spoof", "wrong_mandate_scope"):
            ok = ok and sec_w > bands[sec]["max"] + 1e-6
        elif cause == "poisoned_note":
            ok = ok and inst_w > maxpos + 1e-6
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000,
                    help="seeds per family per shifted value (0..n-1)")
    args = ap.parse_args()
    invalid = 0
    clean_pos = 0
    zero_pos = 0
    max_pos = 0
    max_steps = 0
    breach_viol = 0
    total = 0
    for family in generator.FAMILIES:
        for shifted in (False, True):
            for seed in range(args.n):
                ep = generator.generate(seed, family, shifted)
                total += 1
                if validate(ep):
                    invalid += 1
                ys = [s["label"]["y"] for s in ep["steps"]]
                pos = sum(ys)
                max_pos = max(max_pos, pos)
                max_steps = max(max_steps, len(ep["steps"]))
                if family == "clean" and pos:
                    clean_pos += 1
                if family != "clean" and pos == 0:
                    zero_pos += 1
                if family in ("drift", "poisoned_note", "authority_spoof",
                              "wrong_mandate_scope") and pos:
                    if not _replay_check(ep, family):
                        breach_viol += 1
    print(f"probe: {total} episodes (seeds 0-{args.n - 1}, all families, both shifted)")
    print(f"  invalid: {invalid}")
    print(f"  clean episodes with a positive: {clean_pos}")
    print(f"  failure episodes with zero positives: {zero_pos}")
    print(f"  max positives in one episode: {max_pos}")
    print(f"  max steps in one episode: {max_steps}")
    print(f"  limit-breach replay failures: {breach_viol}")
    bad = invalid or clean_pos or zero_pos or breach_viol
    print("probe:", "FAIL" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
