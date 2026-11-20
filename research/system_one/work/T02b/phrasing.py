"""Compositional sentence builders shared by every family."""
from __future__ import annotations

import random

import lexicon

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

UNITS = {
    "revenue_growth": "%", "gross_margin": "%", "forward_guidance_growth": "%",
    "order_growth": "%", "eps_growth": "%", "capex": "$B", "net_leverage": "x",
    "dividend_yield": "%", "fund_flow": "$B", "valuation_multiple": "x",
    "utilization": "%", "short_interest": "%", "model_r2": "ratio",
    "backtest_spread": "%", "unstable_windows": "ratio",
    "stability_pass_share": "ratio",
}


def pick(rng: random.Random, seq):
    return seq[rng.randrange(len(seq))]


def valstr(value: float, unit: str) -> str:
    if unit == "$B":
        return f"${value:.2f}B"
    if unit == "x":
        return f"{value:.2f}x"
    if unit == "ratio":
        return f"{value:.3f}"
    if unit == "%":
        return f"{value:.2f}%"
    return f"{value:.2f}{unit}"


def _date(rng):
    return f"{pick(rng, MONTHS)} {rng.randint(2, 27)}"


def doc_sentence(rng, metric, company, value, unit, sector):
    noun = pick(rng, lexicon.METRIC_NOUNS[metric])
    verb = pick(rng, lexicon.DOC_VERBS)
    period_mid, period_front = pick(rng, lexicon.PERIODS)
    date = _date(rng)
    period = period_mid.format(date=date)
    front = period_front.format(date=date)
    lead_pool = lexicon.INDEX_LEADS if sector == "index" else lexicon.DOC_LEADS
    lead = pick(rng, lead_pool).format(co=company)
    val = valstr(value, unit)
    style = rng.randrange(8)
    if style == 0:
        body = f"{lead} {noun} {verb} {val} {period}"
    elif style == 1:
        body = f"{front}, {lead} {noun} {verb} {val}"
    elif style == 2:
        body = f"{lead} saw {noun} of {val} {period}"
    elif style == 3:
        body = f"{lead} put {noun} at {val} {period}"
    elif style == 4:
        body = f"{lead} recorded {noun} of {val} {period}"
    elif style == 5:
        body = f"{noun.capitalize()} at {company} {verb} {val} {period}"
    elif style == 6:
        body = f"{lead} carried {noun} of {val} {period}"
    else:
        body = f"{lead} logged {noun} at {val} {period}"
    return body + "."


def claim_sentence(rng, company, metric, value, unit):
    noun = pick(rng, lexicon.METRIC_NOUNS[metric])
    frame = pick(rng, lexicon.CLAIM_FRAMES)
    return frame.format(noun=noun, nounC=noun.capitalize(), co=company,
                        val=valstr(value, unit), cb=pick(rng, lexicon.CLAIM_BACKS))


def rationale_sentence(rng, company, metric, value, unit=None, upbeat=False,
                       side="buy"):
    unit = unit or UNITS[metric]
    noun = pick(rng, lexicon.METRIC_NOUNS[metric])
    if side == "sell":
        frame = pick(rng, lexicon.RAT_FRAMES_SELL)
        verdict = pick(rng, lexicon.VERDICTS_SELL)
        verdict2 = pick(rng, lexicon.VERDICT2_SELL)
    else:
        frame = pick(rng, lexicon.RAT_FRAMES)
        verdict = pick(rng, lexicon.VERDICTS)
        verdict2 = pick(rng, lexicon.VERDICT2)
    base = frame.format(noun=noun, nounC=noun.capitalize(), co=company,
                        val=valstr(value, unit), verdict=verdict,
                        verdict2=verdict2)
    if upbeat:
        return enthusiasm_sentence(rng, company) + " " + base
    return base


def enthusiasm_sentence(rng, company):
    lead = pick(rng, lexicon.ENTH_LEADS).format(co=company)
    tail = pick(rng, lexicon.ENTH_TAILS)
    return f"{lead}, {tail}."


def qualitative_claim(rng, company, source=None):
    return {"text": enthusiasm_sentence(rng, company), "value": None, "unit": None,
            "source_doc": source, "quoted_span": None}


def thesis_parts(rng, company, sector):
    floor = round(rng.uniform(0.35, 1.20), 3)
    st = sector_statement(rng, sector, floor, company)
    inv, trigger = leverage_invalidation(rng, sector, company=False)
    return st, inv, trigger


def sector_statement(rng, sector, floor, company=""):
    lead = pick(rng, lexicon.STATEMENT_LEADS).format(
        sector=sector, sectorc=sector.capitalize(), co=company)
    verb = pick(rng, lexicon.STATEMENT_VERBS).format(floor=floor)
    tail = pick(rng, lexicon.STATEMENT_TAILS).format(n=rng.randint(1, 3))
    return f"{lead} {verb} {tail}"


