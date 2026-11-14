"""The bench market: real recorded price paths plus a seeded synthetic book of names.

  BTCUSDT, ETHUSDT, SOLUSDT   the recorded Binance public feed in data/arena/feeds/ (bookTicker + last, one exchange). The recording is 144
                              ticks long; longer runs play it forwards then backwards (ping-pong), so every price move is a real one but
                              the time axis repeats. Quotes are bid / last / ask, so the trusted median is `last` inside the spread.
  15 synthetic names          `orderguard_arena.feeds.ReplayFeed` (seeded GBM with jumps, three venues, an occasional lying venue, genuine
                              and fake news). They carry the news that drives L7 and give the swarm a realistic number of symbols.

Everything is deterministic for a seed. `quotes(step)` is raw venue data; the auditor computes its own trusted price from it.
"""
from __future__ import annotations

from pathlib import Path

from orderguard_arena.feeds import RecordedFeed, ReplayFeed, Snapshot
from orderguard_guard import ROOT

FEED = ROOT / "data" / "arena" / "feeds" / "binance-public-20261111T000117Z.jsonl"


def pingpong(t: int, n: int) -> int:
    """Index into a recording of n ticks for step t, played forwards then backwards so the path never jumps."""
    if n <= 1:
        return 0
    period = 2 * (n - 1)
    r = t % period
    return r if r < n else period - r


class BenchMarket:
    def __init__(self, seed: int, steps: int, steps_per_day: int, feed_path: str | Path = FEED):
        self.seed, self.steps, self.steps_per_day = int(seed), int(steps), int(steps_per_day)
        self.recorded = RecordedFeed(feed_path, steps_per_day=steps_per_day)
        self.synthetic = ReplayFeed(seed, steps=steps, steps_per_day=steps_per_day)
        self.real_symbols = list(self.recorded.symbols)
        self.symbols = list(self.synthetic.symbols) + self.real_symbols
        rec = list(self.recorded)
        self.snaps: list[Snapshot] = []
        for snap in self.synthetic:
            r = rec[pingpong(snap.step, len(rec))]
            quotes = dict(snap.quotes)
            quotes.update(r.quotes)
            self.snaps.append(Snapshot(snap.step, snap.day, snap.ts, quotes, snap.news, snap.meta))
        self.trusted = [s.trusted() for s in self.snaps]
        self.recording_ticks = len(rec)

    def __len__(self) -> int:
        return self.steps

    def __iter__(self):
        return iter(self.snaps)

    def describe(self) -> dict:
        return {"real_symbols": self.real_symbols, "synthetic_symbols": list(self.synthetic.symbols), "recording": FEED.name,
                "recording_ticks": self.recording_ticks, "steps": self.steps, "steps_per_day": self.steps_per_day,
                "note": "real symbols replay the recorded Binance path ping-pong; synthetic names are a seeded GBM feed with news"}
