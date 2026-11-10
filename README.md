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

Live runs use DeepSeek V4.1 Flash, either through OpenRouter or directly from DeepSeek:
- For OpenRouter, set `OPENROUTER_API_KEY`. For DeepSeek's own API, set `OG_PROVIDER=deepseek` and `DEEPSEEK_API_KEY`. Either key can instead come from a dotenv file named by `OG_ENV_FILE`.
- Set `OG_LLM=record` and raise `OG_BUDGET_USD`.
- Run `og-lab estimate` first. Every model call is recorded to `data/replay/` so tables rebuild offline. The client refuses calls when credit falls below US$0.30.

## Results so far

Every number below comes from [docs/RESULTS.md](docs/RESULTS.md), which `og-lab tables` rebuilds from the raw runs in `results/`.

**Live, DeepSeek V4.1 Flash (DeepSeek API), 83 cases × 3 arms, one repeat:**
- **The model rarely falls for attacks on its own.** With no guard it tried the attacker's action in 0 of 60 runs across families A–D.
- **What does work against the bare model:**
  - false facts it then repeats as true (1 of 16 runs);
  - denial of service, where a fake lot size, price band or halt makes it abandon a legitimate trade (5 of 7 runs).
- **Gate only:** 1 of 10 trigger attacks executed. That arm has no L7.
- **Full guard:**
  - 0 harmful orders executed;
  - 1 of 16 false beliefs still got through;
  - denial of service still worked in 5 of 7 runs, because the guard can stop bad orders but can't restore a trade the agent chose to abandon.
- **Model screen (L2):**
  - flagged 82 of 99 attack chunks;
  - wrongly flagged 4 of 174 clean chunks;
  - caught every hidden instruction and every fake-authority chunk, but only 35 of 52 false-data chunks.
- **Adaptive attacker:** 3 campaigns of 3 rounds against the full guard, 0 succeeded. The attacker model refused once.
- **Utility on clean tasks:** 6 of 7 completed in every arm. The miss is a trigger control that fails even with no guard. Before the trusted figure lookup was added, the guarded arms completed only 3 or 4 of 7 (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).
- **Errors with no attacker:** with the full guard the agent cited a wrong figure in 6 of 27 honest runs, against 10 of 27 unguarded. L6 refuses any order that relies on one.

**Offline sandbox sweep** (scripted policy agents, 1,150 attacked worlds × 3 arms, with benign twins). This tests the code and the dollar metric, not model behaviour:
- **naive arm:** attacks executed $7.6M of orders at trusted prices;
- **gate-only arm:** $0.29M, all of it trigger sells;
- **full arm:** $0.

**Caveats:**
- Each case ran once, so the intervals are wide. RESULTS.md shows them.
- The A, B, D and E rows for the guarded arms were recorded before the figure-lookup tool was added. Controls and families C and F were rerun with it.
- DeepSeek's API does not report cost, so the spend table is the client's estimate at OpenRouter list prices. Actual DeepSeek charges were lower: about CNY 6.5 (US$0.91) for everything.

## Layout

`receiver/` (TypeScript L8 and Python bridge), `packages/` (SDK and MCP server), `python/orderguard_guard` (L1–L5, L7, agent, `orderguard` CLI), `python/orderguard_verify` (L6, `og` CLI), `python/orderguard_lab` (cases, sandbox, `og-lab` CLI), `results/` (raw runs), `docs/`, `lab/legacy` (earlier experiments, kept as history).

## Licence

MIT. See [LICENSE](LICENSE).
