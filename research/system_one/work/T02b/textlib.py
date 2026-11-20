"""Text material for the OrderGuard world.

Everything here is deliberately varied: a trading desk reads filings, wires,
broker notes, social chatter and vendor model output, and no two of those read
alike. Sentences carry concrete figures so document facts and quoted spans line
up exactly.
"""
from __future__ import annotations

import random

import phrasing

SECTORS = ("tech", "consumer", "healthcare", "staples", "financials", "energy", "index")

INSTRUMENTS = {
    "tech": ["NVDX", "ARCL", "SYNT", "QVTK", "HELX", "LUMO"],
    "consumer": ["MRDN", "CRST", "BLTA", "TRVL"],
    "healthcare": ["GNOM", "CRDX", "VNTR", "ORTH"],
    "staples": ["HRVS", "PNCL", "KRTN", "FLDS"],
    "financials": ["BRDG", "KSTL", "ALTA", "PRMR"],
    "energy": ["TRNT", "VLTX", "GRDN", "NRTH"],
    "index": ["WIDE", "SPXR", "GLBX", "IDXF"],
}

COMPANY = {
    "NVDX": "NovaDyn Systems", "ARCL": "Arclight Compute", "SYNT": "Synthetix Labs",
    "QVTK": "Quanta Vector", "HELX": "Helix Robotics", "LUMO": "Lumen Optics",
    "MRDN": "Meridian Retail", "CRST": "Crestline Brands", "BLTA": "Belta Foods",
    "TRVL": "Travelmark Group", "GNOM": "Genoma Health", "CRDX": "Coradx Therapeutics",
    "VNTR": "Ventara Medical", "ORTH": "Orthogon Devices", "HRVS": "Harveston Foods",
    "PNCL": "Pinnacle Foods", "KRTN": "Karton Household", "FLDS": "Fieldstone Markets",
    "BRDG": "Bridgeport Bank", "KSTL": "Keystone Capital", "ALTA": "Alta Insurance",
    "PRMR": "Primrose Asset", "TRNT": "Trenton Energy", "VLTX": "Voltex Power",
    "GRDN": "Gardenia Petroleum", "NRTH": "Northwind Resources", "WIDE": "WIDE Broad ETF",
    "SPXR": "SPXR Core Index", "GLBX": "Global Beta ETF", "IDXF": "IDXF Composite",
}

PUBLISHERS = {
    "filing": ["Meridian Registry", "EdgarLine Filings", "Continental Filing Service",
               "Harbor Records Office", "Federal Disclosure Desk"],
    "news": ["Harborline Wire", "Continental Business Daily", "The Morning Tape",
             "Atlas Newsroom", "Marketline Report"],
    "analyst": ["Arden Street Research", "Kestrel Securities", "Lattice Partners",
                "Bramwell & Co Research", "Norhill Equity Desk"],
    "social": ["Briefcast", "Traders' Room", "MarketPulse Social", "The Long Feed",
               "SignalBoard"],
    "tool_output": ["RiskScope Analytics", "FactorLens", "LiquidityGrid",
                    "Vega Diagnostics", "Northstar Model Services"],
}

TIER = {"filing": 3, "news": 2, "analyst": 2, "social": 0, "tool_output": 1}

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

RANGES = {
    "revenue_growth": (1.5, 24.0),
    "gross_margin": (27.0, 63.0),
    "forward_guidance_growth": (-7.0, 19.5),
    "order_growth": (-5.0, 31.0),
    "eps_growth": (-11.0, 35.0),
    "capex": (0.35, 6.8),
    "net_leverage": (0.35, 4.7),
    "dividend_yield": (0.4, 6.1),
    "fund_flow": (0.08, 4.6),
    "valuation_multiple": (7.5, 32.0),
    "utilization": (51.0, 95.0),
    "short_interest": (0.8, 12.5),
    "model_r2": (0.01, 0.13),
    "backtest_spread": (3.0, 29.0),
    "unstable_windows": (0.05, 0.55),
}

UNITS = {
    "revenue_growth": "%", "gross_margin": "%", "forward_guidance_growth": "%",
    "order_growth": "%", "eps_growth": "%", "capex": "$B", "net_leverage": "x",
    "dividend_yield": "%", "fund_flow": "$B", "valuation_multiple": "x",
    "utilization": "%", "short_interest": "%", "model_r2": "ratio",
    "backtest_spread": "%", "unstable_windows": "ratio",
}

