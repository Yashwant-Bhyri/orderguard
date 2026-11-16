"""The simulated world every system faces: an impact market from orderguard_sim, brokers that can delay or lose reports, and the
account's true positions. Paper and simulation only: nothing here can reach an exchange.

Timing within one step t:
    1. marks are the market mid at t (the trusted price every system sees)
    2. broker reports due at t are delivered (to the system and to the agents)
    3. every R steps the broker's full order list and positions go to the system (reconciliation)
    4. agents propose; each proposal goes through the system; allowed orders are sent to a venue
    5. orders that reached a venue fill at the mid of t plus square-root impact, if marketable; unfilled ones cancel after 3 steps
    6. the market steps with the net filled flow and the scenario's exogenous returns
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from orderguard_sim.market import ImpactMarket

SYMBOLS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "JNJ", "KO", "JPM", "XOM", "SPY", "QQQ"]
SECTORS = {"AAPL": "tech", "MSFT": "tech", "NVDA": "tech", "GOOGL": "tech", "AMZN": "consumer", "TSLA": "consumer",
           "JNJ": "healthcare", "KO": "staples", "JPM": "financials", "XOM": "energy", "SPY": "index", "QQQ": "index"}
PRICES = {"AAPL": 230.0, "MSFT": 420.0, "NVDA": 135.0, "GOOGL": 170.0, "AMZN": 190.0, "TSLA": 250.0, "JNJ": 155.0, "KO": 62.0,
          "JPM": 210.0, "XOM": 115.0, "SPY": 560.0, "QQQ": 480.0}
SIGMA_STEP = 0.0009                 # per-step volatility; at 390 steps a day that is about 1.8% a day
STUDENT_DF = 5.0


@dataclass
class Proposal:
    """One order an agent proposes, with the typed intent behind it and the ground truth the benchmark scores against."""
    agent: str
    symbol: str
    side: str
    qty: int
    limit: float
    key: str
    label: str = "legit"                      # legit | harmful (ground truth, never shown to a system)
    harm_kind: str = ""
    intent_id: str = ""
    intent_symbol: str | None = None          # what the agent decided, if a compromised tool changed the order
    intent_side: str | None = None
    intent_qty: int | None = None
    kind: str = "fundamental"
    action: str | None = None
    evidence: tuple[str, ...] = ()
    claims: tuple = ()
    thesis: str = "position sized to the signed plan"
    venue: str = "V1"
    lineage_child: bool = False               # sent by a helper the agent's tool spawned
    retry_of: str | None = None
    mark_notional: float = 0.0                # trusted price at decision time (set by the runner)


@dataclass
class BrokerOrder:
    oid: str
    p: Proposal
    sent: int
    venue: str
    arrived: bool = True
    status: str = "new"
    filled: int = 0
    price: float = 0.0
    report_lost: bool = False


@dataclass
class Report:
    oid: str
    status: str                 # acknowledged, filled, canceled, rejected
    filled: int
    price: float
    step: int


class Broker:
    """One or more venues for one account. `delay_fn(order, step) -> (delay_steps, lost_report, lost_in_transit)` lets a scenario
    model a bad connection: reports arrive late, never arrive (until reconciliation), or the order never reaches the venue."""

    def __init__(self, delay_fn=None):
        self.orders: dict[str, BrokerOrder] = {}
        self.queue: list[tuple[int, Report]] = []
        self.delay_fn = delay_fn or (lambda o, s: (1, False, False))
        self.positions: dict[str, int] = {}
        self.venue_positions: dict[str, dict[str, int]] = {}

    def send(self, oid: str, p: Proposal, step: int) -> None:
        delay, lost, transit = self.delay_fn(p, step)
        o = BrokerOrder(oid, p, step, p.venue, arrived=not transit, report_lost=lost)
        o.delay = delay
        self.orders[oid] = o
        if transit:
            return
        if not lost:
            self.queue.append((step + delay, Report(oid, "acknowledged", 0, 0.0, step)))

    def process(self, step: int, market: ImpactMarket, flow: np.ndarray) -> list[BrokerOrder]:
        """Fill what arrived and is marketable; cancel what has rested 3 steps. Returns orders filled this step."""
        filled = []
        gross: dict[str, float] = {}
        for o in self.orders.values():
            if not o.arrived or o.status not in ("new",):
                continue
            i = market.index[o.p.symbol]
            mid = float(market.mid[i])
            sgn = 1 if o.p.side == "buy" else -1
            gross[o.p.symbol] = gross.get(o.p.symbol, 0.0) + o.p.qty * mid
            px = mid * math.exp(sgn * market.slippage_fraction(o.p.symbol, gross[o.p.symbol]))
            if (sgn > 0 and px <= o.p.limit) or (sgn < 0 and px >= o.p.limit):
                o.status, o.filled, o.price = "filled", o.p.qty, px
                self.positions[o.p.symbol] = self.positions.get(o.p.symbol, 0) + sgn * o.p.qty
                vp = self.venue_positions.setdefault(o.venue, {})
                vp[o.p.symbol] = vp.get(o.p.symbol, 0) + sgn * o.p.qty
                flow[i] += sgn * o.p.qty * px
                filled.append(o)
                if not o.report_lost:
                    self.queue.append((step + o.delay, Report(o.oid, "filled", o.filled, px, step)))
            elif step - o.sent >= 3:
                o.status = "canceled"
                if not o.report_lost:
                    self.queue.append((step + o.delay, Report(o.oid, "canceled", 0, 0.0, step)))
        return filled

    def deliver(self, step: int) -> list[Report]:
        due = [r for t, r in self.queue if t <= step]
        self.queue = [(t, r) for t, r in self.queue if t > step]
        return due

    def snapshot(self) -> tuple[list[dict], dict[str, int]]:
        """The broker's own records: every order it received (status and fill) and the account's positions. Complete as of now."""
        orders = [{"order_id": o.oid, "idempotency_key": o.p.key, "status": o.status if o.status != "new" else "acknowledged",
                   "filled": o.filled, "price": o.price, "venue": o.venue} for o in self.orders.values() if o.arrived]
        return orders, dict(self.positions)


class World:
    def __init__(self, seed: int, steps: int, steps_per_day: int, *, sigma: float = SIGMA_STEP, delay_fn=None):
        self.seed, self.steps, self.steps_per_day = seed, steps, steps_per_day
        self.market = ImpactMarket(SYMBOLS, seed, initial_prices=PRICES, sigma={s: sigma for s in SYMBOLS}, student_df=STUDENT_DF)
        self.broker = Broker(delay_fn)
        self.rng = np.random.default_rng(seed + 10_007)
        self.step = 0
        self.regime_factor = 0.0              # extra common-factor volatility per step (the volatility regime scenario)

    def marks(self) -> dict[str, float]:
        return {s: float(self.market.mid[i]) for i, s in enumerate(SYMBOLS)}

    def true_step_cov(self) -> np.ndarray:
        """The market's actual per-step covariance right now (GARCH state, correlation, regime factor). Ground truth for scoring."""
        m = self.market
        sd = m.sigma * np.sqrt(m.variance_state)
        cov = m.correlation * sd[:, None] * sd[None, :]
        if self.regime_factor:
            cov = cov + self.regime_factor ** 2
        return cov

    def true_daily_es(self, exposures: dict[str, float], alpha: float = 0.975) -> float:
        from ..risk import es_factor
        w = np.array([exposures.get(s, 0.0) for s in SYMBOLS])
        var = float(w @ self.true_step_cov() @ w) * self.steps_per_day
        return es_factor(alpha, STUDENT_DF) * math.sqrt(max(var, 0.0))
