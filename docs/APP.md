# OrderGuard web app

A FastAPI service and a single-page dashboard over the guard layers. Research prototype: simulated markets only.

## Run

```bash
.venv/bin/orderguard serve                 # http://127.0.0.1:8600
.venv/bin/orderguard serve --port 9000
.venv/bin/python -m orderguard_app         # same, default host and port
```

The app defaults to `OG_LLM=replay`, so it makes no model call and spends nothing unless you set `OG_LLM=record` or `live` yourself (and a key, and a budget with `OG_BUDGET_USD`). The dashboard needs no network: HTML, CSS and JS are served from the package with no CDN.

## Endpoints

All JSON, under `/api`. Errors are `{"error": "..."}` with a proper status (401, 404, 413, 422, 502, 500); a 500 carries only a short reference, never a stack trace.

| Method and path | What it does |
|---|---|
| `GET /api/health` | Versions, provider (`OG_PROVIDER`), `key_configured` (a bool; the key is never returned or logged), LLM mode (`OG_LLM`), budget. |
| `POST /api/screen` `{text, kind}` | L1 normalise findings, then the L2 model screen. If there is no key (and not replay), or replay has no recording for the text, `l2.status` is `unavailable` instead of an error. Includes `classifier` (`orderguard_guard.classifier.score`) when that module is installed. |
| `GET /api/mandate` | The demo mandate, signed at startup with a fresh in-memory Ed25519 key, and its public key. The private key is never exposed or stored. |
| `POST /api/check-order` `{order, mandate?, prices?, as_of?, daily_total_usd?, require_figures?}` | L5 order gate with the L6 figure checker. Sized at the trusted price (`prices`, default the lab's demo market). Returns `decision`, `reasons`, `checks`, mandate info. `mandate` is `{mandate, public_key}`: a signed mandate JSON and the signer's base64 public key. Without a public key only expiry is checked, and the response says the signature was not checked. The signed body must contain every field the gate hashes, including `referencePrices`. |
| `POST /api/trigger-graph` `{rules?, events?, preset?, quarantined_sources?, blast_source?, lies?}` | L7 evaluate plus blast radius, with the naive baseline alongside. Defaults to the three standing rules and a `preset` event set. Custom rules: `{id, kind: pct_change or event, inputs, threshold, notional, side, match?}`. |
| `GET /api/scenarios` | Scenario ids: four scripted demos (`demo-1` to `demo-4`) and all lab cases. |
| `POST /api/run-scenario` `{scenario, arm?}` | Runs one scenario through `run_agent` and returns the layer-by-layer timeline. Scripted demos use the scripted agent (their arm is fixed). Lab cases (e.g. `C0-web`) replay recordings in `data/replay`; where no recording exists the response has `replay_miss: true` and the trace stops there. |
| `GET /api/ledger` | L8 receiver snapshot when `ORDERGUARD_RECEIVER_URL` is set, else `{"connected": false, ...}`. |
| `GET /api/results` | `docs/RESULTS.md` parsed into sections and tables (read-only). |

## Auth

Set `ORDERGUARD_APP_TOKEN` to require `Authorization: Bearer <token>` on every `/api` route (constant-time compare). The page at `/` stays public so it can ask for the token; the dashboard keeps it in `sessionStorage` only. With a token set, the OpenAPI document is also disabled.

## Security notes

- Binds `127.0.0.1` by default. Binding another address without a token prints a warning; put it behind TLS and a token if you do.
- Request bodies are capped (1 MB), text at 100,000 characters, rule and event lists at 50 and 2,000.
- The dashboard never uses `innerHTML`; every server or user string is rendered with `textContent`. A strict Content-Security-Policy (`default-src 'self'`, no inline script or style) backs this up.
- API responses are `no-store`. Keys come from the environment or `OG_ENV_FILE` by name inside the LLM client; the app only reports whether one exists.
- Uploaded mandates are evaluated, never stored.

## Packaging

`pyproject.toml` lists the wheel packages explicitly; add `python/orderguard_app` there (and include `static/`) so an installed wheel ships the app. An editable install picks it up once the path is on the package list or `PYTHONPATH`.
