# OrderGuard Bench

**In short.** We ran 1.09 million orders from 100,000 simulated agents across 1,200 human-signed envelopes. The orders followed real recorded Binance prices and included every attack we model plus deliberate abuse of the system itself. An independent auditor found **zero** breaches of any signed limit. The gate made identical decisions on 1, 2, 4 and 8 processes, peaking at **140,302 decisions per second**. When we deliberately broke each safety mechanism, the auditor caught it **every time (7 of 7)**. Two weaknesses are open: the order-risk model stops scaling when one scorer watches more than about 25,000 agents, and these are simulated agents on one laptop, not production order flow.

Reproduce: `og-bench run --profile quick` (about a minute, CI-sized) or `og-bench run --profile full`. The report is [results/bench/report.html](../results/bench/report.html): a single file that works offline. The headline numbers are in [results/bench/summary.json](../results/bench/summary.json).

## The claim

OrderGuard lets AI-agent order flow through only when the order fits what a human signed: allowed symbols and sides, per-order and daily caps, price band, step-up threshold, per-symbol, position and order-count limits, all valued at a trusted price. The claim this bench tests is that **this holds at exchange scale, under concurrency, crashes and active abuse, and that it can be checked independently after the fact.**

## The evidence

### 1. Nothing outside the mandate took effect

After every run an auditor recomputes everything from the decision logs, the signed mandates and the raw market quotes. It never reads the system's own counters. For each envelope it rebuilds the budget, per-symbol, position and order-count tallies, then re-checks every allowed and held order with the strict reference gate (`OrderGate`).

| what was checked | quick profile (20,000 agents, 240 envelopes) | full profile (100,000 agents, 1,200 envelopes) |
|---|---|---|
| decisions audited | 439,340 across 5 runs | 4,362,432 across 4 gate runs (1,090,608 each) |
| signed-limit breaches (daily, per-order, per-symbol, position, orders per day) | **0** | **0** |
| allows and holds independently reproduced by the reference gate | 75,664 of 75,664 per run | (audited, all reproduced) |
| duplicate and retried deliveries: executed twice | **0** of 4,597 | 0 |
| tampered retries (same key, different order) accepted | **0** of 380 | 0 |
| orders allowed after a revoke | **0** (8 revocations) | 0 |
| replayed, widened or foreign-signed mandates that took effect | **0** (8 replays, 16 forgeries) | 0 |
| decision log hash chain | verified, 87,900 links per run | verified |
| same decisions at every process count | yes (digest `f2017979b5de`) | yes (digest `ef51b8a25162`) |

The workload mixes honest strategies with every attack family we model: fat finger, stale price, off-list and look-alike tickers, compromised agents, runaway loops, and three kinds of colluders, including white-box adaptive colluders tuned against the shipped risk model. It also includes traffic aimed at the system: retries, duplicate deliveries, tampered retries, bursts of about 1.6x an envelope's daily cap, orders exactly at the limits, revocations, and replayed and forged mandates.

### 2. The auditor would have noticed

A clean audit means little unless the auditor can fail. Each guarantee was switched off in turn, and every run failed its audit:

| guarantee switched off | where | auditor found |
|---|---|---|
| daily budget check and reservation | Python authority | 2,469 daily-cap breaches |
| idempotency | Python authority | 4,000 double executions |
| portfolio limits | Python authority | 50 order-count and 49 position-cap breaches |
| revocation | Python authority | 1,664 orders after revoke |
| budget lock, 16 threads racing one envelope | Python authority | 160 over-cap fills (intact: exactly the 20 entitled fills) |
| budget lock (`budgetLockOff`), 4 processes racing one ledger | TypeScript receiver | 220 daily-cap breaches (intact: exactly 20 fills) |
| idempotency (`idempotencyOff`), 4 processes sending the same keys | TypeScript receiver | 180 double executions (intact: 60 rows for 60 keys) |

### 3. It survives crashes

A durable receiver was killed with SIGKILL at random moments, often mid-commit, then restarted and fed every order it had not acknowledged. Every restart re-verified the whole hash chain before serving (4 of 4). 30 orders had committed without the client hearing back; all were answered as replays when re-sent, none executed twice. No acknowledged order was lost, and the ledger audited clean. The full profile is set to repeat this 20 times; that run was not completed here.

### 4. Exact limits behave exactly

Thirty probes sit exactly at a limit or one unit or one cent past it: per-order cap, daily cap, step-up, price band, per-symbol cap, position cap (long and short), orders per day, the next-day rollover, and revoke-then-replay. All 30 get the decision the mandate requires, identically in the Python authority, the reference gate and the TypeScript receiver.

