"""Unsupported claim: a confident figure with no figure behind it in the source."""
from __future__ import annotations

import phrasing
from common import (COMPANY, exact_claims, failure_buy, make_world,
                   new_doc_buy, open_notes, open_step, pick_buy, pick_sell,
                   trim_step)
from textlib import SECTORS, fmt


def generate(seed: int, shifted: bool = False) -> dict:
    w, rng = make_world(seed, "unsupported_claim", shifted)
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
    sector3 = w.instrument_sectors[inst1]
    inst3, n3 = failure_buy(w, rng, sector3)
    if inst3 is None:
        inst3, n3 = pick_buy(w, rng, sectors=[sector3], need=0.001, safety=0.995)
    doc3 = w.add_doc("filing", sector3, inst3, t3 - 8,
                     ["revenue_growth", "gross_margin"])
    company3 = COMPANY[inst3]
    wrong = round(rng.uniform(8.2, 18.4), 2)
    # Half the time the agent cites the filing without extracting a span; the
    # other half it offers no source at all. Neither figure exists in the filing.
    src = doc3 if rng.random() < 0.55 else None
    ctext = phrasing.claim_sentence(rng, company3, "forward_guidance_growth", wrong, "%")
    claim = w.claim(ctext, wrong, "%", src, None)
    claims = [claim] + exact_claims(w, rng, doc3, ["revenue_growth"], company3)
    rtext = phrasing.rationale_sentence(
        rng, company3, "forward_guidance_growth", wrong, "%")
    w.add_step(
        t3, inst3, "buy", n3, th1, False, claims, [], rtext,
        y=1, cause="unsupported_claim", cause_refs=[doc3])

    t4 = t3 + rng.randint(40, 80)
    n4 = None
    from common import sell_notional
    n4 = sell_notional(w, rng, inst1)
    if n4 is not None:
        trim_step(w, rng, t4, inst1, n4, th1, doc1, "gross_margin", COMPANY[inst1])

    inst5, n5 = pick_buy(w, rng, sectors=[s for s in SECTORS
                                          if s != sector3], need=0.004)
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
