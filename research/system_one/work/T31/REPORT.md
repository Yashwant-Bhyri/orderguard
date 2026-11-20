# T31 — Binding coherence in the reference world

## 1. What I built

- **`og_s1/coherence.py`.** A code check `coherence(action, case) -> list[dict]`.
  `case_for_step(episode, i)` builds a causal case from documents with
  `t <= action.t` and theses opened by then; it never reads labels or `meta`.
  The surface form is inferred from the first decisive ticker or company-name
  mention in the documents, so the shift flag itself is not taken from
  `meta` either. The check uses the reference world's own entity map (tickers
  unshifted, company names shifted) and its shifted fact phrases, not ticker
  substring matching over shifted text. It returns findings for:
  - `rationale_direction`: buying words on a sell, or selling words on a buy;
  - `rationale_foreign_instrument`: the rationale names a different
    instrument without an explicit comparison in the same sentence;
  - `claim_not_about_trade`: no claim is about the traded instrument, the
    action thesis's evidence, or the traded sector;
  - `claim_foreign_instrument`: a claim names a peer without an explicit
    same-sentence comparison to the traded name;
  - `claim_source_entity_mismatch`: the claim's subject is not the subject of
    its source document (right value, wrong entity);
  - `claim_stale_period`: the claim uses an older figure while a strictly
    later document reports the same fact for the same instrument (right value,
    wrong period).

  The last three are extensions required so the `binding_error` family's
  entity and period plants are actually detectable; the brief's three named
  checks alone cannot see a wrong-entity or wrong-period binding.

- **Reference world v2.1 in `og_s1/world.py`.** `simulate(..., coherent=True)`
  is a new option, default off. With it on:
  - rationale templates are side-aware (`BUY_RATIONALE` / `SELL_RATIONALE`);
  - claims and rationales use the newest document about the traded
    instrument; if the episode has none, a filing about that instrument is
    added at the action's time (legal because documents with `t` not later
    than the action are citable), and a sector-level template that names only
    the traded name and its sector is used;
  - every non-binding family action is coherent (including positives of
    `drift`, `unsupported_claim`, `misquote`, `vague_hype`, `poisoned_note`,
    `authority_spoof`, `stale_thesis`);
  - a new `binding_error` family plants four subtypes: sibling value asserted
    about the traded name, old figure presented against a newer one, rationale
    direction opposite the side, and a sibling claim presented as the traded
    name;
  - `binding_error` also emits hard negatives: clean actions whose rationale
    and claim explicitly compare the traded name to a peer with "versus".

- **`og_s1/generate.py --coherent`** generates the nine-family v2.1 corpus with
  the same families, sizes, seeds and shifted splits as v2. `FAMILIES` remains
  the eight v2 families, so every existing caller is unchanged.

- **Schema and validator.** `SCHEMA.md` documents `binding_error` and the
  explicit relative-value hard negative. `og_s1/validate.py` now requires a
  non-empty `cause_refs` on every `binding_error` label (the existing
  resolution and availability checks still apply to the referenced document).

- **`og_s1/tests/test_coherence.py`.** Ten tests: v2 byte-for-byte samples,
  v2.1 clean zero findings, v2.1 non-binding positives coherent, every
  binding positive detected with a finding that points at its `cause_refs`,
  hard negatives zero findings, the lead's episode 57/80 example, label
  blindness, explicit comparisons, direction detection, and stable finding
  names.

- **Measurement and re-scoring.** `work/T31/rescore_t03.py` re-runs T03's
  features and AUROC with incoherent negatives removed; `work/T31/
  rescore_t05.py` re-scores T05's registered readers with T05's own sampler
  and scorers and T05's decision cache; `work/T31/verify_v2.py`,
  `analyze_v21.py` and `run.sh` complete the entry point.

Isolation: I did not open `work/T02*`, `work/T06`, `work/T16` or
`data/heldout*`, ran no git command, and did not edit T03 or T05 files (their
modules are imported read-only). I read `work/T03/LEAD_NOTE.md`, T03's report
and T05's report, schema and pre-registration.

