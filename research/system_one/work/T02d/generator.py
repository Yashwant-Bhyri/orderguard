"""Deterministic episode family router and dataset writer."""
import json
import hashlib
import random
import re
from collections import Counter, defaultdict

from fam_clean import build as clean
from fam_drift import build as drift
from fam_unsupported_claim import build as unsupported_claim
from fam_misquote import build as misquote
from fam_vague_hype import build as vague_hype
from fam_poisoned_note import build as poisoned_note
from fam_authority_spoof import build as authority_spoof
from fam_stale_thesis import build as stale_thesis
from fam_binding_error import build as binding_error
from fam_signed_restriction import build as signed_restriction_breach
from fam_embargo_breach import build as embargo_breach
import variety
from world import prune_theses, renumber_notes


FAMILIES = ("clean", "drift", "unsupported_claim", "misquote", "vague_hype", "poisoned_note",
            "authority_spoof", "stale_thesis", "binding_error", "signed_restriction_breach",
            "embargo_breach")
BUILDERS = {"clean": clean, "drift": drift, "unsupported_claim": unsupported_claim,
            "misquote": misquote, "vague_hype": vague_hype, "poisoned_note": poisoned_note,
            "authority_spoof": authority_spoof, "stale_thesis": stale_thesis,
            "binding_error": binding_error,
            "signed_restriction_breach": signed_restriction_breach,
            "embargo_breach": embargo_breach}


def generate(seed: int, family: str, shifted: bool = False) -> dict:
    try:
        builder = BUILDERS[family]
    except KeyError as exc:
        raise ValueError(f"unknown or not-yet-implemented family: {family}") from exc
    episode = builder(seed, shifted)
    prune_theses(episode)
    episode = variety.apply(episode, seed, family, shifted)
    return renumber_notes(episode)


def _episode_texts(episode):
    texts = [doc["text"] for doc in episode["documents"]]
    texts += [note["text"] for note in episode["initial_notes"]]
    for step in episode["steps"]:
        texts += [note["text"] for note in step["pre_notes"] + step["new_notes"]]
        texts.append(step["action"]["rationale"])
        texts += [claim["text"] for claim in step["action"]["claims"]]
    for thesis in episode["theses"]:
        texts.extend((thesis["statement"], thesis["invalidation"]))
    return texts


def write_dataset(path, per_family=150):
    sentence_episodes = defaultdict(set)
    punct_episodes = defaultdict(set)
    episodes = []
    stats = {family: {"episodes": 0, "shifted": 0, "actions": 0, "positives": 0}
             for family in FAMILIES}
    positive_positions = {family: Counter() for family in FAMILIES}
    step_positives = Counter()
    for family in FAMILIES:
        for seed in range(per_family):
            is_shifted = seed % 5 == 0
            episode = generate(seed, family, shifted=is_shifted)
            episodes.append(episode)
            row = stats[family]
            row["episodes"] += 1
            row["shifted"] += int(is_shifted)
            row["actions"] += len(episode["steps"])
            for index, step in enumerate(episode["steps"]):
                row["positives"] += step["label"]["y"]
                step_positives[index] += step["label"]["y"]
                positive_positions[family][index] += step["label"]["y"]

    # Stable interleaving prevents family-block order from becoming a corpus cue.
    random.Random(0xA11CE).shuffle(episodes)
    with open(path, "w", encoding="utf-8") as fh:
        for episode in episodes:
            fh.write(json.dumps(episode, ensure_ascii=False, separators=(",", ":")) + "\n")

    episode_number = len(episodes)
    for episode_id, episode in enumerate(episodes):
        for text in _episode_texts(episode):
            for sentence in text.split(". "):
                sentence = sentence.strip()
                if sentence:
                    sentence_episodes[sentence].add(episode_id)
            for sentence in re.split(r"(?<=[.!?])\s+", text):
                sentence = sentence.strip()
                if sentence:
                    punct_episodes[sentence].add(episode_id)

    total_actions = sum(row["actions"] for row in stats.values())
    total_positives = sum(row["positives"] for row in stats.values())
    for family in FAMILIES:
        row = stats[family]
        rate = row["positives"] / row["actions"] if row["actions"] else 0.0
        print(f"{family}: episodes={row['episodes']} shifted={row['shifted']} actions={row['actions']} "
              f"positives={row['positives']} label_rate={rate:.3f}")
        steps_per_episode = row["actions"] // row["episodes"] if row["episodes"] else 0
        pos_list = [positive_positions[family][i] for i in range(steps_per_episode)]
        print(f"positive_positions[{family}]={pos_list}")
    overall_rate = total_positives / total_actions if total_actions else 0.0
    print(f"total: episodes={episode_number} actions={total_actions} positives={total_positives} "
          f"label_rate={overall_rate:.3%}")
    max_index = max(step_positives, default=-1)
    print(f"positive_step_counts={ {i: step_positives[i] for i in range(max_index + 1)} }")
    family_sequence = [episode["meta"]["family"] for episode in episodes]
    max_family_run = 0
    run_length = 0
    previous = None
    for family in family_sequence:
        run_length = run_length + 1 if family == previous else 1
        max_family_run = max(max_family_run, run_length)
        previous = family
    print(f"corpus_order: max_consecutive_same_family={max_family_run}")
    for name, table in (("sentence audit", sentence_episodes), ("punctuation audit", punct_episodes)):
        max_reuse = max((len(ids) for ids in table.values()), default=0)
        over_limit = sum(len(ids) > episode_number * 0.05 for ids in table.values())
        rate = max_reuse / episode_number if episode_number else 0.0
        print(f"{name}: episodes={episode_number} distinct_sentences={len(table)} "
              f"maximum_reuse={max_reuse} max_rate={rate:.3%} over_5pct={over_limit}")
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print(f"dataset_sha256={digest}")


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "out/episodes.jsonl"
    write_dataset(target, int(sys.argv[2]) if len(sys.argv) > 2 else 150)
