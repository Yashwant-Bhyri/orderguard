# Contract notes: where the build differs from CONTRACT.md

## §5.1 Receiver bridge
- r5 mandates are single-symbol, at most 5 orders and at most 1 hour, so r5 cannot carry the multi-symbol JSON mandate.
  - The bridge authorises a one-share AAPL *anchor* mandate in r5. `receiver/core` enforces the JSON scope: allow-list, side, trusted-price notional, price band, daily total and step-up. It also owns the effect ledger, a hash-chained SQLite log.
  - A proposal commits only if the core passes and r5 still reports the anchor active.
  - `/revoke` revokes in the core first, then through the r5 passkey ceremony.
  - The bridge renews the anchor (same synthetic passkey ceremony) at 80% of its lifetime and on demand if a proposal finds it inactive. It never renews after `/revoke` or once the JSON mandate has expired. If renewal fails, proposals are denied as `anchor_unavailable`.
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

## §4 Default model and provider
- Live runs can go straight to DeepSeek's API (`OG_PROVIDER=deepseek`, key `DEEPSEEK_API_KEY`, model `deepseek-flash` = DeepSeek V4.1 Flash) as well as through OpenRouter. Both model clients support it.
- Replay keys hash the logical (OpenRouter-shaped) request, so recordings work with either provider.
- DeepSeek's API does not report cost, so spend is estimated from token counts at OpenRouter list prices (`OG_PRICE_IN` / `OG_PRICE_OUT`). The estimate runs higher than DeepSeek's actual charges. The credit floor is checked against DeepSeek's `/user/balance`.

## §5.3 Guard
- The guarded arms get one extra tool, `get_reported_figure`, a trusted lookup of filed figures backed by L6. See docs/ARCHITECTURE.md.

## Product additions beyond the contract
- `orderguard init` / `orderguard doctor` (config dir, signing key, signed mandate, checks), `orderguard serve` (web API and dashboard, docs/APP.md), Docker and compose (docs/OPERATIONS.md).
- `broker.OrderRouter`: orders reach a ledger only with an `allow` decision and only through the L8 receiver. No real-money adapter ships, in line with §4.
- L2 can run a local JSON-exported classifier first (`OG_CLASSIFIER=prefilter|ensemble`, default off; docs/CLASSIFIER.md). Default request bodies are unchanged, so recordings stay valid.
- Guarded arms check a dropped, intended trade against trusted market status (halt, lot size, band) and send at most one neutral notice (docs/ARCHITECTURE.md). Envs mark intended trades with `intended_trade`.
- The sandbox names fiscal years the way the company and L6 do (`world.fiscal_year_name`), not by the calendar year of the period end.
