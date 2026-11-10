"""Truth store: dated snapshots of trusted facts, kept in SQLite.

Every row says what the fact is, when it became public (`as_of`), where it came from and a hash of
the source record. Lookups take a decision date and never return anything filed after it, so a
number restated in 2025 cannot be used to judge a decision made in 2024.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date
from pathlib import Path

from ..core.models import Evidence

from ..paths import DATA

DEFAULT_DB = DATA / "truth.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    claim_type TEXT NOT NULL,      -- fundamental | price
    ticker TEXT NOT NULL,
    metric TEXT NOT NULL,
    period TEXT,                   -- FY2024, Q3 FY2025 (null for prices)
    duration TEXT,                 -- FY | Q
    period_end TEXT,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    as_of TEXT NOT NULL,           -- date the figure became public (filing date / quote date)
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    hash TEXT NOT NULL,
    note TEXT
);
CREATE INDEX IF NOT EXISTS snap_lookup ON snapshots (ticker, metric, period, as_of);
CREATE TABLE IF NOT EXISTS fetched (ticker TEXT PRIMARY KEY, ts REAL);   -- when a company was last pulled from EDGAR on demand
"""


class Snapshot(Evidence):
    claim_type: str
    ticker: str
    metric: str
    duration: str | None = None
    period_end: str | None = None
    note: str | None = None


class TruthStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()      # one connection is shared by the eval's worker threads; cursors must not interleave

    def add(self, s: Snapshot) -> None:
        self.db.execute(
            "INSERT INTO snapshots (claim_type,ticker,metric,period,duration,period_end,value,unit,as_of,"
            "source,source_url,hash,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s.claim_type, s.ticker, s.metric, s.period, s.duration, s.period_end, s.value, s.unit,
             s.as_of, s.source, s.source_url, s.hash, s.note),
        )

    def clear(self, ticker: str, claim_type: str) -> None:
        self.db.execute("DELETE FROM snapshots WHERE ticker=? AND claim_type=?", (ticker, claim_type))

    def commit(self) -> None:
        self.db.commit()

    # --- lookups -------------------------------------------------------------------------------

    def _rows(self, sql: str, args: tuple) -> list[Snapshot]:
        with self.lock:
            return [Snapshot(**dict(r)) for r in self.db.execute(sql, args).fetchall()]

    def versions(self, ticker: str, metric: str, period: str, as_of: date, include_future: bool = False) -> list[Snapshot]:
        """All versions of one figure, newest first. By default only those public on `as_of`."""
        cut = "" if include_future else "AND as_of <= ?"
        args = (ticker, metric, period) + (() if include_future else (as_of.isoformat(),))
        return self._rows(
            f"SELECT * FROM snapshots WHERE ticker=? AND metric=? AND period=? {cut} ORDER BY as_of DESC, id DESC", args)

    def by_period_end(self, ticker: str, metric: str, period_end: date, as_of: date) -> list[Snapshot]:
        return self._rows(
            "SELECT * FROM snapshots WHERE ticker=? AND metric=? AND period_end=? AND as_of<=? ORDER BY as_of DESC, id DESC",
            (ticker, metric, period_end.isoformat(), as_of.isoformat()))

    def latest_period(self, ticker: str, metric: str, duration: str, as_of: date) -> Snapshot | None:
        """The most recent period (by period end) that was public on `as_of`, in its newest version."""
        rows = self._rows(
            "SELECT * FROM snapshots WHERE ticker=? AND metric=? AND duration=? AND as_of<=? "
            "ORDER BY period_end DESC, as_of DESC, id DESC LIMIT 1", (ticker, metric, duration, as_of.isoformat()))
        return rows[0] if rows else None

    def older_periods(self, ticker: str, metric: str, latest: Snapshot, as_of: date, n: int = 8) -> list[Snapshot]:
        """Earlier periods of the same length, newest first, one row (newest version) per period."""
        rows = self._rows(
            "SELECT * FROM snapshots WHERE ticker=? AND metric=? AND duration=? AND period_end<? AND as_of<=? "
            "ORDER BY period_end DESC, as_of DESC, id DESC", (ticker, metric, latest.duration, latest.period_end, as_of.isoformat()))
        seen: set[str] = set()
        out = []
        for r in rows:
            if r.period not in seen:
                seen.add(r.period)
                out.append(r)
        return out[:n]

    def periods(self, ticker: str, metric: str, duration: str, as_of: date) -> list[Snapshot]:
        """Every period of one length public on `as_of`, in its newest version, newest period first."""
        rows = self._rows("SELECT * FROM snapshots WHERE ticker=? AND metric=? AND duration=? AND as_of<=? "
                          "ORDER BY period_end DESC, as_of DESC, id DESC", (ticker, metric, duration, as_of.isoformat()))
        seen: set[str] = set()
        return [r for r in rows if not (r.period in seen or seen.add(r.period))]

    def latest_filing_date(self, ticker: str, as_of: date) -> date | None:
        with self.lock:
            r = self.db.execute("SELECT MAX(as_of) FROM snapshots WHERE ticker=? AND claim_type='fundamental' AND as_of<=?",
                                (ticker, as_of.isoformat())).fetchone()
        return date.fromisoformat(r[0]) if r and r[0] else None

    def quote(self, ticker: str, as_of: date) -> Snapshot | None:
        """Latest price snapshot on or before `as_of`."""
        rows = self._rows(
            "SELECT * FROM snapshots WHERE claim_type='price' AND ticker=? AND as_of<=? ORDER BY as_of DESC, id DESC LIMIT 1",
            (ticker, as_of.isoformat()))
        return rows[0] if rows else None

    def all_public(self, ticker: str, as_of: date) -> list[Snapshot]:
        """Every fundamental figure public on `as_of`, all versions, oldest period first (what a human or a judge model would be shown)."""
        return self._rows("SELECT * FROM snapshots WHERE ticker=? AND claim_type='fundamental' AND as_of<=? ORDER BY metric, period_end, as_of",
                          (ticker, as_of.isoformat()))

    def mark_fetched(self, ticker: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO fetched VALUES (?, strftime('%s','now'))", (ticker,))
        self.db.commit()

    def fetched_age_days(self, ticker: str) -> float | None:
        """Days since this company was pulled on demand; None if it was loaded in bulk (treated as fresh)."""
        r = self.db.execute("SELECT (strftime('%s','now') - ts) / 86400.0 FROM fetched WHERE ticker=?", (ticker,)).fetchone()
        return r[0] if r else None

    def has_fundamentals(self, ticker: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM snapshots WHERE ticker=? AND claim_type='fundamental' LIMIT 1", (ticker,)).fetchone() is not None

    def tickers(self) -> list[str]:
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT DISTINCT ticker FROM snapshots ORDER BY ticker").fetchall()]
