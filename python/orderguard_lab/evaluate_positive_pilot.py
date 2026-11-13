"""Confirm positive mandate forecasts that use short, policy-specific simulator runs."""
from __future__ import annotations

import argparse
import random
from pathlib import Path

from .evaluate_signed_policy_ranking import generate_holdout
from .evaluate_varied_policy_warnings import simulate_varied_group

HOLDOUT_SEEDS = tuple(random.Random(90624311).sample(range(10_000, 2**32), 160))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if not args.generate or args.workers < 1:
        parser.error("Use --generate and at least one worker.")
    args.directory.mkdir(parents=True, exist_ok=True)
    generate_holdout(args.directory / "holdout.jsonl.gz", args.workers, seeds=HOLDOUT_SEEDS, simulator=simulate_varied_group)


if __name__ == "__main__":
    main()
