"""Audit fact coverage, quoted-claim values, markers, and structural shortcuts."""
from __future__ import annotations

import json
import re
import sys

import prose

MARKER = re.compile(
    r"ignore|waive|suspend|do not apply|do not bother|limits are|"
    r"without waiting|amendment|paperwork|pending|treat as effective"
)


def main(path):
    facts = prec = absent = quoted = qbad = markers = 0
    conf = {}
    claim_counts = {}
    opens = {"clean": 0, "pos": 0}
    recency = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            ep = json.loads(line)
            fam = ep["meta"]["family"]
            docs = {d["id"]: d for d in ep["documents"]}
            all_notes = list(ep["initial_notes"])
            for s in ep["steps"]:
                all_notes += s["pre_notes"] + s["new_notes"]
            for d in ep["documents"]:
                for f in d["facts"]:
                    facts += 1
                    if prose.round_for(f["unit"], f["value"]) != f["value"]:
                        prec += 1
                    if prose.fmt(f["name"], f["value"], f["unit"]) not in d["text"]:
                        absent += 1
            for n in all_notes:
                if MARKER.search(n["text"].lower()):
                    markers += 1
            for s in ep["steps"]:
                a = s["action"]
                y = s["label"]["y"]
                if MARKER.search(a["rationale"].lower()):
                    markers += 1
                doc_t = [d["t"] for d in ep["documents"] if d["t"] <= a["t"]]
                newest = max(doc_t) if doc_t else None
                cited = [c["source_doc"] for c in a["claims"] if c.get("source_doc")]
                is_old = bool(cited) and newest is not None and any(
                    docs[c]["t"] < newest for c in cited)
                for c in a["claims"]:
                    if (c.get("quoted_span") and c.get("value") is not None
                            and c.get("source_doc")):
                        quoted += 1
                        vals = [f["value"] for f in docs[c["source_doc"]]["facts"]]
                        if not any(abs(v - c["value"]) < 1e-9 for v in vals):
                            qbad += 1
                if a["side"] == "buy" and not a["opens_thesis"]:
                    opens["pos" if y == 1 else "clean"] += 1
                if a["cites_notes"]:
                    key = (fam, y, min(len(a["claims"]), 2))
                    claim_counts[key] = claim_counts.get(key, 0) + 1
                if fam in ("stale_thesis", "superseded_source"):
                    row = recency.setdefault(fam, {"clean_old": 0, "clean_tot": 0,
                                                   "pos_old": 0, "pos_tot": 0})
                    if y == 0:
                        row["clean_tot"] += 1
                        row["clean_old"] += int(is_old)
                    else:
                        row["pos_tot"] += 1
                        row["pos_old"] += int(is_old)
            if fam in ("poisoned_note", "authority_spoof"):
                row = conf.setdefault(fam, [0, 0, 0])
                row[0] += 1
                row[1] += any(s["label"]["y"] == 0 and s["action"]["cites_notes"]
                              for s in ep["steps"])
                row[2] += any(s["label"]["y"] == 1 and s["action"]["cites_notes"]
                              for s in ep["steps"])

    print(f"facts: {facts}, display-precision mismatches: {prec}, absent from text: {absent}")
    print(f"quoted claims: {quoted}, value absent from source facts: {qbad}")
    print(f"marker phrases (all notes and rationales): {markers}")
    for fam, row in sorted(conf.items()):
        print(f"  {fam}: clean-cites-note {row[1]}/{row[0]}, "
              f"positive-cites-note {row[2]}/{row[0]}")

    print("claim-count audit (actions that cite notes; claims capped at 2+):")
    for fam in sorted({k[0] for k in claim_counts}):
        parts = []
        for y in (0, 1):
            counts = {n: claim_counts.get((fam, y, n), 0) for n in (0, 1, 2)}
            parts.append(f"y={y} " + "/".join(f"{n}:{counts[n]}" for n in (0, 1, 2)))
        print(f"  {fam:<20} " + ", ".join(parts))

    print(f"opens_thesis audit: continuation buys y=0 {opens['clean']}, y=1 {opens['pos']}")
    print("citation-recency audit (cited a document older than the newest available):")
    for fam, row in sorted(recency.items()):
        print(f"  {fam}: clean {row['clean_old']}/{row['clean_tot']}, "
              f"positive {row['pos_old']}/{row['pos_tot']}")

    def perfect(pos_yes, pos_tot, clean_yes, clean_tot):
        return pos_tot > 0 and clean_tot > 0 and pos_yes == pos_tot and clean_yes == 0

    claim_shortcut = False
    for fam in {k[0] for k in claim_counts}:
        c0 = claim_counts.get((fam, 0, 0), 0)
        c_n = sum(claim_counts.get((fam, 0, n), 0) for n in (1, 2))
        p0 = claim_counts.get((fam, 1, 0), 0)
        p_n = sum(claim_counts.get((fam, 1, n), 0) for n in (1, 2))
        if (p0 and not c0) or (c_n and not p_n):
            claim_shortcut = True
    opens_shortcut = opens["pos"] > 0 and opens["clean"] == 0
    rec_shortcut = any(perfect(r["pos_old"], r["pos_tot"], r["clean_old"], r["clean_tot"])
                       for r in recency.values())

    ok = (prec == 0 and absent == 0 and markers == 0
          and all(r[1] == r[0] and r[2] == r[0] for r in conf.values())
          and not claim_shortcut and not opens_shortcut and not rec_shortcut)
    print("fact/provenance audit:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out/episodes.jsonl"))
