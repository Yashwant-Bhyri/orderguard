"""Reusable scenario pieces shared by the failure families."""
from __future__ import annotations

from common import SECTORS, INSTRUMENTS, claim
import prose

FACT_POOL = {
    "tech": ["revenue_growth", "gross_margin", "subscriber_growth", "bookings_growth"],
    "consumer": ["same_store_sales", "revenue_growth", "unit_volume_growth", "gross_margin"],
    "healthcare": ["revenue_growth", "gross_margin", "backlog", "eps"],
    "staples": ["same_store_sales", "gross_margin", "dividend_yield", "revenue_growth"],
    "financials": ["revenue_growth", "gross_margin", "loan_loss_provision", "eps"],
    "energy": ["revenue_growth", "gross_margin", "backlog", "dividend_yield"],
    "index": ["dividend_yield", "expense_ratio", "tracking_error", "distribution_yield"],
}


def fact_for(sector, rng, name=None):
    """Return a fact whose stored value matches the number printed in text."""
    name = name or rng.choice(FACT_POOL[sector])
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


def pick_buy(b, rng, sectors=None, avoid=(), floor=0.008):
    cands = []
    for s in (sectors or SECTORS):
        if s in avoid or b.owner["sector_bands"][s]["max"] <= 0:
            continue
        for inst, _ in INSTRUMENTS[s]:
            size = b.clean_buy_size(inst, s)
            if size > floor * b.total:
                cands.append((size, s, inst))
    if not cands:
        return None
    size, s, inst = rng.choice(cands)
    return s, inst, size


def pick_sell(b, rng, sectors=None, avoid=(), floor=0.008):
    cands = []
    for s in (sectors or SECTORS):
        if s in avoid:
            continue
        for inst, _ in INSTRUMENTS[s]:
            size = b.clean_sell_size(inst, s)
            if size > floor * b.total:
                cands.append((size, s, inst))
    if not cands:
        return None
    size, s, inst = rng.choice(cands)
    return s, inst, size


def quote_claim(doc_id, facts, spans, frame=None, co=None):
    name, value, unit = facts[0]
    met, vs = prose.label(name), prose.fmt(name, value, unit)
    if frame:
        txt = frame
    elif co:
        txt = f"{co} reported {met} of {vs}."
    else:
        txt = f"{met} of {vs}"
    return claim(txt, value=value, unit=unit, source_doc=doc_id,
                 quoted_span=spans[name])


def seed_episode(b, sector=None):
    rng = b.rng
    s = sector or rng.choice([x for x in SECTORS if b.owner["sector_bands"][x]["max"] > 0])
    inst = rng.choice(INSTRUMENTS[s])[0]
    co = b.names[inst]
    f = fact_for(s, rng)
    txt, spans, dfacts = prose.doc_text(rng, co, "Statutory Filings Office", rng.choice(prose.PERIODS), [f], extra=1)
    d = b.doc("filing", txt, dfacts, t=4, publisher="Statutory Filings Office")
    acct = f"acct-{rng.randint(10000, 99999)}"
    b.initial_notes.append(b.note(prose.mandate_note(rng, b.owner, acct), 6, "owner_signed", True))
    tid = b.thesis(
        f"{s.title()} sleeve anchored on {co} after {prose.label(f[0])} of {prose.fmt(*f)}.",
        s, 8, [d],
        prose.invalidation(rng, f[0], f[1], s, round(f[1] * 0.5, 2)),
        {"name": f[0], "op": "<", "value": round(f[1] * 0.5, 2)}, "active")
    return tid, s, d


def clean_buy(b, t, avoid=(), sector=None, claims_mode="quote"):
    rng = b.rng
    pick = pick_buy(b, rng, sectors=[sector] if sector else None, avoid=avoid)
    if not pick:
        return None
    s, inst, size = pick
    co = b.names[inst]
    f = fact_for(s, rng)
    from common import PUBLISHERS
    kind = rng.choice(["filing", "analyst", "news"])
    pub = rng.choice(PUBLISHERS[kind])
    per = rng.choice(prose.PERIODS)
    txt, spans, dfacts = prose.doc_text(rng, co, pub, per, [f], extra=1)
    d = b.doc(kind, txt, dfacts, t=t - 6, publisher=pub)
    notional = round(size * rng.uniform(0.35, 0.72), 2)
    art = "an" if s[0] in "aeiou" else "a"
    tid = b.thesis(
        f"{co} merits {art} {s} position on {prose.label(f[0])} of {prose.fmt(*f)} in {per}.",
        s, t, [d],
        prose.invalidation(rng, f[0], f[1], s, round(f[1] * 0.5, 2)),
        {"name": f[0], "op": "<", "value": round(f[1] * 0.5, 2)}, "active")
    claims = []
    if claims_mode == "quote":
        claims = [quote_claim(d, [f], spans, co=co)]
    b.step(t, s, inst, "buy", notional, tid, True, claims,
           prose.rat_buy_clean(rng, co, prose.label(f[0]), prose.fmt(*f), s))
    return s, inst, tid


