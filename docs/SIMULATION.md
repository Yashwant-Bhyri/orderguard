# Impact-aware market simulation

## The question

The original arena replays orders against prices that do not move when agents trade. This simulator asks what changes when many agents react to the same headline or price move, their fills move prices, and those prices feed back into later orders. It is product evidence about mandate behavior in a stylized market, not a forecast of an exchange.

## Setup

`python/orderguard_sim/` stores agent attributes and positions in NumPy arrays. It materializes only active orders, but every materialized order goes through `orderguard_arena.authority.Authority.authorize()` individually. Every guarded arm uses the real Authority and a signed envelope with a shared daily budget. The portfolio arm adds signed per-symbol and position caps. In the `full` arm, the shipped `RiskScorer` scores each fresh gate-allowed order and `tighten()` combines the result; it cannot turn a refusal into an approval. The unguarded comparison uses a signed, deliberately wide-open envelope, so the Authority remains the code deciding the order.

An envelope is shared by about 1,000 agents. A 10,000-agent run uses 10 envelopes; a 1,000,000-agent run uses 1,000. Each agent samples from a four-symbol basket, allowing positions to build across names. The collusion scenario moves a synchronized ring across three correlated names.

Only authorized signed dollar flow is netted by symbol for the market update. Order validation, daily reservations, portfolio checks, risk scoring and the audit remain per order. This flow aggregation is exact for this model because impact is applied once at the end of a step as a function of net flow. It does not approximate or combine mandate decisions. A test compares the aggregated update with sequential order accumulation to 1e-12 relative tolerance. Spread counts exclude the initially shocked symbol and count names whose cumulative return exceeds two baseline standard deviations in the shock direction. Half-life is the first step after the peak when that count falls to at most half the peak. Honest loss is the negative part of aggregate final PnL for the five honest strategy archetypes.

### Market parameters and sources

| Parameter | Value | Source and use |
|---|---:|---|
| Initial price | $250 equities; $100 crypto | Simulation starting scales; prices have no effect on return calibration. |
| Equity one-step volatility | 0.15% | Stylized fallback for symbols absent from the recording. |
| Crypto one-step volatility | 0.30% fallback | Stylized fallback. For BTC, ETH and SOL the included recording supplies realized volatility instead. |
| Recorded volatility | Sample standard deviation of log returns, scaled by `sqrt(simulated step seconds)`, then clipped at 0.8% | 144 one-second Binance public ticks from [the committed recording](../data/arena/feeds/binance-public-20261111T000117Z.jsonl). BTC, ETH and SOL realized one-second volatility is about 0.004%, 0.004% and 0.009%; the short sample is only a seed. |
| Equity correlation | 0.30 common-factor prior | Stylized factor-model prior for missing pairs. |
| Cross-sleeve correlation | 0.12 | Stylized prior between equities and crypto. |
| Recorded correlations | 75% empirical estimate + 25% prior | Used for symbols that overlap the recording; the matrix is projected to a positive semidefinite correlation matrix. |
| ADV | $50m equities; $150m crypto | Explicit stylized daily-liquidity assumptions, not measured exchange volume. |
| Impact coefficient `eta` | 1.0 | Model choice. Per-step log impact is `eta * sigma * sign(Q) * sqrt(abs(Q)/ADV)`. |
| Impact decay | 0.82 per step | Model choice; an isolated impact impulse halves in about 3.5 steps. |
| Return tails | Student-t, 5 degrees of freedom | Stylized heavy-tailed innovation. |
| Volatility persistence | GARCH `alpha=0.08`, `beta=0.90`, `omega=0.02` | Stylized clustering process; it has no drift term. |
| Order-flow execution slippage | 1 bp floor plus the same square-root impact curve | Model choice; measured slippage includes the spread floor and impact. |

The recorded file spans only 144 ticks and has no large crash. Therefore `real_crash` is a seeded, 8% down shock with three independent confirming news origins; it is not a replay of a historical crash. The separate stale-feed case injects an 8% repricing that Venue C misses for eight steps. Venue A and B remain current, so the trusted median is current.

### Mandates and risk arms

The default per-order cap is $25,000. The shared daily cap is `max(2 * per_order, agents_per_envelope * activity * steps * $4,000 * 0.7)`. The base portfolio limits are 60% of daily cap per symbol and 80% per position, each floored at the per-order cap. The price band is 2.5%; there is no step-up threshold in this experiment. Signed limits are varied together for the sizing frontier. The generated values are per envelope, not per agent.

