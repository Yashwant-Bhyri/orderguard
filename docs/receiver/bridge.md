# Receiver bridge and core

`node receiver/bridge/serve.mjs --mandate mandate.json [--port P] [--step-up-usd N] [--ledger FILE|:ephemeral] [--anchor-ttl-sec S] [--anchor-renew-frac F|off]` (or `npm run bridge -- --mandate path`) prints `READY <port>` on stdout once listening on 127.0.0.1.

## API

| Route | Body | Reply |
|---|---|---|
| `GET /health` | | `{status, mandateId, revoked, issuerMandateActive}` |
| `POST /propose` | `{symbol, side, quantity, limitPrice, clientOrderId}` | `{decision: filled/denied/held, reason, reasons, orderId?, ledgerEffect, replay?, trustedPrice?, notionalUsd?}` |
| `POST /revoke` | | `{revoked: true}` |
| `POST /approve` | `{orderId, authorization?}` | same shape as `/propose`. A signed authorization is required in signed paper mode. |
| `GET /snapshot` | | `{orders, ledgerIntegrity, revoked, usedNotionalUsd}` |

`ledgerEffect` is true only when that call created the effect. A repeated `clientOrderId` returns the original `orderId` with `ledgerEffect: false` and `replay: true`. The same id with a different body is denied as `idempotency_conflict`.