### 5. Speed

Measured on an 8-core Apple-silicon laptop (16 GiB) with CPython 3.12.3 and Node v26.0.0.

| | decisions per second | latency p50 / p99 / p99.9 |
|---|---|---|
| Python authority, gate only, 1 process (full, 1.09M orders) | 45,099 | |
| ... 2 / 4 / 8 processes (full) | 71,752 / 119,882 / **140,302** | |
| Python authority, gate only, 1 process (quick) | 52,278 | 7.5 / 31 / 83 µs per decision |
| gate + order-risk model, 1 process (quick) | 9,019 | 80 / 277 / 1,080 µs per order |
| TypeScript receiver, in-process, throw-away ledger | 22,456 | 44 / 127 / 498 µs per order |
| TypeScript receiver, in-process, durable ledger (WAL, fsync) | 5,414 | 77 / 1,778 / 4,072 µs per order |
| receiver over its HTTP bridge | not measured here (see limits) | |

Scaling flattens past 4 processes: the laptop has fewer performance cores than logical CPUs. The order-risk model costs about 50 µs per order and dominates when it is on.

For context only: production pre-trade risk gateways at venues are usually described in single-digit microseconds or less, on native or hardware paths. OrderGuard is an authorization layer in front of a broker's or venue's own risk controls, written in Python and TypeScript. These numbers show what it does as written; they do not show that it matches those gateways.

### 6. What it stops

From the quick profile's gate + risk run. Dollars are notional at the trusted price, counting first deliveries only.

| | proposed | stopped by the gate | stopped by the risk model | let through |
|---|---|---|---|---|
| all bad orders | $123.9M | $85.0M | $37.1M | **$1.80M (98.5% stopped)** |
| of which white-box adaptive colluders | $4.03M | $0.36M | $2.17M | **$1.49M (62.9% stopped)** |
| gate alone, without the risk model | | | | $38.9M (68.6% stopped) |

Honest orders: 91.9% allowed, 5.2% refused (mostly when the shared daily budget ran out), 2.9% held for a human. Human review load: 1,782 holds a day, 89 per 1,000 agents.

## Limits

- **Simulated, not production.** The agents and fills are simulated, and no order was sent anywhere. BTC, ETH and SOL prices come from a real Binance recording, but it is only 144 ticks long and is replayed forwards and backwards. The other 15 symbols are synthetic.
- **One laptop, interpreted runtimes.** Throughput depends on the machine. State is per process: a multi-host deployment needs the same rule of one writer per envelope.
- **The risk model does not scale past about 25,000 agents per scorer.** Its feature engine rebuilds an internal map of co-trading agents on every order once that map holds more than 400,000 entries. With half of the 100,000-agent swarm in one scorer the map reached 513,431 entries, and scoring slowed from about 120 µs to 68,761 µs per order. With 12,500 agents per scorer it stays at 110-130 µs. The fix belongs in `orderguard_risk/features.py`, which is outside this bench's scope. Until then, run one scorer per shard of at most about 25,000 agents. Sharding changes the model's view of cross-envelope flow, so its decisions depend on the shard layout. The gate's decisions do not.
- **The risk model holds more honest orders here than on its own test data**: 2.8% of the honest orders the gate allowed, against 0.26% on its held-out seeds. The bench's population differs from training: many smaller envelopes, real crypto prices, and system traffic in the same stream. Review load should be estimated on your own flow.
- **The full profile is partial.** Its four gate runs (1.09M orders each) completed and were audited. The run was stopped when the single-scorer risk run hit the scaling problem above. The full profile now runs the risk model at 8 processes. Its receiver, race and crash numbers come from the quick profile, which completed in full.
- **"Durable" means process-crash safe.** SQLite on macOS calls `fsync`, which does not force the drive's cache to disk. The kill test proves survival of a process crash, not of power loss.
- **The HTTP bridge benchmark did not run here.** The sandbox forbids binding a local port. Run `.venv/bin/og-bench http --profile quick` on a normal machine; it writes `results/bench/http.json` and adds it to the report.
- **Workloads are open-loop.** Agents never react to refusals. The economics do not re-simulate the budget a refused colluder would have freed.

---

## Appendix A: how the bench works

