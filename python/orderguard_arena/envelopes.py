"""Envelopes: a human-signed Mandate plus metadata, with a daily budget shared by every agent that draws on it.

The envelope's limits are the signed Mandate (gate.sign_mandate, Ed25519 over canonical JSON). `owner`, `purpose` and `name` are
metadata, not signed limits. Agents never choose, create or widen an envelope: the book is built by the human (or by the lab,
which only advises: see frontier.py) and handed to the authority.

`Envelope.check` applies exactly the L5 rules of `orderguard_guard.gate.OrderGate`, at the TRUSTED price, without re-verifying the
signature on every order (it is verified once, when the envelope is added). `tests/arena/test_authority.py` checks parity
against OrderGate on thousands of random orders.

`DailyBudget` is the arena's version of the receiver's invariant I2: one running total per envelope and day, reserved
atomically, so concurrent agents can never together exceed the daily cap.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import threading
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from orderguard_guard.gate import (Mandate, MandateInvalid, _parse_time, normalise_ticker, public_key_to_b64, sign_mandate)
import unicodedata

FAR_FUTURE = "2099-01-01T00:00:00Z"


def owner_key_from_seed(label: str) -> Ed25519PrivateKey:
    """A SIMULATED owner key derived from a public label. It is deterministic so runs reproduce, and it is not a secret."""
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(("orderguard-arena-owner:" + label).encode()).digest())


class DailyBudget:
    """Per-day running total with an atomic check-and-reserve. Kept in integer cents, like the receiver's ledger, so the two never differ by rounding.

    What counts: every order that is allowed OR held for a human (the receiver counts `status IN ('filled','held')`). A held order therefore
    reserves its notional when it is held, and a later approval does not reserve again.
    """

    def __init__(self, cap: float):
        self.cap = float(cap)
        self._cap_c = round(self.cap * 100)
        self._used: dict[int, int] = {}
        self._agent: dict = {}
        self._lock = threading.Lock()

    def used(self, day: int) -> float:
        return self._used.get(day, 0) / 100.0

    def reserve(self, day: int, amount: float, agent=None, agent_cap: float | None = None) -> bool:
        """Atomically add `amount` to the day's total unless that would pass the cap. With `agent_cap`, one agent may also not pass its own share."""
        c = round(amount * 100)
        with self._lock:
            cur = self._used.get(day, 0)
            if cur + c > self._cap_c:
                return False
            if agent_cap is not None:
                k = (day, agent)
                mine = self._agent.get(k, 0)
                if mine + c > round(agent_cap * 100):
                    return False
                self._agent[k] = mine + c
            self._used[day] = cur + c
            return True

    def total_by_day(self) -> dict[int, float]:
        with self._lock:
            return {d: c / 100.0 for d, c in self._used.items()}


