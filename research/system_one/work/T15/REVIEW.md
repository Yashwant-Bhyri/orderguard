VERDICT: REVISE

(provisional — final pass-bar confirmation pending the full re-run now in progress;
the required fixes below are already evidenced and will not change)

# T15 review — frozen evaluation spec and model-neutral reader adapter

Context used: tasks/T15-eval-spec.md, POLICY.md, work/T15/REPORT.md,
work/T15/check.log, the worker's code and tests, og_s1/schema.py,
og_s1/checks.py, docs/vision/lab/COMBOS.md (sections 0/3/4), lab/run_lab.py.
No SOL_ADVICE.md exists in work/T15/, so there is no binding ruling to apply.
The round-2 ESCALATION.md in the folder is historical: its question (empirical
vs finite-sample bound) was answered by the round-3 implementation, which this
review verified independently (see below). No new escalation is needed.

## What I re-ran and what it printed

1. `bash run.sh` from work/T15/ in a clean shell (no PYTHONPATH): FAILED.
   41 tests passed and the spec hash printed, but evaluate.py died with
   `ModuleNotFoundError: No module named 'og_s1'` (capture
   20261120T030438Z-18450.log). Cause: og_s1 is not installed in .venv;
   `python work/T15/evaluate.py` puts work/T15 on sys.path, not the
   system_one root. The lab runner injects PYTHONPATH=ROOT for every
   non-isolated child (lab/run_lab.py:243), which is why every worker/runner
   capture succeeded. See loophole L1 — hardening item, not a pass-bar fail.
2. `PYTHONPATH=<system_one root> bash run.sh` (runner-equivalent environment):
   re-run in progress at the time of writing; result appended below.
3. Independent metric verification (reviewer script, not worker code):
   rebuilt the 640-episode / 76,800-action corpus and the owner split from
   data/ref with the worker's extraction, then recomputed EVERY pooled metric
   with independent implementations — sklearn roc_auc_score, a hand-written
   ECE, a Clopper-Pearson upper bound computed by root-finding on the exact
   binomial CDF (not scipy.stats.beta.ppf), and a brute-force search of the
   fixed 101-point grid using calibration data only. Result: ALL_MATCH
   against the cited capture 20261120T024510Z-13418 — corpus counts, split
   counts, tau=0.99, cal_upper=0.0268 (12,556 allowed / 278 bad), test
   realized 0.0168 (208 bad / 12,207 good allowed), AUROC 0.9963 / 0.5000,
   ECE 0.0042 / 0.2947, top cause 15/2,945, pointer 1,434/1,854, false holds
   794.7266 / 0.0000, escalation 1.0000 / 0.0001, for both readers.
4. Programmatic diff of REPORT.md against the cited capture: 595 numbers
   checked. All corpus/split/rendering-length/pooled/slice point estimates
   and all capture-printed CIs match EXCEPT the items in Required fixes.
5. `shasum -a 256 og_s1/eval/SPEC.md` =
   ad9650c87f929018e4a474d133957cc6729fd4b361807f155e1be7a9d7233896,
   identical to SPEC.sha256, to the report, and to every round-3/4 capture.

## Pass bar

1. Case extraction reads only model_view_at; a test proves no future field
   reaches a Case — MET. cases.py builds every Case from model_view_at
   (schema.py:372 strips labels/meta, filters documents/notes/theses by time,
   drops thesis status); code_features come from checks.featurize, which also
   reads only model_view_at per action. test_no_future_field_of_any_kind_
   reaches_case creates a future thesis and mutates every future
   thesis/document/note/action field plus all labels and meta, and asserts
   byte-identical earlier Cases WITH and WITHOUT code features;
   test_no_future_field_reaches_case also appends a future step and checks
   episode-key stability. 41 tests passed in my re-run attempt.
2. Group-split leak test passes — MET. Random-row, manual group-leak and
   episode-on-both-sides splits all raise in tests; the real owner/episode
   splits assert both group and episode disjointness in evaluate.py; the
   company split's 640/640 episode overlap is printed and labelled "NOT a
   generalization test". Author/agent axes are explicitly unavailable on
   data/ref (1 author, no agent_id) — the most defensible handling, recorded
   in Judgement calls 5.5; the splitter is tested on synthetic multi-group
   data.
3. Every metric has a unit test on a hand-computed example — MET. I verified
   the arithmetic of every hand example myself (AUROC 0.75; ECE 0.4;
   empirical midpoint tau 0.595 with upper 1/21; conformal tau 0.29 with
   B=0/A=205; hold-all; fail-closed coverage 1/3 on [0.1, nan, nan, 0.5];
   fail-closed AUROC 0.5 with answered-subset 1.0; top-cause 0.5 incl.
   missing prediction; pointer 2/3 incl. size cap and None; false holds 250;
   escalation 0.25; cost mean/p50/p99/gpu-per-1000). All correct.
4. Spec hash printed and stable across two runs — MET (pending final
   confirmation from my full re-run). Hash printed before/after in every
   capture; identical across the cited capture, the runner's 025330Z capture
   and my partial run; matches the file bytes and SPEC.sha256.

## Required fixes (in order of importance)

