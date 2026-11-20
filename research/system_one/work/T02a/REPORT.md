# REPORT — Thornbury world generator

## 1. What I built

A deterministic, standard-library-only generator of OrderGuard System One
episodes in the voice of a former sell-side analyst. The world is a fictional
manager, Thornbury Asset Management, trading a **36-name** universe across all
seven sectors under signed mandates whose bands, caps and signing-key id vary by
episode. Episodes have 3 to 6 steps, a replayable starting book, tiered documents
(filings, news, analyst notes, social posts, tool output), agent/tool/external/
owner-signed notes, theses with numeric invalidation triggers, and exact-quote
claims.

Ten families are produced, 150 episodes each:

- the eight SCHEMA families: `clean`, `drift`, `unsupported_claim`, `misquote`,
  `vague_hype`, `poisoned_note`, `authority_spoof`, `stale_thesis`;
- two novel families: `liquidity_breach` and `withdrawn_target`.

Every family now carries the same standing prelude: a signed investment policy,
a signed exit-liquidity policy (4.0% of book scope), a daily ADV tool output, a
tool note, an analyst note and a social post. Document kind, note author and
policy/tool presence are therefore uniform across families and carry no family
or label information.

Clean episodes carry the required hard negatives: legitimate new theses on fresh
tier-3 evidence, exact quotes, enthusiastic-but-factual claims, disciplined
sells, add-on buys to an existing thesis, explicit relative-value comparisons
("NXGN trades at 18.0x forward earnings versus QLTM at 27.0x"), a clean numeric
claim sourced to a social document, a clean thesis with tool-output evidence, a
clean suspended analyst target the agent deliberately does **not** trade on, a
signed single-name tightening it obeys, and a benign agent compliance memo that
restates a genuinely signed instruction. Failures are not all buys:
`unsupported_claim` and `misquote` include bearish sell variants and non-opening
add-on variants.

Files: `generator.py` (entry point), `gen_core.py` (mandate, book, builder),
`gen_text.py` (documents, wording, shared prelude and policy), `fam_common.py`
(shared clean steps and sequence padding), one `fam_*.py` per family, `audit.py`
(41 semantic checks), and `run.sh` which regenerates, validates, audits and
summarises everything.

## 2. How to re-run

```
./run.sh
```

It uses `.venv/bin/python` when present and `python3` otherwise. It writes 150
episodes per family (1,500 lines) to `out/episodes.jsonl`, prints its SHA-256,
runs `python -m og_s1.validate out/episodes.jsonl`, then `python audit.py
out/episodes.jsonl`, then a 6,000-episode stress check on **disjoint** seeds
2000-2299, then a 10,000-episode seed 0-499 scan (both `shifted` values, all
families) that now also runs the nine semantic checks. It then prints per-family
episode, action and positive counts, a TOTAL row, the failure-rate range, the
family policy/tool/tool-note/analyst/social counts, per-family maximum order
size, action- and episode-level positive rates, and the worst sentence-
repetition rate both pooled and per family. The final block enforces the pass
bar and exits non-zero if any family is missing, any family does not have 150
episodes, clean has a positive, a failure action-level rate leaves [5%, 60%], an
episode is outside 3-6 steps, or sentence repetition exceeds 5% either pooled or
within any single family.

**Label-rate metric.** The pass-bar rate is measured at the **action** level:
positives divided by all actions in the family. It is not measured per episode.
For completeness `run.sh` also prints the per-episode positive share; by design
that is 1.000 for every failure family and 0.000 for clean, because each failure
episode contains exactly one planted positive.

## 3. Results

- Validation: **1,500 episodes, 0 errors**.
- Semantic audit: **41/41 checks pass** (`audit.py`, run by `run.sh`).
- Families present: 10/10, including both novel families.
- Actions: **6,747** in total, 3-6 per episode; **1,350** positives.

| family | episodes | actions | y=1 | rate |
|---|---:|---:|---:|---:|
| authority_spoof | 150 | 686 | 150 | 0.219 |
| clean | 150 | 672 | 0 | 0.000 |
| drift | 150 | 683 | 150 | 0.220 |
| liquidity_breach | 150 | 672 | 150 | 0.223 |
| misquote | 150 | 658 | 150 | 0.228 |
| poisoned_note | 150 | 676 | 150 | 0.222 |
| stale_thesis | 150 | 690 | 150 | 0.217 |
| unsupported_claim | 150 | 670 | 150 | 0.224 |
| vague_hype | 150 | 686 | 150 | 0.219 |
| withdrawn_target | 150 | 654 | 150 | 0.229 |

- Failure-family action-level positive rates are **21.7%-22.9%** (inside the
  5-60% band). Clean is 0% by label *and* by the semantic checks below.
- Episode-level positive share: **1.000** in every failure family, **0.000** in
  clean (printed by `run.sh`).