## 2. How to re-run (one command)

```
bash research/system_one/work/T31/run.sh
```

From this task folder, `bash run.sh` is equivalent. The command takes several
minutes on this Mac, refuses to run concurrently, and writes one capture to
`work/T31/check.log` through a temporary file that is moved into place only
after the whole run succeeds. It verifies v2 byte for byte, regenerates
`data/ref_v21/` (size printed by the capture; inside the git-ignored data
directory), validates it, prints every rate and re-score, runs
`python3 -m pytest og_s1/tests -q`, and then checks that each section heading
appears exactly once in the capture. The T05 re-score uses T05's existing
on-disk decision cache; every key was present, so it makes no network call.
`work/T31/t05_scores.npz` caches the local reader scores; delete it (and its
`.json` sidecar) to force a full model re-score. All numbers below come from
that capture; wall-clock timings printed by the generator are the only values
that vary between runs and are not treated as results.

## 3. Results

### 3.1 v2 still reproduces exactly

All **3,200 / 3,200** v2 episodes (eight families, both splits) are identical
to `data/ref/`. `V2 REPRODUCTION: PASS`. The captured full test suite is
**140 passed** in 28.14 s. (The suite count includes tests from other tasks in
the shared package and can move when those tasks change; the pass condition is
that every test passes.)

### 3.2 v2 incoherence rates

Rates are per y=0 action in each family and split. "any" is at least one
finding; "brief3" is at least one of the brief's three checks (direction,
rationale-foreign, no-claim-about-trade). `claim_source_entity_mismatch` is 0
on every v2 negative because v2's clean claims always name the company whose
document they cite.

| family | split | negatives | any | brief3 | direction | rationale-foreign | no claim | claim-foreign | source mismatch | stale |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| clean | unshifted | 24000 | 42.8% | 34.1% | 23.8% | 14.6% | 11.6% | 16.1% | 0.0% | 13.0% |
| drift | unshifted | 18482 | 48.4% | 41.9% | 25.8% | 22.8% | 18.2% | 25.1% | 0.0% | 11.2% |
| unsupported_claim | unshifted | 17292 | 41.2% | 34.1% | 23.9% | 14.3% | 11.2% | 15.6% | 0.0% | 10.8% |
| misquote | unshifted | 17374 | 41.0% | 33.5% | 23.2% | 14.5% | 11.4% | 15.8% | 0.0% | 10.5% |
| vague_hype | unshifted | 17419 | 40.6% | 34.0% | 23.7% | 14.4% | 11.3% | 15.4% | 0.0% | 9.9% |
| poisoned_note | unshifted | 17750 | 52.8% | 46.8% | 26.4% | 28.2% | 23.2% | 31.0% | 0.0% | 11.6% |
| authority_spoof | unshifted | 17762 | 52.7% | 47.0% | 26.8% | 28.9% | 23.0% | 31.7% | 0.0% | 11.0% |
| stale_thesis | unshifted | 21464 | 44.2% | 36.4% | 24.5% | 16.5% | 12.9% | 18.2% | 0.0% | 12.8% |
| clean | shifted | 24000 | 42.8% | 34.1% | 23.8% | 14.6% | 11.6% | 16.1% | 0.0% | 13.0% |
| drift | shifted | 20373 | 47.0% | 39.4% | 24.9% | 20.5% | 16.2% | 22.6% | 0.0% | 12.3% |
| unsupported_claim | shifted | 17292 | 41.2% | 34.1% | 23.9% | 14.3% | 11.2% | 15.6% | 0.0% | 10.8% |
| misquote | shifted | 17374 | 41.0% | 33.5% | 23.2% | 14.5% | 11.4% | 15.8% | 0.0% | 10.5% |
| vague_hype | shifted | 17419 | 40.6% | 34.0% | 23.7% | 14.4% | 11.3% | 15.4% | 0.0% | 9.9% |
| poisoned_note | shifted | 17750 | 52.8% | 46.8% | 26.4% | 28.2% | 23.2% | 31.0% | 0.0% | 11.6% |
| authority_spoof | shifted | 17762 | 52.7% | 47.0% | 26.8% | 28.9% | 23.0% | 31.7% | 0.0% | 11.0% |
| stale_thesis | shifted | 21464 | 44.2% | 36.4% | 24.5% | 16.5% | 12.9% | 18.2% | 0.0% | 12.8% |

