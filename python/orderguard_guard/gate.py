"""L5 order gate: code only, using trusted data the agent cannot touch.

  Mandate        the human-signed limits (CONTRACT §5.1 JSON shape), Ed25519 over canonical JSON, with expiry and revocation
  OrderGate      `evaluate(order, state)` -> {"decision": allow|refuse|hold, "reasons": [plain sentences], "checks": {...}}

Rules, in the order they are reported: mandate valid; ticker normalised and on the allow-list; side allowed; quantity x
TRUSTED price within the per-order cap; running daily total; limit within the band of the TRUSTED price; every cited
figure checked by L6 (`orderguard_verify.api.check_figures`): a contradicted, stale or not-public-yet figure refuses; step-up
hold above a threshold.

Why the TRUSTED price: in the prototype 8 of 11 agents that believed a fake 10-for-1 split ordered about 440 shares at $22.30.
Valued at its own limit that is about $9,800 and passes a $10,000 cap; valued at the trusted $222.70 it is about $98,000 and
is refused (lab/legacy/attack-lab-2026-11-06/README.md, feed case F2). The order's own price is never used for sizing.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path
from typing import Callable, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

from .market import TrustedMarket, UnknownTicker
from .normalise import fold_confusables, non_latin_letters

FigureChecker = Callable[[str, dt.date, list], list]

BLOCKING_FIGURE_STATUSES = ("contradicted", "stale", "not_public_yet")


# ---- keys and canonical JSON ---------------------------------------------------------------------------------------

def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def private_key_to_b64(key: Ed25519PrivateKey) -> str:
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return base64.b64encode(raw).decode()


def public_key_to_b64(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def private_key_from_b64(s: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(s))


def public_key_from_b64(s: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(s))


def canonical_json(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _parse_time(s) -> dt.datetime:
    if isinstance(s, dt.datetime):
        return s if s.tzinfo else s.replace(tzinfo=dt.timezone.utc)
    if isinstance(s, dt.date):
        return dt.datetime(s.year, s.month, s.day, tzinfo=dt.timezone.utc)
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


class MandateInvalid(Exception):
    """The mandate cannot be relied on. The message is a plain sentence."""


# ---- the mandate ----------------------------------------------------------------------------------------------------

@dataclass
class Mandate:
    """Fields use the CONTRACT §5.1 JSON names. `stepUpAboveUsd` (optional) holds orders above it for a human."""
    symbols: list[str]
    sides: list[str]
    maxOrderNotionalUsd: float
    maxDailyNotionalUsd: float
    priceBandPct: float
    expiresAt: str
    referencePrices: dict = field(default_factory=dict)
    stepUpAboveUsd: float | None = None
    # Optional portfolio-safety limits. Absent (None) means no limit and the field is never serialised, so mandates signed before these
    # fields existed keep their bytes, signatures and ids.
    maxSymbolDailyNotionalUsd: float | None = None     # one symbol's notional per day (allowed and held orders), the concentration control
    maxPositionUsd: float | None = None                # absolute net position in one symbol after the order, at the trusted price
    maxOrdersPerDay: int | None = None                 # non-denied orders per day, a backstop against a runaway agent
    signature: str | None = None
    signerPublicKey: str | None = None

    # -- construction --------------------------------------------------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict) -> "Mandate":
        known = {f for f in cls.__dataclass_fields__}
        required = [f.name for f in fields(cls) if f.default is MISSING and f.default_factory is MISSING]
        missing = [f for f in required if d.get(f) is None]
        if missing:
            raise MandateInvalid(f"the mandate is missing required fields: {', '.join(missing)}")
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def load(cls, path) -> "Mandate":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def to_dict(self, with_signature: bool = True) -> dict:
        d = {k: v for k, v in asdict(self).items() if v is not None}
        if not with_signature:
            d.pop("signature", None)
            d.pop("signerPublicKey", None)
        return d

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1))

    # -- identity, verification ----------------------------------------------------------------------------------
    @property
    def id(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict(with_signature=False))).hexdigest()[:16]

    def verify(self, public_key: Ed25519PublicKey, *, now=None, revoked: Iterable[str] = ()) -> None:
        """Raise MandateInvalid unless the signature matches, the mandate has not expired and it is not revoked."""
        if not self.signature:
            raise MandateInvalid("the mandate is not signed")
        try:
            public_key.verify(base64.b64decode(self.signature), canonical_json(self.to_dict(with_signature=False)))
        except Exception:       # a bad signature of any shape (not base64, wrong length, not a string) is the same answer
            raise MandateInvalid("the mandate's signature does not match its contents: it was changed after the human signed it") from None
        self.check_live(now=now, revoked=revoked)

    def validate(self) -> None:
        """Raise MandateInvalid unless every limit is a finite, sensible number and the lists hold strings. A NaN cap would compare False
        against everything and wave every order through, so a mandate like that is refused outright."""
        def num(name: str, v, *, positive: bool = True, optional: bool = False) -> None:
            if v is None and optional:
                return
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or (positive and v == 0):
                raise MandateInvalid(f"the mandate's {name} must be a finite {'positive' if positive else 'non-negative'} number, not {v!r}")
        for name in ("symbols", "sides"):
            v = getattr(self, name)
            if not isinstance(v, (list, tuple)) or not v or not all(isinstance(x, str) and x.strip() for x in v):
                raise MandateInvalid(f"the mandate's {name} must be a non-empty list of strings")
        num("maxOrderNotionalUsd", self.maxOrderNotionalUsd)
        num("maxDailyNotionalUsd", self.maxDailyNotionalUsd)
        num("priceBandPct", self.priceBandPct, positive=False)
        num("stepUpAboveUsd", self.stepUpAboveUsd, optional=True)
        num("maxSymbolDailyNotionalUsd", self.maxSymbolDailyNotionalUsd, optional=True)
        num("maxPositionUsd", self.maxPositionUsd, optional=True)
        n = self.maxOrdersPerDay
        if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n < 1 or n > 10**9):
            raise MandateInvalid(f"the mandate's maxOrdersPerDay must be a positive whole number, not {n!r}")
        if not isinstance(self.referencePrices, dict) or not all(isinstance(k, str) for k in self.referencePrices):
            raise MandateInvalid("the mandate's referencePrices must be a mapping of ticker to price")
        try:
            _parse_time(self.expiresAt)
        except (ValueError, TypeError, OverflowError):
            raise MandateInvalid(f"the mandate's expiry {self.expiresAt!r} is not a valid date and time") from None

    def check_coherent(self) -> None:
        """Raise MandateInvalid for limits that contradict each other (used before signing a template; the gate itself only needs validate())."""
        self.validate()
        if self.maxOrderNotionalUsd > self.maxDailyNotionalUsd:
            raise MandateInvalid("the mandate's per-order cap exceeds its daily cap")
        if self.stepUpAboveUsd is not None and self.stepUpAboveUsd > self.maxOrderNotionalUsd:
            raise MandateInvalid("the mandate's step-up threshold is above its per-order cap, so it would never trigger")
        if self.maxSymbolDailyNotionalUsd is not None:
            if self.maxSymbolDailyNotionalUsd > self.maxDailyNotionalUsd:
                raise MandateInvalid("the mandate's per-symbol daily cap exceeds its daily cap")
            if self.maxSymbolDailyNotionalUsd < self.maxOrderNotionalUsd:
                raise MandateInvalid("the mandate's per-symbol daily cap is below its per-order cap")
        if self.maxPositionUsd is not None and self.maxPositionUsd < self.maxOrderNotionalUsd:
            raise MandateInvalid("the mandate's position cap is below its per-order cap")

    def check_live(self, *, now=None, revoked: Iterable[str] = ()) -> None:
        if self.id in set(revoked):
            raise MandateInvalid("the mandate has been revoked by the account owner")
        try:
            t = _parse_time(now) if now is not None else dt.datetime.now(dt.timezone.utc)
        except (ValueError, TypeError, OverflowError):
            raise MandateInvalid(f"the decision time {now!r} is not a valid date and time, so expiry cannot be checked") from None
        try:
            expires = _parse_time(self.expiresAt)
        except (ValueError, TypeError, OverflowError):
            raise MandateInvalid(f"the mandate's expiry {self.expiresAt!r} is not a valid date and time") from None
        if t >= expires:
            raise MandateInvalid(f"the mandate expired at {self.expiresAt}")


def sign_mandate(mandate: dict | Mandate, private_key: Ed25519PrivateKey) -> dict:
    """Return the canonical mandate body with its Ed25519 signature and the signer's public key."""
    if isinstance(mandate, Mandate):
        mandate = mandate.to_dict(with_signature=False)
    # Serialization omits nulls. Apply defaults to that shape so verify() rebuilds the same body.
    body = Mandate.from_dict({k: v for k, v in mandate.items() if v is not None}).to_dict(with_signature=False)
    signature = private_key.sign(canonical_json(body))
    return {
        **body,
        "signerPublicKey": public_key_to_b64(private_key.public_key()),
        "signature": base64.b64encode(signature).decode(),
    }


