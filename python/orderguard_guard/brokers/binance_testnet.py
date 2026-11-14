"""Binance Spot TESTNET broker (https://testnet.binance.vision), behind the `Broker` protocol.

Safety pins, all enforced in code and covered by tests:
  * the base URL is HARD-PINNED to https://testnet.binance.vision; any other base URL is refused at construction, and every request URL is
    re-checked immediately before it is sent (so a redirect target, a proxy rewrite or a later attribute change cannot reach another host)
  * `dry_run=True` is the default: the request is built and signed and returned REDACTED, and nothing is sent
  * credentials are read from the environment variables BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_SECRET by NAME only; their values are
    never printed, logged, returned, put in an exception message or written to a file (the signature and key header are redacted in every
    returned request)
  * `submit` works only inside `TestnetRouter.route`, i.e. after the gate/authority said `allow` (and, when a receiver is configured, after the
    L8 receiver filled the order); a direct call raises NotRouted
  * idempotency: `newClientOrderId` is the order's idempotency key; symbol, lot-size, tick-size and min-notional filters come from exchangeInfo

Testnet funds have no value. This module has never been run against the live testnet by the project's tests, which use a mocked transport only.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Callable
from urllib.parse import urlencode, urlsplit

from ..broker import Broker, Fill, OrderRouter, Reject, Result

TESTNET_BASE_URL = "https://testnet.binance.vision"
KEY_ENV = "BINANCE_TESTNET_API_KEY"
SECRET_ENV = "BINANCE_TESTNET_SECRET"
_ARMED: contextvars.ContextVar[bool] = contextvars.ContextVar("og_binance_armed", default=False)


class NotConfigured(RuntimeError):
    """Credentials or settings are missing. The message names environment variables, never values."""


class NotRouted(RuntimeError):
    """`submit` was called outside OrderRouter after an allow."""


class WrongHost(RuntimeError):
    pass


def _norm_base(url: str) -> str:
    u = urlsplit(str(url).strip())
    if u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise WrongHost("the base URL must be exactly https://testnet.binance.vision")
    return f"{u.scheme}://{(u.hostname or '').lower()}" + (f":{u.port}" if u.port else "")


def _check_url(url: str) -> None:
    u = urlsplit(url)
    if u.scheme != "https" or (u.hostname or "").lower() != "testnet.binance.vision" or u.port not in (None, 443) or u.username or u.password:
        raise WrongHost("refusing to send: the host is not testnet.binance.vision")


@dataclass
class SignedRequest:
    method: str
    url: str
    params: dict
    headers: dict
    sent: bool = False
    notes: list = field(default_factory=list)

    def __repr__(self) -> str:             # never show the signature or the key header, even in a traceback or a log line
        return f"SignedRequest({self.redacted()!r})"

    def redacted(self) -> dict:
        p = {k: ("***" if k == "signature" else v) for k, v in self.params.items()}
        h = {k: ("***" if k.lower() == "x-mbx-apikey" else v) for k, v in self.headers.items()}
        return {"method": self.method, "url": self.url, "params": p, "headers": h, "sent": self.sent, "notes": list(self.notes)}


Transport = Callable[[SignedRequest], tuple]          # -> (status_code, parsed_json)


def _httpx_transport(req: SignedRequest) -> tuple:
    import httpx
    _check_url(req.url)
    with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as c:      # no proxy or netrc from the environment
        if req.method == "GET":
            r = c.get(req.url, params=req.params, headers=req.headers)
        else:
            r = c.request(req.method, req.url, data=req.params, headers={**req.headers, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


class BinanceTestnetBroker:
    """`Broker` for Binance Spot testnet. `unit_size` maps a symbol to base-asset units per arena unit (e.g. {"BTCUSDT": 0.001})."""

    def __init__(self, *, base_url: str = TESTNET_BASE_URL, dry_run: bool = True, transport: Transport | None = None, recv_window_ms: int = 5000,
                 unit_size: dict | None = None, filters: dict | None = None, clock: Callable[[], float] = time.time, env: dict | None = None):
        if _norm_base(base_url) != TESTNET_BASE_URL:
            raise WrongHost(f"this broker is pinned to {TESTNET_BASE_URL}; it will not talk to any other host")
        self.base_url = TESTNET_BASE_URL
        self._dry_run = bool(dry_run)
        self._transport = transport or _httpx_transport
        self.recv_window_ms, self.unit_size = int(recv_window_ms), dict(unit_size or {})
        self._filters = dict(filters or {})
        self._clock = clock
        self._env = env if env is not None else os.environ
        self._seen: dict[str, Result] = {}
        self.last_request: dict | None = None

    @property
    def dry_run(self) -> bool:
        """Fixed at construction. Read-only so that nothing can flip a dry-run broker live after it has been handed around."""
        return self._dry_run

    # ---- credentials, by name only ---------------------------------------------------------------------------------------
    def _creds(self, required: bool) -> tuple[str | None, str | None]:
        key, secret = self._env.get(KEY_ENV), self._env.get(SECRET_ENV)
        if required and not (key and secret):
            raise NotConfigured(f"set the environment variables {KEY_ENV} and {SECRET_ENV} (Binance spot testnet credentials) to send orders")
        return key, secret

    # ---- filters ---------------------------------------------------------------------------------------------------------
    def load_filters(self, symbol: str) -> dict:
        """GET /api/v3/exchangeInfo?symbol=... (public data, unsigned) and keep lot size, tick size and min notional."""
        req = SignedRequest("GET", f"{self.base_url}/api/v3/exchangeInfo", {"symbol": symbol}, {})
        status, body = self._send(req)
        if status != 200 or not body.get("symbols"):
            raise NotConfigured(f"exchangeInfo for {symbol} was not available (HTTP {status})")
        f = {x["filterType"]: x for x in body["symbols"][0].get("filters", [])}
        out = {"stepSize": f.get("LOT_SIZE", {}).get("stepSize"), "minQty": f.get("LOT_SIZE", {}).get("minQty"),
               "tickSize": f.get("PRICE_FILTER", {}).get("tickSize"),
               "minNotional": (f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}).get("minNotional")}
        self._filters[symbol] = out
        return out

    @staticmethod
    def _floor(x: Decimal, step: str | None) -> Decimal:
        if not step or Decimal(step) == 0:
            return x
        s = Decimal(step)
        return (x / s).to_integral_value(rounding=ROUND_DOWN) * s

    # ---- building and signing -----------------------------------------------------------------------------------------------
    def build_order_request(self, order: dict, idempotency_key: str) -> SignedRequest:
        sym = str(order.get("symbol") or order.get("ticker")).upper()
        side = str(order["side"]).upper()
        qty = Decimal(str(order["quantity"])) * Decimal(str(self.unit_size.get(sym, 1)))
        price = Decimal(str(order.get("limit_price", order.get("limitPrice"))))
        # Binance prices per base unit; the arena's price is per arena unit, so scale it back
        price = price / Decimal(str(self.unit_size.get(sym, 1)))
        flt = self._filters.get(sym)
        notes = []
        if flt is None and not self.dry_run:
            flt = self.load_filters(sym)
        if flt:
            qty, price = self._floor(qty, flt.get("stepSize")), self._floor(price, flt.get("tickSize"))
            if flt.get("minQty") and qty < Decimal(flt["minQty"]):
                raise ValueError(f"quantity {qty} is below the symbol's minimum lot {flt['minQty']}")
            if flt.get("minNotional") and qty * price < Decimal(flt["minNotional"]):
                raise ValueError(f"order value {qty * price} is below the symbol's minimum notional {flt['minNotional']}")
        else:
            notes.append("exchangeInfo filters not loaded: quantity and price are not rounded to the symbol's lot and tick size")
        if not 1 <= len(idempotency_key) <= 36:
            idempotency_key = hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]       # newClientOrderId allows at most 36 characters
        params = {"symbol": sym, "side": side, "type": "LIMIT", "timeInForce": "GTC", "quantity": format(qty.normalize(), "f"),
                  "price": format(price.normalize(), "f"), "newClientOrderId": idempotency_key, "recvWindow": self.recv_window_ms,
                  "timestamp": int(self._clock() * 1000)}
        key, secret = self._creds(required=not self.dry_run)
        if secret:
            params["signature"] = sign(secret, urlencode(params))
        else:
            params["signature"] = "unsigned: BINANCE_TESTNET_SECRET is not set"
            notes.append("not signed: credentials are not set (dry run)")
        url = f"{self.base_url}/api/v3/order"
        _check_url(url)
        return SignedRequest("POST", url, params, {"X-MBX-APIKEY": key or "unset"}, False, notes)

    def _send(self, req: SignedRequest) -> tuple:
        _check_url(req.url)                      # re-checked at the last moment, whatever happened since construction
        if self.dry_run and req.method != "GET":
            raise NotConfigured("dry_run is on: nothing is sent")
        req.sent = True
        return self._transport(req)

    # ---- Broker protocol -----------------------------------------------------------------------------------------------------
    def submit(self, order: dict, idempotency_key: str) -> Result:
        if not _ARMED.get():
            raise NotRouted("orders reach this broker only through TestnetRouter.route, after an allow")
        if idempotency_key in self._seen:
            r = self._seen[idempotency_key]
            return type(r)(**{**r.__dict__, "replay": True})
        try:
            req = self.build_order_request(order, idempotency_key)
        except (ValueError, NotConfigured) as e:
            return Reject(f"not sent: {e}", idempotency_key)
        if self.dry_run:
            self.last_request = req.redacted()
            res = Reject("dry run: the request was built and signed but not sent", idempotency_key)
            self._seen[idempotency_key] = res
            return res
        try:
            status, body = self._send(req)
        except WrongHost:
            raise
        except Exception as e:                       # noqa: BLE001 - transport failure: the order may or may not have reached the exchange
            self.last_request = req.redacted()
            return Reject(f"not confirmed: the exchange did not answer ({type(e).__name__}). The order may exist. Retry with the same key "
                          "(the key is the exchange's client order id, so it is placed at most once) or check the testnet account.",
                          idempotency_key, transient=True)
        self.last_request = req.redacted()
        if not isinstance(body, dict):
            body = {}
        if status == 200 and body.get("orderId") is not None:
            ex = body.get("fills") or []
            avg = (sum(float(x["price"]) * float(x["qty"]) for x in ex) / sum(float(x["qty"]) for x in ex)) if ex else float(order.get("limit_price", 0))
            res = Fill(str(body["orderId"]), str(order.get("symbol") or order.get("ticker")), str(order["side"]), int(order["quantity"]), avg, idempotency_key)
        else:
            retryable = status >= 500 or status == 429 or body.get("code") in (-1021, -1003, -1001)   # server error, rate limit, clock window, busy
            res = Reject(f"exchange rejected the order (HTTP {status}, code {body.get('code')})" + (". Not final: retry later with the same key." if retryable else ""),
                         idempotency_key, transient=retryable)
            if retryable:
                return res                            # not remembered, so the same key can be tried again
        self._seen[idempotency_key] = res
        return res

    def cancel(self, order_id: str) -> bool:
        return False                               # not implemented: a cancel needs the symbol; use the exchange's own tools

    def positions(self) -> dict[str, int]:
        return {}

    def cash(self) -> float:
        return 0.0


class TestnetRouter(OrderRouter):
    """OrderRouter whose broker is armed only for the duration of an allowed route. With `receiver`, the L8 receiver must fill first."""
    __test__ = False                               # not a pytest class

    def __init__(self, broker: BinanceTestnetBroker, receiver=None):
        super().__init__(broker)
        self.receiver = receiver

    def route(self, order: dict, decision: dict, idempotency_key: str) -> Result:
        if isinstance(decision, dict) and decision.get("decision") == "allow" and self.receiver is not None:
            from ..receiver_client import ReceiverError
            try:
                r = self.receiver.propose(order["symbol"], order["side"], order["quantity"], float(order.get("limit_price", order.get("limitPrice"))),
                                          client_order_id=idempotency_key)
            except ReceiverError as e:
                return Reject(f"receiver unavailable, nothing was sent: {e}", idempotency_key)
            if r.get("decision") != "filled":
                return Reject(f"the L8 receiver did not fill it ({r.get('decision')}): {r.get('reason')}", idempotency_key, held=(r.get("decision") == "held"))
        token = _ARMED.set(True)
        try:
            return super().route(order, decision, idempotency_key)
        finally:
            _ARMED.reset(token)
