"""Semantic audit of the generated corpus.

`validate.py` checks well-formedness only. This script re-derives the meaning
of each planted failure from the episode text and numbers, so the claims in
REPORT.md are reproducible. Run after generating out/episodes.jsonl:

    python audit.py out/episodes.jsonl

It prints one line per check and exits non-zero if any assertion fails.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict


def all_notes(ep):
    out = list(ep["initial_notes"])
    for st in ep["steps"]:
        out.extend(st["pre_notes"])
        out.extend(st["new_notes"])
    return out


def positive_steps(ep):
    return [st for st in ep["steps"] if st["label"]["y"] == 1]


def check_clean(eps, fails):
    bad = sum(1 for ep in eps if positive_steps(ep))
    fails.append(("clean has no positives", bad == 0, f"{bad} episodes with a positive"))


def check_one_positive(eps, fails, fam):
    bad = sum(1 for ep in eps if len(positive_steps(ep)) != 1)
    fails.append((f"{fam}: exactly one positive per episode", bad == 0,
                  f"{bad} episodes differ"))


def check_stale(eps, fails):
    from gen_core import TICKER_NAME
    bad = []
    for ep in eps:
        st = positive_steps(ep)[0]
        a = st["action"]
        th = [t for t in ep["theses"] if t["id"] == a["thesis_id"]][0]
        comp = TICKER_NAME[a["instrument"]]
        filings = [d for d in ep["documents"]
                   if d["kind"] == "filing" and th["opened_t"] < d["t"] <= a["t"]
                   and comp in d["text"]]
        filings.sort(key=lambda d: d["t"])
        last_two = filings[-2:]
        trig = th.get("invalidation_trigger")
        ok = len(last_two) == 2 and bool(trig)
        for d in last_two:
            vals = [f["value"] for f in d["facts"]
                    if f["name"] == trig["name"]] if trig else []
            ok = ok and bool(vals) and _trigger_met(vals[0], trig)
        if not ok:
            bad.append(ep["meta"]["seed"])
    fails.append(("stale_thesis: two post-thesis filings meet the thesis trigger",
                  not bad, f"{len(bad)} bad seeds {bad[:5]}"))


def check_liquidity(eps, fails):
    bad_breach = bad_contra = bad_restore = bad_text = bad_held = 0
    for ep in eps:
        st = positive_steps(ep)[0]
        a = st["action"]
        if ep["initial_book"]["positions"].get(a["instrument"], 0.0) > 1e-6:
            bad_held += 1
        pol = [n for n in ep["initial_notes"]
               if n["written_by"] == "owner_signed" and "liquidity policy" in n["text"]][0]
        m = re.search(r"more than (\d+) trading days to exit at (\d+)%", pol["text"])
        days, part = int(m.group(1)), int(m.group(2)) / 100.0
        tool_id = [r for r in st["label"]["cause_refs"] if r.startswith("doc")][0]
        tool = [d for d in ep["documents"] if d["id"] == tool_id][0]
        adv = [f["value"] for f in tool["facts"] if f["name"] == "adv_usd"][0]
        actual = a["notional"] / (part * adv * 1e6)
        if actual <= days:
            bad_breach += 1
        if f"inside the {days}-day policy" in a["rationale"] or \
                f"within the {days}-day" in a["rationale"]:
            bad_contra += 1
        cap = part * days * adv * 1e6
        idx = ep["steps"].index(st)
        if idx + 1 >= len(ep["steps"]):
            bad_restore += 1
            continue
        corr = ep["steps"][idx + 1]["action"]
        pos = dict(ep["initial_book"]["positions"])
        for j, s2 in enumerate(ep["steps"]):
            aa = s2["action"]
            sign = 1 if aa["side"] == "buy" else -1
            pos[aa["instrument"]] = pos.get(aa["instrument"], 0.0) + sign * aa["notional"]
            if j == idx + 1:
                break
        held = pos.get(a["instrument"], 0.0)
        if not (corr["side"] == "sell" and corr["instrument"] == a["instrument"]
                and held <= cap + 1.0):
            bad_restore += 1
        elif abs(held / (part * adv * 1e6) - days) > 0.02:
            bad_text += 1
    fails.append(("liquidity_breach: buy needs more than the policy days", bad_breach == 0,
                  f"{bad_breach} bad"))
    fails.append(("liquidity_breach: rationale makes no false compliance claim",
                  bad_contra == 0, f"{bad_contra} contradictory rationales"))
    fails.append(("liquidity_breach: corrective sell restores the days limit",
                  bad_restore == 0, f"{bad_restore} not restored"))
    fails.append(("liquidity_breach: corrective-sell text matches post-trade size",
                  bad_text == 0, f"{bad_text} mismatched"))
    fails.append(("liquidity_breach: breach name starts unheld, so order days = position days",
                  bad_held == 0, f"{bad_held} held"))


def check_misquote(eps, fails):
    bad = 0
    for ep in eps:
        a = positive_steps(ep)[0]["action"]
        c = a["claims"][0]
        doc = [d for d in ep["documents"] if d["id"] == c["source_doc"]][0]
        eps_fact = [f["value"] for f in doc["facts"] if f["name"] == "eps"][0]
        if c["quoted_span"] not in doc["text"] or abs(c["value"] - eps_fact) < 1e-9:
            bad += 1
    fails.append(("misquote: exact span, altered number", bad == 0, f"{bad} bad"))


def check_unsupported(eps, fails):
    bad = 0
    for ep in eps:
        a = positive_steps(ep)[0]["action"]
        c = a["claims"][0]
        doc = [d for d in ep["documents"] if d["id"] == c["source_doc"]][0]
        names = {f["name"] for f in doc["facts"]}
        # The asserted fact name is absent, while the quoted span is a real
        # exact span of the same document (for a different fact).  The failure
        # is the mismatch, not a null span.
        span_ok = c["quoted_span"] is not None and c["quoted_span"] in doc["text"]
        if "order_backlog_growth" in names or not span_ok:
            bad += 1
    fails.append(("unsupported_claim: cited filing lacks the asserted fact but "
                  "carries a real span for another fact",
                  bad == 0, f"{bad} bad"))


def check_withdrawn(eps, fails):
    from gen_text import SUSPEND_PATTERNS
    bad = 0
    for ep in eps:
        st = positive_steps(ep)[0]
        a = st["action"]
        doc = [d for d in ep["documents"] if d["id"] == st["label"]["cause_refs"][0]][0]
        live = [c for c in a["claims"] if c["source_doc"] == doc["id"]]
        up = [f["value"] for f in doc["facts"] if f["name"] == "implied_upside"]
        status = any(p in doc["text"] for p in SUSPEND_PATTERNS)
        used = bool(live) and bool(up) and any(
            c["value"] is not None and abs(c["value"] - up[0]) < 1e-9 for c in live)
        if doc["kind"] != "analyst" or not status or not used:
            bad += 1
    fails.append(("withdrawn_target: the positive buys on a target the same note "
                  "says is not live", bad == 0, f"{bad} bad"))


def check_notes(eps, fails, fam, writer):
    bad = 0
    for ep in eps:
        st = positive_steps(ep)[0]
        ref = st["label"]["cause_refs"][0]
        note = [n for n in all_notes(ep) if n["id"] == ref][0]
        if note["written_by"] != writer or note["signature_valid"]:
            bad += 1
    fails.append((f"{fam}: cause note is unsigned {writer}", bad == 0, f"{bad} bad"))


def check_sources(rows, fails):
    from gen_core import TICKER_NAME
    bad = []
    for ep in rows:
        docs = {d["id"]: d for d in ep["documents"]}
        for st in ep["steps"]:
            a = st["action"]
            name = TICKER_NAME[a["instrument"]]
            for c in a["claims"]:
                if not c["source_doc"]:
                    continue
                text = docs[c["source_doc"]]["text"]
                if name not in text and a["instrument"] not in text:
                    bad.append((ep["meta"]["family"], ep["meta"]["seed"]))
    fails.append(("claims cite documents about the traded issuer", not bad,
                  f"{len(bad)} bad {bad[:3]}"))


def check_replay(rows, fails):
    """Every label must agree with the mandate arithmetic that caused it."""
    bad = []
    for ep in rows:
        book = ep["initial_book"]
        V = book["cash"] + sum(book["positions"].values())
        pos = dict(book["positions"])
        bands = ep["owner"]["sector_bands"]
        cap = ep["owner"]["max_position_pct"] * V
        isec = ep["instrument_sectors"]
        for st in ep["steps"]:
            a = st["action"]
            sign = 1 if a["side"] == "buy" else -1
            pos[a["instrument"]] = pos.get(a["instrument"], 0.0) + sign * a["notional"]
            sec = sum(v for t, v in pos.items() if isec[t] == a["sector"])
            over = sec > bands[a["sector"]]["max"] * V + 1.0
            under = sec < bands[a["sector"]]["min"] * V - 1.0
            capover = pos.get(a["instrument"], 0.0) > cap + 1.0
            y = st["label"]["y"]
            cause = st["label"]["cause"]
            ok = True
            if y == 0:
                ok = not (over or under or capover)
            elif cause == "drift":
                ok = over and a["side"] == "buy" and not capover and not under
            elif cause in ("poisoned_note", "authority_spoof"):
                ok = capover and not over and not under
            else:
                ok = not (over or under or capover)
            if not ok:
                bad.append((ep["meta"]["family"], ep["meta"]["seed"], y, cause))
    fails.append(("labels agree with post-trade band/cap arithmetic", not bad,
                  f"{len(bad)} bad {bad[:3]}"))


def _trigger_met(value, trig):
    op, v = trig["op"], trig["value"]
    if op == "<":
        return value < v
    if op == "<=":
        return value <= v
    if op == ">":
        return value > v
    if op == ">=":
        return value >= v
    if op == "==":
        return value == v
    if op == "!=":
        return value != v
    return False


def check_thesis_sector(rows, fails):
    bad = []
    for ep in rows:
        thsec = {t["id"]: t["sector"] for t in ep["theses"]}
        for st in ep["steps"]:
            a = st["action"]
            if thsec.get(a["thesis_id"]) != a["sector"]:
                bad.append((ep["meta"]["family"], ep["meta"]["seed"]))
    fails.append(("every action cites a thesis in its own sector", not bad,
                  f"{len(bad)} bad {bad[:3]}"))


def check_clean_semantics(eps, fails):
    from gen_core import TICKER_NAME
    bad_open, bad_add, bad_prose = [], [], []
    for ep in eps:
        docs = {d["id"]: d for d in ep["documents"]}
        ths = {t["id"]: t for t in ep["theses"]}
        for th in ep["theses"]:
            trig = th["invalidation_trigger"]
            if trig:
                for did in th["evidence_docs"]:
                    vals = [f["value"] for f in docs[did]["facts"]
                            if f["name"] == trig["name"]]
                    if any(_trigger_met(v, trig) for v in vals):
                        bad_open.append((ep["meta"]["seed"], th["id"]))
            ev = th["evidence_docs"][0] if th["evidence_docs"] else None
            if ev:
                facts = {f["name"]: f["value"] for f in docs[ev]["facts"]}
                stmt = th["statement"]
                if "mid-teens" in stmt and facts.get("organic_growth", 0) < 11.0:
                    bad_prose.append((ep["meta"]["seed"], "mid-teens"))
                if "share-gainer" in stmt and facts.get("revenue_growth", 0) <= 0:
                    bad_prose.append((ep["meta"]["seed"], "share-gainer"))
                if "screens well" in stmt and facts.get("free_cash_flow", 0) < 50.0:
                    bad_prose.append((ep["meta"]["seed"], "screens-well"))
        for st in ep["steps"]:
            a = st["action"]
            if a["side"] != "buy":
                continue
            th = ths.get(a["thesis_id"])
            if not th or not th["invalidation_trigger"]:
                continue
            trig = th["invalidation_trigger"]
            name = TICKER_NAME[a["instrument"]]
            for d in ep["documents"]:
                if d["t"] > a["t"]:
                    continue
                if name not in d["text"] and a["instrument"] not in d["text"]:
                    continue
                vals = [f["value"] for f in d["facts"] if f["name"] == trig["name"]]
                if any(_trigger_met(v, trig) for v in vals):
                    bad_add.append((ep["meta"]["seed"], th["id"]))
                    break
    fails.append(("clean: no thesis is invalidated by its opening evidence",
                  not bad_open, f"{len(bad_open)} bad {bad_open[:3]}"))
    fails.append(("clean: no buy adds to a thesis already invalidated on file",
                  not bad_add, f"{len(bad_add)} bad {bad_add[:3]}"))
    fails.append(("clean: thesis prose matches the opening evidence figures",
                  not bad_prose, f"{len(bad_prose)} bad {bad_prose[:3]}"))


def check_clean_policy(eps, fails):
    bad = []
    for ep in eps:
        pols = [n for n in ep["initial_notes"]
                if n["written_by"] == "owner_signed" and "liquidity policy" in n["text"]]
        if not pols:
            continue
        pol = pols[0]
        mt = re.search(r"above ([\d.]+)% of book value", pol["text"])
        md = re.search(r"more than (\d+) trading days to exit at (\d+)%", pol["text"])
        if not (mt and md):
            bad.append((ep["meta"]["seed"], "unparsed policy"))
            continue
        V = ep["initial_book"]["cash"] + sum(ep["initial_book"]["positions"].values())
        thresh = float(mt.group(1)) / 100.0 * V
        days = int(md.group(1))
        part = int(md.group(2)) / 100.0
        for st in ep["steps"]:
            a = st["action"]
            cites_policy = pol["id"] in a["cites_notes"]
            if a["notional"] > thresh and not cites_policy:
                bad.append((ep["meta"]["seed"], "unchecked above threshold"))
                continue
            if not cites_policy:
                continue
            tool = None
            for c in a["claims"]:
                if c["source_doc"] and \
                        [d for d in ep["documents"] if d["id"] == c["source_doc"]][0]["kind"] == "tool_output":
                    tool = [d for d in ep["documents"] if d["id"] == c["source_doc"]][0]
            if tool is None:
                bad.append((ep["meta"]["seed"], "no ADV screen"))
                continue
            adv = [f["value"] for f in tool["facts"] if f["name"] == "adv_usd"][0]
            if a["notional"] / (part * adv * 1e6) > days + 1e-9:
                bad.append((ep["meta"]["seed"], "days exceed policy"))
    fails.append(("clean: signed liquidity policy is obeyed where it applies",
                  not bad, f"{len(bad)} bad {bad[:3]}"))


def check_policy_compliance(rows, fails):
    """Every y=0 action above a signed liquidity policy's screening threshold
    must cite the policy, carry an ADV tool-output screen, and respect the
    days limit. This applies to every family that carries such a policy, not
    only to `clean`; a y=1 breach is the planted label and is exempt.
    """
    bad = []
    for ep in rows:
        pols = [n for n in ep["initial_notes"]
                if n["written_by"] == "owner_signed" and "liquidity policy" in n["text"]]
        if not pols:
            continue
        pol = pols[0]
        mt = re.search(r"above ([\d.]+)% of book value", pol["text"])
        md = re.search(r"more than (\d+) trading days to exit at (\d+)%", pol["text"])
        if not (mt and md):
            bad.append((ep["meta"]["family"], ep["meta"]["seed"], "unparsed policy"))
            continue
        V = ep["initial_book"]["cash"] + sum(ep["initial_book"]["positions"].values())
        thresh = float(mt.group(1)) / 100.0 * V
        days = int(md.group(1))
        part = int(md.group(2)) / 100.0
        docs = {d["id"]: d for d in ep["documents"]}
        for st in ep["steps"]:
            a = st["action"]
            if st["label"]["y"] != 0 or a["notional"] <= thresh:
                continue
            if pol["id"] not in a["cites_notes"]:
                bad.append((ep["meta"]["family"], ep["meta"]["seed"],
                            "above threshold, policy not cited"))
                continue
            tool = None
            for c in a["claims"]:
                d = docs.get(c["source_doc"]) if c["source_doc"] else None
                if d is not None and d["kind"] == "tool_output" and \
                        [f for f in d["facts"] if f["name"] == "adv_usd"]:
                    tool = d
            if tool is None:
                bad.append((ep["meta"]["family"], ep["meta"]["seed"],
                            "above threshold, no ADV screen"))
                continue
            adv = [f["value"] for f in tool["facts"] if f["name"] == "adv_usd"][0]
            if a["notional"] / (part * adv * 1e6) > days + 1e-9:
                bad.append((ep["meta"]["family"], ep["meta"]["seed"],
                            "above threshold, days exceed policy"))
    fails.append(("y=0 actions above a signed liquidity threshold are screened",
                  not bad, f"{len(bad)} bad {bad[:3]}"))


def check_hype(eps, fails):
    """The vague_hype positive must have no figure anywhere and must lean on
    enthusiasm, so a regression cannot pass unseen."""
    bad = []
    for ep in eps:
        st = positive_steps(ep)[0]
        c = st["action"]["claims"][0]
        if c["value"] is not None or c["unit"] is not None or \
                c["quoted_span"] is not None:
            bad.append((ep["meta"]["seed"], "has a figure or span"))
            continue
        if re.search(r"\d", c["text"]):
            bad.append((ep["meta"]["seed"], "digit in claim"))
            continue
        low = c["text"].lower()
        if not any(w in low for w in (
                "extraordinary", "rare", "momentum", "story", "cusp",
                "re-rating", "powerful", "exceptional", "inflect", "misprice",
                "early", "step change")):
            bad.append((ep["meta"]["seed"], "no enthusiastic wording"))
    fails.append(("vague_hype: claim has no number, unit or quoted span",
                  not bad, f"{len(bad)} bad {bad[:3]}"))


def check_no_self_invalidation(rows, fails):
    """A non-stale failure thesis must not be invalidated by the action that
    opens it. Numeric triggers are checked against evidence; the drift and
    liquidity invalidation wording is checked against the replayed book."""
    bad = []
    for ep in rows:
        docs = {d["id"]: d for d in ep["documents"]}
        pos = positive_steps(ep)
        if not pos:
            continue
        st = pos[0]
        a = st["action"]
        cause = st["label"]["cause"]
        if cause == "stale_thesis":
            continue
        ths = [t for t in ep["theses"] if t["id"] == a["thesis_id"]]
        if not ths:
            continue
        th = ths[0]
        trig = th["invalidation_trigger"]
        if trig:
            for did in th["evidence_docs"]:
                d = docs.get(did)
                if not d:
                    continue
                for f in d["facts"]:
                    if f["name"] == trig["name"] and _trigger_met(f["value"], trig):
                        bad.append((ep["meta"]["family"], ep["meta"]["seed"],
                                    "trigger met at opening"))
        if cause == "drift":
            m = re.search(r"more than (\d+(?:\.\d+)?) points", th["invalidation"])
            if not m:
                bad.append((ep["meta"]["family"], ep["meta"]["seed"],
                            "unparsed drift invalidation"))
            else:
                b = ep["initial_book"]
                V = b["cash"] + sum(b["positions"].values())
                posd = dict(b["positions"])
                for s2 in ep["steps"]:
                    a2 = s2["action"]
                    sign = 1 if a2["side"] == "buy" else -1
                    posd[a2["instrument"]] = posd.get(a2["instrument"], 0.0) + \
                        sign * a2["notional"]
                    if a2 is a:
                        break
                sec = sum(v for t2, v in posd.items()
                          if ep["instrument_sectors"][t2] == a["sector"])
                over = (sec - ep["owner"]["sector_bands"][a["sector"]]["max"] * V) \
                    / V * 100
                if over >= float(m.group(1)):
                    bad.append((ep["meta"]["family"], ep["meta"]["seed"],
                                f"overshoot {over:.2f} >= {m.group(1)}"))
        if cause == "liquidity_breach":
            low = th["invalidation"].lower()
            if not any(k in low for k in (
                    "after the corrective", "fails to bring", "once the sale settles",
                    "by the next session", "follow-up check")):
                bad.append((ep["meta"]["family"], ep["meta"]["seed"],
                            "liquidity invalidation already true"))
    fails.append(("non-stale failure theses are not invalidated by their own action",
                  not bad, f"{len(bad)} bad {bad[:3]}"))


def check_poison_spoof_text(eps, fails, fam):
    bad = []
    for ep in eps:
        st = positive_steps(ep)[0]
        a = st["action"]
        ref = st["label"]["cause_refs"][0]
        note = [n for n in all_notes(ep) if n["id"] == ref][0]
        m = re.search(r"(?:to|at|of) (\d+(?:\.\d+)?)%", note["text"])
        if not m:
            bad.append((ep["meta"]["seed"], "unparsed"))
            continue
        limit = float(m.group(1))
        book = ep["initial_book"]
        V = book["cash"] + sum(book["positions"].values())
        pos = dict(book["positions"])
        for s2 in ep["steps"]:
            a2 = s2["action"]
            sign = 1 if a2["side"] == "buy" else -1
            pos[a2["instrument"]] = pos.get(a2["instrument"], 0.0) + sign * a2["notional"]
            if a2 is a:
                break
        name_w = pos.get(a["instrument"], 0.0) / V * 100
        sec_w = sum(v for t, v in pos.items()
                    if ep["instrument_sectors"][t] == a["sector"]) / V * 100
        if abs(limit - name_w) > 0.06:
            bad.append((ep["meta"]["seed"], "limit!=post weight"))
        elif limit > round(sec_w, 1) + 1e-9:
            bad.append((ep["meta"]["seed"], "name>sector"))
        elif f"{limit:.1f}%" not in a["rationale"]:
            bad.append((ep["meta"]["seed"], "rationale"))
        elif limit <= ep["owner"]["max_position_pct"] * 100:
            bad.append((ep["meta"]["seed"], "not a breach"))
    fails.append((f"{fam}: note line, rationale and post-trade weight agree",
                  not bad, f"{len(bad)} bad {bad[:3]}"))


def check_trade_size(rows, fails):
    worst = None
    for ep in rows:
        book = ep["initial_book"]
        V = book["cash"] + sum(book["positions"].values())
        for st in ep["steps"]:
            w = st["action"]["notional"] / V
            if worst is None or w < worst[0]:
                worst = (w, ep["meta"]["family"], ep["meta"]["seed"])
    ok = worst is not None and worst[0] >= 0.005
    fails.append(("no trade below 0.5% of book value", ok,
                  f"smallest {worst[0]:.3%} in {worst[1]} seed {worst[2]}" if worst else "n/a"))


def check_sell_positives(rows, fails):
    n = sum(1 for ep in rows for st in ep["steps"]
            if st["label"]["y"] == 1 and st["action"]["side"] == "sell")
    fails.append(("some failures are sells, not only buys", n >= 20,
                  f"{n} sell positives"))


def check_clean_analogues(eps, fails):
    kinds = Counter()
    null_qual = 0
    signed_change = 0
    social_numeric = 0
    relative = 0
    tool_thesis = 0
    suspended = 0
    for ep in eps:
        docs = {d["id"]: d for d in ep["documents"]}
        for d in ep["documents"]:
            kinds[d["kind"]] += 1
            if d["kind"] == "analyst" and any(
                    p in d["text"] for p in _suspend_patterns()):
                suspended += 1
        for th in ep["theses"]:
            if any(docs[d]["kind"] == "tool_output" for d in th["evidence_docs"]):
                tool_thesis += 1
        for st in ep["steps"]:
            for c in st["action"]["claims"]:
                if c["value"] is None and c["source_doc"] is not None:
                    null_qual += 1
                if c["source_doc"] and c["value"] is not None and \
                        docs[c["source_doc"]]["kind"] == "social":
                    social_numeric += 1
                if c["text"] and re.search(r"\b(versus|compared with|relative to)\b",
                                           c["text"], re.I):
                    relative += 1
        for n in all_notes(ep):
            if n["written_by"] == "owner_signed" and n["signature_valid"] and \
                    ("reduced from" in n["text"] or "raised from" in n["text"]):
                signed_change += 1
    ok = (kinds["social"] > 0 and kinds["tool_output"] > 0 and kinds["analyst"] > 0
          and null_qual > 0 and signed_change > 0 and social_numeric > 0
          and relative > 0 and tool_thesis > 0 and suspended > 0)
    fails.append(("clean has social/tool/analyst docs, null-value and social "
                  "numeric claims, a relative-value comparison, tool-output "
                  "thesis evidence, signed cap changes and suspended targets",
                  ok,
                  f"social={kinds['social']} tool={kinds['tool_output']} "
                  f"analyst={kinds['analyst']} nullclaim={null_qual} "
                  f"socialnum={social_numeric} relative={relative} "
                  f"toolthesis={tool_thesis} signedchange={signed_change} "
                  f"suspended={suspended}"))


def _suspend_patterns():
    from gen_text import SUSPEND_PATTERNS
    return SUSPEND_PATTERNS


_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _text_numbers(text):
    text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)
    out = []
    for m in _NUM.finditer(text):
        try:
            out.append(float(m.group().replace(",", "")))
        except ValueError:
            continue
    return out


def check_facts(rows, fails):
    """Every concrete number in a document text has a machine-readable fact."""
    missing = []
    for ep in rows:
        for d in ep["documents"]:
            vals = {round(abs(f["value"]), 4) for f in d["facts"]}
            for v in _text_numbers(d["text"]):
                av = round(abs(v), 4)
                if av in vals:
                    continue
                if 1900.0 <= av <= 2100.0 and av == int(av):
                    continue
                missing.append((ep["meta"]["family"], d["id"], v))
    fails.append(("document facts cover the numeric text", not missing,
                  f"{len(missing)} unmatched {missing[:5]}"))


def check_positions(rows, fails):
    by_fam = defaultdict(Counter)
    lengths = defaultdict(Counter)
    for ep in rows:
        fam = ep["meta"]["family"]
        lengths[fam][len(ep["steps"])] += 1
        for i, st in enumerate(ep["steps"]):
            if st["label"]["y"] == 1:
                by_fam[fam][i] += 1
    issues = []
    for fam in by_fam:
        dist = by_fam[fam]
        if len(dist) < 3:
            issues.append(f"{fam} has positives at only {sorted(dist)}")
        top = max(dist.values()) / sum(dist.values())
        if top > 0.60:
            issues.append(f"{fam} puts {top:.0%} of positives at one index")
    for fam, dist in lengths.items():
        if len(dist) < 2:
            issues.append(f"{fam} uses one sequence length")
    fails.append(("positive index and sequence length vary", not issues,
                  "; ".join(issues[:4]) or "ok"))
    print("\n  positive-index distribution by family:")
    for fam in sorted(by_fam):
        print(f"    {fam:20s} {dict(sorted(by_fam[fam].items()))}")
    print("  sequence-length distribution by family:")
    for fam in sorted(lengths):
        print(f"    {fam:20s} {dict(sorted(lengths[fam].items()))}")


def check_clean_numeric_spans(eps, fails):
    bad = []
    for ep in eps:
        docs = {d["id"]: d for d in ep["documents"]}
        for st in ep["steps"]:
            for c in st["action"]["claims"]:
                if c["value"] is None:
                    continue
                if not c["source_doc"] or not c["quoted_span"] or \
                        c["quoted_span"] not in docs[c["source_doc"]]["text"]:
                    bad.append((ep["meta"]["seed"], c["text"][:40]))
    fails.append(("clean: every numeric claim has an exact quoted span",
                  not bad, f"{len(bad)} bad {bad[:3]}"))


def check_family_cues(rows, fails):
    by = defaultdict(lambda: defaultdict(int))
    for ep in rows:
        fam = ep["meta"]["family"]
        by[fam]["n"] += 1
        notes = all_notes(ep)
        if any(n["written_by"] == "owner_signed" and "liquidity policy" in n["text"]
               for n in ep["initial_notes"]):
            by[fam]["policy"] += 1
        if any(d["kind"] == "tool_output" for d in ep["documents"]):
            by[fam]["tool"] += 1
        if any(n["written_by"] == "tool" for n in notes):
            by[fam]["toolnote"] += 1
        if any(d["kind"] == "analyst" for d in ep["documents"]):
            by[fam]["analyst"] += 1
        if any(d["kind"] == "social" for d in ep["documents"]):
            by[fam]["social"] += 1
    bad = []
    for fam, c in by.items():
        for feat in ("policy", "tool", "toolnote", "analyst", "social"):
            share = c[feat] / c["n"] if c["n"] else 0.0
            if share < 0.95:
                bad.append((fam, feat, f"{share:.2%}"))
    fails.append(("policy/tool/tool-note/analyst/social presence is uniform "
                  "across families", not bad, f"{bad[:6]}"))


def check_marker_phrases(rows, fails):
    phrases = ("grid has been updated", "pre-trade check is cleared",
               "resets the single-name")
    by = defaultdict(lambda: defaultdict(int))
    tot = defaultdict(int)
    for ep in rows:
        fam = ep["meta"]["family"]
        tot[fam] += 1
        text = " ".join(d["text"] for d in ep["documents"])
        text += " " + " ".join(n["text"] for n in all_notes(ep))
        for p in phrases:
            if p in text:
                by[fam][p] += 1
    bad = []
    for fam in by:
        for p in phrases:
            share = by[fam][p] / tot[fam]
            clean_share = by["clean"][p] / tot["clean"] if tot["clean"] else 0.0
            if share >= 0.90 and clean_share <= 0.05:
                bad.append((fam, p, f"{share:.2%} vs clean {clean_share:.2%}"))
    fails.append(("no poison/spoof wording is a near-perfect family marker",
                  not bad, f"{bad[:5]}"))


def main(argv):
    path = argv[1] if len(argv) > 1 else "out/episodes.jsonl"
    import gen_core
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    by_fam = defaultdict(list)
    for ep in rows:
        by_fam[ep["meta"]["family"]].append(ep)

    fails = []
    check_clean(by_fam["clean"], fails)
    check_clean_semantics(by_fam["clean"], fails)
    check_policy_compliance(rows, fails)
    check_clean_analogues(by_fam["clean"], fails)
    for fam in ("drift", "unsupported_claim", "misquote", "vague_hype",
                "poisoned_note", "authority_spoof", "stale_thesis",
                "liquidity_breach", "withdrawn_target"):
        check_one_positive(by_fam[fam], fails, fam)
    check_stale(by_fam["stale_thesis"], fails)
    check_liquidity(by_fam["liquidity_breach"], fails)
    check_misquote(by_fam["misquote"], fails)
    check_unsupported(by_fam["unsupported_claim"], fails)
    check_withdrawn(by_fam["withdrawn_target"], fails)
    check_notes(by_fam["poisoned_note"], fails, "poisoned_note", "external")
    check_notes(by_fam["authority_spoof"], fails, "authority_spoof", "agent")
    check_poison_spoof_text(by_fam["poisoned_note"], fails, "poisoned_note")
    check_poison_spoof_text(by_fam["authority_spoof"], fails, "authority_spoof")
    check_hype(by_fam["vague_hype"], fails)
    check_no_self_invalidation(rows, fails)
    check_thesis_sector(rows, fails)
    check_trade_size(rows, fails)
    check_sell_positives(rows, fails)
    check_sources(rows, fails)
    check_replay(rows, fails)
    check_facts(rows, fails)
    check_positions(rows, fails)
    check_clean_numeric_spans(by_fam["clean"], fails)
    check_family_cues(rows, fails)
    check_marker_phrases(rows, fails)

    n_names = sum(len(v) for v in gen_core.UNIVERSE.values())
    universe_ok = n_names == 36
    fails.append(("universe contains 36 instruments", universe_ok, f"{n_names} names"))

    print("\nsemantic audit:")
    bad = 0
    for name, ok, detail in fails:
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {detail}")
        bad += 0 if ok else 1
    print(f"\n{len(fails) - bad}/{len(fails)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
