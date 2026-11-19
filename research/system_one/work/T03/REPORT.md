# T03 — Code checks v2: provenance, span verification, drift, staleness

## 1. What I built

A deterministic, causal feature layer for System One's first line of defence.

- `og_s1/checks.py` — `featurize(episode, *, timings=None) -> (X, names, groups)`.
  It walks the steps in time order and, for action *i*, reads **only**
  `og_s1.schema.model_view_at(episode, i)`: documents published by then, notes
  written before the action, theses opened by then (without their final
  `status`), the earlier actions, and the current action. It never reads a
  label, `meta`, rationale, claim prose, note prose or document prose, except
  the exact-substring test that the schema requires for a quoted span. It does
  not use `re` or any keyword list over text. The book state (positions, sector
  values, cash, daily turnover, the drift CUSUM) is updated incrementally from
  the earlier actions, so no future document, note or final thesis status can
  enter a row.
- **41 features** in the cause groups below. Every feature is oriented so that a larger
  value means more risk, so a monotone scorer can consume the columns without
  sign changes.
  - **drift:** out-of-band book weight after the action; the increase in
    out-of-band weight caused by this action; a Bernoulli CUSUM of out-of-band
    buys; daily turnover divided by `max_daily_turnover_pct`; post-action
    instrument position divided by `max_position_pct`; the position excess; the
    traded sector's excess after the action; the count of sectors outside their
    bands; the worst sector excess. The CUSUM is
    `S_t = max(0, S_{t-1} + x_t - 0.5)`, with `x_t = 1` exactly when the action
    is a buy that leaves the traded sector above its `max`.
  - **unsupported_claim:** share of **all** claims (numeric and non-numeric)
    with no source; share whose source document is not available at the action
    time; share whose quoted span is absent, blank or not an exact substring of
    the source; share whose unit is absent from the source's facts (checked for
    every claim that carries a unit, and for every numeric claim); share of
    numeric no-span claims whose value matches no same-unit fact; and the
    maximum of those shares. The value-fidelity checks themselves stay
    numeric-only.
  - **misquote:** the maximum relative error between a valid-span numeric
    claim and the nearest same-unit (or same-dimension) source fact; the
    cross-unit scale error; a binary raw-number unit-swap indicator; and the
    maximum of those. Units are canonicalised only from the structured `unit`
    field (`%`, `pct`, `bp`, `$B`, `$M`, `$K`, `$T`, `ratio`, `x`, and the
    corresponding word forms) into a dimension and a scale.
  - **poisoned_note:** share of cited notes that are external/tool and cite
    no document or any trust-tier-0 document; share of cited notes that are
    unsigned and not written by the agent; share of cited notes not available in
    the causal view; share of cited notes with a trust-tier-0 citation; and the
    maximum of the first three.
  - **authority_spoof:** the conjunction of an unsigned cited note and an
    action-specific permission excess; the conjunction with a sector-band
    breach; the permission excess itself (traded sector on the side that can
    breach, traded instrument cap, instrument not in `allowed_instruments`);
    whether any unsigned note was cited; the instrument-not-allowed indicator;
    and the action-specific band-breach indicator.
  - **stale_thesis:** time since the thesis's newest evidence; time since
    the thesis opened; whether its numeric invalidation trigger is met by a fact
    in a document published strictly after `opened_t`; the same restricted to
    documents of trust tier at least 2; the conjunction of a fired trigger and a
    buy that adds exposure; the age of the firing document; and the inverse mean
    trust of the thesis's evidence documents.
  - **evidence_quality:** inverse mean trust tier of the cited documents;
    share of social documents; share of tool-output documents; share of
    low-trust documents. This group is descriptive, not a cause detector.
- `og_s1/tests/test_checks.py` — **36 tests**. They cover point-in-time
  correctness (mutating future documents and notes, final thesis status, labels
  and `meta` leaves earlier or all rows unchanged; a document at the action time
  is visible and one at the next time is not; a same-step `pre_note` is visible
  and a same-step `new_note` is not), unit-swap detection (`%`/`bp`,
  `$M`/`$B`, and a correct conversion that must not be flagged), no-source,
  absent/blank/foreign spans, unit-absent, relative-value, non-numeric
  unsourced, unavailable-source and unit-absent claims, a non-numeric claim
  with a valid quote that must not be flagged, note-provenance, authority,
  staleness, CUSUM, drift-sell, mixed-trust note citations, clean-reference,
  family-separability, AUROC hand-computation, p99 latency, and a guard that
  the feature module never materialises the whole-episode `model_view`.
- `work/T03/evaluate.py` — loads the reference corpora, calls `featurize`, reads
  labels **only for scoring**, and prints the corpus counts, label rates,
  latency, separate end-to-end and featurisation-only throughput, the best
  single feature per cause group on clean and shifted data, the evidence-quality
  sanity number, a descriptive claim-support number for `vague_hype`, and the
  pass-bar verdict.
