# OrderGuard web app

A FastAPI service and a single-page dashboard over the guard layers. Research prototype: simulated markets only.

## Run

```bash
.venv/bin/orderguard serve                 # http://127.0.0.1:8600
.venv/bin/orderguard serve --port 9000
.venv/bin/python -m orderguard_app         # same, default host and port
```

The app defaults to `OG_LLM=replay`, so it makes no model call and spends nothing unless you set `OG_LLM=record` or `live` yourself (and a key, and a budget with `OG_BUDGET_USD`). The dashboard needs no network: HTML, CSS and JS are served from the package with no CDN.

Fastest way to a working install: `sh scripts/quickstart.sh` (venv, install, `orderguard init`, `orderguard doctor`, offline tests, then serve). See [GUIDE.md](GUIDE.md).

## Dashboard

A single page with a left sidebar (wordmark, navigation with the layer codes each page uses, and an environment block with mode, provider and model, budget meter and receiver status). Below 960px the sidebar becomes a menu. The theater lives at `/theater`, outside the hash router. The eight hash routes are `#overview`, `#screen`, `#order`, `#graph`, `#scenario`, `#arena`, `#ledger` and `#results`. The visual language is specified in [DESIGN.md](DESIGN.md).

| Page | What it gives you |
|---|---|
| Overview | The L1 to L8 rail showing each layer's status on this server (hover or focus a station for what it checks), the demo and configured mandates, model, provider, budget and receiver. |
| Screen text | The input with what L1 found made visible (hidden-character chips, mixed-script tokens underlined with their folded spelling, base64 runs with the decoded payload), then a row per detector (local classifier with a probability bar, threshold tick and highlighted features; fast model; main model screen), each with its own verdict and latency. |
| Check order | Verdict card with the layer that decided and numbered reasons, the path through L1 to L8, the agent's numbers beside the ones OrderGuard trusts, meters for the per-order cap, the daily cap and the price band, and the cited-figure table (claimed, filed truth, status, source). |
| Triggers | The trigger board: every source with its independence group (quarantined ones struck through), each rule with its threshold, median and outcome ("needs 2 independent sources, has 1"), and the blast radius as bars. |
| Scenarios | The run on one rail, then a timeline of the agent's tool calls, each with a compact rail of the layers that acted, ending in the run's verdict card. |
| Swarm arena | Simulated strategies and adversaries, a proposal tape, and unsigned draft review with containment, experimental forecasts, parent-versus-draft paper comparisons and JSON export. |
| Ledger | Receiver orders and hash-chain integrity, or a clear not-connected state. |
| Results | Headline tiles, the honest caveats directly beneath them, a grouped bar chart of attack success by family and arm with Wilson 95% whiskers (inline SVG, patterns as well as colours), and the tables with family and arm filters. |

Tool pages show example actions, loading states and field errors. Press `Ctrl K` or `Cmd K` for the command palette and `?` for shortcuts. Use `g a` to open the swarm arena. The theme is remembered in `localStorage`. The layout is designed for 360px and respects `prefers-reduced-motion`. The mandate comparison was checked by keyboard in a 360px browser viewport in both light and dark themes. It had no page-level horizontal overflow. The twelve static files total 243,022 bytes uncompressed, within a 260 KB ceiling. The ceiling was 200 KB until the Swarm Theater added its own page, stylesheet and script, about 60 KB together; `python/tests/app/test_app_api.py` and `test_arena_page.py` enforce the new figure with that justification. The JavaScript runs without a build step.

Screenshots: none are checked in. To capture them, run `orderguard serve`, open each page at 1280px and 360px in light and dark, and use the example buttons so each page shows a result (the fake split order, the hidden instruction text and the injected-transfer scenario are the clearest).

## Swarm Theater

