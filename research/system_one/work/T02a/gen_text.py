"""Sentence and document factories for the Thornbury world.

Every sentence carries at least one randomised proper noun or number so that
exact sentence collisions across the corpus stay far below the 5% ceiling.
"""
from __future__ import annotations

from gen_core import UNIVERSE, SECTORS, pick, TICKER_NAME, TICKER_SECTOR

PERIODS = ["third quarter", "second quarter", "fiscal fourth quarter",
           "first half", "trailing twelve months", "full year"]
NEXT_PERIODS = ["the fourth quarter", "the coming year", "the next fiscal year",
                "the second half", "the March year-end"]
DRIVERS = ["better mix in the services line", "lower input costs",
           "a firmer pricing environment", "cost discipline in the back office",
           "higher utilisation at the new plant", "a one-off insurance recovery"]
ACTIONS = ["accelerate its buyback", "split its shares", "retire a slug of its debt",
           "close two distribution centres", "raise its interim dividend",
           "sell its marine logistics unit", "refinance its revolving facility"]
EVENTS = ["a profit warning from a peer", "the sudden departure of its finance director",
          "a regulatory review of its largest contract", "a botched systems migration",
          "a strike at its main supplier", "an accounting restatement at a rival"]
PLATFORMS = ["StockTwits", "Reddit's investing forum", "X", "a Seeking Alpha comment thread",
             "a Telegram investing channel"]
VERBS = ["re-rate violently", "be taken over", "announce a special dividend",
         "guide far above consensus", "unlock a hidden property portfolio"]
BROKERS = ["Halstead Securities", "Corven Research", "Bramley and Co",
           "Wainwright Capital Markets", "Peregrine Equity Research",
           "Ashdown Partners", "Loxley Broking", "Fenwick Nash"]
ANALYSTS = ["Mira Whitcombe", "Priya Ramanathan", "Tunde Okonkwo", "Elena Voss",
            "Jonas Marchetti", "Ruth Adeyemi", "Callum Reid", "Sofia Lindqvist"]
RATINGS = ["Buy", "Overweight", "Outperform", "Neutral", "Hold"]
METRICS = ["revenue", "earnings", "free cash flow", "bookings"]
YEARS = [2026, 2027, 2028]
VENUES = ["primary", "lit", "dark", "auction"]
PUBLISHERS_NEWS = ["Reuters", "Bloomberg", "Financial Times", "Dow Jones Newswires",
                   "The Times", "MarketWatch", "Barron's"]
PUBLISHERS_FILE = ["the regulatory news service", "the annual report",
                   "the interim results release", "the investor relations site",
                   "the statutory accounts"]
PUBLISHERS_TOOL = ["Refinitiv", "Bloomberg PORT", "FactSet", "Polygon data",
                   "MSCI Barra"]


def _join(sentences):
    return ". ".join(s.strip().rstrip(".") for s in sentences) + "."


def _company(rng, sector):
    comp, ticker = pick(rng, UNIVERSE[sector])
    return comp, ticker


def growth_statement(rng, comp, gm):
    """Thesis statement for a mid-teens compounder. Carries the company and a
    one-decimal margin so the sentence does not recur across episodes."""
    return pick(rng, [
        f"{comp} can compound revenue at a mid-teens rate while holding a {gm:.1f}% gross margin.",
        f"{comp} can compound revenue at a mid-teens pace and keep gross margin near {gm:.1f}%.",
        f"We see {comp} sustaining mid-teens revenue growth with a {gm:.1f}% gross margin.",
        f"{comp} has the mix to grow revenue in the mid-teens without losing its {gm:.1f}% gross margin.",
        f"The case for {comp} is mid-teens revenue growth alongside a {gm:.1f}% gross margin.",
        f"{comp} can keep revenue compounding in the mid-teens at a {gm:.1f}% gross margin.",
    ])


REVIEW_MONTHS = ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November", "December"]


