"""Load fundamentals from SEC EDGAR "company facts" into the truth store.

One record per (metric, period, version). A restated figure becomes a new version with a later
`as_of` (its filing date), so the store can answer "what was known on date X".
"""
from __future__ import annotations

import hashlib
import os
import json
import time
from datetime import date
from pathlib import Path

import httpx

from ..paths import DATA
from .truth_store import Snapshot, TruthStore

# EDGAR asks for a descriptive User-Agent. Deliberately has no personal contact details.
DEFAULT_USER_AGENT = "OrderGuardVerify research-prototype unaffiliated"


def user_agent() -> str:
    """SEC's fair-access guidance asks automated users to identify themselves with contact details. The shipped default has none, on purpose;
    set OG_SEC_UA (for example "MyResearch contact-details") to use your own."""
    return os.getenv("OG_SEC_UA") or DEFAULT_USER_AGENT
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
COMPANIES = DATA / "companies.json"
FIRST_PERIOD_END = date(2018, 1, 1)

# metric -> XBRL tags in priority order (companies switch tags over the years, so we merge per period)
TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "eps_basic": ["EarningsPerShareBasic"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "PaymentsForCapitalImprovements"],
    "rd_expense": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
}
UNIT_FOR = {"USD": "USD", "USD/shares": "USD/share"}


def fetch_facts(cik: int, client: httpx.Client | None = None) -> dict:
    c = client or httpx.Client(headers={"User-Agent": user_agent()}, timeout=60)
    r = c.get(FACTS_URL.format(cik=cik))
    r.raise_for_status()
    return r.json()


def _duration(e: dict) -> str | None:
    days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
    if 350 <= days <= 380:
        return "annual"
    if 80 <= days <= 100:
        return "quarter"
    return None


def _fy_year(end: date) -> int:
    """Fiscal-year number from the period-end date: the year it ends in (52/53-week years ending in the
    first days of January belong to the year before). SEC's own `fy` field is not reliable for this."""
    return end.year - 1 if end.month == 1 and end.day <= 10 else end.year


def fy_offset(gaap: dict) -> int:
    """How this company numbers its fiscal years relative to the year the period ends in. Most use the end year (offset 0); some
    January year-ends (Lululemon, Target, Home Depot) call the year ending January 2024 "fiscal 2023" (offset -1). The company's own
    filings say which: in each 10-K the newest annual period carries the company's fiscal-year label in SEC's `fy` field."""
    newest: dict[str, tuple[str, int]] = {}
    for ents in (u for tag in gaap.values() for u in tag.get("units", {}).values()):
        for e in ents:
            if e.get("form") == "10-K" and e.get("fp") == "FY" and "start" in e and _duration(e) == "annual":
                if e["accn"] not in newest or e["end"] > newest[e["accn"]][0]:
                    newest[e["accn"]] = (e["end"], e["fy"])
    votes: dict[int, int] = {}
    for end, fy in newest.values():
        d = fy - _fy_year(date.fromisoformat(end))
        votes[d] = votes.get(d, 0) + 1
    best = max(votes, key=votes.get) if votes else 0
    return best if best in (-1, 0, 1) else 0


