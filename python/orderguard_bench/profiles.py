"""Benchmark profiles. `quick` fits in CI (under two minutes on a laptop); `full` is the exchange-scale run (about twenty minutes)."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    seed: int = 11
    agents: int = 20_000
    owners: int = 80                       # each owner signs three envelopes (core, tactical, crypto): envelopes = 3 x owners
    steps: int = 400
    steps_per_day: int = 200
    partitions: int = 8                    # workload is generated once into this many owner partitions; worker counts must divide it
    workers: tuple = (1, 2, 4)             # gate-only scaling runs
    risk_workers: tuple = (1, 4)           # gate + order-risk model runs; the smallest N is the economic reference (fewest, widest scorers)
    scorer_scaling_s: float = 0.0          # seconds per point of the single-scorer scaling measurement (0 = skip)
    retry_rate: float = 0.03               # a delivered order is re-delivered later with the same key (client retry)
    dupnow_rate: float = 0.01              # ... or delivered twice back to back (duplicate delivery)
    conflict_rate: float = 0.005           # ... or its key is reused for a different order (tampered retry)
    stage_sample: int = 20_000             # decisions in the per-stage profiling pass
    receiver_envelopes: int = 6            # envelopes whose full order streams go through the TypeScript receiver
    receiver_max_orders: int = 30_000
    race_procs: int = 4                    # processes racing one SQLite ledger
    race_orders: int = 60                  # orders per racing process
    fault_cycles: int = 3                  # SIGKILL + restart cycles of a durable receiver
    fault_orders: int = 400
    thread_race: int = 16                  # threads racing one envelope inside one Python process
    http_requests: int = 2_000
    http_concurrency: int = 32
    growth_orders: int = 10_000            # one envelope, one day: receiver latency as its ledger grows

    def to_dict(self) -> dict:
        return asdict(self)


PROFILES = {
    "quick": Profile("quick"),
    "full": Profile("full", agents=100_000, owners=400, steps=1000, steps_per_day=500, workers=(1, 2, 4, 8), risk_workers=(8,),
                    stage_sample=100_000, receiver_envelopes=24, receiver_max_orders=250_000, race_procs=8, race_orders=150,
                    fault_cycles=20, fault_orders=3_000, thread_race=32, http_requests=20_000, http_concurrency=64,
                    growth_orders=100_000, scorer_scaling_s=60.0),
    "tiny": Profile("tiny", agents=2_000, owners=10, steps=200, steps_per_day=100, partitions=2, workers=(1, 2), risk_workers=(1,),
                    stage_sample=2_000, receiver_envelopes=2, receiver_max_orders=3_000, race_procs=2, race_orders=30, fault_cycles=1,
                    fault_orders=80, thread_race=8, http_requests=200, http_concurrency=8, growth_orders=2_000),
}


def get(name: str, **over) -> Profile:
    if name not in PROFILES:
        raise SystemExit(f"unknown profile {name!r}; choose one of {', '.join(PROFILES)}")
    p = PROFILES[name]
    return Profile(**{**p.to_dict(), **{k: v for k, v in over.items() if v is not None}}) if over else p