The arms are: a wide-open signed-envelope control; signed gate only; gate plus signed per-symbol and position limits; and full (gate, portfolio limits, plus the shipped risk scorer). Frontier candidates run the full path with tight (0.65x per-order, 0.55x daily), loose (1.6x per-order, 1.8x daily), and open-capacity (2x per-order, 6x daily) sizing. Symbol and position limits scale with daily cap. The candidate names and exact signed limits are in each result JSON.

## Answers from the quick runs

Unless a row says otherwise, metrics below are means across seeds 7, 8 and 9, with 10,000 agents, 64 steps and 10 shared envelopes. The quick run completed in seconds on the development machine. Every guarded arm, including the frontier candidates, had zero independently audited cap breaches.

### 1. Tremors

| Scenario | Unguarded | Gate only | Full |
|---|---:|---:|---:|
| Fake headline: fake-news dollars executed | $417,520 in seed 7 | $0; all 74 trigger orders held by L7 | $0 |
| Fake headline: non-target symbols beyond 2σ | 0 | 0 | 0 |
| Confirmed 8% crash: bad dollars executed | $110,932 | $12,013 | $6,163 |
| Confirmed crash: non-target symbols beyond 2σ at peak | 2.7 | 2.7 | 2.7 |
| Confirmed crash: contagion half-life | 2.7 steps | 2.0 steps | 2.0 steps |
| Three-name collusion ring: bad dollars executed | $6.08m | $365k | $58.8k |
| Three-name ring: non-target symbols beyond 2σ at peak | 0.3 | 0 | 0 |

The price shock itself still moves correlated names: limits do not undo an exogenous market move. They contain agent-driven follow-on flow and losses. Mean honest-cohort loss in the crash run was $101 unguarded, $0 gate only and $176 full; the risk layer reduced bad flow but did not improve every honest-PnL measure in this small sample. On the ring, the gate alone reduces bad executed dollars by 94% against the wide-open arm; adding the risk scorer reduces the gate-only remainder by a further 84%. In seed 7, the gate allowed 20 of 322 collusion orders, while full allowed 3, held 16 and refused 303. The four-symbol baskets create cross-holdings; the portfolio cap checks the envelope's net position across those fills, not just one agent's order.

In the stale-venue seed-7 run, the wide-open arm filled all 1,139 stale-price proposals. Gate only refused 1,088 and allowed 51 that remained inside the mandate. Across the whole run, the refusal log recorded 927 daily-cap, 300 band and 3 per-order refusals. Full held four more stale-labeled orders that had passed the gate. This shows why one stale venue must not set the authority's sizing price.

### 2. Crowding

The crowded-momentum scenario deliberately raises the momentum cohort's participation after a +5% impulse. The daily cap is sized to ordinary activity, so it binds hard during this stress.

| Arm | Honest fills lost vs wide-open | Slippage | Honest-cohort loss | Worst portfolio drawdown |
|---|---:|---:|---:|---:|
| Wide-open signed envelope | 0% | $3,932 | $124,083 | $546,455 |
| Gate only | 95.1% | $131 | $25,430 | $95,493 |
| Gate + portfolio limits | 95.1% | $126 | $18,599 | $77,195 |
| Full | 95.2% | $108 | $15,682 | $62,805 |

Adding the per-symbol and position limits to the gate cuts modeled slippage another 4% and worst drawdown 19%, with about 0.5% fewer honest fills than gate only. Most of the fill reduction comes from the shared daily cap: the desk-wide flow is far above the ordinary activity assumption. A desk that wants more honest capacity needs to sign a larger daily budget and accept the loss frontier below; tightening every cap is not a free safety improvement.

### 3. Mandates at scale

The crowded-momentum frontier makes the cost visible. Throughput is honest notional actually filled over the 64-step session; loss is the worst portfolio peak-to-trough drawdown over the three seeds.

| Full-path sizing | Per order | Daily / symbol / position caps per envelope | Honest filled | Worst drawdown |
|---|---:|---:|---:|---:|
| Tight | $16.3k | $49.3k / $27.1k / $32.0k | $395k | $20.2k |
| Base | $25k | $89.6k / $53.8k / $71.7k | $783k | $62.8k |
| Loose | $40k | $161.3k / $137.1k / $193.5k | $1.43m | $200.7k |
| Open capacity | $50k | $537.6k / $483.8k / $806.4k | $4.20m | $341.2k |
| Wide-open control | $1,000tn | No practical cap | $20.9m | $546.5k |

These are candidate points, not a universal recommendation. For this stress and this generated order rate, moving from base to open capacity buys 5.4x honest filled notional and raises worst drawdown 5.4x. A desk should choose a loss budget first, then use the frontier to select the loosest signed caps that remain within it. The daily cap is shared, so per-agent counts alone are a poor sizing rule: the activity rate, envelope sharing ratio, symbol concentration and positions determine the needed headroom.