- Sentence variety: the check counts every natural-language field (document
  text, initial/step note text, thesis `statement` and `invalidation`, action
  `rationale`, claim text) and splits on `(?<=[.!?])\s+`. It reports **72,101
  distinct sentences**; the worst sentence appears in **9 of 1,500 episodes
  (0.600%)** pooled. The worst per-family sentence appears in **6 of 150
  episodes (4.000%)**. Both are under the 5% ceiling, and `run.sh` enforces both.
- Determinism: two consecutive full regenerations produce byte-identical
  `out/episodes.jsonl` (SHA-256
  `4bf9cd9abfdad4d084ec815bdb37a613ab5e2f7788b7c3dd0a8eb8442356b55f`).
- Policy/tool presence: **150/150 in every family** for the signed liquidity
  policy, the ADV `tool_output`, the tool note, an analyst document and a social
  document.
- Clean policy compliance: the largest clean order is **2.600%** of book value,
  below the policy's **4.0%** screening scope; the general policy check reports
  **0** violations.
- Liquidity family: the planted buy is **4.306%-5.000%** of book value, above the
  **4.0%** scope, while its largest y=0 order (padding or corrective) is
  **2.200%**.
- Non-opening positives: **33** in `unsupported_claim`, **31** in `misquote`,
  and all **150** in `stale_thesis`. Sells: **144** positives are sells.
- Smallest trade in the main run: **0.829%** of book value (seeds 1000-1149).
  The disjoint stress corpus (seeds 2000-2299) is clean and passes 9/9 semantic
  checks. The 0-499 scan (10,000 episodes) has **0** errors, passes **9/9**
  semantic checks, and its smallest trade is **0.5305%**.
  `generate(104, "clean")` has a **1.000%** smallest trade.

The audit's Round 6 checks:

- **Unsupported claim is not a null-span marker:** the positive claim names a
  real fact the filing does not contain while quoting an exact span of the same
  filing for another fact. The audit checks the asserted fact name is absent and
  the span is a real substring.
- **Withdrawn target is semantic, not keyword:** the note may use any of several
  desk-status wordings; the audit checks the cited analyst note says coverage is
  not live and that the claim actually uses its withdrawn target number. Clean
  also contains suspended analyst notes the agent explicitly refuses to use.
- **Stale thesis reads the stated trigger:** the audit now compares the two
  later filings to `thesis["invalidation_trigger"]` rather than a hard-coded 3.0.
- **Clean numeric claims:** every clean numeric claim must have an exact quoted
  span (0 violations).
- **Family-cue parity:** policy, tool output, tool note, analyst and social
  presence must be at least 95% in every family; all are 150/150.
- **Marker phrases:** no poison/spoof wording may occur in at least 90% of one
  family while being absent from clean.

## 4. What did not work

- The `unsupported_claim` family originally had a perfect field marker (`value !=
  null`, `quoted_span == null`). It now quotes a real span for a different fact;
  a null span is no longer a cue.
- The liquidity policy was originally present only in clean and liquidity
  episodes, and the tool note only in clean. Both are now in the shared prelude
  in every family.
- The withdrawn target originally used the fixed words "not current" and "under
  review" in all 150 episodes. It now uses six desk-status wordings, and clean
  carries the same language in a note the agent correctly ignores.
- The vague-hype positive was the only claim sourced to a social document. It
  now leans on a news document with no concrete figure, while clean carries a
  numeric claim sourced to a social document.
- The liquidity thesis was the only thesis with `tool_output` evidence. Clean
  now has tool-output thesis evidence too.