# ---- ticker normalisation -------------------------------------------------------------------------------------------

def normalise_ticker(raw) -> tuple[str, str | None]:
    """Return (ticker, problem). NFKC, strip, upper-case. A ticker still holding non-Latin letters (a Cyrillic А) is a problem."""
    if raw is not None and not isinstance(raw, str):
        return str(raw), f"the ticker {str(raw)!r} is not text"
    s = unicodedata.normalize("NFKC", raw or "").strip()
    odd = non_latin_letters(s)
    if odd:
        s = s.upper()
        return s, f"the ticker {s!r} contains non-Latin letters and looks like {fold_confusables(s)!r}; an order for a look-alike symbol is refused"
    if not s.isascii():     # dotless i, sharp s, Kelvin-style forms: upper-casing would turn them into other letters
        return s.upper(), f"the ticker {s!r} contains non-ASCII characters; an order for a look-alike symbol is refused"
    s = s.upper()
    if not s or not all(c.isalnum() or c in ".-" for c in s):
        return s, f"the ticker {s!r} is not a valid symbol"
    return s, None


_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def _num(x) -> float | None:
    """A finite number from an int, a float or a plain ASCII numeric string ("1,000", "$12.50"). Booleans, NaN, infinity, other digit
    scripts, underscores and anything else are None."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        try:
            v = float(x)
        except OverflowError:
            return None
    elif isinstance(x, str):
        t = x.strip().replace(",", "").replace("$", "")
        if not t.isascii() or not _NUMBER.fullmatch(t):
            return None
        try:
            v = float(t)
        except (ValueError, OverflowError):
            return None
    else:
        return None
    return v if math.isfinite(v) else None


def portfolio_reasons(m: Mandate, ticker: str, side: str, qty, trusted, state: dict) -> list[str]:
    """The optional portfolio limits (maxOrdersPerDay, maxSymbolDailyNotionalUsd, maxPositionUsd) as plain-sentence refusal reasons.

    Shared by OrderGate and the arena's Envelope.check so the two cannot drift. Fails closed: a limit that is set and whose state is missing
    or invalid is a refusal. `qty` and `trusted` are None when the order could not be sized (other reasons already refuse it).
    state: orders_today int; symbol_daily_usd {SYM: float} (a symbol not listed has placed nothing); positions {SYM: net filled qty, all days}
    (a symbol not listed is flat); optional held_qty {SYM: {"buy": q, "sell": q}} for held orders, counted in the direction that grows exposure.
    """
    reasons: list[str] = []
    if m.maxOrdersPerDay is not None:
        n = state.get("orders_today")
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            reasons.append(f"The count of orders placed today ({n!r}) is missing or not a whole non-negative number, so the cap of "
                           f"{m.maxOrdersPerDay} orders per day cannot be enforced and the order is refused.")
        elif n + 1 > m.maxOrdersPerDay:
            reasons.append(f"{n} orders have already been placed today; one more would pass the cap of {m.maxOrdersPerDay} orders per day.")
    if qty is None or trusted is None:
        return reasons

    def table(name: str):
        t = state.get(name)
        if not isinstance(t, dict):
            return None
        return {str(k).strip().upper(): v for k, v in t.items()}

    cents = round(qty * trusted * 100)
    if m.maxSymbolDailyNotionalUsd is not None:
        t = table("symbol_daily_usd")
        v = None if t is None else _num(t.get(ticker, 0.0))
        if v is None or v < 0:
            reasons.append(f"The day's running total for {ticker} is missing or not a finite non-negative number, so the per-symbol daily cap of "
                           f"${m.maxSymbolDailyNotionalUsd:,.0f} cannot be enforced and the order is refused.")
        elif round(v * 100) + cents > round(m.maxSymbolDailyNotionalUsd * 100):
            reasons.append(f"With ${v:,.0f} already placed in {ticker} today this order would bring that symbol's total to "
                           f"${v + cents / 100:,.0f}, above the per-symbol daily cap of ${m.maxSymbolDailyNotionalUsd:,.0f}.")
    if m.maxPositionUsd is not None and side in ("buy", "sell"):
        t = table("positions")
        net = None if t is None else _num(t.get(ticker, 0.0))
        hb = hs = 0.0
        held = state.get("held_qty")
        if held is not None:
            h = held.get(ticker) if isinstance(held, dict) else None
            if h is None and isinstance(held, dict):
                h = {str(k).strip().upper(): v for k, v in held.items()}.get(ticker, {})
            hb = _num(h.get("buy", 0)) if isinstance(h, dict) else None
            hs = _num(h.get("sell", 0)) if isinstance(h, dict) else None
            if hb is None or hs is None or hb < 0 or hs < 0:
                net = None
        if net is None:
            reasons.append(f"The net position in {ticker} is missing or invalid, so the position cap of ${m.maxPositionUsd:,.0f} cannot be enforced and the order is refused.")
        else:
            s = qty if side == "buy" else -qty
            exposure = max(abs(net + hb + s), abs(net - hs + s))      # held orders counted whichever way grows the exposure
            after = round(exposure * trusted * 100)
            if after > round(m.maxPositionUsd * 100):
                reasons.append(f"After this order the position in {ticker} could reach {exposure:,.0f} shares, ${after / 100:,.0f} at the trusted price of "
                               f"${trusted:,.2f}, above the position cap of ${m.maxPositionUsd:,.0f}.")
    return reasons


# ---- the gate -------------------------------------------------------------------------------------------------------

class OrderGate:
    """`OrderGate(mandate, market, figure_checker).evaluate(order, state)`.

    order = {"ticker", "side", "quantity", "limit_price", "key_figures": [{metric, fiscal_year, value, unit?}], ...}
    state = {"daily_total_usd": float, optional portfolio state (see portfolio_reasons): "symbol_daily_usd", "positions", "held_qty", "orders_today", "as_of": date|str (decision date; also the clock for expiry), "revoked": [ids]}
    """

    def __init__(self, mandate: Mandate | dict, market: TrustedMarket, figure_checker: FigureChecker | None = None, *,
                 public_key: Ed25519PublicKey | None = None, require_figures: bool = False, revoked: Iterable[str] = ()):
        self.mandate = mandate if isinstance(mandate, Mandate) else Mandate.from_dict(mandate)
        self.market = market
        self.figure_checker = figure_checker
        self.public_key = public_key
        self.require_figures = require_figures
        self.revoked = set(revoked)

    def revoke(self) -> None:
        self.revoked.add(self.mandate.id)

    def evaluate(self, order: dict, state: dict | None = None) -> dict:
        """Never raises and never allows on a fault: anything unreadable or unexpected is a refusal with a reason a person can act on."""
        def refuse(reason: str, **checks) -> dict:
            return {"decision": "refuse", "reasons": [reason], "checks": checks}
        if state is None:
            state = {}
        if not isinstance(state, dict):
            return refuse("The decision state (daily total, date, revocations) is not a mapping, so the order cannot be checked; fix the caller and place the order again.", state="invalid")
        if not isinstance(order, dict):
            return refuse("The order is not a JSON object with ticker, side, quantity and limit_price, so it cannot be checked.", order="invalid")
        placed = state.get("daily_total_usd")
        if placed is not None and (_num(placed) is None or _num(placed) < 0):
            return refuse(f"The day's running total {placed!r} is not a finite non-negative number, so the daily cap cannot be enforced and the order is refused.", daily_total="invalid")
        revoked = state.get("revoked")
        if revoked is not None and (isinstance(revoked, (str, bytes)) or not hasattr(revoked, "__iter__")):
            return refuse("The list of revoked mandates is not a list, so revocation cannot be checked and the order is refused.", revoked="invalid")
        try:
            self.mandate.validate()
        except MandateInvalid as e:
            return refuse(str(e)[0].upper() + str(e)[1:] + "; no order can be placed.", mandate="invalid")
        try:
            return self._evaluate(order, state)
        except MandateInvalid as e:
            return refuse(str(e)[0].upper() + str(e)[1:] + "; no order can be placed.", mandate="invalid")
        except Exception as e:      # noqa: BLE001  fail closed
            return refuse(f"The gate could not evaluate this order safely ({type(e).__name__}), so it is refused; check the order and the mandate and try again.", error=type(e).__name__)

    def _evaluate(self, order: dict, state: dict) -> dict:
        m = self.mandate
        reasons: list[str] = []
        holds: list[str] = []
        checks: dict = {}
        as_of = state.get("as_of")
        now = state.get("now") or as_of
        try:
            decision_date = _parse_time(as_of).date() if as_of else dt.date.today()
        except (ValueError, TypeError, OverflowError):
            return {"decision": "refuse", "reasons": [f"The decision date {as_of!r} is not a valid date, so the order cannot be checked."], "checks": {"as_of": "invalid"}}

        # 0. the mandate itself
        try:
            if self.public_key is not None:
                m.verify(self.public_key, now=now, revoked=self.revoked | set(state.get("revoked") or ()))
            else:
                m.check_live(now=now, revoked=self.revoked | set(state.get("revoked") or ()))
            checks["mandate"] = "ok"
        except MandateInvalid as e:
            checks["mandate"] = "invalid"
            return {"decision": "refuse", "reasons": [str(e)[0].upper() + str(e)[1:] + "; no order can be placed."], "checks": checks}

        # 1. only buy/sell orders exist: money movement is not an order
        kind = str(order.get("type") or order.get("action") or "order").lower()
        if kind in ("transfer", "withdraw", "withdrawal", "wire", "transfer_funds") or "destination_account" in order:
            return {"decision": "refuse", "reasons": ["Moving money out of the account is not something the mandate allows."],
                    "checks": {**checks, "kind": "money_movement"}}

        # 2. ticker
        ticker, problem = normalise_ticker(order.get("ticker"))
        checks["ticker"] = {"given": str(order.get("ticker")), "normalised": ticker}
        allowed = {unicodedata.normalize("NFKC", s).upper() for s in m.symbols}
        if problem:
            reasons.append(problem[0].upper() + problem[1:] + ".")
            checks["ticker"]["ok"] = False
        elif ticker not in allowed:
            reasons.append(f"The ticker {ticker} is not on the mandate's allow-list ({', '.join(sorted(allowed))}).")
            checks["ticker"]["ok"] = False
        else:
            checks["ticker"]["ok"] = True

        # 3. side
        side = str(order.get("side", "")).strip().lower()
        checks["side"] = {"given": side, "ok": side in [s.lower() for s in m.sides]}
        if side not in ("buy", "sell"):
            reasons.append(f"The side {side!r} is not buy or sell.")
            checks["side"]["ok"] = False
        elif not checks["side"]["ok"]:
            reasons.append(f"The mandate allows {' and '.join(m.sides)} orders only, not {side}.")

        # 4. quantity and notional at the TRUSTED price
        qty, limit = _num(order.get("quantity")), _num(order.get("limit_price"))
        trusted = None
        if checks["ticker"]["ok"] or not problem:
            try:
                q = self.market.quote(ticker)
                trusted = _num(q.get("price")) if isinstance(q, dict) else None
            except (UnknownTicker, KeyError):
                trusted = None
        if trusted is None:
            trusted = _num((m.referencePrices or {}).get(ticker))
            if trusted is not None:
                checks["price_source"] = "mandate reference price"
        else:
            checks["price_source"] = "trusted market quote"
        checks["trusted_price"] = trusted
        if qty is None or qty <= 0 or float(qty) != int(qty):
            reasons.append("The quantity must be a positive whole number of shares.")
            qty = None
        if limit is None or limit <= 0:
            reasons.append("The limit price must be a positive number.")
            limit = None
        notional = None
        if trusted is None:
            if checks["ticker"].get("ok"):
                reasons.append(f"There is no trusted price for {ticker}, so the order cannot be sized and is refused.")
        elif qty is not None:
            notional = round(qty * trusted, 2)
            checks["notional_usd"] = notional
            checks["limit_notional_usd"] = round(qty * limit, 2) if limit else None
            if notional > m.maxOrderNotionalUsd:
                reasons.append(f"The order is worth ${notional:,.0f} at the trusted price of ${trusted:,.2f} "
                               f"({int(qty)} shares), above the per-order cap of ${m.maxOrderNotionalUsd:,.0f}.")
            # 5. running daily total
            placed = _num(state.get("daily_total_usd")) or 0.0
            checks["daily_total_after_usd"] = round(placed + notional, 2)
            if placed + notional > m.maxDailyNotionalUsd:
                reasons.append(f"With ${placed:,.0f} already placed today this order would bring the day's total to "
                               f"${placed + notional:,.0f}, above the daily cap of ${m.maxDailyNotionalUsd:,.0f}.")

        # 5b. optional portfolio limits (fail closed when their state is missing)
        reasons.extend(portfolio_reasons(m, ticker, side, qty, trusted, state))

        # 6. limit price within the band of the TRUSTED price
        if trusted is not None and limit is not None:
            band = m.priceBandPct / 100.0
            off = (limit - trusted) / trusted
            checks["limit_vs_trusted_pct"] = round(off * 100, 2)
            if abs(off) > band + 1e-12:
                reasons.append(f"The limit price ${limit:,.2f} is {abs(off) * 100:.1f}% {'above' if off > 0 else 'below'} the trusted price "
                               f"${trusted:,.2f}; the mandate allows at most {m.priceBandPct:g}%.")

        # 7. cited figures (L6)
        figs = order.get("key_figures") or []
        checks["figures"] = []
        if not figs:
            if self.require_figures:
                reasons.append("The order cites no reported financial figures, and the mandate requires every order to cite the figures it relies on. "
                               "To fix it, add at least one figure from the company's annual filing to key_figures "
                               "(metric, fiscal_year, value, unit; e.g. revenue for the latest fiscal year in USD millions) and place the order again.")
        elif self.figure_checker is None:
            if self.require_figures:
                holds.append("The cited figures could not be checked because no figure checker is configured.")
        else:
            try:
                if not isinstance(figs, list):
                    raise TypeError("key_figures is not a list")
                results = self.figure_checker(ticker, decision_date, list(figs))
                if not isinstance(results, list) or len(results) != len(figs) or not all(isinstance(r, dict) for r in results):
                    raise ValueError("the checker did not return one result per figure")
            except Exception as e:      # fail closed
                results = []
                reasons.append(f"The cited figures could not be checked ({type(e).__name__}: {str(e)[:120]}), so the order is refused. "
                               "Check key_figures (a list of metric, fiscal_year, value, unit) and the figure source, then place the order again.")
            for r in results:
                st = r.get("status")
                f = r.get("figure") if isinstance(r.get("figure"), dict) else {}
                label = f"{f.get('metric')} FY{f.get('fiscal_year')} = {f.get('value')} {f.get('unit', '')}".strip()
                checks["figures"].append({"figure": f, "status": st, "truth": r.get("truth")})
                why = (r.get("reason") or "").strip().rstrip(".")
                if st in BLOCKING_FIGURE_STATUSES:
                    word = {"contradicted": "contradicts the filings", "stale": "is out of date", "not_public_yet": "was not public yet on the decision date"}[st]
                    reasons.append(f"The cited figure {label} {word}" + (f": {why}." if why else "."))
                elif st == "unverifiable" and state.get("l7_confirmed"):
                    checks["figures"][-1]["note"] = "not required: the order carries out a standing rule that L7 confirmed"
                elif st == "unverifiable":
                    holds.append(f"The cited figure {label} could not be verified" + (f": {why}." if why else "."))
                elif st != "confirmed":
                    reasons.append(f"The cited figure {label} came back with the unrecognised status {st!r}, so it is not treated as confirmed.")

        # 8. step-up hold
        if m.stepUpAboveUsd is not None and notional is not None and notional > m.stepUpAboveUsd:
            holds.append(f"The order is worth ${notional:,.0f}, above the ${m.stepUpAboveUsd:,.0f} step-up threshold, so a human must approve it.")

        if reasons:
            return {"decision": "refuse", "reasons": reasons + holds, "checks": checks}
        if holds:
            return {"decision": "hold", "reasons": holds, "checks": checks}
        return {"decision": "allow", "reasons": [], "checks": checks}


# ---- figure checker adapters ----------------------------------------------------------------------------------------

def verify_api_checker() -> FigureChecker | None:
    """The L6 adapter: orderguard_verify.api.check_figures when it exists, else None."""
    try:
        from orderguard_verify.api import check_figures      # type: ignore
        return check_figures
    except Exception:
        return None


class FakeFigureChecker:
    """Test double / offline fallback for L6. truth = {(metric, fiscal_year): value in USD millions (or USD/share)}.

    Reproduces the L6 statuses: a figure within 1% is confirmed, otherwise contradicted; `not_public_yet` = {(metric, year)} and
    `stale` = {(metric, year)} force those statuses; anything unknown is unverifiable.
    """

    def __init__(self, truth: dict, not_public_yet: Iterable = (), stale: Iterable = ()):
        self.truth, self.npy, self.stale = dict(truth), set(not_public_yet), set(stale)
        self.calls: list[tuple] = []

    def __call__(self, ticker: str, as_of: dt.date, figures: list[dict]) -> list[dict]:
        self.calls.append((ticker, as_of, figures))
        out = []
        for f in figures:
            key = (f.get("metric"), int(_num(f.get("fiscal_year")) or 0))
            v = _num(f.get("value"))
            unit = f.get("unit", "")
            if v is not None and unit == "USD billions":
                v *= 1000
            elif v is not None and unit == "" and f.get("metric") in ("revenue", "net_income") and 0 < v < 5000:
                v *= 1000                       # an agent that wrote billions without a unit
            tv = self.truth.get(key)
            if key in self.npy:
                st, reason = "not_public_yet", "this figure was first published after the decision date"
            elif key in self.stale:
                st, reason = "stale", "a later filing superseded this figure"
            elif tv is None or v is None:
                st, reason = "unverifiable", "no filing figure is on record"
            elif abs(v - tv) <= 0.01 * abs(tv):
                st, reason = "confirmed", "matches the filing"
            else:
                st, reason = "contradicted", f"the filing reports {tv:g}"
            out.append({"figure": f, "status": st, "truth": tv, "unit": unit, "source": None, "reason": reason})
        return out


APPLE_FY2024_TRUTH = {("revenue", 2024): 391035.0, ("net_income", 2024): 93736.0, ("eps_diluted", 2024): 6.08,
                      ("revenue", 2023): 383285.0, ("net_income", 2023): 96995.0, ("eps_diluted", 2023): 6.13,
                      ("operating_income", 2024): 123216.0}


def default_figure_checker() -> FigureChecker:
    """orderguard_verify when available; otherwise the Apple FY2024 table the prototype used (SEC XBRL, USD millions)."""
    return verify_api_checker() or FakeFigureChecker(APPLE_FY2024_TRUTH)
