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

A single page with a left sidebar (wordmark, navigation with the layer codes each page uses, and an environment block with mode, provider and model, budget meter and receiver status). Below 960px the sidebar becomes a menu. The eight hash routes are `#overview`, `#screen`, `#order`, `#graph`, `#scenario`, `#arena`, `#ledger` and `#results`. The visual language is specified in [DESIGN.md](DESIGN.md).

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

Tool pages show example actions, loading states and field errors. Press `Ctrl K` or `Cmd K` for the command palette and `?` for shortcuts. Use `g a` to open the swarm arena. The theme is remembered in `localStorage`. The layout is designed for 360px and respects `prefers-reduced-motion`. The mandate comparison was checked by keyboard in a 360px browser viewport in both light and dark themes. It had no page-level horizontal overflow. The nine static files total 181,768 bytes uncompressed, within the 200 KB ceiling in [DESIGN.md](DESIGN.md). The JavaScript runs without a build step.

Screenshots: none are checked in. To capture them, run `orderguard serve`, open each page at 1280px and 360px in light and dark, and use the example buttons so each page shows a result (the fake split order, the hidden instruction text and the injected-transfer scenario are the clearest).

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

`pyproject.toml` lists `python/orderguard_app` as a wheel package. A local `uv build --wheel` check confirmed the built wheel contains all eight static files (161,519 bytes total).
