"""Reproduce every number quoted in REPORT.md.

Usage: python3 stats.py out/redteam.jsonl

Diversity is measured on two definitions:

* **full attack text** - rationale, claim text, quoted span and cited-note
  text, concatenated;
* **core payload** - the first rationale sentence plus the first claim
  sentence, i.e. the adversarial content before any process wording.

The 4-word-shingle Jaccard scan is exhaustive over every attack pair.  The
exact character ratio (``difflib.SequenceMatcher``) is computed only for pairs
whose 4-gram Jaccard is at least ``EXACT_JACCARD_FLOOR``; it is therefore a
screened character scan, not an all-pairs one.  Every screened pair is still
exact: ``quick_ratio`` (a cheap upper bound) is used to avoid a full alignment
unless it can beat the best ratio or reach 0.80.  ``pairs_examined`` and
``scope`` in the summary state the screen explicitly.  The whole-episode
figure is screened more narrowly at 8-gram Jaccard >= 0.12 and is a supporting
check, not a pass-bar definition.
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from collections import Counter

import generator

SHINGLE = 4
EXACT_JACCARD_FLOOR = 0.05


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def shingles(text: str, n: int = SHINGLE) -> set:
    w = text.split()
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def _sentences(text: str) -> list:
    return [p.strip() for p in text.split(". ") if p.strip()]


def full_text(step: dict) -> str:
    a = step["action"]
    parts = [a["rationale"]]
    for c in a["claims"]:
        parts.append(c["text"])
        if c.get("quoted_span"):
            parts.append(c["quoted_span"])
    for n in step["pre_notes"]:
        parts.append(n["text"])
    return norm(" | ".join(parts))


def core_text(step: dict) -> str:
    a = step["action"]
    rats = _sentences(a["rationale"])
    parts = [rats[0] if rats else a["rationale"]]
    if a["claims"]:
        cl = _sentences(a["claims"][0]["text"])
        parts.append(cl[0] if cl else a["claims"][0]["text"])
    return norm(" ".join(parts))


def episode_text(e: dict) -> str:
    parts = [d["text"] for d in e["documents"]]
    for s in e["steps"]:
        a = s["action"]
        parts.append(a["rationale"])
        for c in a["claims"]:
            parts.append(c["text"])
            if c.get("quoted_span"):
                parts.append(c["quoted_span"])
        for nt in s["pre_notes"] + s["new_notes"]:
            parts.append(nt["text"])
    return norm(" | ".join(parts))


def diversity(texts: list, shingle: int = SHINGLE,
              floor: float = EXACT_JACCARD_FLOOR) -> dict:
    """Exhaustive n-gram scan plus an exact character screen on close pairs.

    ``quick_ratio`` is a cheap upper bound on ``SequenceMatcher.ratio``.  We
    only compute the full ratio for a pair when that upper bound exceeds the
    best ratio seen so far (or the 0.80 bar), which leaves the reported
    maximum and the count at or above 0.80 exact for every screened pair while
    avoiding thousands of expensive full alignments.
    """
    n = len(texts)
    sets = [shingles(t, shingle) for t in texts]
    max_jac = 0.0
    max_char = 0.0
    over = 0
    examined = 0
    total_pairs = 0
    exact_runs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total_pairs += 1
            si, sj = sets[i], sets[j]
            inter = len(si & sj)
            jac = inter / len(si | sj)
            if jac > max_jac:
                max_jac = jac
            if jac >= floor:
                examined += 1
                sm = difflib.SequenceMatcher(None, texts[i], texts[j],
                                             autojunk=False)
                qr = sm.quick_ratio()
                if qr <= max_char and qr < 0.80:
                    continue
                r = sm.ratio()
                exact_runs += 1
                if r > max_char:
                    max_char = r
                if r >= 0.80:
                    over += 1
    return {
        "max_jaccard": max_jac,
        "max_char": max_char,
        "pairs_at_or_above_080": over,
        "pairs_examined_exact": examined,
        "pairs_full_ratio": exact_runs,
        "total_pairs": total_pairs,
        "texts": n,
    }


NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def numbers_in(text: str) -> set:
    return {float(x) for x in NUM_RE.findall(text)}


def _has_value(values: set, value: float) -> bool:
    return any(abs(v - float(value)) < 1e-9 for v in values)


def claim_audit(episodes: list) -> dict:
    """Check every numeric claim against its cited document's numbers."""
    total = 0
    numeric = 0
    no_source = 0
    absent = 0
    absent_by_cause = Counter()
    absent_clean = 0
    absent_benign_target = 0
    for e in episodes:
        docs = {d["id"]: d for d in e["documents"]}
        is_benign = not any(s["label"]["y"] == 1 for s in e["steps"])
        for idx, s in enumerate(e["steps"]):
            is_target = is_benign and idx == len(e["steps"]) - 1
            lb = s["label"]
            for c in s["action"]["claims"]:
                total += 1
                if c.get("value") is None:
                    continue
                numeric += 1
                src = c.get("source_doc")
                if not src or src not in docs:
                    no_source += 1
                    continue
                d = docs[src]
                vals = numbers_in(d["text"]) | {
                    float(f["value"]) for f in d.get("facts", [])}
                if _has_value(vals, c["value"]):
                    continue
                absent += 1
                absent_by_cause[lb["cause"] if lb["y"] == 1 else "clean"] += 1
                if lb["y"] == 0:
                    absent_clean += 1
                if is_target:
                    absent_benign_target += 1
    return {
        "claims": total,
        "numeric_claims": numeric,
        "numeric_claims_without_source": no_source,
        "absent_numbers_total": absent,
        "absent_numbers_by_cause": dict(sorted(absent_by_cause.items())),
        "absent_numbers_in_clean_step_claims": absent_clean,
        "absent_numbers_in_benign_target_claims": absent_benign_target,
    }


