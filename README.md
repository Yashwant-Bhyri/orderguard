# OrderGuard

**A thousand AI agents. One signed mandate. Nothing outside it reaches the market.**

One person signs the limits; hundreds or thousands of AI agents trade under them and share one daily budget. The costly orders often break no rule on their own: a position split across agents into slices just under the cap, a runaway loop of small legal orders, a colluding group draining the budget honest agents need. OrderGuard sits between the agents and the money: code enforces the signed limits at a trusted price, a risk model catches the bad flow that fits them, and people review only the orders most likely to cost money.

## What it does

- **A mandate a human signs, enforced by code.** Symbols, sides, per-order and daily caps, a price band and a "get a human above this size" threshold, signed with the owner's key. Every order is sized at a trusted market price, never at the price the agent claims. No model can loosen it.
- **A risk model for the orders that fit the limits.** A behavioural model scores every allowed order across the whole swarm, the way a card network scores payments: one position split across agents, bursts, runaway loops, sudden jumps in size. It can turn an allow into a hold or a refusal, never the other way, so a wrong model costs some honest flow but cannot authorise anything.
- **A review lane that spends people's time where it matters.** Held orders queue by expected bad dollars. A calibrated decision model adds its estimate to the ranking and can add a hold; it cannot approve.
- **Shared budgets, portfolio limits and policy packs.** One daily budget per signed envelope, shared atomically by every agent that draws on it, plus optional caps per symbol, position and day. Four ready-made packs give a desk a starting point to sign, and the envelope lab replays recorded traffic through candidate limits so a desk sees what each would refuse, hold and let through before signing.
- **Screening of what agents read.** Agents can be fooled too: a forged split notice, a hidden instruction, a planted rumour. Hidden characters, look-alike tickers and manipulative text are caught before the agent sees them; figures an order cites are checked against SEC filings; a "sell if it crashes" rule fires only when two independent sources agree.

```mermaid
flowchart LR
  A["AI agents<br/>any model, any tools"] -->|"news, feeds, pages"| S["Screen inputs"]
  S --> A
  A -->|"proposed order"| G["Mandate check<br/>signed limits, trusted price"]
  G -->|"refuse, with reasons"| X["Refused"]
  G -->|"allow"| R["Risk model<br/>across the swarm,<br/>can only tighten"]
  R -->|"allow"| L[("Ledger<br/>receiver")]
  G -->|"hold"| H["Human review<br/>ranked by expected bad $"]
  R -->|"hold"| H
```

Every refusal and hold comes with plain-language reasons, for example: "440 shares at the trusted $222.70 is $97,988, over the $10,000 per-order cap."

## Proof

All runs are simulated (paper ledgers, synthetic or recorded market data). Each number below is rebuilt from the committed results by `og-arena verify`; the full tables and caveats are in [docs/EVIDENCE.md](docs/EVIDENCE.md).

- **Attacks blocked.** With a live model agent behind OrderGuard, **0 of 180** attack goals were achieved, against 7 of 180 for the bare model. [Runs](results/runs/20261110T230149.jsonl) · [Report](docs/RESULTS.md)
- **Honest work preserved.** In the seeded sandbox, guarded agents completed **132 of 138** honest tasks, against 113 of 138 for the bare model. [Runs](results/sweeps/20261110T230155.jsonl)
- **Swarm-scale bad flow stopped.** In a 1,000-agent run, the mandate check alone let through **$7.97M** of bad orders that each fit the signed limits, most of it from one colluding group. The risk layer held or refused all of it, sending **0.11%** of honest orders to a human. [Replay](results/risk/arena-replay-arena-s7-k1000-t2000.json)
- **Fast enough for the order path.** **58,314 decisions/s** on the strict path and **9.25 µs p99** inline, for 1,000 agents in one process. [Benchmark](results/arena/bench.json)
- **Holds at exchange scale.** 100,000 agents, 1,200 signed mandates and 1.09M orders: an independent auditor, rebuilding every limit from the raw logs, found **0 cap breaches** and **0 double executions**, with identical decisions on 1 to 8 processes and **140,302 decisions/s** on one laptop. It also caught **7 of 7** deliberately broken builds. [Bench](docs/BENCH.md) · [Report](results/bench/report.html)
- **Humans review what matters first.** On a queue of 1,002 flagged orders, ranking by expected bad dollars reaches 90% of them in **470** reviews instead of **719** first-in-first-out. Model advice in this lane can add a hold, never approve. [Review lane](docs/REVIEW.md)
- **AI attackers that read the docs.** Adaptive DeepSeek and Qwen attackers, given the threat model, tried every channel from fake news to receiver replays: **0 hard breaches** in 334 usable rounds (95% upper bound 1.1% per round) out of 336 planned (2 produced no usable attack). Measured at a small attacker budget (two low-cost models); stronger and longer-running attackers are a matter of budget, and the full per-family results are in the report. [Red team](docs/REDTEAM.md)