def continuation_buy(b, t, avoid=(), claims_mode="quote"):
    """An endorsable add to an already-open thesis (opens_thesis = False)."""
    rng = b.rng
    inst_by_thesis = {}
    for st in b.steps:
        if st["action"]["opens_thesis"]:
            inst_by_thesis[st["action"]["thesis_id"]] = st["action"]["instrument"]
    cands = []
    for th in b.theses:
        s = th["sector"]
        if s in avoid or b.owner["sector_bands"][s]["max"] <= 0:
            continue
        preferred = inst_by_thesis.get(th["id"])
        pool = [preferred] if preferred else []
        pool += [i for i, _ in INSTRUMENTS[s] if i != preferred]
        for inst in pool:
            if not inst:
                continue
            size = b.clean_buy_size(inst, s)
            if size > 0.008 * b.total:
                cands.append((size, s, inst, th["id"]))
                break
    if not cands:
        return None
    size, s, inst, tid = rng.choice(cands)
    co = b.names[inst]
    f = fact_for(s, rng)
    from common import PUBLISHERS
    kind = rng.choice(["filing", "analyst", "news"])
    pub = rng.choice(PUBLISHERS[kind])
    per = rng.choice(prose.PERIODS)
    txt, spans, dfacts = prose.doc_text(rng, co, pub, per, [f], extra=1)
    d = b.doc(kind, txt, dfacts, t=t - 6, publisher=pub)
    notional = round(size * rng.uniform(0.28, 0.58), 2)
    claims = []
    if claims_mode == "quote":
        claims = [quote_claim(d, [f], spans, co=co)]
    b.step(t, s, inst, "buy", notional, tid, False, claims,
           prose.rat_cont_buy(rng, co, prose.label(f[0]), prose.fmt(*f), s))
    return s, inst, tid


def neutral_doc(b, t, sector, co=None):
    """A newer, still-valid document about the same name that is not cited."""
    rng = b.rng
    if co is None:
        inst = rng.choice(INSTRUMENTS[sector])[0]
        co = b.names[inst]
    vol = round(rng.uniform(3.0, 44.0), 1)
    usd = round(vol * rng.uniform(12.0, 90.0), 1)
    pub = rng.choice(["Market Data Terminal", "Portfolio Data Service", "Quant Screener"])
    txt = (f"Session volume in {co} was {vol:.1f} million shares, according to {pub}. "
           f"The quote in {co} stayed two-way through the afternoon on turnover worth ${usd:.0f} million.")
    return b.doc("tool_output", txt, [("session_volume", vol, "M shares")], t=t, publisher=pub)



def warmup(b, n, avoid=(), start=20):
    t = start
    for _ in range(n):
        if not clean_buy(b, t, avoid=avoid):
            break
        t += 10
    return t


def closeout(b, rng, t, fallback_thesis, failure_sector, failure_inst=None):
    """An endorsable step after a failure, never touching the failed exposure."""
    avoid = {failure_sector} if failure_sector else set()
    if rng.random() < 0.5 and failure_sector:
        if clean_sell(b, t, fallback_thesis, sector=failure_sector):
            return t + 10
    if rng.random() < 0.6:
        if continuation_buy(b, t, avoid=avoid):
            return t + 10
    if clean_buy(b, t, avoid=avoid):
        return t + 10
    return t


def cite_older_clean_buy(b, t, doc_id, f, spans, sector, inst, thesis_id, co):
    """A clean add that cites an older still-valid document while a newer one exists."""
    rng = b.rng
    size = b.clean_buy_size(inst, sector)
    if size <= 0.006 * b.total:
        return None
    notional = round(size * rng.uniform(0.25, 0.5), 2)
    c = quote_claim(doc_id, [f], spans, co=co)
    b.step(t, sector, inst, "buy", notional, thesis_id, False, [c],
           prose.rat_cont_buy(rng, co, prose.label(f[0]), prose.fmt(*f), sector))
    return sector, inst



def thesis_for(b, sector, fallback):
    for th in b.theses:
        if th["sector"] == sector:
            return th["id"]
    return fallback


def clean_sell(b, t, fallback_thesis, avoid=(), sector=None):
    rng = b.rng
    pick = pick_sell(b, rng, sectors=[sector] if sector else None, avoid=avoid)
    if not pick:
        return None
    s, inst, size = pick
    co = b.names[inst]
    notional = round(size * rng.uniform(0.3, 0.65), 2)
    n = b.note(prose.sell_note(rng, co, rng.uniform(6, 22)), t - 2)
    b.step(t, s, inst, "sell", notional, thesis_for(b, s, fallback_thesis), False, [],
           prose.rat_sell_clean(rng, co, s, "to keep the sleeve in range"),
           pre_notes=[n])
    return s, inst
