"""Arbitrary-seed sweep + a REAL cross-process determinism check.

1. generate(seed, family, shifted) must validate for any seed, not just the 150
   written to the corpus: sweeps seeds 0..9999 for every family with both
   shifted values (220,000 episodes).
2. Determinism is checked across processes, not by two identical calls in one
   process: a sample of episodes is serialised and hashed here, then regenerated
   in a FRESH subprocess (new interpreter, new RNG state) and hashed again. The
   two hash sets must match. This catches a stateful global RNG or any
   cross-process nondeterminism that a same-call comparison cannot.

Exits non-zero on any validator error or determinism mismatch.
"""
import hashlib
import json
import subprocess
import sys

from generator import FAMILIES, generate
from og_s1.validate import validate

SAMPLE_SEEDS = (0, 7, 149, 2882, 5454, 17654, 18974, 19150, 9999,
                4873, 12005, 12537, 14665, 18145)


def _hash(ep):
    return hashlib.sha256(json.dumps(ep, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sample_hashes():
    rows = []
    for family in FAMILIES:
        for seed in SAMPLE_SEEDS:
            for shifted in (False, True):
                rows.append(f"{family} {seed} {int(shifted)} {_hash(generate(seed, family, shifted))}")
    return rows


def hash_sample_mode():
    for row in sample_hashes():
        print(row)
    return 0


def main():
    errors = 0
    checked = 0
    for family in FAMILIES:
        for seed in range(10000):
            for shifted in (False, True):
                ep = generate(seed, family, shifted)
                errs = validate(ep)
                checked += 1
                if errs:
                    errors += 1
                    if errors <= 20:
                        print(f"SWEEP FAIL {family} seed={seed} shifted={shifted}: {errs[:3]}")

    # Cross-process determinism: hash here, then in a fresh subprocess.
    here = sample_hashes()
    proc = subprocess.run([sys.executable, "-B", __file__, "--hash-sample"],
                          capture_output=True, text=True)
    there = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    mismatches = 0
    if proc.returncode != 0 or len(there) != len(here):
        mismatches = len(here)
        print(f"DETERMINISM FAIL: subprocess rc={proc.returncode} lines={len(there)} expected={len(here)}")
        if proc.stderr:
            print(proc.stderr[:500])
    else:
        for a, b in zip(here, there):
            if a != b:
                mismatches += 1
                if mismatches <= 10:
                    print(f"DETERMINISM FAIL: {a.split()[0]} seed={a.split()[1]} shifted={a.split()[2]}")
    errors += mismatches
    print(f"seed sweep: episodes={checked} validator_errors={errors - mismatches}")
    print(f"determinism: cross_process_sample={len(here)} mismatches={mismatches}")
    return 1 if errors else 0


if __name__ == "__main__":
    if "--hash-sample" in sys.argv:
        sys.exit(hash_sample_mode())
    sys.exit(main())
