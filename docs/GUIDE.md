# OrderGuard user guide

How to install OrderGuard, run it on your own computer, read its verdicts, put your own agent behind it and operate it. OrderGuard is a research prototype: simulated markets only, no real orders, no broker connection.

Contents: [Concepts](#concepts) | [Install](#install) | [Configure keys](#configure-keys) | [First run](#first-run) | [The dashboard](#using-the-dashboard) | [Integrate your agent](#integrating-your-own-agent) | [Operate it](#operating-it) | [Troubleshooting](#troubleshooting) | [FAQ](#faq) | [Security model](#security-model-summary)

## Concepts

**The problem.** An AI trading agent reads web pages, feeds and filings, and some of it is false. Making the model un-foolable does not work well enough, so OrderGuard puts code between the model and the money. Code decides what the agent may do, using numbers the agent cannot touch.

**Mandate.** A small JSON file the human signs with an Ed25519 key. It says which symbols and sides are allowed, the per-order and daily dollar caps, the allowed price band, the order size above which a human must step in, and when it expires. Any edit after signing invalidates the signature, and an unsigned, altered or expired mandate refuses every order. Create one with `orderguard init`; edit it, then `orderguard init --resign`. Three optional signed limits cap the portfolio rather than the order flow: `maxSymbolDailyNotionalUsd` (one symbol's notional per day, allowed and held orders alike, so many agents cannot split one big position on one ticker), `maxPositionUsd` (absolute net position in one symbol after the order, at the trusted price; held orders count in the direction that grows the exposure) and `maxOrdersPerDay` (non-denied orders per day, a backstop against a runaway agent). A missing field means no limit and leaves an old mandate's bytes, signature and id unchanged. The gate takes their state as `symbol_daily_usd`, `positions`, `held_qty` and `orders_today`, and refuses when a limit is set and its state is missing; the receiver computes them from its ledger inside the commit transaction (deny codes `symbol_daily_cap`, `position_cap`, `order_count_cap`). A sub-mandate (draft) can never loosen one of these limits or drop one its parent has.

**Trusted price.** Orders are sized at a price from a source the agent cannot write to (a market quote or the mandate's `referencePrices`), never at the limit price the order carries. A fake "10-for-1 split" that makes 440 shares at "$22.30" look like $9,812 is $97,988 at the trusted $222.70, and is refused.

**Layers.** Eight checks, each doing one job:

| Layer | What it does | Runs |
|---|---|---|
| L1 Normalise | Strips zero-width and hidden Unicode characters, flags look-alike tickers (Cyrillic "АAPL") | code |
| L2 Model screen | A model judges whether a text chunk is safe to show the agent; a failure quarantines the chunk | model (optional classifier first) |
| L3 Risk bucket | Quarantines repeats of a quarantined claim | code, then model if unsure |
| L4 Data marking | Wraps tool output in data tags so the agent is told it is not instruction | prompt |
| L5 Order gate | Signed mandate, allow-list, side, size at the trusted price, caps, price band, step-up | code |
| L6 Figure check | Each figure an order cites is checked against SEC filings public on the decision date | code over filings |
| L7 Trigger graph | A standing rule ("sell if down 40%") fires only when at least two independent, unquarantined sources agree | code |
| L8 Receiver | The final authority: re-checks the order against the signed mandate, keeps an atomic hash-chained ledger | TypeScript service |

L1, L5, L6, L7 and L8 are plain code. L2 and L4 depend on a model, which is why nothing relies on them alone.

**Arms.** A run of an agent uses one of three arms, so you can see what each layer buys: `naive` (no checks, every tool, the control), `gate_only` (L5, L6 and L8 on orders; no money-movement tool) and `full` (all layers). The scenario page and the lab results compare them.

**Verdicts.** Every check ends in one of: *allow*, *refuse*, *hold* (a human or more evidence is needed) or, for text, *quarantine*. See [what each verdict means](#what-each-verdict-means).

## Install

You need Python 3.11 or newer and Node 22.13 or newer (the receiver is Node). No API key is needed to try it.

### Fastest: the quickstart script

```sh
git clone <your copy of this repository> && cd orderguard
sh scripts/quickstart.sh
```

It creates `.venv`, installs the package, runs `orderguard init` and `orderguard doctor`, runs the offline test suite and starts the dashboard at <http://127.0.0.1:8600>. It is safe to re-run and never overwrites an existing signing key. Options: `--port N`, `--no-serve`, `--skip-tests`, `--skip-node`.

### By hand

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm ci
.venv/bin/orderguard init
.venv/bin/orderguard doctor
OG_LLM=replay .venv/bin/python -m pytest -q
.venv/bin/orderguard serve
```

Extras: `.[ml]` only to retrain detector models, `.[detector]` for the transformer detector.

### Docker

Follow the container setup to initialize and publish the signed policy files. Compose starts the signed paper receiver and dashboard together, with the dashboard published on `127.0.0.1:8600`. The image defaults to offline replay. Add a local `.env` to configure live model calls. [Container setup](OPERATIONS.md#install)

## Configure keys

Keys are read from the environment or from a `0600` env file; they are never returned by the app and never logged. Only variable names are listed here.

| Name | Purpose |
|---|---|
| `OG_PROVIDER` | `deepseek` (default, direct) or `openrouter` |
| `OPENROUTER_API_KEY` | key when the provider is OpenRouter |
| `DEEPSEEK_API_KEY` | key when the provider is DeepSeek's own API |
| `OG_LLM` | `replay` (recorded answers, no model call), `record` or `live` |
| `OG_BUDGET_USD` | hard ceiling on model spend |
| `OG_MODEL` | model name for the screen and agent |
| `ORDERGUARD_APP_TOKEN` | bearer token the web app requires |
| `ORDERGUARD_RECEIVER_URL` | base URL of the L8 receiver bridge |
| `ORDERGUARD_HOME` | config directory (default `./var/orderguard`) |
| `OG_ENV_FILE` | path to an env file kept outside the repository |

`orderguard init` writes `var/orderguard/.env` with these names and empty values. Fill in a value there, or export it in your shell. Never commit a key; `npm run scan` and `bash scripts/scan_committable.sh` look for them.

Live calls default to DeepSeek direct; set `DEEPSEEK_API_KEY` or point `OG_ENV_FILE` at a protected file containing it. To explicitly use OpenRouter, set `OG_PROVIDER=openrouter` and `OPENROUTER_API_KEY`. Then set `OG_LLM=live` and a small `OG_BUDGET_USD` before a live call.

## First run

1. Run `sh scripts/quickstart.sh` (or the by-hand steps above). The dashboard opens in replay mode: it makes no model call and spends nothing.
2. Open <http://127.0.0.1:8600>. The **Overview** page shows the L1 to L8 pipeline and which layers are available, configured or off on your machine.
3. Go to **Check order** and press **Fake 10-for-1 split (attack)**, then **Check order**. You should see a red *Refuse* banner decided by the order gate.
4. Press **Ordinary buy (benign)**. You should see a green *Allow*.
5. Open **Scenarios** and run **Fake split in the feed (attack)** to see an agent run call by call.
6. Edit `var/orderguard/mandate.json` to your own limits and symbols, then `orderguard init --resign`. The Overview page shows your configured mandate and whether its signature is valid.

Without a provider key, the model screen (L2) reports *unavailable* instead of an error. L1, L5, L6 and L7 still work, since they are code.

## Policy packs

`policies/` holds four unsigned templates (`conservative-equities`, `balanced-equities`, `active-equities`, `crypto-sleeve`) that use the portfolio limits above. They are starting points, not advice; the numbers are in [policies/README.md](../policies/README.md).

```bash
orderguard policy list
orderguard policy show balanced-equities
orderguard policy sign balanced-equities --key var/orderguard/signing.key --out var/orderguard/mandate.json [--symbols AAPL MSFT]
```

`sign` resolves `ttlHours` into `expiresAt`, refuses a template whose limits contradict each other (for example a per-order cap above the daily cap), and signs with your key. The templates ship inside the installed package.

## Using the dashboard

Seven pages, one per tab. Each tool page has example buttons (attacks and benign cases), inline validation next to each field, and a loading state. Results announce themselves to screen readers, every verdict has a text label as well as a color, and every result has an expandable **Raw JSON**.

- **Overview**: what OrderGuard does, the live L1 to L8 flow with each layer's status, the demo and configured mandates (limits, symbols, expiry, signature valid or not), the model, provider and budget, and whether the receiver is connected.
- **Screen text** (L1 + L2): paste a page, feed window or tool result. Shows hidden characters L1 removed, the model screen's judgement, the local classifier's attack probability when it is installed, and the cleaned text.
- **Check order** (L5 + L6): an order is sized at the trusted price and checked against the mandate and any figures it cites. Shows the value at the trusted price against the value at the order's own limit. Open **Mandate in use** to see the limits or paste your own signed mandate with its public key.
- **Triggers** (L7): pick a market event set and see which standing rules a naive system would fire against the guarded graph, plus the blast radius if one venue lies.
- **Scenarios**: replay a whole agent run as a timeline. Each step is one tool call with the layer that quarantined, refused or held it. Lab cases replay recordings offline; where none exists the page says so.
- **Ledger** (L8): the receiver's orders and hash-chain integrity, when `ORDERGUARD_RECEIVER_URL` is set.
- **Results**: headline numbers from the attack lab, the honest caveats, and the full tables.

### What each verdict means

| Verdict | Meaning | What to do |
|---|---|---|
| **Allow** | Every check passed: the order is inside the signed mandate at the trusted price and cited figures are confirmed. | Nothing. It still goes to L8, which checks again. |
| **Refuse** | A hard rule failed (ticker or side not allowed, over a cap, outside the price band, mandate invalid or expired, a cited figure contradicted). The reasons are plain sentences. | Fix the order, or if the rule is wrong, edit and re-sign the mandate. |
| **Hold** | Not refused, but not safe to proceed on its own: the order is above the step-up amount, a figure is unverifiable, or a trigger rule's inputs lack independent confirmation. | A human must approve, or more evidence must arrive. |
| **Quarantine** | For text: hidden or deceptive characters, or the model screen flagged it. The chunk is withheld from the agent. | Do not feed it to the agent; inspect the cleaned text. |
| **Clean** | For text: nothing severe found and the model judged it safe. Not a proof of honesty: a plainly written lie passes L1 and L2. | Rely on L5 and L6 for what the agent may do with it. |
| **Unknown** | The model screen could not run (no key, or no recording in replay mode). | Configure a key or use text that has a recording. |

The "Decided by" line names the deciding layer. L6 means a cited figure was contradicted, stale, not yet public or unverifiable.

## Integrating your own agent

Three ways in, from most to least Python-specific.

### Python: `run_agent`

`run_agent` runs one analyst agent against a tool environment in a chosen arm, applying the layers around every tool output and every order.

```python
from orderguard_guard.agent import run_agent
from orderguard_lab import cases

case = cases.get("C0-web")                 # a lab case; any object with .market, .mandate, .as_of and tools works as the env
env = case.build_env()
transcript = run_agent("deepseek/deepseek-v4.1-flash-1017", case.user_task(), env, arm="full")   # OG_LLM=replay serves recordings
print(transcript["final"], [c["name"] for c in transcript["calls"]], transcript["quarantined"])
```

`model` is a model name or any object with `.chat(messages, tools=...)`. The transcript holds each call with its `gate` decision, the quarantined chunks and the cost. With `OG_LLM=replay` it serves recordings only. To check single orders without an agent, use `orderguard check-order order.json --mandate mandate.json`, or `POST /api/check-order` on the app. Orders must cite their figures as `key_figures: [{metric, fiscal_year, value, unit}]` when the gate requires figures.

### Receiver SDK (Node)

`packages/sdk` is a small client for the receiver's HTTP routes. It turns one typed order into a preview and submits it; it holds no signing key and is not a security boundary. See `packages/sdk/README.md`.

```js
import { OrderGuardClient } from "@orderguard/sdk";
const og = new OrderGuardClient({ baseUrl: "http://127.0.0.1:8700" });
const result = await og.proposeOrder({ mandateId, symbol: "AAPL", side: "buy", quantity: 1, orderType: "market", session: "regular", timeInForce: "day" });
```

### MCP server

`packages/mcp-server` exposes `get_mandate`, `propose_order`, `order_status` and `cancel` to any MCP client over stdio. It is a thin adapter over the same receiver routes: `ORDERGUARD_URL=http://127.0.0.1:8700 node bin/orderguard-mcp.js`. Send bearer tokens only through the host's secret environment, never in a URL or a prompt. See `packages/mcp-server/README.md`.

Whichever way you integrate, give the agent no money-movement tool and let the receiver be the only path to the ledger.

## Operating it

**Budgets and the credit floor.** `OG_BUDGET_USD` caps model spend; calls stop at the ceiling and the Overview page shows spend so far. Providers have their own credit floor: keep the balance above what one run can spend, because a call that fails on low credit is reported as an error and not retried silently. Start with a very low budget.

**Record and replay.** `OG_LLM=replay` serves recorded responses from `data/replay` (override with `OG_REPLAY_DIR`) with no network and no spend. Tests and CI always use it. `OG_LLM=record` calls the model and records the answer for later replay; `live` calls without recording. The dashboard defaults to replay and only changes if you set the mode yourself.

**Logs.** The app logs to the terminal where `orderguard serve` runs. An unexpected error returns a short reference (`ref`) to the browser and logs only the error type with that reference: request text is never logged. Spend is written to the file named by `OG_SPEND_FILE`.

**Ledger backup.** The receiver bridge keeps its SQLite ledger in a temporary directory that it deletes on shutdown, so it does not persist across restarts today. Before stopping it:

```sh
curl -s http://127.0.0.1:8700/snapshot > var/ledger-snapshot-$(date +%Y%m%d%H%M%S).json
```

Also back up `var/orderguard/`. The signing key is the one irreplaceable file; keep an encrypted offline copy.

**Mandate lifecycle.** A mandate expires (30 days by default). Edit `expiresAt` and limits, run `orderguard init --resign`, then restart the bridge. `orderguard init --force` makes a new key and loses the old one.

**Upgrading.** `git pull && pip install -e . && npm ci && orderguard doctor`.

See [OPERATIONS.md](OPERATIONS.md) for Docker, the receiver bridge and hardening notes.

## Troubleshooting

`orderguard doctor` prints one `problem:` line per broken thing and exits 1 if there are any. A missing provider key or app token is only a `note:` (fine for a first local replay-mode run; exit 0); `orderguard doctor --strict` fails on notes too, which suits CI or a deployment check. It never prints a key value.

Command-line mistakes (missing or malformed JSON file, bad date, bad `--prices`) print one `orderguard: error:` line with a `hint:` and exit 2; set `ORDERGUARD_DEBUG=1` for a traceback. If `orderguard serve` cannot bind its port it says so and suggests `--port`. In the dashboard or API, 429 means slow down (wait the seconds in `Retry-After`), 503 means another heavy run is in progress, 504 means the run was too big: use fewer agents or steps.

`scripts/quickstart.sh` keeps going with the existing install when pip cannot reach the package index (offline, proxy, TLS inspection) and says so.

| Message or symptom | Cause and fix |
|---|---|
| `config directory ... does not exist` | Run `orderguard init`, or set `ORDERGUARD_HOME`. |
| `signing.key is readable by other users` | `chmod 600 var/orderguard/signing.key`. |
| `mandate: ... changed after the human signed` | You edited `mandate.json`. Run `orderguard init --resign`. |
| `mandate: ... expired` | Edit `expiresAt`, run `orderguard init --resign`, restart the bridge. |
| `OPENROUTER_API_KEY is not set` (or `DEEPSEEK_API_KEY`) | Only matters for live model calls. Add the key to `var/orderguard/.env` or the environment, or use `OG_LLM=replay`. |
| `ORDERGUARD_APP_TOKEN is not set` | Set a long random token before any use beyond this machine. |
| `receiver at the configured URL: ... unreachable` | The bridge is not running or the URL is wrong. Start it and check it printed `READY`. |
| Dashboard shows "Model screen unavailable" | No key, or replay mode has no recording for that text. Not an error: L1, L5, L6 and L7 still work. |
| Scenario shows "no recording exists" | Replay mode has no recording for that scenario and arm; pick another or record one. |
| Dashboard asks for an access token | The server has `ORDERGUARD_APP_TOKEN` set. Enter it; it is kept for the tab only. |
| `listen EPERM` or "Operation not permitted" on start | A sandbox forbids binding local ports. Run outside it or allow local binding. |
| `quickstart.sh` says Python or Node is too old | Install Python 3.11+ and Node 22.13+; use `--skip-node` for the Python parts only. |
| Port 8600 in use | `orderguard serve --port 9000` or `sh scripts/quickstart.sh --port 9000`. |

## FAQ

**Does it place real orders?** No. Orders reach a paper ledger only. No broker adapter ships.

**Is it safe to expose the dashboard?** Keep it on `127.0.0.1`. If you must expose it, set `ORDERGUARD_APP_TOKEN` and put a TLS reverse proxy with its own authentication in front.

**Does the dashboard call a model?** Not by default. It starts in replay mode. It only calls a model if you set `OG_LLM=record` or `live`, a key and a budget.

**Why was my honest order refused?** Read the reasons in the banner. The usual causes are a ticker or side outside the mandate, a cap, or a limit price far from the trusted price. The trusted price is not the order's own price by design.

**Why Hold and not Refuse?** Hold means the order breaks no rule but needs a human or more evidence, for example it is above the step-up amount.

**Can it make my agent profitable?** No. It bounds what a wrong or fooled agent can do. It does not judge whether a trade is a good idea.

**What do the results prove?** They are measurements from a hand-built attack set and a cheap model, with wide intervals. Read the caveats on the Results page and [RESULTS.md](RESULTS.md); the threats not defended are in [THREAT-MODEL.md](THREAT-MODEL.md).

## Security model summary

- The agent is least-privileged: in `gate_only` and `full` no money-movement tool is offered, and a call to one is refused.
- Limits come from a human-signed Ed25519 mandate. The private key lives in `signing.key` (mode 600), is never printed, and is never read by the dashboard.
- Orders are valued at a trusted price, not the one the order states. Cited figures are checked against SEC filings public on the decision date.
- The receiver is the final authority: it re-checks the signed mandate on every order, is idempotent and supports revocation.
- Standing rules need two independent, unquarantined sources.
- The web app binds loopback by default, caps request sizes, never uses `innerHTML`, sends a strict Content-Security-Policy with no inline script or style and loads nothing from the network. API responses are `no-store`. An optional bearer token protects `/api`.
- Not defended: a false belief that leads to an allowed order, a mandate signed against the owner's interest, a compromised broker or receiver, and collusion of independent sources. See [THREAT-MODEL.md](THREAT-MODEL.md).
