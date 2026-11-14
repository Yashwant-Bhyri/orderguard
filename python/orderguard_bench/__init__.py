"""OrderGuard Bench: throughput, latency and audited correctness of the pre-trade authority at swarm scale.

    og-bench run --profile quick|full      workload -> sharded authority runs -> independent audit -> receiver runs -> report

See docs/BENCH.md for the method and the limits. Nothing here sends an order anywhere: the market data is a local recording plus a
seeded synthetic feed, the agents are simulated and the receiver ledgers are throw-away SQLite files.
"""
