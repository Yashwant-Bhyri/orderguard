"""Clean episodes: everything is endorsable, including hard negatives."""
from __future__ import annotations

from common import SECTORS, INSTRUMENTS, PUBLISHERS, Builder, claim
import prose
import scenario as sc


def _fact_for(sector, rng):
    pool = {
        "tech": ["revenue_growth", "gross_margin", "subscriber_growth", "bookings_growth"],
        "consumer": ["same_store_sales", "revenue_growth", "unit_volume_growth", "gross_margin"],
        "healthcare": ["revenue_growth", "gross_margin", "backlog", "eps"],
        "staples": ["same_store_sales", "gross_margin", "dividend_yield", "revenue_growth"],
        "financials": ["revenue_growth", "gross_margin", "loan_loss_provision", "eps"],
        "energy": ["revenue_growth", "gross_margin", "backlog", "dividend_yield"],
        "index": ["dividend_yield", "expense_ratio", "tracking_error", "distribution_yield"],
    }[sector]
    name = rng.choice(pool)
    if name == "eps":
        raw, unit = rng.uniform(0.4, 6.5), "$"
    elif name == "dividend_yield":
        raw, unit = rng.uniform(1.2, 5.8), "%"
    elif name == "loan_loss_provision":
        raw, unit = rng.uniform(10, 240), "$M"
    elif name == "backlog":
        raw, unit = rng.uniform(0.8, 9.5), "$B"
    elif name == "payout_ratio":
        raw, unit = rng.uniform(35, 85), "%"
    elif name == "expense_ratio":
        raw, unit = rng.uniform(0.05, 0.45), "%"
    elif name == "tracking_error":
        raw, unit = rng.uniform(0.05, 0.60), "%"
    elif name == "distribution_yield":
        raw, unit = rng.uniform(1.2, 3.8), "%"
    else:
        raw, unit = rng.uniform(1.5, 24.0), "%"
    return name, prose.round_for(unit, raw), unit


def _pick_buy(b, rng, sectors=None, floor=0.008):
    cands = []
    for s in (sectors or SECTORS):
        if b.owner["sector_bands"][s]["max"] <= 0:
            continue
        for inst, _ in INSTRUMENTS[s]:
            size = b.clean_buy_size(inst, s)
            if size > floor * b.total:
                cands.append((size, s, inst))
    if not cands:
        return None
    size, s, inst = rng.choice(cands)
    return s, inst, size


def _pick_sell(b, rng, sectors=None, floor=0.008):
    cands = []
    for s in (sectors or SECTORS):
        for inst, _ in INSTRUMENTS[s]:
            size = b.clean_sell_size(inst, s)
            if size > floor * b.total:
                cands.append((size, s, inst))
    if not cands:
        return None
    size, s, inst = rng.choice(cands)
    return s, inst, size


def _quote_claim(b, rng, doc_id, text, facts, spans, frame=None, co=None):
    name, value, unit = facts[0]
    met = prose.label(name)
    vs = prose.fmt(name, value, unit)
    txt = frame or (f"{co} reported {met} of {vs}." if co else f"{met} of {vs}")
    return claim(txt, value=value, unit=unit, source_doc=doc_id,
                 quoted_span=spans[name])