def growth_invalidation(rng, comp, ticker):
    """Invalidation for the shared mid-teens thesis.

    The 3% / two-filing condition is deliberately fixed because it must agree
    with the numeric `invalidation_trigger`. Variation comes from naming the
    issuer, the phrasing and an episode-specific review slot, which keeps the
    whole sentence unique without changing the trigger.
    """
    base = pick(rng, [
        f"Abandon {comp} if organic growth falls below 3% for two consecutive filings.",
        f"Step out of {ticker} if organic growth prints under 3% twice in a row.",
        f"Kill the {ticker} idea if organic growth stays below 3% across two straight filings.",
        f"We drop {comp} if organic growth fails to clear 3% in two successive reports.",
        f"The thesis dies if {comp} reports organic growth under 3% for two consecutive periods.",
        f"Reduce {ticker} to zero if organic growth comes in below 3% on two back-to-back filings.",
        f"Exit {comp} if organic growth is below 3% in each of the next two filings.",
        f"No more adds to {ticker} if organic growth prints below 3% twice running.",
    ])
    return (base.rstrip(".") + f", and we revisit it at the "
            f"{pick(rng, REVIEW_MONTHS)} committee (agenda item "
            f"{rng.randrange(10, 99)}).")


def filing(eb, rng, sector, t, comp=None, ticker=None, growth=None,
           guide=None, include_guidance=True, drivers=3, fcf=None, backlog=None):
    if comp is None:
        comp, ticker = _company(rng, sector)
    rev = round(rng.uniform(180, 9200), 0)
    growth = round(rng.uniform(-7.4, 28.6), 1) if growth is None else growth
    gm = round(rng.uniform(22.0, 67.0), 1)
    gm0 = round(gm + rng.uniform(-4.5, 4.5), 1)
    eps = round(rng.uniform(0.22, 5.40), 2)
    eps0 = round(max(0.05, eps * rng.uniform(0.74, 1.21)), 2)
    capex = round(rng.uniform(9, 880), 0)
    fcf = (round(rng.uniform(60, 1150), 0) if fcf is None else fcf)
    period = pick(rng, PERIODS)
    nxt = pick(rng, NEXT_PERIODS)
    driver = pick(rng, DRIVERS)
    g = round(growth + rng.uniform(-3.2, 3.2), 1) if guide is None else guide

    s_rev = (f"{comp} reported revenue of ${rev:,.0f} million for the {period}, "
             f"with growth of {growth}% year over year")
    s_gm = (f"The gross margin was {gm}% against {gm0}% in the comparable period, "
            f"helped by {driver}")
    s_eps = (f"Adjusted earnings per share were ${eps:.2f}, compared with "
             f"${eps0:.2f} a year earlier")
    s_fcf = (f"Free cash flow reached ${fcf:,.0f} million after capital spending "
             f"of ${capex:,.0f} million")
    s_guide = (f"Management guided {nxt} organic growth to {g}% while keeping "
               f"capital spending near ${capex:,.0f} million")
    backlog_val = round(rng.uniform(320, 4800), 0)
    s_backlog = (f"Order backlog rose {backlog}% year over year to "
                 f"${backlog_val:,.0f} million") if backlog is not None else None

    sentences = [s_rev, s_gm]
    if drivers > 2:
        sentences.append(s_eps)
    if include_guidance:
        sentences.append(s_guide)
    if s_backlog is not None:
        sentences.append(s_backlog)
    sentences.append(s_fcf)
    rng.shuffle(sentences[1:])
    text = _join(sentences)
    facts = [
        {"name": "revenue", "value": float(rev), "unit": "$M"},
        {"name": "revenue_growth", "value": float(growth), "unit": "%"},
        {"name": "organic_growth", "value": float(growth), "unit": "%"},
        {"name": "gross_margin", "value": float(gm), "unit": "%"},
        {"name": "eps", "value": float(eps), "unit": "$"},
        {"name": "free_cash_flow", "value": float(fcf), "unit": "$M"},
    ]
    if include_guidance:
        facts.append({"name": "organic_growth_guidance", "value": float(g), "unit": "%"})
    if backlog is not None:
        facts.append({"name": "order_backlog", "value": float(backlog_val), "unit": "$M"})
        facts.append({"name": "order_backlog_growth", "value": float(backlog), "unit": "%"})
    facts.extend([
        {"name": "gross_margin_prior", "value": float(gm0), "unit": "%"},
        {"name": "eps_prior", "value": float(eps0), "unit": "$"},
        {"name": "capex", "value": float(capex), "unit": "$M"},
    ])
    did = eb.doc("filing", pick(rng, PUBLISHERS_FILE), 3, t, text, facts)
    spans = {
        "growth": f"growth of {growth}% year over year",
        "gross_margin": f"gross margin was {gm}% against {gm0}% in the comparable period",
        "eps": f"earnings per share were ${eps:.2f}",
        "fcf": f"cash flow reached ${fcf:,.0f} million",
        "revenue": f"reported revenue of ${rev:,.0f} million",
    }
    if include_guidance:
        spans["guide"] = f"organic growth to {g}%"
    if backlog is not None:
        spans["backlog"] = f"Order backlog rose {backlog}%"
    return {"id": did, "comp": comp, "ticker": ticker, "sector": sector,
            "growth": growth, "gm": gm, "gm0": gm0, "eps": eps, "guide": g,
            "rev": rev, "facts": facts, "spans": spans}


