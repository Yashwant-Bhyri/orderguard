"""Vague hype: a full-size decision resting on adjectives, not figures."""
from __future__ import annotations

from common import (COMPANY, failure_buy, make_world, new_doc_buy, open_step,
                   open_notes, pick_buy, sell_notional, trim_step)
from textlib import SECTORS, hype_claim, hype_rationale


def generate(seed: int, shifted: bool = False) -> dict:
    w, rng = make_world(seed, "vague_hype", shifted)
    w.initial_notes.extend(open_notes(w, rng))

    inst1, n1 = pick_buy(w, rng, need=0.005)
    t1 = rng.randint(90, 135)
    th1, doc1 = open_step(w, rng, t1, inst1, n1, "filing",
                          ["revenue_growth", "gross_margin"])

    inst2, n2 = pick_buy(w, rng, sectors=[w.instrument_sectors[inst1]],
                         need=0.003)
    t2 = t1 + rng.randint(35, 75)
    if inst2 is not None:
        new_doc_buy(w, rng, t2, inst2, n2, th1, "news",
                    ["order_growth", "forward_guidance_growth"])
    else:
        t2 = t1 + 40

    t3 = t2 + rng.randint(35, 75)
    inst3, n3 = failure_buy(w, rng, w.instrument_sectors[inst1])
    if inst3 is None:
        inst3, n3 = pick_buy(w, rng, sectors=[w.instrument_sectors[inst1]],
                             need=0.001, safety=0.995)
    company3 = COMPANY[inst3]
    doc3 = w.add_doc("news", w.instrument_sectors[inst3], inst3, t3 - 5,
                     ["order_growth", "revenue_growth"])
    claims = []
    for _ in range(rng.randint(1, 2)):
        src = doc3 if rng.random() < 0.6 else None
        claims.append(hype_claim(rng, company3, source=src))
    w.add_step(t3, inst3, "buy", n3, th1, False, claims, [],
               hype_rationale(rng, company3),
               y=1, cause="vague_hype", cause_refs=[])

    t4 = t3 + rng.randint(40, 80)
    n4 = sell_notional(w, rng, inst1)
    if n4 is not None:
        trim_step(w, rng, t4, inst1, n4, th1, doc1, "gross_margin", COMPANY[inst1])

    inst5, n5 = pick_buy(w, rng, sectors=[s for s in SECTORS
                                          if s != w.instrument_sectors[inst3]],
                         need=0.004)
    if inst5 is None:
        inst5, n5 = pick_buy(w, rng, need=0.004)
    t5 = t4 + rng.randint(40, 85)
    th2, doc5 = open_step(w, rng, t5, inst5, n5, "filing",
                          ["revenue_growth", "eps_growth"])

    inst6, n6 = pick_buy(w, rng, sectors=[w.instrument_sectors[inst5]],
                         need=0.003)
    t6 = t5 + rng.randint(35, 80)
    if inst6 is not None:
        new_doc_buy(w, rng, t6, inst6, n6, th2, "analyst",
                    ["order_growth", "valuation_multiple"])
    return w.episode("Halvorsen Risk Desk")