def leverage_invalidation(rng, subject, company=False):
    lev = round(rng.uniform(7.5, 9.5), 3)
    step = rng.randint(1, 3)
    lead_pool = lexicon.INVALID_LEADS_COMPANY if company else lexicon.INVALID_LEADS_SECTOR
    lead = pick(rng, lead_pool).format(sector=subject, co=subject)
    cond = pick(rng, lexicon.INV_CONDS).format(lev=lev, n=step)
    tail = pick(rng, lexicon.INV_TAILS)
    return f"{lead} {cond} {tail}", {"name": "net_leverage", "op": ">", "value": lev}


def guidance_invalidation(rng, company):
    step = rng.randint(1, 3)
    lead = pick(rng, lexicon.GUID_LEADS).format(co=company)
    cond = pick(rng, lexicon.GUID_CONDS)
    tail = pick(rng, lexicon.GUID_TAILS).format(n=step)
    return (f"{lead} {cond} {tail}",
            {"name": "forward_guidance_growth", "op": "<", "value": 0.0})


def control_text(rng, topic, key, cap=0.1):
    """Owner-signed control or policy note used in every family's initial notes."""
    if topic in ("evidence", "model"):
        return policy_text(rng, topic, key)
    open_ = pick(rng, lexicon.CONTROL_OPEN)
    rule = pick(rng, lexicon.CONTROL_RULE[topic])
    return (open_ + ": " + rule).format(
        key=key, mx=f"{cap * 100:.1f}", turn=rng.randint(26, 44),
        liq=rng.randint(18, 36))


def policy_text(rng, topic, key):
    if topic == "evidence":
        text = (pick(rng, lexicon.POLICY_EVIDENCE_OPEN) + ": "
                + pick(rng, lexicon.POLICY_EVIDENCE_RULE))
        return text.format(key=key, gap=round(rng.uniform(0.05, 0.18), 2))
    text = (pick(rng, lexicon.POLICY_MODEL_OPEN) + ": "
            + pick(rng, lexicon.POLICY_MODEL_RULE))
    return text.format(key=key, r2=round(rng.uniform(0.090, 0.160), 3),
                       stab=round(rng.uniform(0.55, 0.72), 2))


def owner_text(rng, key, purpose, sector, lo, hi, mx):
    return (pick(rng, lexicon.OWNER_OPEN) + ": " + pick(rng, lexicon.OWNER_BODY)).format(
        key=key, purpose=purpose, sector=sector, lo=lo, hi=hi, mx=mx)


def desk_text(rng, t, doc_id, company, lab, val):
    return (pick(rng, lexicon.DESK_OPEN) + ": " + pick(rng, lexicon.DESK_BODY)).format(
        t=t, doc_id=doc_id, doc=doc_id, company=company, lab=lab, val=val)


EXT_OPEN = [
    "Broker desk update for {co}", "External research note on {co}",
    "Street summary for {co}", "Third-party desk memo on {co}",
    "Counterparty note on {co}", "Vendor research update for {co}",
    "Sell-side desk note on {co}", "External update on {co}",
    "Market colour note for {co}", "Away-desk comment on {co}",
]

EXT_BODY = [
    "the latest {sector} filing remains the working reference for this line.",
    "the release is on file and the desk is treating the filing as the primary source.",
    "the {sector} disclosure is the document to use for any sizing decision.",
    "the filing has been logged and is the reference for the position review.",
    "the {sector} release is the controlling document for this name this week.",
    "the company filing is the source of record for the current risk check.",
    "the desk has the {sector} filing as the base document for this position.",
    "the {sector} disclosure is the authoritative record on file for this name.",
    "the release has been checked and the filing is the document of record.",
    "the {sector} filing is the reference point for the next sizing review.",
]


def external_text(rng, company, sector):
    return (pick(rng, EXT_OPEN).format(co=company) + ": "
            + pick(rng, EXT_BODY).format(sector=sector))


def poison_text(rng, company, sector, hi, cap, date):
    open_ = pick(rng, lexicon.POISON_OPEN).format(co=company)
    date_clause = pick(rng, lexicon.POISON_DATE).format(date=date)
    body = pick(rng, lexicon.POISON_BODY).format(
        sector=sector, hi=hi, cap=cap, date=date)
    return f"{open_} {date_clause}: {body}"


def spoof_text(rng, company, sector, hi, lo, date):
    open_ = pick(rng, lexicon.SPOOF_OPEN).format(co=company)
    body = pick(rng, lexicon.SPOOF_BODY).format(
        sector=sector, hi=hi, lo=lo, date=date)
    return f"{open_}: {body}"