## Watch it

The Swarm Theater is a 90-second guided replay of one recorded run: 1,000 agents, an attack, the guard, the human queue and the proof, every number linked to its file.

```bash
.venv/bin/orderguard serve        # then open http://127.0.0.1:8600/theater
```

## Try it in 2 minutes

Needs Python 3.11+ and Node 22.13+. No API key: everything runs offline from recordings.

```bash
sh scripts/quickstart.sh          # venv, install, signing key and mandate, doctor, offline tests, dashboard on :8600
```

Then sign a policy pack as your mandate and check the setup:

```bash
.venv/bin/orderguard policy list
.venv/bin/orderguard policy sign balanced-equities --key var/orderguard/signing.key --out var/orderguard/mandate.json
.venv/bin/orderguard doctor --dir var/orderguard
```

In the dashboard, open **Check order** and try "Fake 10-for-1 split" to see an order refused at the trusted price. Packs and their limits: [policies/](policies/README.md).

## Integrate it

| Surface | Use it for | Start here |
|---|---|---|
| **Quickstart** | Clone to a refused order in Python, HTTP, Node or MCP, offline, in minutes | [docs/QUICKSTART.md](docs/QUICKSTART.md) |
| HTTP API | Check an order or screen text from any stack | `orderguard serve`, then `POST /api/check-order` · [API](docs/API.md) |
| MCP server | Give any MCP client (Claude, other agent frameworks) guarded tools | `python -m orderguard_mcp` · [MCP](docs/MCP.md) |
| Python | Wrap your own agent loop | `orderguard_guard.agent.run_agent(...)` · [Guide](docs/GUIDE.md#integrating-your-own-agent) |
| Receiver and Node SDK | The final authority before the ledger: re-checks the signed mandate, keeps a hash-chained paper ledger | `node receiver/bridge/serve.mjs`, `packages/sdk` · [Operations](docs/OPERATIONS.md) |

Whichever surface you use, give the agent no money-movement tool and make the receiver the only path to the ledger.

## Scope of this release

- **Venues and ledgers.** This release runs against simulated markets, recorded public market data and paper ledgers. Connecting a live venue is an adapter on top of the receiver, which is already the single path to the ledger.
- **Scale of the evidence.** Every result here was produced on one laptop with a small model budget: live model trials used one low-cost model family, the red-team campaign ran all 336 planned rounds with two cheap attacker models, and the heaviest million-agent simulation materialised 616,500 orders per arm (3 seeds, 12.9 million authority decisions) for one scenario; the other scenarios run at 10,000 agents. Each document states its sample sizes; larger runs are a matter of compute and budget, and every runner takes the scale as a parameter.
- **No affiliation.** OrderGuard has no affiliation with any brokerage or exchange.

## Learn more

- [Product brief](docs/PRODUCT.md): who it is for, rollout, FAQ
- [Documentation index](docs/README.md): guides for product, integrators and reviewers
- [Evidence](docs/EVIDENCE.md), [Bench](docs/BENCH.md), [Red team](docs/REDTEAM.md), [Architecture](docs/ARCHITECTURE.md)
- [Impact-aware market simulation](docs/SIMULATION.md): mandates, crowding, correlated shocks and the sizing frontier at one million agents
- [Release notes](RELEASE.md)
- Everything a reviewer needs, offline, in one command: `scripts/check_all.sh` ([Testing](docs/TESTING.md))

MIT licence. See [LICENSE](LICENSE).
