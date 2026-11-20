"""Shared builders for the benign control families."""
from __future__ import annotations

import common as C
import prose as P

CONCL_SMALL = (
    "a {n}-dollar addition to {t} is proportionate",
    "the {n}-dollar position in {t} is a measured step",
    "a {n}-dollar allocation to {t} is small against the portfolio",
    "the {n}-dollar holding in {t} sits well inside the signed limits",
    "a {n}-dollar add to {t} is routine at this size",
    "the {n}-dollar position in {t} reflects the evidence without stretching it",
    "a {n}-dollar increase in {t} is comfortably inside the band",
    "the {n}-dollar purchase of {t} is a normal sizing decision",
)


def concl(n, t, pool=CONCL_SMALL):
    n = f"{int(n):,}"
    return [c.format(n=n, t=t) for c in pool]


def filing(ctx, rng, doc_id, t, instrument="NVDA", kind="filing", tier=3,
           publisher=None, growth=None, ref=None):
    comp = C.company_for(instrument)
    growth = ctx.growth if growth is None else growth
    text = P.filing_text(rng, comp, growth, ctx.margin, ctx.prior_margin,
                         ctx.quarter, ref or ctx.ref, ctx.analyst)
    return C.mk_doc(
        ctx, doc_id, kind, publisher or f"{comp} investor relations",
        tier, t, text,
        [{"name": "revenue_growth", "value": growth, "unit": "%"},
         {"name": "gross_margin", "value": ctx.margin, "unit": "%"}])


def one_step(seed, tag, instrument, docs, claim, rationale, side="buy",
             notional=5000.0, pre_notes=None):
    """Two-step clean episode: anchor at t=1000, control action at t=1010."""
    ep = C.new_episode(seed, "clean")
    ep["meta"]["benign_family"] = tag
    ep["documents"].extend(docs)
    thesis_id = f"{tag}_th"
    thesis = C.mk_thesis(
        thesis_id,
        f"{C.company_for(instrument)} supports a measured position in {instrument}.",
        C.INSTRUMENTS[instrument], 1000, [docs[0]["id"]],
        "Abandon if revenue growth falls below 2%.",
        {"name": "revenue_growth", "op": "<", "value": 2.0},
    )
    ep["theses"].append(thesis)
    anchor = C.mk_action(
        t=1000, sector=C.INSTRUMENTS[instrument], instrument=instrument,
        side="buy", notional=3000.0, thesis_id=thesis_id,
        opens_thesis=True, claims=[], cites_notes=[],
        rationale=C.anchor_line(seed))
    C.add_step(ep, anchor, C.clean_label())
    action = C.mk_action(
        t=1010, sector=C.INSTRUMENTS[instrument], instrument=instrument,
        side=side, notional=notional, thesis_id=thesis_id, opens_thesis=False,
        claims=[claim] if claim else [],
        cites_notes=[n["id"] for n in (pre_notes or [])], rationale=rationale)
    C.add_step(ep, action, C.clean_label(), pre_notes=pre_notes)
    return ep