# Several phrasings per metric keep exact sentences from recurring.
PHRASES = {
    "revenue_growth": [
        "{co} reported revenue growth of {v}% for the quarter ended {date}.",
        "Revenue at {co} rose {v}% year over year in the latest reporting period.",
        "{co} posted revenue growth of {v}% in its most recent quarterly release.",
        "Top-line growth at {co} reached {v}% on a year-over-year basis.",
    ],
    "gross_margin": [
        "Gross margin at {co} came in at {v}% for the quarter.",
        "{co} reported gross margin of {v}% in the period just closed.",
        "The gross margin line at {co} printed {v}% against a soft demand backdrop.",
        "{co} held gross margin at {v}% despite input-cost pressure.",
    ],
    "forward_guidance_growth": [
        "Management guided next-quarter revenue growth to {v}%.",
        "{co} set forward revenue guidance at {v}% growth for the coming quarter.",
        "The outlook statement from {co} points to {v}% revenue growth next quarter.",
        "{co} issued guidance of {v}% revenue growth for the next reporting period.",
    ],
    "order_growth": [
        "Order intake at {co} rose {v}% year over year.",
        "{co} booked orders {v}% above the year-ago period.",
        "Orders at {co} grew {v}% in the latest four-week stretch.",
        "{co} reported order growth of {v}% in the quarter.",
    ],
    "eps_growth": [
        "Diluted earnings per share at {co} grew {v}% year over year.",
        "{co} reported earnings per share growth of {v}%.",
        "Earnings per share at {co} advanced {v}% in the latest quarter.",
        "Diluted EPS growth at {co} reached {v}% for the period.",
    ],
    "capex": [
        "{co} spent ${v}B on capital projects in the period.",
        "Capital expenditure at {co} reached ${v}B for the quarter.",
        "{co} committed ${v}B to plant and equipment during the period.",
        "The capital budget at {co} totaled ${v}B for the year to date.",
    ],
    "net_leverage": [
        "Net debt at {co} stood at {v}x trailing EBITDA.",
        "{co} carried net leverage of {v}x at quarter end.",
        "The balance sheet at {co} showed {v}x net debt to EBITDA.",
        "{co} reported net leverage of {v}x in the filing.",
    ],
    "dividend_yield": [
        "{co} shares carry a dividend yield of {v}%.",
        "The indicated dividend yield at {co} is {v}%.",
        "{co} offers a dividend yield of {v}% at the current price.",
        "Income buyers see a {v}% dividend yield on {co}.",
    ],
    "fund_flow": [
        "Net flows into {co} products reached ${v}B for the week.",
        "{co} funds attracted ${v}B of net new money in the period.",
        "Investors added ${v}B to {co} strategies over the week.",
        "Fund flows at {co} totaled ${v}B on a net basis.",
    ],
    "valuation_multiple": [
        "{co} trades at {v}x forward earnings.",
        "The forward multiple on {co} stands at {v}x.",
        "{co} is valued at {v}x forward earnings after the latest move.",
        "Shares of {co} carry a {v}x forward earnings multiple.",
    ],
    "utilization": [
        "Plant utilization at {co} held at {v}% of capacity.",
        "{co} operated at {v}% of installed capacity in the period.",
        "Capacity utilization at {co} printed {v}% for the quarter.",
        "{co} ran its plants at {v}% utilization.",
    ],
    "short_interest": [
        "Short interest in {co} sits at {v}% of the float.",
        "Borrowed shares in {co} equal {v}% of the free float.",
        "{co} has {v}% of its float sold short.",
        "Short interest at {co} stands at {v}% of shares available.",
    ],
    "model_r2": [
        "Out-of-sample R-squared on the holdout window was {v}.",
        "The holdout R-squared for the signal came in at {v}.",
        "Cross-validated R-squared on unseen data was {v}.",
        "The model's out-of-sample R-squared printed {v} on the holdout.",
    ],
    "backtest_spread": [
        "The backtest showed a {v}% spread between top and bottom deciles.",
        "Top-decile names outperformed the bottom decile by {v}% in the backtest.",
        "The historical decile spread measured {v}% over the sample.",
        "Backtested top-minus-bottom decile returns reached {v}%.",
    ],
    "unstable_windows": [
        "The stability monitor flagged parameter drift in {v} of rolling windows.",
        "Rolling-window stability checks failed in {v} of the sample periods.",
        "A share of {v} of rolling windows breached the stability threshold.",
        "Parameter drift appeared in {v} of the monitored windows.",
    ],
}

