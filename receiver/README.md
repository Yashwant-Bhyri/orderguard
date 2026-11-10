# Receiver

The receiver is layer L8: the final authority over a paper ledger. Nothing reaches the ledger except through it.

What is here, and how much to trust it:

- `core/` is the part written for this repository and the one the invariants test. It checks the exact canonical order against a human-signed mandate and commits it atomically.
  - Notional is quantity times a trusted reference price, never the order's own limit price. The limit must sit within `priceBandPct` of the trusted price.
  - Tickers are trimmed, NFKC-folded, uppercased and must be plain ASCII. Mixed-script symbols are denied.
  - Daily budget, idempotency and revocation are checked in one SQLite transaction.
  - Orders above a threshold are held until the synthetic owner passkey approves them.
- `bridge/serve.mjs` is a thin loopback HTTP wrapper (`/health`, `/propose`, `/revoke`, `/snapshot`, `/approve`). It boots r5 with an isolated temp ledger and a synthetic passkey. See `docs/receiver/bridge.md`.
- `invariants/` is the seeded fault campaign behind `npm run invariants`.
- `r5/` is an older, much larger receiver and workbench imported from an earlier snapshot (see `r5/SOURCE-MAP.json` and `r5/PATCHES.md`). Here it provides the owner passkey ceremony and the mandate's active/revoked state. Its own test evidence is not included in this repository.
- `futu-adapter/`, `futu_simulate_adapter.py` and `r5/futu-simulate-adapter.ts` are an adapter for a Futu OpenD SIMULATE account. It has never been run against Futu in this repository. It is closed unless two environment flags are set, nothing here sets them, and no test or script calls a broker.
- `intel/` is research code kept for reference; the core does not use it.

Everything is synthetic: simulated passkey, simulated prices, a local SQLite ledger. Passing tests say nothing about real money, a real broker or production use.