1. REPORT.md 3.3: the top-cause and pointer bootstrap CIs are stale — they
   do not match the deterministic results.json produced by the cited
   capture's code. Report vs results.json (value [lo, hi]):
   - owner top-cause: report [0.0014, 0.0103], actual [0.0017, 0.0094]
   - owner pointer: report [0.6361, 0.8935], actual [0.6112, 0.9144]
   - episode top-cause: report [0.0014, 0.0081], actual [0.0020, 0.0076]
   - episode pointer: report [0.5436, 0.8081], actual [0.5513, 0.7985]
   - company top-cause: report [0.0058, 0.0115], actual [0.0058, 0.0114]
   - company pointer: report [0.6315, 0.7186], actual [0.6298, 0.7376]
   The point estimates and every capture-printed CI match; only these
   six intervals (which the capture CSV does not print) are wrong. The
   pattern — tau-dependent metrics stale, tau-independent escalation CIs
   correct — indicates they were carried over from the pre-round-3
   empirical operating point. Regenerate them from the cited run's
   results.json (and preferably print them in the capture so future reviews
   can diff them directly). Forensic confirmation pending (see below).
2. REPORT.md 3.5, company/behavioural row: escalation is printed as 0.0000
   but the cited capture and results.json give 0.000125 (2/15,999 escalated),
   which formats to 0.0001. Fix the cell.
3. (Hardening, non-blocking) run.sh depends on an ambient PYTHONPATH that
   only the lab runner supplies; in a clean shell the entry point fails
   after the tests. Export PYTHONPATH="$PWD" (or equivalent) inside run.sh
   and/or document the requirement in REPORT.md section 2, so the one
   command works outside the runner too.

## Loopholes checked

- L1 (entry-point environment): see fix 3. The lab check itself passes
  (runner capture 20261120T025330Z-15608 in check.log reproduces every
  deterministic line), so this is fragility, not a broken check.
- L2 (test-set peeking): threshold selection uses calibration only
  (verified in code and by my independent reimplementation); the logistic
  model fits on train only; slices use the pooled tau; the fixed grid,
  band, fractions and seeds are data-independent constants. The round-3
  switch from the empirical rule to Clopper-Pearson/Bonferroni was made
  after earlier test overshoots were observed, but it moved to a stricter
  a-priori rule with a finite-sample guarantee — the option the round-2
  escalation itself named — not a threshold tuned to test data. Disclosed
  in REPORT 5.2 and Round 3 changes. Acceptable.
- L3 (conformal claim soundness): I verified the math independently. For
  each fixed grid tau, conditional on A allowed calibration cases, B is
  binomial under exchangeability; the exact CP upper bound at delta/101
  plus the Bonferroni union over the 101 data-independent candidates gives
  >=95% simultaneous coverage, so the selected tau's population conditional
  false-allow rate is <=0.05 with >=95% confidence; transfer to test needs
  the usual cal/test exchangeability. The report states exactly this limit
  ("calibration bound, not a test-set oracle"; realized test shares are
  descriptive). This satisfies the brief's "conformal false-allow bound of
  0.05" in the finite-sample sense the escalation question asked for.
- L4 (abstention gaming): coverage keeps None clean test cases in the
  denominator (fail-closed); calibration None cases are excluded from A,
  which is exactly equivalent to holding them; AUROC ranks None above all
  answered risks and reports the answered subset; ECE assigns None risk
  1.0; missing cause/pointer predictions count as misses; pointer sets are
  size-capped. Tested with hand examples. No denominator-shrinking hole.
- L5 (isolation): no code path opens work/T02*, work/T06 or data/heldout*;
  the only mentions are out-of-scope prose in SPEC.md. evaluate.py reads
  data/ref only. My own grep for secrets/absolute home paths in all
  deliverables found nothing; check_artifacts.py scans work/T15 and all of
  og_s1 and reported 0 hits in the cited capture.
- L6 (labels into Cases): cases() never calls labels(); Case has no
  label/meta/status field; shift-axis tags are attached after extraction
  and stripped by reader_view() before scoring (asserted in my rebuild:
  every cal/test case had shift_axes == ()).
- L7 (hand-typed results): 595 report numbers diffed against the cited
  capture; the only mismatches are fixes 1-2. Everything else is produced
  by evaluate.py. No hard-coded metric values in code.
- L8 (seed shopping): split/bootstrap/reader seeds are the fixed date
  constant 20261119 in code, unchanged across rounds; no evidence of
  post-hoc selection.
- L9 (company split overclaim): labelled episode-overlapping everywhere,
  overlap count printed; headline generalization claims rest on the
  owner/episode splits only. Author/agent never faked with proxies.
- L10 (capture provenance): two orphan captures without index lines are
  explained: 20261120T000357Z-80430 failed the artifact check (bytecode
  caches present at the time), and 20261120T022248Z-7298 is the completed
  run whose malformed index line round 4 removed. Audit trail intact; the
  cited capture is immutable and present.
- L11 (trivial-reader limits): top-cause adapter cannot predict vague_hype
  at all (CAUSE_GROUPS omits it) and defaults to "clean" below a 0.5
  feature max; the report discloses the adapter is weak and forbids cause
  claims from these numbers. The preference slice has zero positives by
  design (synthetic clean is never a preference positive), per the brief's
  own rule. Both are honest, disclosed limitations of a plumbing task.

## Re-run result (appended when complete)

(pending)