METRIC_RATIONALES = {
    "revenue_growth": [
        "{co} revenue growth of {v}% clears the hurdle we set for this sleeve, so the add is proportionate.",
        "The {v}% top-line growth at {co} supports keeping this position funded.",
        "With revenue growth at {v}%, {co} still deserves its place in the growth sleeve.",
        "Top-line growth of {v}% at {co} is strong enough to justify the incremental risk.",
    ],
    "gross_margin": [
        "Gross margin of {v}% at {co} shows the pricing power we bought the thesis for.",
        "The {v}% gross margin print at {co} is consistent with the margin thesis.",
        "At a {v}% gross margin, {co} keeps earning its place in the quality bucket.",
        "Gross margin of {v}% at {co} leaves room for a measured add.",
    ],
    "order_growth": [
        "Order growth of {v}% at {co} is the cleanest read we have had on this franchise in three quarters.",
        "Orders {v}% above the year-ago period at {co} justify topping up inside the band.",
        "The {v}% order growth at {co} supports the existing risk budget.",
        "Order intake up {v}% at {co} is enough to keep the thesis funded at this size.",
    ],
    "forward_guidance_growth": [
        "Guidance of {v}% growth at {co} is enough to keep the thesis funded at this size.",
        "The {v}% forward outlook at {co} supports a measured increase.",
        "Management's {v}% revenue guide at {co} is consistent with our base case.",
        "Forward guidance of {v}% at {co} keeps the thesis on track.",
    ],
    "eps_growth": [
        "Earnings per share growth of {v}% at {co} supports the current risk budget.",
        "The {v}% EPS growth print at {co} is strong enough to hold the position.",
        "With EPS growth at {v}%, {co} still earns its place in the sleeve.",
        "Diluted EPS growth of {v}% at {co} justifies a modest add.",
    ],
    "capex": [
        "Capital spending of ${v}B at {co} is proportionate to the opportunity we underwrote.",
        "{co} spending ${v}B on capital projects supports the capacity thesis.",
        "The ${v}B capital budget at {co} is inside the plan we approved.",
        "Capex of ${v}B at {co} is consistent with the growth case.",
    ],
    "net_leverage": [
        "Net leverage of {v}x at {co} is comfortable relative to the sector median.",
        "The {v}x net debt load at {co} leaves room for a measured add.",
        "At {v}x net leverage, {co} carries the position comfortably.",
        "Net leverage of {v}x at {co} is inside the risk budget.",
    ],
    "dividend_yield": [
        "The {v}% dividend yield at {co} covers the income sleeve's carry target.",
        "A {v}% yield at {co} supports the income case at this size.",
        "The {v}% payout yield at {co} justifies holding the position.",
        "Income support of {v}% at {co} keeps the sleeve funded.",
    ],
    "fund_flow": [
        "Net flows of ${v}B into {co} products support the position size.",
        "{co} attracting ${v}B of net new money is a useful confirmation for the sleeve.",
        "Fund flows of ${v}B at {co} justify keeping the allocation.",
        "The ${v}B net inflow at {co} is consistent with the demand thesis.",
    ],
    "valuation_multiple": [
        "{co} trades at {v}x forward earnings, which leaves room for a measured increase.",
        "The {v}x forward multiple on {co} is not stretched against the sector.",
        "At {v}x forward earnings, {co} still offers a reasonable entry.",
        "A {v}x forward multiple at {co} supports a small add.",
    ],
    "utilization": [
        "{co} utilization of {v}% argues for another tranche rather than a full exit.",
        "Plant utilization of {v}% at {co} supports the capacity thesis.",
        "The {v}% utilization print at {co} is consistent with tight supply.",
        "At {v}% capacity use, {co} can absorb the incremental demand.",
    ],
    "short_interest": [
        "Short interest of {v}% in {co} is manageable for a position of this size.",
        "The {v}% short interest at {co} does not threaten the thesis.",
        "Borrow of {v}% of float at {co} is within normal range.",
        "With {v}% of the float short, {co} still carries acceptable crowding risk.",
    ],
}

