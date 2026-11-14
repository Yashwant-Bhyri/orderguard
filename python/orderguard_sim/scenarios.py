"""Named, deterministic stress scenarios used by ``og-sim``."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Scenario:
    kind: str
    title: str
    description: str
    target_symbol: str
    shock_step: int
    headline_step: int
    attack_start: int
    attack_end: int
    attack_activity: float = 0.04
    headline_side: int = 1
    shock_pct: float = 0.0
    ring_symbols: tuple[str, ...] = ()
    stale_lag: int = 8
    news_id: str = ""

    def exogenous_log_return(self, step: int) -> dict[str, float]:
        if step == self.shock_step and self.shock_pct:
            import math
            return {self.target_symbol: math.log1p(self.shock_pct)}
        return {}

    def as_dict(self) -> dict:
        d = asdict(self)
        d["ring_symbols"] = list(self.ring_symbols)
        return d


SCENARIOS = {
    "fake_headline": ("Fake headline", "One unsupported headline prompts the news-reactive cohort to trade one name; L7 should hold rule-triggered orders.", "AAPL", 0.0, 1, ()),
    "real_crash": ("Confirmed 8% price shock", "A synthetic, three-source-confirmed 8% shock hits one large-cap name, then correlated prices and momentum agents respond.", "AAPL", -0.08, -1, ()),
    "crowded_momentum": ("Crowded momentum", "A +5% price impulse attracts synchronized momentum buying and tests caps against self-inflicted impact.", "NVDA", 0.05, 1, ()),
    "collusion_ring": ("Collusion ring", "A coordinated group buys three correlated large-cap names through shared envelopes.", "AAPL", 0.0, 1, ("AAPL", "MSFT", "SPY")),
    "stale_feed": ("One stale venue", "Venue C misses an 8% repricing and remains eight steps stale for one symbol; the authority still trusts the median of three venues.", "AAPL", 0.08, 1, ()),
}


def build_scenario(name: str, steps: int, *, attack_activity: float = 0.04, seed: int = 0) -> Scenario:
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}; choose one of {', '.join((*SCENARIOS, 'all'))}")
    title, desc, target, shock_pct, side, ring = SCENARIOS[name]
    shock_step = max(2, min(int(steps * 0.25), steps - 2))
    headline_step = shock_step
    return Scenario(name, title, desc, target, shock_step, headline_step, shock_step, max(shock_step + 1, int(steps * 0.75)),
                    float(attack_activity), side, shock_pct, tuple(ring), 8, f"SIM-{name}-{seed}")

