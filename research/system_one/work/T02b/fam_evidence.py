"""Evidence inversion: a low-trust source is preferred to a contradicting filing."""
from __future__ import annotations

import phrasing
from common import (COMPANY, clean_rationale, exact_claims, failure_buy,
                   make_world, new_doc_buy, open_notes, open_step, pick_buy,
                   pick_sell, sell_notional, trim_step)
from textlib import SECTORS, fmt, phrase


def _order_doc(w, rng, inst, t, low=True):
    co = COMPANY[inst]
    sector = w.instrument_sectors[inst]
    if low:
        og = round(rng.uniform(0.4, 3.2), 2)
        rg = round(rng.uniform(4.0, 15.0), 2)
        gm = round(rng.uniform(27.0, 61.0), 2)
        s1 = phrase(rng, "order_growth", co, og, sector)
        s2 = phrase(rng, "revenue_growth", co, rg, sector)
        s3 = phrase(rng, "gross_margin", co, gm, sector)
        facts = [{"name": "order_growth", "value": og, "unit": "%"},
                 {"name": "revenue_growth", "value": rg, "unit": "%"},
                 {"name": "gross_margin", "value": gm, "unit": "%"}]
        spans = {"order_growth": s1, "revenue_growth": s2, "gross_margin": s3}
        return w.add_custom_doc("filing", t, " ".join([s1, s2, s3]), facts, spans)
    og = round(rng.uniform(18.0, 31.0), 2)
    si = round(rng.uniform(1.0, 11.0), 2)
    ff = round(rng.uniform(0.2, 3.8), 2)
    s1 = phrase(rng, "order_growth", co, og, sector)
    s2 = phrase(rng, "short_interest", co, si, sector)
    s3 = phrase(rng, "fund_flow", co, ff, sector)
    facts = [{"name": "order_growth", "value": og, "unit": "%"},
             {"name": "short_interest", "value": si, "unit": "%"},
             {"name": "fund_flow", "value": ff, "unit": "$B"}]
    spans = {"order_growth": s1, "short_interest": s2, "fund_flow": s3}
    return w.add_custom_doc("social", t, " ".join([s1, s2, s3]), facts, spans)


def generate(seed: int, shifted: bool = False) -> dict:
    w, rng = make_world(seed, "evidence_inversion", shifted)
    notes = open_notes(w, rng, "evidence")
    w.initial_notes.extend(notes)
    policy = notes[1]

    inst1, n1 = pick_buy(w, rng, need=0.005)
    t1 = rng.randint(90, 135)
    doc1 = _order_doc(w, rng, inst1, t1 - 10, low=True)
    co1 = COMPANY[inst1]
    og, _ = w.fact(doc1, "order_growth")
    rg, _ = w.fact(doc1, "revenue_growth")
    sector1 = w.instrument_sectors[inst1]
    statement = phrasing.sector_statement(rng, sector1, rg, co1)
    invalidation, trigger = phrasing.leverage_invalidation(rng, sector1)
    th1 = w.thesis(statement, sector1, t1, [doc1], invalidation, trigger)
    claims = exact_claims(w, rng, doc1, ["order_growth", "revenue_growth"], co1)
    w.add_step(t1, inst1, "buy", n1, th1, True, claims, [],
               clean_rationale(w, rng, co1, "revenue_growth", doc1))

    inst2, n2 = pick_buy(w, rng, sectors=[w.instrument_sectors[inst1]],
                         need=0.003)
    t2 = t1 + rng.randint(35, 70)
    if inst2 is not None:
        # A same-name continuation must not use a lower-tier source that
        # conflicts with the filing already on file; use a filing in that case.
        kind2 = "news" if inst2 != inst1 else "filing"
        new_doc_buy(w, rng, t2, inst2, n2, th1, kind2,
                    ["revenue_growth", "gross_margin"])
    else:
        t2 = t1 + 40

    t3 = t2 + rng.randint(35, 75)
    sector1 = w.instrument_sectors[inst1]
    inst3, n3 = failure_buy(w, rng, sector1)
    if inst3 is None:
        inst3, n3 = pick_buy(w, rng, sectors=[sector1], need=0.001, safety=0.995)
    doc_low = _order_doc(w, rng, inst3, t3 - 12, low=True)
    doc_chat = _order_doc(w, rng, inst3, t3 - 5, low=False)
    high, _ = w.fact(doc_chat, "order_growth")
    co3 = COMPANY[inst3]
    claims = exact_claims(w, rng, doc_chat, ["order_growth"], co3)
    rtext = clean_rationale(w, rng, co3, "order_growth", doc_chat)
    w.add_step(
        t3, inst3, "buy", n3, th1, False, claims, [], rtext,
        y=1, cause="evidence_inversion",
        cause_refs=[doc_chat, doc_low, policy["id"]])

    t4 = t3 + rng.randint(35, 75)
    n4 = sell_notional(w, rng, inst1)
    if n4 is not None:
        trim_step(w, rng, t4, inst1, n4, th1, doc1, "revenue_growth", co1)
    else:
        inst_s, n_s = pick_sell(w, rng, sectors=[sector1])
        if inst_s is not None:
            doc_s = w.add_doc("news", sector1, inst_s, t4 - rng.randint(5, 9),
                              ["revenue_growth"])
            trim_step(w, rng, t4, inst_s, n_s, th1, doc_s, "revenue_growth",
                      COMPANY[inst_s])

    inst5, n5 = pick_buy(w, rng, sectors=[s for s in SECTORS
                                          if s != w.instrument_sectors[inst1]],
                         need=0.003)
    if inst5 is None:
        inst5, n5 = pick_buy(w, rng, need=0.003)
    t5 = t4 + rng.randint(40, 80)
    th2, doc5 = open_step(w, rng, t5, inst5, n5, "filing",
                          ["revenue_growth", "eps_growth"])

    inst6, n6 = pick_buy(w, rng, sectors=[w.instrument_sectors[inst5]],
                         need=0.003)
    t6 = t5 + rng.randint(35, 75)
    if inst6 is not None:
        new_doc_buy(w, rng, t6, inst6, n6, th2, "analyst",
                    ["order_growth", "valuation_multiple"])
    return w.episode("Halvorsen Risk Desk")
