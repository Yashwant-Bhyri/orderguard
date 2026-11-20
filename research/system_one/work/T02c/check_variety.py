"""Sentence-repetition audit over every narrative string in the episode.

Counts a sentence once per episode (pooled) and once per episode within its
family, and fails if any sentence appears in more than 5% of episodes on
either denominator.
"""
from __future__ import annotations

import json
import re
import sys


def sentences(ep):
    out = []
    for d in ep["documents"]:
        out.extend(d["text"].split(". "))
    for n in ep["initial_notes"]:
        out.extend(n["text"].split(". "))
    for th in ep["theses"]:
        out.extend(th["statement"].split(". "))
        out.extend(th["invalidation"].split(". "))
    for s in ep["steps"]:
        out.extend(s["action"]["rationale"].split(". "))
        for c in s["action"]["claims"]:
            out.extend(c["text"].split(". "))
        for n in s["pre_notes"] + s["new_notes"]:
            out.extend(n["text"].split(". "))
    return [x.strip().rstrip(".") for x in out if x.strip()]


def _norm(s):
    return re.sub(r"\d+(?:[.,]\d+)?", "#", s)


def audit(path, limit=0.05):
    pooled = {}
    per_fam = {}
    pooled_n = {}
    per_fam_n = {}
    fam_n = {}
    n_eps = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            ep = json.loads(line)
            fam = ep["meta"]["family"]
            n_eps += 1
            fam_n[fam] = fam_n.get(fam, 0) + 1
            seen = set(sentences(ep))
            norm_seen = set(_norm(s) for s in seen)
            famd = per_fam.setdefault(fam, {})
            famnd = per_fam_n.setdefault(fam, {})
            for s in seen:
                pooled[s] = pooled.get(s, 0) + 1
                famd[s] = famd.get(s, 0) + 1
            for s in norm_seen:
                pooled_n[s] = pooled_n.get(s, 0) + 1
                famnd[s] = famnd.get(s, 0) + 1
    if not n_eps:
        print("no episodes")
        return 1
    top = sorted(pooled.items(), key=lambda kv: -kv[1])[:8]
    worst = top[0][1] / n_eps if top else 0.0
    topn = sorted(pooled_n.items(), key=lambda kv: -kv[1])[:5]
    worst_n = topn[0][1] / n_eps if topn else 0.0
    fam_worst = []
    for fam, counts in per_fam.items():
        if not counts:
            continue
        s, c = max(counts.items(), key=lambda kv: kv[1])
        fam_worst.append((c / fam_n[fam], s, fam))
    fam_worst.sort(reverse=True)
    print(f"sentence audit: {n_eps} episodes, {len(pooled)} distinct sentences")
    print("  denominators: pooled over all episodes; per-family over that family")
    print(f"  worst pooled exact-sentence share:    {worst:.3%} (limit {limit:.0%})")
    print(f"  worst pooled digit-normalised share:  {worst_n:.3%}")
    if fam_worst:
        w, s, fam = fam_worst[0]
        print(f"  worst per-family exact-sentence share: {w:.3%} in {fam} (limit {limit:.0%})")
    for s, c in top:
        print(f"  {c / n_eps:6.2%}  {s[:96]}")
    over_pooled = [(s, c) for s, c in pooled.items() if c / n_eps > limit]
    over_fam = [(s, fam, c, fam_n[fam]) for fam, counts in per_fam.items()
                for s, c in counts.items() if c / fam_n[fam] > limit]
    if over_pooled or over_fam:
        print(f"FAIL: {len(over_pooled)} sentence(s) exceed the pooled limit, "
              f"{len(over_fam)} exceed it inside one family")
        return 1
    print("sentence variety check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(audit(sys.argv[1] if len(sys.argv) > 1 else "out/episodes.jsonl"))
