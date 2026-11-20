"""Surface variety shared by every family (round 4).

Two jobs:
1. Give some clean BUY actions a plain, qualitative compliance claim instead of
   their numeric quote. The plain claim is NOT source-less: it rests on a new
   tool-output pre-trade check document that states the projected post-order
   sector and single-name weights, and it quotes an exact span of that check.
   The claim is only emitted when the scope it asserts is actually true after
   replaying the book through that action. Sells and explicit relative-value
   comparisons are never overwritten, so the trim / rebalance / peer-comparison
   hard negatives keep their claims.
2. Add ordinary, benign notes (tool/agent/external relay logs carrying a
   published figure, with no instructions) to about half of the steps that have
   no pre-notes.
"""
import random

import text_pools as pools
from world import document, note, note_id, rng_for

SECTORS = ("tech", "consumer", "healthcare", "staples", "financials", "energy", "index")
COMPARISON_WORDS = ("versus", "compared with", "compared to", "relative to")


def _issuer_for(ep, action):
    """The issuer behind the traded line, parsed from the episode's own docs."""
    sector = action["sector"]
    docs = ep["documents"]
    try:
        if sector == "tech":
            for d in docs:
                if d["text"].startswith("For "):
                    return d["text"].split("For ", 1)[1].split(",", 1)[0]
        if sector == "consumer":
            for d in docs:
                if d["text"].startswith("Comparable store sales at "):
                    return d["text"].split(" at ", 1)[1].split(" increased", 1)[0]
        if sector == "staples":
            for d in docs:
                if d["text"].startswith("Cash at "):
                    return d["text"].split(" at ", 1)[1].split(" covered", 1)[0]
    except (IndexError, KeyError):
        pass
    return "the sleeve"


def _replay_through(ep, index):
    """Book state after step `index`; returns (positions, cash, value)."""
    book = ep["initial_book"]
    positions = {k: float(v) for k, v in book["positions"].items()}
    cash = float(book["cash"])
    value = cash + sum(positions.values())
    for s in ep["steps"][: index + 1]:
        a = s["action"]
        n = float(a["notional"])
        if a["side"] == "buy":
            cash -= n
            positions[a["instrument"]] = positions.get(a["instrument"], 0.0) + n
        else:
            cash += n
            positions[a["instrument"]] = positions.get(a["instrument"], 0.0) - n
    return positions, cash, value


def _weights(ep, index):
    positions, cash, value = _replay_through(ep, index)
    isec = ep["instrument_sectors"]
    weights = {s: 0.0 for s in SECTORS}
    for inst, v in positions.items():
        weights[isec[inst]] += v / value
    return positions, weights, value


def _scope_holds(ep, index, scope):
    positions, weights, value = _weights(ep, index)
    if _replay_through(ep, index)[1] < 0 or any(v < 0 for v in positions.values()):
        return False
    owner = ep["owner"]
    action = ep["steps"][index]["action"]
    if scope == "sector":
        b = owner["sector_bands"][action["sector"]]
        return b["min"] - 1e-9 <= weights[action["sector"]] <= b["max"] + 1e-9
    if scope == "instrument":
        return positions.get(action["instrument"], 0.0) / value <= owner["max_position_pct"] + 1e-9
    for s in SECTORS:
        b = owner["sector_bands"][s]
        if not (b["min"] - 1e-9 <= weights[s] <= b["max"] + 1e-9):
            return False
    return all(v / value <= owner["max_position_pct"] + 1e-9 for v in positions.values())


def _pretrade_doc(ep, index, rng):
    """A tool-output pre-trade check sourcing a qualitative compliance claim."""
    action = ep["steps"][index]["action"]
    positions, weights, value = _weights(ep, index)
    owner = ep["owner"]
    sector = action["sector"]
    band = owner["sector_bands"][sector]
    sw = weights[sector] * 100.0
    iw = positions.get(action["instrument"], 0.0) / value * 100.0
    cap = owner["max_position_pct"] * 100.0
    issuer = _issuer_for(ep, action)
    text = rng.choice(pools.PRETRADE_CHECK).format(
        side=action["side"], notional=action["notional"], instrument=action["instrument"],
        issuer=issuer, sector=sector, sw=sw, lo=band["min"] * 100.0, hi=band["max"] * 100.0,
        iw=iw, cap=cap)
    doc = document(f"D{len(ep['documents'])}", "tool_output",
                   rng.choice(pools.PRETRADE_PUBLISHERS), 1, action["t"] - 1, text,
                   [{"name": "projected_sector_weight", "value": round(sw, 2), "unit": "%"},
                    {"name": "projected_instrument_weight", "value": round(iw, 2), "unit": "%"}])
    ep["documents"].append(doc)
    ep["documents"].sort(key=lambda d: d["t"])
    return doc, cap


def apply(ep, seed, family, shifted=False):
    rng = rng_for(seed, family + "_variety", shifted)
    for i, step in enumerate(ep["steps"]):
        action = step["action"]
        quantified = any(ch.isdigit() for ch in action["rationale"])
        is_comparison = any(w in c["text"].lower() for c in action["claims"] for w in COMPARISON_WORDS)
        # Only clean buys whose rationale already names a figure, and never a
        # relative-value comparison (preserve that hard negative's claim).
        if (step["label"]["y"] == 0 and quantified and action["side"] == "buy"
                and not is_comparison and rng.random() < 0.25):
            issuer = _issuer_for(ep, action)
            eligible = [(scope, text) for scope, text in pools.PLAIN_CLAIM
                        if _scope_holds(ep, i, scope)]
            if eligible:
                scope, text = rng.choice(eligible)
                doc, cap = _pretrade_doc(ep, i, rng)
                span = next((s.format(cap=cap) for s in pools.PRETRADE_SPANS[scope]
                             if s.format(cap=cap) in doc["text"]), None)
                if span is not None:
                    action["claims"] = [{"text": text.format(issuer=issuer), "value": None,
                                         "unit": None, "source_doc": doc["id"], "quoted_span": span}]
        if step["pre_notes"] or rng.random() < 0.5:
            continue
        usable = [d for d in ep["documents"] if d["t"] <= action["t"] and d["facts"]
                  and d["kind"] != "tool_output"]
        if not usable:
            continue
        doc = rng.choice(usable)
        fact = rng.choice(doc["facts"])
        if doc["text"].startswith("For "):
            issuer = doc["text"].split("For ", 1)[1].split(",", 1)[0]
        elif doc["text"].startswith("Comparable store sales at "):
            issuer = doc["text"].split(" at ", 1)[1].split(" increased", 1)[0]
        elif doc["text"].startswith("Cash at "):
            issuer = doc["text"].split(" at ", 1)[1].split(" covered", 1)[0]
        else:
            issuer = doc["publisher"]
        text = rng.choice(pools.BENIGN_NOTE).format(issuer=issuer, metric=fact["name"].replace("_", " "),
                                                    value=fact["value"], unit=fact["unit"])
        writer = rng.choice(("tool", "agent", "external"))
        step["pre_notes"] = [note(note_id(seed, 10 + i), action["t"] - 1, text, writer=writer)]
    return ep
