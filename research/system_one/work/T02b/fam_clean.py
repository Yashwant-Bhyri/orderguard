"""Clean episodes: endorsable decisions with hard negatives throughout."""
from __future__ import annotations

import phrasing
from common import (COMPANY, clean_rationale, desk_note, exact_claims,
                   make_world, open_notes, pick_buy, pick_sell, sell_notional,
                   thesis_texts)
from textlib import SECTORS


def _external_note(w, rng, t, doc_id, company, sector):
    return w.note(t, phrasing.external_text(rng, company, sector),
                  written_by="external", signature_valid=False, cites=[doc_id])


def _open(w, rng, t, inst, notional, kind, metrics, pre_notes=None,
          new_notes=None, upbeat=False, cites_notes=None):
    sector = w.instrument_sectors[inst]
    doc = w.add_doc(kind, sector, inst, t - rng.randint(4, 13), metrics)
    company = COMPANY[inst]
    statement, invalidation, trigger = thesis_texts(rng, company, sector)
    th = w.thesis(statement, sector, t, [doc], invalidation, trigger)
    claims = exact_claims(w, rng, doc, metrics, company)
    cites = [n["id"] for n in (pre_notes or [])] + list(cites_notes or [])
    w.add_step(t, inst, "buy", notional, th, True, claims, cites,
               clean_rationale(w, rng, company, metrics[0], doc, upbeat),
               pre_notes=pre_notes, new_notes=new_notes)
    return th, doc


def _trim(w, rng, t, inst, thesis_id, doc, company, metric, exclude=()):
    n = sell_notional(w, rng, inst)
    if n is None:
        inst2, n = pick_sell(w, rng)
        if inst2 is None:
            return t, False
        inst = inst2
        company = COMPANY[inst]
        doc = w.add_doc("analyst", w.instrument_sectors[inst], inst, t - 6,
                        [metric, "valuation_multiple"])
        company = COMPANY[inst]
    claims = exact_claims(w, rng, doc, [metric], company)
    w.add_step(t, inst, "sell", n, thesis_id, False, claims, [],
               clean_rationale(w, rng, company, metric, doc, side="sell"))
    return t, True


def generate(seed: int, shifted: bool = False) -> dict:
    w, rng = make_world(seed, "clean", shifted)
    notes0 = open_notes(w, rng)
    w.initial_notes.extend(notes0)

    inst1, n1 = pick_buy(w, rng, need=0.006)
    t1 = rng.randint(95, 140)
    th1, doc1 = _open(w, rng, t1, inst1, n1, "filing",
                      ["revenue_growth", "gross_margin"])

    inst2, n2 = pick_buy(w, rng, sectors=[w.instrument_sectors[inst1]],
                         need=0.004)
    t2 = t1 + rng.randint(35, 80)
    if inst2 is not None:
        doc2 = w.add_doc("news", w.instrument_sectors[inst2], inst2, t2 - 7,
                         ["order_growth", "forward_guidance_growth"])
        company2 = COMPANY[inst2]
        claims = exact_claims(w, rng, doc2, ["order_growth",
                                             "forward_guidance_growth"], company2)
        chat = w.add_doc("social", w.instrument_sectors[inst2], inst2, t2 - 3,
                         ["short_interest", "fund_flow"])
        claims += exact_claims(w, rng, chat, ["short_interest", "fund_flow"],
                               company2)
        pre = [desk_note(w, rng, t2 - 4, doc1, COMPANY[inst1], "gross_margin")]
        pre.append(_external_note(w, rng, t2 - 6, doc2, company2,
                                  w.instrument_sectors[inst2]))
        w.add_step(t2, inst2, "buy", n2, th1, False, claims,
                   [n["id"] for n in pre],
                   clean_rationale(w, rng, company2, "order_growth", doc2),
                   pre_notes=pre)
    else:
        t2 = t1 + 40

    t3 = t2 + rng.randint(40, 85)
    t3, _ = _trim(w, rng, t3, inst1, th1, doc1, COMPANY[inst1], "gross_margin")

    inst4, n4 = pick_buy(w, rng, sectors=[s for s in SECTORS
                                          if s != w.instrument_sectors[inst1]],
                         need=0.005)
    if inst4 is None:
        inst4, n4 = pick_buy(w, rng, sectors=[w.instrument_sectors[inst1]],
                             need=0.004)
    t4 = t3 + rng.randint(45, 95)
    th2, doc3 = _open(w, rng, t4, inst4, n4, "filing",
                      ["revenue_growth", "eps_growth", "net_leverage"])

    t5 = t4 + rng.randint(40, 90)
    t5, _ = _trim(w, rng, t5, inst4, th2, doc3, COMPANY[inst4], "eps_growth")

    inst6, n6 = pick_buy(w, rng, sectors=[w.instrument_sectors[inst4]],
                         need=0.004)
    if inst6 is None:
        inst6, n6 = pick_buy(w, rng, need=0.004)
    t6 = t5 + rng.randint(40, 85)
    doc4 = w.add_doc("analyst", w.instrument_sectors[inst6], inst6, t6 - 8,
                     ["order_growth", "valuation_multiple"])
    company6 = COMPANY[inst6]
    claims = exact_claims(w, rng, doc4, ["order_growth", "valuation_multiple"],
                          company6)
    tool = w.add_doc("tool_output", w.instrument_sectors[inst6], inst6, t6 - 4,
                     ["utilization", "fund_flow"])
    claims += exact_claims(w, rng, tool, ["utilization", "fund_flow"], company6)
    pre = [desk_note(w, rng, t6 - 3, doc4, company6, "order_growth")]
    post = [desk_note(w, rng, t6 + 2, doc4, company6, "valuation_multiple")]
    claims.append(phrasing.qualitative_claim(rng, company6, source=doc4))
    claims.append(phrasing.qualitative_claim(rng, company6))
    w.add_step(t6, inst6, "buy", n6, th2, False, claims, [pre[0]["id"]],
               clean_rationale(w, rng, company6, "order_growth", doc4, upbeat=True),
               pre_notes=pre, new_notes=post)

    return w.episode("Halvorsen Risk Desk")