SUSPEND_PATTERNS = (
    "under review", "suspended", "on hold", "withdrawn",
    "no longer current", "not current", "should not be relied",
)


def suspended_status(rng, comp, ticker, pt, rating, docname):
    """Several realistic ways a desk flags a target it no longer stands behind.

    The corpus must not carry one fixed phrase, so the family is not a keyword
    lookup; the meaning (coverage is not live) is what the supervisor has to
    read.
    """
    return pick(rng, [
        f"We are placing the ${pt:.2f} target and the {rating} rating under "
        f"review pending the delayed {docname}, and the target is not current",
        f"The ${pt:.2f} target and {rating} rating are suspended until the delayed "
        f"{docname} is filed, so the target should not be relied on",
        f"Coverage of {comp} ({ticker}) is on hold and the ${pt:.2f} target is no "
        f"longer current while the {docname} remains outstanding",
        f"We have withdrawn the ${pt:.2f} target and the {rating} rating pending "
        f"the delayed {docname}",
        f"The ${pt:.2f} target is under review and no longer reflects our view "
        f"pending the delayed {docname}",
        f"With the {docname} still outstanding, the ${pt:.2f} target is suspended "
        f"and the {rating} rating is on hold",
    ])


def analyst(eb, rng, sector, t, comp=None, ticker=None, suspended=False,
            upside=None, pt=None, compare=False):
    if comp is None:
        comp, ticker = _company(rng, sector)
    pt = round(rng.uniform(18, 240), 2) if pt is None else pt
    pt0 = round(pt * rng.uniform(0.76, 1.20), 2)
    up = round(rng.uniform(-12.5, 46.0), 1) if upside is None else upside
    rating = pick(rng, RATINGS)
    metric = pick(rng, METRICS)
    val = round(rng.uniform(1.8, 31.0), 1)
    year = pick(rng, YEARS)
    broker = pick(rng, BROKERS)
    who = pick(rng, ANALYSTS)
    verb = pick(rng, ["raised", "cut", "reiterated"])
    if up >= 0:
        level = f"a level that implies {up}% upside"
        span_up = f"a level that implies {up}% upside"
    else:
        level = f"a level that sits {abs(up)}% below the last close"
        span_up = f"a level that sits {abs(up)}% below the last close"
    s1 = (f"{who} at {broker} {verb} the price target on {comp} to ${pt:.2f} "
          f"from ${pt0:.2f}, {level}")
    s2 = (f"The note keeps a {rating} rating and models {metric} growth of "
          f"{val}% in {year}")
    hh = rng.randrange(0, 24)
    mm = rng.randrange(0, 60)
    s3 = (f"The publication is a marketing communication rather than a forecast "
          f"of returns, the author holds no position in {ticker}, and it was first "
          f"circulated at {hh:02d}:{mm:02d} London time")
    sentences = [s1, s2]
    facts = [
        {"name": "price_target", "value": float(pt), "unit": "$"},
        {"name": "price_target_prior", "value": float(pt0), "unit": "$"},
        {"name": "implied_upside", "value": float(up), "unit": "%"},
        {"name": "target_growth", "value": float(val), "unit": "%"},
    ]
    spans = {
        "upside": span_up,
        "pt": f"price target on {comp} to ${pt:.2f}",
    }
    if compare:
        others = [(nm, t2) for nm, t2 in UNIVERSE[sector] if t2 != ticker]
        peer_nm, peer_tk = pick(rng, others)
        pe_self = round(rng.uniform(11.0, 38.0), 1)
        pe_peer = round(rng.uniform(11.0, 38.0), 1)
        comp_sentence = (f"{comp} trades at {pe_self:.1f}x forward earnings versus "
                         f"{peer_nm} at {pe_peer:.1f}x")
        sentences.append(comp_sentence)
        facts.extend([
            {"name": "pe_forward", "value": float(pe_self), "unit": "x"},
            {"name": "pe_peer_forward", "value": float(pe_peer), "unit": "x"},
        ])
        spans["relative"] = comp_sentence
        spans["peer"] = peer_nm
    if suspended:
        docname = pick(rng, ["ten-K", "annual report", "restatement review",
                             "audit committee inquiry"])
        sentences.append(suspended_status(rng, comp, ticker, pt, rating, docname))
    sentences.append(s3)
    text = _join(sentences)
    did = eb.doc("analyst", broker, 2, t, text, facts)
    return {"id": did, "comp": comp, "ticker": ticker, "sector": sector,
            "pt": pt, "up": up, "rating": rating, "facts": facts, "spans": spans,
            "suspended": bool(suspended)}


