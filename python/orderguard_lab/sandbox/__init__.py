"""The sandbox at scale: seeded simulated worlds, a technique compiler with benign twins, offline policy agents, sweeps and a manifest.

world.py     deterministic World generator: (seed, config) -> instruments, venues, trusted prices, corporate actions, filings, wires, pages, account, mandate, rules, clock
compiler.py  (family x surface x technique x parameters) -> attack env + success predicate + BENIGN TWIN
policy.py    offline credulous / cautious policy agents (a ScriptedLLM-style fake) so the pipeline runs at 1,000+ worlds for zero spend
sweep.py     og-lab sweep: budget-aware, resumable, with per-run metrics
manifest.py  og-lab sandbox describe -> docs/SANDBOX.md
"""