**Workload.** Each owner has their own Ed25519 key and signs three envelopes (core, tactical, crypto), sized for the agents that share them. Every second owner also signs portfolio limits. The agents come from `orderguard_arena.agents.make_population`, unchanged, at the arena's default failure rates. Colluding groups are split into naive, stealth, and white-box adaptive variants; the white-box parameters come from `results/risk/adversary.json`. System traffic: 3% of orders are retried 1-20 steps later, 1% are delivered twice back to back, and 0.5% have their key reused for a different order. Every tenth owner gets a burst, limit probes, and a revoke/replay/forge sequence. The workload is generated once into eight owner partitions, open-loop. Event order is a global key, so every envelope sees the same sequence however the owners are sharded.

**Sharding.** A process owns whole owners: their envelopes, budgets, portfolio state, idempotency records, and the agents pinned to them. Nothing mutable is shared between processes; market data is read-only and copied. Throughput is total decisions divided by wall time, from a common start barrier to the last worker's finish. Per-stage latency comes from a separate pass in which each stage's real function is wrapped by a timer:

| Python stage (quick, µs) | p50 | p99 | p99.9 |
|---|---|---|---|
| mandate signature verify (on load, not per order) | 89 | 149 | 176 |
| idempotency and routing | 8.3 | 30 | 87 |
| gate rules | 1.9 | 5.2 | 28 |
| portfolio limits | 7.6 | 26 | 111 |
| reservation | 2.2 | 5.8 | 54 |
| order-risk score | 51 | 157 | 535 |
| decision-log append (SHA-256) | 7.2 | 39 | 329 |

| receiver stage (quick, µs) | throw-away p50 / p99 | durable p50 / p99 |
|---|---|---|
| budget query | 2.8 / 5.6 | 3.0 / 12 |
| portfolio queries | 2.3 / 4.7 | 2.5 / 6.5 |
| insert and hash chain | 10 / 20 | 9.8 / 30 |
| whole commit transaction | 33 / 90 | 98 / 1,638 |

Verify-on-open re-hashes a ledger at about 8 µs per event.

**The auditor** (`python/orderguard_bench/auditor.py`) recomputes:

- the log's hash chain, and the receiver's event chain using the receiver's formula reimplemented in Python;
- every mandate signature, over its own canonical JSON;
- the trusted price, as the venue median, and notional in integer cents;
- every cap, at the moment of each decision;
- idempotency (one effect per key, replays identical, conflicts refused);
- revocation and forged mandates;
- news-trigger confirmation (at least two independent origins);
- every allow and hold, through `OrderGate`.

For receiver ledgers, which it opens read-only, it also checks that every acknowledged effect is present. Refusals that the gate would have allowed are reported separately: they cost availability, not safety.

**Races and crashes.** `receiver/bench/race-worker.ts` opens K receivers in K processes on one SQLite file. They fire at the same instant, and only SQLite's `BEGIN IMMEDIATE` serialises them; the production bridge's single-writer lock is bypassed on purpose. `receiver/bench/fault-child.ts` is the kill/restart driver. Python thread races use 8-32 threads on one envelope.

**Files.** `python/orderguard_bench/` (generation, engine, auditor, economics, races, receiver driver, report, `og-bench`). `receiver/bench/` (`inprocess.ts`, `race-worker.ts`, `fault-child.ts`, `growth.ts`, `http.mjs`, `run.mjs` for `npm run bench`). `python/tests/bench/`. Results: `results/bench/quick.json`, `full-partial.json`, `summary.json`, `report.html`.

## Appendix B: two defects found and fixed

1. **A replayed signed mandate reset its envelope** (`orderguard_arena/envelopes.py`). Adding an already-loaded mandate again replaced it with a fresh envelope: the daily budget went back to zero, and a revoked envelope came back live. `EnvelopeBook.add` now returns the envelope already loaded, with its state. The arena suites pass, and `og-arena verify` regenerates every committed arena result byte-for-byte (97/97).
2. **The receiver's commit got slower as its ledger grew** (`receiver/core/receiver-core.ts`). Every commit scanned the whole orders table several times. On this machine the median `propose()` time rose from 0.53 ms to 5.95 ms over the first 16,000 orders of a day, and to 12.7 ms with portfolio limits. The fix has three parts:
   - prepared statements are cached;
   - an index on `orders(day)` is created, only after the ledger verifies;
   - the day's totals and every symbol's position are kept in memory, valid only while the ledger head (the newest event's seq and hash) is unchanged. Every write appends an event, so any change, from this or another process or by a rollback, forces a recompute.

   Median latency is now flat at about 41 µs up to 16,000 rows. Before and after, on a fixed 23,899-order workload over 40 envelopes, the decision digest and every ledger's event chain and order table are byte-identical. The receiver's TypeScript tests (52) and its 1,000-seed invariants campaign, with both mutation checks, pass.