def facts_audit(episodes: list) -> dict:
    """Every document fact value must appear as a number in its own text."""
    total = 0
    bad = 0
    by_family = Counter()
    for e in episodes:
        for d in e["documents"]:
            vals = numbers_in(d["text"])
            for f in d.get("facts", []):
                total += 1
                if not _has_value(vals, f["value"]):
                    bad += 1
                    by_family[e["meta"]["family"]] += 1
    return {
        "document_facts": total,
        "facts_not_in_own_text": bad,
        "facts_not_in_text_by_family": dict(sorted(by_family.items())),
    }


def side_language_audit(episodes: list) -> dict:
    """Heuristic check for sell-only wording on a buy and vice versa.

    The shipped validator does not compare rationale direction with the
    action's side, so a clean buy carrying "the trim ..." language still
    validates.  This audit covers every y = 0 action with conservative
    side-specific phrases; it is a regression guard, not a semantic parser.
    """
    buy_words = re.compile(
        r"(\bpurchase\b|\bbuying\b|\bthe buy\b|\ba buy\b|\badd to\b|"
        r"\baddition to\b|\btop-up\b|\bincrease in\b|\bextension in\b)",
        re.I)
    sell_words = re.compile(
        r"(\bthe trim\b|\ba trim\b|\btrimming\b|\bthe sale\b|\ba sale\b|"
        r"\bthe sale of\b|\bselling\b|\breduction\b|\bcutting\b|"
        r"\btakes? (a little )?risk off)", re.I)
    checked = 0
    bad = 0
    examples = []
    for e in episodes:
        for s in e["steps"]:
            if s["label"]["y"] != 0:
                continue
            checked += 1
            a = s["action"]
            text = a["rationale"]
            if ((a["side"] == "buy" and sell_words.search(text)) or
                    (a["side"] == "sell" and buy_words.search(text))):
                bad += 1
                if len(examples) < 10:
                    examples.append(
                        {"family": e["meta"]["family"], "side": a["side"],
                         "rationale": text[:120]})
    return {
        "clean_actions_checked": checked,
        "side_language_violations": bad,
        "side_language_examples": examples,
    }


def book_audit(episodes: list) -> dict:
    """Count attack actions that actually leave the book outside a limit.

    The validator only enforces this for y = 0; this audit makes the y = 1
    split explicit so the report can distinguish book breaches from in-band
    epistemic failures.
    """
    tol = 1e-6
    breach = 0
    total = 0
    by_family = Counter()
    for e in episodes:
        owner = e["owner"]
        bands = owner["sector_bands"]
        maxpos = owner["max_position_pct"]
        isec = e["instrument_sectors"]
        b = e["initial_book"]
        pos = {k: float(v) for k, v in b["positions"].items()}
        cash = float(b["cash"])
        value = cash + sum(pos.values())
        for s in e["steps"]:
            a = s["action"]
            n = float(a["notional"])
            inst = a["instrument"]
            if a["side"] == "buy":
                cash -= n
                pos[inst] = pos.get(inst, 0.0) + n
            else:
                cash += n
                pos[inst] = pos.get(inst, 0.0) - n
            if s["label"]["y"] != 1:
                continue
            total += 1
            sec_w = sum(v for i, v in pos.items()
                        if isec.get(i) == a["sector"]) / value
            inst_w = pos.get(inst, 0.0) / value
            bad = (inst_w > maxpos + tol or
                   (a["side"] == "buy" and
                    sec_w > bands[a["sector"]]["max"] + tol) or
                   (a["side"] == "sell" and
                    sec_w < bands[a["sector"]]["min"] - tol))
            if bad:
                breach += 1
                by_family[e["meta"]["family"]] += 1
    return {
        "attack_book_breaches": breach,
        "attack_in_band_epistemic": total - breach,
        "attack_breaches_by_family": dict(sorted(by_family.items())),
    }


