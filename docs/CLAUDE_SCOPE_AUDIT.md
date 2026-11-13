# OrderGuard Claude scope audit

Audit date: 2026-11-12. Source of truth: `docs/CONTRACT.md`, the OrderGuard Claude transcripts, current repository implementation and the local verification run recorded below. This audit covers OrderGuard only.

## What was agreed

In the November 10 Claude build session, the user asked for the whole robust product rather than a phased prototype, while explicitly limiting model breadth and keeping model spend bounded. The user later rejected a proposed broad six-model evaluation and directed the build toward the current DeepSeek model. The requirement was end-to-end completion of the product, with every contract item implemented and tested or explicitly named as a gap, a report of test results and spend, and a locally ready state. The user explicitly withheld permission to push until signing in and saying to proceed.

The product scope in `docs/CONTRACT.md` is the operative definition of done:

| Area | Agreed outcome | Evidence in this checkout | Status |
|---|---|---|---|
| L1 input normalization | Detect hidden Unicode, mixed-script/look-alike tickers, encoded and tag-spelled instructions | `python/orderguard_guard/normalize.py`; seeded properties and adversarial corpus | Implemented and locally tested |
| L2 model screen | Shared guarded LLM client, replay by default, explicit live budget and credit floor | `python/orderguard_guard/llm.py`, `docs/RESULTS.md`, offline and bounded model checks | Implemented; live model quality remains model- and prompt-dependent |
| L3/L4 data controls | Quarantine repeated/dependent/untrusted claims and mark tool output as data | Guard agent loop, risk-bucket tests and attack corpus | Implemented and locally tested |
| L5/L6 decision | Signed mandate, ticker/side/size/day limits, trusted-price valuation, band and step-up; check cited figures for stale, future, non-public, period and split/unit errors | Gate and verifier packages; property tests; browser order flow previously exercised | Implemented and locally tested on bundled/simulated data |
| L7 trigger graph | Independent-source thresholding, quarantine, median and blast-radius simulation | Trigger graph package, seeded properties and UI page | Implemented and locally tested in simulation |
| L8 receiver | Fail-closed local paper receiver, idempotency, hash-chain ledger and bridge | Python router/paper broker, TypeScript receiver and real local bridge E2E | Implemented and locally tested; no real broker by design |
| Attack lab and evidence | Six attack families plus controls, comparisons of naive/gate-only/full, reproducible result tables | `data/lab`, `results`, `docs/RESULTS.md`, attack corpus and 1,000-seed invariants | Implemented; claims apply to the recorded scope and simulation |
| Product surface | Dashboard, API, MCP, CLI, GitHub CI, and multi-agent paper arena | App, API/MCP packages, workflow and arena page/tests; 1,000 agents × 144 ticks has been recorded | Implemented as a research product; not deployed or connected to a live venue |

## Verification performed for this audit

`bash scripts/check_all.sh` passed all five gates: Python (743 passed, 1 skipped), result tables, sandbox manifest, receiver/quickstart/1,000-seed invariant/secret scan checks, and a second committable-file secret scan. After closing the browser used for responsive review, an isolated `OG_LLM=replay pytest -q --durations=12` run completed in 55.78 seconds. One Starlette/httpx deprecation warning appeared during Python tests. A fresh `uv build --wheel` succeeded; inspection confirmed the wheel includes all eight app static files, totaling 161,519 bytes. The latest published GitHub Actions run for revision `b20827c` also passed its Python, receiver, secret-scan and Docker jobs; it predates this turn's local CSS and documentation edits.

The local dashboard at `127.0.0.1:8600` was inspected through its accessibility tree. It exposes the seven main work areas plus Swarm arena, reports the research/simulated-only boundary, shows the replay mode and budget, and makes the receiver's disconnected state explicit. Prior local browser checks covered representative order refusal and recorded-feed flows. This audit checked all eight routes at 360px in light/system and dark themes, and at 1280px in dark theme; document-level horizontal overflow was zero at every route. The mobile menu opened and navigated successfully, and the command palette opened with Cmd+K and closed with Escape. Chromium's accessibility tree showed one visible h1 per route and no unnamed buttons, links, textboxes, comboboxes, checkboxes or radio buttons. Design-token contrast calculations for primary, secondary, link and verdict colors against their specified backgrounds met WCAG AA. VoiceOver and enlarged-text passes remain unverified.

## Remaining gaps before calling the complete local prototype fully signed off

1. **Some accessibility evidence remains.** Token-pair calculations meet AA, the browser accessibility tree has named controls and one visible h1 per route, and the command palette works by keyboard. VoiceOver and enlarged-text behavior have not been verified.
2. **Current local changes have not been built into a Docker image.** The local Docker daemon is unavailable. GitHub Actions successfully built the latest published revision, but that run predates the local responsive CSS fix and documentation edits. The Dockerfile itself was not changed.
3. **Live integrations remain unproven and mostly out of scope.** Live EDGAR and market feeds, real WebAuthn, production load and real broker behavior are not validated. The contract explicitly excludes real orders and broker claims; the product is a research prototype, not production trading infrastructure.
4. **Model evidence is bounded.** Recorded live results and a tiny smoke call do not establish robust behavior across every model, prompt, market condition or adversary. User scope explicitly rejected broad model-benchmarking work for this build.

## Calibrated completion statement

The contract-defined **local simulated prototype is substantially implemented end-to-end**, and its offline safety/reproducibility gates pass. The product demonstrates the core path from adversarial input through bounded decisions to a paper receiver, and presents its API/MCP, CLI, results and swarm arena surfaces. The dashboard meets the reconciled 180 KB asset ceiling and passed the recorded responsive route checks. Remaining release evidence is a fuller assistive-technology pass and a Docker build of the current uncommitted checkout. The latest published revision's CI, including Docker, passes. No production deployment or real-world integration is proven. Real trading is not a remaining deliverable under the agreed contract.

No Git commit, push, deployment or real order was performed.
