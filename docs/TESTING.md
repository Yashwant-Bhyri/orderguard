# Testing OrderGuard

Everything here runs offline. No test calls a live model: `OG_LLM=replay` is forced, so a request with no recording raises instead of
reaching the network. Randomised tests use `random.Random(<fixed seed>)`, so a failure reproduces exactly.

## Run it

```
bash scripts/check_all.sh                      # everything a reviewer needs, one PASS/FAIL table with timings
OG_LLM=replay .venv/bin/python -m pytest -q    # the Python suite alone (about 56 s; the receiver e2e adds about 4 s when it can run)
OG_LLM=replay .venv/bin/python -m pytest -q python/tests/safety       # the safety suite alone (about 20 s)
npm run check                                  # TypeScript receiver: unit, quickstart, 1,000-seed invariants, secret scan
```

`check_all.sh` runs: pytest (all), `og-lab tables --check`, `og-lab sandbox describe --check`, `npm run check`, the secret scan. It
exits non-zero if any step fails. `CHECK_ALL_SKIP="npm"` skips steps whose name contains a listed word; `CHECK_ALL_VERBOSE=1` streams output.

Markers (registered in `python/tests/conftest.py`): `slow` (a few seconds, still offline) and `e2e` (starts the real receiver bridge).
The e2e tests **skip with a reason** when `node` is missing or the environment forbids binding a loopback port.

## What each suite proves

| Suite (under `python/tests/`) | Layer | Guarantee |
|---|---|---|
| `safety/test_gate_properties.py` (12 tests, 1,500 generated orders each in the main ones) | L5 | `allow` or `hold` implies: normalised ticker on the allow-list and ASCII, side allowed, quantity x **trusted** price within the per-order cap, daily total within the cap, limit inside the band of the trusted price, mandate signed by the pinned key, unexpired, unrevoked, step-up respected. An independent oracle also checks the converse (a fully permitted order is not refused). Any change to a signed mandate field, a flipped/truncated/foreign/missing signature or a re-signed mandate refuses. The order's own limit price never changes the valuation. Extra order fields (`reference_price`, `approved`, ...) never change the decision. Money movement is never an order. Unverifiable, stale, contradicted or not-yet-public figures, a checker that raises, and missing required figures fail closed. `evaluate` is pure. |
| `safety/test_normalise_properties.py` (13) | L1 | `clean` never raises on random Unicode, removes Unicode 17 default-ignorable characters and reports them, decodes nested base64 and tag-spelled instructions into findings, is idempotent, flags mixed-script tokens (Cyrillic or Greek inside Latin) and not pure-Latin ones, and the gate refuses a look-alike ticker. |
| `safety/test_bucket_properties.py` (10) | L3 | A repeat (shared distinctive number), a dependent claim (shared entity) or anything from a quarantined source is quarantined; transitively through `admit`; unrelated items are not; quarantine only grows and keeps provenance; a failing model never creates a false quarantine. |
| `safety/test_graph_properties.py` (9) | L7 | A rule never fires on fewer than `min_sources` independent unquarantined sources; echoes from one origin or owner count once; one lying venue cannot move the median out of the honest range; a real crash on every venue still fires; quarantined events are inert; blast radius is monotone in lie size and zero for one liar among two honest venues. |
| `safety/test_figure_properties.py` (11) | L6 | On an offline truth store (no network): the same truth is confirmed in USD, millions, billions and thousands; a unit slip is named; quarterly-as-annual and last-year-as-this-year are contradicted; a restated figure is `stale` after the restatement and `not_public_yet` before it; nothing is usable before its filing date; more than 2% off is never confirmed; garbage input never raises and is never confirmed; unknown company is unverifiable; behind L5 only confirmed figures allow. |
| `safety/test_broker_properties.py` (12) | L8 client | The router routes only an exact `allow`; no key means no routing; duplicate keys reach the broker once (also under 32 threads) and a changed order under a used key never does; `SimBroker` never goes negative or oversells; the paper broker fails closed on connection errors, timeouts, HTTP 5xx, non-JSON and every non-`filled` reply; malformed orders send no request. |
| `safety/test_agent_properties.py` (22) | L1-L5 in the loop | The naive arm is offered a transfer tool in every environment and guarded arms never are (a poisoned description cannot bring one back); random call sequences (including calls to tools that are not offered) never move money or exceed the mandate in guarded arms; `max_steps` bounds agent turns; the abandonment notice fires at most once and extra steps are bounded; quarantined web chunks, hidden tag characters and echoes of a quarantined feed claim never reach the model; full-arm tool output is wrapped as `<data>`; a down screen quarantines instead of passing content. |
| `safety/test_attack_corpus.py` (162; marked `slow`, about 12 s) | all | Every one of the lab's cases (A-F plus controls) through the offline credulous agent: **full** arm executes zero harm, zero transfers, no success; **gate_only** never transfers and keeps every executed order on the allow-list within the cap; all clean controls complete in full; the naive arm is hurt (so the corpus is not vacuous). |
| `safety/test_sandbox_determinism.py` (32) | sandbox | Same seed gives the same world digest, scenario and offline run record (also across thread schedules); benign-twin parity holds for every technique over 8 seeds. |
| `e2e/test_receiver_e2e.py` (14) | L8 | Against the real TypeScript bridge: allowed fill, duplicate is a replay with no second effect, refused orders (unlisted, fake split price, sell, oversize, zero/negative) leave the ledger untouched, daily cap, oversize body, malformed bodies, router + paper broker through the receiver, after `/revoke` nothing fills and ledger integrity holds, a stopped bridge fails closed. |
| `guard/`, `lab/`, `verify/`, `app/` (pre-existing example tests) | all | Hand-written scenarios: the exact prototype attacks, CLI, init/doctor, classifier, DoS defence, judge, tables, L6 pipeline, web app API. |
| `receiver/test/*`, `receiver/invariants/` (npm) | L8 | Receiver core and bridge unit tests; 1,000 seeded fault campaigns check the receiver's safety invariants (see `docs/receiver/invariants.md`). |

