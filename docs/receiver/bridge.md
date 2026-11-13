# Receiver bridge and core

`node receiver/bridge/serve.mjs --mandate mandate.json [--port P] [--step-up-usd N] [--anchor-ttl-sec S] [--anchor-renew-frac F|off]` (or `npm run bridge -- --mandate path`) prints `READY <port>` on stdout once listening on 127.0.0.1.

## API

| Route | Body | Reply |
|---|---|---|
| `GET /health` | | `{status, mandateId, revoked, issuerMandateActive}` |
| `POST /propose` | `{symbol, side, quantity, limitPrice, clientOrderId}` | `{decision: filled/denied/held, reason, reasons, orderId?, ledgerEffect, replay?, trustedPrice?, notionalUsd?}` |
| `POST /revoke` | | `{revoked: true}` |
| `POST /approve` | `{orderId, authorization?}` | same shape as `/propose`. A signed authorization is required in signed paper mode. |
| `GET /snapshot` | | `{orders, ledgerIntegrity, revoked, usedNotionalUsd}` |

`ledgerEffect` is true only when that call created the effect. A repeated `clientOrderId` returns the original `orderId` with `ledgerEffect: false` and `replay: true`. The same id with a different body is denied as `idempotency_conflict`.

The demo bridge uses contract mandate JSON with an optional `stepUpThresholdUsd`. Deny reasons include `invalid_order`, `non_ascii_symbol`, `invalid_symbol`, `unlisted_symbol`, `side_not_allowed`, `no_trusted_price`, `limit_outside_band`, `per_order_cap`, `daily_cap`, `mandate_revoked`, `mandate_expired`, `mandate_changed`, `anchor_unavailable`, `idempotency_conflict`, `approval_invalid` and `not_held`.

## Signed paper mode

`orderguard paper-receiver` starts a loopback paper receiver with the configured `mandate.json` and pinned `signing.pub`. `orderguard activate-draft FILE` checks the unsigned file against that parent, signs the draft in the local CLI and sends it to the receiver. The receiver independently verifies the original parent, the action signature and the draft's containment. The signature binds the exact terms to this ledger and the current revision. A repeat of the most recent applied activation returns the same revision. Two different updates signed for the same revision cannot both apply.

Activation keeps the same SQLite ledger, idempotency keys and UTC-day spending. Pending holds from the previous revision are cancelled in the activation transaction. If earlier fills already used the new daily limit, the receiver refuses further orders for that day. The transaction adds a hash-chained activation event. A core restart that reopens the same SQLite file retains the revision. The bridge itself starts a disposable ledger for each separate paper session.

| Signed-mode route | Purpose |
|---|---|
| `GET /policy` | Current ledger and parent IDs, revision and effective limits. |
| `POST /policy/activate` | Apply a contained draft with a valid owner signature bound to the reported revision. |
| `POST /approve` | Approve one held order with an owner signature bound to the order ID and revision. Use `orderguard approve-paper-order ORDER_ID`. |

An owner action carries `payload` and `signature` as base64. The signature covers the exact decoded JSON bytes. The receiver checks the action purpose, parent ID, ledger ID and revision before applying it. The CLI sends these actions only to a numeric loopback address. The dashboard and MCP expose unsigned review. The synthetic r5 anchor remains part of the paper bridge, and signed-mode step-up additionally requires the configured owner's Ed25519 signature. The active parent can be revoked with `/revoke` or by listing its ID in `revoked-mandates.json`. Once observed, revocation is final for that ledger.

## Split of responsibility (a deviation from CONTRACT 5.1, stated plainly)

r5 can only issue single-symbol mandates of at most five orders and one hour, so it cannot carry the JSON scope. The bridge therefore authorises a one-share AAPL anchor mandate in r5 with the synthetic passkey, and the receiver core enforces the JSON scope. A proposal commits only if the core's checks pass and r5 still reports the anchor mandate active; `/revoke` revokes in the core first (durable, synchronous) and then through the r5 passkey ceremony. The core does not read r5's order ledger: effects live in the core's own SQLite ledger, a hash-chained event log checked by `ledgerIntegrity`.

## Anchor renewal

An r5 mandate lasts at most one hour, so the anchor is renewed instead of being allowed to lapse:

- Proactive: at 80% of the anchor's lifetime the bridge authorises a fresh anchor with the same synthetic passkey ceremony as at boot. The old anchor stays valid until its own expiry, so there is no gap.
- On demand: if `/propose` or `/approve` finds the current anchor inactive while the JSON mandate is still valid and not revoked, it renews first.
- Never after revocation: `/revoke` stops the timer, waits for any renewal already in flight, then revokes every anchor ever issued. Nothing renews afterwards. Renewal is also skipped once the JSON mandate's own `expiresAt` has passed.
- Fail closed: if renewal fails (for example r5 is down), the proposal is denied as `anchor_unavailable` with `detail` `anchor renewal failed: ...`, `ledgerEffect: false`. The proactive timer keeps retrying.
- `mandateId` in `/health` stays the first anchor's id (the core's identity); `anchorId` is the current one.

Settings: `--anchor-ttl-sec S` or `ORDERGUARD_ANCHOR_TTL_SEC` (default 3600; accepted 2 to 3600; r5 caps mandates at one hour). `--anchor-renew-frac F` or `ORDERGUARD_ANCHOR_RENEW_FRAC` (default 0.8; 0.1 to 0.95, or `off` for on-demand only). A shorter lifetime needs the small r5 release patch `ORDERGUARD_HUMAN_MANDATE_TTL_MS` (see `receiver/r5/PATCHES.md`), which the bridge sets itself.

## Valuation

Trusted price comes from the mandate's `referencePrices`; a boot-time quote source is used only for symbols the mandate does not price. Paper fills are recorded at the trusted price. Held orders reserve budget; revocation releases held reservations and cancels them.

Daily budget is per UTC day. The bridge is for paper use. The Futu SIMULATE adapter is unexercised.