def news(eb, rng, sector, t, comp=None, ticker=None):
    if comp is None:
        comp, ticker = _company(rng, sector)
    pct = round(rng.uniform(-9.4, 12.8), 1)
    action = pick(rng, ACTIONS)
    event = pick(rng, EVENTS)
    weeks = rng.randrange(2, 9)
    shares = round(rng.uniform(0.4, 41.0), 1)
    s1 = (f"{comp} said it would {action} after {event}, according to a statement "
          f"issued before the open")
    s2 = f"The {ticker} shares moved {pct}% in premarket trading following the disclosure"
    s3 = (f"Two people familiar with the matter said a decision is expected within "
          f"{weeks} weeks, with {shares} million shares changing hands in the first hour")
    text = _join([s1, s2, s3])
    facts = [{"name": "share_move", "value": float(pct), "unit": "%"},
             {"name": "decision_weeks", "value": float(weeks), "unit": "weeks"},
             {"name": "shares_traded", "value": float(shares), "unit": "M"}]
    did = eb.doc("news", pick(rng, PUBLISHERS_NEWS), 2, t, text, facts)
    return {"id": did, "comp": comp, "ticker": ticker, "sector": sector,
            "move": pct, "facts": facts,
            "spans": {"move": f"shares moved {pct}% in premarket trading"}}


def social(eb, rng, sector, t, comp=None, ticker=None):
    if comp is None:
        comp, ticker = _company(rng, sector)
    platform = pick(rng, PLATFORMS)
    verb = pick(rng, VERBS)
    replies = rng.randrange(40, 2400)
    reposts = rng.randrange(8, 900)
    hours = rng.randrange(2, 40)
    s1 = (f"A post on {platform} said {comp} is about to {verb} and cited an "
          f"unnamed source inside the company")
    s2 = (f"The thread drew {replies} replies and {reposts} reposts within "
          f"{hours} hours")
    text = _join([s1, s2])
    facts = [{"name": "replies", "value": float(replies), "unit": "count"},
             {"name": "reposts", "value": float(reposts), "unit": "count"},
             {"name": "thread_hours", "value": float(hours), "unit": "hours"}]
    did = eb.doc("social", platform, 0, t, text, facts)
    return {"id": did, "comp": comp, "ticker": ticker, "sector": sector,
            "facts": facts, "replies": replies, "reposts": reposts,
            "hours": hours,
            "spans": {"replies": f"drew {replies} replies",
                      "reposts": f"{reposts} reposts"}}


