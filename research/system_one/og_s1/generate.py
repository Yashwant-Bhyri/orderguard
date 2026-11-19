"""Generate the reference dataset and print statistics.

``python -m og_s1.generate --out data/ref --n-per-family 200`` writes, for each
family, ``<family>.jsonl`` (unshifted) and ``<family>.shifted.jsonl``, then
prints counts, per-family label rates, the sentence repeat rate and throughput.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from .world import FAMILIES, _World, simulate


def _sentences(text):
    return [p for p in text.split(". ") if p.strip()]


def generate(n_per_family, n_steps, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    total_episodes = 0
    start = time.time()
    stats = {}
    all_sentences = []

    for fi, family in enumerate(FAMILIES):
        for shifted in (False, True):
            path = out / (f"{family}.shifted.jsonl" if shifted else f"{family}.jsonl")
            n_actions = 0
            n_pos = 0
            n_pos_buy = 0
            n_pos_sell = 0
            min_episode_positives = None
            n_pre_onset = 0
            with open(path, "w", encoding="utf-8") as fh:
                for i in range(n_per_family):
                    seed = fi * 1000 + i
                    ep = simulate(seed, family, n_steps=n_steps, shifted=shifted)
                    fh.write(json.dumps(ep.to_dict()) + "\n")
                    n_actions += len(ep.steps)
                    ep_pos = [s for s in ep.steps if s.label.y == 1]
                    n_pos += len(ep_pos)
                    n_pos_buy += sum(1 for s in ep_pos if s.action.side == "buy")
                    n_pos_sell += sum(1 for s in ep_pos if s.action.side == "sell")
                    if min_episode_positives is None:
                        min_episode_positives = len(ep_pos)
                    else:
                        min_episode_positives = min(min_episode_positives, len(ep_pos))
                    if family != "clean":
                        onset = _World(seed, family, n_steps, shifted).onset
                        n_pre_onset += sum(
                            1 for s in ep_pos
                            if s.action.t < onset)
                    for d in ep.documents:
                        all_sentences.extend(_sentences(d.text))
                    for n in ep.initial_notes:
                        all_sentences.extend(_sentences(n.text))
                    for s in ep.steps:
                        for n in s.pre_notes:
                            all_sentences.extend(_sentences(n.text))
                        for n in s.new_notes:
                            all_sentences.extend(_sentences(n.text))
                    total_episodes += 1
            key = f"{family}{'.shifted' if shifted else ''}"
            stats[key] = {
                "episodes": n_per_family,
                "actions": n_actions,
                "positives": n_pos,
                "positive_buys": n_pos_buy,
                "positive_sells": n_pos_sell,
                "min_episode_positives": min_episode_positives or 0,
                "label_rate": n_pos / n_actions if n_actions else 0.0,
                "pre_onset_positives": n_pre_onset,
            }

    elapsed = time.time() - start
    eps_per_sec = total_episodes / elapsed if elapsed else 0.0

    counts = Counter(all_sentences)
    total_sentences = len(all_sentences)
    duplicate_sentences = sum(1 for s in all_sentences if counts[s] > 1)
    repeat_rate = duplicate_sentences / total_sentences if total_sentences else 0.0

    return {
        "stats": stats,
        "total_episodes": total_episodes,
        "total_sentences": total_sentences,
        "duplicate_sentences": duplicate_sentences,
        "repeat_rate": repeat_rate,
        "elapsed_seconds": elapsed,
        "episodes_per_second": eps_per_sec,
    }


def _print(results):
    print("== counts ==")
    for fam in FAMILIES:
        for suffix in ("", ".shifted"):
            key = fam + suffix
            s = results["stats"][key]
            print(f"{key:24s} episodes={s['episodes']:4d} actions={s['actions']:6d} "
                  f"positives={s['positives']:5d} label_rate={s['label_rate']:.4f} "
                  f"pos_buys={s['positive_buys']:5d} pos_sells={s['positive_sells']:5d} "
                  f"min_episode_positives={s['min_episode_positives']:3d} "
                  f"pre_onset_positives={s['pre_onset_positives']}")
    print("== repeat rate ==")
    print(f"total_sentences={results['total_sentences']} "
          f"duplicate_sentences={results['duplicate_sentences']} "
          f"repeat_rate={results['repeat_rate']:.4f}")
    print("== throughput ==")
    print(f"episodes={results['total_episodes']} elapsed={results['elapsed_seconds']:.2f}s "
          f"episodes_per_second={results['episodes_per_second']:.2f}")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/ref")
    p.add_argument("--n-per-family", type=int, default=200)
    p.add_argument("--n-steps", type=int, default=120)
    a = p.parse_args(args)
    results = generate(a.n_per_family, a.n_steps, a.out)
    _print(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