Pooled over all families: **45.4%** of unshifted negatives and **45.2%** of
shifted negatives have at least one finding; the brief-three union is
**38.3%** and **38.0%**. On the clean family the rates are **42.8% any /
34.1% brief3**, with direction 23.8%, rationale-foreign 14.6%, no claim about
the traded name 11.6%, claim-foreign 16.1%, and stale-period 13.0%. The
brief's qualitative finding is reproduced: peer-named rationales,
buying-language sells and claims that do not concern the traded name are all
common among v2 negatives. The direction rate is higher than the lead's rough
one-template estimate because the check catches both v2 buy templates ("We
add" and "Rebalancing into"), not only "We add". The lead's example
`data/ref/clean.jsonl` episode 57 step 80 (sell PEP, claims about CL and COST,
"We add COST...") has direction, rationale-foreign, claim-foreign and
no-claim findings.

The `check.log` all-action finding table now labels every count `*_all`
because it counts y=1 actions as well as y=0 actions. In that table
`claim_source_entity_mismatch_all = 3,174` on `unsupported_claim` is exactly
the 3,174 y=1 positives whose planted unsupported claim cites a sibling's
filing; the same run's positive-only table shows that count, and its
negative-only table shows 0 for every family and split. It is not a
clean-action false positive.

### 3.2b Why shifted and unshifted rates match

The check is written against the world's entity map, not against tickers in
the shifted text. `_shift_text` and `_company_str` change only surface strings
(company names, fact phrases, publisher names), while `coherence` maps both
forms back to the same instrument id. The capture proves this structurally:
for seven of the eight v2 families the shifted and unshifted action
structures and finding sequences are identical item for item. `drift` is the
exception, and it is a generator difference, not a check difference:
`_World._drift_prob` in `og_s1/world.py` deliberately uses a shorter, higher
schedule when unshifted (span 30, cap 0.85) than when shifted (span 60, cap
0.6). That changes which post-onset buys become drift positives, which is why
`drift` has 5,518 unshifted and 3,627 shifted positives and different removal
counts. No other family has a `self.shifted` branch in its action logic.

### 3.3 T03 re-score with incoherent negatives removed

Shifted numbers. The unshifted AUROC deltas are identical for all six groups
(the full unshifted table is in `check.log`); only `drift` has different
removal counts, because its label schedule differs by split as explained in
§3.2b.

| cause group | best feature | baseline AUROC | after brief3 removal | delta | after any-finding removal | delta | negatives removed (brief3 / any) |
|---|---|---:|---:|---:|---:|---:|---:|
| drift | `drift_out_of_band_increase` | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 8025 / 9570 |
| unsupported_claim | `claim_support_failure_share` | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 5890 / 7118 |
| misquote | `value_relative_error` | 0.9999 | 0.9999 | 0.0000 | 0.9999 | 0.0000 | 5816 / 7121 |
| poisoned_note | `note_external_tool_unsourced_share` | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 8302 / 9371 |
| authority_spoof | `auth_unsigned_and_excess` | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 8351 / 9368 |
| stale_thesis | `stale_invalidated_buy` | 0.8836 | 0.8491 | −0.0345 | 0.8581 | −0.0255 | 7820 / 9491 |

Five of six cause groups do not move: T03's structural features read
provenance, spans, book state and thesis timing, not binding prose. The
stale-thesis number falls because the removed clean negatives were unusually
easy negatives for that feature. It stays above the 0.80 bar (0.8491 after
the brief-three removal; 0.8581 after removing every finding). T03's shifted
pass bar still prints PASS.

### 3.4 T05 re-score with incoherent negatives removed

T05's fixed sample: **1,440 actions from 360 episodes**, **1,117** y=0 rows.
Removing incoherent negatives drops **418** (brief-three) or **510** (any
finding) of them over the whole sample. T05's own AUROC definition and feature
targets are reused. The table below is the shifted half (554 y=0 rows), which
is the split T05's pass bar uses; all registered readers:

| feature | reader | baseline | brief3-filtered | delta | any-filtered | delta |
|---|---|---:|---:|---:|---:|---:|
| hype | lexicon | 0.6711 | 0.6711 | 0.0000 | 0.6711 | 0.0000 |
| hype | nli | 0.9994 | 0.9993 | −0.0001 | 0.9992 | −0.0002 |
| hype | embed_lr | 0.9664 | 0.9867 | +0.0203 | 0.9877 | +0.0213 |
| hype | decision | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0.0000 |
| authority_language | lexicon | 0.8448 | 0.8448 | 0.0000 | 0.8448 | 0.0000 |
| authority_language | nli | 0.9996 | 0.9996 | 0.0000 | 0.9995 | −0.0001 |
| authority_language | embed_lr | 0.9358 | 0.9407 | +0.0048 | 0.9364 | +0.0006 |
| authority_language | injection | 0.5319 | 0.5250 | −0.0069 | 0.5233 | −0.0086 |
| authority_language | injection_fmops | 0.6242 | 0.6244 | +0.0002 | 0.6266 | +0.0024 |
| authority_language | decision | 0.9238 | 0.9296 | +0.0058 | 0.9308 | +0.0069 |
| support_gap | lexicon | 0.8432 | 0.8423 | −0.0009 | 0.8419 | −0.0013 |
| support_gap | nli | 0.9903 | 0.9916 | +0.0013 | 0.9904 | +0.0001 |
| support_gap | embed_lr | 0.6821 | 0.6950 | +0.0130 | 0.6918 | +0.0097 |
| support_gap | decision | 0.9983 | 0.9974 | −0.0009 | 0.9971 | −0.0012 |

T05's registered selections (`og_s1.text.DEFAULT_READERS`: NLI for hype, the
decision reader for authority_language, NLI for support_gap) move by at most
+0.0069: authority decision +0.0069 any / +0.0058 brief3, support NLI +0.0001
any / +0.0013 brief3, hype NLI −0.0002 any / −0.0001 brief3. The raw best
decision reader on support_gap moves −0.0012. The largest movement anywhere is
`embed_lr` on hype, +0.0213 any / +0.0203 brief3. The T05 text channel is
therefore not materially rewarded by the v2 binding defect; the defect mainly
matters for training a model that treats incoherence as normal and for false
positives in a reader that does notice binding.

