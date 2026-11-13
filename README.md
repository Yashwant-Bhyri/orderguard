# OrderGuard

**AI trading agents will believe fake information. OrderGuard decides what they may do using numbers they can't touch, checks the facts their orders rely on, and holds a whole swarm of agents inside the envelope a human signed.**

OrderGuard is a pre-trade authorisation layer that sits between AI agents (any model, any tools) and the ledger. Refusals and holds include plain-language reasons. The research prototype uses simulated fills and paper ledgers, with optional testnet and simulated broker adapters. OrderGuard has no affiliation with any brokerage or exchange.

## What the evidence shows

The fixed-case live comparisons below use DeepSeek V4.1 Flash 1017. The separate sandbox rows use scripted agents in simulation. The report also covers an earlier Flash variant, other scripted controls and detector experiments. [Results report](docs/RESULTS.md) · [Fixed-case runs](results/runs/20261110T230149.jsonl) · [Sandbox runs](results/sweeps/20261110T230155.jsonl)

| Simulated outcomes | Bare model | Full guard |
|---|---|---|
| Attack goals achieved (families A–D) | 7 of 180 | **0 of 180** |
| Attacker actions executed (same A–D trials) | 0 of 180 | 0 of 180 |
| Planted claims repeated without a matching doubt term (belief-targeted A–D trials) | 7 of 48 | **0 of 48** |
| Legitimate trades dropped (family E denial-of-service trials) | 15 of 21 | **1 of 21** |
| Clean controls completed | 17 of 20 | 18 of 21 |
| Sandbox attack goals achieved (22 techniques × 6 seeds) | 14 of 130 evaluable trials, $9,762.50 executed notional | **0 of 132**, $0 executed notional |
| Sandbox benign-twin tasks completed | 113 of 138 | **132 of 138** |

One bare-model clean control and two bare-model sandbox attack trials ended in errors. Benign-twin utility includes six natural-error scenarios and correct abstention in 18 trigger scenarios per arm. [Clean-control and sandbox breakdowns](docs/RESULTS.md)

- An adaptive attacker recorded **0 observed successes** across five goals with up to five rounds each. One campaign stopped after two evaluated rounds when the attacker produced unusable output. [Adaptive runs](results/adaptive/20261110T232836.jsonl)
- In the 1,000-agent synthetic benchmark, the strict path processed **58,314 decisions/s** on a 5,000-proposal sample. The inline path had a **9.25 µs p99**, and the end-to-end run processed **28,771 proposals/s**. [Benchmark results](results/arena/bench.json)
- In a one-envelope, one-day paper-ledger check at shared static prices, **2,372 of 2,372** eligible decisions agreed with the TypeScript receiver. [L8 comparison](results/arena/l8-agreement-s23-k1000.txt)

## How it works

```
agent tool output → L1 normalise → L2 model screen → L3 risk bucket → L4 data marking
agent order       → L5 order gate (signed mandate, trusted price) → L6 figure check (SEC filings)
standing rules    → L7 trigger graph (≥ 2 independent sources, blast radius)
allowed order     → TypeScript L8 receiver when configured, otherwise local paper ledger
```

- **Code decides about money.** The order gate sizes every order at the *trusted* price, never the agent's own limit price, against an Ed25519-signed mandate with caps, a price band, an allow-list and a step-up threshold. The gate enforces the signed limits even when a model is fooled. Harmful orders can still fit inside a signed mandate.
- **Facts are checked, not believed.** Figures an order cites are checked against SEC EDGAR as of the decision date: confirmed, contradicted, stale, not public yet or unverifiable. Guarded agents can look figures up from the same trusted source.
- **Inputs are cleaned and screened.** Hidden Unicode, look-alike tickers and encoded payloads are exposed in code; a model screen quarantines manipulative text; repeats of a quarantined claim are quarantined too.
- **Standing rules need corroboration.** A "sell if it crashes" rule fires only when at least two independent, unquarantined sources agree.
- **The receiver enforces the mandate at commit time.** Its invariant campaign checks five properties over 1,000 fault seeds and checks two intentionally weakened configurations. [Receiver campaign](receiver/invariants/run.ts)

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Threat model: [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md).

