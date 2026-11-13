"""Adapter skeleton for the simulated trading environment of Futu OpenAPI (TrdEnv.SIMULATE).

This project is not affiliated with, endorsed by or supported by Futu. The adapter is a skeleton: it has never been run against Futu here.

It is closed unless ALL of these hold, and otherwise raises NotConfigured with a plain message:
  * the `futu` Python SDK (futu-api) is installed
  * a local OpenD gateway answers on 127.0.0.1 (default port 11111)
  * the trading environment is SIMULATE: any other value is refused at construction, and the real-money constant is never referenced

Like every broker it must be reached through OrderRouter after an `allow` (and the L8 receiver where configured).
"""
from __future__ import annotations

import socket

from ..broker import Broker, Fill, Reject, Result
from .binance_testnet import NotConfigured, NotRouted, _ARMED

SIMULATE = "SIMULATE"


class FutuSimBroker:
    def __init__(self, *, host: str = "127.0.0.1", port: int = 11111, market: str = "US", trd_env: str = SIMULATE, connect_timeout: float = 1.0):
        if trd_env != SIMULATE:
            raise NotConfigured("only the simulated trading environment (SIMULATE) is allowed")
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise NotConfigured("OpenD must run on this machine (127.0.0.1)")
        self.host, self.port, self.market, self.connect_timeout = host, int(port), market, connect_timeout
        self._ctx = None

    def _ready(self):
        try:
            import futu  # type: ignore
        except ImportError:
            raise NotConfigured("the futu SDK is not installed (pip install futu-api) and a local OpenD gateway is required") from None
        try:
            socket.create_connection((self.host, self.port), timeout=self.connect_timeout).close()
        except OSError:
            raise NotConfigured(f"no OpenD gateway answered on {self.host}:{self.port}") from None
        if self._ctx is None:
            self._ctx = futu.OpenSecTradeContext(host=self.host, port=self.port)
        return futu

    def submit(self, order: dict, idempotency_key: str) -> Result:
        if not _ARMED.get():
            raise NotRouted("orders reach this broker only through an OrderRouter after an allow")
        futu = self._ready()
        code = f"{self.market}.{order.get('symbol') or order.get('ticker')}"
        side = futu.TrdSide.BUY if order["side"] == "buy" else futu.TrdSide.SELL
        ret, data = self._ctx.place_order(price=float(order["limit_price"]), qty=int(order["quantity"]), code=code, trd_side=side,
                                          trd_env=futu.TrdEnv.SIMULATE, remark=idempotency_key[:64])
        if ret != futu.RET_OK:
            return Reject("the simulated environment rejected the order", idempotency_key)
        return Fill(str(data["order_id"][0]), str(order.get("symbol") or order.get("ticker")), order["side"], int(order["quantity"]), float(order["limit_price"]), idempotency_key)

    def cancel(self, order_id: str) -> bool:
        return False

    def positions(self) -> dict[str, int]:
        return {}

    def cash(self) -> float:
        return 0.0
