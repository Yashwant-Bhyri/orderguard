"""L6 as a library: check the figures an order relies on against SEC filings as of the decision date (CONTRACT section 5.2).

    check_figures(ticker, as_of, figures) -> one result per figure
    check_text(text, ticker, as_of)       -> the memo pipeline: a model reads the text into claims, code checks them

All comparison, unit and status logic is plain code. The only model call is in `check_text` (reading a memo into claims).
Truth comes from SEC EDGAR companyfacts, fetched on demand and cached in the truth store (env OG_TRUTH_DB moves it)."""
from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from .core.llm import ask_json
from .core.pack import SourceUnavailable
from .core.pipeline import check as _check_memo
from .finance import sources
from .finance.models import Memo, normalise_ticker
from .finance.pack import FinancePack, load_mandate
from .finance.truth_store import DEFAULT_DB, Snapshot, TruthStore

METRICS = ("revenue", "net_income", "eps_diluted", "eps_basic", "operating_income", "operating_cash_flow", "gross_profit")
PER_SHARE = ("eps_diluted", "eps_basic")
ALIASES = {"net_sales": "revenue", "sales": "revenue", "total_revenue": "revenue", "revenues": "revenue", "net_revenue": "revenue",
           "net_earnings": "net_income", "profit": "net_income", "net_profit": "net_income", "eps": "eps_diluted",
           "diluted_eps": "eps_diluted", "eps_diluted": "eps_diluted", "basic_eps": "eps_basic", "operating_profit": "operating_income",
           "cash_from_operations": "operating_cash_flow", "cfo": "operating_cash_flow", "gross_income": "gross_profit"}
SCALES = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
LABELS = {1e9: "USD billions", 1e6: "USD millions", 1e3: "USD thousands", 1.0: "USD"}
REL_CAP = 0.02        # whatever the figure's precision, never accept more than 2% off
SPLIT_NOTE = "a stock split changed the per-share basis"
VALUE = re.compile(r"^\(?\s*(-)?\s*\$?\s*(-)?\s*([\d,]*\.?\d+)\s*([a-zA-Z]*)\s*\)?$")


class Bad(ValueError):
    """An input we cannot read; becomes an `unverifiable` result with this reason."""


def normalise_metric(raw) -> str:
    m = re.sub(r"[\s\-/]+", "_", str(raw or "").strip().lower())
    m = ALIASES.get(m, m)
    if m not in METRICS:
        raise Bad(f"metric {raw!r} is not supported (supported: {', '.join(METRICS)})")
    return m


def normalise_unit(unit, metric: str) -> tuple[float, str]:
    """-> (scale to base units, canonical label). Accepts 'USD', 'USD millions', 'USD billions', 'USD/share', '$M', 'billions', ..."""
    u = str(unit or "").lower().replace("us$", "usd").replace("$", "usd ").replace("_", " ").strip()
    if "share" in u:
        if metric not in PER_SHARE:
            raise Bad(f"unit {unit!r} is per share but {metric} is a total")
        return 1.0, "USD/share"
    words = [w for w in re.split(r"[\s,]+", u) if w and w not in ("usd", "in", "dollars", "dollar", "of")]
    words = [w[:-1] if w.endswith("s") and w[:-1] in SCALES else w for w in words]      # millions -> million
    if not words:
        scale = 1.0
    elif len(words) == 1 and words[0] in SCALES:
        scale = SCALES[words[0]]
    else:
        raise Bad(f"unit {unit!r} is not understood")
    if metric in PER_SHARE and scale != 1.0:
        raise Bad(f"{metric} is per share; unit {unit!r} cannot apply")
    return scale, ("USD/share" if metric in PER_SHARE else LABELS[scale])


def parse_value(value, metric: str, unit) -> tuple[float, float, str, Decimal]:
    """-> (value in base USD or USD/share, scale, unit label, the stated number as a Decimal for precision).
    A string such as "$94.9B" carries its own scale, which wins over `unit`."""
    scale, label = normalise_unit(unit, metric)
    if isinstance(value, bool) or value is None:
        raise Bad("no numeric value")
    if isinstance(value, str):
        m = VALUE.match(value.strip())
        if not m:
            raise Bad(f"cannot read the value {value!r}")
        suffix = m.group(4).lower()
        if suffix:
            if suffix not in SCALES or metric in PER_SHARE:
                raise Bad(f"cannot read the value {value!r}")
            scale, label = SCALES[suffix], LABELS[SCALES[suffix]]
        neg = bool(m.group(1) or m.group(2)) or (value.strip().startswith("(") and value.strip().endswith(")"))
        num = Decimal(m.group(3).replace(",", ""))
        num = -num if neg else num
    else:
        try:
            num = Decimal(repr(float(value)))
        except (InvalidOperation, ValueError, TypeError):
            raise Bad("no numeric value") from None
        if num != num or num.is_infinite():
            raise Bad("no numeric value")
        if num == num.to_integral_value():
            num = Decimal(int(num))
    return float(num) * scale, scale, label, num


