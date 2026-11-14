# Operations

How to install, configure, run, back up and upgrade OrderGuard. No real-money broker adapter ships: orders reach a paper ledger only, through the L8 receiver bridge (`python/orderguard_guard/broker.py`). A real broker would have to be added behind the same `Broker` Protocol and still go through L8.

## Install

Python 3.11+ and Node 22.13+ (the receiver bridge is Node).

```sh
pip install -e '.[dev]'     # from a checkout; add .[ml] only to retrain detector models, .[detector] for the transformer detector
npm ci                      # receiver dependencies
```

For a first Docker installation, build the image and create the owner configuration in a one-time container. If you already have `var/orderguard/mandate.json` and its signing keys, use that directory and skip the `docker run` initialization.

```sh
docker compose build receiver
mkdir -p var/orderguard
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD/var/orderguard:/owner" orderguard:local orderguard init --dir /owner
```

Copy the signed parent and public key into the directory the services can read. If the owner directory has an existing revocation list, copy that file too before starting the receiver.

```sh
install -d -m 0755 var/paper-policy
install -m 0644 var/orderguard/mandate.json var/orderguard/signing.pub var/paper-policy/
if test -f var/orderguard/revoked-mandates.json; then
  install -m 0644 var/orderguard/revoked-mandates.json var/paper-policy/
fi
docker compose up --build
```

Both services read `var/paper-policy` through a read-only mount. The private signing key stays in `var/orderguard`. The app listens on `127.0.0.1:8600` on the host. It defaults to offline replay. Add a local `.env` based on `.env.example` to configure a provider. New recordings and spend logs go in the app data volume, and the bundled recordings remain available from the image. The image uses an editable install to resolve `receiver/` and `data/` from the source tree.

## Configure

Environment variable names (values are yours; never commit them):

| Name | Purpose |
|---|---|
| `OG_PROVIDER` | `deepseek` (default, direct) or `openrouter` |
| `OPENROUTER_API_KEY` / `DEEPSEEK_API_KEY` | key for the chosen provider |
| `OG_LLM` | `live` or `replay` (replay never calls a model) |
| `OG_BUDGET_USD` | hard ceiling on model spend; calls stop at the ceiling |
| `ORDERGUARD_APP_TOKEN` | bearer token the web app requires |
| `ORDERGUARD_RECEIVER_URL` | bridge base URL, e.g. `http://127.0.0.1:8700` |
| `ORDERGUARD_HOME` | config directory (default `./var/orderguard`) |
| `ORDERGUARD_LEDGER` | persistent receiver ledger file (default `<config dir>/ledger/paper-ledger.sqlite` for `paper-receiver`) |
| `OG_ENV_FILE` | path to an env file kept outside the repository |
| `OG_RECORD_DIR` | optional writable model recording directory, checked before the bundled replay directory |

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
orderguard paper-receiver
OG_LLM=replay ORDERGUARD_RECEIVER_URL=http://127.0.0.1:8700 orderguard serve
```

`docker compose up` runs both. The bridge listens on loopback only and rejects other Host headers, so in compose the app shares the receiver's network namespace rather than reaching it over a bridge network.

For an owner action in Compose, run a one-time command in the receiver's network namespace. This example uses a draft saved as `orderguard-draft.json` in the current directory.

```sh
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/var/orderguard:/owner:ro" -v "$PWD/orderguard-draft.json:/draft.json:ro" \
  app orderguard activate-draft /draft.json --dir /owner
