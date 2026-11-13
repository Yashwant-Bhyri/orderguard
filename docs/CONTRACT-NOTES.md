# Contract notes: where the build differs from CONTRACT.md

## §5.1 Receiver bridge
- r5 mandates are single-symbol, at most 5 orders and at most 1 hour, so r5 cannot carry the multi-symbol JSON mandate.
  - The bridge authorises a one-share AAPL *anchor* mandate in r5. `receiver/core` enforces the JSON scope: allow-list, side, trusted-price notional, price band, daily total and step-up. It also owns the effect ledger, a hash-chained SQLite log.
  - A proposal commits only if the core passes and r5 still reports the anchor active.
  - `/revoke` revokes in the core first, then through the r5 passkey ceremony.
  - The bridge renews the anchor (same synthetic passkey ceremony) at 80% of its lifetime and on demand if a proposal finds it inactive. It never renews after `/revoke` or once the JSON mandate has expired. If renewal fails, proposals are denied as `anchor_unavailable`.
  - Details are in `docs/receiver/bridge.md`.
- `/propose` returns extra fields: `reasons`, `replay`, `trustedPrice` and `notionalUsd`.
- There is an extra endpoint, `POST /approve`, for step-up above `stepUpThresholdUsd`. Signed paper mode additionally requires a signature from the configured owner.
- `orderguard paper-receiver` adds the signed paper mode. The owner can activate a contained draft on the running ledger, keeping prior fills, daily spending and idempotency. See [the bridge contract](receiver/bridge.md#signed-paper-mode).
- The bridge's effects don't use r5's own paper ledger.

## §5.2 Figure check
- `check_figures` / `check_text` take optional keyword arguments `store=`, `fetch=` and `ask=`. Each figure may carry `period` (FY, or Q1 to Q4).
- `check_figures` writes on-demand SEC fetches to `data/verify/truth.db` unless `OG_TRUTH_DB` points elsewhere. The review gateway uses a working copy under `var/verify`.

## §4 Model calls
- All live L1–L6 calls use the shared `orderguard_guard.llm` client, spend cap, provider-floor check and spend log.
- L6 reads its historical `data/verify/llm_cache` answers first in replay/record mode, preserving the older logical request cache. New recordings use the shared `data/replay` cache.

## Running locally
- The bridge test and quickstart bind loopback ports. In a restricted sandbox that fails with `listen EPERM`, which is not a code failure.

## §4 Default model and provider
- The default is DeepSeek direct with `deepseek/deepseek-v4.1-flash-1017` mapped to API model `deepseek-flash`. OpenRouter remains an explicit override.
- Replay keys hash the logical (OpenRouter-shaped) request, so recordings work with either provider.
- Live calls reserve against peak token prices and the requested output-token ceiling before POST, then settle against reported or estimated usage. On an ambiguous response timeout, the reserved exposure remains charged against the process cap and is logged as unconfirmed. The credit floor is checked against the configured provider's current balance.

## §5.3 Guard
- The guarded arms get one extra tool, `get_reported_figure`, a trusted lookup of filed figures backed by L6. See docs/ARCHITECTURE.md.

## §7 DeepSeek demo

The replay demo uses the bundled lab cases `C0-web`, `B-revsplit`, `C-D8` and `A-htmlc-web`. The exact model replay uses lab tool receipts. Each case then checks its allowed proposals on a fresh signed loopback paper receiver. The L6 demonstration also re-evaluates the contradicted order captured in C-D8 repetition 1. The scripted demo uses the receiver inline and retains the original forward-split example. [Replay walkthrough](OPERATIONS.md#record-and-replay)

## Product additions beyond the contract
- `orderguard init` / `orderguard doctor` (config dir, signing key, signed mandate, checks), `orderguard serve` (web API and dashboard, docs/APP.md), Docker and compose (docs/OPERATIONS.md).
- `broker.OrderRouter`: orders reach a ledger only with an `allow` decision and only through the L8 receiver. No real-money adapter ships, in line with §4.
- L2 can run a local JSON-exported classifier first (`OG_CLASSIFIER=prefilter|ensemble`, default off; docs/CLASSIFIER.md). Default request bodies are unchanged, so recordings stay valid.
- Guarded arms check a dropped, intended trade against trusted market status (halt, lot size, band) and send at most one neutral notice (docs/ARCHITECTURE.md). Envs mark intended trades with `intended_trade`.
- The sandbox names fiscal years the way the company and L6 do (`world.fiscal_year_name`), not by the calendar year of the period end.
