"""Compact, seeded agent population for impact-market simulations.

Agent attributes and positions live in NumPy arrays. Each step creates a sparse
batch of orders; every emitted row is still passed individually to the real
OrderGuard Authority. Only the authorized dollar flow is summed for market
impact. Agent generation is intentionally stylized and is not an LLM workload.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .market import ImpactMarket

ARCHETYPES = ("market_making", "momentum", "mean_reversion", "rebalancing", "news_reactive", "colluding", "compromised", "runaway")
ARCHETYPE_MIX = np.array([0.22, 0.20, 0.16, 0.17, 0.18, 0.025, 0.02, 0.025], dtype=np.float64)


@dataclass(slots=True)
class OrderBatch:
    """Sparse per-step order arrays. `side` is +1 for buy, -1 for sell."""

    agent: np.ndarray
    symbol: np.ndarray
    side: np.ndarray
    quantity: np.ndarray
    limit_price: np.ndarray
    envelope: np.ndarray
    label: np.ndarray
    key: np.ndarray
    trigger: np.ndarray

    def __len__(self) -> int:
        return len(self.agent)


class VectorPopulation:
    """Population state sized for 10^4..10^6 simulated agents."""

    def __init__(self, agents: int, symbols: list[str], envelopes: int, seed: int, *, activity: float = 0.0005,
                 honest_mix: np.ndarray | None = None):
        if agents < 1 or envelopes < 1 or not symbols:
            raise ValueError("agents, envelopes and symbols must be positive")
        self.n, self.symbols, self.env_count = int(agents), list(symbols), int(envelopes)
        self.seed, self.activity = int(seed), float(activity)
        self.rng = np.random.default_rng(seed + 0x0A11CE)
        mix = ARCHETYPE_MIX if honest_mix is None else np.asarray(honest_mix, dtype=np.float64)
        if mix.shape != (len(ARCHETYPES),) or np.any(mix < 0) or not np.isclose(mix.sum(), 1.0):
            raise ValueError("archetype mix must have eight non-negative weights summing to one")
        self.archetype = self.rng.choice(len(ARCHETYPES), size=self.n, p=mix).astype(np.uint8)
        self.envelope = (np.arange(self.n, dtype=np.int64) % self.env_count).astype(np.int32)
        # Four-symbol baskets create cross-symbol holdings. Repeated basket names
        # are harmless and avoid an N x S permutation allocation at million scale.
        self.basket = self.rng.integers(0, len(self.symbols), size=(self.n, 4), dtype=np.int16)
        self.venue = self.rng.integers(0, 3, size=self.n, dtype=np.uint8)
        self.size_usd = np.clip(self.rng.lognormal(np.log(4_000.0), 0.65, self.n), 250.0, 40_000.0)
        self.aggression = self.rng.uniform(0.0003, 0.0025, self.n)
        self.position = np.zeros((self.n, len(self.symbols)), dtype=np.int32)
        self.cash = np.zeros(self.n, dtype=np.float64)
        self.last_symbol = np.zeros(self.n, dtype=np.int16)
        self.last_side = np.ones(self.n, dtype=np.int8)
        self.last_qty = np.ones(self.n, dtype=np.int32)
        self.last_limit = np.ones(self.n, dtype=np.float64)
        self.runaway_key = np.full(self.n, "", dtype=object)

    @property
    def archetype_names(self) -> np.ndarray:
        return np.asarray(ARCHETYPES, dtype=object)[self.archetype]

    @property
    def honest_mask(self) -> np.ndarray:
        return self.archetype < 5

    def propose(self, market: ImpactMarket, step: int, scenario, *, per_order_cap: float) -> OrderBatch:
        """Generate one sparse batch using vector operations over agent state."""
        rng = self.rng
        n = self.n
        arch = self.archetype
        probabilities = np.full(n, self.activity, dtype=np.float64)
        # Failed/attack archetypes are infrequent in ordinary steps. Scenario
        # windows explicitly raise activity so their aggregate effects are visible.
        probabilities[arch == 5] = self.activity * 0.15
        probabilities[arch == 6] = self.activity * 0.4
        probabilities[arch == 7] = self.activity * 0.25
        if scenario.kind == "collusion_ring" and scenario.attack_start <= step < scenario.attack_end:
            probabilities[arch == 5] = scenario.attack_activity
        if scenario.kind == "crowded_momentum" and step >= scenario.shock_step:
            probabilities[arch == 1] = scenario.attack_activity
        if scenario.kind in ("fake_headline", "real_crash") and step == scenario.headline_step:
            probabilities[arch == 4] = scenario.attack_activity
        if scenario.kind == "stale_feed" and step > scenario.shock_step:
            probabilities[(arch == 1) & (self.venue == 2)] = max(self.activity, scenario.attack_activity)
        active = rng.random(n) < probabilities
        idx = np.flatnonzero(active)
        if not len(idx):
            empty = np.empty(0)
            return OrderBatch(empty.astype(np.int32), empty.astype(np.int16), empty.astype(np.int8), empty.astype(np.int32),
                              empty.astype(np.float64), empty.astype(np.int32), empty.astype(object), empty.astype(object), empty.astype(object))

        ai = arch[idx]
        slots = rng.integers(0, self.basket.shape[1], len(idx), dtype=np.uint8)
        sym = self.basket[idx, slots].astype(np.int16)
        # All shared price views are derived from the impact market. The stale
        # venue scenario affects only agents assigned to venue C.
        if scenario.target_symbol in market.index:
            target = market.index[scenario.target_symbol]
        else:
            target = 0
        target_orders = np.zeros(len(idx), dtype=bool)
        if scenario.kind in ("fake_headline", "real_crash", "crowded_momentum"):
            if scenario.kind != "real_crash" or step > scenario.shock_step:
                target_orders = (ai == 4) if scenario.kind == "fake_headline" else (ai == 1)
                sym[target_orders] = target
        if scenario.kind == "collusion_ring" and scenario.attack_start <= step < scenario.attack_end:
            colluders = ai == 5
            ring = scenario.ring_symbols or [scenario.target_symbol]
            ring_ix = np.array([market.index[s] for s in ring if s in market.index], dtype=np.int16)
            if len(ring_ix):
                sym[colluders] = ring_ix[(idx[colluders] + step) % len(ring_ix)]
        if scenario.kind == "stale_feed":
            sym[ai == 1] = target

        px = market.mid[sym].copy()
        stale = (scenario.kind == "stale_feed") & (step > scenario.shock_step) & (self.venue[idx] == 2) & (sym == target)
        if np.any(stale):
            lag = max(int(scenario.stale_lag), 1)
            px[stale] = np.array([market.quote(self.symbols[int(s)], lag=lag) for s in sym[stale]])
        px = np.maximum(px, 0.01)

        # Five-step price move informs momentum and mean reversion. It is an
        # observation, not an approval input.
        lookback_ix = max(0, len(market.prices) - 1 - 5)
        past = market.prices[lookback_ix][sym]
        move = np.log(market.mid[sym] / np.maximum(past, 0.01))
        side = rng.choice(np.array([-1, 1], dtype=np.int8), size=len(idx))
        mom = ai == 1
        mr = ai == 2
        side[mom] = np.where(move[mom] >= 0, 1, -1)
        side[mr] = np.where(move[mr] >= 0, -1, 1)
        reb = ai == 3
        if np.any(reb):
            have = self.position[idx[reb], sym[reb]]
            side[reb] = np.where(have > 0, -1, 1)
        news = ai == 4
        if np.any(news):
            if scenario.kind == "fake_headline" and step == scenario.headline_step:
                side[news] = scenario.headline_side
            elif scenario.kind == "real_crash":
                side[news] = -1
        collude = ai == 5
        if np.any(collude):
            side[collude] = 1 if scenario.kind == "collusion_ring" else rng.choice(np.array([-1, 1], dtype=np.int8), size=int(collude.sum()))
        compromised = ai == 6
        if np.any(compromised):
            side[compromised] = 1

        dollars = self.size_usd[idx] * rng.lognormal(0.0, 0.35, len(idx))
        dollars = np.minimum(dollars, per_order_cap * 0.92)
        if np.any(collude):
            dollars[collude] = per_order_cap * rng.uniform(0.70, 0.88, int(collude.sum()))
        if np.any(compromised):
            dollars[compromised] = per_order_cap * rng.uniform(1.02, 1.35, int(compromised.sum()))
        qty = np.maximum(1, np.floor(dollars / px)).astype(np.int32)
        # Runaway rows replay one identical order/key. Authority's own
        # idempotency check ensures only the original can consume budget/flow.
        runaway = ai == 7
        limit = px * (1.0 + side * self.aggression[idx])
        if np.any(runaway):
            rids = idx[runaway]
            fresh = self.runaway_key[rids] == ""
            self.last_symbol[rids[fresh]] = sym[runaway][fresh]
            self.last_side[rids[fresh]] = side[runaway][fresh]
            self.last_qty[rids[fresh]] = qty[runaway][fresh]
            self.last_limit[rids[fresh]] = limit[runaway][fresh]
            self.runaway_key[rids[fresh]] = [f"sim:{self.seed}:runaway:{int(a)}" for a in rids[fresh]]
            sym[runaway] = self.last_symbol[rids]
            side[runaway] = self.last_side[rids]
            qty[runaway] = self.last_qty[rids]
            limit[runaway] = self.last_limit[rids]

        labels = np.full(len(idx), "legit", dtype=object)
        labels[collude] = "collusion"
        labels[compromised] = "compromised"
        labels[runaway] = "runaway"
        labels[stale] = "stale_price"
        if scenario.kind == "fake_headline" and step == scenario.headline_step:
            labels[news & target_orders] = "fake_news"
        keys = np.array([f"sim:{self.seed}:{int(a)}:{step}" for a in idx], dtype=object)
        if np.any(runaway):
            keys[runaway] = self.runaway_key[idx[runaway]]
        triggers = np.full(len(idx), None, dtype=object)
        if scenario.kind == "fake_headline" and step == scenario.headline_step:
            for j in np.flatnonzero(news & target_orders):
                triggers[j] = {"news_id": scenario.news_id, "rule": f"headline {scenario.target_symbol}", "pct": scenario.headline_side * 10}
        elif scenario.kind == "real_crash" and step == scenario.headline_step and np.any(news):
            for j in np.flatnonzero(news):
                triggers[j] = {"news_id": scenario.news_id, "rule": f"real shock {scenario.target_symbol}", "pct": -8.0}
        return OrderBatch(idx.astype(np.int32), sym, side, qty, limit.astype(np.float64), self.envelope[idx].copy(), labels, keys, triggers)

    def on_fill(self, agent: int, symbol: int, side: int, quantity: int, price: float) -> None:
        self.position[agent, symbol] += side * quantity
        self.cash[agent] -= side * quantity * price