@dataclass
class Envelope:
    mandate: dict                       # the signed Mandate JSON (CONTRACT 5.1 shape)
    name: str = "envelope"
    owner: str = "owner-1"
    purpose: str = ""
    m: Mandate = field(init=False)
    id: str = field(init=False)
    budget: DailyBudget = field(init=False)
    revoked: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.m = Mandate.from_dict(self.mandate)
        self.id = self.m.id
        self.budget = DailyBudget(self.m.maxDailyNotionalUsd)
        self.allowed = frozenset(unicodedata.normalize("NFKC", s).upper() for s in self.m.symbols)
        self.sides = frozenset(s.lower() for s in self.m.sides)
        self.max_order = float(self.m.maxOrderNotionalUsd)
        self.band = self.m.priceBandPct / 100.0
        self.stepup = self.m.stepUpAboveUsd
        self.ref = {k.upper(): float(v) for k, v in (self.m.referencePrices or {}).items()}
        self.expires = _parse_time(self.m.expiresAt)

    def verify(self, public_key: Ed25519PublicKey, now=None) -> None:
        self.m.verify(public_key, now=now)

    def live(self, as_of: dt.datetime) -> str | None:
        """None when usable, else the plain reason it is not."""
        if self.revoked:
            return "The mandate has been revoked by the account owner; no order can be placed."
        if as_of >= self.expires:
            return f"The mandate expired at {self.m.expiresAt}; no order can be placed."
        return None

    def headroom(self, notional: float, day: int) -> float:
        """Smallest remaining room after this order: min(per-order cap, daily remainder) minus its notional."""
        return min(self.max_order - notional, self.budget.cap - self.budget.used(day) - notional)

    def check(self, ticker: str, problem: str | None, side: str, qty, limit, trusted: float | None, used: float) -> tuple[list, list, float | None]:
        """The OrderGate rules 2-6 and 8 for one order. Returns (refusal reasons, hold reasons, notional at the trusted price)."""
        m = self.m
        reasons: list[str] = []
        holds: list[str] = []
        t_ok = False
        if problem:
            reasons.append(problem[0].upper() + problem[1:] + ".")
        elif ticker not in self.allowed:
            reasons.append(f"The ticker {ticker} is not on the mandate's allow-list ({', '.join(sorted(self.allowed))}).")
        else:
            t_ok = True
        if side not in ("buy", "sell"):
            reasons.append(f"The side {side!r} is not buy or sell.")
        elif side not in self.sides:
            reasons.append(f"The mandate allows {' and '.join(m.sides)} orders only, not {side}.")
        if trusted is None:
            trusted = self.ref.get(ticker)
        if qty is None or qty <= 0 or float(qty) != int(qty):
            reasons.append("The quantity must be a positive whole number of shares.")
            qty = None
        if limit is None or limit <= 0:
            reasons.append("The limit price must be a positive number.")
            limit = None
        notional = None
        if trusted is None:
            if t_ok:
                reasons.append(f"There is no trusted price for {ticker}, so the order cannot be sized and is refused.")
        elif qty is not None:
            cents = round(qty * trusted * 100)                       # integer cents, as in the receiver
            notional = cents / 100.0
            if cents > round(self.max_order * 100):
                reasons.append(f"The order is worth ${notional:,.0f} at the trusted price of ${trusted:,.2f} "
                               f"({int(qty)} shares), above the per-order cap of ${self.max_order:,.0f}.")
            if round(used * 100) + cents > round(m.maxDailyNotionalUsd * 100):
                reasons.append(f"With ${used:,.0f} already placed today this order would bring the day's total to "
                               f"${used + notional:,.0f}, above the daily cap of ${m.maxDailyNotionalUsd:,.0f}.")
        if trusted is not None and limit is not None:
            off = (limit - trusted) / trusted
            if abs(off) > self.band + 1e-12:
                reasons.append(f"The limit price ${limit:,.2f} is {abs(off) * 100:.1f}% {'above' if off > 0 else 'below'} the trusted price "
                               f"${trusted:,.2f}; the mandate allows at most {m.priceBandPct:g}%.")
        if self.stepup is not None and notional is not None and round(notional * 100) > round(self.stepup * 100):
            holds.append(f"The order is worth ${notional:,.0f}, above the ${self.stepup:,.0f} step-up threshold, so a human must approve it.")
        return reasons, holds, notional


def make_envelope(key: Ed25519PrivateKey, *, name: str, owner: str = "owner-1", purpose: str = "", symbols, sides=("buy", "sell"),
                  per_order: float, daily: float, band_pct: float, step_up: float | None = None, expires: str = FAR_FUTURE,
                  reference_prices: dict | None = None) -> Envelope:
    body = {"symbols": list(symbols), "sides": list(sides), "maxOrderNotionalUsd": float(per_order), "maxDailyNotionalUsd": float(daily),
            "priceBandPct": float(band_pct), "expiresAt": expires, "referencePrices": dict(reference_prices or {})}
    if step_up is not None:
        body["stepUpAboveUsd"] = float(step_up)
    env = Envelope(sign_mandate(body, key), name=name, owner=owner, purpose=purpose)
    env.verify(key.public_key())
    return env


def sleeve_of(symbol: str) -> str:
    return "crypto" if symbol.endswith("-USD") or symbol.endswith("USDT") else "equity"


