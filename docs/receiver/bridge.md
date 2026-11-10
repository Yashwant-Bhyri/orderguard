# Receiver bridge and core

`node receiver/bridge/serve.mjs --mandate mandate.json [--port P] [--step-up-usd N]` (or `npm run bridge -- --mandate path`) prints `READY <port>` on stdout once listening on 127.0.0.1.

## API

| Route | Body | Reply |
|---|---|---|
| `GET /health` | | `{status, mandateId, revoked, issuerMandateActive}` |
| `POST /propose` | `{symbol, side, quantity, limitPrice, clientOrderId}` | `{decision: filled/denied/held, reason, reasons, orderId?, ledgerEffect, replay?, trustedPrice?, notionalUsd?}` |
| `POST /revoke` | | `{revoked: true}` |
| `POST /approve` | `{orderId}` | same shape as `/propose` |
| `GET /snapshot` | | `{orders, ledgerIntegrity, revoked, usedNotionalUsd}` |

`ledgerEffect` is true only when that call created the effect. A repeated `clientOrderId` returns the original `orderId` with `ledgerEffect: false` and `replay: true`. The same id with a different body is denied as `idempotency_conflict`.

Mandate JSON is the contract's, plus an optional `stepUpThresholdUsd`. Deny reasons: `invalid_order`, `non_ascii_symbol`, `invalid_symbol`, `unlisted_symbol`, `side_not_allowed`, `no_trusted_price`, `limit_outside_band`, `per_order_cap`, `daily_cap`, `mandate_revoked`, `mandate_expired`, `idempotency_conflict`, `approval_invalid`, `not_held`.

## Split of responsibility (a deviation from CONTRACT 5.1, stated plainly)

r5 can only issue single-symbol mandates of at most five orders and one hour, so it cannot carry the JSON scope. The bridge therefore authorises a one-share AAPL anchor mandate in r5 with the synthetic passkey, and the receiver core enforces the JSON scope. A proposal commits only if the core's checks pass and r5 still reports the anchor mandate active; `/revoke` revokes in the core first (durable, synchronous) and then through the r5 passkey ceremony. The core does not read r5's order ledger: effects live in the core's own SQLite ledger, a hash-chained event log checked by `ledgerIntegrity`.

## Valuation

Trusted price comes from the mandate's `referencePrices`; a boot-time quote source is used only for symbols the mandate does not price. Paper fills are recorded at the trusted price. Held orders reserve budget; revocation releases held reservations and cancels them.

## Not done

Step-up uses the one synthetic passkey registered at boot. Daily budget is per UTC day. The Futu SIMULATE adapter is unexercised.
