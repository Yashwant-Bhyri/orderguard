"""Write the full red-team corpus to JSONL."""
from __future__ import annotations

import argparse
import json
import os

import generator


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/redteam.jsonl")
    ap.add_argument("--attack-n", type=int, default=65)
    ap.add_argument("--benign-n", type=int, default=20)
    args = ap.parse_args(argv)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    episodes = []
    for tech in generator.ATTACK_TECHNIQUES:
        for seed in range(args.attack_n):
            episodes.append(generator.generate(seed, tech))
    for tech in generator.BENIGN_TECHNIQUES:
        for seed in range(args.benign_n):
            episodes.append(generator.generate(seed, tech))

    with open(args.out, "w", encoding="utf-8") as fh:
        for ep in episodes:
            fh.write(json.dumps(ep, sort_keys=True, separators=(",", ":")))
            fh.write("\n")

    n_attacks = sum(1 for ep in episodes for s in ep["steps"]
                    if s["label"]["y"] == 1)
    n_benign_actions = sum(1 for ep in episodes for s in ep["steps"]
                           if s["label"]["y"] == 0)
    print(f"wrote {len(episodes)} episodes, {n_attacks} attack actions, "
          f"{n_benign_actions} clean actions to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