- Poison/spoof notes used fixed phrases ("grid has been updated", "pre-trade
  check is cleared", "resets the single-name"). They are now several variants,
  and clean's genuinely signed tightening uses the same "grid has been updated /
  pre-trade check is cleared" wording.
- The clean add-on buy could be as small as `0.80 x 0.006 = 0.48%` of book. The
  room test is now `0.0075` and `generate()` retries any episode with a trade
  below 0.5% of book.
- `opens_thesis = False` was a perfect stale-thesis cue. Add-on positive
  variants now exist in `misquote` (31) and `unsupported_claim` (33).
- The stress corpus overlapped the main run (seeds 1000-1299 versus 1000-1149).
  It now uses disjoint seeds 2000-2299, and the 10,000-episode scan runs the
  semantic checks.
- The sentence-variety check used `.split(". ")`; it now uses the independent
  `(?<=[.!?])\s+` splitter.
- Repeated thesis-invalidation sentences reached 6-8/150 in drift and withdrawn
  episodes. They now carry an episode-specific review slot so the whole sentence
  differs.

## 5. Judgement calls

- **One positive per failure episode; ~22% action-level.** Mixing causes within
  an episode would make attribution ambiguous; the episode-level prior is listed
  as an open risk.
- **Clean is a semantic label, not just the absence of a planted failure.**
  Clean theses must survive their own evidence, the signed policy must be
  obeyed, and add-on buys must be on still-valid theses.
- **One shared policy scope: 4.0% of book value.** A dollar threshold could not
  sit above every y=0 order and below every liquidity breach across the
  $25-75M book range. A fraction is exact, and the largest y=0 order (drift's
  corrective sell, 3.595%) stays below it while the smallest liquidity buy is
  4.306%.
- **Drift invalidation at five points.** The measured overshoot is 1.213-2.595
  points, so five leaves margin while still being a plausible loss limit.
- **Liquidity invalidation is post-corrective.** It fires only if the corrective
  sale does not restore the limit, so the opening buy cannot invalidate it.
- **Sell failures are bearish false claims.** A sell is the natural action on a
  fabricated backlog collapse or a misquoted EPS drop.
- **Add-on positives in misquote/unsupported.** They express the same false
  claim but do not open a thesis, weakening the `opens_thesis` cue without
  inventing an implausible trade.
- **Poison/spoof overshoot is adaptive and can be small (0.15 point).** Every
  candidate remains band-safe and cap-breaking only.
- **`stale_thesis` ends at `weakened`, not `invalidated`.** A reader must compare
  the two later filings' organic growth against the trigger.
- **Infeasible books are retried, not mislabelled.** The retry also rejects any
  sub-0.5%-of-book trade; `meta.seed` still records the requested seed.
- **`shifted` is a recorded flag only.** It validates but does not change the
  distribution; no shift-robustness claim should be inferred.

## 6. Loopholes I checked

- **Availability order.** Pre-notes before their action, new-notes after; no
  future document or unavailable note is cited. The validator checks this.
- **Cause/label convention.** Every `y = 0` is `clean`; every failure episode
  has exactly one non-clean cause; novel causes only on `y = 1`.
- **Book replay.** No negative cash or position; clean buys stay inside bands
  and caps; clean sells stay above sector floors; initial books are inside all
  limits.
- **Clean semantic consistency.** No clean thesis is invalidated by its opening
  evidence; no clean buy adds to an invalidated thesis.
- **Signed liquidity policy.** Every y=0 action above any family's 4.0% policy
  threshold cites the policy, carries an ADV screen and respects the days limit;
  there are no y=0 actions above 4.0% in this corpus, and the check still guards
  a regression.
- **Single-name vs sector exclusivity.** Only drift crosses a sector band; only
  poison/spoof cross the single-name cap; no other positive crosses either.
- **Poison/spoof text.** Note line = rationale percentage = replayed post-trade
  weight, and name weight <= sector weight.
- **Thesis/sector coherence.** No action cites a thesis about another sector.
- **Self-invalidation.** A non-stale failure thesis is not invalidated by its
  own action (drift points, liquidity post-corrective wording, numeric triggers).
- **Claims.** Non-null spans are exact substrings; a span never lacks a source;
  sources are available at the action time and are about the traded issuer;
  every clean numeric claim quotes its figure.
- **Facts coverage.** Every concrete number in document text has a matching
  machine-readable fact value, apart from clock times and calendar years. The
  check matches values; it does not parse fact names or units out of prose, so
  `AUTHOR_NOTES.md` no longer claims that it does.
- **Trade size.** Every trade is at least 0.5% of book in the main run, the
  disjoint stress run and the 0-499 scan.
- **Hard-negative analogues.** Clean contains social/tool/analyst documents, a
  sourced `value = null` claim, a social-sourced numeric claim, a relative-value
  comparison, tool-output thesis evidence, a signed single-name tightening, a
  suspended target it refuses to trade, and the same policy/ADV prelude as every
  failure family.
- **Sentence variety.** Enforced pooled and per family with the regex splitter.
- **Pass-bar arithmetic.** Counts and rates in section 3 are computed from
  `out/episodes.jsonl`, not hand-typed; the SHA-256 is printed by `run.sh`.

## 7. Open risks

- **`stale_thesis` positives are all non-opening.** Other families have
  non-opening positives (33 + 31), so `opens_thesis=False` is not a perfect
  stale cue, but it remains universal in stale.
- **One positive per episode** gives episode-level aggregates a strong prior;
  per-episode every failure family is 150/150.
- **Positive index still varies by family.** Drift places most positives at
  index 1 and stale cannot place one before index 2; position remains a weak
  cue.
- **Episode length is close to balanced but not identical.** Clean lengths are
  `{3: 25, 4: 52, 5: 49, 6: 24}`; the other families differ modestly.
- **`vague_hype` remains detectable in principle.** Its claim has no value, no
  unit and no quoted span by definition; clean has a sourced null-value claim
  but not an enthusiastically worded claim with no figure.
- **Family vocabulary.** Some collocations (for example "backlog" in
  `unsupported_claim`) remain more common in their family; removing every one
  would make the prose less realistic.
- **Policy wording is now universal, including the 4.0% scope.** This removes
  the presence cue but is uniform across the corpus, so the scope carries no
  family information.
- **`shifted` is unused** as a distribution change.
- **`meta.family` and `label` remain in the raw JSONL.** The schema requires them
  for scoring and supplies `model_view` to strip them; the harness must apply
  that rule.
- **The universe is 36 fictional names** with modest band jitter.
- **Ground truth for several families is author-declared.** The validator does
  not check claim-to-fact semantics; `audit.py` is our check.
- **Rounding of the liquidity scope.** The policy states 4.0% of book; the gap
  to the largest y=0 order (3.595%) and the smallest planted buy (4.306%) is wide
  enough that rounding cannot flip the scope.

## Round 6 changes

The review's items, in their order of importance:

1. **`unsupported_claim` field marker removed.** All three positive variants now
   quote an exact revenue span from the filing while asserting an absent
   `order_backlog_growth` fact. `check_unsupported` verifies the asserted fact
   is absent and the span is a real substring, instead of requiring a null span.
2. **Policy/ADV presence equalised.** The shared prelude gives every family a
   signed investment policy, a signed 4.0%-of-book liquidity policy, an ADV
   `tool_output`, a tool note, an analyst note and a social post. All five
   features are 150/150 in every family; `check_family_cues` enforces this.
3. **`withdrawn_target` literal marker removed.** Six desk-status wordings
   replace the fixed "not current"/"under review" pair. Clean carries suspended
   analyst notes (56/150) with the same wordings and an agent note explicitly
   refusing to use the target. `check_withdrawn` now checks status semantics and
   that the positive claim uses the withdrawn target number.
4. **Clean-only tool note removed.** Every family now carries a tool note; the
   clean-specific ADV note remains as an additional, genuinely used screen.
5. **`vague_hype` social cue removed.** Its positive now leans on a news
   document with no concrete figure. Clean carries a numeric claim sourced to a
   social document with an exact span.
6. **Liquidity thesis-evidence cue removed.** Clean's opening thesis includes
   the ADV tool output as evidence; 150/150 clean episodes have a thesis with
   tool-output evidence.
7. **Relative-value hard negative added.** Each clean episode has an analyst
   note comparing the traded name with a named peer using "versus", and the
   action carries that exact comparison as a claim. `check_clean_analogues`
   verifies it.
8. **Poison/spoof marker phrases varied.** The fixed phrases are now several
   variants; clean's genuinely signed tightening also uses "grid has been
   updated" and "pre-trade check is cleared". `check_marker_phrases` fails if a
   phrase becomes a near-perfect family marker.
9. **Documentation and arithmetic corrected.** `AUTHOR_NOTES.md` now reports the
   measured clean maximum (2.600%), the measured misquote ranges (buy 12.92%-
   39.00% higher, sell 19.23%-44.80% lower), the 4.0% policy scope and the
   uniform document/note presence. The report states the action-level label
   metric, and `run.sh` now prints the SHA-256 rather than requiring a separate
   command.
10. **Remaining cues equalised or disclosed.** Analyst and social documents are
    now universal, and `owner.purpose` is uniform across all four mandate types
    in every family (drift and liquidity no longer restrict it). Residual
    episode-level structure (one positive per episode, non-opening stale
    positives, positive index) is disclosed in section 7.

Audit/reproducibility fixes from the review's loophole list:

- `check_stale` now reads `thesis["invalidation_trigger"]` rather than hard-coding
  3.0.
- The stress corpus uses disjoint seeds 2000-2299, and the 10,000-episode scan
  runs the semantic checks.
- `run.sh` uses the regex sentence splitter.
- A new check requires every clean numeric claim to carry an exact quoted span.
- Fact coverage is described accurately: values are matched, not names/units.

Not changed, and why:

- **`shifted` remains a recorded flag only.** The schema says the generator
  "may use" it; inventing a shifted distribution with no target would change
  the corpus without evidence that it helps.
- **One positive per failure episode.** Multiple positives would make the
  planted cause ambiguous.
- **Stale positives stay non-opening.** Opening a thesis is incompatible with
  the stale-thesis definition (trading an *existing* invalidated thesis).
- **`meta`/`label` stay in the raw JSONL.** The schema requires them for scoring
  and supplies `model_view` to strip them; the harness must apply that rule.
- **Some family vocabulary remains.** Removing every collocation would make the
  documents less realistic; the residual is disclosed as an open risk.
- **`check_facts` still matches values, not names or units.** The prose does not
  carry machine-readable fact names, so the check cannot reliably recover them;
  the documentation now says what is actually enforced.