`/theater` (the dashboard's landing call to action, "Watch a swarm get caught", and a Swarm Theater link in the sidebar) is a 90-second guided replay of one real recorded run: 1,000 simulated agents, 2,000 ticks, four simulated days (`results/arena/arena-s7-k1000-t2000.jsonl`). Nothing on it is generated for the show. Every number is a sourced fact (a file and a JSON pointer, each checked by `python/tests/app/test_theater.py`) or a count taken from the stream and reconciled with the run's own summary, and the page links the source file beside it. It is its own page (`theater.html`, `theater.css`, `theater.js`) on the dashboard's tokens, `ui.js` helpers, CSP and content-hashed asset URLs; no inline script or style, no `innerHTML`.

**What a viewer sees**

1. **Calm** (steps 0 to the first attack). Three envelope cards, each with its agents as dots and a live gauge of the day's shared budget. Honest orders pulse; the counters count them. Caps (per order, step-up, price band) are printed under each gauge.
2. **The attack starts.** The same run with the arena's labels revealed: attacker agents are ringed, and a bad order shows as a red dot because with nothing in front of it the order reaches the exchange. The counter is the dollars of bad orders that reached the gate, counted from the stream. The run has no no-guard counterfactual, so the page says it is not a modelled loss. It plays three real windows: the first attacks (fake news, stale price, the first fat finger), the runaway loop, and the colluding group, skipping the gaps.
3. **The guard.** It rewinds to the first attack and replays the same windows with the verdicts. The feed names each refusal or hold in plain English with the event's own numbers ("869 QQQ at the trusted $112.80 is $98,024, over the tactical per-order cap of $40,000"), collapsing repeats. Three counters split the bad dollars by who stopped them: the mandate gate, the order-risk layer, and nothing. A focus panel follows one attack end to end (the rumour held by L7, the injected oversize order refused by L5, and five colluding agents that the gate allowed and the order-risk unit `split_under_threshold` stopped): the order with the agent's numbers beside the trusted ones, the rule or unit that fired, the decision, and the ledger entry. The ledger step shows the budget moved and the recording's hash-chain rows around the event, which the browser re-hashes on request.
4. **The human.** The held-order queue for the hour the collusion began, ordered by expected bad dollars as in [REVIEW.md](REVIEW.md) (`all_held`), beside each order's first-in-first-out position. Jev's advice sits in a dashed box headed "Advice only" and says it cannot approve or release the order. Ground truth is hidden until the viewer reveals it. This run set no revocation, so the revoke card quotes the receiver evidence register (the Q5 recorded-action replay) and says it is separate evidence, not this run.
5. **The proof.** Bad dollars stopped by both layers, with the gate-alone share beside it; honest orders held and refused, with the daily-cap cost stated; decisions per second with latency percentiles; the L8 receiver agreement and the recording's chain; and the reconciliation checks. A clearly marked slot reads `results/bench/summary.json` when that file exists and shows its headline (the scalar entries of its `headline` object, or of the file); until then it says it is not written and shows nothing in its place.

**Controls.** Play and pause, back and next beat, step back and forward one tick of the run, speed, a scrubber with beat marks, and "Copy link". Keys: Space, left and right arrows, comma and full stop (Shift for ten). The caption is an `aria-live` region updated once per beat; gauges are `role="meter"`; shape (circle, square, diamond) carries state as well as colour. With `prefers-reduced-motion` (or `?motion=reduce` on the address, to force it) nothing plays by itself: Next and Back show each beat's end state and Step moves through the run. Below 700 px the swarm stacks into three compact cards and the controls shrink to one row; on narrow screens the human and proof beats hide the swarm.

**Deep link.** `/theater#beat=3&step=1040` opens paused at that beat and 1-based step; the address updates as you pause or move. A link without `beat=` starts playing.

**Data.** `python -m orderguard_app.theater build` reads the stream, summary, order-risk replay, latency, triage study, L8 result, receiver register and the order-risk model, scores the stream point in time with the shipped model, replays the Jev advice from `data/replay/decisions` (never a live call), and writes `results/theater/timeline.json` (about 217 KB): the events packed at two bytes each (agent and state), per-step aggregates, a feed with its English interned, the three focus attacks, the queue, and the facts. The file records the hash of every input and of the builder; `check` (and a test) fails when any changed, and the endpoint rebuilds in memory instead of serving a stale file. It is byte-for-byte deterministic. The order-risk layer is a replay over the recorded gate decisions on a seed it never trained on; budget a stopped colluder would have freed is not re-simulated.

**Limits.** Agents, fills and labels are simulated. The recording's hash chain indexes the stream file; it is not the L8 receiver's ledger. The theater has not been run against a reduced-motion browser setting or a screen reader; the static contract for both is tested, and the layout was checked in the built-in browser at 1280 and 375 px in light and dark.

## Limits and security

Authentication runs before anything is read or parsed, so an unauthenticated caller learns nothing. Request bodies are capped at 1,000,000 bytes (chunked uploads too). Heavy routes (arena runs, scenarios, screening) have a per-client rate limit, a concurrency cap and a deadline (429, 503 and 504 respectively); the table, the environment switches and the deliberate absence of CORS are in [API.md](API.md#limits-and-cross-origin-stance). Every response carries `nosniff`, `X-Frame-Options: DENY`, a strict CSP and a no-camera/microphone/geolocation `Permissions-Policy`. The dashboard maps 429, 503 and 504 to plain instructions.

## Endpoints

All JSON, under `/api`. Errors are `{"error": "..."}` with a proper status (401, 404, 405, 413, 422, 429, 502, 503, 504, 500); a 422 adds `details` naming each bad field; a 500 carries only a short reference, never a stack trace.

| Method and path | What it does |
|---|---|
| `GET /api/overview` | What the Overview page shows: `layers` (L1 to L8, each `{id, name, status, detail}` with status `available`, `configured` or `off`), `classifier`, `demo_mandate`, `configured_mandate` (the `mandate.json` in `ORDERGUARD_HOME`, its signature checked against `signing.pub`; `signing.key` is never read), `receiver` and `model` (provider, mode, key configured as a bool, budget and spend). Never returns a key. |
| `GET /api/health` | Versions, provider (`OG_PROVIDER`), `key_configured` (a bool; the key is never returned or logged), LLM mode (`OG_LLM`), budget. |
| `POST /api/screen` `{text, kind}` | L1 normalise findings, then the L2 model screen. If there is no key (and not replay), or replay has no recording for the text, `l2.status` is `unavailable` instead of an error. Includes `classifier` (`orderguard_guard.classifier.score`, plus `threshold`, `latency_ms` and `top_features` with character `spans`) when that module is installed, `fast` (the optional fast-model stage, `off` unless configured), `reveal` (the input as text, hidden, mixed and b64 segments), per-detector `latency_ms` and `decided_by`. |
| `GET /api/mandate` | The demo mandate, signed at startup with a fresh in-memory Ed25519 key, and its public key. The private key is never exposed or stored. |
| `POST /api/check-order` `{order, mandate?, prices?, as_of?, daily_total_usd?, require_figures?}` | L5 order gate with the L6 figure checker. Sized at the trusted price (`prices`, default the lab's demo market). Returns `decision`, `reasons`, `checks`, mandate info, plus `decided_by` (L5 or L6), `reason_layers`, `path` (the eight rail stations), `claimed`, `meters` (caps, band, daily totals) and `figure_rows` (with source form and filed date). `mandate` is `{mandate, public_key}`: a signed mandate JSON and the signer's base64 public key. Without a public key only expiry is checked, and the response says the signature was not checked. The signed body must contain every field the gate hashes, including `referencePrices`. |
| `POST /api/trigger-graph` `{rules?, events?, preset?, quarantined_sources?, blast_source?, lies?}` | L7 evaluate plus blast radius, with the naive baseline alongside, plus `sources` (with independence groups), `rule_details` (threshold, per-input median and source counts, outcome) and `min_sources`. Defaults to the three standing rules and a `preset` event set. Custom rules: `{id, kind: pct_change or event, inputs, threshold, notional, side, match?}`. |
| `GET /api/scenarios` | Scenario ids: four scripted demos (`demo-1` to `demo-4`) and all lab cases. |
| `POST /api/run-scenario` `{scenario, arm?}` | Runs one scenario through `run_agent` and returns the layer-by-layer timeline, each step with a `path` of stations, and `run_path` for the whole run (`off` for layers the arm does not run). Scripted demos use the scripted agent (their arm is fixed). Lab cases (e.g. `C0-web`) replay recordings in `data/replay`; where no recording exists the response has `replay_miss: true` and the trace stops there. |
| `GET /api/theater/timeline` | The Swarm Theater's precomputed timeline (below). About 217 KB, 73 KB gzipped (served gzip when the client accepts it). |
| `GET /api/theater/bench` | The headline of `results/bench/summary.json` when it exists, else `{"present": false, ...}`. Read on every request. |
| `GET /api/theater/source?id=...` | Without `id`, the files the theater is built from; with one of those ids (or `bench`), that committed file as plain text. An allow-list of exact ids: no path is read from the request. |
| `GET /api/ledger` | L8 receiver snapshot when `ORDERGUARD_RECEIVER_URL` is set, else `{"connected": false, ...}`. |
| `GET /api/results` | `docs/RESULTS.md` parsed into sections and tables (read-only), plus `charts` (per model, family and arm: k, n, rate and the report's Wilson interval) and `headline` (pooled live figures and spend). |

## Auth

Set `ORDERGUARD_APP_TOKEN` to require `Authorization: Bearer <token>` on every `/api` route (constant-time compare). The page at `/` stays public so it can ask for the token; the dashboard keeps it in `sessionStorage` only. With a token set, the OpenAPI document is also disabled.

## Security notes

- Binds `127.0.0.1` by default. Binding another address without a token prints a warning; put it behind TLS and a token if you do.
- Request bodies are capped (1 MB), text at 100,000 characters, rule and event lists at 50 and 2,000.
- The dashboard never uses `innerHTML`; every server or user string is rendered with `textContent`. A strict Content-Security-Policy (`default-src 'self'`, no inline script or style) backs this up.
- API responses are `no-store`. Keys come from the environment or `OG_ENV_FILE` by name inside the LLM client; the app only reports whether one exists.
- Uploaded mandates are evaluated, never stored.

## Packaging

`pyproject.toml` lists `python/orderguard_app` as a wheel package. A local `uv build --wheel` check, made before the Swarm Theater was added, confirmed the built wheel contains all eight static files then in the package (161,519 bytes total). The theater also reads committed result files, so it needs a source checkout (or those files beside the package) and answers 404 with a sentence naming what is missing.
