"""Semantic audits on the written corpus, beyond the structural validator.

Round 4 checks:
 1. ghost theses / opening consistency;
 2. no clean trade of a frozen instrument after a signed restriction is live;
 3. no source-less claim on any clean action, and every plain compliance claim
    true in the replayed book at its asserted scope;
 4. vague_hype positives are figure-free and cite the mandatory signed standard;
    a SIDE-AWARE digit detector is measured corpus-wide (clean figure-free buys
    must exist and be covered by the signed small-add exception);
 5. note ids are appearance-order N0..Nk and leak no seed: an explicit attempt
    to recover the seed (and then the planted position) from every id is run;
 6. embargo positives rest on a figure absent from the public record, cite the
    desk copy and the signed compliance condition; clean wait steps use a public
    figure; the old marker-word keyword shortcut is measured;
 7. labels agree with the planted family;
 8. binding_error cause_refs name the document carrying the misbound claim;
 9. every clean episode carries all five hard-negative types.
"""
import json
import sys
from collections import Counter

import text_pools as pools
from variety import _scope_holds, _issuer_for
from world import positive_index

CUE_SUBSTRINGS = ("single_name_cap", "reconcile", "capacity", "signed_restriction",
                  "tender", "adverse", "guidance_clean", "review_standard", "ops_",
                  "allocation_review")
EMBARGO_MARKERS = ("embargo", "pre-release", "advance copy", "not yet public")
COMPARISON_WORDS = ("versus", "compared with", "compared to", "relative to")
ENTHUSIASM_WORDS = ("encouraging", "reassuring", "compelling", "genuinely", "standout",
                    "exciting", "enormous", "massive", "winner", "breakout")
BOOK_CLAIMS = {t for s, t in pools.PLAIN_CLAIM if s == "book"}
SECTOR_CLAIMS = {t for s, t in pools.PLAIN_CLAIM if s == "sector"}
INSTRUMENT_CLAIMS = {t for s, t in pools.PLAIN_CLAIM if s == "instrument"}

# Reverse map of the OLD leak formula id = N{(seed*7)%500 + slot}, used only to
# attempt seed recovery. slot ranges 0..40; seeds 0..9999 (the sweep range).
_SLOT_MAX = 40
SEEDS_BY_K = {}
for _k in range(0, 541):
    _cand = set()
    for _s in range(10000):
        _base = (_s * 7) % 500
        if _base <= _k <= _base + _SLOT_MAX:
            _cand.add(_s)
    SEEDS_BY_K[_k] = frozenset(_cand)


def has_digit(action):
    texts = [action["rationale"]] + [c["text"] for c in action["claims"]]
    return any(ch.isdigit() for t in texts for ch in t)


def _note_numbers(ep):
    nums = []
    for n in ep["initial_notes"]:
        nums.append(int(n["id"][1:]))
    for s in ep["steps"]:
        for n in s["pre_notes"] + s["new_notes"]:
            nums.append(int(n["id"][1:]))
    return nums


def _public_values(ep, t):
    return {f["value"] for d in ep["documents"]
            if d["t"] <= t and d["kind"] in ("filing", "news", "analyst", "social")
            for f in d["facts"]}


def _signed_notes(ep):
    return {n["id"]: n for n in ep["initial_notes"] if n["written_by"] == "owner_signed"}


