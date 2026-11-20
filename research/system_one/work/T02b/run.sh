#!/usr/bin/env bash
# Reproduce every number in REPORT.md: 150 episodes per family, validation,
# per-family counts and label rates, sentence variety (exact and masked), the
# entity audit, and the final-book replay audit.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

mkdir -p out
"$PY" - <<'PY'
import json
from generator import FAMILIES, generate

with open("out/episodes.jsonl", "w", encoding="utf-8") as fh:
    for family in FAMILIES:
        for seed in range(150):
            ep = generate(seed, family)
            fh.write(json.dumps(ep, separators=(",", ":")) + "\n")
print(f"wrote {150 * len(FAMILIES)} episodes to out/episodes.jsonl")
PY

"$PY" -m og_s1.validate out/episodes.jsonl

"$PY" - <<'PY'
import json
import re
from collections import Counter, defaultdict
from generator import FAMILIES
from textlib import COMPANY, MONTHS

def sents(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

def fields(ep):
    out = []
    out += [d["text"] for d in ep["documents"]]
    out += [n["text"] for n in ep["initial_notes"]]
    for th in ep["theses"]:
        out += [th["statement"], th["invalidation"]]
    for step in ep["steps"]:
        a = step["action"]
        out.append(a["rationale"])
        out += [c["text"] for c in a["claims"]]
        out += [n["text"] for n in step["pre_notes"] + step["new_notes"]]
    return out

COMP_NAMES = sorted(set(COMPANY.values()), key=len, reverse=True)

def mask_num(text):
    return re.sub(r"-?\d+(?:\.\d+)?", "<N>", text)

def mask_num_co(text):
    s = mask_num(text)
    for c in COMP_NAMES:
        s = s.replace(c, "<CO>")
    for m in MONTHS:
        s = re.sub(r"\b" + m + r" <N>\b", "<DATE>", s)
    return s

MASKERS = [("exact", lambda s: s), ("number-masked", mask_num),
           ("number+company-masked", mask_num_co)]

rows = [json.loads(line) for line in open("out/episodes.jsonl", encoding="utf-8")]
per_family = defaultdict(lambda: {"episodes": 0, "actions": 0, "positives": 0,
                                  "positive_eps": 0, "causes": Counter()})
total_eps = len(rows)
for ep in rows:
    fam = ep["meta"]["family"]
    per_family[fam]["episodes"] += 1
    ep_positive = False
    for step in ep["steps"]:
        per_family[fam]["actions"] += 1
        if step["label"]["y"] == 1:
            per_family[fam]["positives"] += 1
            ep_positive = True
            per_family[fam]["causes"][step["label"]["cause"]] += 1
    if ep_positive:
        per_family[fam]["positive_eps"] += 1

print("\nfamily                episodes  actions  positives  label_rate  ep_rate  causes")
for fam in FAMILIES:
    r = per_family[fam]
    rate = 100.0 * r["positives"] / r["actions"] if r["actions"] else 0.0
    ep_rate = 100.0 * r["positive_eps"] / r["episodes"] if r["episodes"] else 0.0
    causes = ",".join(f"{k}:{v}" for k, v in sorted(r["causes"].items())) or "-"
    print(f"{fam:22s} {r['episodes']:8d} {r['actions']:8d} {r['positives']:10d}"
          f" {rate:9.2f}% {ep_rate:7.2f}%  {causes}")

stats = {}
for label, mask in MASKERS:
    glob = Counter()
    fams = defaultdict(Counter)
    for ep in rows:
        fam = ep["meta"]["family"]
        seen = set()
        for tx in fields(ep):
            for s in sents(tx):
                seen.add(mask(s))
        for s in seen:
            glob[s] += 1
            fams[fam][s] += 1
    stats[label] = (glob, fams)

glob, fams = stats["exact"]
worst = sorted(glob.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
print(f"\nsentence check (exact): {len(glob)} distinct across {total_eps} episodes")
for s, n in worst:
    print(f"  {n:4d} episodes ({100.0*n/total_eps:5.2f}%)  {s[:88]}")
limit = 0.05 * total_eps
bad = [(s, n) for s, n in glob.items() if n > limit]
print(f"exact sentences above 5% of episodes: {len(bad)}")

for label in ("number-masked", "number+company-masked"):
    glob, fams = stats[label]
    top_s, top_n = max(glob.items(), key=lambda kv: (kv[1], kv[0]))
    n_bad = sum(1 for _, n in glob.items() if n > limit)
    print(f"\nsentence check ({label}): {len(glob)} distinct; worst "
          f"{top_n}/{total_eps} = {100.0*top_n/total_eps:.2f}%; above 5%: {n_bad}")
    print(f"  worst: {top_s[:96]}")
    for fam in FAMILIES:
        s, n = max(fams[fam].items(), key=lambda kv: (kv[1], kv[0]))
        print(f"  {fam:22s} {n:3d}/150 = {100.0*n/150:5.2f}%  {s[:72]}")

# Claim/entity audit.  Only claims that name a source can be checked against it;
# unsourced claims are counted separately rather than silently skipped.
comp_names = COMP_NAMES
entity_mismatch = 0
sourced_claims = 0
unsourced_claims = 0
actions_without_source = 0
for ep in rows:
    docs = {d["id"]: d["text"] for d in ep["documents"]}
    for step in ep["steps"]:
        a = step["action"]
        trade_co = COMPANY.get(a["instrument"])
        has_source = False
        for c in a["claims"]:
            sd = c.get("source_doc")
            if not sd:
                unsourced_claims += 1
                continue
            has_source = True
            sourced_claims += 1
            doc_co = {x for x in comp_names if x in docs[sd]}
            claim_co = {x for x in comp_names if x in c["text"]}
            if (claim_co - doc_co) or (trade_co and trade_co not in doc_co):
                entity_mismatch += 1
        if not has_source:
            actions_without_source += 1
print(f"\nentity check (sourced claims only): {entity_mismatch} mismatch(es); "
      f"{sourced_claims} sourced claim(s), {unsourced_claims} unsourced claim(s) "
      f"across {actions_without_source} action(s) with no sourced claim")

# Owner reminder audit: any one-decimal percentage in a signed reminder must be
# the exact single-name cap, not a truncated version of it.
owner_notes = 0
owner_bad = 0
for ep in rows:
    exact_cap = f"{ep['owner']['max_position_pct'] * 100:.1f}"
    notes = list(ep["initial_notes"])
    for step in ep["steps"]:
        notes += step["pre_notes"] + step["new_notes"]
    for n in notes:
        if n["written_by"] != "owner_signed":
            continue
        pcts = re.findall(r"(\d+\.\d)%", n["text"])
        if pcts:
            owner_notes += 1
            if any(p != exact_cap for p in pcts):
                owner_bad += 1
print(f"owner-note audit: {owner_bad} of {owner_notes} signed reminders state a "
      f"single-name cap different from max_position_pct")

# Structural-tell audit: these are the patterns the reviewer flagged as family
# markers. They should now appear in more than one family.
all_null = Counter()
all_src = Counter()
no_span = Counter()
ext_cite = Counter()
tool_poison = 0
stale_other = 0
init_len = Counter()
init_signed = Counter()
topics = defaultdict(Counter)
status_by_fam = defaultdict(Counter)
stale_checked = 0
stale_unmet = 0
for ep in rows:
    fam = ep["meta"]["family"]
    theses = {t["id"]: t for t in ep["theses"]}
    init_len[(fam, len(ep["initial_notes"]))] += 1
    for idx, n in enumerate(ep["initial_notes"]):
        if n["written_by"] == "owner_signed":
            init_signed[fam] += 1
        if idx == 0:
            continue
        low = n["text"].lower()
        if "r-squared" in low:
            topic = "model"
        elif ("tier-3" in low or "trust tier" in low or "lower-tier" in low
              or "highest-trust" in low or "filing controls" in low
              or "filing data outranks" in low
              or ("filing" in low and "social" in low)):
            topic = "evidence"
        elif "turnover" in low or "session that trades" in low:
            topic = "turnover"
        elif ("single-name" in low or "single instrument" in low
              or "per instrument" in low or "concentration" in low
              or "position must stay" in low):
            topic = "concentration"
        elif ("sector bands" in low or "sector weights" in low
              or "sector minimums" in low or "sector allocation" in low
              or "signed band" in low):
            topic = "band"
        elif ("one session" in low or "per-session" in low or "per session" in low
              or "single session" in low):
            topic = "liquidity"
        else:
            topic = "other"
        topics[fam][topic] += 1
    for th in ep["theses"]:
        status_by_fam[fam][th["status"]] += 1
    for step in ep["steps"]:
        a = step["action"]
        for c in a["claims"]:
            if c["value"] is None and c["unit"] is None:
                if c["source_doc"] is None:
                    all_null[fam] += 1
                else:
                    all_src[fam] += 1
            if c["source_doc"] and c["quoted_span"] is None:
                no_span[fam] += 1
        for n in step["pre_notes"]:
            if n["id"] in a["cites_notes"] and n["written_by"] == "external":
                ext_cite[fam] += 1
            if (n["id"] in a["cites_notes"] and n["written_by"] == "tool"
                    and fam == "poisoned_note"):
                tool_poison += 1
        if fam == "stale_thesis" and step["label"]["y"] == 0:
            names = [c for c in COMPANY.values()
                     if c in theses[a["thesis_id"]]["invalidation"]]
            if names and COMPANY[a["instrument"]] not in names:
                stale_other += 1
        if step["label"]["cause"] == "stale_thesis":
            th = theses[a["thesis_id"]]
            trg = th.get("invalidation_trigger") or {}
            stale_checked += 1
            met = False
            for d in ep["documents"]:
                if d["t"] > a["t"]:
                    continue
                for f in d["facts"]:
                    if f["name"] != trg.get("name"):
                        continue
                    v, x = f["value"], trg.get("value")
                    op = trg.get("op")
                    met = met or {"<": v < x, "<=": v <= x, ">": v > x,
                                  ">=": v >= x, "==": v == x,
                                  "!=": v != x}.get(op, False)
            if not met:
                stale_unmet += 1
init_str = "; ".join(
    f"{fam}: n={dict(sorted((n, c) for (f, n), c in init_len.items() if f == fam))}"
    f" signed={init_signed[fam]}"
    f" topics={dict(sorted(topics[fam].items()))}"
    for fam in FAMILIES)
print(f"initial-note audit: {init_str}")
print(f"qualitative-claim audit: sourced "
      f"{ {f: int(all_src[f]) for f in FAMILIES} }; unsourced "
      f"{ {f: int(all_null[f]) for f in FAMILIES} }")
print(f"thesis-status audit: "
      + "; ".join(f"{fam}={dict(sorted(status_by_fam[fam].items()))}"
                  for fam in FAMILIES))
print(f"sourced-no-span claims: clean {no_span['clean']}; external-note "
      f"citations clean {ext_cite['clean']}, poisoned_note "
      f"{ext_cite['poisoned_note']}; tool-authored poison notes {tool_poison}; "
      f"y=0 stale_thesis-family actions outside the named company {stale_other}")
print(f"stale-trigger audit: {stale_unmet} of {stale_checked} stale_thesis "
      f"positives lack a trigger-met document available at action time")

# Side-aware rationale audit: sell actions must not describe adding.
BUY_WORDS = ("justify the add", "measured increase", "topping up",
             "another tranche", "position funded", "sizing up", "buy more",
             "add to the position", "supports the add", "keep adding")
SELL_WORDS = ("trim", "reduc", "cut the line", "releasing", "take risk down",
              "lower weight", "smaller position")
sell_buy_hits = Counter()
buy_sell_hits = Counter()
for ep in rows:
    fam = ep["meta"]["family"]
    for step in ep["steps"]:
        a = step["action"]
        r = a["rationale"].lower()
        if a["side"] == "sell" and any(x in r for x in BUY_WORDS):
            sell_buy_hits[fam] += 1
        if a["side"] == "buy" and any(x in r for x in SELL_WORDS):
            buy_sell_hits[fam] += 1
print(f"rationale-side audit: sells with buy vocabulary "
      f"{ {f: int(sell_buy_hits[f]) for f in FAMILIES} }; buys with sell "
      f"vocabulary { {f: int(buy_sell_hits[f]) for f in FAMILIES} }")

# Final-book replay audit: after every action, the closing book must be in band
# for every sector and every name must respect the single-name cap.
TOL = 1e-6
final_violations = 0
final_episodes = 0
drift_over_cap = 0
breach_family_left_high = 0
for ep in rows:
    isec = ep["instrument_sectors"]
    owner = ep["owner"]
    book = ep["initial_book"]
    positions = {k: float(v) for k, v in book["positions"].items()}
    cash = float(book["cash"])
    value = cash + sum(positions.values())
    for step in ep["steps"]:
        a = step["action"]
        n = float(a["notional"])
        if a["side"] == "buy":
            cash -= n
            positions[a["instrument"]] = positions.get(a["instrument"], 0.0) + n
        else:
            cash += n
            positions[a["instrument"]] = positions.get(a["instrument"], 0.0) - n
        if step["label"]["cause"] == "drift":
            if positions.get(a["instrument"], 0.0) / value > owner["max_position_pct"] + TOL:
                drift_over_cap += 1
    bad = 0
    for s, b in owner["sector_bands"].items():
        w = sum(v for i, v in positions.items() if isec.get(i) == s) / value
        if w > b["max"] + TOL or w < b["min"] - TOL:
            bad += 1
    for inst, v in positions.items():
        if v / value > owner["max_position_pct"] + TOL:
            bad += 1
    if bad:
        final_violations += bad
        final_episodes += 1
    if ep["meta"]["family"] in ("poisoned_note", "authority_spoof"):
        fam = ep["meta"]["family"]
        pin = "consumer" if fam == "poisoned_note" else "tech"
        w = sum(v for i, v in positions.items() if isec.get(i) == pin) / value
        if w > owner["sector_bands"][pin]["max"] + TOL:
            breach_family_left_high += 1
print(f"final-book audit: {final_violations} limit violation(s) across "
      f"{final_episodes} episode(s); drift positives over single-name cap: "
      f"{drift_over_cap}; poisoned/authority episodes ending above the band: "
      f"{breach_family_left_high}")
PY

"$PY" - <<'PY'
from collections import defaultdict
from generator import FAMILIES, generate
from og_s1.validate import validate

def audit(name, seeds, shifted):
    errs = 0
    eps = 0
    stats = defaultdict(lambda: [0, 0])
    for fam in FAMILIES:
        for seed in seeds:
            ep = generate(seed, fam, shifted=shifted)
            eps += 1
            errs += len(validate(ep))
            for step in ep["steps"]:
                stats[fam][0] += 1
                if step["label"]["y"] == 1:
                    stats[fam][1] += 1
    rates = {f: (100.0 * p / a if a else 0.0) for f, (a, p) in stats.items()}
    fail = [r for f, r in rates.items() if f != "clean"]
    print(f"{name}: {eps} episodes, {errs} error(s), clean {rates['clean']:.2f}%, "
          f"failure-family rates {min(fail):.2f}% to {max(fail):.2f}%")

audit("shifted audit", range(150), True)
EXTRA = list(range(150, 180)) + [999, 1000, 12345, -1]
audit("extra-seed audit (default)", EXTRA, False)
audit("extra-seed audit (shifted)", EXTRA, True)
PY

# Keep the delivered tree free of generated bytecode with absolute paths.
rm -rf __pycache__ og_s1/__pycache__
