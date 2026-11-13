"""Rerun the swarm under alternative policies on the same exogenous market feed."""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import asdict, dataclass

from orderguard_guard.gate import Mandate
from orderguard_guard.mandate_fit import check_mandate_fit

from .agents import DEFAULT_RATES
from .arena import ArenaConfig, ArenaResult, run_arena
from .authority import Authority
from .envelopes import EnvelopeBook, make_envelope, owner_key_from_seed
from .feeds import RecordedFeed, ReplayFeed, Snapshot

_SIM_KEY = owner_key_from_seed("policy-evaluation")
REGIMES = ("normal", "volatile", "poisoned", "collusion")


@dataclass(frozen=True)
class PolicyScenario:
    seed: int = 7
    agents: int = 150
    steps: int = 400
    regime: str = "normal"

    def __post_init__(self):
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ValueError("Use a seed between 0 and 4294967295.")
        if type(self.agents) is not int or not 1 <= self.agents <= 5_000:
            raise ValueError("Use 1–5,000 agents.")
        if type(self.steps) is not int or not 1 <= self.steps <= 2_000 or self.steps * self.agents > 2_500_000:
            raise ValueError("Use 1–2,000 steps and at most 2,500,000 agent steps.")
        if self.regime not in REGIMES:
            raise ValueError("Choose normal, volatile, poisoned, or collusion.")

    def feed(self) -> ReplayFeed:
        opts = {
            "normal": {},
            "volatile": {"vol_scale": 3.0, "news_jump_rate": 0.0012},
            "poisoned": {"lie_rate": 0.03, "fake_news_rate": 0.008},
            "collusion": {},
        }
        return ReplayFeed(self.seed, steps=self.steps, steps_per_day=max(self.steps // 4, 1), **opts[self.regime])

    def rates(self) -> dict:
        rates = dict(DEFAULT_RATES)
        if self.regime == "collusion":
            rates["colluding"] = 0.10
        if self.regime == "poisoned":
            rates["compromised"] = 0.05
        return rates


@dataclass(frozen=True)
class _PreparedReplay:
    symbols: list[str]
    steps_per_day: int
    snapshots: tuple[Snapshot, ...]

    def __len__(self) -> int:
        return len(self.snapshots)

    def __iter__(self) -> Iterator[Snapshot]:
        return iter(self.snapshots)


def shared_policy_feed(scenario: PolicyScenario, feed: RecordedFeed | None = None) -> RecordedFeed | _PreparedReplay:
    """Prepare the synthetic tape once while each policy retains its own agents, budget and fills."""
    if feed is not None:
        return feed
    market = scenario.feed()
    return _PreparedReplay(market.symbols, market.steps_per_day, tuple(market))


def simulate_policy(body: dict, scenario: PolicyScenario, *, feed: ReplayFeed | RecordedFeed | _PreparedReplay | None = None,
                    agent_share: float | None = None) -> ArenaResult:
    """Run an already validated policy body with fresh agents, a paper book and no external receiver."""
    market = feed if feed is not None else scenario.feed()
    if len(market) * scenario.agents > 2_500_000:
        raise ValueError("This feed and swarm exceed 2,500,000 agent steps.")
    if not set(body["symbols"]).intersection(market.symbols):
        raise ValueError("The policy and the feed have no symbols in common.")
    book = EnvelopeBook(_SIM_KEY.public_key())
    # The owner clock is checked before evaluation. The historical/synthetic clock here is counterfactual.
    book.add(make_envelope(_SIM_KEY, name="policy", purpose="simulation only", symbols=body["symbols"], sides=body["sides"],
                           per_order=body["maxOrderNotionalUsd"], daily=body["maxDailyNotionalUsd"], band_pct=body["priceBandPct"],
                           step_up=body.get("stepUpAboveUsd"), reference_prices=body.get("referencePrices")))
    cfg = ArenaConfig(seed=scenario.seed, agents=scenario.agents, steps=len(market), steps_per_day=market.steps_per_day,
                      rates=scenario.rates(), agent_share=agent_share, paired_fills=True, strict=True)
    authority = Authority(book, steps_per_day=market.steps_per_day, agent_share=agent_share, strict=True)
    return run_arena(cfg, feed=market, book=book, authority=authority)


def policy_metrics(run: ArenaResult) -> dict:
    """Keep simulator truth, authority decisions and paper effects distinct."""
    s = run.summary
    days = s["config"]["days"]
    legit_fills = [e for e in run.events if e["label"] == "legit" and e["fill_price"] is not None]
    bad_allowed = s["bad"]["leak_per_day_usd"]
    # The arena summary rounds total fills and daily authorizations at different
    # stages. Filled notional is a subset of authorized notional at the same price.
    bad_filled = min(bad_allowed, round(s["bad"]["executed_usd"] / days, 2))
    envelope = run.authority.book.envelopes()[0]
    used = envelope.budget.total_by_day()
    return {
        "digest": s["digest"], "days": days, "proposals": s["proposals"], "decisions": s["decisions"],
        "legitimate_proposals": s["legit"]["proposals"], "legitimate_proposed_usd": s["legit"]["notional_usd"],
        "legitimate_allowed_usd_per_day": round(s["legit"]["allowed_usd"] / days, 2),
        "legitimate_fills": len(legit_fills),
        "legitimate_filled_usd_per_day": round(sum(e["risk"] for e in legit_fills) / days, 2),
        "bad_proposed_usd": s["bad"]["attack_notional_usd"],
        "bad_allowed_usd_per_day": bad_allowed,
        "bad_filled_usd_per_day": bad_filled,
        "false_refusal_rate": s["legit"]["false_refusal_rate"], "holds_per_day": s["approvals_per_day"],
        "daily_reserved_usd": [used.get(day, 0.0) for day in range(days)],
        "daily_cap_usd": envelope.budget.cap, "daily_cap_refusals": s["refusal_reasons"].get("daily", 0),
        "refusals_by_reason": s["refusal_reasons"],
    }


def compare_policies(parent: dict, draft: dict, trusted_key, scenario: PolicyScenario, *, now: dt.datetime | None = None,
                     revoked=(), feed: RecordedFeed | None = None) -> dict:
    """Reject a non-contained draft before running either simulated policy."""
    fit = check_mandate_fit(parent, draft, trusted_key, now=now, revoked=revoked)
    if not fit["fits"]:
        return {"fit": fit, "simulation": None}
    market = shared_policy_feed(scenario, feed)
    baseline = Mandate.from_dict(parent).to_dict(with_signature=False)
    results = {name: policy_metrics(simulate_policy(body, scenario, feed=market))
               for name, body in (("parent", baseline), ("draft", fit["draft"]))}
    return {"fit": fit, "simulation": {"scenario": asdict(scenario) | {"steps": len(market), "steps_per_day": market.steps_per_day},
                                       "feed": market.path.name if feed is not None else "synthetic", "results": results,
                                       "unobserved_draft_symbols": sorted(set(fit["draft"]["symbols"]) - set(market.symbols))}}
