"""Quote feed.

SYNTHETIC reference prices for the mandate check (order size) and for the price-claim tests. They are round numbers
chosen by hand, flat over time, and say so in their `source` field. They exist so the demo and the
eval run with no market-data licence. Swap in a real read-only feed here (Futu OpenD quotes are the
intended one) without touching the verifier: it only asks the truth store for the latest quote.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from .truth_store import Snapshot, TruthStore

PRICES = {
    "AAPL": 230.0, "MSFT": 410.0, "AMZN": 215.0, "GOOGL": 185.0, "META": 600.0, "NVDA": 130.0, "TSLA": 320.0,
    "JNJ": 155.0, "WMT": 90.0, "XOM": 110.0, "PG": 165.0, "KO": 62.5, "PEP": 150.0, "DIS": 110.0, "NFLX": 900.0,
    "INTC": 22.0, "AMD": 120.0, "CSCO": 60.0, "ORCL": 170.0, "BA": 175.0, "NKE": 75.0, "MCD": 290.0, "PFE": 26.0,
    "F": 10.5, "COST": 950.0, "ADBE": 450.0, "CRM": 320.0, "MRNA": 40.0, "PTON": 7.0, "SNAP": 9.0,
}
SOURCE = "SYNTHETIC reference quote (demo only, not market data)"
FIRST, LAST = date(2024, 1, 1), date(2026, 12, 31)


def load(store: TruthStore) -> int:
    """(Re)write one synthetic quote per ticker per weekday."""
    n = 0
    for ticker, px in PRICES.items():
        store.clear(ticker, "price")
        d = FIRST
        while d <= LAST:
            if d.weekday() < 5:
                digest = hashlib.sha256(f"synthetic|{ticker}|{d}|{px}".encode()).hexdigest()
                store.add(Snapshot(claim_type="price", ticker=ticker, metric="price", value=px, unit="USD", as_of=d.isoformat(),
                                   source=SOURCE, source_url="https://github.com/ (this repository: orderguard_verify/quotes.py)",
                                   hash=digest))
                n += 1
            d += timedelta(days=1)
    store.commit()
    return n