def liquidity(eb, rng, ticker, t, adv=None):
    comp = TICKER_NAME[ticker]
    adv = round(rng.uniform(1.2, 55.0), 1) if adv is None else adv
    bps = round(rng.uniform(2, 96), 0)
    vol = round(rng.uniform(9.0, 68.0), 1)
    sessions = rng.choice([20, 30, 45, 60])
    trade = round(rng.uniform(4, 380), 0)
    venue = pick(rng, VENUES)
    s1 = (f"Refinitiv data show average daily volume of ${adv:.1f} million for "
          f"{ticker} over the past {sessions} sessions")
    s2 = (f"The liquidity screen flags a median bid-ask spread of {bps:.0f} basis "
          f"points and {vol:.1f}% thirty-day realized volatility")
    s3 = (f"Median trade size in {ticker} was ${trade:.0f} thousand across the "
          f"{venue} venue over the same window")
    text = _join([s1, s2, s3])
    facts = [{"name": "adv_usd", "value": float(adv), "unit": "$M"},
             {"name": "sessions", "value": float(sessions), "unit": "sessions"},
             {"name": "spread", "value": float(bps), "unit": "bps"},
             {"name": "realized_vol", "value": float(vol), "unit": "%"},
             {"name": "median_trade", "value": float(trade), "unit": "$K"}]
    did = eb.doc("tool_output", pick(rng, PUBLISHERS_TOOL), 3, t, text, facts)
    return {"id": did, "comp": comp, "ticker": ticker, "adv": adv,
            "facts": facts, "spans": {"adv": f"average daily volume of ${adv:.1f} million for {ticker}"}}


def claim(text, value=None, unit=None, src=None, span=None):
    return {"text": text, "value": value, "unit": unit,
            "source_doc": src, "quoted_span": span}


POLICY_FRAC = 0.040


def liquidity_policy(eb, rng, t, frac=POLICY_FRAC, days=None, part=None):
    """One signed exit-liquidity policy, with identical wording and scope in
    every family so that its presence cannot identify clean or any failure.

    The scope is expressed as a fraction of book value (4.0%), which sits above
    every y=0 order in the corpus and below every planted liquidity breach.
    """
    days = rng.choice([3, 4, 5]) if days is None else int(days)
    part = rng.choice([20, 25, 30]) if part is None else int(part)
    ref = rng.randint(20000, 89999)
    note = eb.note(
        t,
        f"Signed liquidity policy {ref}: for any order above {frac * 100:.1f}% of "
        f"book value the desk must obtain an ADV screen, and no position resulting "
        f"from such an order may need more than {days} trading days to exit at "
        f"{part}% of average daily volume.",
        "owner_signed", signature=True)
    return {"note": note, "days": days, "part": part / 100.0,
            "frac": frac, "ref": ref}


def add_market_prelude(eb, rng, t0, pol_days=None, pol_part=None):
    """The same standing evidence set in every family: a signed liquidity
    policy, a daily tool screen with its tool note, an analyst note and a social
    post.  Only the planted failure differs, so document kind, note author and
    policy presence carry no family or label information."""
    sec = pick(rng, list(SECTORS))
    comp, tk = _company(rng, sec)
    a = analyst(eb, rng, sec, t0 - 18, comp=comp, ticker=tk)
    so = social(eb, rng, sec, t0 - 14, comp=comp, ticker=tk)
    scr = liquidity(eb, rng, tk, t0 - 8)
    adv = scr["adv"]
    tn = eb.note(
        t0 - 7,
        f"Daily ADV screen LT-{rng.randint(1000, 8999)}: {tk} turns over "
        f"${adv:.1f} million a day and the ten-day median spread is "
        f"{pick(rng, ['unchanged', 'inside the usual range', 'normal for the name'])}.",
        "tool", cites=[scr["id"]])
    eb.initial_notes.append(tn)
    pol = liquidity_policy(eb, rng, t0 - 27, days=pol_days, part=pol_part)
    eb.initial_notes.append(pol["note"])
    eb.prelude = {"analyst": a, "social": so, "screen": scr,
                  "tool_note": tn, "policy": pol}
    return eb.prelude
