# OrderGuard

**AI trading agents will believe fake information. OrderGuard decides what they may do using numbers they can't touch, and checks the facts their orders rely on.**

It is a pre-trade authorisation and safety layer that sits between an analyst agent (any model, any tools) and the ledger. It's a research prototype and runs on simulated markets only: no real orders, no broker connection, no affiliation with any brokerage.

## Why it is built this way

Earlier attack-lab runs are kept in `lab/legacy/attack-lab-2026-11-06/README.md`:
- **Hidden instructions** fooled the agent in **1 of 107** runs.
- **Official-looking fake data** often fooled it: a fake 10-for-1 split, a fake "reference price" notice, a fake symbol change, a fake restatement.
- **Every harmful action** broke a rule that code can check against trusted data.
- **With no attacker at all,** the agent's first order cited a wrong figure in **13 of 112** runs.

So OrderGuard doesn't try to make the model un-foolable. It puts code-checked rules, run on trusted numbers, between the model and the money.

## Layers

```
agent tool output → L1 normalise → L2 model screen → L3 risk bucket → L4 data marking
agent order       → L5 order gate (signed mandate, trusted price) → L6 figure check (SEC filings)
standing rules    → L7 trigger graph (≥2 independent sources, blast radius)
                  → L8 receiver (TypeScript; atomic ledger, idempotency, revocation, human step-up)
```

| Layer | Code | What it guarantees |
|---|---|---|
| L1 | `python/orderguard_guard/normalise.py` | Strips zero-width and Unicode tag characters, flags mixed-script tickers (Cyrillic "АAPL"), applies NFKC and decodes base64 runs. |
| L2 / L3 | `screen.py`, `bucket.py` | A model screen quarantines flagged chunks and fails closed. Repeats of a quarantined claim are quarantined too. |
| L5 | `gate.py` | Ed25519-signed mandate with expiry and revocation. Allow-list, side, quantity × **trusted** price ≤ cap, daily total, price band, cited figures and step-up. |
| L6 | `python/orderguard_verify/api.py` | Each cited figure comes back confirmed, contradicted, stale, not public yet, or unverifiable, checked against SEC EDGAR as of the decision date. It catches quarterly-as-annual, wrong-year and split-adjusted EPS. |
| L7 | `graph.py` | A standing rule fires only when ≥2 independent, unquarantined sources agree (median across venues). Blast-radius simulation for a lying source. |
| L8 | `receiver/` | The final authority. Five guarantees are proved over 1,000 seeded fault runs, and two deliberately broken versions must be caught. |

Details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md) and [docs/CONTRACT-NOTES.md](docs/CONTRACT-NOTES.md).

## The sandbox

The attack lab has **83 named cases** in six families (A hidden instructions, including Chinese and Cantonese variants; B fake authority; C false facts; D feed and trigger; E denial of service; F natural errors), plus clean controls.

On top of those cases sits a **seeded world generator**. Each world contains:
- instruments, decoys and look-alikes;
- multi-venue quotes with a trusted median price;
- corporate actions and filings built from real SEC facts;
- news wires with independence groups;
- ranked web pages;
- the account, a signed mandate and standing rules.

Each of 23 techniques compiles into an attacked world plus a **benign twin**, so false refusals are measured rather than guessed. Harm is counted in **dollars at trusted prices**. See [docs/SANDBOX.md](docs/SANDBOX.md).

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
npm ci
```

Offline checks (no API key needed):

```bash
OG_LLM=replay .venv/bin/python -m pytest -q
```

```bash
npm run check
```

```bash
.venv/bin/orderguard demo --scripted
```

```bash
.venv/bin/og-lab sweep --seeds 50 --arms naive,gate_only,full
```

```bash
.venv/bin/og-lab tables --check
```

`npm run check` runs the receiver tests, the quickstart, the 1,000-seed invariants and a secret scan. The demo starts the receiver bridge, runs four scenarios plus the trigger graph, and prints the ledger snapshot.

Live runs use DeepSeek V4.1 Flash through OpenRouter:
- Set `OPENROUTER_API_KEY`, or `OG_ENV_FILE` pointing to a dotenv file.
- Set `OG_LLM=record` and raise `OG_BUDGET_USD`.
- Run `og-lab estimate` first. Every model call is recorded to `data/replay/` so tables rebuild offline. The client refuses calls when credit falls below US$0.30.

## Results so far

See [docs/RESULTS.md](docs/RESULTS.md), which `og-lab tables` rebuilds from `results/`.

**Offline results only.** The rows there come from scripted policy agents and a keyword screen. They test the code and the metrics, not model behaviour.

In the 50-seed offline sweep (1,150 attacked worlds × 3 arms, with benign twins):
- **naive arm:** attacks executed $7.6M of orders at trusted prices.
- **gate-only arm:** this fell to $0.29M, all of it trigger-rule sells, which the gate-only arm can't catch because it has no L7.
- **full arm:** $0.

The live DeepSeek suite has **not** been run yet, because the OpenRouter account ran out of credit before integration. `og-lab estimate` puts the full suite (83 cases × 3 arms) at about US$1.43.

## Layout

`receiver/` (TypeScript L8 and Python bridge), `packages/` (SDK and MCP server), `python/orderguard_guard` (L1–L5, L7, agent, `orderguard` CLI), `python/orderguard_verify` (L6, `og` CLI), `python/orderguard_lab` (cases, sandbox, `og-lab` CLI), `results/` (raw runs), `docs/`, `lab/legacy` (earlier experiments, kept as history).

## Licence

MIT. See [LICENSE](LICENSE).
