"""Finance extraction prompt and claim normalisation: what a research memo's claims look like."""
from __future__ import annotations

from ..core.models import Claim
from .models import Memo, Order

METRICS = ["revenue", "net_income", "operating_income", "gross_profit", "eps_diluted", "operating_cash_flow", "capex", "rd_expense",
           "gross_margin", "operating_margin", "net_margin", "free_cash_flow", "price"]
TYPES = ("fundamental", "price", "rumour", "sentiment")

SYSTEM = """You read an equity research memo and list the checkable claims it makes. You do NOT judge whether a claim is true.

Return one JSON object: {"claims": [ ... ]}. One entry per distinct claim, each with:
- "text": an exact quote from the memo (copy the words; do not paraphrase)
- "type": one of
    "fundamental"  a reported company financial figure (revenue, net income, operating income, gross profit, diluted EPS, operating cash flow, capital expenditure, R&D expense, free cash flow, gross / operating / net margin, or year-over-year growth in one of these) or a reported corporate event
    "price"        a share price level ("trades at $210", "closed at $98.40")
    "rumour"       anything unconfirmed: "reportedly", "sources say", "in talks", "is said to", leaks, whispers, unannounced deals
    "sentiment"    opinions, ratings, price targets, forecasts, guidance expectations, "bullish", "momentum", "analysts expect"
- "ticker": US ticker of the company the claim is about (null if unclear)
- "metric": for fundamental claims one of revenue, net_income, operating_income, gross_profit, eps_diluted, operating_cash_flow, capex, rd_expense, gross_margin, operating_margin, net_margin, free_cash_flow, or "<one of the first eight>_growth_yoy" for year-over-year growth; "price" for price claims; otherwise null (a bare "cash flow" with no further word is null)
- "period": "FY2024" for a fiscal year, "Q3 FY2025" for a quarter, "latest_fy" when the memo says latest / most recent / last reported year, "latest_q" for latest / last / most recent quarter; null if none
- "period_end": "YYYY-MM-DD" only if the memo states the period-end date, else null
- "value": the number as a plain number: dollars in full units ($94.9 billion -> 94900000000), EPS in dollars, growth and margins as a fraction (18% -> 0.18), a price in dollars. Null if the claim has no number. A loss is negative.
- "unit": "USD", "USD/share", "ratio", or the stated currency code (e.g. "CNY"); null if no number
- "key": true if the trade recommendation depends on this claim
- "main_reason": true for each claim the memo presents as the reason to act ("the thesis", "that is why", "we are buying because"). Several claims may share this role. A figure the memo gives "for background" or "for context" is not the reason.

Rules: list every figure the memo states for a past fiscal year, including comparatives ("up from $X in FY2023", "versus $Y in fiscal 2022", "up 8%"): each is its own claim with its own period. Skip pure narrative with nothing checkable. Forecasts and targets are sentiment. Do not invent numbers that are not in the memo. If a figure is given in a currency other than USD, keep that currency in "unit"."""

EXAMPLE_MEMO = ("Order: buy 300 ACME. Memo: ACME reported fiscal 2023 revenue of $4.2 billion, up 12% from a year earlier. "
                "Operating margin was 21% and free cash flow was $0.6 billion. The stock closed at $55.10 yesterday. "
                "Sources say ACME is exploring a sale of its cloud unit. Analysts are bullish.")
EXAMPLE_ANSWER = """{"claims": [
 {"text": "ACME reported fiscal 2023 revenue of $4.2 billion", "type": "fundamental", "ticker": "ACME", "metric": "revenue", "period": "FY2023", "period_end": null, "value": 4200000000, "unit": "USD", "key": true, "main_reason": true},
 {"text": "up 12% from a year earlier", "type": "fundamental", "ticker": "ACME", "metric": "revenue_growth_yoy", "period": "FY2023", "period_end": null, "value": 0.12, "unit": "ratio", "key": false, "main_reason": false},
 {"text": "Operating margin was 21%", "type": "fundamental", "ticker": "ACME", "metric": "operating_margin", "period": "FY2023", "period_end": null, "value": 0.21, "unit": "ratio", "key": false, "main_reason": false},
 {"text": "free cash flow was $0.6 billion", "type": "fundamental", "ticker": "ACME", "metric": "free_cash_flow", "period": "FY2023", "period_end": null, "value": 600000000, "unit": "USD", "key": false, "main_reason": false},
 {"text": "The stock closed at $55.10 yesterday", "type": "price", "ticker": "ACME", "metric": "price", "period": null, "period_end": null, "value": 55.10, "unit": "USD", "key": false, "main_reason": false},
 {"text": "Sources say ACME is exploring a sale of its cloud unit", "type": "rumour", "ticker": "ACME", "metric": null, "period": null, "period_end": null, "value": null, "unit": null, "key": false, "main_reason": false},
 {"text": "Analysts are bullish", "type": "sentiment", "ticker": "ACME", "metric": null, "period": null, "period_end": null, "value": null, "unit": null, "key": false, "main_reason": false}]}"""


def extraction_prompt(memo: str, ctx: Memo) -> tuple[str, str]:
    about = f"Proposed order: {ctx.side} {ctx.quantity} {ctx.ticker}." if isinstance(ctx, Order) else f"Company the memo is about: {ctx.ticker}."
    user = f"Example memo:\n{EXAMPLE_MEMO}\nExample answer:\n{EXAMPLE_ANSWER}\n\nNow the real memo.\n{about}\nMemo:\n{memo}"
    return SYSTEM, user


def claim_from_raw(raw: dict, index: int, ctx: Memo) -> Claim:
    d = {k: v for k, v in raw.items() if k not in ("id", "ticker", "metric")}
    c = Claim(id=f"c{index}", subject=raw.get("ticker"), attribute=raw.get("metric"), **d)
    if c.type not in TYPES:
        raise ValueError(f"unknown claim type {c.type!r}")
    if c.attribute and c.attribute.removesuffix("_growth_yoy") not in METRICS:
        c.attribute = None
    c.subject = (c.subject or ctx.ticker).upper()
    # The model may mark more claims as key, never fewer: facts about the traded company, and any rumour, are always key.
    if (c.type in ("price", "fundamental") and c.subject == ctx.ticker.upper()) or c.type == "rumour":
        c.key = True
    return c