At the current checkout, pytest collects 744 Python tests; the full offline run completed with 743 passed and 1 skipped. The suite
has no expected-failure markers; historical regressions that once used strict `xfail` are now covered by ordinary passing tests.
The receiver checks run through `npm test`, followed by the separate 1,000-seed invariant campaign in `npm run check`. The
safety suite generates well over 20,000 randomised cases in total.

## Resolved regression findings

The suite has no expected-failure markers. Regression coverage now verifies nested and idempotent base64 normalization, Unicode 17 default-ignorable cleanup, canonical mandate signing with optional `referencePrices`, and quarantine of unsigned authority directives in saved notes. Historical live results still reflect the build that was tested at that time; see `docs/RESULTS.md` for the exact run scope.

## Offline versus live evaluation

The suites above never spend money and never reach a model. The headline results in `docs/RESULTS.md` come from **live** runs of real models,
recorded once by the lab (record) and re-judged offline from `results/` by code (replay): `og-lab tables --check` rebuilds the tables from the
recorded transcripts and fails if the committed file differs, so no number depends on a model being reachable. In replay mode a request with no
recording raises `ReplayMiss`; re-recording needs an explicit live mode, a key and a budget (`OG_BUDGET_USD`). The offline policy agents
(`PolicyLLM`: cautious, credulous, mixed) stand in for a model in the corpus and sweeps: they test the layers, not any model's judgement.

## What is not tested

- Real model behaviour: whether a given model is fooled, and how well the live L2 screen separates attacks from clean text. Only the recorded
  live results speak to that; the offline heuristic screen is deliberately crude (it also flags some clean 10-K paragraphs).
- Live data: EDGAR fetches and any real market feed. L6 is tested on hand-built filings; trusted prices are simulated.
- A real broker: none is shipped. `ReceiverPaperBroker` and the SQLite ledger are the only effect path.
- Browser passkey ceremonies: the bridge uses a synthetic passkey; real WebAuthn hardware is out of scope.
- A full automated browser suite and Docker-image build. The arena page has a jsdom rendering test; key order-check and recorded-feed flows were also exercised manually in a local browser during this build. Performance measurements are simulated single-process authorization, not production load.
- An `OrderGate` built without a pinned `public_key` does not check the signature (it still checks expiry and revocation); the tests pin the key
  and one test documents the unpinned behaviour. Callers must pin it.
- Adversaries outside the threat model in `docs/THREAT-MODEL.md` (a compromised trusted data source, a compromised owner key).
