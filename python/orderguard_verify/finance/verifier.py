"""Verifier: turn one claim into confirmed / contradicted / stale / unverifiable.

The LLM is used only to look up a definition (which stored metric does "net sales" mean?). Every
comparison, tolerance and label below is plain code.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Callable

from ..core.llm import ask_json
from ..core.models import Claim, Evidence, Verdict
from .router import NO_SOURCE_REASON, route
from .truth_store import Snapshot, TruthStore

REL_TOL = 0.02          # a figure within 2% of the filing counts as the same figure (rounding)
EPS_ABS_TOL = 0.015     # EPS is quoted to the cent
GROWTH_TOL = 0.015      # growth rates: within 1.5 percentage points
QUOTE_MAX_AGE = timedelta(days=5)
FILING_GAP = timedelta(days=125)   # no newer filing for this long: our data may be behind
EXTRA = ["eps_basic"]   # stored and checked, but kept out of STORED because STORED is part of a recorded model prompt (changing it breaks replay)
STORED = ["revenue", "net_income", "operating_income", "gross_profit", "eps_diluted", "operating_cash_flow", "capex", "rd_expense"]
# Worked out in code from two stored figures of the same period.
DERIVED = {"gross_margin": ("gross_profit", "revenue"), "operating_margin": ("operating_income", "revenue"), "net_margin": ("net_income", "revenue"),
           "free_cash_flow": ("operating_cash_flow", "capex")}
# Plain wording -> stored measure, tried in order before any model is asked. A bare "cash flow" is ambiguous and is not guessed.
WORDS = [("free cash flow", "free_cash_flow"), ("gross margin", "gross_margin"), ("operating margin", "operating_margin"), ("net margin", "net_margin"),
         ("profit margin", "net_margin"), ("operating cash flow", "operating_cash_flow"), ("cash from operations", "operating_cash_flow"),
         ("cash flow from operations", "operating_cash_flow"), ("capital expenditure", "capex"), ("capex", "capex"),
         ("research and development", "rd_expense"), ("r&d", "rd_expense")]
MARGIN_TOL = 0.01       # a margin stated in whole percent is good to one point; with a decimal, to half a point


SCALES = {"billion": 1e9, "bn": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
NUMBER = re.compile(r"(\d[\d,]*)(?:\.(\d+))?\s*(billion|bn|million|mm|thousand|m|k)?\b", re.I)


def tolerance(text: str, claimed: float) -> float:
    """How far a figure may sit from the filing and still count as the same figure: one unit of the last digit the memo
    states ("$3.2bn" is good to 0.1bn, "$69,632 million" to 1 million), never less than 0.1% or more than 2%."""
    for m in NUMBER.finditer(text):
        scale = SCALES.get((m.group(3) or "").lower(), 1)
        if abs(float(m.group(1).replace(",", "") + "." + (m.group(2) or "0")) * scale - abs(claimed)) <= 0.001 * abs(claimed):
            return min(REL_TOL, max(0.001, 10 ** -len(m.group(2) or "") * scale / abs(claimed)))
    return REL_TOL


def close(claimed: float, actual: float, metric: str, text: str = "") -> bool:
    if metric in ("eps_diluted", "eps_basic") and abs(claimed - actual) <= EPS_ABS_TOL:
        return True
    return abs(claimed - actual) <= tolerance(text, claimed) * abs(actual)


def _ev(s: Snapshot) -> Evidence:
    return Evidence(**s.model_dump(include=set(Evidence.model_fields)))


def verify(claim: Claim, as_of: date, store: TruthStore, ask: Callable = ask_json) -> Verdict:
    src = route(claim)
    if src is None:
        return Verdict(claim_id=claim.id, label="unverifiable", reason=NO_SOURCE_REASON[claim.type])
    if src == "quotes":
        return _verify_price(claim, as_of, store)
    return _verify_fundamental(claim, as_of, store, ask)


def money(metric: str, v: float) -> str:
    """Human-readable figure for evidence text."""
    if metric in ("eps_diluted", "eps_basic"):
        return f"${v:.2f}/share"
    if metric == "price":
        return f"${v:,.2f}"
    for size, suffix in ((1e9, "B"), (1e6, "M")):
        if abs(v) >= size:
            return f"${v / size:,.2f}{suffix}"
    return f"{v:g}"


def _verify_price(c: Claim, as_of: date, store: TruthStore) -> Verdict:
    if c.attribute != "price" or c.value is None or not c.subject:
        return Verdict(claim_id=c.id, label="unverifiable", reason="not a plain share-price claim")
    q = store.quote(c.subject, as_of)
    if q is None:
        return Verdict(claim_id=c.id, label="unverifiable", reason=f"no quote for {c.subject} on or before {as_of}")
    if as_of - date.fromisoformat(q.as_of) > QUOTE_MAX_AGE:
        return Verdict(claim_id=c.id, label="stale", reason=f"newest quote is from {q.as_of}; need a fresh one", evidence=[_ev(q)])
    if close(c.value, q.value, "price", c.text):
        return Verdict(claim_id=c.id, label="confirmed", reason=f"claimed {money("price", c.value)}, quote {money("price", q.value)}", evidence=[_ev(q)])
    return Verdict(claim_id=c.id, label="contradicted", reason=f"claimed {money("price", c.value)}, quote on {q.as_of} is {money("price", q.value)}", evidence=[_ev(q)])


def resolve_metric(c: Claim, ask: Callable) -> str | None:
    """Definition lookup (LLM): which stored metric does this claim mean? Code checks the answer."""
    base = (c.attribute or "").removesuffix("_growth_yoy")
    text = c.text.lower()
    for words, metric in WORDS:
        if words in text:
            return metric
    if "cash flow" in text and base not in STORED:
        return None
    if base in STORED or base in EXTRA:
        return c.attribute
    data, _ = ask("You map a financial claim to one stored metric. Reply with JSON {\"metric\": <name or null>}. "
                  f"Stored metrics: {STORED + list(DERIVED)}. Use null if none is the same quantity (for example EBITDA or a segment figure).",
                  f"Claim: {c.text}")
    m = data.get("metric")
    if m not in STORED + list(DERIVED):
        return None
    return m + ("_growth_yoy" if c.attribute and c.attribute.endswith("_growth_yoy") else "")


def _prior_label(label: str) -> str:
    head, _, fy = label.rpartition("FY")
    return f"{head}FY{int(fy) - 1}"


def _verify_fundamental(c: Claim, as_of: date, store: TruthStore, ask: Callable) -> Verdict:
    def out(label, reason, ev=(), premature=False):
        return Verdict(claim_id=c.id, label=label, reason=reason, evidence=[_ev(s) for s in ev], premature=premature)

    if c.value is None or not c.subject:
        return out("unverifiable", "no number to check, or no company named")
    if c.subject not in store.tickers():
        return out("unverifiable", f"{c.subject} is not covered by the truth store")
    metric = resolve_metric(c, ask)
    if metric is None:
        return out("unverifiable", "this measure is not in the truth store")
    growth = metric.endswith("_growth_yoy")
    base = metric.removesuffix("_growth_yoy")
    if base in DERIVED and growth:
        return out("unverifiable", "growth of a derived measure is not checked")
    anchor = DERIVED[base][0] if base in DERIVED else base      # which stored series tells us the period

    # 1. find the period the claim is about
    duration = "Q" if (c.period or "").startswith(("Q", "latest_q")) else "FY"
    label = c.period
    latest = None
    if c.period and c.period not in ("latest_fy", "latest_q") and store.versions(c.subject, anchor, c.period, as_of):
        pass                    # the memo names a fiscal period we hold: trust the name over a period-end date a memo may have wrong
    elif c.period_end:
        rows = store.by_period_end(c.subject, anchor, c.period_end, as_of)
        label = rows[0].period if rows else None
    elif c.period in ("latest_fy", "latest_q"):
        latest = store.latest_period(c.subject, anchor, duration, as_of)
        label = latest.period if latest else None
    if not label:
        return out("unverifiable", "no period given, or none public yet on the decision date")
    if base in DERIVED:
        return _verify_derived(c, base, label, as_of, store, out)
    versions = store.versions(c.subject, base, label, as_of)
    if not versions:
        later = store.versions(c.subject, base, label, as_of, include_future=True)
        if later:
            return out("unverifiable", f"{label} was not public until {later[-1].as_of}, after the decision date {as_of}", [later[-1]], premature=True)
        return out("unverifiable", f"no {base} for {label} in the truth store")
    current = versions[0]
    if not growth and c.unit not in (None, current.unit):
        return out("unverifiable", f"claim is in {c.unit}; the source figure is in {current.unit}", [current])

    # 2. growth claims are computed from two stored figures
    if growth:
        prior = store.versions(c.subject, base, _prior_label(label), as_of)
        if not prior or prior[0].value == 0:
            return out("unverifiable", f"no prior-year {base} to compute growth")
        actual = current.value / prior[0].value - 1
        ok = abs(c.value - actual) <= GROWTH_TOL
        why = f"claimed {c.value:+.1%}; {label} vs prior year is {actual:+.1%} ({money(base, current.value)} vs {money(base, prior[0].value)})"
        return out("confirmed" if ok else "contradicted", why, [current, prior[0]])

    # 3. compare the number
    if close(c.value, current.value, base, c.text):
        return out("confirmed", f"claimed {money(base, c.value)}; {label} per {current.source} is {money(base, current.value)}", [current])
    for old in versions[1:]:   # restated since: true once, not any more
        if close(c.value, old.value, base, c.text):
            return out("stale", f"{money(base, c.value)} was the {label} figure until it was restated to {money(base, current.value)} on {current.as_of}", [current, old])
    if latest is not None:     # "latest" quarter/year, but the number belongs to an older period
        for p in store.older_periods(c.subject, base, latest, as_of):
            if close(c.value, p.value, base, c.text):
                return out("stale", f"{money(base, c.value)} is the {p.period} figure; the latest period is {latest.period} ({money(base, latest.value)})", [latest, p])
    last_filing = store.latest_filing_date(c.subject, as_of)
    if c.period in ("latest_fy", "latest_q") and last_filing and as_of - last_filing > FILING_GAP:
        return out("stale", f"newest filing in the store is from {last_filing}; a newer one may exist (refresh)", [current])
    return out("contradicted", f"claimed {money(base, c.value)}; {label} per {current.source} is {money(base, current.value)}", [current])



def _verify_derived(c: Claim, base: str, label: str, as_of: date, store: TruthStore, out) -> Verdict:
    a, b = DERIVED[base]
    x, y = store.versions(c.subject, a, label, as_of), store.versions(c.subject, b, label, as_of)
    if not x or not y or (base != "free_cash_flow" and y[0].value == 0):
        return out("unverifiable", f"{a} or {b} for {label} is not in the truth store")
    if base == "free_cash_flow":
        actual = x[0].value - y[0].value
        ok = close(c.value, actual, base, c.text)
        shown = lambda v: money("revenue", v)
        how = f"operating cash flow {shown(x[0].value)} minus capex {shown(y[0].value)}"
        return out("confirmed" if ok else "contradicted", f"claimed {shown(c.value)}; {label} {how} = {shown(actual)}", [x[0], y[0]])
    actual = x[0].value / y[0].value
    claimed = c.value / 100 if abs(c.value) > 1.5 else c.value
    tol = MARGIN_TOL / 2 if re.search(r"\d\.\d+\s*%", c.text) else MARGIN_TOL
    ok = abs(claimed - actual) <= tol
    return out("confirmed" if ok else "contradicted",
               f"claimed {claimed:.1%}; {label} {a.replace('_', ' ')} / {b} = {actual:.1%} ({money(a, x[0].value)} / {money(b, y[0].value)})", [x[0], y[0]])
