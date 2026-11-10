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

## Run it as a product

Install from a clone (the code reads its data, recordings and model files from the checkout). Then create a config directory with a fresh Ed25519 signing key (mode 600, never printed), a signed mandate template and a `.env` that lists variable names only:

```bash
.venv/bin/orderguard init --dir var/orderguard
```

Edit the mandate's limits, re-sign it with `orderguard init --resign`, put your own API key in the `.env` or the environment, and check everything:

```bash
.venv/bin/orderguard doctor --dir var/orderguard
```

Start the web app (API plus dashboard at http://127.0.0.1:8600). It binds to loopback and requires a bearer token whenever `ORDERGUARD_APP_TOKEN` is set:

```bash
.venv/bin/orderguard serve
```

Or run the receiver and the app together in containers:

```bash
docker compose up --build
```

The dashboard screens text (L1, L2 and the local classifier), checks orders against the signed mandate at trusted prices (L5, L6), evaluates standing rules (L7), replays demo scenarios layer by layer and shows the receiver ledger. Orders reach a ledger only through `broker.OrderRouter`, which sends nothing without an `allow` decision and goes through the L8 receiver. No real-money broker adapter ships; a real one must sit behind the same `Broker` interface. See [docs/APP.md](docs/APP.md) and [docs/OPERATIONS.md](docs/OPERATIONS.md).

**Local ML classifier.** `data/models/injection_clf.json` is a character and word n-gram logistic-regression detector trained on the lab and sandbox, exported as plain JSON and scored in pure Python (no pickle, no sklearn at runtime). `OG_CLASSIFIER=prefilter` quarantines high-confidence attacks without a model call; `ensemble` flags when either the classifier or the model does. It is off by default because, held out by technique, it is weaker than the model screen on real filing text. See [docs/CLASSIFIER.md](docs/CLASSIFIER.md).

## Live runs

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
  - denial of service: 0 of 7, down from 5 of 7. When a guarded agent drops a trade it was asked to make because tool output claimed a halt, lot size or price band, the guard checks the claim against trusted market status and, if trusted data contradicts it, tells the agent once and lets it decide again (still under L5 to L8). With the gate only: 1 of 7.
- **Model screen (L2):**
  - flagged 82 of 99 attack chunks;
  - wrongly flagged 4 of 174 clean chunks;
  - caught every hidden instruction and every fake-authority chunk, but only 35 of 52 false-data chunks.
- **Local ML classifier,** held out by technique on the same chunks: 59 of 99 attacks, 16 of 174 false alarms. It is fast and free but weaker, so it ships off by default.
- **Adaptive attacker:** 3 campaigns of 3 rounds against the full guard, 0 succeeded. The attacker model refused once.
- **Utility on clean tasks:** 6 of 7 completed in every arm. The miss is a trigger control that fails even with no guard. Before the trusted figure lookup was added, the guarded arms completed only 3 or 4 of 7 (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).
- **Errors with no attacker:** with the full guard the agent cited a wrong figure in 6 of 27 honest runs, against 10 of 27 unguarded. L6 refuses any order that relies on one.

**Offline sandbox sweep** (scripted policy agents, 1,150 attacked worlds × 3 arms, with benign twins). This tests the code and the dollar metric, not model behaviour:
- **naive arm:** attacks executed $7.6M of orders at trusted prices;
- **gate-only arm:** $0.29M, all of it trigger sells;
- **full arm:** $0.

**Caveats:**
- Each case ran once, so the intervals are wide. RESULTS.md shows them.
- The A, B and D rows for the guarded arms were recorded before the figure-lookup tool was added. Controls and families C, E and F were rerun with it.
- A first live sandbox sweep is excluded from the tables: SEC EDGAR was unreachable from its run, and it exposed a fiscal-year labelling bug in the world generator (now fixed). It still recorded $0 of harmful orders in the full arm. See `results/sweeps/excluded/README.md`. A clean live sweep is the next run once there is credit.
- DeepSeek's API does not report cost, so the spend table is the client's estimate at OpenRouter list prices. Actual DeepSeek charges were lower: about CNY 6.5 (US$0.91) for everything.

## Layout

`receiver/` (TypeScript L8 and Python bridge), `packages/` (SDK and MCP server), `python/orderguard_guard` (L1–L5, L7, agent, local classifier, broker router, `orderguard` CLI), `python/orderguard_app` (web API and dashboard), `data/models` (classifier weights as JSON), `Dockerfile` and `docker-compose.yml`, `python/orderguard_verify` (L6, `og` CLI), `python/orderguard_lab` (cases, sandbox, `og-lab` CLI), `results/` (raw runs), `docs/`, `lab/legacy` (earlier experiments, kept as history).

## Licence

MIT. See [LICENSE](LICENSE).