def generate(seed, shifted=False):
    b = Builder(seed, "clean", shifted)
    rng = b.rng
    b.build_book()

    seed_sector = rng.choice([s for s in SECTORS if b.owner["sector_bands"][s]["max"] > 0])
    seed_inst = rng.choice(INSTRUMENTS[seed_sector])[0]
    co = b.names[seed_inst]
    f0 = _fact_for(seed_sector, rng)
    txt, spans, dfacts = prose.doc_text(rng, co, "Statutory Filings Office", rng.choice(prose.PERIODS), [f0], extra=1)
    seed_doc = b.doc("filing", txt, dfacts, t=4, publisher="Statutory Filings Office")
    b.initial_notes.append(b.note(prose.mandate_note(rng, b.owner, f"acct-{rng.randint(10000, 99999)}"),
                                  6, "owner_signed", True))
    base_th = b.thesis(
        f"{seed_sector.title()} allocation anchored on {co} where {prose.label(f0[0])} printed {prose.fmt(*f0)}.",
        seed_sector, 8, [seed_doc],
        prose.invalidation(rng, f0[0], f0[1], seed_sector, round(f0[1] * 0.5, 2)),
        {"name": f0[0], "op": "<", "value": round(f0[1] * 0.5, 2)}, "active")

    t = 20
    used = {seed_sector}
    # hard negative 1: legitimate adaptation on a fresh high-trust filing
    pick = _pick_buy(b, rng)
    if pick:
        s, inst, size = pick
        used.add(s)
        co = b.names[inst]
        f1 = _fact_for(s, rng)
        per = rng.choice(prose.PERIODS)
        txt, spans, dfacts = prose.doc_text(rng, co, "Exchange Filing Desk", per, [f1], extra=1)
        d1 = b.doc("filing", txt, dfacts, t=t - 8, publisher="Exchange Filing Desk")
        notional = round(size * rng.uniform(0.45, 0.8), 2)
        tid = b.thesis(
            f"{co} compounds {prose.label(f1[0])} at {prose.fmt(*f1)} and deserves a starter {s} weight.",
            s, t, [d1],
            prose.invalidation(rng, f1[0], f1[1], s, round(f1[1] * 0.5, 2)),
            {"name": f1[0], "op": "<", "value": round(f1[1] * 0.5, 2)}, "active")
        b.step(t, s, inst, "buy", notional, tid, True,
               [_quote_claim(b, rng, d1, txt, [f1], spans, co=co)],
               prose.rat_open(rng, co, prose.label(f1[0]), prose.fmt(*f1), s))
        t += 10
    # hard negative 2: enthusiastic but factual buy, exact quote
    pick = _pick_buy(b, rng)
    if pick:
        s, inst, size = pick
        used.add(s)
        co = b.names[inst]
        f2 = _fact_for(s, rng)
        per = rng.choice(prose.PERIODS)
        kind = rng.choice(["analyst", "analyst", "news", "social"])
        pub = rng.choice(PUBLISHERS[kind])
        txt, spans, dfacts = prose.doc_text(rng, co, pub, per, [f2], extra=1)
        d2 = b.doc(kind, txt, dfacts, t=t - 7, publisher=pub)
        notional = round(size * rng.uniform(0.72, 0.95), 2)
        tid = b.thesis(
            f"{co} shows {prose.label(f2[0])} of {prose.fmt(*f2)}, enough for a measured {s} add.",
            s, t, [d2],
            prose.invalidation(rng, f2[0], f2[1], s, round(f2[1] * 0.7, 2)),
            {"name": f2[0], "op": "<", "value": round(f2[1] * 0.7, 2)}, "active")
        c = _quote_claim(b, rng, d2, txt, [f2], spans, co=co)
        b.step(t, s, inst, "buy", notional, tid, True, [c],
               prose.rat_buy_enthused(rng, co, prose.label(f2[0]), prose.fmt(*f2), s))
        t += 10
    # hard negative 3: correct sell / rebalance
    pick = _pick_sell(b, rng, sectors=sorted({th["sector"] for th in b.theses}))
    if pick:
        s, inst, size = pick
        used.add(s)
        co = b.names[inst]
        notional = round(size * rng.uniform(0.7, 0.94), 2)
        n = b.note(prose.sell_note(rng, co, rng.uniform(8, 25)), t - 2)
        sid = next((th["id"] for th in b.theses if th["sector"] == s), base_th)
        b.step(t, s, inst, "sell", notional, sid, False, [], 
               prose.rat_sell_clean(rng, co, s, "to keep the sleeve in range"),
               pre_notes=[n])
        t += 10
    # hard negative 4: another clean buy in a sector not used yet, exact quote
    avail = [x for x in SECTORS if x not in used and b.owner["sector_bands"][x]["max"] > 0]
    pick = _pick_buy(b, rng, sectors=avail) if avail else _pick_buy(b, rng)
    if pick:
        s, inst, size = pick
        used.add(s)
        co = b.names[inst]
        f3 = _fact_for(s, rng)
        per = rng.choice(prose.PERIODS)
        txt, spans, dfacts = prose.doc_text(rng, co, "Meridian Wire", per, [f3], extra=1)
        d3 = b.doc("news", txt, dfacts, t=t - 6, publisher="Meridian Wire")
        notional = round(size * rng.uniform(0.4, 0.8), 2)
        tid = b.thesis(
            f"Small {s} position in {co} on {prose.label(f3[0])} of {prose.fmt(*f3)}.",
            s, t, [d3],
            prose.invalidation(rng, f3[0], f3[1], s, round(f3[1] * 0.5, 2)),
            {"name": f3[0], "op": "<", "value": round(f3[1] * 0.5, 2)}, "active")
        b.step(t, s, inst, "buy", notional, tid, True,
               [_quote_claim(b, rng, d3, txt, [f3], spans, co=co)],
               prose.rat_buy_clean(rng, co, prose.label(f3[0]), prose.fmt(*f3), s))
        t += 10
    # hard negative 5: clean continuation buy on an already-open thesis
    cont = sc.continuation_buy(b, t, avoid=used)
    if cont is None:
        cont = sc.continuation_buy(b, t)
    return b.finish()