def snapshots_from_facts(ticker: str, cik: int, facts: dict) -> list[Snapshot]:
    """Pure function: companyfacts JSON in, snapshot rows out."""
    out: list[Snapshot] = []
    gaap = facts.get("facts", {}).get("us-gaap", {})
    off = fy_offset(gaap)
    fy_name = lambda end: _fy_year(end) + off      # the company's own number for the fiscal year ending on `end`
    fy_ends = sorted({date.fromisoformat(e["end"]) for tags in TAGS.values() for tag in tags
                      for ents in gaap.get(tag, {}).get("units", {}).values() for e in ents
                      if e.get("fp") == "FY" and e.get("form") in ("10-K", "10-K/A") and "start" in e and _duration(e) == "annual"})

    def label(end_s: str, kind: str, fp: str) -> str:
        end = date.fromisoformat(end_s)
        if kind == "annual":
            return f"FY{fy_name(end)}"
        following = next((d for d in fy_ends if d >= end and (d - end).days < 400), None)
        year = fy_name(following) if following else (fy_name(fy_ends[-1]) + 1 if fy_ends else end.year + off)
        return f"{'Q4' if fp == 'FY' else fp} FY{year}"

    for metric, tags in TAGS.items():
        # Collect every filing's value for each period across all tags. Companies re-tag items over time, so the
        # period's label and first-public date must come from the earliest filing under ANY tag.
        periods: dict[tuple[str, str], list[tuple[int, str, str, dict]]] = {}
        for priority, tag in enumerate(tags):
            for unit_name, entries in gaap.get(tag, {}).get("units", {}).items():
                if unit_name not in UNIT_FOR:
                    continue
                for e in entries:
                    if e.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A") or "start" not in e:
                        continue
                    kind = _duration(e)
                    if date.fromisoformat(e["end"]) < FIRST_PERIOD_END or not kind:
                        continue
                    if (kind == "annual") != (e["fp"] == "FY") and kind == "annual":
                        continue   # a trailing-twelve-month figure inside a 10-Q is not a fiscal year
                    if kind == "quarter" and e["fp"] not in ("Q1", "Q2", "Q3", "FY"):
                        continue
                    periods.setdefault((e["start"], e["end"]), []).append((priority, tag, UNIT_FOR[unit_name], e))
        for (start, end), items in periods.items():
            best: dict[str, tuple[int, str, str, dict]] = {}     # one value per filing: highest-priority tag wins
            for it in items:
                if it[3]["accn"] not in best or it[0] < best[it[3]["accn"]][0]:
                    best[it[3]["accn"]] = it
            es = sorted(best.values(), key=lambda it: (it[3]["filed"], it[3]["accn"]))
            kind = _duration(es[0][3])
            primary = next((it[3] for it in es if it[3]["form"] in ("10-K", "10-Q")), es[0][3])
            lab = label(end, kind, primary["fp"])
            prev = None
            for _, tag, unit, e in es:
                if prev is not None and e["val"] == prev:
                    continue  # same number re-filed as a comparative; not a new version
                note = "original filing" if prev is None else f"restated (previously {prev:g})"
                accn = e["accn"]
                digest = hashlib.sha256(json.dumps({"cik": cik, "tag": tag, **e}, sort_keys=True).encode()).hexdigest()
                out.append(Snapshot(
                    claim_type="fundamental", ticker=ticker, metric=metric, period=lab,
                    duration="FY" if kind == "annual" else "Q", period_end=end, value=float(e["val"]), unit=unit,
                    as_of=e["filed"], source=f"SEC EDGAR {e['form']} ({tag})",
                    source_url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{accn}-index.htm",
                    hash=digest, note=note))
                prev = e["val"]
    return out


def load_companies() -> dict[str, dict]:
    return json.loads(COMPANIES.read_text())


def ingest(store: TruthStore, tickers: list[str] | None = None, pause: float = 0.25) -> dict[str, int]:
    """Fetch and (re)load fundamentals. Returns rows loaded per ticker."""
    companies = load_companies()
    counts: dict[str, int] = {}
    with httpx.Client(headers={"User-Agent": user_agent()}, timeout=60) as client:
        for t in tickers or list(companies):
            rows = snapshots_from_facts(t, companies[t]["cik"], fetch_facts(companies[t]["cik"], client))
            store.clear(t, "fundamental")
            for s in rows:
                store.add(s)
            store.commit()
            counts[t] = len(rows)
            time.sleep(pause)
    return counts


def refresh(store: TruthStore, ticker: str) -> None:
    """Re-fetch one company. Used when the store may be behind the filings; any US-listed ticker works, not only the shipped set."""
    from . import sources
    sources.refresh(store, ticker)