### 4. One million agents, heavy profile

The `heavy` profile runs the fake-headline (tremor) scenario at **1,000,000 agents**, 1,000 signed envelopes, 64 steps and 3 seeds (99, 100, 101), through all seven arms: wide-open control, gate only, gate + portfolio, full, and the three sizing candidates. Ordinary activity is 1% of agents per step, so each arm materialised **616,500 orders on average (about 1.85 million per arm across the three seeds)**, and every one went through `Authority.authorize()` individually: 12,946,507 authority decisions in all. Compare the quick profile's roughly 600 orders per arm.

| Arm (mean of 3 seeds, 616,500 orders each) | Bad dollars executed | Honest fills lost vs wide-open | Symbols over 2 sigma | Half-life | Worst drawdown | Independent-auditor breaches |
|---|---:|---:|---:|---:|---:|---:|
| Wide-open signed envelope | $268.9m | 0% | 14 | none | $452.6k | 0 |
| Gate only | $37.9m | 41.4% | 12 | 21 steps | $1.80m | 0 |
| Gate + portfolio limits | $37.9m | 41.4% | 12 | 21 steps | $1.80m | 0 |
| Full | $6.2m | 54.4% | 9 | 7 steps | $1.14m | 0 |

What the larger sample says: at this scale the full path cuts executed bad flow by 97.7% against the wide-open control and gate only by 85.9%; the full path shortens the contagion half-life from 21 to 7 steps and the spread from 14 to 9 symbols. The portfolio limits do not bind in this scenario, so gate-only and gate + portfolio decide identically. Gate-only and the full path show a larger worst mark-to-market drawdown than the control ($1.80m and $1.14m against $453k) (mark-to-market equity of the filled flow, which the guarded arms still build in the shocked direction); the full path cuts that drawdown 37% relative to gate only; the honest cost is the 54.4% of honest fills held back.

Scale of the run: 1,000,000 agents, 616,500 materialised orders per arm, 3 seeds, 7 arms, 12.9 million authority decisions and 12.9 million audited order-log rows (0 breaches, auditor replaying per-order, daily, per-symbol and position caps from the raw decision logs). It ran on one laptop with 6 worker processes in 5,341 s (89 minutes), an aggregate of **2,424 decisions/s**; the machine was shared and memory-constrained during the run, and a quiet single process sustained about 10,000 full-path and 45,000 wide-open decisions/s in a short trial. Worker count changes only wall time: digests are identical for any `--workers` value (tested). See [the result](../results/sim/fake_headline-k1000000-s99.json). The 12.9 million-row logs are audited from scratch copies and not committed; each arm's digest is in the result so a rerun can be compared byte for byte.

Crowding, collusion, real-crash and stale-feed runs at this scale are a matter of compute: the same command with `--scenario crowded_momentum` (and so on) writes `results/sim/<scenario>-k1000000-s99.json`, and the quick-profile tables above remain the evidence for those scenarios until those runs are added.

## Limits and reproduction

This is a stylized, synchronous model with no order book, auction, venue routing, queue position, market-hours calendar, borrow constraints or strategic market makers outside the simulated swarm. Per-step prices move after the active orders have been authorized, so the model does not resolve within-step matching. The 144-tick recorded sample is too short to estimate robust covariance or ADV. The 8% crash and stale venue are scenario inputs, not historical observations. The agent strategies and failure rates are synthetic, and the risk layer is evaluated on behavior close to the families it was trained to recognize.

Run the fast profile offline (no model APIs or network):

```bash
og-sim run --scenario all --profile quick --seed 7
og-sim report
```

Longer runs are marked slow and can take minutes. The heavy profile (1,000,000 agents, 64 steps, 3 seeds, 1% activity per step, attack activity 6%) materialises over 600,000 orders per arm; it takes about 90 minutes per scenario on a shared laptop with `--workers 6` and far less on an idle multi-core machine. Logs are audited from scratch copies unless `--log-dir` is given:

```bash
og-sim run --scenario fake_headline --profile heavy --seed 99 --workers 6
```

The slow profile:

```bash
og-sim run --scenario collusion_ring --profile slow --agents 1000000 --steps 256 --seed 99 --replicates 3
```

Results are in [`results/sim/`](../results/sim/), with the self-contained [offline HTML report](../results/sim/report.html). The simulator uses the real OrderGuard Authority as the only path to an allow; risk can only tighten it.