```

For `approve-paper-order ORDER_ID --dir /owner`, the owner directory mount is sufficient. The receiver checks for revocations in `var/paper-policy/revoked-mandates.json` during the session. After an owner re-signs the parent, republish the signed public files and deliberately start a new paper session.

## Budgets and credit floor

`OG_BUDGET_USD` is a hard per-process cap; spend is appended to `OG_SPEND_FILE`. Separate live processes have separate local caps, so do not run independent live jobs concurrently when you need one combined budget. Providers also have their own credit floor: keep the account balance above what one run can spend, because a call that fails on low credit is reported as an error, not retried silently. Live results are recorded so runs can be replayed.

## Record and replay

Run `OG_LLM=replay orderguard demo` to replay the four bundled DeepSeek lab cases at zero provider spend. The command uses the original lab tool receipts to match the recorded requests. It sends the exact guarded proposals that filled in the lab to fresh local paper receivers, then checks the receiver effects and prints each ledger. The altered-filing case also checks a contradicted order captured in another recorded DeepSeek repetition. A replay miss or failed effect check produces a nonzero exit status.

Use `orderguard demo --scripted` to exercise the receiver inline with a deterministic stand-in. `OG_LLM=record orderguard demo` records missing lab-case responses from the configured provider within the budget. `OG_REPLAY_DIR` can point to a different cache for those conversations. The captured contradicted proposal comes from the bundled archive. [Demo evidence](PRODUCT-ACCEPTANCE.md#receiver-and-demo-recheck)

## Upgrade

```sh
git pull && pip install -e . && npm ci
orderguard init --check
```

Rebuild the image with `docker compose build`. Keep the current signed mandate when upgrading and re-sign it after an edit.

## Ledger persistence and backup

`orderguard paper-receiver` keeps its SQLite ledger (hash-chained event log) at `<config dir>/ledger/paper-ledger.sqlite`. Change it with `--ledger PATH` or `ORDERGUARD_LEDGER`; `--ephemeral` (or `:ephemeral`) gives a throw-away ledger. After a restart the receiver keeps its orders, idempotency keys, UTC-day spending, policy revision and revocation. The bare bridge (`npm run bridge`, the demo, tests) is still throw-away unless `--ledger` is passed.

At start the whole ledger is verified. A ledger that fails verification is never served: the receiver exits 1, names the first problem and leaves the file as found. Restore the last backup, or move the file aside to begin a new ledger. A ledger created under a different mandate, or a re-signed parent, is refused too: start a new ledger path. A revoked ledger stays revoked.

```sh
orderguard ledger-verify                       # exit 0 verified, 1 failed verification, 2 problem; prints head SEQ:HASH
orderguard ledger-verify --expect-head SEQ:HASH  # detects a truncated tail, using a head you recorded elsewhere
orderguard ledger-backup [--out FILE]          # consistent, verified SQLite copy (default: ledger/backups/); refuses a tampered ledger
orderguard ledger-export [--out FILE]          # JSON: orders, events, verification result; no key material
```

All three work while the receiver runs. Back up on a schedule and record the printed head off the host. To restore, stop the receiver, copy the backup over the ledger path and start it; the start-up verification confirms it.

In Compose the receiver's config mount is read-only, so it starts with a throw-away ledger and says so. To persist, mount a writable volume and add `--ledger /that/path/paper-ledger.sqlite` to the receiver command. Without that, take a snapshot before stopping:

```sh
docker compose exec -T app node -e 'fetch("http://127.0.0.1:8700/snapshot").then(async r => { if (!r.ok) throw Error(r.status); console.log(JSON.stringify(await r.json())); })' \
  > var/ledger-snapshot-$(date +%Y%m%d%H%M%S).json
```

Back up `var/orderguard/` with the signing key encrypted and offline.

## Security notes

- Bind loopback. Compose publishes `127.0.0.1:8600` only; put a TLS reverse proxy with its own auth in front if you must expose it.
- Set `ORDERGUARD_APP_TOKEN` before any non-local use.
- Keys live in the environment or a `0600` env file outside version control; the repository scan (`npm run scan`) runs in CI.
- The receiver verifies the signed policy for proposals and requires the owner's signature for draft activation and held-order approval.
- The signing key authorises limits. Anyone holding it can sign a wider mandate; protect and rotate it (`init --force`, then restart the bridge).
- Containers run as a non-root user with a read-only root filesystem and all capabilities dropped.

## Troubleshooting

- `listen EPERM` or "Operation not permitted" when starting the bridge or app: the sandbox forbids binding local ports. Run outside the sandbox, or enable local port binding in the sandbox settings.
- `receiver unreachable`: check the bridge printed `READY`, the URL matches, and in compose that `app` uses `network_mode: service:receiver`. If the text says the request may or may not have been applied, retry with the same client order id (applied at most once) or check `ledger-verify` and the snapshot.
- `bridge failed: ... integrity check`: the ledger was edited or damaged; see Ledger persistence and backup. `Another receiver ... is already using`: stop the other receiver or use a different ledger path.
- `mandate: ... changed after the human signed it`: you edited `mandate.json`; run `orderguard init --resign`.
- `mandate expired`: edit `expiresAt`, then `--resign`; restart the bridge.
- `anchor_unavailable` denials: the bridge's r5 anchor could not renew; see `docs/receiver/bridge.md`.
- Model calls fail with an auth error: the key variable for `OG_PROVIDER` is empty; `orderguard init --check` names it.