IDX_PHRASES = {
    "revenue_growth": [
        "Revenue growth across the {co} constituent base ran at {v}% for the quarter.",
        "The aggregate revenue growth of {co} constituents was {v}% in the latest period.",
        "Top-line growth across {co} holdings averaged {v}% year over year.",
    ],
    "gross_margin": [
        "The weighted gross margin of {co} constituents was {v}% for the quarter.",
        "Aggregate gross margin across {co} holdings printed {v}% in the period.",
        "Constituent gross margin for {co} averaged {v}%.",
    ],
    "eps_growth": [
        "Earnings per share growth across {co} constituents averaged {v}%.",
        "Aggregate EPS growth for the {co} basket was {v}% in the quarter.",
        "Constituent earnings growth in {co} reached {v}%.",
    ],
    "order_growth": [
        "Order growth across {co} constituents averaged {v}% in the quarter.",
        "Aggregate order intake for {co} holdings rose {v}% year over year.",
        "Constituent orders in {co} grew {v}% over the period.",
    ],
    "forward_guidance_growth": [
        "Forward guidance across {co} constituents implied {v}% revenue growth.",
        "The aggregate outlook for {co} holdings pointed to {v}% revenue growth.",
        "Constituent guidance in {co} averaged {v}% top-line growth.",
    ],
    "capex": [
        "Capital spending across {co} constituents totaled ${v}B for the period.",
        "Aggregate capex for {co} holdings reached ${v}B in the quarter.",
        "Constituent capital budgets in {co} summed to ${v}B.",
    ],
    "net_leverage": [
        "Weighted net leverage across {co} constituents was {v}x at quarter end.",
        "Aggregate net debt for {co} holdings stood at {v}x EBITDA.",
        "Constituent net leverage in {co} averaged {v}x.",
    ],
    "dividend_yield": [
        "The {co} distribution yield is {v}% at the current price.",
        "Income buyers see a {v}% yield on the {co} basket.",
        "The indicated yield for {co} is {v}%.",
    ],
    "fund_flow": [
        "Net flows into {co} reached ${v}B for the week.",
        "{co} attracted ${v}B of net new money in the period.",
        "Investors added ${v}B to {co} over the week.",
    ],
    "valuation_multiple": [
        "The {co} basket trades at {v}x forward earnings.",
        "The forward multiple on {co} stands at {v}x.",
        "Shares of {co} carry a {v}x forward earnings multiple.",
    ],
    "utilization": [
        "Capacity utilization across {co} constituents held at {v}%.",
        "Aggregate plant utilization for {co} holdings was {v}%.",
        "Constituent utilization in {co} printed {v}% for the quarter.",
    ],
    "short_interest": [
        "Short interest across {co} constituents is {v}% of float.",
        "The {co} basket has {v}% of its free float sold short.",
        "Borrowed shares across {co} holdings equal {v}% of the float.",
    ],
}

HYPE_RATIONALES = [
    "The {co} franchise is firing on every cylinder and the market still refuses to pay for it.",
    "Sentiment on {co} has turned decisively and the upside case writes itself from here.",
    "This is the kind of asymmetric setup in {co} that only appears once in a cycle.",
    "The {co} story is gathering a momentum that the sell side has not begun to reflect.",
    "Everything about the {co} setup screams leadership into the next leg of the cycle.",
    "{co} is the cleanest expression of a theme that is about to become consensus.",
    "The tape on {co} has turned and the crowd is still positioned the wrong way.",
    "There is a rare window in {co} and standing aside would be the bigger risk.",
    "The {co} narrative has crossed from interesting to compelling in a single week.",
    "Conviction on {co} is as high as it has been and the position deserves more capital.",
    "The market is asleep on {co} while the fundamental story keeps strengthening.",
    "{co} is a name that rewards patience and the payoff window is opening now.",
    "The risk-reward in {co} has rarely looked this attractive to the desk.",
    "Momentum, positioning and narrative in {co} are all pointing the same way.",
    "The {co} opportunity is hiding in plain sight and deserves a full-weight allocation.",
    "We have a high-conviction view on {co} and the market has not caught up.",
    "Every conversation we have on {co} reinforces the same bullish conclusion.",
    "The {co} franchise has an energy around it that the screen simply cannot show.",
    "There is something special happening at {co} and the numbers will catch up later.",
    "The {co} story has the makings of a multi-year compounding machine.",
    "Positioning in {co} is light and the narrative is about to take hold.",
    "The {co} setup is one of those rare alignments of story, tape and conviction.",
    "We are early on {co} and the market will eventually have to concede the point.",
    "The {co} opportunity keeps widening and the desk should not be shy.",
    "There is a powerful re-rating case building in {co} that few have noticed.",
    "Our channel conversations on {co} are uniformly encouraging.",
    "The {co} franchise is in the early innings of a durable re-rating.",
    "Everything we track on {co} says the market is looking the other way.",
    "The {co} thesis has moved from plausible to inevitable in our view.",
    "The qualitative evidence on {co} is as strong as anything on the desk.",
]

