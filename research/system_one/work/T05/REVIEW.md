VERDICT: REVISE

# T05 review — round 4 output

Reviewer: fresh adversarial run. Context: tasks/T05-text-channel.md, POLICY.md,
work/T05/REPORT.md, work/T05/check.log, and the binding SOL_ADVICE.md (lead
ruling 2026-11-19 + round-3 addendum). Nothing else assumed. The substance of
the task is met and every metric reproduces; the verdict is REVISE for one
verified false provenance sentence in the generated report block and two
small consistency hardenings in the same script (fixes 1–3 below). All three
are one-file, one-run fixes of exactly the "provenance and consistency" class
the lead's addendum ordered for round 4.

## 1. What I re-ran and what it printed

### 1.1 Entry point: `bash work/T05/run.sh` (full re-run, exit 0)

Run in a clean shell with OPENROUTER_API_KEY ABSENT, which exercises the
cached path the report claims makes a reviewer's re-run free. It printed
(abridged; full log now in work/T05/check.log):

- missing: [] ; versions logged (numpy 2.5.5, torch 2.15.0, transformers
  5.23.0, sentence-transformers 6.3.0, scikit-learn 1.9.1, pytest 9.2.0, ...).
- all four reader weights already cached under data/models/hf.
- preregistered configuration sha256: 79eda5f9...9caf6 (matches static file).
- wrote 2100 rows; per-class counts 350/350, 350/350, 369/331; groups 9/9/4.
- training/ref 6-gram audit: 0 overlapping rows of 2100.
- reader 3: hype row/group holdout 1.0000/1.0000; authority 0.9973/1.0000;
  support 0.8720/0.8113; wrote embed_lr.joblib (20441 bytes).
- eval actions: 1440 from 360 episodes; by shift 720/720.
- scored lexicon, nli, embed_lr, injection, injection_fmops;
  scored decision model (1440 cached calls, $0.042320) — zero new spend,
  no key present.
- authority templates: 0.6555 / 0.6757 / 0.6088 / 0.5360 / 0.9996 —
  identical to the delivered run.
- eligible pass readers: hype decision 1.000 delta 0.329 [0.258, 0.400];
  authority decision 0.924 delta 0.079 [0.018, 0.149]; support decision
  0.998 delta 0.155 [0.096, 0.224]; all beats=True.
- PASS BAR line + AUTHORITY RULING line as delivered.
- tests (online): 12 passed in 10.20s; tests (offline, HF_HUB_OFFLINE=1
  TRANSFORMERS_OFFLINE=1): 12 passed in 9.31s; "og_s1.text imports offline".

Artifact diff vs the delivered snapshot (taken before my re-run): the ONLY
differences in results.json are latency values and run_id (16 fields). Every
AUROC, CI, delta, calibration value, holdout, cost and count is identical to
<1e-9. The regenerated REPORT.md generated block is byte-identical to the
delivered one. PREREGISTERED.md and latency_runs.json hashes unchanged;
latency_history.jsonl gained exactly one appended row (7 -> 8); check.log has
one "12 passed" line per suite, no duplicated tail, no secrets/home paths.
My re-run's local latencies were higher than the frozen ranges (nli p50
244.6 ms, p99 935.8 ms; another lab task was loading the machine) — consistent
with the report's disclosed "wall-clock varies with machine load" design; the
frozen reported ranges are untouched by a reviewer re-run, as claimed.

### 1.2 Independent recomputation (reviewer probe, read-only, scratch dir)

- Rebuilt the exact sample from data/ref with seed 20261119: 1440 actions,
  360 episodes; shift flags consistent with file names; cause vocabulary
  matches the declared mapping; shifted positives 38/58/70 as reported.
- Recomputed AUROCs with sklearn (independent of og_s1.checks.auroc) from the
  cached decision responses and fresh lexicon scoring: all 12 reader x
  feature x shift combinations match results.json to <= 1.1e-16.
- Reimplemented the paired episode bootstrap for the contested authority
  comparison (seed 20261119+100+1, 1000 reps): delta 0.079018,
  CI [0.017621, 0.148934] — EXACT match to results.json; excludes zero.
- Recomputed decision-reader calibration (ECE/Brier, shifted): 0.287686 /
  0.111807 (hype), 0.553105 / 0.416258 (authority), 0.208542 / 0.074143
  (support) — exact matches; n = 592/612/624.
- Decision cache: 1440 rows, 1440 unique sha256 keys; 1440/1440 keys hit
  using the CURRENT question strings and state builder — every scored
  response was produced by exactly the pre-registered questions. Per-row
  latency_s 1.07–2.37 s, p50 1149.99 ms (= reported 1150.0). Cost summed from
  API usage.cost = $0.042319914 (= reported $0.042320). No key, request body,
  bearer string or home path anywhere in the cache.
- Ran report_numbers.build() on the delivered results.json: reproduces the
  delivered REPORT block and numbers.md byte-for-byte; §3.8 latency ranges
  and the 4.3–7.6x ratio reproduce from the four frozen named runs; the
  runs/ archives agree with latency_history.jsonl.
