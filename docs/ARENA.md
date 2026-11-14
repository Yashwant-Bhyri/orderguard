# Arena: pre-trade authorization for swarms of agents

One human signs a few **envelopes** (a conservative core, a tactical sleeve, a crypto sleeve). Hundreds or thousands of autonomous agents propose orders off market data. OrderGuard authorizes each order at the trusted price against a signed envelope, with one daily budget shared by every agent that draws on it. A second tool, the **envelope lab**, replays a recorded proposal stream through many candidate envelopes and shows the human a utility-versus-risk frontier: *which envelope should I sign?*

Hard rule: agents never choose, create or widen an envelope. The lab only advises; its output is an unsigned mandate body the human reviews and signs with their own key.

The agents and fills are simulated. The default feed generates synthetic ticks offline. The recorded market-data replay uses public Binance quotes with the same simulated agents and fills.

## Design

```
feed ticks ──> agents propose ──> authority decides ──> simulated fills ──> metrics + event log
(ReplayFeed /   (200..5,000;       (L1 normalise, L7 rule     (trusted price        results/arena/*.jsonl
 Binance public  honest + failure   confirmation, L5 gate      +/- slippage)         + summary json
 / recorded)     + attackers)       at TRUSTED price, shared
                                    budget, idempotency)
                                          │ optional, sampled
                                          └──> real L8 receiver (ORDERGUARD_RECEIVER_URL)
recorded stream ──> frontier.py ──> candidate envelopes ──> Pareto frontier + recommendation (advice)
```

Package `python/orderguard_arena/`:

| file | what it is |
|---|---|
| `feeds.py` | `ReplayFeed` (seeded GBM + jumps + calm/volatile regimes, 3 venues, an occasional lying venue, genuine and fake news), `BinancePublicFeed` (read-only public data, records JSONL), `RecordedFeed` (exact replay). Trusted price = median across venues. |
| `agents.py` | Five strategy archetypes (momentum, mean-reversion, market-making, rebalancer, news-reactive) with seeded per-agent parameters; failure archetypes at configurable rates; optional `LLMAgent`. |
| `envelopes.py` | `Envelope` = a signed `gate.Mandate` + owner/purpose metadata, `DailyBudget` (atomic reserve, mirrors receiver invariant I2), `EnvelopeBook.fit` and `tightest_fit`. |
| `authority.py` | The authorization service: single and batched, idempotency, step-up holds and human approval, revocation, L7, optional L8 sampling, latency percentiles. |
| `arena.py` | The run loop, simulated fills, PnL, oracle metrics, event log and summary. |
| `frontier.py` | The envelope lab: Latin-hypercube sweep, Pareto frontier, risk-budget recommendation with a plain-English explanation. |
| `cli.py`, `api.py` | `og-arena` and a FastAPI router for the dashboard. |
| `python/orderguard_guard/brokers/` | `binance_testnet.py` and `futu_sim.py`. |

### What the authority checks, in order

1. **L1**: ticker normalised (NFKC, upper-case); a ticker with non-Latin look-alike letters is refused; money movement (`transfer`, `destination_account`) is not an order and is refused.
2. **L7**: an order that claims to carry out a standing rule ("news says sell X") is held unless at least two independent *origins* confirm the event on the trusted feed (`orderguard_guard.graph.TriggerGraph`; three wires echoing one rumour count as one source).
3. **L5** at the **trusted** price, per envelope: allow-list, side, whole positive quantity, per-order cap, the envelope's shared daily cap, limit within the price band, step-up hold above a threshold. The order's own limit price is never used for sizing.
4. **Idempotency**: a repeated key returns the first decision and moves nothing; a key reused for a different order is refused.
5. **Budget**: an allow **or a step-up hold** reserves its notional atomically (`DailyBudget.reserve`, integer cents), so concurrent agents can never together exceed the cap. A step-up hold counts from the moment it is held and its later approval reserves nothing more. This mirrors the receiver (`status IN ('filled','held')`). `test_arena_accounting_matches_the_receiver_model_on_random_orders` checks the accounting against a Python model of the receiver's rules.