def tolerance(num: Decimal, scale: float, truth: float) -> float:
    """Half a unit of the last digit the figure states (it was rounded to that digit), in base units, never above 2% of the truth.
    Whole numbers with trailing zeros (391000) count as rounded to their last non-zero digit."""
    exp = num.as_tuple().exponent
    if exp == 0:
        digits = str(abs(int(num)))
        exp = len(digits) - len(digits.rstrip("0")) if digits.strip("0") else 0
        step = 10.0 ** exp
    else:
        step = 10.0 ** exp
    return min(0.5 * step * scale, REL_CAP * abs(truth)) + 1e-9 * max(1.0, abs(truth))


def _source(s: Snapshot | None) -> dict | None:
    if s is None:
        return None
    form = (re.search(r"SEC EDGAR (\S+)", s.source) or [None, None])[1]
    accn = s.source_url.rstrip("/").rsplit("/", 1)[-1].removesuffix("-index.htm")
    return {"form": form, "filed": s.as_of, "url": s.source_url, "accession": accn}


def _fmt(metric: str, v: float, scale: float) -> str:
    if metric in PER_SHARE:
        return f"${v:,.2f}/share"
    d = v / scale
    return {1e9: f"${d:,.3f}B", 1e6: f"${d:,.0f}M", 1e3: f"${d:,.0f}K"}.get(scale, f"${d:,.0f}")


def _is_split(old: float, new: float) -> bool:
    for r in (old / new if new else 0, new / old if old else 0):
        if r >= 2 and abs(r - round(r)) <= 0.02 * round(r):
            return True
    return False


def default_store() -> TruthStore:
    return TruthStore(os.getenv("OG_TRUTH_DB") or DEFAULT_DB)


def _load(store: TruthStore, ticker: str, metric: str, fetch: bool) -> str | None:
    """Make the company's data available; returns a reason string if it cannot be had."""
    if not fetch:
        return None if store.has_fundamentals(ticker) else f"{ticker} is not in the truth store"
    try:
        sources.ensure(store, ticker)
        have = bool(store.periods(ticker, metric, "FY", date.max))
        age = store.fetched_age_days(ticker)
        if not have and (age is None or age > 1 / 24):      # data cached before this metric was supported: look once more
            sources.refresh(store, ticker)
    except SourceUnavailable as e:
        return str(e)
    return None


def _one(store: TruthStore, ticker: str, as_of: date, fig: dict) -> dict:
    metric = normalise_metric(fig.get("metric"))
    value, scale, label, num = parse_value(fig.get("value"), metric, fig.get("unit"))
    fy = fig.get("fiscal_year")
    if isinstance(fy, bool) or not isinstance(fy, int) or not 1990 <= fy <= 2100:
        raise Bad("fiscal_year must be an integer year in the company's own naming, e.g. 2024")
    quarter = str(fig.get("period") or "FY").upper()
    if quarter not in ("FY", "Q1", "Q2", "Q3", "Q4"):
        raise Bad("period must be FY or Q1..Q4")
    duration = "FY" if quarter == "FY" else "Q"
    period = f"FY{fy}" if quarter == "FY" else f"{quarter} FY{fy}"
    what = f"{metric.replace('_', ' ')} for {period}"

    def res(status, reason, truth=None, src=None):
        return {"figure": fig, "status": status, "truth": None if truth is None else truth / scale, "unit": label,
                "source": _source(src), "reason": reason}

    def near(v: float, truth: float) -> bool:
        return abs(v - truth) <= tolerance(num, scale, truth)

    why = _load(store, ticker, metric, fig.get("_fetch", True))
    if why:
        return res("unverifiable", why)
    versions = store.versions(ticker, metric, period, as_of)
    if not versions:
        later = store.versions(ticker, metric, period, as_of, include_future=True)
        if later:
            return res("not_public_yet", f"{what} was first filed on {later[-1].as_of}, after the decision date {as_of}", None, later[-1])
        known = [p.period for p in store.periods(ticker, metric, duration, as_of)][:3]
        return res("unverifiable", f"no {what} in {ticker}'s filings" + (f" (newest we hold: {', '.join(known)})" if known else ""))
    cur = versions[0]
    unit_base = scale
    if near(value, cur.value):
        return res("confirmed", f"{what} per {cur.source} filed {cur.as_of} is {_fmt(metric, cur.value, unit_base)}; the figure matches within its stated precision",
                   cur.value, cur)
    for old in versions[1:]:
        if near(value, old.value):
            note = f" ({SPLIT_NOTE})" if metric in PER_SHARE and _is_split(old.value, cur.value) else ""
            return res("stale", f"{_fmt(metric, old.value, unit_base)} was the {what} as filed {old.as_of}; it was restated or superseded on {cur.as_of} "
                       f"to {_fmt(metric, cur.value, unit_base)}{note}", cur.value, cur)
    for fut in store.versions(ticker, metric, period, as_of, include_future=True):
        if fut.as_of > as_of.isoformat() and near(value, fut.value):
            return res("not_public_yet", f"the figure matches a revision of {what} filed on {fut.as_of}, after the decision date {as_of}", None, fut)

    # contradicted: say what the number really is, when it is a known kind of mistake
    base = f"{what} per {cur.source} filed {cur.as_of} is {_fmt(metric, cur.value, unit_base)}; claimed {_fmt(metric, value, unit_base)}"
    for p in store.periods(ticker, metric, "FY", as_of):
        if p.period != period and near(value, p.value):
            note = "last year's figure cited as this year's" if p.period == f"FY{fy - 1}" else "a different year's figure"
            return res("contradicted", f"{base}. The claimed figure matches {p.period} (year ended {p.period_end}): {note}.", cur.value, cur)
    for p in store.periods(ticker, metric, "Q", as_of):
        if p.period != period and near(value, p.value):
            note = "a quarterly figure cited as annual" if duration == "FY" else "a different quarter's figure"
            return res("contradicted", f"{base}. The claimed figure matches {p.period} (quarter ended {p.period_end}): {note}.", cur.value, cur)
    if metric not in PER_SHARE:
        for k, name in ((1e3, "a thousand"), (1e6, "a million")):
            if near(value * k, cur.value) or near(value / k, cur.value):
                return res("contradicted", f"{base}. The claimed figure is off by a factor of {name}: check the unit.", cur.value, cur)
    return res("contradicted", f"{base} ({abs(value - cur.value) / abs(cur.value):.1%} off)", cur.value, cur)


