# T04 Review

VERDICT: REVISE

(provisional — full `bash run.sh` re-run is still in progress; this file will be updated with the completed re-run and final verdict. The provisional verdict is REVISE for the reasons below.)

## What I have re-run so far, and what it printed

- `work/T04/run.sh` was started at 2026-11-20T01:01:13Z and is still running at the time of writing. Earlier recorded attempt in `check.log` (started 2026-11-19T23:59:31Z) ended with `===== TIMEOUT after 2700s` during the full reference evaluation, after seed-4 logistic. The runner's check timeout is 45 min (`lab/run_lab.py:515`).
- `bash run.sh` current run: 14 T04 tests passed (`14 passed in 5.25s`); fake `--test` directory built; full reference evaluation entered; seed 0 fitting started. Full result not yet available.
- Independent single-seed full evaluation (all five models, 1,000 bootstraps, `--seeds 1`, no run.sh thread pinning), completed in 550 s wall-clock:
  - logistic `ref_test` AUROC `0.9961840947939566`, tau `0.179261` — exactly the JSON seed-0 value.
  - hgb `ref_test` AUROC `0.9969030127446388` — exactly the JSON seed-0 value.
  - EBM `ref_test` AUROC `0.9966541215391249` vs JSON seed-0 `0.996654047938361`; `cal_tau` `0.151809` vs stored `0.151804`; attribution overall accuracy `0.631951` vs stored `0.632113`. The EBM is not bit-reproducible with `n_jobs=4`, although the reported 4-decimal table is unlikely to move except possibly the EBM top-cause cell.
  - Latency without the run.sh thread pins was much larger for HGB (`p50` 8.655 ms, `p99` 21.425 ms) than reported; this is expected from OpenMP contention and is not a metric failure, but it confirms latency is environment-sensitive.
- `work/T04/build_report.py` re-rendered `REPORT.md` byte-identically from the stored JSON (`diff` empty).
- Verified the fake-test Brier/ECE coincidence is real, not a metric bug: the fake model trained on 40 authority-spoof episodes gives near-zero scores on clean/drift/misquote and near-one on authority/poisoned; ECE and Brier both come out at ~0.0617 by construction. The fake test is a path proof only, as the report says.

## Pass bar

- Tests pass: **met** (14 passed; the full suite also has 131 passed in `check.log`).
- Metric implementations checked against sklearn: **met** (AUROC and Brier tested against sklearn; ECE hand cases; threshold and bootstrap tests present).
- EBM monotonicity check passes for every feature and every bin: **met as implemented**, but see loophole 3: the certificate enumerates only main effects after `remove_terms`, and the code never asserts that interaction removal actually left a purely additive model. The current run reports 41 checked features, all monotone.
- Results on ref and ref shifted reported with CIs: **partly met**. AUROC/Brier/ECE/hold/recall carry bootstrap CIs. Lead-time CIs exist in `results_ref.json` but are not shown in `REPORT.md`; attribution has seed spread only, no episode-bootstrap CI (the report admits this under Open risks).
- No held-out paths used: **met in code and outputs; isolation procedure breached in the report's own account** — the worker says it ran a directory listing of `data/heldout` (names only, no data opened). The brief says do not open `data/heldout*`.
- Latency numbers reported: **met**, though only for one machine and one thread pinning, and the numbers are not reproducible across a loaded machine.

## Required fixes (provisional, in order)

1. Make the one-command entry point finish inside the runner's 45-minute check window and report the latest timeout honestly. The most recent `check.log` run timed out after 2,700 s; `results_ref.json` records `runtime_seconds` of 50,406 s (14 h wall-clock). The report currently presents the older completed capture as if it were the current state and does not mention the timeout. Either reduce the cost (fewer bootstrap resamples only if the brief permits; cache features; avoid re-loading/featurising shifted data), or state clearly that the check is not reproducible within the runner's timeout and why. `POLICY.md` hard rule 7 requires reporting this.
2. Restore exact reproducibility or stop claiming it. Section 3.6 says AUROC/Brier/ECE/hold/recall are "deterministic given the fixed seeds"; the EBM is not deterministic under `n_jobs=4` (seed-0 rerun differs in the 7th–8th decimal and in attribution at 4 decimals). Either pin EBM parallelism to 1 (and represent the cost), or record and report the run-to-run variation and withdraw the determinism claim.
3. Close the EBM additivity/certificate loophole. `_drop_interactions` swallows exceptions and returns 0; nothing asserts `all(len(f) == 1 for f in clf.term_features_)` afterwards, and `remove_terms` in `interpret` 0.7.8 does not update `bins_`. Add an assertion, record how many interaction terms were removed, and make the certificate check the post-removal bins explicitly. Otherwise the "additive glass box" certificate can silently certify the wrong shape functions.
4. Mark the post-hoc reference-test inspection as a peeking event and decide its consequence. `REPORT.md` §6 admits inspecting reference-test attribution rows after the captured run. The brief says the test is held out and `POLICY.md` says "if you looked at it, say so: that result is void." The attribution result (at least) should be labelled void or reproduced on a fresh test view; do not use the inspected rows for any claim.
5. Report the isolation breach and prevent recurrence. The worker's own account says it listed `data/heldout`. No content was read and no code uses held-out paths, but the brief forbids opening it; the report should state the breach plainly and the review must treat it as a process failure even though the numbers are not contaminated.
6. Report the missing CIs or state the limitation in the pass-bar section. Lead-time CIs are in the JSON but absent from the report; attribution has no bootstrap CI. The brief asks for 95% bootstrap CIs and 5-seed spread; show the lead CIs and either add an episode-level attribution CI or explicitly scope the CI requirement to the headline metrics.

## Loopholes found

1. **No-test-peeking loophole.** The worker inspected reference-test attribution rows after the run, then said nothing was changed. That is still test-set inspection under `POLICY.md`; the disclaimer does not make the attribution result unseen.
2. **Held-out isolation breach.** A directory listing of `data/heldout` is an opening of the forbidden path under the brief; only names were seen, but the rule is absolute.
3. **EBM certificate scope.** The certificate checks main-effect bins only. If `remove_terms` failed (the helper catches all exceptions and returns 0) or term ordering changed, the report would still say "additive" and "monotone" without proving it. `remove_terms` also leaves `bins_` untouched in `interpret` 0.7.8; the main-effect indices happen to stay aligned because interactions are appended, but the code does not check that invariant.
4. **Reproducibility loophole.** The report says the wall-clock field can include machine sleep and that the current run is faster, but it never reports CPU time, and the latest actual check timed out. A number that reproduces only after 14 h is not a one-command reproduction for the runner.
5. **CI loophole.** "Results ... with CIs" is satisfied for the headline metrics but not for lead time/attribution; the report's open-risk note does not turn a missing pass-bar item into a met one.
6. **Fake-test interpretation.** The fake test is correctly labelled non-substantive, but its Brier/ECE coincidence looks odd; I verified it is the expected artifact of training on one family and testing on five. No fix needed.
7. **No held-out data in features.** `featurize` uses `model_view_at`; `meta` and labels are only split/score inputs. I found no label/meta/future-state leak in the feature path.

## Status

Full `bash run.sh` re-run in progress. This review will be updated with the final table, exact number comparison against `REPORT.md`, and the final verdict. The provisional verdict remains **REVISE**.