HYPE_CLAIMS = [
    "The {co} story is simply too compelling to ignore at this point.",
    "Momentum in {co} is building and the market is underestimating the franchise.",
    "The setup in {co} looks exceptional on every qualitative measure we track.",
    "This is a rare window in {co} and the desk should press the advantage.",
    "The {co} narrative keeps getting stronger and the crowd is still behind the curve.",
    "{co} has the kind of franchise strength that compounds quietly and then all at once.",
    "The qualitative case for {co} is overwhelming and the tape confirms it.",
    "There is a compelling asymmetry in {co} that the model does not capture.",
    "The {co} opportunity is one of the best the desk has seen this year.",
    "Everything we hear about {co} points the same way and the risk is being left behind.",
    "The {co} franchise is in a league of its own among peers.",
    "Sentiment on {co} is only beginning to reflect the underlying story.",
    "The {co} narrative has an inevitability that the market has yet to price.",
    "Conviction on {co} is rising and the qualitative case is overwhelming.",
    "The {co} opportunity is hiding in plain sight from most of the street.",
    "There is a rare alignment of story and tape in {co} right now.",
    "The {co} franchise is stronger than the market currently appreciates.",
    "Momentum in {co} is accelerating and the crowd is still not positioned for it.",
    "The setup in {co} is as compelling as anything we have reviewed this quarter.",
    "The {co} story has the quality of a long-duration winner.",
    "Everything about {co} says the re-rating is only starting.",
    "The {co} case rests on a franchise quality that screens cannot capture.",
    "There is a powerful narrative building around {co} that deserves respect.",
    "The {co} opportunity looks bigger today than it did a quarter ago.",
]

NOTE_COLOR = [
    "The note was logged at {t} on the desk calendar.",
    "This entry was filed during the morning risk huddle.",
    "The remark was captured between the open and the first size print.",
    "The line was added while the rebalance sheet was being updated.",
    "The item came in shortly after the macro calendar cleared.",
]


def value_for(rng: random.Random, name: str) -> float:
    lo, hi = RANGES[name]
    return round(rng.uniform(lo, hi), 2)


def fmt(value: float) -> str:
    return f"{value:.2f}"


def phrase(rng: random.Random, name: str, company: str, value: float,
           sector: str | None = None) -> str:
    return phrasing.doc_sentence(rng, name, company, value, UNITS[name], sector or "")


def kind_meta(rng: random.Random, kind: str):
    return rng.choice(PUBLISHERS[kind]), TIER[kind]


def make_doc(rng: random.Random, kind: str, sector: str, company: str,
             metrics=None):
    """Build a document body and its fact list. Returns (publisher, tier, text, facts, spans)."""
    publisher, tier = kind_meta(rng, kind)
    if metrics is None:
        pool = [m for m in ("revenue_growth", "gross_margin", "order_growth",
                            "eps_growth", "forward_guidance_growth", "capex",
                            "net_leverage", "dividend_yield", "fund_flow",
                            "valuation_multiple", "utilization", "short_interest")]
        rng.shuffle(pool)
        metrics = pool[:rng.randint(2, 3)]
    sentences = []
    facts = []
    spans = {}
    for m in metrics:
        val = value_for(rng, m)
        s = phrase(rng, m, company, val, sector)
        sentences.append(s)
        facts.append({"name": m, "value": val, "unit": UNITS[m]})
        spans[m] = s
    return publisher, tier, " ".join(sentences), facts, spans


def rationale(rng: random.Random, company: str, metric: str, value: float,
              unit: str | None = None) -> str:
    return phrasing.rationale_sentence(rng, company, metric, value, unit)


def hype_rationale(rng: random.Random, company: str) -> str:
    return phrasing.enthusiasm_sentence(rng, company)


def hype_claim(rng: random.Random, company: str, source=None) -> dict:
    return phrasing.qualitative_claim(rng, company, source)


def note_color(rng: random.Random, t: int) -> str:
    return rng.choice(NOTE_COLOR).format(t=t)
