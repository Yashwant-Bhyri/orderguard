"""Market feeds for the arena. Every feed yields `Snapshot`s: one per step, quotes from several venues per symbol.

  ReplayFeed(seed, symbols, steps)   deterministic synthetic ticks (default, offline): geometric Brownian motion, jumps and
                                     calm/volatile regime changes, three venues per symbol, an occasional lying venue, and
                                     news items (genuine ones have two or more independent origins, fake ones a single origin).
  BinancePublicFeed(symbols)         read-only public market data from api.binance.com (GET bookTicker and ticker/price only,
                                     no keys, no orders). Every snapshot can be recorded to a JSONL file.
  RecordedFeed(path)                 replays such a recording exactly.

The TRUSTED price of a symbol is the median across its venue quotes (the L7 idea: one liar cannot move the median).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Protocol

import numpy as np

VENUES = ("VenueA", "VenueB", "VenueC")
WIRES = ("WireOne", "WireTwo", "WireThree")
BASE_DATE = dt.date(2026, 1, 5)

DEFAULT_SYMBOLS = ["AAPL", "MSFT", "JNJ", "KO", "JPM", "SPY",                 # core
                   "NVDA", "TSLA", "GOOGL", "AMZN", "QQQ", "XOM",             # tactical
                   "BTC-USD", "ETH-USD", "SOL-USD"]                           # crypto sleeve (simulated)


def median_price(venue_quotes: dict[str, float]) -> float:
    v = sorted(venue_quotes.values())
    n = len(v)
    if n == 0:
        raise ValueError("no quotes")
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


@dataclass(slots=True)
class Snapshot:
    step: int
    day: int
    ts: str
    quotes: dict                                   # symbol -> {venue: price}
    news: list = field(default_factory=list)       # TriggerGraph-style headline events
    meta: dict = field(default_factory=dict)       # ground truth for the oracle only: liars, fake news ids. Agents never read it.

    def trusted(self) -> dict[str, float]:
        return {s: round(median_price(q), 4) for s, q in self.quotes.items()}


class MarketFeed(Protocol):
    symbols: list[str]
    steps_per_day: int

    def __iter__(self) -> Iterator[Snapshot]: ...


def _ts(day: int, step_in_day: int, steps_per_day: int) -> str:
    base = dt.datetime.combine(BASE_DATE + dt.timedelta(days=day), dt.time(9, 30), tzinfo=dt.timezone.utc)
    secs = int(step_in_day * (6.5 * 3600) / max(steps_per_day, 1))
    return (base + dt.timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReplayFeed:
    """Deterministic synthetic market. Same (seed, symbols, steps, params) -> the same ticks on every machine."""

    def __init__(self, seed: int = 7, symbols: list[str] | None = None, steps: int = 2000, *, steps_per_day: int = 500,
                 vol_scale: float = 1.0, lie_rate: float = 0.004, news_jump_rate: float = 0.0004, fake_news_rate: float = 0.0006):
        self.seed, self.steps, self.steps_per_day = int(seed), int(steps), int(steps_per_day)
        self.symbols = list(symbols or DEFAULT_SYMBOLS)
        self.vol_scale, self.lie_rate = float(vol_scale), float(lie_rate)
        self.news_jump_rate, self.fake_news_rate = float(news_jump_rate), float(fake_news_rate)
        self._gen()

    def _gen(self) -> None:
        rng = np.random.default_rng(self.seed)
        S, T = len(self.symbols), self.steps
        crypto = np.array([s.endswith("-USD") or s.endswith("USDT") for s in self.symbols])
        start = np.where(crypto, rng.uniform(60, 300, S), np.exp(rng.uniform(math.log(25), math.log(450), S)))
        sigma = np.where(crypto, rng.uniform(0.0025, 0.0045, S), rng.uniform(0.0007, 0.0020, S)) * self.vol_scale
        # market-wide regime: 0 calm, 1 volatile (vol x3), sticky
        regime = np.zeros(T, dtype=int)
        r = 0
        u = rng.random(T)
        for t in range(T):
            if r == 0 and u[t] < 0.0015:
                r = 1
            elif r == 1 and u[t] < 0.010:
                r = 0
            regime[t] = r
        mult = np.where(regime == 1, 3.0, 1.0)[:, None]
        z = rng.standard_normal((T, S))
        jump_hit = (rng.random((T, S)) < self.news_jump_rate * (1 if self.vol_scale > 0 else 0))
        jump_sz = rng.normal(0, 0.035, (T, S))
        jump_sz = np.sign(jump_sz) * np.clip(np.abs(jump_sz), 0.015, 0.09)
        rets = (sigma[None, :] * mult * z) + np.where(jump_hit, jump_sz, 0.0)
        logp = np.log(start)[None, :] + np.cumsum(rets, axis=0)
        self._true = np.exp(logp)
        # venue noise (3 bps) and the occasional liar (one venue prints 20-50% off for one step)
        noise = rng.normal(0, 0.0003, (T, S, len(VENUES))) * (1 if self.vol_scale > 0 else 0)
        liar_hit = rng.random((T, S)) < self.lie_rate * (1 if self.vol_scale > 0 else 0)
        liar_venue = rng.integers(0, len(VENUES), (T, S))
        liar_off = rng.uniform(0.2, 0.5, (T, S)) * rng.choice([-1.0, 1.0], (T, S))
        self._noise, self._liar_hit, self._liar_venue, self._liar_off = noise, liar_hit, liar_venue, liar_off
        # news: genuine jumps are reported by three independent wires; fake news by one origin (echoed or not)
        fake_hit = rng.random((T, S)) < self.fake_news_rate * (1 if self.vol_scale > 0 else 0)
        fake_pct = rng.uniform(8, 25, (T, S)) * rng.choice([-1.0, 1.0], (T, S))
        fake_echo = rng.random((T, S)) < 0.5
        self._jump_hit, self._jump_sz = jump_hit, jump_sz
        self._fake_hit, self._fake_pct, self._fake_echo = fake_hit, fake_pct, fake_echo

    def __len__(self) -> int:
        return self.steps

    def trusted_first(self) -> dict[str, float]:
        """Trusted prices at step 0 (used by the API's order-fit demo)."""
        return next(iter(self)).trusted()

    def __iter__(self) -> Iterator[Snapshot]:
        nid = 0
        for t in range(self.steps):
            quotes, news, liars, fakes = {}, [], {}, []
            for j, sym in enumerate(self.symbols):
                p = float(self._true[t, j])
                q = {}
                for k, v in enumerate(VENUES):
                    px = p * (1.0 + float(self._noise[t, j, k]))
                    if self._liar_hit[t, j] and self._liar_venue[t, j] == k:
                        px = p * (1.0 + float(self._liar_off[t, j]))
                        liars[sym] = v
                    q[v] = round(px, 4)
                quotes[sym] = q
                if self._jump_hit[t, j]:
                    nid += 1
                    pct = round(float(self._jump_sz[t, j]) * 100, 2)
                    text = f"{sym} {'surges' if pct > 0 else 'plunges'} {abs(pct):.1f}% on company news"
                    news += [{"src": w, "type": "headline", "ticker": sym, "text": text, "origin": w, "news_id": f"N{nid}", "pct": pct} for w in WIRES]
                if self._fake_hit[t, j]:
                    nid += 1
                    pct = round(float(self._fake_pct[t, j]), 2)
                    text = f"{sym} {'to be taken over at a large premium' if pct > 0 else 'under investigation, shares seen collapsing'} - sources"
                    fakes.append(f"N{nid}")
                    origin = "RumourMill"
                    wires = WIRES if self._fake_echo[t, j] else WIRES[:1]
                    news += [{"src": w, "type": "headline", "ticker": sym, "text": text, "origin": origin, "news_id": f"N{nid}", "pct": pct} for w in wires]
            day, sid = divmod(t, self.steps_per_day)
            yield Snapshot(t, day, _ts(day, sid, self.steps_per_day), quotes, news, {"liars": liars, "fake_news": fakes})


# ---- Binance public market data (read-only) -------------------------------------------------------------------------------

BINANCE_PUBLIC_BASE = "https://api.binance.com"
BINANCE_PUBLIC_HOSTS = ("https://api.binance.com", "https://data-api.binance.vision")   # the second is Binance's market-data-only mirror (same endpoints)
BINANCE_PUBLIC_PATHS = ("/api/v3/ticker/bookTicker", "/api/v3/ticker/price")      # the only two endpoints this feed may call
DEFAULT_UNIT_SIZE = {"BTCUSDT": 0.001, "ETHUSDT": 0.01, "SOLUSDT": 1.0}            # one arena "unit" = this much base asset


class FeedError(RuntimeError):
    pass


class BinancePublicFeed:
    """Read-only public market data. GET bookTicker and ticker/price on api.binance.com, no API key, no order endpoint.

    Three quotes per symbol are derived from ONE exchange ("bid", "last", "ask"); their median is `last` clamped into [bid, ask].
    They are not independent venues, so this feed cannot show cross-venue lies; it is real prices on a real tape.
    Quotes are per arena unit (price x `unit_size`) so that one whole unit is a tradable size under the envelope caps.
    """

    def __init__(self, symbols: list[str], *, interval_s: float = 1.0, duration_s: float | None = 180.0, max_steps: int | None = None,
                 record_path: str | Path | None = None, unit_size: dict | None = None, steps_per_day: int = 60,
                 fetch: Callable[[str, dict], object] | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, base_url: str = BINANCE_PUBLIC_BASE,
                 attempts_per_tick: int = 3, max_backoff_s: float = 30.0, max_failed_ticks: int = 5):
        if base_url not in BINANCE_PUBLIC_HOSTS:
            raise FeedError(f"base_url must be one of {BINANCE_PUBLIC_HOSTS}: this feed reads public market data only")
        self.base_url = base_url
        self.symbols = [s.upper() for s in symbols]
        self.interval_s, self.duration_s, self.max_steps = float(interval_s), duration_s, max_steps
        self.record_path = Path(record_path) if record_path else None
        self.unit_size = {s: float((unit_size or DEFAULT_UNIT_SIZE).get(s, 1.0)) for s in self.symbols}
        self.steps_per_day = int(steps_per_day)
        self._fetch = fetch or self._http_fetch
        self._sleep, self._clock = sleep, clock
        self._client = None
        self.errors = 0
        self.attempts_per_tick, self.max_backoff_s, self.max_failed_ticks = max(int(attempts_per_tick), 1), float(max_backoff_s), max(int(max_failed_ticks), 1)
        self.backoffs: list[float] = []                # every delay slept after a failed attempt (inspectable in tests and logs)

    def _http_fetch(self, path: str, params: dict):
        import httpx
        if path not in BINANCE_PUBLIC_PATHS:
            raise FeedError("this feed only reads public price endpoints")
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, timeout=10.0, follow_redirects=False)
        r = self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def _poll(self) -> dict[str, dict[str, float]]:
        arr = json.dumps(self.symbols, separators=(",", ":"))
        book = {d["symbol"]: d for d in self._fetch("/api/v3/ticker/bookTicker", {"symbols": arr})}
        last = {d["symbol"]: d for d in self._fetch("/api/v3/ticker/price", {"symbols": arr})}
        out = {}
        for s in self.symbols:
            u = self.unit_size[s]
            bid, ask, px = float(book[s]["bidPrice"]) * u, float(book[s]["askPrice"]) * u, float(last[s]["price"]) * u
            if not all(math.isfinite(v) and v > 0 for v in (bid, ask, px)):
                raise ValueError(f"non-positive or non-finite quote for {s}")         # a bad payload is a failed poll, never a recorded tick
            out[s] = {"bid": round(bid, 6), "last": round(px, 6), "ask": round(ask, 6)}
        return out

    @staticmethod
    def _retry_after(exc: Exception) -> float | None:
        """Seconds the endpoint asked us to wait (HTTP 429 or 418 with a Retry-After header), else None."""
        resp = getattr(exc, "response", None)
        if resp is None or getattr(resp, "status_code", None) not in (418, 429):
            return None
        try:
            return max(float(resp.headers.get("Retry-After", "")), 0.0)
        except (TypeError, ValueError, AttributeError):
            return None

    def _delay(self, failures: int, exc: Exception) -> float:
        """Deterministic exponential backoff (interval x 2^(failures-1), capped); a server-sent Retry-After wins, capped at 60 s."""
        asked = self._retry_after(exc)
        d = min(asked, 60.0) if asked is not None else min(self.interval_s * 2 ** (failures - 1), self.max_backoff_s)
        self.backoffs.append(d)
        return d

    def _poll_with_retries(self) -> dict[str, dict[str, float]]:
        """One tick's data: up to `attempts_per_tick` attempts with exponential backoff between them. Raises the last error if all fail."""
        last_exc: Exception | None = None
        for attempt in range(1, self.attempts_per_tick + 1):
            try:
                return self._poll()
            except Exception as e:                       # network hiccup, HTTP 429/5xx, malformed payload
                last_exc = e
                self.errors += 1
                if attempt < self.attempts_per_tick:
                    self._sleep(self._delay(attempt, e))
        assert last_exc is not None
        raise last_exc

    def __iter__(self) -> Iterator[Snapshot]:
        fh = None
        if self.record_path:
            self.record_path.parent.mkdir(parents=True, exist_ok=True)
            fh = self.record_path.open("w")
            fh.write(json.dumps({"type": "meta", "source": f"{self.base_url.split('//')[1]} public market data (bookTicker, ticker/price); no orders",
                                 "symbols": self.symbols, "unit_size": self.unit_size, "interval_s": self.interval_s,
                                 "steps_per_day": self.steps_per_day,
                                 "started_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
        t0, step, consecutive = self._clock(), 0, 0
        try:
            while True:
                if self.max_steps is not None and step >= self.max_steps:
                    break
                if self.duration_s is not None and self._clock() - t0 >= self.duration_s:
                    break
                try:
                    quotes = self._poll_with_retries()
                    consecutive = 0
                except Exception as e:                     # every attempt for this tick failed: skip the tick (the recording gets a gap, never a guess)
                    consecutive += 1
                    if consecutive >= self.max_failed_ticks:
                        raise FeedError(f"{consecutive} consecutive ticks failed after {self.attempts_per_tick} attempts each reading public data "
                                        f"({type(e).__name__}); the recording so far is valid and ends at step {step}") from None
                    self._sleep(self._delay(consecutive, e))
                    continue
                day, sid = divmod(step, self.steps_per_day)
                ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if fh:
                    fh.write(json.dumps({"type": "tick", "step": step, "ts": ts, "quotes": quotes}, separators=(",", ":")) + "\n")
                    fh.flush()
                yield Snapshot(step, day, ts, quotes)
                step += 1
                self._sleep(self.interval_s)
        finally:
            if fh:
                fh.close()
            if self._client is not None:
                self._client.close()


class RecordedFeed:
    """Replays a JSONL recording exactly (header line + one tick line per step)."""

    def __init__(self, path: str | Path, steps_per_day: int | None = None):
        self.path = Path(path)
        self.meta, self._ticks, self._lines = {}, [], []
        try:
            text = self.path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FeedError("the recording must be UTF-8") from exc
        lines = text.split("\n")
        last_n = max((n for n, ln in enumerate(lines, 1) if ln.strip()), default=0)
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except (ValueError, RecursionError) as exc:
                if n == last_n and not text.endswith("\n"):
                    raise FeedError(f"the recording is truncated: line {n} is cut off mid-record (an interrupted recording?). "
                                    f"Drop that line or re-record; {len(self._ticks)} complete ticks precede it") from exc
                raise FeedError(f"invalid JSON on line {n}") from exc
            if not isinstance(d, dict):
                raise FeedError(f"expected a JSON object on line {n}")
            if d.get("type") == "meta":
                self.meta = d
            elif d.get("type") == "tick":
                if not isinstance(d.get("ts"), str) or not d["ts"] or not self._valid_quotes(d.get("quotes")):
                    raise FeedError(f"invalid timestamp or quotes on line {n}")
                self._ticks.append(d)
                self._lines.append(n)
        if not self._ticks:
            raise FeedError("the recording holds no ticks")
        symbols = self.meta.get("symbols", list(self._ticks[0]["quotes"]))
        if not isinstance(symbols, list) or not symbols or not all(isinstance(s, str) and s.strip() for s in symbols):
            raise FeedError("symbols must be a nonempty list of ticker names")
        if "symbols" in self.meta:                     # a tick that lacks a declared symbol would crash agents mid-run: refuse it up front
            for n, d in zip(self._lines, self._ticks):
                missing = [x for x in symbols if x not in d["quotes"]]
                if missing:
                    raise FeedError(f"line {n}: the tick has no quotes for {', '.join(map(str, missing[:3]))} (declared in the header)")
        self.symbols = symbols
        self.steps_per_day = steps_per_day if steps_per_day is not None else self.meta.get("steps_per_day", 60)
        if type(self.steps_per_day) is not int or self.steps_per_day < 1:
            raise FeedError("steps_per_day must be a positive integer")

    @staticmethod
    def _valid_quotes(quotes) -> bool:
        if not isinstance(quotes, dict) or not quotes:
            return False
        try:
            return all(symbol.strip() and isinstance(venues, dict) and venues and all(
                type(price) in (int, float) and math.isfinite(price) and round(price, 4) > 0 for price in venues.values()
            ) for symbol, venues in quotes.items())
        except OverflowError:
            return False

    def __len__(self) -> int:
        return len(self._ticks)

    def __iter__(self) -> Iterator[Snapshot]:
        for i, d in enumerate(self._ticks):
            day = i // self.steps_per_day
            yield Snapshot(i, day, d["ts"], d["quotes"])