- NLI checkpoint config id2label = {0: entailment, 1: neutral,
  2: contradiction}; the reader selects the entailment index by label name —
  correct, no label-order bug. Licences verified from cached model cards:
  MIT (NLI), Apache-2.0 (MiniLM, ProtectAI, fmops) — matches REPORT §1.
- Max-logit slope check (the defect): authority/decision univariate slope
  fit POOLED (both shifts) = 2.527, matching the delivered 2.5274835;
  fit on shifted-only = 1.783, which does NOT match. See fix 1.

## 2. Pass bar — item by item

1. **The tests pass.** MET. 12/12 online and 12/12 offline in my re-run.
   The suite covers the brief's three required checks (range [0,1],
   determinism, T03 action-order alignment — the latter against an
   independent per-step lexicon calculation) plus causal-input, label/meta
   invariance, 0.5 no-source support, canonical cache key, and the ruling's
   no-fallback authority behavior (NaN + reason without cache/key; finite
   from a seeded cache offline).
2. **Best reader beats the lexicon on shifted ref for each feature, with
   episode-bootstrap CIs.** MET, under the binding ruling's terms: official
   floor = small registered lexicon; authority carried only by the
   pre-registered generic decision question. Eligible pass readers: hype
   decision 1.000 (delta 0.329 [0.258, 0.400]); authority decision 0.924
   (delta 0.079 [0.018, 0.149]); support decision 0.998 (delta 0.155
   [0.096, 0.224]). All three CIs exclude zero; the authority interval was
   reproduced by an independent bootstrap implementation. The ref-selected
   NLI authority template (1.000) is correctly excluded from the bar and the
   channel, kept visible as sensitivity (§3.2/§3.5), per SOL_ADVICE.
3. **Latency is reported.** MET. §3.8 quotes p50/p99 ranges per reader and
   device over four frozen named runs; local readers are timed per action,
   serial, after warm-up; the decision reader's figures are the recorded
   first-live-call round trips replayed from cache (mechanism verified;
   disclosure wording — fix 3). My fresh run's latencies append to history
   without moving the frozen ranges, as designed.
4. **Model downloads cached under research/system_one/data/models/.** MET.
   Four checkpoints, 1.6 GB under data/models/hf; fetch_models.py is
   idempotent and made no network request on my re-run. The POLICY 500 MB
   conflict is resolved by the lead's explicit exception in the SOL_ADVICE
   addendum (exactly these four CPU checkpoints), recorded in REPORT §5.11.
5. **og_s1.text importable and runnable offline once cached.** MET. All
   readers load with local_files_only=True; the offline test suite and the
   offline import both passed in my re-run with no key and no network.

SOL_ADVICE compliance (binding): authority default = decision with NaN+reason
and no NLI fallback (code + tests verified); pass_bar computed only over
eligible readers; one bootstrap seed per feature across all comparison
tables (verified in code and by exact CI reproduction); PREREGISTERED.md
static, hash-checked against the LIVE reader strings, run.sh fails on
mismatch; the four-checkpoint cache exception recorded; every number in the
generated block produced by report_numbers.py from results.json (verified
byte-for-byte). The one residual provenance error is fix 1.

## 3. Required fixes (in order of importance)

1. **REPORT §3.9 misstates the fit sample (verified false provenance).**
   The generated sentence says the univariate logistic slopes were fit "on
   shifted ref". evaluate.py's max_logit_contribution block fits on ALL
   1440 records (both shifts pooled; no shift filter), and results.json's
   own assumption string correctly says "on the reference sample". Proof:
   authority/decision slope pooled = 2.527 (= delivered 2.5274835);
   shifted-only = 1.783 (!= delivered). Fix: in work/T05/report_numbers.py
   change "on shifted ref" to "on the pooled ref sample (unshifted +
   shifted)" and re-run run.sh (or report_numbers.py) to regenerate
   numbers.md and the REPORT block. No metric changes. (Alternative:
   actually fit on shifted-only in evaluate.py and regenerate all numbers —
   but the prose fix matches the delivered artifact and the placeholder's
   stated purpose.)
2. **Generated MET verdict uses point estimates only.**
   report_numbers.py computes "Eligible pass bar: MET" from
   beats_lexicon (delta > 0) alone. The lead's criterion is a CI that
   excludes zero. All three current CIs do exclude zero, so no current
   number or conclusion changes — but a future run with delta > 0 and a CI
   crossing zero would print MET against the ruling. Fix: require
   delta_ci_excludes_zero as well (the field already exists in
   results.json). Same file, same regeneration as fix 1.
