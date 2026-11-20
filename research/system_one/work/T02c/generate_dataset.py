"""Write N episodes per family to JSONL and print per-family label rates."""
from __future__ import annotations

import argparse
import json

import generator


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--out", default="out/episodes.jsonl")
    ap.add_argument("--shifted-every", type=int, default=7,
                    help="make every k-th seed a shifted variant (0 disables)")
    args = ap.parse_args()
    counts = {}
    positives = {}
    total_actions = {}
    shifted_eps = 0
    with open(args.out, "w", encoding="utf-8") as fh:
        for fi, family in enumerate(generator.FAMILIES):
            counts[family] = 0
            positives[family] = 0
            total_actions[family] = 0
            for i in range(args.n):
                shifted = bool(args.shifted_every) and (i % args.shifted_every == args.shifted_every - 1)
                ep = generator.generate(1000 + i * 17 + fi * 97, family, shifted)
                fh.write(json.dumps(ep, ensure_ascii=False) + "\n")
                counts[family] += 1
                shifted_eps += int(shifted)
                for s in ep["steps"]:
                    total_actions[family] += 1
                    positives[family] += int(s["label"]["y"] == 1)
    print(f"wrote {sum(counts.values())} episodes ({shifted_eps} shifted) to {args.out}")
    print(f"{'family':<22}{'episodes':>9}{'actions':>9}{'positives':>11}{'rate':>8}")
    for family in generator.FAMILIES:
        rate = positives[family] / max(1, total_actions[family])
        print(f"{family:<22}{counts[family]:>9}{total_actions[family]:>9}"
              f"{positives[family]:>11}{rate:>7.1%}")
    bad = [f for f in generator.FAMILIES if f != "clean" and not (0.05 <= positives[f] / max(1, total_actions[f]) <= 0.60)]
    if positives.get("clean", 0) != 0:
        bad.append("clean")
    print("label-rate check:", "FAIL " + ",".join(bad) if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
