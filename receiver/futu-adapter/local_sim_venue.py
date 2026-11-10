"""Deterministic local-only venue implementing the adapter gateway contract.

This is a fault-injection fixture, not a broker simulator or market model. It
uses synthetic prices, an in-memory order list, and explicitly injected modes.
"""

from __future__ import annotations

import time
from typing import Any


class LocalSimVenue:
    def __init__(self, mode: str = "fill", *, latency_ms: float = 0,
                 account_id: str = "1", market: str = "HK") -> None:
        if market not in {"HK", "US"}:
            raise ValueError("LocalSimVenue market must be HK or US")
        self.mode = mode
        self.latency_ms = max(0.0, float(latency_ms))
        self.account_id = account_id
        self.market = market
        self.orders: list[dict[str, Any]] = []
        self.place_calls: list[dict[str, Any]] = []
        self.positions: dict[str, int] = {}
        self.cash_by_market = {"HK": 500_000.0, "US": 50_000.0}
        self.opened = True
        self.down = False

    def get_accounts(self) -> list[dict[str, Any]]:
        if self.down:
            raise TimeoutError("local venue injected connection loss")
        return [{"acc_id": self.account_id, "trd_env": "SIMULATE",
                 "sim_acc_type": "STOCK" if self.market == "HK" else "STOCK_AND_OPTION",
                 "acc_status": "ACTIVE"}]

    def get_positions(self, *, account_id: str, market: str, trd_env: str) -> list[dict[str, Any]]:
        if self.down:
            raise TimeoutError("local venue injected connection loss")
        if account_id != self.account_id or market != self.market or trd_env != "SIMULATE":
            raise ValueError("local venue account, market, and environment must match its configured simulator")
        return [{"code": code, "qty": quantity, "position_side": "LONG"}
                for code, quantity in sorted(self.positions.items()) if quantity]

    def find_orders(self, *, code: str, account_id: str, start: str, end: str,
                    trd_env: str, remark: str | None = None) -> list[dict[str, Any]]:
        if self.down:
            raise TimeoutError("local venue injected connection loss")
        return [row for row in self.orders
                if row["code"] == code and row["trd_env"] == trd_env
                and row["acc_id"] == account_id
                and (not start or row["create_time"][:10] >= start[:10])
                and (not end or row["create_time"][:10] <= end[:10])
                and (remark is None or row["remark"] == remark)]

    def place_order(self, **kwargs: Any) -> dict[str, Any]:
        if self.down:
            raise TimeoutError("local venue injected connection loss")
        code = str(kwargs.get("code") or "")
        requested_market = "HK" if code.startswith("HK.") else "US" if code else ""
        if (kwargs.get("account_id") != self.account_id or kwargs.get("trd_env") != "SIMULATE"
                or requested_market != self.market):
            raise ValueError("local venue refuses a different account, market, or trading environment")
        self.place_calls.append(dict(kwargs))
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000.0)
        if self.mode in {"reject", "reject_funds", "reject_lot", "reject_tick"}:
            return {"ret_ok": False}

        quantity = int(kwargs["quantity"])
        # Simulated lot constraints, only for testing reject propagation.
        lot_sizes = {"HK.00700": 100, "HK.09988": 100, "HK.01810": 200}
        lot = lot_sizes.get(code, 1)
        if self.mode == "lot_check" and quantity % lot:
            return {"ret_ok": False}
        price = float(kwargs["price"])
        notional = price * quantity
        if self.mode == "funds_check" and notional > self.cash_by_market[self.market]:
            return {"ret_ok": False}

        partial = self.mode == "partial"
        dealt = max(1, quantity // 2) if partial else quantity
        broker_id = f"LOCAL-{len(self.place_calls):04d}"
        row = {
            "order_id": broker_id, "remark": kwargs["remark"], "code": code,
            "acc_id": self.account_id,
            "trd_side": kwargs["side"], "qty": quantity, "price": price,
            "order_type": "NORMAL", "trd_env": "SIMULATE",
            "order_status": "FILLED_PART" if partial else "FILLED_ALL",
            "dealt_qty": dealt, "dealt_avg_price": price, "time_in_force": "DAY",
            "create_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        }
        self.orders.append(row)
        if dealt:
            direction = 1 if kwargs["side"] == "BUY" else -1
            self.positions[code] = self.positions.get(code, 0) + direction * dealt
            self.cash_by_market[self.market] -= direction * dealt * price
        if self.mode == "lost_after_accept":
            self.mode = "fill"
            raise TimeoutError("local venue injected lost acknowledgement after commit")
        return {"ret_ok": True, "order_id": broker_id}

    def close(self) -> None:
        self.opened = False