def split_sleeves(symbols: list[str]) -> dict[str, list[str]]:
    """core / tactical / crypto. Equities: the first half of the equity list is core (large, slow), all equities are tactical."""
    eq = [s for s in symbols if sleeve_of(s) == "equity"]
    cr = [s for s in symbols if sleeve_of(s) == "crypto"]
    core = eq[: max(1, len(eq) // 2)] if eq else []
    out: dict[str, list[str]] = {}
    if core:
        out["core"] = core
    if eq:
        out["tactical"] = eq
    if cr:
        out["crypto"] = cr
    return out


DEFAULT_LIMITS = {   # per-order cap, daily cap per 100 agents, band %, step-up as a fraction of the per-order cap
    "core": (25_000.0, 800_000.0, 1.0, 0.8),
    "tactical": (40_000.0, 1_000_000.0, 1.5, 0.8),
    "crypto": (20_000.0, 400_000.0, 2.5, 0.8),
}
PURPOSES = {"core": "conservative core: large, slow names, tight price band", "tactical": "tactical: wider list, larger orders",
            "crypto": "crypto sleeve: volatile names, wider price band"}


def default_envelopes(symbols: list[str], n_agents: int, key: Ed25519PrivateKey | None = None, owner: str = "owner-1") -> "EnvelopeBook":
    """One human, up to three envelopes. Daily caps scale with the number of agents that share them (the swarm shares the budget)."""
    key = key or owner_key_from_seed(owner)
    book = EnvelopeBook(key.public_key())
    for name, syms in split_sleeves(symbols).items():
        per_order, daily100, band, su = DEFAULT_LIMITS[name]
        book.add(make_envelope(key, name=name, owner=owner, purpose=PURPOSES[name], symbols=syms, per_order=per_order,
                               daily=daily100 * max(n_agents, 1) / 100.0, band_pct=band, step_up=per_order * su))
    return book


class EnvelopeBook:
    """All envelopes the owner(s) have signed. Verifies each signature once, on add."""

    def __init__(self, public_key: Ed25519PublicKey):
        self.public_key = public_key
        self._envs: dict[str, Envelope] = {}
        self._by_name: dict[str, Envelope] = {}

    def add(self, env: Envelope) -> Envelope:
        try:
            env.verify(self.public_key)
        except MandateInvalid as e:
            raise ValueError(f"envelope {env.name!r} rejected: {e}") from None
        self._envs[env.id] = env
        self._by_name[env.name] = env
        return env

    def get(self, ident: str) -> Envelope | None:
        return self._envs.get(ident) or self._by_name.get(ident)

    def envelopes(self, owner: str | None = None) -> list[Envelope]:
        return [e for e in self._envs.values() if owner is None or e.owner == owner]

    def home_for(self, symbol: str, owner: str | None = None) -> Envelope | None:
        """The owner's default envelope for a symbol: the narrowest one that lists it (core before tactical)."""
        sym = unicodedata.normalize("NFKC", symbol).upper()
        cands = [e for e in self.envelopes(owner) if sym in e.allowed]
        return min(cands, key=lambda e: len(e.allowed)) if cands else None

    def fit(self, order: dict, prices: dict | float | None, day: int = 0, owner: str | None = None, *, include_holds: bool = False) -> list[Envelope]:
        """Envelopes that would authorize this order right now (allow; with include_holds, also those that would hold it)."""
        ticker, problem = normalise_ticker(order.get("ticker"))
        trusted = prices.get(ticker) if isinstance(prices, dict) else prices
        out = []
        as_of = _parse_time(dt.date(2026, 1, 5) + dt.timedelta(days=day))
        for e in self.envelopes(owner):
            if e.live(as_of):
                continue
            r, h, _ = e.check(ticker, problem, str(order.get("side", "")).strip().lower(), _f(order.get("quantity")), _f(order.get("limit_price")),
                              trusted, e.budget.used(day))
            if not r and (include_holds or not h):
                out.append(e)
        return out

    def tightest_fit(self, order: dict, prices: dict | float | None, day: int = 0, owner: str | None = None) -> Envelope | None:
        """Among envelopes that would authorize the order, the one with the smallest headroom (keeps looser envelopes free for orders that need them)."""
        fits = self.fit(order, prices, day, owner)
        if not fits:
            return None
        ticker, _ = normalise_ticker(order.get("ticker"))
        trusted = prices.get(ticker) if isinstance(prices, dict) else prices
        notional = round(float(order["quantity"]) * (trusted if trusted is not None else fits[0].ref.get(ticker, 0.0)), 2)
        return min(fits, key=lambda e: (e.headroom(notional, day), e.name))


def _f(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None