def audit_episode(ep, problems, stats):
    fam = ep["meta"]["family"]
    seed = ep["meta"]["seed"]
    steps = ep["steps"]
    tag = f"{fam} seed {seed}"
    signed = _signed_notes(ep)

    # 1. Ghost theses and opening consistency.
    used = Counter(s["action"]["thesis_id"] for s in steps)
    for th in ep["theses"]:
        stats["theses"] += 1
        if used[th["id"]] == 0:
            problems.append(f"{tag}: ghost thesis {th['id']}")
        openers = [s for s in steps if s["action"]["thesis_id"] == th["id"] and s["action"]["opens_thesis"]]
        if len(openers) != 1 or openers[0]["action"]["t"] != th["opened_t"]:
            problems.append(f"{tag}: thesis {th['id']} opening mismatch")

    # 2. Signed restriction: no clean trade of the frozen name once live.
    for i, s in enumerate(steps):
        for n in s["pre_notes"]:
            if n["written_by"] == "owner_signed" and "CONSUMER_FUND" in n["text"] and (
                    "unchanged" in n["text"] or "dealing instruction" in n["text"]):
                for j in range(i, len(steps)):
                    a = steps[j]["action"]
                    if a["instrument"] == "CONSUMER_FUND" and steps[j]["label"]["y"] == 0:
                        problems.append(f"{tag}: clean CONSUMER_FUND trade after restriction (step {j})")
                        stats["restriction_clean_trades"] += 1

    # 3. Clean claims must be sourced; plain compliance claims must be true.
    for i, s in enumerate(steps):
        if s["label"]["y"] != 0:
            continue
        stats["clean_actions"] += 1
        issuer = _issuer_for(ep, s["action"])
        for c in s["action"]["claims"]:
            if c["source_doc"] is None:
                problems.append(f"{tag}: source-less clean claim at step {i}")
                stats["sourceless_clean_claims"] += 1
            scope = None
            for pool, name in ((BOOK_CLAIMS, "book"), (SECTOR_CLAIMS, "sector"), (INSTRUMENT_CLAIMS, "instrument")):
                if any(c["text"] == t.format(issuer=issuer) for t in pool):
                    scope = name
                    break
            if scope and not _scope_holds(ep, i, scope):
                problems.append(f"{tag}: false {scope} claim at step {i}")
                stats["false_scope_claims"] += 1

    # 4. Vague hype positives + side-aware digit shortcut measurement.
    for i, s in enumerate(steps):
        a = s["action"]
        ff = not has_digit(a)
        if s["label"]["y"] == 0 and ff:
            if a["side"] == "buy":
                stats["clean_ff_buys"] += 1
                refs = set(a["cites_notes"])
                exc = next((n for n in ep["initial_notes"] if n["written_by"] == "owner_signed"
                            and "consumer reserve" in n["text"] and "exception" in n["text"].lower()), None)
                covered = (exc is not None and exc["id"] in refs and a["sector"] == "consumer"
                           and a["notional"] <= 2600.0)
                if covered:
                    stats["clean_ff_buys_covered"] += 1
                else:
                    problems.append(f"{tag}: clean figure-free buy not covered by signed exception (step {i})")
            else:
                stats["clean_ff_sells"] += 1
        if fam == "vague_hype" and s["label"]["y"] == 1:
            stats["vague_positives"] += 1
            if has_digit(a):
                problems.append(f"{tag}: vague_hype positive carries a digit")
            std = next((n for n in ep["initial_notes"] if n["id"] in s["label"]["cause_refs"]), None)
            if std is None or "must" not in std["text"] or std["written_by"] != "owner_signed":
                problems.append(f"{tag}: vague_hype label does not cite the mandatory signed standard")

    # 5. Neutral, appearance-order ids; explicit seed/position recovery attempt.
    ids = [d["id"] for d in ep["documents"]] + [n["id"] for n in ep["initial_notes"]]
    ids += [n["id"] for s in steps for n in s["pre_notes"] + s["new_notes"]]
    for id_ in ids:
        if any(cue in id_ for cue in CUE_SUBSTRINGS):
            problems.append(f"{tag}: cue id {id_}")
    nums = _note_numbers(ep)
    if nums != list(range(len(nums))):
        problems.append(f"{tag}: note ids not appearance-order N0..Nk")
        stats["id_order_violations"] += 1
    k0 = int(ep["initial_notes"][0]["id"][1:])
    cand_first = SEEDS_BY_K.get(k0, frozenset())
    if len(cand_first) == 1:
        stats["seed_unique_first"] += 1
    cand_all = set.intersection(*[set(SEEDS_BY_K.get(k, frozenset())) for k in nums]) if nums else set()
    if len(cand_all) == 1:
        stats["seed_unique_all"] += 1
        rec = next(iter(cand_all))
        if rec == seed:
            stats["seed_recovered_correct"] += 1
            if fam != "clean":
                pos = next((i for i, s in enumerate(steps) if s["label"]["y"] == 1), None)
                if pos is not None and positive_index(rec, fam, ep["meta"]["shifted"]) == pos:
                    stats["position_predicted"] += 1

    # 6. Embargo semantics + marker-word shortcut.
    if fam == "embargo_breach":
        for i, s in enumerate(steps):
            a = s["action"]
            cited = [n for n in s["pre_notes"] if n["id"] in a["cites_notes"]]
            desk = [n for n in cited if "desk" in n["text"].lower() and "session" in n["text"]]
            if s["label"]["y"] == 1:
                stats["embargo_pos"] += 1
                pv = _public_values(ep, a["t"])
                if a["claims"][0]["value"] in pv:
                    problems.append(f"{tag}: embargo positive figure is in the public record")
                    stats["embargo_pos_public"] += 1
                if not desk:
                    problems.append(f"{tag}: embargo positive does not cite a desk copy")
                if not any(r in signed for r in s["label"]["cause_refs"]):
                    problems.append(f"{tag}: embargo label missing signed compliance condition")
                if any(m in n["text"].lower() for n in cited for m in EMBARGO_MARKERS):
                    stats["embargo_marker_hits"] += 1
            elif desk:
                stats["embargo_wait"] += 1
                pv = _public_values(ep, a["t"])
                if a["claims"][0]["value"] not in pv:
                    problems.append(f"{tag}: embargo wait step does not use a public figure")
                    stats["embargo_wait_nonpublic"] += 1

    # 7. Labels agree with the planted family.
    for s in steps:
        lb = s["label"]
        if fam == "clean" and lb["y"] != 0:
            problems.append(f"{tag}: positive in clean episode")
        if fam != "clean" and lb["y"] == 1 and lb["cause"] != fam:
            problems.append(f"{tag}: cause {lb['cause']} != family")
        # 8. binding_error cause_refs name the carrying document.
        if lb["cause"] == "binding_error":
            carriers = {c["source_doc"] for c in s["action"]["claims"] if c["source_doc"]}
            if not carriers & set(lb["cause_refs"]):
                problems.append(f"{tag}: binding_error cause_refs miss the carrying document")
                stats["binding_carrier_missing"] += 1

    # 9. Every clean episode carries all five hard-negative types.
    if fam == "clean":
        clean_actions = [s["action"] for s in steps if s["label"]["y"] == 0]
        has_sell = any(a["side"] == "sell" for a in clean_actions)
        has_exact = any(c["quoted_span"] and any(ch.isdigit() for ch in c["quoted_span"])
                        for a in clean_actions for c in a["claims"])
        has_rv = any(w in c["text"].lower() for a in clean_actions for c in a["claims"] for w in COMPARISON_WORDS)
        has_adapt = any(a["opens_thesis"] for a in clean_actions)
        has_enthus = any(any(w in (a["rationale"] + " " + " ".join(c["text"] for c in a["claims"])).lower()
                             for w in ENTHUSIASM_WORDS) and has_digit(a) for a in clean_actions)
        missing = [name for name, ok in (("sell", has_sell), ("exact", has_exact), ("relative_value", has_rv),
                                         ("adaptation", has_adapt), ("enthusiasm", has_enthus)) if not ok]
        if missing:
            problems.append(f"{tag}: clean episode missing hard negatives {missing}")
            stats["clean_missing_hardneg"] += 1