- `work/T03/run.sh` — the single entry point. It runs the T03 tests, the full
  repository test suite, and `evaluate.py`, and writes the whole run to
  `work/T03/check.log` as a labelled capture block. Each invocation appends a
  block headed `captured run <UTC timestamp>`; the block used for the numbers
  below is identified in Section 2.

Isolation: I read the repository's schema, sprint, policy and reference data
(`data/ref/`), the `og_s1/` package and the T01 report. I did not open anything
under `work/T02*`, `work/T06` or `data/heldout*`, and I ran no git command.

## 2. How to re-run (one command)

```
bash research/system_one/work/T03/run.sh
```

From inside `research/system_one/work/T03/`, `bash run.sh` is equivalent. The
script appends a labelled block to `work/T03/check.log`; it never truncates the
log, so a reviewer rerun preserves every earlier block. At the time of this
report, `check.log` contains the historical captures
**`20261119T032431Z`**, **`20261119T032852Z`** (whose header and end markers
each appear twice) and **`20261119T033054Z`**, plus the round-4 captures
**`20261119T050608Z`**, **`20261119T051057Z`** and **`20261119T051628Z`**.
The Round 3 report wrongly said that `032431Z` was the only block; this section
supersedes that statement. Every current measured result in Sections 1 and 3-7
is printed by the capture headed **`captured run 20261119T051628Z`**. The AUROC values and corpus counts are
deterministic; the latency and throughput figures are sampled wall-clock and
will vary with machine load.

## 3. Results

- Features: **41**.
- Tests: **36 passed** for the T03 file and **105 passed** for the full
  repository suite.
- Corpus: **1600 clean** episodes and **1600 shifted** episodes, **3200**
  episodes in total, **384000** actions in total, **79023** positives in total.
  Per shift setting: **192000** actions; **40457** positives clean and
  **38566** shifted. Each family contributes **200** episodes and **24000**
  actions per shift setting.
- Latency per action on one CPU core, measured across all **384000** timed
  actions: mean **0.2449 ms**, p50 **0.1965 ms**, p95 **0.5365 ms**, p99
  **0.9118 ms** (bar **5.0 ms**), max **43.2755 ms**. The p99 is the bar;
  single-operation maxima are noisy because of OS scheduling.
- Throughput, now reported in two separately labelled forms:
  end-to-end evaluation (open, parse, featurise and label extraction) is
  **99.635 s**, **32.12** episodes/sec and **3854.1** actions/sec; featurisation
  alone (the summed per-action `featurize` timings, excluding file open and
  JSON parsing) is **94.035 s**, **34.03** episodes/sec and **4083.6**
  actions/sec. These sampled values are exactly those in the capture
  **`captured run 20261119T051628Z`** in `check.log`; a rerun on a loaded
  machine will print different latency and throughput, while the corpus counts
  and AUROCs above are deterministic.