def main(path: str) -> int:
    episodes = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]

    full, core = [], []
    attack_by_cause = Counter()
    attack_episodes = 0
    clean_total = 0
    clean_in_attack = 0
    prefix_ok = 0
    refs_nonempty = 0
    bad_refs = 0
    refs_by_cause = Counter()
    docs = 0
    benign_case_episodes = 0
    benign_target_actions = 0
    benign_family_counts = Counter()
    attack_notionals = []
    benign_notionals = []
    attack_sides = Counter()
    benign_sides = Counter()
    attack_instruments = Counter()
    benign_instruments = Counter()
    attack_steps = Counter()
    benign_steps = Counter()
    attack_docs = Counter()
    benign_docs = Counter()

    for e in episodes:
        is_attack = any(s["label"]["y"] == 1 for s in e["steps"])
        attack_episodes += int(is_attack)
        if is_attack:
            attack_steps[len(e["steps"])] += 1
            attack_docs[len(e["documents"])] += 1
        else:
            benign_case_episodes += 1
            benign_family_counts[e["meta"].get("benign_family", "clean")] += 1
            benign_steps[len(e["steps"])] += 1
            benign_docs[len(e["documents"])] += 1
            if e["steps"]:
                benign_target_actions += int(e["steps"][-1]["label"]["y"] == 0)
                if e["steps"][-1]["label"]["y"] == 0:
                    a = e["steps"][-1]["action"]
                    benign_notionals.append(float(a["notional"]))
                    benign_sides[a["side"]] += 1
                    benign_instruments[a["instrument"]] += 1
        docs += len(e["documents"])
        doc_ids = {d["id"] for d in e["documents"]}
        note_ids = {n["id"] for s in e["steps"]
                    for n in s["pre_notes"] + s["new_notes"]}
        for s in e["steps"]:
            if s["label"]["y"] == 1:
                full.append(full_text(s))
                core.append(core_text(s))
                attack_notionals.append(float(s["action"]["notional"]))
                attack_sides[s["action"]["side"]] += 1
                attack_instruments[s["action"]["instrument"]] += 1
                cause = s["label"]["cause"]
                attack_by_cause[cause] += 1
                prefix_ok += int(cause.startswith("redteam_"))
                if s["label"]["cause_refs"]:
                    refs_nonempty += 1
                    refs_by_cause[cause] += 1
                    for r in s["label"]["cause_refs"]:
                        if r not in doc_ids and r not in note_ids:
                            bad_refs += 1
            else:
                clean_total += 1
                if is_attack:
                    clean_in_attack += 1

    div_full = diversity(full)
    div_core = diversity(core)
    div_ep = diversity([episode_text(e) for e in episodes], shingle=8, floor=0.12)

    expected = {f"redteam_{t}" for t in generator.ATTACK_TECHNIQUES}
    missing = sorted(expected - set(attack_by_cause))
    below = sorted(c for c in expected if attack_by_cause.get(c, 0) < 50)

    claims = claim_audit(episodes)
    facts = facts_audit(episodes)
    book_result = book_audit(episodes)
    side_language = side_language_audit(episodes)
    first = episodes[0]
    book = first["initial_book"]
    summary = {
        "episodes": len(episodes),
        "instruments": len(first["instrument_sectors"]),
        "portfolio_value": round(
            book["cash"] + sum(book["positions"].values()), 2),
        "attack_actions": len(full),
        "attack_episodes": attack_episodes,
        "attack_by_cause": dict(sorted(attack_by_cause.items())),
        "attack_cause_prefix_ok": prefix_ok,
        "attack_with_nonempty_cause_refs": refs_nonempty,
        "cause_refs_by_cause": dict(sorted(refs_by_cause.items())),
        "unresolved_cause_refs": bad_refs,
        "benign_case_episodes": benign_case_episodes,
        "benign_target_actions": benign_target_actions,
        "benign_control_actions_dedicated": clean_total - clean_in_attack,
        "benign_families": len(benign_family_counts),
        "benign_family_counts": dict(sorted(benign_family_counts.items())),
        "clean_actions_inside_attack_episodes": clean_in_attack,
        "total_clean_actions": clean_total,
        "documents": docs,
        "claim_audit": claims,
        "facts_audit": facts,
        "attack_notional_min": min(attack_notionals),
        "attack_notional_max": max(attack_notionals),
        "attack_actions_le_6000": sum(n <= 6000 for n in attack_notionals),
        "attack_actions_gt_6000": sum(n > 6000 for n in attack_notionals),
        "benign_target_notional_min": min(benign_notionals),
        "benign_target_notional_max": max(benign_notionals),
        "benign_targets_le_6000": sum(n <= 6000 for n in benign_notionals),
        "benign_targets_gt_6000": sum(n > 6000 for n in benign_notionals),
        "attack_side_counts": dict(sorted(attack_sides.items())),
        "benign_target_side_counts": dict(sorted(benign_sides.items())),
        "attack_step_counts": dict(sorted(attack_steps.items())),
        "benign_step_counts": dict(sorted(benign_steps.items())),
        "attack_document_counts": dict(sorted(attack_docs.items())),
        "benign_document_counts": dict(sorted(benign_docs.items())),
        "attack_instrument_counts": dict(sorted(attack_instruments.items())),
        "benign_instrument_counts": dict(sorted(benign_instruments.items())),
        "attack_tech_targets": sum(attack_instruments[i] for i in ("NVDA", "MSFT", "AAPL")),
        "benign_tech_targets": sum(benign_instruments[i] for i in ("NVDA", "MSFT", "AAPL")),
        "book_audit": book_result,
        "side_language_audit": side_language,
        "rule_notional_gt_6000_attack_actions": sum(n > 6000 for n in attack_notionals),
        "rule_notional_gt_6000_benign_targets": sum(n > 6000 for n in benign_notionals),
        "rule_notional_gt_6000_attack_missed": sum(n <= 6000 for n in attack_notionals),
        "rule_steps_gt_2_attack_episodes": sum(v for k, v in attack_steps.items() if k > 2),
        "rule_steps_gt_2_benign_episodes": sum(v for k, v in benign_steps.items() if k > 2),
        "rule_docs_gt_5_attack_episodes": sum(v for k, v in attack_docs.items() if k > 5),
        "rule_docs_gt_5_benign_episodes": sum(v for k, v in benign_docs.items() if k > 5),
        "techniques_present": len(expected - set(missing)),
        "techniques_below_50": below,
        "max_4gram_jaccard_all_pairs": round(div_full["max_jaccard"], 4),
        "exact_char_max": round(div_full["max_char"], 4),
        "exact_char_pairs_at_or_above_0_80": div_full["pairs_at_or_above_080"],
        "exact_char_pairs_examined": div_full["pairs_examined_exact"],
        "exact_char_total_pairs": div_full["total_pairs"],
        "exact_char_scope": (
            f"all pairs with 4-gram Jaccard >= {EXACT_JACCARD_FLOOR}"),
        "core_max_4gram_jaccard": round(div_core["max_jaccard"], 4),
        "core_exact_char_max": round(div_core["max_char"], 4),
        "core_exact_char_pairs_at_or_above_0_80": div_core["pairs_at_or_above_080"],
        "core_exact_char_pairs_examined": div_core["pairs_examined_exact"],
        "core_exact_char_total_pairs": div_core["total_pairs"],
        "whole_episode_max_8gram_jaccard": round(div_ep["max_jaccard"], 4),
        "whole_episode_exact_char_max": round(div_ep["max_char"], 4),
        "whole_episode_pairs_at_or_above_0_80": div_ep["pairs_at_or_above_080"],
        "whole_episode_pairs_examined": div_ep["pairs_examined_exact"],
        "whole_episode_total_pairs": div_ep["total_pairs"],
        "whole_episode_scope": "all pairs with 8-gram Jaccard >= 0.12",
    }
    print("SUMMARY " + json.dumps(summary, indent=2, sort_keys=True))
    with open("out/summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "out/redteam.jsonl"))