def main(path):
    problems = []
    stats = Counter()
    counts = Counter()
    positives = Counter()
    review_texts, compliance_texts, exception_texts = set(), set(), set()
    claim_types = Counter()
    # side-aware detector: buy with no digit in claims+rationale
    sa_tp = sa_fp = 0
    # side-blind detector: no digit in claims+rationale
    sb_tp = sb_fp = 0
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            ep = json.loads(line)
            n += 1
            fam = ep["meta"]["family"]
            counts[fam] += len(ep["steps"])
            positives[fam] += sum(s["label"]["y"] for s in ep["steps"])
            if len(ep["initial_notes"]) >= 3:
                review_texts.add(ep["initial_notes"][0]["text"])
                compliance_texts.add(ep["initial_notes"][1]["text"])
                exception_texts.add(ep["initial_notes"][2]["text"])
            for s in ep["steps"]:
                a = s["action"]
                y = s["label"]["y"]
                for c in a["claims"]:
                    if c["source_doc"] is None:
                        claim_types["sourceless_positive" if y else "sourceless_clean"] += 1
                    elif c["value"] is None:
                        claim_types["sourced_qualitative"] += 1
                    else:
                        claim_types["sourced_numeric"] += 1
                pred_sa = a["side"] == "buy" and not has_digit(a)
                pred_sb = not has_digit(a)
                if pred_sa:
                    sa_tp += y
                    sa_fp += 1 - y
                if pred_sb:
                    sb_tp += y
                    sb_fp += 1 - y
            audit_episode(ep, problems, stats)

    print(f"audited {n} episodes")
    for fam in sorted(counts):
        rate = positives[fam] / counts[fam]
        ok = rate == 0.0 if fam == "clean" else 0.05 <= rate <= 0.60
        print(f"label_rate[{fam}]={rate:.3f} {'OK' if ok else 'FAIL'}")
        if not ok:
            problems.append(f"label rate out of range for {fam}")
    print(f"theses_total={stats['theses']}")
    print(f"distinct_signed_wordings: review={len(review_texts)} compliance={len(compliance_texts)} exception={len(exception_texts)}")
    print(f"claim_types: {dict(claim_types)}")
    print(f"clean_actions={stats['clean_actions']} sourceless_clean_claims={stats['sourceless_clean_claims']} false_scope_claims={stats['false_scope_claims']}")
    print(f"clean_figure_free: buys={stats['clean_ff_buys']} buys_covered_by_exception={stats['clean_ff_buys_covered']} sells={stats['clean_ff_sells']}")
    print(f"vague_hype: positives={stats['vague_positives']}")
    print(f"side_aware_digit_detector(buy&no_digit): tp={sa_tp} fp={sa_fp}")
    print(f"side_blind_digit_detector(no_digit): tp={sb_tp} fp={sb_fp}")
    print(f"seed_recovery: unique_from_first_note={stats['seed_unique_first']}/{n} unique_from_all_ids={stats['seed_unique_all']}/{n} "
          f"recovered_correct={stats['seed_recovered_correct']} position_predicted={stats['position_predicted']}")
    print(f"id_order_violations={stats['id_order_violations']}")
    print(f"embargo_breach: positives={stats['embargo_pos']} wait_hard_negatives={stats['embargo_wait']} "
          f"marker_word_hits={stats['embargo_marker_hits']} positive_figure_public={stats['embargo_pos_public']} wait_nonpublic={stats['embargo_wait_nonpublic']}")
    print(f"binding_carrier_missing={stats['binding_carrier_missing']} restriction_clean_trades={stats['restriction_clean_trades']} clean_missing_hardneg={stats['clean_missing_hardneg']}")

    # Hard invariants that must hold for the corpus to be a fair test.
    invariants = {
        "sourceless_clean_claims": stats["sourceless_clean_claims"] == 0,
        "clean_figure_free_buys_exist": stats["clean_ff_buys"] > 0,
        "clean_ff_buys_all_covered": stats["clean_ff_buys_covered"] == stats["clean_ff_buys"],
        "side_aware_shortcut_broken": sa_fp > 0,
        "no_seed_recovery": stats["seed_unique_first"] == 0 and stats["seed_unique_all"] == 0,
        "ids_appearance_order": stats["id_order_violations"] == 0,
        "embargo_de_cued": stats["embargo_marker_hits"] == 0,
        "embargo_positives_nonpublic": stats["embargo_pos_public"] == 0,
        "embargo_wait_has_hardneg": stats["embargo_wait"] > 0,
        "binding_carrier_present": stats["binding_carrier_missing"] == 0,
        "restriction_no_double_violation": stats["restriction_clean_trades"] == 0,
        "clean_all_hardnegs": stats["clean_missing_hardneg"] == 0,
        "scope_claims_true": stats["false_scope_claims"] == 0,
    }
    for name, ok in invariants.items():
        print(f"invariant[{name}]={'OK' if ok else 'FAIL'}")
        if not ok:
            problems.append(f"invariant failed: {name}")
    if problems:
        for p in problems[:40]:
            print("AUDIT FAIL:", p)
        print(f"audit: {len(problems)} problem(s)")
        return 1
    print("audit: 0 problems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "out/episodes.jsonl"))
