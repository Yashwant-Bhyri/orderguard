"""Drift: the book walks past a signed sector band one reasonable trade at a time."""
from __future__ import annotations

import random
import zlib

import phrasing
from common import (COMPANY, clean_rationale, exact_claims, open_notes,
                    pick_buy, pick_sell, sell_notional, thesis_texts, trim_step)
from textlib import SECTORS
from world import BANDS, World


def _open(w, rng, t, inst, n, kind, metrics):
    sector = w.instrument_sectors[inst]
    doc = w.add_doc(kind, sector, inst, t - rng.randint(5, 12), metrics)
    company = COMPANY[inst]
    statement, invalidation, trigger = thesis_texts(rng, company, sector)
    th = w.thesis(statement, sector, t, [doc], invalidation, trigger)
    claims = exact_claims(w, rng, doc, metrics, company)
    qsrc = doc if rng.random() < 0.72 else None
    claims.append(phrasing.qualitative_claim(rng, company, source=qsrc))
    w.add_step(t, inst, "buy", n, th, True, claims, [],
               clean_rationale(w, rng, company, metrics[0], doc))
    return th, doc


def _reserve_room(w, rng, need):
    """Move value between tech names so one name has room for both drift buys."""
    tech = [i for i in w.instrument_sectors if w.instrument_sectors[i] == "tech"]
    donor = min(tech, key=lambda i: w.inst_weight(i))
    cap = w.maxpos * 0.97
    target = max(0.0, cap - need / w.value - 0.002)
    if w.inst_weight(donor) > target:
        move = (w.inst_weight(donor) - target) * w.value
        w.positions[donor] -= move
        recipients = [i for i in tech if i != donor]
        for _ in range(24):
            if move <= 1e-6:
                break
            recipients.sort(key=lambda i: cap - w.inst_weight(i), reverse=True)
            placed = False
            for r in recipients:
                room = max(0.0, (cap - w.inst_weight(r)) * w.value)
                if room <= 1e-6:
                    continue
                add = min(move, room)
                if add <= 1e-6:
                    continue
                w.positions[r] = w.positions.get(r, 0.0) + add
                move -= add
                placed = True
                if move <= 1e-6:
                    break
            if not placed:
                break
    w.initial_book = w.book()
    return donor


def _tech_buy(w, rng, t, thesis_id, doc, inst, notional):
    company = COMPANY[inst]
    claims = exact_claims(w, rng, doc, ["order_growth"], company)
    w.add_step(t, inst, "buy", notional, thesis_id, False, claims, [],
               clean_rationale(w, rng, company, "order_growth", doc),
               y=1, cause="drift", cause_refs=[])
    return inst, notional


def generate(seed: int, shifted: bool = False) -> dict:
    mix = (int(seed) * 1000003 + (zlib.crc32(b"drift") & 0xFFFFFF)) & 0x7FFFFFFF
    rng = random.Random(mix + (97 if shifted else 0))
    purpose = "growth"
    gap = rng.uniform(0.006, 0.016)
    pin_value = BANDS[purpose]["tech"]["max"] - gap
    w = World(rng, family="drift", shifted=shifted, purpose=purpose,
              pin="tech", pin_value=pin_value,
              total_w=rng.uniform(0.895, 0.930))
    w.seed = int(seed)
    return _build(w, rng)


def _build(w, rng):
    band = w.bands["tech"]
    notes0 = open_notes(w, rng)
    w.initial_notes.extend(notes0)
    nontech = [s for s in SECTORS if s != "tech"]

    w0 = w.sector_weight("tech")
    excess = rng.uniform(0.0045, 0.0115)
    need_onset = (band["max"] + excess - w0) * w.value
    need_second = 0.010 * w.value
    inst_t = _reserve_room(w, rng, need_onset + need_second)

    inst0, n0 = pick_buy(w, rng, sectors=nontech, need=0.004)
    t1 = rng.randint(90, 135)
    th0, doc0 = _open(w, rng, t1, inst0, n0, "filing",
                      ["revenue_growth", "gross_margin"])

    t2 = t1 + rng.randint(35, 75)
    doc_t = w.add_doc("filing", "tech", inst_t, t2 - 10,
                      ["revenue_growth", "order_growth"])
    company_t = COMPANY[inst_t]
    rv = w.fact(doc_t, "revenue_growth")[0]
    statement = phrasing.sector_statement(rng, "tech", rv, company_t)
    invalidation, trigger = phrasing.leverage_invalidation(rng, company_t, company=True)
    th1 = w.thesis(statement, "tech", t2, [doc_t], invalidation, trigger)
    claims = exact_claims(w, rng, doc_t, ["revenue_growth", "order_growth"], company_t)
    room = max(0.0, w.maxpos * 0.97 - w.inst_weight(inst_t)) * w.value
    cross = round(min(need_onset, room * 0.99), 2)
    w.add_step(t2, inst_t, "buy", cross, th1, True, claims, [],
               clean_rationale(w, rng, company_t, "revenue_growth", doc_t),
               y=1, cause="drift", cause_refs=[])

    t3 = t2 + rng.randint(35, 70)
    doc_t2 = w.add_doc("news", "tech", inst_t, t3 - 9,
                       ["order_growth", "forward_guidance_growth"])
    room = max(0.0, w.maxpos * 0.97 - w.inst_weight(inst_t)) * w.value
    n2 = round(min(rng.uniform(0.004, 0.008) * w.value, room * 0.98,
                   w.cash * 0.50), 2)
    if n2 >= 0.0015 * w.value:
        _tech_buy(w, rng, t3, th1, doc_t2, inst_t, n2)

    # A corrective sell takes tech back inside the band. It is the hard negative.
    t4 = t3 + rng.randint(40, 80)
    w_now = w.sector_weight("tech")
    target = band["max"] - rng.uniform(0.002, 0.007)
    sell_sector = (w_now - target) * w.value
    sell_amt = min(sell_sector, w.positions.get(inst_t, 0.0) * 0.85,
                   (w_now - band["min"]) * w.value * 0.90)
    if sell_amt >= 0.0015 * w.value:
        trim_step(w, rng, t4, inst_t, round(sell_amt, 2), th1, doc_t,
                  "revenue_growth", company_t)

    inst2, n2b = pick_buy(w, rng, sectors=[s for s in nontech
                                           if s != w.instrument_sectors[inst0]],
                          need=0.004)
    if inst2 is None:
        inst2, n2b = pick_buy(w, rng, sectors=nontech, need=0.004)
    t5 = t4 + rng.randint(40, 85)
    th2, doc2 = _open(w, rng, t5, inst2, n2b, "analyst",
                      ["revenue_growth", "eps_growth"])

    t6 = t5 + rng.randint(40, 80)
    inst_s = inst0
    n_s = sell_notional(w, rng, inst_s)
    if n_s is not None:
        trim_step(w, rng, t6, inst_s, n_s, th0, doc0, "gross_margin", COMPANY[inst_s])
    else:
        inst_s2, n_s2 = pick_sell(w, rng)
        if inst_s2 is not None:
            doc_s = w.add_doc("news", w.instrument_sectors[inst_s2], inst_s2,
                              t6 - rng.randint(5, 9), ["eps_growth"])
            trim_step(w, rng, t6, inst_s2, n_s2, th2, doc_s, "eps_growth",
                      COMPANY[inst_s2])

    return w.episode("Halvorsen Risk Desk")
