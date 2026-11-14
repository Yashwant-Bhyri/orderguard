"""Getting the trusted data on demand: any US-listed company with US-GAAP filings, fetched from SEC EDGAR when first
asked for and cached in the truth store. SEC fair-access rules: descriptive User-Agent without contact details, a pause
between requests (well under 10 a second), a retry with back-off on 429/5xx."""
from __future__ import annotations

import json
import threading
import time

import httpx

from ..core.pack import SourceUnavailable
from ..paths import VAR
from . import edgar
from .models import normalise_ticker
from .truth_store import TruthStore

TICKER_MAP = "https://www.sec.gov/files/company_tickers.json"
MAX_AGE_DAYS = 30
PAUSE = 0.15          # at least this long between any two requests from this process: under 7 a second (SEC allows 10)
_gate = threading.Lock()
_last = [0.0]


def _throttle() -> None:
    """Process-wide spacing of SEC requests, safe across threads."""
    with _gate:
        wait = _last[0] + PAUSE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def _get(client: httpx.Client, url: str) -> httpx.Response:
    for attempt in range(4):
        _throttle()
        r = client.get(url)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt * 2)
            continue
        return r
    raise SourceUnavailable("SEC EDGAR is rate-limiting or down; try again in a minute")


def lookup_cik(client: httpx.Client, ticker: str) -> int | None:
    known = edgar.load_companies()
    if ticker in known:
        return known[ticker]["cik"]
    cache = VAR / "company_tickers.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 7 * 86400:
        mapping = json.loads(cache.read_text())
    else:
        r = _get(client, TICKER_MAP)
        r.raise_for_status()
        mapping = r.json()
        VAR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(mapping))
    return next((row["cik_str"] for row in mapping.values() if row["ticker"].upper() == ticker), None)


def ensure(store: TruthStore, ticker: str, force: bool = False) -> None:
    """Make sure `ticker` is in the store and not older than MAX_AGE_DAYS (`force` re-fetches regardless). Works for any
    US-listed ticker, not only the shipped set. Raises SourceUnavailable with a plain reason."""
    ticker = normalise_ticker(ticker)
    if ticker is None:
        raise SourceUnavailable("not a plain ticker symbol")
    have = store.has_fundamentals(ticker)
    age = store.fetched_age_days(ticker)
    if have and not force and (age is None or age < MAX_AGE_DAYS):
        return
    try:
        with httpx.Client(headers={"User-Agent": edgar.user_agent()}, timeout=60, follow_redirects=True) as client:
            cik = lookup_cik(client, ticker)
            if cik is None:
                raise SourceUnavailable(f"{ticker} is not a US-listed ticker known to SEC EDGAR")
            r = _get(client, edgar.FACTS_URL.format(cik=cik))
            if r.status_code == 404:
                raise SourceUnavailable(f"{ticker} has no financial-statement data on EDGAR (not a US-GAAP filer)")
            r.raise_for_status()
            rows = edgar.snapshots_from_facts(ticker, cik, r.json())
    except SourceUnavailable:
        if have:
            return     # a refresh failed; the older data is still the best there is
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, OverflowError, OSError) as e:
        # network down, a non-JSON or oddly shaped reply, a read-only cache directory: all mean "no trusted data right now"
        if have:
            return
        raise SourceUnavailable(f"could not fetch {ticker} from SEC EDGAR ({type(e).__name__}); check the network, or load the truth store ahead of time "
                                "(og ingest) and retry") from e
    if not rows:
        if have:
            return
        raise SourceUnavailable(f"{ticker} has no US-GAAP annual figures on EDGAR (foreign filer or too new)")
    store.clear(ticker, "fundamental")
    for s in rows:
        store.add(s)
    store.commit()
    store.mark_fetched(ticker)


def refresh(store: TruthStore, ticker: str) -> None:
    """Re-fetch one company now (the store may be behind the filings). Works for tickers outside the shipped set."""
    ensure(store, ticker, force=True)