Error statuses: 400 for a malformed body (`invalid_json`, `invalid_body`), 408 if the body stalls, 413 over 64 KiB, 403 for a non-loopback Host, 503 while stopping, 500 `internal_error` (no internal detail in the reply; it goes to the receiver's log with paths removed). Order refusals are always HTTP 200 with a `decision`. A retry of `/propose` or `/approve` is answered from the ledger before the anchor is consulted, so it sees the original outcome even while the anchor is unavailable. `anchor_unavailable` and `mandate_changed` mean "not now": nothing was recorded and the same `clientOrderId` may be sent again.

The demo bridge uses contract mandate JSON with an optional `stepUpThresholdUsd`. Deny reasons include `invalid_order`, `non_ascii_symbol`, `invalid_symbol`, `unlisted_symbol`, `side_not_allowed`, `no_trusted_price`, `limit_outside_band`, `per_order_cap`, `daily_cap`, `mandate_revoked`, `mandate_expired`, `mandate_changed`, `anchor_unavailable`, `idempotency_conflict`, `approval_invalid` and `not_held`.

## Signed paper mode

`orderguard paper-receiver` starts a loopback paper receiver with the configured `mandate.json` and pinned `signing.pub`. `orderguard activate-draft FILE` checks the unsigned file against that parent, signs the draft in the local CLI and sends it to the receiver. The receiver independently verifies the original parent, the action signature and the draft's containment. The signature binds the exact terms to this ledger and the current revision. A repeat of the most recent applied activation returns the same revision. Two different updates signed for the same revision cannot both apply.

Activation keeps the same SQLite ledger, idempotency keys and UTC-day spending (a persistent ledger keeps them across receiver restarts, see below). Pending holds from the previous revision are cancelled in the activation transaction. If earlier fills already used the new daily limit, the receiver refuses further orders for that day. The transaction adds a hash-chained activation event. A core restart that reopens the same SQLite file retains the revision. `orderguard paper-receiver` keeps its ledger on disk by default; the bare bridge and `Bridge.start` use a disposable ledger unless `--ledger` is given.

| Signed-mode route | Purpose |
|---|---|
| `GET /policy` | Current ledger and parent IDs, revision and effective limits. |
| `POST /policy/activate` | Apply a contained draft with a valid owner signature bound to the reported revision. |
| `POST /approve` | Approve one held order with an owner signature bound to the order ID and revision. Use `orderguard approve-paper-order ORDER_ID`. |

An owner action carries `payload` and `signature` as base64. The signature covers the exact decoded JSON bytes. The receiver checks the action purpose, parent ID, ledger ID and revision before applying it. The CLI sends these actions only to a numeric loopback address. The dashboard and MCP expose unsigned review. The synthetic r5 anchor remains part of the paper bridge, and signed-mode step-up additionally requires the configured owner's Ed25519 signature. The active parent can be revoked with `/revoke` or by listing its ID in `revoked-mandates.json`. Once observed, revocation is final for that ledger.

## Persistent ledger

| Setting | Effect |
|---|---|
| `--ledger FILE` or `ORDERGUARD_LEDGER=FILE` | Keep the effect ledger in this SQLite file (directory created mode 0700). |
| `--ledger :ephemeral` or nothing | Temp-directory ledger, deleted on exit. This is the demo default and what `Bridge.start` does. |
| `orderguard paper-receiver` | Defaults to `<config dir>/ledger/paper-ledger.sqlite`; `--ledger PATH` overrides, `--ephemeral` opts out. If the config directory is not writable (a read-only container mount) it starts throw-away and says so on stdout. |

What a persistent ledger guarantees:

- **Identity.** Orders, order ids and idempotency keys are bound to a stable mandate identity (the signed parent id; for a demo mandate a hash of its contents), not to the per-run r5 anchor. The same `clientOrderId` and body after a restart is a replay with `ledgerEffect: false`; a different body is `idempotency_conflict`. A ledger opened with a different mandate is refused ("different mandate"), as is one bound to another signed parent.
- **Verification before serving.** At every open (start, and the core's internal restart) the whole ledger is verified: contiguous hash chain, then a replay of the event log against every order row (terms, status, fill price, notional, action hash, order id), the revocation flag (deleting it cannot un-revoke), the policy revision against recorded activations, and each UTC day's spending against the daily limit. Any failure refuses to serve, exits 1, prints the first problem and tells the owner to restore a backup or start a new ledger, and leaves the file untouched. Unreadable or newer-schema files are refused the same way.
- **Single writer.** A `<ledger>.lock` pid file stops a second receiver using the same file (a dead holder is taken over).
- **Durability.** WAL with `synchronous=FULL` and a busy timeout. Each commit is one `BEGIN IMMEDIATE` transaction; a failure part-way rolls back the event and the row together, and the same `clientOrderId` can be retried.
- **Clock.** Expiry is exclusive to the millisecond (`now >= expiresAt` is expired). A UTC day's budget is charged to the newest day in the ledger, so a clock that steps backwards cannot reset spending. Revocation stays final: a revoked persistent ledger keeps refusing every order (`/health` shows `revoked`; start a new ledger to resume).
- **Known limit.** Deleting the newest events and their rows leaves a valid shorter chain. Record the `head` printed by `verify`/`export` somewhere the receiver's host cannot write and pass it back with `--expect-head SEQ:HASH` to detect truncation.

Ledger tool (works while the receiver runs; exit 0 verified, 1 failed verification, 2 usage or file problem):

```sh
node receiver/bridge/ledger-tool.mjs verify --ledger FILE [--expect-head SEQ:HASH]
node receiver/bridge/ledger-tool.mjs export --ledger FILE --out FILE.json      # orders, events, verification result; no key material
node receiver/bridge/ledger-tool.mjs backup --ledger FILE --out FILE.sqlite    # verified copy; never overwrites; refuses a tampered ledger
orderguard ledger-verify | ledger-export | ledger-backup [--ledger FILE] [--out FILE]   # same, resolving the default ledger
```

## Split of responsibility (a deviation from CONTRACT 5.1, stated plainly)

r5 can only issue single-symbol mandates of at most five orders and one hour, so it cannot carry the JSON scope. The bridge therefore authorises a one-share AAPL anchor mandate in r5 with the synthetic passkey, and the receiver core enforces the JSON scope. A proposal commits only if the core's checks pass and r5 still reports the anchor mandate active; `/revoke` revokes in the core first (durable, synchronous) and then through the r5 passkey ceremony. The core does not read r5's order ledger: effects live in the core's own SQLite ledger, a hash-chained event log checked by `ledgerIntegrity`.

## Anchor renewal

An r5 mandate lasts at most one hour, so the anchor is renewed instead of being allowed to lapse:

- Proactive: at 80% of the anchor's lifetime the bridge authorises a fresh anchor with the same synthetic passkey ceremony as at boot. The old anchor stays valid until its own expiry, so there is no gap.
- On demand: if `/propose` or `/approve` finds the current anchor inactive while the JSON mandate is still valid and not revoked, it renews first.
- Never after revocation: `/revoke` stops the timer, waits for any renewal already in flight, then revokes every anchor ever issued. Nothing renews afterwards. Renewal is also skipped once the JSON mandate's own `expiresAt` has passed.
- Fail closed: if renewal fails (for example r5 is down), the proposal is denied as `anchor_unavailable` with `detail` `anchor renewal failed: ...`, `ledgerEffect: false`. The proactive timer keeps retrying.
- `mandateId` in `/health` is the core's stable identity (see Persistent ledger); `anchorId` is the current anchor's id.

Settings: `--anchor-ttl-sec S` or `ORDERGUARD_ANCHOR_TTL_SEC` (default 3600; accepted 2 to 3600; r5 caps mandates at one hour). `--anchor-renew-frac F` or `ORDERGUARD_ANCHOR_RENEW_FRAC` (default 0.8; 0.1 to 0.95, or `off` for on-demand only). A shorter lifetime needs the small r5 release patch `ORDERGUARD_HUMAN_MANDATE_TTL_MS` (see `receiver/r5/PATCHES.md`), which the bridge sets itself.

## Valuation

Trusted price comes from the mandate's `referencePrices`; a boot-time quote source is used only for symbols the mandate does not price. Paper fills are recorded at the trusted price. Held orders reserve budget; revocation releases held reservations and cancels them.

Daily budget is per UTC day. Held orders reserve budget in the day they were created.

## Client behaviour (`python/orderguard_guard/receiver_client.py`)

`Receiver` retries reads, `propose`, `revoke` and `approve` (2 extra attempts, short backoff) on connection failure, timeout or 5xx, always with the same `clientOrderId`, which is safe because the receiver applies each id at most once. `activate_policy` is never retried. A reply without a recognised decision, a non-JSON reply or a non-object reply raises `ReceiverError`. `ReceiverError` text says what happened and what to do, and never contains the receiver URL, a home path or a secret. `OrderRouter` does not remember transient outcomes (receiver down or slow, `anchor_unavailable`, `mandate_changed`), so the same key can be retried; final outcomes are remembered. Different keys never wait on each other.

The Binance testnet broker is pinned to testnet, dry-run (read-only property), reachable only through `TestnetRouter` after an `allow` (and after the receiver fills when one is configured), ignores proxy environment variables and never follows redirects; transport failures and 5xx/429 are transient and retried under the same exchange client order id. The Futu simulate adapter is unexercised.
