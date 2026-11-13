"""Pre-simulation features for a draft in a seeded synthetic world."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import numpy as np

from .agents import Agent, Ctx, PopulationConfig, make_population
from .envelopes import split_sleeves
from .feeds import ReplayFeed
from .policy_sim import PolicyScenario

CONTEXT_FEATURES = ("active_collusion_groups", "first_collusion_in_day", "peak_collusion_pressure",
                    "mean_collusion_pressure", "total_activity", "automatic_activity", "mean_absolute_return",
                    "large_return_share", "news_jump_share", "fake_news_share")
RUNAWAY_FEATURES = tuple(f"{trajectory}_{metric}" for trajectory in ("no_fills", "permissive_fills")
                         for metric in ("runaway_agents", "runaway_mean", "runaway_peak", "runaway_first"))
RUNAWAY_ORDER = np.dtype([("agent", "i4"), ("symbol", "U20"), ("side", "U4"), ("step", "i4"),
                          ("notional", "f8"), ("price_distance", "f8")])


@dataclass(frozen=True)
class ScenarioInputs:
    market: ReplayFeed
    groups: list[dict]
    normal: list[tuple[list[str], float, float]]
    runaway: tuple[np.ndarray, ...] = ()


def scenario_inputs(scenario: PolicyScenario, market: ReplayFeed | None = None, *, include_runaway: bool = False) -> ScenarioInputs:
    market = market if market is not None else scenario.feed()
    population = make_population(PopulationConfig(n=scenario.agents, seed=scenario.seed, rates=scenario.rates()),
                                 split_sleeves(market.symbols), scenario.steps)
    groups = {agent.group["id"]: agent.group for agent in population if agent.group}
    normal = [(a.symbols, a.size, {"news_reactive": 0.1, "market_maker": 0.4}.get(a.archetype, 1) / a.period)
              for a in population]
    runaway = runaway_orders(market, population) if include_runaway else ()
    return ScenarioInputs(market, list(groups.values()), normal, runaway)


def runaway_orders(market: ReplayFeed, population: list[Agent]) -> tuple[np.ndarray, np.ndarray]:
    """Generate indicative fresh-ID retries from two independent position trajectories."""
    loopers = [agent for agent in population if agent.failure == "runaway" and agent.run_fresh]
    if not loopers:
        return np.empty(0, dtype=RUNAWAY_ORDER), np.empty(0, dtype=RUNAWAY_ORDER)
    # Each trajectory uses the seed and known tape. No outcomes from the full simulator enter these inputs.
    records = ([], [])
    shadows = (deepcopy(loopers), deepcopy(loopers))
    context = Ctx(len(market))
    for snapshot in market:
        prices = snapshot.trusted()
        context.update(snapshot.step, prices, snapshot.meta.get("fake_news", ()))
        for fill_base_orders, agents, orders in zip((False, True), shadows, records):
            for agent in agents:
                for proposal in agent.propose(context, snapshot, snapshot.step):
                    order = proposal.order
                    symbol, side, quantity = order["ticker"], order["side"], order["quantity"]
                    price = prices[symbol]
                    if proposal.label == "runaway_loop" and price > 0 and (proposal.trigger is None or
                            proposal.trigger["news_id"] not in context.fake_news):
                        distance = abs(order["limit_price"] - price) / price * 100
                        orders.append((agent.id, symbol, side, snapshot.step, round(quantity * price, 2), distance))
                    elif fill_base_orders and proposal.label == "legit" and agent.run_order is None:
                        agent.on_fill(symbol, side, quantity)
    return tuple(np.array(orders, dtype=RUNAWAY_ORDER) for orders in records)


def runaway_vector(body: dict, inputs: ScenarioInputs) -> list[float]:
    """Estimate pressure before shared budget, portfolio and fill effects are evaluated."""
    daily = body["maxDailyNotionalUsd"]
    step_up = body.get("stepUpAboveUsd")
    automatic = min(daily, body["maxOrderNotionalUsd"], step_up if step_up is not None else daily)
    dayspan = inputs.market.steps_per_day
    days = -(-len(inputs.market) // dayspan)
    values = []
    for orders in inputs.runaway:
        fits = (np.isin(orders["symbol"], body["symbols"]) & np.isin(orders["side"], body["sides"])
                & (orders["notional"] <= automatic) & (orders["price_distance"] <= body["priceBandPct"]))
        allowed = orders[fits]
        pressure = np.bincount(allowed["step"] // dayspan, weights=allowed["notional"], minlength=days) / daily
        first = (allowed["step"] % dayspan).min(initial=dayspan) / dayspan
        values.extend((np.log1p(len(np.unique(allowed["agent"]))), np.log1p(pressure.mean()), np.log1p(pressure.max()), first))
    return values


def context_vector(body: dict, inputs: ScenarioInputs) -> list[float]:
    market, groups, normal = inputs.market, inputs.groups, inputs.normal
    allowed = set(body["symbols"])
    per_order, daily = body["maxOrderNotionalUsd"], body["maxDailyNotionalUsd"]
    step_up = body.get("stepUpAboveUsd")
    automatic = per_order if step_up is None else min(per_order, step_up)
    dayspan = market.steps_per_day
    price_path = market._true
    symbol_index = {symbol: i for i, symbol in enumerate(market.symbols)}
    pressure = np.zeros(-(-len(price_path) // dayspan))
    first_collusion, active_groups = 1.0, 0
    if "buy" in body["sides"]:
        for group in groups:
            if group["ticker"] not in allowed:
                continue
            start = group["start"]
            end = min(start + group["window"], len(price_path))
            prices = price_path[start:end, symbol_index[group["ticker"]]]
            quantity = np.maximum(1, np.floor(automatic * group["frac"] / prices))
            eligible = (quantity * prices <= automatic) & (body["priceBandPct"] >= 0.1)
            if eligible.any():
                pressure += np.bincount(np.arange(start, end) // dayspan, weights=quantity * prices * eligible,
                                        minlength=len(pressure))
                first_collusion = min(first_collusion, (start % dayspan) / dayspan)
                active_groups += 1
    returns = np.abs(np.diff(np.log(price_path[:, [symbol_index[s] for s in sorted(allowed)]]), axis=0))
    order_rates = [(size, rate * (len(allowed.intersection(symbols)) / len(symbols))) for symbols, size, rate in normal]
    activity = sum(size * rate for size, rate in order_rates) * dayspan / daily
    automatic_activity = sum(size * rate for size, rate in order_rates if size <= automatic) * dayspan / daily
    return [np.log1p(active_groups), first_collusion, np.log1p(pressure.max() / daily), np.log1p(pressure.mean() / daily),
            np.log1p(activity), np.log1p(automatic_activity), returns.mean(), (returns >= 0.01).mean(),
            market._jump_hit.mean(), market._fake_hit.mean()]