### 3.5 v2.1 and the new `binding_error` family

`data/ref_v21/` has **3,600 episodes** and **432,000 actions** (nine families
× 200 episodes × two splits; 24,000 actions per family per split), validated
with **0 errors**. The capture prints the generation elapsed time and
throughput; those are wall-clock values and are not treated as results.

- Every v2.1 **y=0** action (including all hard negatives): **0** coherence
  findings, across all nine families and both splits (the corpus has 432,000
  actions in total).
- Every v2.1 **y=1** action outside `binding_error`: **0** findings. In v2.1
  incoherence appears only in the new family.
- `binding_error`: **6,605 positives per split** (13,210 total), and
  **6,372 hard negatives per split** (96.5% of the positive count, 26.6% of
  the family's 24,000 actions). Hard negatives are explicit "versus"
  comparisons.
- Coherence check on `binding_error` (shifted, and identical unshifted):
  **recall 1.0000**, **false-positive rate 0.0000** on hard negatives.
- Every `binding_error` positive's findings intersect its `cause_refs`:
  **0 misses** in both splits, checked across the full corpus (not just the
  test seeds).
- Finding counts in the shifted family: rationale_direction 1,725;
  claim_source_entity_mismatch 1,578; claim_foreign_instrument 1,663;
  claim_stale_period 3,636. Some actions raise more than one finding, which is
  why the sum exceeds 6,605. `rationale_foreign_instrument` and
  `claim_not_about_trade` are deliberately absent: the family plants binding
  errors, not missing-topic or peer-naming rationales.

Pass-bar items: v2 reproduces byte for byte; v2.1 clean has zero findings;
`binding_error` has more than 2,000 positives and more than 20% hard
negatives; recall is 1.0, hard-negative FPR is 0.0 and `cause_refs` misses are
0 on the shifted split; no API spend.

## 4. What did not work

- **A previous `check.log` was corrupted by overlapping runs.** Two `run.sh`
  invocations wrote the same log; the second truncated the file while the
  first still held its old offset, leaving a duplicated tail. `run.sh` now
  takes a lock, writes a temporary capture and moves it into place on success,
  and fails if any section heading appears other than once. The current
  capture passes that integrity check 9/9.
- **The first v2.1 pass broke v2 byte-for-byte.** Moving the coherent
  rationale call ahead of the claim call in `_open_thesis` changed the RNG
  order. Fixed by preserving the original call order on the default path;
  the final run is 3,200/3,200 identical.
- **Some planted direction errors were invisible.** The first
  wrong-direction plant could randomly pick "Fresh filing ... acting
  accordingly", which carries no direction cue and is in both side lists.
  Fixed with dedicated `WRONG_DIRECTION_ON_BUY` / `WRONG_DIRECTION_ON_SELL`
  lists and broader "increase/build the {company} position" cues.
- **Same-time documents were treated as different periods.** The period check
  first used document ordinal, so two filings at the same `t` made each
  other stale. Fixed to require a strictly later `t`.
- **The first T05 re-score was wrong.** It reused one episode's context for
  every episode in a file, which removed nearly all negatives and produced
  nonsense. Fixed to build a context per episode; the corrected removal is 418
  (brief-three) / 510 (any).
- **The first T05 re-score run crashed after 11 minutes** on a wrong module
  attribute (`FEATURES` lives in `og_s1.text`, not T05's evaluate module).
  Fixed, and a small score cache now makes reruns cheap.
- **The sector-level unsourced fallback is unused in practice.** Because the
  coherent generator adds a filing when an instrument has no document, every
  clean claim has a real source. This is a deliberate deviation from writing
  an unsourced placeholder; see Judgement calls.
- **The period check is strict and makes v2 look worse.** It is not one of
  the brief's three checks: 11.5% of unshifted v2 negatives have a stale
  period under it. That is a real binding defect for the current-period
  reading of the action, but it is stricter than "no claim about the traded
  name" and is reported separately.

## 5. Judgement calls

- **Choice: a code check with six findings, not a text classifier.**
  Alternatives: (a) the brief's three checks only; (b) an NLI or LLM reader
  over the rationale and claims. The three-check-only version cannot detect
  a wrong-entity or wrong-period claim that still names the traded name, so
  `binding_error` recall would fail. A text classifier needs training data,
  is harder to debug, and has no provable bound on false positives. The code
  check is deterministic, causal, sub-millisecond, and its failures are
  inspectable. The extra `claim_foreign_instrument`,
  `claim_source_entity_mismatch` and `claim_stale_period` findings are what
  make the new family detectable. Evidence that would flip it: an independent
  world where these checks cannot parse the surface form because the entity
  map or fact phrases are not available; then the check would need a supplied
  lexicon or an NLI fallback.
- **Choice: detect wrong-period claims by "a strictly later document reports
  the same fact name for the same instrument".** Alternatives: (a) look for
  explicit temporal words ("last quarter", "current") and compare to document
  age; (b) drop the wrong-period subtype and keep only entity/direction
  plants. Explicit temporal words are easy to paraphrase and would miss the
  value-level defect; dropping the subtype would not meet the brief's four
  plants. The document-age rule is objective and needs no wording. Evidence
  that would flip it: a world where older-period figures are legitimately
  cited as history and the action says so; then the check would need the
  temporal wording as a guard.
- **Choice: v2.1 adds a filing when the traded instrument has no document,
  rather than making an unsourced sector-level claim.** The brief allows a
  sector-level template that names no other company. An unsourced claim would
  be flagged by T03's support checks and would make a "clean" v2.1 action
  structurally unsupported. A sourced filing about the traded name is true,
  citable and keeps the clean family coherent. The sector-level templates
  remain in the code for the no-fact fallback. Evidence that would flip it: a
  requirement that v2.1 not add documents at all, in which case the fallback
  would need to be an explicitly portfolio-level (non-factual) statement and
  the coherence check would need to accept it.
- **Choice: `cause_refs` name the document that carries the misbound claim
  or rationale figure, not a claim id.** The schema deliberately gives claims
  no id and says a `cause_ref` is always a document or a note. Adding claim
  ids would change v2 serialization (or silently extend the schema) and every
  downstream reader. The document is the carrier of the claim, and the
  coherence finding points at the same document, so the test can intersect
  them. Evidence that would flip it: a schema revision that assigns claim ids
  and requires claim-level attribution.
- **Choice: report all-action and negative-only finding counts as separate,
  explicitly labelled tables.** Alternatives: (a) report only the negative
  counts the report uses; (b) report only the all-action counts. The first
  hides that some findings are expected on the planted positives, and the
  second makes a positive-only count look like a clean-action false positive.
  The two tables make the `claim_source_entity_mismatch_all = 3,174` count
  traceable to the 3,174 `unsupported_claim` positives and show 0 on every
  negative. Evidence that would flip it: none; this is presentation, not a
  measurement choice.
- **Choice: report two removal sets for the re-scores.** "Brief3" removes
  negatives with any of the brief's three findings; "any" also removes
  claim-foreign, source-entity and stale-period negatives. The brief's
  examples match the first, while the extra findings are the same binding
  defect at claim level. Reporting both avoids claiming a larger correction
  than the brief requested. The headline movement is small either way; the
  stale-thesis T03 delta is −0.0345 brief3 versus −0.0255 any.
- **Choice: hard negatives are explicit same-sentence comparisons.** A peer
  named with "versus" / "compared with" / "relative to" in the same sentence
  as the traded name is not a binding error; a peer named alone is. This is
  the narrowest reading that keeps the named hard negatives clean. Evidence
  that would flip it: an adversary that puts a comparison word in a sentence
  while still passing off a peer's number as the traded one; the check would
  need claim-level value matching rather than sentence-level cues.
- **Choice: use T05's decision cache, never the network.** The brief sets a
  zero API spend. The script checks every response key before calling
  `decision.score` and skips the reader if any key is missing. All 1,440 keys
  were present. Evidence that would flip it: a brief that allows spend and a
  cache that is incomplete.
- **Choice: the default v2 record's `meta.author` is unchanged; v2.1 records
  use `reference-v2.1`.** This keeps v2 byte-for-byte and makes provenance
  explicit. No downstream scorer reads `author`.
- **Choice: follow the brief's explicit file list over the general
  task-folder rule.** The brief directs `og_s1/coherence.py`, the generator
  option in `og_s1/world.py`, `og_s1/generate.py`, `og_s1/validate.py`,
  `SCHEMA.md` and `og_s1/tests/test_coherence.py`. I treated those as
  task-authorized writes; everything else stayed in `work/T31/` or the
  git-ignored `data/` directory. No T03 or T05 file was edited.

## 6. Loopholes I checked

- **Labels and `meta` are not inputs.** `case_for_step` filters documents,
  theses and the action itself; it never reads `label` or `meta`. The surface
  form is inferred from document text, not from `meta.shifted`. One test flips
  every label to `binding_error`; another flips `meta.shifted`; the findings
  are unchanged in both.
- **Causality.** Cases include only documents with `t <= action.t`; the
  shared context's stale-period table is filtered by `t > source_t` and
  `t <= action.t`. A document at a later step cannot make an earlier action
  stale.
- **Shifted text.** The check uses the shifted company-name map and shifted
  fact phrases. `rescore_t03.py` compares the shifted and unshifted action
  structures and finding sequences item by item; they are identical for seven
  of eight families, and the one exception (`drift`) is a documented
  shift-dependent label schedule in the generator, not a check failure. The
  v2.1 shifted recall/FPR are 1.0/0.0.
- **Hard negatives.** All 6,372 per split carry an explicit "versus" and
  have zero findings; the check does not flag a peer merely for being named
  in a comparison.
- **v2 byte-for-byte.** The script simulates all 3,200 episodes from their
  seeds and compares the exact JSON string, not a parsed equality.
- **No test-set peeking.** `data/heldout*`, T02, T06 and T16 were not opened.
  v2.1 was generated from the same seeds as v2, not tuned on held-out data.
- **No API spend.** The decision reader is cache-only; the run prints
  "scored from cache (no network call)". No keys are read or written.
- **Validator.** All 3,600 v2.1 episodes validate with zero errors, including
  the new non-empty `cause_refs` rule for `binding_error`.
- **`cause_refs` resolution.** Every `binding_error` positive has at least
  one finding whose `refs` intersect its `cause_refs`. The test suite checks
  four seeds in both splits; `analyze_v21.py` checks every positive in the
  full corpus and reports 0 misses in both splits.
- **T03/T05 untouched.** Their files were imported, not edited. Their
  headline definitions (best single feature per cause group; T05's
  `_feature_target` and `auroc`) are reused verbatim.
- **Single clean capture.** `run.sh` locks against concurrent runs, writes to
  a temporary log and moves it into place only on success, then verifies each
  section heading appears exactly once. The current capture passes 9/9.
- **No large files.** The task folder is small; v2.1 lives in the git-ignored
  `data/` directory, and `run.sh` prints its size.

## 7. Open risks

- **Circularity.** The `binding_error` family and the coherence check were
  written by the same hand. Recall 1.0 is evidence that the plants are
  detectable as specified, not that real-world binding errors are caught. The
  independent worlds and T16's messy benchmark remain the real test.
- **The period rule is stricter than the brief's wording.** It treats any
  older same-name fact as stale when a later document reports a different
  value, even if the action does not claim "current". If the lead wants only
  explicit temporal claims, the v2 rate falls and the `binding_error`
  wrong-period plant would need temporal wording.
- **v2.1 adds documents on demand.** Episodes, actions, seeds and labels keep
  the v2 shape, but the document stream differs for instruments with no prior
  document. Downstream text models see more filings than in v2. This is
  necessary for sourced claims but is a distribution change beyond the
  binding fix.
- **A comparison claim that cites the peer's document would be flagged.**
  The hard negatives cite the traded name's document for the traded figure
  and mention the peer's figure in the same sentence. A schema with one
  `source_doc` per claim cannot attach both; if a real action cites the peer's
  filing for the peer leg, `claim_source_entity_mismatch` would fire. The
  intended fix is per-span attribution, not a looser check.
- **Reference-specific entity map.** `coherence.py` imports the reference
  world's company names and fact phrases. `case_from_view` accepts an
  `entity_names` override, but an independent world with different fact
  names would need a supplied phrasing table.
- **T05 re-score is a 1,440-action sample with point estimates.** It uses
  T05's official sample and metric code, but no new confidence intervals were
  computed; the deltas are small relative to the sample.
- **T05's registered selection is a moving target.** The current
  `og_s1.text.DEFAULT_READERS` selects NLI for hype, the decision reader for
  authority_language and NLI for support_gap. This round re-scored every
  registered reader, not only the selected ones, so the table remains usable
  if T05 changes its selection again.
- **Decision cache provenance.** If T05's cache is deleted or its key format
  changes, the decision reader is skipped rather than recomputed; the local
  readers still reproduce.
- **Disk.** v2.1 lives in git-ignored `data/`; its size is printed by the
  capture. The task folder stays small, but the lab Mac is tight on space.

## Recommendation (the lead decides)

Move any task that trains, selects or evaluates on the reference world to
v2.1: **T04** (model zoo), **T05** (text channel re-run), **T07**
(integration), **T11** (GPU readers), **T12** (owner adaptation), **T14**
(taint/why graph), **T15** (frozen evaluation), and **T19** (minimal pairs).
T03's structural code does not need retuning (its numbers barely move), but
its regression runs should use v2.1 so the stale-thesis number is not flattered
by incoherent negatives. T16 and the independent T02 worlds are unaffected
because they do not use the reference generator. Keep `data/ref/` frozen as
the v2 audit corpus; generate v2.1 from the same seeds as `data/ref_v21/`.

## Round 2 changes

Round 1's review was `VERDICT: REVISE` with four provisional items. I fixed
them in order of importance and re-ran the whole entry point; the current
`check.log` is a single successful capture with the integrity check passing
9/9.

1. **Corrupted/duplicated `check.log` (most important).** The old log was
   written by two overlapping `run.sh` processes, so the second truncation
   left the first process's tail in place. `run.sh` now takes a lock, refuses a
   concurrent run, writes to a temporary log, moves it into place only on
   success, and checks that every section heading appears exactly once. The
   duplicated capture is gone.
2. **Report/log timing mismatch.** I removed the hand-copied generation
   timing from REPORT.md. The capture still prints elapsed time and throughput,
   but they are wall-clock values that vary with machine load and are
   explicitly not treated as results.
3. **`claim_source_entity_mismatch=3,174` looked inconsistent with "0 on every
   negative".** It was a column-semantics problem, not a counting error: the
   first table counted findings over all actions. The script now labels those
   columns `*_all`, adds a positive-only table, and keeps a separate
   negative-only table. The 3,174 is exactly the number of `unsupported_claim`
   positives whose planted unsupported claim cites a sibling's filing; the
   negative-only count is 0 for every family and split. REPORT.md §3.2 spells
   this out.
4. **Byte-identical shifted/unshifted rates needed a code-level explanation.**
   §3.2b now gives it and the run now proves it structurally: for seven of
   eight families the shifted and unshifted action structure and finding
   sequences are identical item for item. `drift` is the only exception
   because `_World._drift_prob` deliberately uses a different schedule when
   shifted; that is why its positives and removal counts differ.

5. **A latent `meta` read in context building.** `build_context` used
   `meta.shifted` to choose the entity map, which contradicted REPORT.md's
   "never reads `meta`" claim and the schema's evaluation-only rule. It now
   infers the surface form from the first decisive ticker or company-name
   mention in the documents, never from `meta`, and a guard test flips
   `meta.shifted` and asserts the findings are unchanged. I verified the
   inference against all 3,200 v2 and 3,600 v2.1 episodes; every inferred flag
   matches the generator's, so no finding count changed.

I also added two measurement checks while I was in the code: the full-corpus
`binding_error` recall table now also counts positives whose findings do not
intersect their `cause_refs` (0 in both splits), and the report no longer
quotes the brief's rough percentages as if they were measured numbers.

What I did **not** change, and why:

- I did not change the binding-check logic, the v2.1 generator, the
  `binding_error` plants or the hard negatives. The review found reporting and
  capture defects, not a failure of the check; changing the generator would
  make the v2.1 numbers incomparable. The only `coherence.py` change is the
  surface-form inference above, and it leaves every v2 and v2.1 finding count
  unchanged.
- I did not edit any T03 or T05 file. Both are imported read-only, as the brief
  requires. Their re-scores are computed from their own feature and reader
  code.
- I did not change the brief's pass bar or reclassify any result. I did update
  the test-suite count (140 passed in this capture) and the T05 selected-reader
  commentary because T05's current `DEFAULT_READERS` selects the decision
  reader for authority_language; the re-score table already covers every
  registered reader, so no number had to be recomputed for that change.
- I did not add new required test cases. The existing
  `og_s1/tests/test_coherence.py` already covers the brief's four required
  cases; I added only the one guard test for the `meta` inference. The new
  full-corpus `cause_refs` check lives in the reproducible analysis script so
  it checks every corpus positive rather than four seeds.
