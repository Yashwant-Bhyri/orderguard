# OrderGuard v1.0

**Let AI agents trade, inside limits a human signed and code enforces.**

v1.0 is the first release packaged for people outside the project: product teams at exchanges and brokers, and engineers who want to put their own agents behind a guard. It is a working prototype on paper ledgers.

## What's in it

**The guard**
- **Signed mandates enforced in code.** Symbols, sides, per-order and daily caps, a price band and a human step-up threshold, signed with Ed25519. Orders are sized at a trusted price, never the agent's own. Any edit after signing invalidates the mandate.
- **Portfolio limits.** Optional signed caps per symbol per day, per net position and on orders per day, enforced by the gate, the arena and the receiver alike. A draft can never loosen a limit its parent has.
- **Policy packs.** Four unsigned templates (`conservative-equities`, `balanced-equities`, `active-equities`, `crypto-sleeve`) and `orderguard policy sign`, which refuses a template that contradicts itself.
- **Input screening and fact checks.** Hidden characters and look-alike tickers exposed in code, an optional model screen for manipulative text, cited figures checked against SEC filings as of the decision date, and standing rules that need two independent sources.
- **Order-risk layer.** Programmed and learned weights score every allowed order for swarm behaviour (splitting, bursts, runaway loops). It can only tighten a decision, never loosen one.
- **Review lane.** Held orders ranked for a human by expected bad dollars, plus a mandate-draft copilot and an intent check. Model advice can add a warning or a hold; it can never approve, release or sign.
- **Receiver.** A TypeScript service that re-checks the signed mandate at commit time, with idempotency, revocation and a hash-chained paper ledger.

**Ways to see and use it**
- **Swarm Theater** at `/theater`: a 90-second guided replay of a recorded 1,000-agent run, every number linked to its source file.
- **Dashboard**: check an order, screen text, test standing rules, run scenarios, run a swarm arena and review a mandate draft.
- **Integration**: HTTP API, MCP server, Python `run_agent`, receiver bridge and Node SDK.
- **Envelope lab**: replay recorded traffic through candidate limits before anyone signs them.

**Evidence you can rerun**
- The headline numbers are in the [README](README.md#proof) and in detail in [docs/EVIDENCE.md](docs/EVIDENCE.md). `og-arena verify --quick` checks that every number quoted in the README, the docs and the dashboard home matches the committed result files; `og-arena verify` also regenerates the arena results from their seeds.
- Scale and red-team results: [docs/BENCH.md](docs/BENCH.md) and [docs/REDTEAM.md](docs/REDTEAM.md).

## Try it

```bash
sh scripts/quickstart.sh                 # needs Python 3.11+ and Node 22.13+; no API key
# then open http://127.0.0.1:8600/theater
.venv/bin/orderguard policy sign balanced-equities --key var/orderguard/signing.key --out var/orderguard/mandate.json
.venv/bin/orderguard doctor --dir var/orderguard
```

Everything runs offline from recordings by default. Live model calls need a provider key and a spend cap (`OG_BUDGET_USD`); see [docs/GUIDE.md](docs/GUIDE.md#configure-keys).

## Known limits

- Simulated markets, simulated fills, synthetic agents and paper ledgers. No real broker adapter ships, and nothing here is evidence about real-money performance.
- Live model trials cover one model family with few repeats. The attacks were written by the people who built the defences.
- A harmful order that fits a signed mandate is allowed by the mandate check. The risk layer and portfolio limits narrow that gap but do not close it; the risk model's weakest family is compromised agents.
- There is no single shadow-mode switch; shadow running means calling the check endpoint and logging the verdict ([docs/PRODUCT.md](docs/PRODUCT.md#how-a-desk-would-roll-it-out)).
- The dashboard binds to localhost by default. Exposing it needs `ORDERGUARD_APP_TOKEN` and a TLS proxy.
- The Swarm Theater has not been tested with a screen reader.
- OrderGuard has no affiliation with any brokerage or exchange.

## GitHub repo settings

For the owner to apply by hand under the repository's About settings.

- **Description:** Pre-trade guard for AI trading agents: a human-signed mandate enforced in code at trusted prices, with input screening, a tighten-only risk layer and a human review lane. Prototype on paper ledgers.
- **Topics:** `ai-agents`, `ai-safety`, `trading`, `pre-trade-risk`, `risk-management`, `prompt-injection`, `llm-security`, `mcp`, `fintech`, `agent-swarms`
- **Website:** leave empty until there is a hosted demo.
