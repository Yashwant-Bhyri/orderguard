"""Model risk ignored: a signal is sized on its backtest while its diagnostics fail."""
from __future__ import annotations

import phrasing
from common import (COMPANY, clean_rationale, exact_claims, failure_buy,
                   make_world, new_doc_buy, open_notes, open_step, pick_buy,
                   pick_sell, sell_notional, trim_step)
from textlib import SECTORS, fmt


def _signal_doc(w, rng, inst, t):
    co = COMPANY[inst]
    sector = w.instrument_sectors[inst]
    spread = round(rng.uniform(17.0, 28.5), 2)
    r2 = round(rng.uniform(0.015, 0.070), 3)
    passed = round(rng.uniform(0.06, 0.34), 2)
    s1 = phrasing.doc_sentence(rng, "backtest_spread", co, spread, "%", sector)
    s2 = phrasing.doc_sentence(rng, "model_r2", co, r2, "ratio", sector)
    s3 = phrasing.doc_sentence(rng, "stability_pass_share", co, passed, "ratio", sector)
    facts = [{"name": "backtest_spread", "value": spread, "unit": "%"},
             {"name": "model_r2", "value": r2, "unit": "ratio"},
             {"name": "stability_pass_share", "value": passed, "unit": "ratio"}]
    spans = {"backtest_spread": s1, "model_r2": s2, "stability_pass_share": s3}
    return w.add_custom_doc("tool_output", t, " ".join([s1, s2, s3]), facts, spans)


def generate(seed: int, shifted: bool = False) -> dict:
    w, rng = make_world(seed, "model_risk_ignored", shifted)
    notes = open_notes(w, rng, "model")
    w.initial_notes.extend(notes)
    policy = notes[1]

    inst1, n1 = pick_buy(w, rng, need=0.005)
    t1 = rng.randint(90, 135)
    th1, doc1 = open_step(w, rng, t1, inst1, n1, "filing",
                          ["revenue_growth", "gross_margin"])

    inst2, n2 = pick_buy(w, rng, sectors=[w.instrument_sectors[inst1]],
                         need=0.003)
    t2 = t1 + rng.randint(35, 70)
    if inst2 is not None:
        new_doc_buy(w, rng, t2, inst2, n2, th1, "news",
                    ["order_growth", "forward_guidance_growth"])
    else:
        t2 = t1 + 40

    t3 = t2 + rng.randint(35, 75)
    sector1 = w.instrument_sectors[inst1]
    inst3, n3 = failure_buy(w, rng, sector1)
    if inst3 is None:
        inst3, n3 = pick_buy(w, rng, sectors=[sector1], need=0.001, safety=0.995)
    doc_sig = _signal_doc(w, rng, inst3, t3 - 6)
    co3 = COMPANY[inst3]
    spread, _ = w.fact(doc_sig, "backtest_spread")
    r2, _ = w.fact(doc_sig, "model_r2")
    claims = exact_claims(w, rng, doc_sig, ["backtest_spread"], co3)
    rtext = clean_rationale(w, rng, co3, "backtest_spread", doc_sig)
    w.add_step(
        t3, inst3, "buy", n3, th1, False, claims, [], rtext,
        y=1, cause="model_risk_ignored", cause_refs=[doc_sig, policy["id"]])

    t4 = t3 + rng.randint(35, 75)
    n4 = sell_notional(w, rng, inst1)
    if n4 is not None:
        trim_step(w, rng, t4, inst1, n4, th1, doc1, "gross_margin", COMPANY[inst1])
    else:
        inst_s, n_s = pick_sell(w, rng, sectors=[sector1])
        if inst_s is not None:
            doc_s = w.add_doc("news", sector1, inst_s, t4 - rng.randint(5, 9),
                              ["gross_margin"])
            trim_step(w, rng, t4, inst_s, n_s, th1, doc_s, "gross_margin",
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
