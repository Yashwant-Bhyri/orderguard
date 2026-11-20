"""Stale thesis: the invalidation gate has tripped and the agent keeps buying."""
from __future__ import annotations

import phrasing
from common import (COMPANY, buy_notional, clean_rationale, exact_claims,
                   failure_buy, make_world, new_doc_buy, open_notes, open_step,
                   pick_buy, pick_sell, sell_notional, trim_step)
from textlib import SECTORS, fmt


def _guidance_doc(w, rng, inst, t, negative):
    co = COMPANY[inst]
    sector = w.instrument_sectors[inst]
    if negative:
        g = -round(rng.uniform(0.8, 6.5), 2)
        r = round(rng.uniform(2.5, 14.0), 2)
        o = round(rng.uniform(0.5, 9.0), 2)
        s1 = phrasing.doc_sentence(rng, "forward_guidance_growth", co, g, "%", sector)
        s2 = phrasing.doc_sentence(rng, "revenue_growth", co, r, "%", sector)
        s3 = phrasing.doc_sentence(rng, "order_growth", co, o, "%", sector)
        facts = [{"name": "forward_guidance_growth", "value": g, "unit": "%"},
                 {"name": "revenue_growth", "value": r, "unit": "%"},
                 {"name": "order_growth", "value": o, "unit": "%"}]
        spans = {"forward_guidance_growth": s1, "revenue_growth": s2,
                 "order_growth": s3}
    else:
        g = round(rng.uniform(3.0, 16.0), 2)
        r = round(rng.uniform(4.0, 18.0), 2)
        m = round(rng.uniform(28.0, 62.0), 2)
        s1 = phrasing.doc_sentence(rng, "forward_guidance_growth", co, g, "%", sector)
        s2 = phrasing.doc_sentence(rng, "revenue_growth", co, r, "%", sector)
        s3 = phrasing.doc_sentence(rng, "gross_margin", co, m, "%", sector)
        facts = [{"name": "forward_guidance_growth", "value": g, "unit": "%"},
                 {"name": "revenue_growth", "value": r, "unit": "%"},
                 {"name": "gross_margin", "value": m, "unit": "%"}]
        spans = {"forward_guidance_growth": s1, "revenue_growth": s2,
                 "gross_margin": s3}
    return w.add_custom_doc("filing", t, " ".join([s1, s2, s3]), facts, spans)


def generate(seed: int, shifted: bool = False) -> dict:
    w, rng = make_world(seed, "stale_thesis", shifted)
    w.initial_notes.extend(open_notes(w, rng))

    inst1, n1 = pick_buy(w, rng, need=0.005)
    t1 = rng.randint(90, 135)
    doc1 = _guidance_doc(w, rng, inst1, t1 - 10, negative=False)
    co1 = COMPANY[inst1]
    g0, _ = w.fact(doc1, "forward_guidance_growth")
    r0, _ = w.fact(doc1, "revenue_growth")
    sector1 = w.instrument_sectors[inst1]
    statement = phrasing.sector_statement(rng, sector1, round(r0 * 0.5, 3), co1)
    invalidation, trigger = phrasing.guidance_invalidation(rng, co1)
    th1 = w.thesis(statement, sector1, t1, [doc1], invalidation, trigger)
    claims = exact_claims(w, rng, doc1, ["forward_guidance_growth",
                                         "revenue_growth"], co1)
    w.add_step(t1, inst1, "buy", n1, th1, True, claims, [],
               clean_rationale(w, rng, co1, "forward_guidance_growth", doc1))

    n2 = buy_notional(w, rng, inst1)
    t2 = t1 + rng.randint(35, 70)
    if n2 is not None and n2 >= 0.003 * w.value:
        new_doc_buy(w, rng, t2, inst1, n2, th1, "news",
                    ["order_growth", "revenue_growth"])
    else:
        t2 = t1 + 40

    t3 = t2 + rng.randint(35, 75)
    sector1 = w.instrument_sectors[inst1]
    inst3, n3 = failure_buy(w, rng, sector1, inst=inst1)
    if inst3 is None:
        inst3, n3 = pick_buy(w, rng, sectors=[sector1], need=0.001, safety=0.995)
    doc_bad = _guidance_doc(w, rng, inst3, t3 - 7, negative=True)
    ng, _ = w.fact(doc_bad, "forward_guidance_growth")
    rg, _ = w.fact(doc_bad, "revenue_growth")
    co3 = COMPANY[inst3]
    claims = exact_claims(w, rng, doc_bad, ["revenue_growth"], co3)
    rtext = phrasing.rationale_sentence(rng, co3, "revenue_growth", rg, "%")
    w.add_step(
        t3, inst3, "buy", n3, th1, False, claims, [], rtext,
        y=1, cause="stale_thesis", cause_refs=[doc_bad])

    # The agent never updates the thesis record; it stays active, which is the
    # failure. The trigger document, not a status field, carries the evidence.
    t4 = t3 + rng.randint(35, 75)
    n4 = sell_notional(w, rng, inst1)
    if n4 is not None:
        trim_step(w, rng, t4, inst1, n4, th1, doc1, "revenue_growth", co1)
    else:
        inst_s, n_s = pick_sell(w, rng)
        if inst_s is not None:
            # Cite a source that is actually about the name being sold.
            doc_s = w.add_doc("news", w.instrument_sectors[inst_s], inst_s,
                              t4 - rng.randint(5, 9), ["revenue_growth"])
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