Best single feature per cause group, against the labels of that cause's family
(the brief's sanity check, not the held-out result). Here "Clean" means the
unshifted version of that cause's family, not the all-negative clean family:

| Cause group | Best feature | Clean AUROC | Shifted AUROC |
|---|---|---:|---:|
| drift | `drift_out_of_band_increase` | 1.0000 | 1.0000 |
| unsupported_claim | `claim_support_failure_share` | 1.0000 | 1.0000 |
| misquote | `value_relative_error` | 0.9999 | 0.9999 |
| poisoned_note | `note_external_tool_unsourced_share` | 1.0000 | 1.0000 |
| authority_spoof | `auth_unsigned_and_excess` | 1.0000 | 1.0000 |
| stale_thesis | `stale_invalidated_buy` | 0.8836 | 0.8836 |

Pass-bar check as printed: every shifted AUROC is at or above **0.80**, and p99
is **0.9118 ms** against the **5.0 ms** bar. The run prints `OVERALL: PASS`.

Evidence-quality sanity number (not a cause family, so no bar): the best
evidence-quality feature is `evidence_mean_trust_risk`, AUROC **0.5370** clean
and **0.5341** shifted when clean actions are negatives and every failure action
is a positive. It is weak, as expected; it is a descriptive feature group, not a
cause detector.

Label rates from the captured run (positives / actions, **24000** actions per
cell):

| Family | Clean positives | Clean rate | Shifted positives | Shifted rate |
|---|---:|---:|---:|---:|
| clean | 0 | 0.0000 | 0 | 0.0000 |
| drift | 5518 | 0.2299 | 3627 | 0.1511 |
| unsupported_claim | 6708 | 0.2795 | 6708 | 0.2795 |
| misquote | 6626 | 0.2761 | 6626 | 0.2761 |
| vague_hype | 6581 | 0.2742 | 6581 | 0.2742 |
| poisoned_note | 6250 | 0.2604 | 6250 | 0.2604 |
| authority_spoof | 6238 | 0.2599 | 6238 | 0.2599 |
| stale_thesis | 2536 | 0.1057 | 2536 | 0.1057 |

The brief asks for a sanity check, not confidence intervals, so the table
reports point estimates. The independent T02 worlds, not this reference set, are
the real test of shift robustness.

`vague_hype` has no dedicated structural cause feature. Its definition is
wording-based ("enthusiasm with no concrete figure"), so the cause itself is
deliberately left to the T05 text channel. Round 4 did change one adjacent
behaviour: non-numeric claims now go through the support checks (review fix 1),
so a hype claim with no source or no usable quote is flagged structurally. On
the reference `vague_hype` family the best unsupported_claim feature separates
the actions at AUROC **1.0000** clean and **1.0000** shifted. That is a property
of this generator (its hype claims are sourceless non-numeric claims), not
evidence that the structural layer detects hype in general: a vague but
properly sourced qualitative claim is not flagged, and the run prints that
distinction.

## 4. What did not work

- **Whole-book band excess was the wrong authority test.** The first authority
  feature measured the worst sector excess anywhere in the book after the
  action. After a spoof buy had already pushed a sector out of band, ordinary
  clean sells in other sectors inherited a positive excess, and the authority
  AUROC fell below the bar in a development sample. Fixed by making the
  permission test action-specific: the traded sector on the side that can
  breach, the traded instrument's position cap, and the allowed-instrument list,
  then ANDing it with an unsigned cited note. The captured run reports the
  conjunction at 1.0000 shifted.
- **Passing an already-stripped dict into `model_view_at` was much slower.**
  `model_view` uses `Episode.to_dict()` when given an `Episode`, but falls back
  to `copy.deepcopy` when given a dict. Passing the stripped dict therefore made
  every per-action view copy the whole episode with `deepcopy`, and development
  mean latency rose sharply. I reverted to passing the original `Episode`. The
  step count now comes from `len(episode.steps)` (or `len(episode["steps"])` for
  a dict) instead of materialising `model_view`; round 2 removed the last
  whole-episode call. I also disabled Python's cyclic GC during the per-action
  loop and restored it afterwards; that removed the millisecond-scale GC pauses
  and produced the captured p99.
- **Age-only staleness is weak.** `stale_days_since_opened` and
  `stale_days_since_newest_evidence` alone are much weaker than the invalidation
  conjunction. The deeper problem is label noise in the reference world: random
  later documents can report negative guidance and meet a thesis's
  `invalidation_trigger`, while the generator only labels the specifically
  chosen thesis. A structurally correct trigger check therefore flags some clean
  actions too. The best stale feature is `stale_invalidated_buy` at **0.8836**,
  which clears the **0.80** bar but is the weakest of the cause groups.
- **An unsourced claim with a real document but no span escaped the unit test.**
  The cited document may happen to carry a fact with the same unit, so the
  brief's unit test alone does not fire. I added `claim_value_absent_share` as a
  diagnostic: a no-span numeric claim whose value does not match any same-unit
  fact in the source at a tight exact tolerance. Round 4 then made the absent
  span itself missing support, so the support feature fires regardless of the
  value match; the unsupported aggregate is 1.0000 shifted.
- **Evidence quality is not a cause detector here.** The pooled AUROC is
  **0.5370** clean and **0.5341** shifted. It should not be used as a standalone
  risk score; it is context for the scorer.
- **Vague hype as a cause is not caught structurally.** A "claim has no number"
  rule would be a wording proxy and would also flag legitimate qualitative
  claims, so the cause stays in T05. The reference generator's hype actions do
  happen to carry sourceless non-numeric claims, which the round-4 support
  checks flag; that is a property of this generator, not a general hype
  detector.
- **The final thesis status is deliberately unused.** `model_view_at` strips
  `status` because it is end-of-episode state; using it would leak the future.
  The causal invalidation trigger is the substitute. If an author invalidates a
  thesis by status alone, with no numeric trigger, this layer cannot see it.

## 5. Judgement calls

### 5.1 Structural/provenance code versus a learned or text-based detector

- **Choice:** deterministic structural and provenance checks over the recorded
  fields (bands, positions, facts, units, note writers, signatures, trust tiers,
  document times, thesis triggers).
- **Alternatives:** (a) a learned tabular classifier over the same fields
  (learning paradigm); (b) an LLM adjudicator reading the documents, notes and
  claims (LLM paradigm); (c) keyword/regex rules over prose (rule paradigm);
  (d) an NLI/text-channel answer folded in here.
- **Why it wins on this project's criteria:** structure is invariant to wording,
  so it should survive independent authors' paraphrase and the shifted
  reference set; it cannot be talked around by adversarial prose because it
  never reads prose; latency is **0.2449 ms** mean and **0.9118 ms** p99, far
  below the **5.0 ms** bar; cost is zero (no weights, no calls); it needs no
  training data; it is debuggable because each feature maps to one cause; and
  the arithmetic and substring checks have exact, provable semantics.
- **What evidence would flip it:** if held-out authors use structures these
  checks do not cover (non-numeric claims, status-only invalidation, permission
  changes that stay inside the current mandate) and T05 cannot recover them, add
  a learned or text layer; do not replace the structural layer, which is the
  only part with exact semantics.

### 5.2 Per-action causal view

- **Choice:** call `model_view_at(episode, i)` for every action and update the
  book/CUSUM state only from earlier actions.
- **Alternatives:** (a) the whole-episode `model_view` (cheaper but leaks later
  documents and final thesis status); (b) a hand-rolled incremental view built
  from one `model_view` (faster but not the schema-provided causal view and
  harder to audit); (c) masking a full view after the fact.
- **Why it wins:** it is the lead's causal-input rule; it is testable by
  mutating future entities; it is the least likely to leak; and the measured
  latency leaves ample headroom for the extra copies.
- **What evidence would flip it:** if latency or memory became the bottleneck,
  build a cached causal view and prove it byte-equivalent to `model_view_at` by
  tests; a hand-rolled view without that proof would not be acceptable.

### 5.3 Value fidelity from structured facts

- **Choice:** verify the quoted span is a non-empty exact substring, then compare
  the claim's value to the nearest same-unit (or same-dimension) number in the
  source's `facts`, using a symmetric relative error.
- **Alternatives:** (a) parse numbers and units out of the span/prose;
  (b) exact string equality with the quoted figure; (c) an NLI cross-encoder or
  LLM judge in T05.
- **Why it wins:** it uses the schema's machine-readable facts, so it never
  parses prose and never depends on wording; exact string equality is too strict
  for formatting differences; it is cheap, deterministic and testable.
- **What evidence would flip it:** if independent authors omit facts or publish
  facts inconsistent with their text, add a span tokenizer or move the check to
  T05. A numeric tokenizer over the span would be the first fallback because it
  is still deterministic.

### 5.4 Unit canonicalisation

- **Choice:** a small closed table that maps the structured `unit` field to a
  dimension and a scale, plus exact-unit support and cross-unit scale checks.
- **Alternatives:** (a) exact string match only; (b) parse unit words from prose;
  (c) let an LLM normalise units.
- **Why it wins:** it catches `%` versus `bp` and `$M` versus `$B` structurally,
  including the case where the agent copies the raw number but changes the unit;
  it also accepts a correctly rescaled basis-point conversion. It is deterministic
  and cheap.
- **What evidence would flip it:** if held-out authors use units outside the
  table, extend the table (a data change) or send unknown units to T05. The
  table is a vocabulary for a structured field, not a keyword list over prose.

### 5.5 Drift CUSUM

- **Choice:** a Bernoulli CUSUM with `x_t = 1` for an out-of-band buy and a
  reference value of `0.5`.
- **Alternatives:** (a) an EWMA of the excess weight; (b) a simple running count
  of out-of-band buys; (c) Page's CUSUM on continuous weight excess; (d) no
  CUSUM, only the instantaneous out-of-band increase.
- **Why it wins:** it is standard, parameter-light and detects sustained
  out-of-band buying even when a single action's weight change is small; `x_t` is
  purely structural; it adds no data or tuning burden.
- **What evidence would flip it:** if a held-out slower drift is missed, tune
  the reference value or switch to a Page CUSUM on weight excess. The
  instantaneous `drift_out_of_band_increase` remains the primary drift signal;
  the CUSUM is a complement.

### 5.6 Thesis staleness

- **Choice:** evaluate the thesis's numeric `invalidation_trigger` against facts
  in documents published strictly after `opened_t`, and combine it with a
  buy-that-adds-exposure indicator, days since the newest evidence, and the age
  of the firing document.
- **Alternatives:** (a) use the final `thesis.status` (leaks the future);
  (b) an age threshold only; (c) an NLI judgment of the invalidation sentence;
  (d) a learned staleness model.
- **Why it wins:** it is causal, structural, uses no prose, and matches the
  schema's trigger field. The final status is end-of-episode state and would
  leak; the age-only features are weak and do not know whether the thesis is
  still alive.
- **What evidence would flip it:** if held-out authors invalidate theses with
  status or with non-numeric text, add a T05 reader. The structural layer cannot
  see a status-only invalidation causally.

### 5.7 Authority spoof

- **Choice:** AND an unsigned cited note with an action-specific permission
  excess (traded sector on the side that can breach, traded instrument cap,
  instrument not in `allowed_instruments`).
- **Alternatives:** (a) the whole-book band excess; (b) note provenance alone;
  (c) a text detector for claimed authority; (d) a learned classifier.
- **Why it wins:** it implements the brief's structural definition ("does the
  action need a permission the signed mandate does not grant?"). The whole-book
  version false-positived on clean actions after a spoof; note provenance alone
  confuses poisoned notes with spoofs; the conjunction is cheap and debuggable.
- **What evidence would flip it:** if a spoof asserts a permission change but
  stays inside the current mandate, this layer cannot see it; T05 must detect
  the claimed change. If held-out authors forge signatures rather than omit
  them, add a signature/key check.

### 5.8 Evidence quality

- **Choice:** inverse mean trust, social share, tool-output share and low-trust
  share of the cited documents.
- **Alternatives:** (a) a publisher allowlist; (b) source count only; (c) a
  learned source-reliability model; (d) omit the group.
- **Why it wins:** it is structural, uses no publisher keywords, is cheap, and
  gives the scorer context without pretending to be a cause detector.
- **What evidence would flip it:** if T04 shows source reliability is
  predictive, replace it with a calibrated reliability term. The pooled AUROC
  here is only **0.5370** clean and **0.5341** shifted, so it is not carrying a
  cause on its own.

### 5.9 AUROC implementation

- **Choice:** a tie-averaged rank implementation in `checks.auroc`, with a
  hand-computed test and a tie test.
- **Alternatives:** `sklearn.metrics.roc_auc_score`; a Mann-Whitney U call; a
  bootstrap confidence interval.
- **Why it wins:** no extra dependency, deterministic, auditable, and the tie
  behaviour is explicit. The hand-computed test pins the arithmetic.
- **What evidence would flip it:** if confidence intervals are required for a
  later task, add a bootstrap or use sklearn; this task asks for a sanity check,
  not CIs.

### 5.10 Vague hype

- **Choice:** no dedicated structural feature; defer the cause to T05. The
  general claim-support checks still apply to non-numeric claims, so a hype
  claim with no source or no usable quote is flagged, but hype with a proper
  source is not.
- **Alternatives:** (a) a "no numeric claim" heuristic; (b) a sentiment/hype
  lexicon; (c) an LLM judge.
- **Why it wins:** the failure is about wording, and a no-number rule would flag
  legitimate qualitative claims. The task table intentionally omits it, and the
  brief says wording belongs to the text channel.
- **What evidence would flip it:** if T05 cannot separate hype from factual
  qualitative reasoning, revisit a bounded structural proxy, but only with
  evidence that it does not punish legitimate claims.

### 5.11 Libraries and test framework

- **Choice:** `numpy` for the feature matrix and timing percentiles, and `pytest`
  for the tests. Both are already used by the repository.
- **Alternatives:** pure Python lists plus `statistics`; a `pandas` DataFrame
  for the matrix; `unittest` or a bespoke runner for the tests.
- **Why it wins:** `numpy` is already a dependency of the reference world, gives
  a compact `[n_actions, n_features]` array, and makes the rank AUROC and
  percentiles cheap. `pytest` is already the repository's framework, so the T03
  tests sit beside the existing suite and run with the same command. Neither
  choice adds an install or a new execution path.
- **What evidence would flip it:** if the scorer (T04/T07) standardises on a
  pandas or tensor input, convert at the boundary and keep `featurize`'s array
  contract; if the lab standardises on another test runner, port the tests
  without changing the checks.

### 5.12 Empty and whitespace quoted spans

- **Choice:** a `quoted_span` of `None`, `""` or whitespace-only is not a valid
  span. An empty or whitespace span increments `claim_span_not_in_source_share`,
  which feeds `claim_support_failure_share`, so it cannot be silently accepted
  by Python's `"" in text` behaviour even when the claimed value happens to
  match a source fact.
- **Alternatives:** (a) treat only `None` as missing and accept `""` as a valid
  substring (the previous behaviour, which the reviewer found unsound);
  (b) treat an empty span as missing and run only the value-match fallback,
  which leaves a claim with a matching fact unflagged; (c) ignore blank spans
  entirely.
- **Why it wins:** the schema calls `quoted_span` the exact substring a claim
  relies on; an empty string carries no evidence. Counting it as an invalid span
  is structural, needs no prose parsing, and makes the support feature fire. The
  new regression test pins both `""` and whitespace-only spans.
- **What evidence would flip it:** if a legitimate world generator emits an
  empty span to mean "no quote intended" rather than null, normalise that
  generator's output to null before featurising; do not restore `"" in text` as
  evidence.

### 5.13 Mixed-trust citations in the poisoned-note check

- **Choice:** an external or tool note is unsourced when it cites no document
  **or any** document at trust tier 0. A note citing both a tier-0 document and
  a higher-tier document is flagged.
- **Alternatives:** (a) require **all** cited documents to be tier 0 (the
  previous behaviour); (b) report mixed citations only through the generic
  `note_low_trust_citation_share`, which drops the external/tool writer
  condition; (c) split into separate any-tier-0 and all-tier-0 features.
- **Why it wins:** the brief says "cites documents of trust tier 0", and the
  mixed case does cite such a document. A tier-0 citation is the structural
  defect; adding a high-tier citation should not launder it. This also removes
  the gap the reviewer identified, where the external/tool condition disappeared
  for mixed citations. `ESCALATION.md` records the any-versus-all ambiguity; if
  the reviewer or lead rules for "all", this is a one-line change and the
  separate low-trust share remains available.
- **What evidence would flip it:** a ruling from the escalation reviewer or lead
  that "cites documents of trust tier 0" means every cited document, or held-out
  evidence that mixed citations are common and legitimate for external/tool
  notes. The mixed-citation regression test would then be reversed.

## 6. Loopholes I checked

- **Future documents and notes:** mutating every document after the action time
  (text, facts, trust tier, kind) and every future note (writer, signature,
  citations, text), and appending new future documents/notes, leaves the rows
  up to the cut unchanged. Tested.
- **Document boundary:** a document at the action's `t` is visible; one at
  `t + 1` is not, and a claim sourcing the latter gets
  the source-unavailable feature. Tested.
- **Intra-step note order:** a same-step `pre_note` is visible to the action; a
  same-step `new_note` is not, and citing it produces
  the missing-note feature. Tested.
- **Final thesis status:** setting every thesis's final `status` to
  `invalidated` changes no row. Tested.
- **Labels and `meta`:** replacing every label and all `meta` changes no row,
  and featurising the dict from `schema.model_view(episode)` equals featurising
  the full episode. That is an input-equivalence test in the test harness; the
  feature module never calls `model_view` (round 2 guard test).
- **Prohibited whole-episode view:** `og_s1.checks` no longer imports or calls
  `model_view`; a test asserts the module has no such global and its source has
  no `model_view(` call after removing `model_view_at(`.
- **No wording logic:** there is no `re` import and no keyword list over prose.
  The only prose access is `quoted_span in document.text`, which the schema
  requires. Everything else is structured: facts, units, kinds, writers,
  signatures, trust tiers, times, bands and positions.
- **Unit swaps:** `%` versus `bp`, `$M` versus `$B`, and a correctly rescaled
  basis-point conversion are all tested; the swap features fire only on the
  erroneous copies.
- **Absent and empty quotes:** a `None` span, `""` and a whitespace-only
  `quoted_span` are all tested and increment the span-failure and support-failure
  features, even when the claimed value matches a source fact. The `None` test
  is the reviewer's exact case: numeric claim, available source, matching fact,
  no quote.
- **Non-numeric claims:** an unsourced non-numeric claim and a non-numeric claim
  whose source document is not yet available are tested and flagged; a
  non-numeric claim with a valid quote is tested and is *not* flagged. The
  fidelity comparisons remain numeric-only.
- **Mixed-trust citations:** an external/tool note citing both a tier-0 and a
  tier-3 document is tested and flagged by the external/tool unsourced feature.
- **Clean actions:** the clean-reference test asserts no drift, claim, value,
  note-provenance or authority signal; it passes.
- **Reference-family separability:** a test simulates reference episodes,
  collects features and labels, and requires the best feature in each cause
  group to clear a threshold; it passes.
- **AUROC arithmetic:** the rank implementation is pinned by a hand-computed
  example and a tie example.
- **Latency:** a test asserts the per-action p99 is below the **5 ms** bar
  and a mean bound; the captured run reports **0.9118 ms** p99.
- **Throughput label:** the evaluator used to print a single
  `total_featurise_wall_s` that actually included file open and JSON parsing.
  It now prints `total_eval_wall_s` (load + parse + featurise, plus the label
  loop) and `total_featurise_wall_s` (the summed per-action `featurize`
  timings), each with its own episodes/sec and actions/sec. The two are no
  longer conflated.
- **No test-set peeking:** `evaluate.py` reads labels only after `featurize` has
  consumed the causal view. `featurize` itself calls only `model_view_at`.
- **Isolation:** only `data/ref/` and the repository code were read; no
  `work/T02*`, `work/T06` or `data/heldout*` access.
- **No git, no secrets, no absolute home paths:** none were used or written; the
  captured `check.log` contains no absolute home path.
- **Disk:** the task folder contains only `REPORT.md`, `run.sh`,
  `evaluate.py` and `check.log`; no data and nothing near the 5 MB limit.
- **Reproducibility:** `run.sh` appends a timestamp-labelled capture block to
  `check.log`, so a reviewer rerun cannot destroy the capture the report cites.

## 7. Open risks

- **Reference-only development.** The checks were designed against the reference
  world. The independent T02 worlds may use unit spellings outside the table,
  different note-provenance patterns, or invalidations without a numeric
  trigger. Those are the most likely failure points.
- **Non-numeric claims are only partly covered.** Round 4 made the support and
  provenance checks apply to every claim, so an unsourced non-numeric claim, an
  unavailable source, an absent/blank quote and a broken quote are all visible.
  What remains outside this layer is value fidelity for non-numeric claims
  (there is no number to compare) and a vague but properly sourced qualitative
  claim. Those go to T05.
- **Status-only or same-time invalidation.** If an author invalidates a thesis
  through `status` alone, or through a document at exactly `opened_t`, the
  causal trigger check misses it. Using the final status would leak the future,
  so the structural layer cannot close this gap without a schema change.
- **Authority changes that stay inside the mandate.** A note that asserts a
  permission change but acts within the signed bands and caps is not a
  structural authority failure. T05 must judge the claimed authority.
- **Poisoned notes from the agent.** The structural rule covers external/tool
  notes with no documents or any tier-0 document, and unsigned non-agent notes.
  A poisoned note written by the agent and backed by a high-trust document is
  left to T05.
- **Daily turnover aggregation.** Turnover is summed by the integer `t` field.
  If a held-out world puts several actions at the same `t` with different
  intraday times, the daily figure is approximate. The schema does not carry a
  finer clock.
- **CUSUM reference value.** The `0.5` reference value is a design choice. A
  slower held-out drift with many in-band actions can reset the statistic; the
  instantaneous out-of-band increase remains the primary drift signal.
- **No price moves.** The book is valued at constant prices, as the schema
  specifies. Realised P&L and price drift are out of scope.
- **Latency is sampled.** The p99 is **0.9118 ms** in the captured run, but the
  maximum is an OS scheduling outlier and a heavily loaded machine will move
  the tail. The headroom to the **5.0 ms** bar is large but not a hard real-time
  guarantee.
- **Evidence quality is weak.** Its pooled AUROC is **0.5370** clean and
  **0.5341** shifted. It should not be interpreted as a cause signal.

## Round 2 changes

Review verdict: **REVISE**. Both required fixes are addressed.

1. **Removed the whole-episode `model_view(episode)` call.** `og_s1/checks.py` no
   longer imports `model_view`; it obtains the action count from
   `len(episode.steps)` for an `Episode` and `len(episode["steps"])` for a dict,
   then reads each row only through `model_view_at(episode, i)`. A new test,
   `test_featurize_does_not_materialize_the_whole_episode_view`, asserts the
   module has no `model_view` global and that the module source contains no
   `model_view(` call once `model_view_at(` is removed, so the call cannot be
   reintroduced silently. The T03 suite grew to **30 tests** in that round.
2. **Reconciled the then-current captured numbers with `check.log`.** I re-ran
   `bash work/T03/run.sh` after the code change and replaced the report's test
   counts, latency and throughput with the values printed in that capture. The
   repository count rose because other tasks' tests were in the same
   `og_s1/tests` tree. Those figures are superseded by the Section 3 capture
   below; the historical values are not repeated here.

I did not change the feature set, the cause groups, the AUROC analysis, the
isolation boundary, or the pass-bar logic: the review confirmed those items
met the bar, and the AUROCs and corpus counts are deterministic and unchanged
(drift 1.0000, unsupported_claim 1.0000, misquote 0.9999, poisoned_note 1.0000,
authority_spoof 1.0000, stale_thesis 0.8836 shifted; 41 features; 3200
episodes, 384000 actions, 79023 positives). I also did not request an
escalation: both findings had direct fixes, as `ESCALATION.md` records.

The report's latency figures are a single sample from a shared machine and will
move run to run; they match the `check.log` captured for this round, which is
the reproducibility claim the report makes. The p99 remains far below the
**5.0 ms** bar and the pass bar is unchanged.

## Round 3 changes

Review verdict: **REVISE**. All three required fixes are addressed, in the
reviewer's order of importance.

1. **Sampled latency/throughput figures now reconcile with one identified
   capture.** The mismatch happened because `run.sh` overwrote `check.log` on
   every invocation while the report quoted an earlier capture. `run.sh` now
   appends a block headed `captured run <UTC timestamp>` and ends it with
   `end captured run <id>`, so a reviewer rerun cannot destroy the cited run.
   This round's text incorrectly said the supplied `check.log` held exactly one
   block. It already held the duplicated `20261119T032852Z` capture, as the
   Round 4 reviewer found; the log now holds six capture ids (see Section 2).
   The Round 3 latency figures were mean **0.2004 ms**, p50 **0.1921 ms**, p95
   **0.2397 ms**, p99 **0.3678 ms**, **39.31** episodes/sec and **4716.9**
   actions/sec over **384000** timed actions, and are superseded by Section 3.
   These remain sampled wall-clock numbers; a rerun appends a different capture,
   which is why the report names the capture it cites instead of claiming that
   every future run will print the same values.
2. **Empty and whitespace quoted spans are now invalid.** `""` previously
   passed `"" in source_text`, so a numeric claim with an empty quote and a
   matching source fact could leave the support features at zero. Empty,
   whitespace-only and non-string spans now increment
   `claim_span_not_in_source_share`, which feeds
   `claim_support_failure_share`; only a genuine `None` span took the
   value-match fallback at that point. (Round 4 later made an absent `None`
   span missing support as well; see the Round 4 section.) A regression test,
   `test_empty_quoted_span_is_treated_as_missing_and_flagged`, pins both `""`
   and `"   "`.
3. **Mixed-trust note citations now resolve to "any tier-0".** The
   external/tool condition changed from `all(t == 0 for t in tiers)` to
   `any(t == 0 for t in tiers)`, so an external/tool note citing a tier-0 and a
   higher-tier document is flagged by
   `note_external_tool_unsourced_share`. This follows the brief's wording and
   the reviewer's reading; the any-versus-all question remains recorded in
   `ESCALATION.md` with no ruling yet, and Section 5.13 documents the call and
   what would reverse it. The existing high-tier-only case still does not fire.
   A mixed-citation assertion was added to the tier-zero note test.

At the end of Round 3 the T03 suite was **31 tests** (up from 30) and the full
repository suite was **99 passed**; Round 4 below supersedes both counts. The
feature count remains **41**, the corpus remains **3200** episodes / **384000** actions / **79023** positives, and all
reference AUROCs are unchanged: drift **1.0000**, unsupported_claim **1.0000**,
misquote **0.9999**, poisoned_note **1.0000**, authority_spoof **1.0000**,
stale_thesis **0.8836** shifted. `OVERALL: PASS`.

I did not change the cause groups, the feature set, the AUROC analysis, the
isolation boundary, the wording-free rule, or the pass bar. The stale-thesis
weakness, the structural deferral of `vague_hype`, and the open risks remain as
reported; none of the three review items required touching them.

## Round 4 changes

Review verdict: **REVISE**. All four required fixes are addressed, in the
reviewer's order of importance, and every number was re-generated by
`bash run.sh` in capture **`20261119T051628Z`**.

1. **Support checks now run over all claims, not only numeric ones.**
   `_claim_features` in `og_s1/checks.py` no longer filters to
   `value is not None`. Every claim gets the source-presence, document-
   availability and quoted-span checks; every claim that carries a unit (and
   every numeric claim) gets the unit-presence check; and the share
   denominators are the total number of claims. Value fidelity remains
   numeric-only: a non-numeric claim has no number to compare, so it cannot
   produce a relative error, scale error or unit swap. I added four regression
   tests: `test_nonnumeric_unsourced_claim_is_flagged`,
   `test_nonnumeric_claim_from_an_unavailable_document_is_flagged`,
   `test_nonnumeric_claim_with_an_absent_unit_is_flagged`, and
   `test_nonnumeric_claim_with_a_valid_quote_is_supported` (the last prevents
   the new coverage from turning a correctly sourced qualitative claim into a
   false positive).
2. **An absent quoted span is now missing support.** A `None` span increments
   `claim_span_not_in_source_share` and therefore
   `claim_support_failure_share`, instead of silently taking the value-match
   fallback. `claim_value_absent_share` is still computed for numeric no-span
   claims as a diagnostic, and still enters the support maximum, but the absent
   span is already a failure so support cannot stay at zero. The exact reviewer
   case — numeric claim, available source, matching fact, `quoted_span=None` —
   is pinned by
   `test_absent_quoted_span_is_missing_support_even_when_value_matches_fact`.
   I did not add a separate feature for absent spans: it would raise the feature
   count for no cause-group benefit, and folding it into the existing span
   feature keeps the semantics that an absent quote is not evidence.
3. **The capture claim in the report is corrected.** The Round 3 statement
   that `check.log` held exactly one block was false; it already contained the
   duplicated `20261119T032852Z` capture. Section 2 now names every capture id
   in the current log and says the log is append-only, and Section 3 cites the
   round-4 capture `20261119T051628Z`. The Round 3 paragraph itself now records
   the error and points to Section 2 instead of repeating it.
4. **The aggregate throughput label no longer conflates file I/O with
   featurisation.** `work/T03/evaluate.py` now prints two labelled lines:
   `total_eval_wall_s` with `eval_episodes_per_s` / `eval_actions_per_s` for
   open + parse + featurise + label extraction, and `total_featurise_wall_s`
   with `featurise_episodes_per_s` / `featurise_actions_per_s` computed from
   the summed per-action timings inside `featurize` only. Section 3 reports
   both pairs.

Results after the changes, from capture `20261119T051628Z`: **36** T03 tests
passed, **105** repository tests passed, **41** features, **3200** episodes,
**384000** actions, **79023** positives. Shifted AUROCs are unchanged: drift
**1.0000**, unsupported_claim **1.0000**, misquote **0.9999**, poisoned_note
**1.0000**, authority_spoof **1.0000**, stale_thesis **0.8836**;
`OVERALL: PASS`. Latency is mean **0.2449 ms**, p50 **0.1965 ms**, p95
**0.5365 ms**, p99 **0.9118 ms** against the **5.0 ms** bar; the sampled tail
moved because the run shared the machine with other work. End-to-end evaluation
throughput is **32.12** episodes/sec / **3854.1** actions/sec; featurisation-only
throughput is **34.03** episodes/sec / **4083.6** actions/sec. As a side effect
of fix 1, the reference `vague_hype` family's sourceless non-numeric claims are
now flagged by claim support (AUROC **1.0000** clean and shifted, printed in
the descriptive section); the cause itself is still deferred to T05 because a
vague but properly sourced claim has no structural defect.

What I did **not** change and why:

- **The feature set and cause groups** are unchanged at 41 features and seven
  groups; the four fixes did not require new causes, and the six required
  cause-group AUROCs already cleared the shifted 0.80 bar.
- **The any-versus-all tier-0 citation rule** is unchanged. `ESCALATION.md`
  records the interpretation question and no ruling has arrived; changing it
  again without a ruling would just reverse a documented call.
- **The stale-thesis weakness** remains. It is a known structural limit
  (status-only and non-numeric invalidation) cleared by the shifted AUROC, not
  a review item this round.
- **The pass bar, isolation boundary, wording-free rule and causal input**
  (`model_view_at` per action) are unchanged.
- **No test-set peeking, no git, no secrets, no writes outside this task
  folder and `og_s1/`.** The new tests use only the synthetic test builders and
  `og_s1.world.simulate`; the evaluator still reads labels only after
  featurisation and never reads `meta`.
