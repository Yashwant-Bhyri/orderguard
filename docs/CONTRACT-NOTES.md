# Contract notes: where the build differs from CONTRACT.md

## §5.1 Receiver bridge
- r5 mandates are single-symbol, at most 5 orders and at most 1 hour, so r5 cannot carry the multi-symbol JSON mandate.
  - The bridge authorises a one-share AAPL *anchor* mandate in r5. `receiver/core` enforces the JSON scope: allow-list, side, trusted-price notional, price band, daily total and step-up. It also owns the effect ledger, a hash-chained SQLite log.
  - A proposal commits only if the core passes and r5 still reports the anchor active.
  - `/revoke` revokes in the core first, then through the r5 passkey ceremony.
  - After about one hour the anchor expires and the bridge fails closed.
  - Details are in `docs/receiver/bridge.md`.
- `/propose` returns extra fields: `reasons`, `replay`, `trustedPrice` and `notionalUsd`.
- There is an extra endpoint, `POST /approve {orderId}`, for human step-up above `stepUpThresholdUsd`.
- The bridge's effects don't use r5's own paper ledger.

## §5.2 Figure check
- `check_figures` / `check_text` take optional keyword arguments `store=`, `fetch=` and `ask=`. Each figure may carry `period` (FY, or Q1 to Q4).
- `check_figures` writes on-demand SEC fetches to `data/verify/truth.db` unless `OG_TRUTH_DB` points elsewhere. The review gateway uses a working copy under `var/verify`.

## §4 Model calls
- L6 (`orderguard_verify`) keeps its own `core/llm.py` client. Its recorded answers are keyed to that client's request format, so moving it would invalidate the committed replay cache. It reads the same `OPENROUTER_API_KEY` / `OG_ENV_FILE`.
- Every other model call goes through `orderguard_guard.llm`.

## Running locally
- The bridge test and quickstart bind loopback ports. In a restricted sandbox that fails with `listen EPERM`, which is not a code failure.