Routing is `pinned` (each agent draws on its sleeve's envelope; the default) or `tightest_fit` (any envelope of the owner that would authorize the order, the one with the smallest headroom wins, which keeps looser envelopes free for orders that need them).

### Guarantees (and what tests check them)

- The fast and strict modes matched on 3,000 randomized orders (`test_fast_path_agrees_with_the_real_order_gate_on_random_orders`). The seeded 1,000-agent run produced the **same event digest** (`601fc223...`) in strict mode, which uses the real `OrderGate` for its L5 checks. [Strict summary](../results/arena/arena-s7-k1000-t2000-strict.summary.json)
- The shared daily budget is atomic under threads (16 threads, exact `floor(cap/7)` reservations; 12 concurrent agents through the authority; a concurrent duplicate key reserves once).
- Colluding agents that each stay under the per-order cap cannot exceed an envelope's daily cap. They can still *use* the cap, which starves honest agents (see results).
- Compromised agents never get a transfer, an off-list ticker or a homoglyph ticker authorized, and no position outside the allow-lists ever exists after the fills.
- Same seed, same run: identical digest (`test_arena_is_deterministic_for_a_seed`).
- A tampered (widened after signing) envelope is refused when it is loaded.

## The agent population

Default mix: momentum 25%, mean-reversion 20%, market-making 15%, rebalancer 20%, news-reactive 20%. Failure archetypes are fractions of the population (defaults in `agents.DEFAULT_RATES`): fat finger (x10/x100 quantity, 2%), stale price (limit 4-30% off trusted, 2%), off-list ticker (1%), homoglyph ticker (0.5%), compromised (1%; techniques transfer, oversize at a fake reference price, sell everything, unlisted ticker; the injection language and encoding come from `orderguard_lab.payloads`), runaway loop (1%; same key or fresh keys), colluders (0.5%, assigned in groups of five). The seeded 1,000-agent run includes one colluding group. Fat-finger, stale-price, off-list and homoglyph agents slip on 15% of their non-trigger proposals.

Every proposal carries an oracle label (`legit` or the failure kind). The authority never sees it. News-reactive agents carry a rule trigger, and orders triggered by a fake story are labelled `fake_news`. Colluders are assumed to know the per-order cap, lowered to the step-up threshold, and the daily cap (a worst case); each group tries 1.5x the daily cap in total.

`LLMAgent` wraps a model (anything with `.chat`) for a small sampled subset via `wrap_llm`. It is off by default, nothing calls it, and the tests use a scripted model.

## Measured results (seed 7, 1,000 agents, 2,000 ticks = 4 simulated days)

Reproduce with `og-arena run --seed 7 --agents 1000 --steps 2000`. [Event log](../results/arena/arena-s7-k1000-t2000.jsonl) · [Summary](../results/arena/arena-s7-k1000-t2000.summary.json) · [Frontier](../results/arena/arena-s7-k1000-t2000.frontier.json)

Environment: one process, one thread, CPython 3.12, an Apple-silicon laptop. Marketable limits fill at the trusted price with 0.6–6.0 basis points of slippage. Passive limits fill at the limit with probability 0.4. The budget counts authorized notional.

### Decisions

The 20,503 proposals produced 18,394 fresh allows, 230 fresh holds, 1,777 refusals and 102 duplicate-key responses. The duplicate responses repeated 68 allows and 34 holds without moving anything. Of the fresh holds, 163 were for uncorroborated news and 67 were step-up holds. The refusals were for the daily cap (1,323), price band (162), off-list or look-alike tickers (147), per-order cap (104) and money movement (41).

| label | proposals | allow | hold | refuse | replays | measured notional $ | allowed $ |
|---|---|---|---|---|---|---|---|
| legit | 19,072 | 17,847 | 67 | 1,158 | 0 | 34,743,490 | 30,540,747 |
| collusion | 633 | 392 | 0 | 241 | 0 | 12,000,763 | 7,433,099 |
| compromised_oversize | 64 | 0 | 0 | 64 | 0 | 6,271,063 | 0 |
| compromised_unlisted | 116 | 0 | 0 | 116 | 0 | 951,200 | 0 |
| compromised_transfer | 41 | 0 | 0 | 41 | 0 | 389,500 | 0 |
| compromised_sell_all | 28 | 4 | 0 | 24 | 0 | 269,087 | 30,580 |
| fake_news | 163 | 0 | 163 | 0 | 0 | 1,925,535 | 0 |
| fat_finger | 33 | 15 | 0 | 18 | 0 | 2,108,422 | 158,910 |
| runaway_loop | 137 | 136 | 0 | 1 | 0 | 345,604 | 342,868 |
| runaway_dup | 102 | 0 | 0 | 0 | 102 | 904,937 | 0 |
| stale_price | 83 | 0 | 0 | 83 | 0 | 105,447 | 0 |
| off_list / homoglyph | 31 | 0 | 0 | 31 | 0 | 57,979 | 0 |

- Of $25.33M in measured bad-proposal notional, $16.46M was refused or held (65.0%), $7.97M was authorized ($7.67M filled), and $0.90M was absorbed as duplicate deliveries. The colluding group accounted for $7.43M of authorized notional. The arena authorized zero transfers, off-list or look-alike symbols, fake-reference oversize orders, stale-limit proposals or uncorroborated news orders. Some fat-finger and compromised sell-all orders fit the envelope and were authorized.
- The arena refused 1,158 of 19,072 legitimate proposals (6.07%), or $2.87M of $34.74M. The core daily cap accounted for 1,068 of those refusals, the price band for 67, and the per-order cap for 23. Another 67 legitimate proposals received step-up holds.
- The operator can narrow an envelope's daily cap with a per-agent share. A separate run with the same seed and a 1% share refused 2.36% of legitimate proposals, authorized $0.91M of bad notional and blocked 92.8% of bad notional. [Fair-share summary](../results/arena/arena-s7-k1000-t2000-fairshare.summary.json)
- A separate `tightest_fit` run refused 0.52% of legitimate proposals and authorized $12.65M in bad notional, with 47.8% blocked. This routing lets proposals draw on other eligible envelopes. [Tightest-fit summary](../results/arena/arena-s7-k1000-t2000-tightestfit.summary.json)
- The strict run produced the same event digest and decision counts as the baseline. The authority processed about 49,000 proposals per second in that run. [Strict summary](../results/arena/arena-s7-k1000-t2000-strict.summary.json)

### Throughput and latency (`og-arena bench --scales 200,1000,5000 --steps 1000`)

| agents | proposals | authority decisions/s (inline) | decisions/s (recorded stream, fresh authority) | p50 / p95 / p99 per decision (µs, inline) | strict sample decisions/s | end-to-end proposals/s (agents + authority + fills) |
|---|---|---|---|---|---|---|
| 200 | 2,115 | 164,255 | 242,822 | 4.3 / 8.0 / 18.5 | 59,223 | 19,598 |
| 1,000 | 10,306 | 210,762 | 194,887 | 3.7 / 6.2 / 9.3 | 58,314 | 28,771 |
| 5,000 | 53,157 | 218,585 | 163,338 | 3.5 / 5.5 / 9.5 | 60,055 | 31,789 |

The benchmark ran in single-threaded CPython. Inline latency measures local authorization. The strict sample uses the real `OrderGate` after envelope registration and includes at most 5,000 proposals per scale. The separate 2,000-tick baseline recorded an inline p99 of 25.29 µs. [Benchmark data](../results/arena/bench.json) · [Baseline summary](../results/arena/arena-s7-k1000-t2000.summary.json)

### Envelope frontier (`og-arena frontier`, 240 Latin-hypercube candidates plus two anchors, 20 on the frontier)

The default budget for this swarm allows up to $250,000 in leak and 60 holds per simulated day, with false refusals capped at 5%. The CLI calls the hold budget `--max-approvals`. It counts all holds, including uncorroborated triggers, as a proxy for review load. Honest agents proposed about $8.69M/day in legitimate notional. The stream contains about $6.11M/day in bad notional after duplicate deliveries are removed.

Replaying the baseline envelopes allowed $7.64M/day in legitimate notional (87.9%), refused 6.1% of legitimate proposals, leaked $1.99M/day and recorded 57.5 holds/day.

The recommended envelope uses a per-order cap of $91,360, a daily cap of $20,568,830, a 0.8% price band, 15 allowed symbols, a step-up above $66,976 and a 0.5% per-agent share. On replay it would have allowed $8,330,890/day in legitimate notional (95.9%), refused 2.43% of legitimate proposals, leaked $219,347/day and recorded 42 holds/day.

Frontier points (utility vs leak per day; the full list is in the `.frontier.json`): $3.78M/day at $0 leak (17.9% false refusals, 566.5 holds/day); $5.57M at $42k; $7.14M at $82k (6.7% false refusals); $8.33M at $219k; $8.58M at $599k; $8.69M at $3.71M (wide open, 0% false refusals). The frontier is steep at the loose end: going from $8.33M to $8.69M/day (the last 4% of legitimate flow) raises the leak from $219k to $3.71M/day.

In the sensitivity sweeps, raising the per-agent share from 2% to 5% increased total leak by $3.13M and lowered legitimate notional allowed by $8,741. Raising the per-order cap from $68,615.10 to $137,230.20 lowered total leak by $17,074 and legitimate notional allowed by $6,304. Looser limits change which orders spend the shared budget first. [Frontier sweeps](../results/arena/arena-s7-k1000-t2000.frontier.json)

Caveats the lab prints with every result: the stream comes from simulated agents; replay is open-loop (agents do not react to refusals or retry); one envelope covers the whole stream and its daily budget is shared by all agents; leak includes bad orders that lie inside any envelope loose enough to pass legitimate flow; the frontier is advice, the human signs.

## Review a draft against a signed policy

Open **Swarm arena → Review a mandate** and select the demo or your configured signed policy. Edit the suggested draft and check it against the parent. For a contained draft, **Estimate outcomes** returns an experimental model forecast and **Simulate both policies** reruns fresh agents under the parent and draft on the same market. A proposal's paper fill can affect later proposals. The policy review keeps effects in memory. Use **Download unsigned draft** to save the checked terms for human review.

**Compare draft options** generates up to eight distinct drafts that keep the parent's symbols, sides, expiry and reference prices. It runs each draft on the same market and starting population. Enter any combination of harmful notional, legitimate refusal and hold limits in **Simulation settings and risk limits**. The dashboard highlights the draft with the highest legitimate paper fill value among the matches when that value is positive. Fill value uses filled quantities at the trusted prices used by the guard. Use **Edit this draft** to open its terms and run a direct comparison with the parent.

**Preview draft ranking** shows an experimental ordering for supported synthetic scenarios with risk limits. The preview and **Estimate outcomes** can warn when a calibrated lower estimate for a specific outcome exceeds an entered limit, including zero. In API and CLI output, `warning` gives the metric, lower estimate and limit. The forecast may abstain. Use the measured comparison to see which drafts actually met the limits in the chosen scenario.

The CLI supports the same workflow. Omit `--draft` to get the verified parent and its suggested draft. Save the `suggested_draft` object as `draft.json`, then use it in either command below.

```sh
og-arena policy --source demo
og-arena policy --source demo --draft draft.json --mode estimate --agents 1000 --steps 600 --regime volatile
og-arena policy --source demo --draft draft.json --mode simulate --agents 1000 --steps 600 --seed 42 --regime volatile --max-bad 25000
```

An exit status of 1 means the draft fails containment. If you supply a risk limit, read `simulation.limits.met` to see whether the draft met it in the selected scenario. A recorded feed can be used with `--mode simulate --feed path/to/recording.jsonl`. The forecast covers only the synthetic scenarios in its training domain. The [acceptance record](PRODUCT-ACCEPTANCE.md) reports the model's operating limits and the measured comparisons.

```sh
og-arena policy --source demo --mode rank --max-bad 25000 --max-refusal 0.35 --max-holds 40
og-arena policy --source demo --mode search --max-bad 25000 --max-refusal 0.35 --max-holds 40
```

`--mode search` reports each candidate's measured outcomes and limit checks. `selected_rank` identifies the highest positive legitimate fill value among the matches when a limit was entered. With a recorded feed or an out-of-domain policy, the generated order is used. For a recording, the signed parent must include at least one exact feed symbol, such as `BTCUSDT` for the included Binance quotes. The response lists any unobserved policy symbols. The HTTP endpoint `POST /api/arena/policy/search` uses `rank` or `simulate`. Python MCP exposes `rank` and `search` on `review_mandate`. [HTTP reference](API.md#post-apiarenapolicysearch) · [MCP tools](MCP.md#tools)

To use a draft reviewed against your configured policy, start the signed paper receiver in one terminal, then activate the downloaded file in another. Both commands use `ORDERGUARD_HOME` or the same `--dir`.

```sh
orderguard paper-receiver
orderguard activate-draft path/to/orderguard-draft.json
```

The activation result reports the effective limits, revision and count of cancelled holds. The owner can approve a later held order by running `orderguard approve-paper-order ORDER_ID`. Start OrderGuard with `ORDERGUARD_RECEIVER_URL=http://127.0.0.1:8700` to use that receiver from supported app or agent flows. See [signed paper mode](receiver/bridge.md#signed-paper-mode) for ledger and approval behavior.

## Recorded public market data

`BinancePublicFeed` reads `GET /api/v3/ticker/bookTicker` and `/api/v3/ticker/price` only (no keys, no order endpoint; any other path raises), at 1 request pair per second, and writes every tick to `data/arena/feeds/*.jsonl` so a session replays exactly (`og-arena replay --feed ...`). The three quotes per symbol (`bid`, `last`, `ask`) come from **one** exchange, so they are not independent venues and the feed cannot show cross-venue lies; the trusted price is `last` clamped into `[bid, ask]`. Prices are per arena *unit* (BTC 0.001, ETH 0.01, SOL 1) so one unit fits under the caps. "Days" in a live session are 60-tick budget windows.

A recording from Binance's market-data mirror on 2026-11-11 UTC was replayed with 1,000 simulated agents for 144 ticks across three 60-tick budget windows. Of 1,330 proposals, 1,247 were allowed, 5 held and 78 refused. The run blocked 14.99% of labeled bad notional and refused 3.71% of legitimate proposals. [Public feed recording](../data/arena/feeds/binance-public-20261111T000117Z.jsonl) · [Replay summary](../results/arena/replay-binance-public-20261111T000117Z-k1000.summary.json)

Reproduce with `og-arena replay --feed data/arena/feeds/binance-public-20261111T000117Z.jsonl --agents 1000`. Recording and replay are also covered by a mocked-transport test.

## L8 pass-through

With `ORDERGUARD_RECEIVER_URL` set, `Authority.from_env` samples decisions deterministically by idempotency key (`ORDERGUARD_RECEIVER_SAMPLE`, default 1%) and compares them with the TypeScript receiver (`summary.l8`).

`og-arena l8 --seed 23 --agents 1000 --steps 400` starts the local TypeScript bridge with a temporary paper ledger and compares decisions under one envelope for one simulated day. Both sides use the same static prices, which the receiver reads from the mandate's `referencePrices`. The check compares each eligible order's `allow`, `hold` or `refuse` outcome with the receiver's `filled`, `held` or `denied` response. It reports `L8 CHECK PASS` with exit code 0 or `L8 CHECK FAIL` with exit code 1.

All **2,372 of 2,372** eligible comparisons agreed, with zero unreachable requests. The arena processed 2,404 proposals in total. [Raw L8 result](../results/arena/l8-agreement-s23-k1000.txt)

## Brokers

Both adapters implement `orderguard_guard.broker.Broker` and are reachable only through a router after an `allow`.

**`brokers/binance_testnet.py`** (Binance Spot testnet, funds have no value):

- Base URL hard-pinned to `https://testnet.binance.vision`; any other URL (other host, `http`, userinfo trick, port, path) is refused at construction, and the URL is re-checked right before every send.
- `dry_run=True` by default. The adapter builds and redacts the order request, signing it with HMAC-SHA256 when credentials are available. Dry run blocks order POSTs. Explicit exchange-information GETs can still use the transport.
- Credentials come from `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_SECRET`, by name only; values never appear in a request repr, return value, log or exception (errors name the variables). Dry run works without credentials and says the request is unsigned.
- Filters (`LOT_SIZE`, `PRICE_FILTER`, `NOTIONAL`) come from `exchangeInfo`; quantity and price are floored to the step and tick; `newClientOrderId` is the idempotency key.
- `submit` raises `NotRouted` unless called inside `TestnetRouter.route` after an `allow`; with a receiver configured, the L8 receiver must fill first.
- **Never run against the real testnet.** Tests use a mocked transport and send nothing.

**`brokers/futu_sim.py`**: an adapter skeleton for Futu OpenAPI's simulated environment (`TrdEnv.SIMULATE`). It raises `NotConfigured` unless the `futu` SDK is installed and a local OpenD gateway answers on 127.0.0.1; any environment other than `SIMULATE` is refused at construction. No affiliation with or endorsement by Futu is claimed, and it has never been run against Futu here.

## Run it

```bash
og-arena run --seed 7 --agents 1000 --steps 2000            # arena + event log + summary
og-arena run --seed 7 --agents 1000 --steps 2000 --agent-share 0.01 --summary-only --name my-run
og-arena frontier --stream results/arena/arena-s7-k1000-t2000.jsonl --max-leak 250000 --max-approvals 60
og-arena bench --scales 200,1000,5000 --steps 1000
og-arena replay --feed data/arena/feeds/<recording>.jsonl --agents 200
og-arena record --symbols BTCUSDT,ETHUSDT,SOLUSDT --seconds 180   # read-only public data
og-arena l8 --seed 23 --agents 1000 --steps 400             # needs node and a loopback port
```

Without installing the script: `python -m orderguard_arena.cli ...`. API: mount `orderguard_arena.api.router` (`/api/arena/run`, `/api/arena/frontier`, `/api/arena/envelopes`; synthetic runs are capped at 5,000 agents, 2,000 ticks and 2.5 million agent-ticks. Replay uses the recording length). Tests: `OG_LLM=replay python -m pytest -q python/tests/arena`. Check every quoted number: `og-arena verify`.

## Reproducing and checking the numbers

`og-arena verify` rebuilds every figure quoted in `README.md`, this page and `RISK.md` from the committed result files and requires the quoting sentence to match, then regenerates the arena results from their seeds (the 1,000-agent baseline, fair-share, tightest-fit and strict runs, the recorded-feed replay, the benchmark's deterministic columns and the envelope frontier) and requires them to match byte for byte. Timing fields are excluded because they measure a machine. `og-arena verify --quick` does only the first half in about a second; `--skip-frontier` skips the 35-second frontier rebuild. Committed summaries written before `paired_fills` existed are compared with that field at its default, which is what they used.

- Runs are deterministic across Python hash seeds (`PYTHONHASHSEED`), checked by a test that compares two runs, a strict run and a frontier across three seeds.
- Measured on one Apple-silicon laptop, CPython 3.12: `og-arena run --seed 7 --agents 5000 --steps 2000` makes 102,765 proposals in about 4.5 s wall with a 25.8 MB event log and a peak of about 125 MB resident when the log is streamed to disk (188 MB when events are also kept in memory). Timing and memory are machine-dependent and are not part of any check.
- The event log is streamed line by line to `<name>.jsonl.partial` and renamed only when the run completes, so a killed run never leaves a log that looks complete. Runs are deterministic and take seconds, so "resuming" means running again with the same seed.
- `og-arena frontier` refuses a truncated or corrupt log with the line number. `--allow-partial` uses the complete events of a log whose last line was cut off.
- A recorded feed that is truncated, has a bad line, or lacks a symbol its header declares is refused with the line number. Recording retries each poll up to three times with exponential backoff (the interval doubled each time, at most 30 s; a 429 or 418 `Retry-After` is honoured up to 60 s), never records a non-positive or non-finite quote, and stops with a clear error after five consecutive failed ticks. The recording up to that point stays valid.
- The Pareto frontier is checked against a brute-force dominance test on 200 random small grids (with ties) and on a real 40-candidate stream.
- `/api/arena/run`, `/frontier` and `/envelopes` answer 422 and name the field for a seed, `agents` or `steps` that is not a whole number or is outside its limits (agents 1 to 5,000, steps 1 to 2,000). The only adjustment is the documented work bound: steps are cut so that agents x steps stays within 2.5 million.

## Limitations

- The agents and fills are simulated. The default prices are synthetic. The separate public-feed replay uses recorded quotes from one exchange.
- A bad order inside the envelope is authorized by design. The envelope bounds the loss; it does not remove it.
- A shared budget protects dollars and costs availability: a colluding group can starve honest agents until the operator adds a fair-share policy or the human tightens the envelope. The fair share is an authority policy, not part of the signed mandate.
- The frontier is computed on one recorded stream, open-loop, with one pooled envelope; a different stream or a different human risk budget gives a different answer.
- The latency and throughput benchmarks measure Arena authorization in a single CPython process on one machine.