def check_figures(ticker: str, as_of: date, figures: list[dict], *, store: TruthStore | None = None, fetch: bool = True) -> list[dict]:
    """Check each figure against the company's filings that were public on `as_of`.

    figure in : {"metric": revenue|net_income|eps_diluted|eps_basic|operating_income|operating_cash_flow|gross_profit,
                 "fiscal_year": int (the company's own naming), "value": float or a string such as "$94.9B",
                 "unit": "USD"|"USD millions"|"USD billions"|"USD/share" (optional), "period": "FY" (default) or "Q1".."Q4"}
    result out: {"figure": <in>, "status": confirmed|contradicted|stale|not_public_yet|unverifiable, "truth": float|None,
                 "unit": str, "source": {"form","filed","url","accession"}|None, "reason": str}
    `truth` is in the figure's own (normalised) unit. `fetch=False` never touches the network. Never raises on bad input."""
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    t = normalise_ticker(ticker)
    store = store or default_store()
    out = []
    for fig in figures:
        try:
            if t is None:
                raise Bad(f"{ticker!r} is not a plain ticker symbol")
            if not isinstance(fig, dict):
                raise Bad("a figure must be a dict")
            out.append(_one(store, t, as_of, {**fig, "_fetch": fetch}) | {"figure": fig})
        except Bad as e:
            out.append({"figure": fig, "status": "unverifiable", "truth": None, "unit": str(fig.get("unit") or "") if isinstance(fig, dict) else "",
                        "source": None, "reason": str(e)})
        except Exception as e:   # noqa: BLE001  a checker must say "could not check", never crash an order flow or pass silently
            out.append({"figure": fig, "status": "unverifiable", "truth": None, "unit": "", "source": None,
                        "reason": f"could not be checked ({type(e).__name__})"})
    return out


def check_text(text: str, ticker: str, as_of: date, *, store: TruthStore | None = None, ask: Callable = ask_json, fetch: bool = True) -> dict:
    """The memo pipeline: a model reads `text` into claims, code checks them against filings public on `as_of`, and the decision is
    pass / revise / block / escalate. Returns {"decision","reasons","claims":[{id,text,type,status,reason,key}],"fix","coverage","error"}."""
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    try:
        memo = Memo(ticker=ticker, as_of=as_of)
    except ValueError as e:
        return {"decision": "escalate", "reasons": [f"invalid ticker: {e}"], "claims": [], "fix": [], "coverage": "no checkable claims found", "error": str(e)}
    pack = FinancePack(store or default_store(), load_mandate(), refresh_fn=sources.refresh if fetch else None, on_demand=fetch)
    r = _check_memo(text or "", memo, pack, ask=ask)
    verdict = {v.claim_id: v for v in r.verdicts}
    claims = [{"id": c.id, "text": c.text, "type": c.type, "key": c.key,
               "status": verdict[c.id].label if c.id in verdict else "unverifiable",
               "reason": verdict[c.id].reason if c.id in verdict else ""} for c in r.claims]
    return {"decision": r.decision.action, "reasons": r.decision.reasons, "claims": claims, "fix": r.decision.fix,
            "coverage": r.coverage, "error": r.error or None, "ticker": memo.ticker, "as_of": as_of.isoformat()}