## Use it

Install from a clone (the code reads its data, recordings and model files from the checkout):

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && npm ci
```

Or let the quickstart do everything (checks Python 3.11+ and Node 22, installs, creates a signed mandate, runs the offline tests, starts the app):

```bash
sh scripts/quickstart.sh
```

| surface | how | docs |
|---|---|---|
| **Dashboard** | `orderguard serve`, then open http://127.0.0.1:8600 | [APP](docs/APP.md), [design language](docs/DESIGN.md) |
| **HTTP API** | the same server; bearer token whenever `ORDERGUARD_APP_TOKEN` is set | [API](docs/API.md) |
| **MCP server** | `orderguard-mcp` (stdio): any MCP client can screen text, check orders and figures, evaluate rules, and submit only through the guard | [MCP](docs/MCP.md) |
| **Swarm arena** | `og-arena run`, `og-arena policy`, `og-arena frontier`, `og-arena replay --feed …` | [ARENA](docs/ARENA.md) |
| **Agents in Python** | `orderguard_guard.agent.run_agent(...)` with any OpenAI-style model | [GUIDE](docs/GUIDE.md) |
| **Containers** | Publish the signed policy files, then run `docker compose up --build` | [Container setup](docs/OPERATIONS.md#install) |

Create your own signing key and mandate, then check the setup (secrets are never printed):

```bash
.venv/bin/orderguard init --dir var/orderguard
```

```bash
.venv/bin/orderguard doctor --dir var/orderguard
```

Recorded scenarios replay offline. A new model request needs a matching recording or live access. Live calls default to DeepSeek V4.1 Flash 1017 through the direct DeepSeek API. Put `DEEPSEEK_API_KEY` in the environment (or set `OG_ENV_FILE` to a protected dotenv file containing it), set `OG_LLM=record` and a small `OG_BUDGET_USD`, and run `og-lab estimate` first. Every process enforces a spend cap and refuses calls when the available balance is too close to the configured floor.

## Agent swarms and the envelope lab

One person signs a few envelopes; hundreds or thousands of agents trade inside them. The arena ([docs/ARENA.md](docs/ARENA.md)) runs such a swarm against synthetic or recorded real market data (a public Binance feed is included) and authorises every proposal in code.

- **Mandate review** checks an unsigned draft against the signed parent and compares both policies in the same paper market. The preview can warn that a draft is likely to exceed a risk limit in a supported synthetic scenario. [Mandate review walkthrough](docs/ARENA.md#review-a-draft-against-a-signed-policy)
- In the seeded 1,000-agent run, the arena authorized zero transfers, off-list or look-alike symbols, fake-reference oversize orders, stale-limit proposals or uncorroborated news orders. It held 163 uncorroborated news proposals. [Arena baseline](results/arena/arena-s7-k1000-t2000.summary.json)
- The baseline authorized $7.97M of bad notional, including $7.43M from one colluding group. The daily cap accounted for 1,068 of the 1,158 legitimate refusals. A separate run with the same seed and a 1% per-agent share authorized $0.91M of bad notional and refused 2.36% of legitimate proposals. [Baseline event log](results/arena/arena-s7-k1000-t2000.jsonl) · [Fair-share run](results/arena/arena-s7-k1000-t2000-fairshare.summary.json)
- **The envelope lab** replays the recorded proposals through hundreds of candidate envelopes. The recommended envelope would have authorized 95.9% of legitimate notional, leaked $219,347 per simulated day and refused 2.43% of legitimate proposals. The human reviews and signs the envelope. [Frontier](results/arena/arena-s7-k1000-t2000.frontier.json)

## The order-risk layer

Rules see one order at a time; coordination only shows across agents and time. `orderguard_risk` scores every order the gate allowed from 35 behavioural features: the order against its envelope, the agent's own baseline, cross-agent synchrony and size similarity, a co-occurrence graph of agents that trade together, and volatility. Features are point-in-time and cost O(1) per order. Gradient-boosted trees trained on 592,988 labelled proposals from 48 simulated swarms are exported to 0.15 MB of JSON and scored in pure Python (about 40 µs median). [Risk model](docs/RISK.md)

- **It can only tighten.** Allow can become hold (a human decides) or refuse. Nothing the signed mandate forbids can be allowed; a property test checks this over 5,000 random decisions.
- **On the baseline arena stream above,** inline replay held or refused all $7.97M of bad notional the gate allowed, and sent 0.40% of allowed honest orders to a human. On the recorded Binance-price stream: $5.03M to $0, 1.82% of honest orders. Budget a refused colluder would have freed is not re-simulated. [Replay](results/risk/arena-replay-arena-s7-k1000-t2000.json)
- **On held-out seeds,** 99.8% of bad dollars held or refused with 1.07% of honest orders held; above 99.7% under regime shift and time splits. **On adaptive colluders it never trained on: 94.0%, with 0.86% held.** [Evaluation](results/risk/eval.json)
- **Its limits are measured too.** Left out of training, fat-finger and stale-price mistakes are mostly missed (22.5% and 0%); those remain the code gate's job when they break a cap or the band.
- **One analyst label, no retraining.** `label_attack(event)` adds a prototype sized to capture at most 0.5% of recent unflagged flow. Over 10 random single labels, adaptive-colluder dollars caught in other runs rose from 93.6% to a median of 94.5% (range 93.6–99.5%). [One-shot trials](results/risk/oneshot.json)
- The shipped model uses no rationale text: the simulator writes rationales from each order's label, so text features would flatter the scores.

## Testing

- **Python:** unit, property and safety suites (thousands of generated mandates and orders against an independent oracle, Unicode fuzzing of L1, trigger-graph and broker invariants, the full attack corpus through scripted agents), end-to-end tests against the real receiver, MCP and API contract tests. Offline, under a minute.
- **Receiver:** TypeScript tests, the 1,000-seed invariants and mutation checks (`npm run check`).
- **Everything a reviewer needs, one command:** `scripts/check_all.sh`. See [docs/TESTING.md](docs/TESTING.md).

## Limits

- Simulated markets, simulated fills and synthetic agents. Nothing here is evidence about real-money performance.
- Live fixed-case trials cover two variants of one DeepSeek Flash family, with up to three repeats per case and arm. [Results and intervals](docs/RESULTS.md)
- The people who built the defences wrote the cases and techniques. The adaptive campaigns cover a small set of goals and rounds.
- The recorded earlier DeepSeek Flash detector flagged 35 of 52 false-data chunks in the lab. [Detector results](docs/RESULTS.md#detectors)
- The agent dropped a legitimate trade after a forged owner note in one of 21 DeepSeek Flash 1017 denial-of-service trials with the full guard. [Recorded run](results/runs/20261110T230149.jsonl#L649)
- On the mixed lab chunk set, the local classifier flagged 56 of 99 attacks and 9 of 174 clean chunks. The earlier DeepSeek Flash detector flagged 82 attacks and 4 clean chunks. The classifier ships off by default. [Classifier evaluation](docs/CLASSIFIER.md)
- Coordinated agents inside the envelope are only partly addressed (see above).

## Layout

`python/orderguard_guard` (L1–L5, L7, agent, classifier, broker router and adapters, `orderguard` CLI) · `python/orderguard_verify` (L6) · `python/orderguard_app` (API and dashboard) · `python/orderguard_mcp` (MCP server) · `python/orderguard_arena` (swarm arena, envelope lab) · `python/orderguard_risk` (order-risk model, `og-risk`) · `python/orderguard_lab` (attack lab, sandbox, `og-lab`) · `receiver/` (TypeScript L8 and bridge) · `packages/` (receiver SDK and MCP server) · `results/` (raw runs) · `docs/` ([index](docs/README.md)) · `lab/legacy` (earlier experiments).

## Licence

MIT. See [LICENSE](LICENSE).