3. **§3.8 should state that decision latency is replayed, not re-measured.**
   The decision reader's p50/p99 are the latency_s recorded at the first
   live call, replayed from the cache on every later run (verified: constant
   1150.0/1657.4 across all runs, equal to the cache's stored values).
   "The network decision reader includes the round trip" plus §3.11's
   "cached request latency" hint at this but do not say it; a reader could
   take §3.8 to mean each run re-measures network latency. Fix: one sentence
   in report_numbers.py's §3.8 prose, e.g. "The decision reader's latency is
   the round trip recorded when each response was first fetched live; cached
   re-runs replay it and do not re-measure the network." Same regeneration.

All three fixes live in work/T05/report_numbers.py (fix 1 may alternatively
touch evaluate.py), change no metric, and are re-runnable with the single
entry point. Process note: the lead's addendum calls round 4 final; these
are residual items of exactly the provenance/consistency class round 4 was
ordered to fix, so if the worker-round budget is exhausted the lead may
apply or accept them directly rather than open a new round.

## 4. Loopholes found and checked

- **§3.9 sample mislabel** — the one real finding (fix 1). Everything else
  below was checked and held up.
- Test-set peeking / leakage: no code path reads data/heldout*, work/T02*
  or work/T06 (grep + full code read); evaluation uses data/ref only, as the
  brief directs. Training text is generated from the worker's own templates
  (make_train_text.py never opens data/ref); an independent 6-gram audit
  against every ref document/note/rationale/claim finds 0/2100 overlapping
  rows and fails the run on any overlap. Reader 3's template-group holdout
  (0.811 support) is reported alongside the optimistic row split (0.872),
  and reader 3 is selected for nothing.
- Ref-tuned authority template: the 0.9996 "restriction has been lifted"
  hypothesis was chosen on shifted ref — disclosed, quarantined as
  sensitivity, excluded from the pass bar and from DEFAULT_READERS, frozen
  in PREREGISTERED.md for T07/T11. The extended lexicon (1.000, an oracle on
  ref) is likewise sensitivity-only. This follows the binding ruling exactly;
  the report does not hide either number (§3.2, §3.4, §3.5, §4).
- Decision-question drift: cache keys are sha256 of the canonical request;
  1440/1440 hit with the current strings, so no question was edited after
  the responses were bought. The questions are generic feature-definition
  paraphrases with no ref-specific phrase, frozen and hash-enforced.
- Causal input: channel and tournament both consume only
  schema.model_view_at(episode, i) (documents filtered by t, notes by
  availability, theses without final status, no meta/label). Tests perturb
  future documents/notes/actions and all labels/meta and assert invariance.
- Metrics: AUROC is tie-averaged rank AUROC, cross-checked against sklearn
  to machine precision; bootstrap resamples whole episodes, deltas are
  paired on the same draws, one seed per feature shared across tables;
  negatives are all y=0 actions and other-cause y=1 actions are excluded
  (target -1), not silently counted as negatives; calibration ECE/Brier
  recomputed exactly. No metric error found.
- Hard-coded results: the entire §3 generated block reproduces byte-for-byte
  from results.json via report_numbers.py; cost comes from API usage.cost;
  prose numbers in §§4–7 match the artifacts (holdouts, counts, AUROCs,
  $0.04, 20 KB, 1.6 GB, 58 positives). No hand-typed result found.
- Seeds/thresholds after seeing test data: sampling seed 20261119 and
  training seed 12345 are fixed in run.sh/scripts; bootstrap seeds are
  deterministic functions of the sampling seed; no threshold tuning exists
  (features are raw reader outputs; the 0.5 neutral is brief-mandated).
- Secrets / paths: grep over work/T05 and og_s1 channel/readers/tests found
  no key, bearer string, or absolute home path; the cache stores only
  sha256 key + status + latency + response; the key is read from the
  environment and my key-less re-run succeeded entirely from cache.
- Isolation / policy: no git use, no writes outside the task folder +
  data/models (the brief places og_s1/text.py, readers and tests outside the
  task folder explicitly); task folder 1.8 MB, no file > 5 MB; spend $0.0423
  < $2 cap; no real orders; no GPU reader chosen (T10/D10's remit).
- Fragility notes (minor, no fix required beyond the three above):
  empty-text hype/authority defaults to 0.5 in both channel and tournament
  (consistent, but §5.9 documents only support's neutral); decision.score's
  nan_to_num(0.5) makes score_view's "returned no answer" branch unreachable
  (a missing answer would silently become 0.5 — no effect here, all 1440
  responses carry all three answers); §3.8 prose hard-codes "1,440 actions"
  rather than reading corpus.actions; the decision reader's (n,3) interface
  deviation is documented in the package docstring and §5.5.
- Overclaims: none found beyond fix 1. The report is unusually candid —
  injection classifiers near chance, reader 3 weak on support, NLI latency
  above the 300 ms target in most runs, decision model badly calibrated on
  authority (ECE 0.553), the round-1 contamination, and the round-1-review
  template discrepancy are all in §4/§7. The "what ref cannot tell us"
  paragraph required by the ruling is present (§3.12).

## 5. Bottom line

Every pass-bar item is met and every number reproduces — AUROCs, CIs,
calibration, costs and holdouts matched an independent recomputation to
machine precision, and a full key-less re-run regenerated the delivered
report block byte-for-byte. The single verified defect is a false sample
description in generated prose (§3.9 "on shifted ref" for a pooled fit),
plus two cheap hardenings in the same script. REVISE with fixes 1–3; after
them this is a PASS. No escalation is needed: the lead's ruling already
settled the only high-level question (floor and eligible authority reader),
and the work follows it.
