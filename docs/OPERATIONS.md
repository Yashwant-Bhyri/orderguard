# Operations

How to install, configure, run, back up and upgrade OrderGuard. No real-money broker adapter ships: orders reach a paper ledger only, through the L8 receiver bridge (`python/orderguard_guard/broker.py`). A real broker would have to be added behind the same `Broker` Protocol and still go through L8.

## Install

Python 3.11+ and Node 22.13+ (the receiver bridge is Node).

```sh
pip install -e '.[dev]'     # from a checkout; add .[ml] only to retrain detector models, .[detector] for the transformer detector
npm ci                      # receiver dependencies
```

Docker (needs `.env` and a config directory first, see below):

```sh
docker compose run --rm app orderguard init     # creates ./var/orderguard
docker compose up --build
```

The image installs the package in editable mode because the code finds `receiver/` and `data/` relative to the repository root. The app listens on `127.0.0.1:8600` on the host only.

## Configure

Environment variable names (values are yours; never commit them):

| Name | Purpose |
|---|---|
| `OG_PROVIDER` | `openrouter` (default) or `deepseek` |
| `OPENROUTER_API_KEY` / `DEEPSEEK_API_KEY` | key for the chosen provider |
| `OG_LLM` | `live` or `replay` (replay never calls a model) |
| `OG_BUDGET_USD` | hard ceiling on model spend; calls stop at the ceiling |
| `ORDERGUARD_APP_TOKEN` | bearer token the web app requires |
| `ORDERGUARD_RECEIVER_URL` | bridge base URL, e.g. `http://127.0.0.1:8700` |
| `ORDERGUARD_HOME` | config directory (default `./var/orderguard`) |
| `OG_ENV_FILE` | path to an env file kept outside the repository |

`.env.example` lists them with empty values.

## init and doctor

```sh
orderguard init [--dir PATH] [--provider deepseek|openrouter] [--force]
orderguard init --resign        # after editing mandate.json
orderguard init --check         # doctor: prints problems, exit code 1 if any
```

`init` creates `signing.key` (Ed25519, mode 600, never printed), `signing.pub`, a signed `mandate.json` template (allow-list, per-order cap, daily cap, price band, step-up threshold, 30-day expiry, placeholder `referencePrices`) and a `.env` listing names only. It refuses to overwrite without `--force`, which also generates a new key. Edit the mandate limits and reference prices to real values, then `--resign`: any edit invalidates the signature by design.

`init --check` verifies the key exists and is not group/world readable, the public key matches, the mandate signature is valid and unexpired, the provider key and app token are set (names only are reported, never values), and, if `ORDERGUARD_RECEIVER_URL` is set, that the receiver answers `/health` and is not revoked.

## Run

```sh
node receiver/bridge/serve.mjs --port 8700 --mandate var/orderguard/mandate.json   # prints READY 8700
orderguard serve --host 127.0.0.1 --port 8600
```

`docker compose up` runs both. The bridge listens on loopback only and rejects other Host headers, so in compose the app shares the receiver's network namespace rather than reaching it over a bridge network.

## Budgets and credit floor

`OG_BUDGET_USD` caps model spend per the spend file (`OG_SPEND_FILE`); set it low first. Providers also have their own credit floor: keep the account balance above what one run can spend, because a call that fails on low credit is reported as an error, not retried silently. Live results are recorded so runs can be replayed.

## Record and replay

`OG_LLM=replay` serves recorded responses from `data/replay` (`OG_REPLAY_DIR`) with zero spend; tests and CI always use it. `orderguard demo --live-record` records a live run (spends, within the budget).

## Upgrade

```sh
git pull && pip install -e . && npm ci
orderguard init --check
```

Rebuild the image with `docker compose build`. A new release never changes your signed mandate; re-sign only if you edit it.

## Backup

The bridge keeps its SQLite ledger (hash-chained event log, checked by `ledgerIntegrity`) in a temporary directory that it deletes on shutdown, so it does not persist across restarts today. Before stopping the bridge, save the state:

```sh
curl -s http://127.0.0.1:8700/snapshot > var/ledger-snapshot-$(date +%Y%m%d%H%M%S).json
```

Also back up `var/orderguard/` (the signing key is the one irreplaceable file; store the copy encrypted and offline). Persisting the ledger file itself needs a change in `receiver/bridge/serve.mjs` (a configurable ledger path); this is not done.

## Security notes

- Bind loopback. Compose publishes `127.0.0.1:8600` only; put a TLS reverse proxy with its own auth in front if you must expose it.
- Set `ORDERGUARD_APP_TOKEN` before any non-local use.
- Keys live in the environment or a `0600` env file outside version control; the repository scan (`npm run scan`) runs in CI.
- The receiver is the final authority: the agent, the app and the gate cannot move the ledger except through `/propose`, which checks the signed mandate again.
- The signing key authorises limits. Anyone holding it can sign a wider mandate; protect and rotate it (`init --force`, then restart the bridge).
- Containers run as a non-root user with a read-only root filesystem and all capabilities dropped.

## Troubleshooting

- `listen EPERM` or "Operation not permitted" when starting the bridge or app: the sandbox forbids binding local ports. Run outside the sandbox, or enable local port binding in the sandbox settings.
- `receiver unreachable`: check the bridge printed `READY`, the URL matches, and in compose that `app` uses `network_mode: service:receiver`.
- `mandate: ... changed after the human signed it`: you edited `mandate.json`; run `orderguard init --resign`.
- `mandate expired`: edit `expiresAt`, then `--resign`; restart the bridge.
- `anchor_unavailable` denials: the bridge's r5 anchor could not renew; see `docs/receiver/bridge.md`.
- Model calls fail with an auth error: the key variable for `OG_PROVIDER` is empty; `orderguard init --check` names it.
