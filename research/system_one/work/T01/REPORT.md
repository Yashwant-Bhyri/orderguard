# T01 — World v2

## 1. What I built

A self-contained package `og_s1/` and the author-facing contract for the System
One world, revised through round 5 so that the world has an explicit, replayable
portfolio, an unambiguous intra-step event order, strict label/cause
consistency, and unambiguous stale-thesis failures.

- `og_s1/schema.py` — typed dataclasses (`Owner`, `Document`, `Note`, `Claim`,
  `Thesis`, `Action`, `Label`, `Step`, `Book`, `Episode`) with
  `to_dict`/`from_dict`, JSON-serialisable. `Document.content_hash` is sha256 of
  `text`. `model_view(episode)` returns the evaluation-stripped view.
- `og_s1/world.py` — the reference simulator `simulate(seed, family,
  n_steps=120, shifted=False) -> Episode`, with all eight families: `clean`,
  `drift`, `unsupported_claim`, `misquote`, `vague_hype`, `poisoned_note`,
  `authority_spoof`, `stale_thesis`.
  - The book is explicit: `Episode.initial_book` holds cash, per-instrument
    market values and per-sector totals; `Episode.instrument_sectors` maps every
    instrument to its sector. The simulator updates that same book, and the
    validator replays it from the episode alone.
  - Each step is `{action, pre_notes, new_notes, label}`. `pre_notes` are
    written before the action and are available to it; `new_notes` are written
    after it and are not.
  - The injected notice at a poison/spoof onset is created in `pre_notes` of the
    onset step, so the action that follows it cites a note that already exists.
- `og_s1/validate.py` — `validate(episode_dict) -> list[str]` and the CLI
  `python -m og_s1.validate <dir-or-jsonl>`. It checks the schema, all id
  references with causal availability, quoted spans, labels, monotone times, the
  book's internal consistency, the strict `y`/`cause` convention, and a full
  book replay against the mandate and the labels (gated on `y`, not on the
  cause string).
- `og_s1/generate.py` — writes the reference dataset and prints counts, label
  rates, positive buys/sells, the minimum positives per episode, pre-onset
  positives, repeat rate and throughput.
- `og_s1/tests/` — 54 pytest tests (determinism, family labels, book replay,
  band/position compliance, span substrings, `pre_notes` availability,
  label/cause convention and replay-on-relabel, stale-thesis buy-only positives,
  validator breakage kinds, `model_view`).
- `SCHEMA.md` — the author-facing contract (in the repo root).
- `work/T01/run.sh` — the single entry point.

## 2. How to re-run (one command)

```
bash research/system_one/work/T01/run.sh
```

It generates 200 episodes per family (unshifted) plus the same 200 shifted into
`data/ref/`, validates every file, prints the statistics, and runs pytest. Every
number below is printed by that command. `run.sh` writes its output to
`work/T01/check.log`, truncating it on each invocation, so the log always holds
exactly one clearly identified run (prefixed `== T01 world v2 single captured
run ==`). All deterministic numbers below reproduce exactly on every run; the
throughput figure is the sample from the report-time run and will vary with
machine load.

## 3. Results

From the final `run.sh` run (3200 episodes = 8 families × 2 shift settings ×
200; 24,000 actions per cell):

- Validation errors: **0** across 3200 episodes.
- Tests: **54 passed**.
- Sentence repeat rate: **1.36%** (9,710 duplicate sentences out of 712,896) —
  below the 5% bar.
- Throughput: **165.36 episodes/sec** on one CPU core (3,200 episodes in
  19.35 s). This is sampled wall-clock; see §7.
- Pre-onset positives: **0** for every failure family, unshifted and shifted
  (printed per line by `generate.py`).
- Clean episodes: **0 positives** in both datasets.

Label rate per family (positives / actions; 24,000 actions per cell):

| Family | positives | label_rate | shifted positives | shifted label_rate |
|---|---:|---:|---:|---:|
| clean | 0 | 0.0000 | 0 | 0.0000 |
| drift | 5,518 | 0.2299 | 3,627 | 0.1511 |
| unsupported_claim | 6,708 | 0.2795 | 6,708 | 0.2795 |
| misquote | 6,626 | 0.2761 | 6,626 | 0.2761 |
| vague_hype | 6,581 | 0.2742 | 6,581 | 0.2742 |
| poisoned_note | 6,250 | 0.2604 | 6,250 | 0.2604 |
| authority_spoof | 6,238 | 0.2599 | 6,238 | 0.2599 |
| stale_thesis | 2,536 | 0.1057 | 2,536 | 0.1057 |

`drift` is the only family whose rate changes under shift (the required "slower
drift"); all other families change wording/publishers only, so their labels are
identical. `stale_thesis` has 2,536 positives in round 5 (down from round 4,
whose positives included sells) because its positives are now **buys only** (see
§4 and the Round 5 changes). The run
prints `pos_sells=0` and `min_episode_positives=2` for both stale-thesis
corpora, so every one of those 200 episodes still has at least two stale-thesis
positives and none is a sell. (For reference, the run also prints
`min_episode_positives=0` for `drift`: a minority of drift episodes never get an
affordable post-onset buy, so they carry no positive. This is not new in round 5
(the drift generator is unchanged) and is noted in §7.)


## 4. What did not work

- My first document renderer joined sentences with `". "` while each template
  already ended in `"."`, producing double periods after each sentence. Fixed by
  joining with a single space.
- The first `stale_thesis` invalidation mutated the fact value in the fact pool
  without rewriting the document text, so the negative-guidance figure did not
  appear in the text and the validator correctly rejected the quoted span.
  Fixed by generating the invalidating document with the negative fact forced,
  so text, `facts` and the fact pool agree.
- An early draft of the note templates had constant sentences, which pushed the
  repeat rate well above the 5% bar. Fixed by giving every note sentence a varying element (a
  number, company, or the unique key).
- In round 2, sizing a "following" buy to fill a target band *exactly* and
  rounding it to 2 decimals could round to `0.0` when the sector was already
  within a few cents of the target. Fixed by falling back to a positive random
  notional whenever the fill amount is non-positive.
- **Round 4: the first explicit book spent all cash.** A second round of clean
  buys drove cash to $0, so a later injected note could never be followed and
  some `poisoned_note` / `authority_spoof` seeds had zero positives. Fixed by
  targeting 75% invested at the start and by keeping a 15% cash buffer on
  prudent buys (failure actions may spend into the buffer).
- **Round 4: an initial book could start outside a band.** The first allocator
  distributed extra weight in proportion to random draws and could push one
  sector above its `max`. Fixed by a capped water-filling allocator; the validator now also rejects any
  initial book outside its bands or caps.
- **Round 4: a drift label could sit a hair above the cap.** Flooring a dollar
  notional to cents once left a drift buy a floating-point hair above its cap. Fixed
  by labelling drift only when the buy leaves the sector at least 0.01% of
  portfolio value above `max`; otherwise the action is generated as an ordinary
  clean action.
- **Round 5: the validator trusted the cause string.** `_check_replay` checked
  bands only when `cause == "clean"`, so changing a drift positive's `y` to 0 (or
  substituting a novel cause on a band-breaking action) passed validation. Fixed
  by making the label convention strict (`y=0` ⇔ `cause="clean"`) and gating the
  replay's band/position checks on `y == 0`, not on the cause. The replay now
  also runs after a label-convention failure instead of being skipped.
- **Round 5: stale-thesis positives included sells.** In round 4 many
  stale-thesis positives were sells, which can be an owner-endorsed response to
  invalidation. Fixed by making every stale-thesis positive a **buy** on the
  invalidated thesis; a stale action with no affordable buy falls back to a
  clean action. This cut the family to 2,536 positives (still `pos_sells=0` and
  `min_episode_positives=2`).

No negative scientific results: every failure family produces positives in every
corpus, every clean episode is all-negative, and the validator catches all
planted breakage kinds in the tests.

## 5. Judgement calls

### 5.1 Method, library and metric choices (challenged per POLICY)

**Choice: procedural, template-based text generation.**
*Alternatives* — (a) LLM-generated document/note/claim text (an "LLM as world
author" paradigm); (b) a generative grammar / programmatic synthesis of
sentences; (c) real market filings and news with retro-fitted labels.
*Why templates win* — deterministic per seed (testable, reproducible), cheap (the
throughput bar is met on one CPU core, no model weights or paid calls), and they
let me place exact facts/claims so the ground-truth label is provably correct
rather than inferred. They also avoid an LLM leaking detector-shaped wording
into the reference set.
*Flip evidence* — if a later task shows the template surface is too uniform for
detectors, I would move to grammar-based synthesis first and an LLM author
second.

**Choice: typed `dataclass` schema with explicit `to_dict`/`from_dict`.**
*Alternatives* — (a) Pydantic models (validation-in-schema paradigm); (b) JSON
Schema + Protobuf (cross-language/versioned contract); (c) bare dicts.
*Why dataclasses win* — zero extra dependencies, JSON-serialisable by
construction, and the explicit round-trip makes "every number comes from code"
easy to audit.
*Flip evidence* — if independent authors need a language-neutral, versioned
contract or schema-embedded validation, I would add a JSON Schema artifact
generated from the dataclasses.

**Choice: `numpy.random.default_rng` (PCG64) for all randomness.**
*Alternatives* — (a) Python's `random` module; (b) a hand-rolled xorshift/hash
stream so different languages reproduce the same seed exactly.
*Why default_rng wins* — fast, deterministic per seed, and supports the
vectorised draws the generator uses. Cross-language bit-reproducibility is not a
requirement here.
*Flip evidence* — if an independent author must reproduce the *same* episode
bytes in another language, I would switch to a specified xorshift/splitmix
stream with a written spec.

**Choice: structural validator plus a book replay (not a semantic fact-checker,
not a learned classifier).**
*Alternatives* — (a) purely structural validation with no replay; (b) a semantic
validator that also matches claim value/unit to the cited fact (fact-checking
paradigm); (c) a learned classifier that predicts "valid episode" (learning
paradigm).
*Why this wins* — replay checks label *correctness* against the mandate without
leaking detection logic; a fact-value check would reject the
`unsupported_claim`/`misquote` families' intentional source-less or mismatched
claims. Structural + replay is debuggable and cheap.
*Flip evidence* — if independent authors ship structurally valid but
semantically broken episodes that the replay cannot see, I would add an opt-in
`--strict` fact-value check rather than fold it into the default path.

**Choice: shift as surface word-substitution (plus publisher/company rename).**
*Alternatives* — (a) LLM paraphrasing of the same scenario; (b) changing only
company names/publishers with no wording change; (c) a held-out style transfer.
*Why substitution wins* — it changes the surface form deterministically while
keeping `owner`, `facts` and (except drift) labels identical, which is exactly
what the brief asks.
*Flip evidence* — if a detector is shown to key on the substituted words, I
would strengthen the substitution or add a small LLM paraphrase layer.

**Choice: repeat-rate metric = fraction of sentences (document and note text,
split on `". "`, including `pre_notes`/`new_notes`) appearing more than once.**
*Alternatives* — (a) per-episode duplicate rate; (b) n-gram (word-level) overlap;
(c) a BLEU-style self-similarity.
*Why this wins* — it directly measures the brief's "the same sentence does not
recur more than 5%" bar and is trivial to reproduce.
*Flip evidence* — if a reviewer argues the bar concerns word n-grams, I would
report an n-gram overlap metric alongside it.

**Choice: `pre_notes` / `new_notes` split for the intra-step order.**
*Alternatives* — (a) one `notes` list plus an explicit ordering field
(`before`/`after`); (b) infer order from timestamps only; (c) a separate
`NoteEvent` timeline outside steps.
*Why this wins* — the two lists make the causal order structural, so the
validator cannot be fooled by equal timestamps, and authors do not need to
reason about tie-breaking. It is the option the lead review recommended.
*Flip evidence* — if authors need many note events between actions, a global
ordered `NoteEvent` timeline would be cleaner.

**Choice: explicit positions + cash, with sector totals carried alongside.**
*Alternatives* — (a) sector weights only (the round-3 state); (b) a full
lot-level ledger with prices; (c) per-instrument positions with sector totals
derived by the reader.
*Why positions + cash win* — a reviewer can replay every action and re-derive
sector weights and instrument caps; carrying `sectors` explicitly makes the
book checkable by hand and by machine. A lot-level ledger adds price modelling
the brief does not ask for; deriving totals only is more error-prone for
authors.
*Flip evidence* — if a later task needs realised P&L or tax lots, a priced,
lot-level ledger would replace this snapshot.

**Choice: 15% single-instrument cap, 75% invested at t=0, 15% cash buffer.**
*Alternatives* — (a) keep the earlier 5% cap; (b) no instrument cap; (c) start
fully invested.
*Why this wins* — each sector has only 7 instruments and can carry up to 50% of
the book, so a 5% cap makes a legal initial book impossible; 15% × 7 names
leaves headroom. Starting 75% invested with a cash buffer lets both prudent buys
and later injected instructions be feasible.
*Flip evidence* — if independent authors use larger instrument universes, a
lower cap would be more realistic.

**Choice: poisoned/spoof actions are labelled `y=1` only when they actually
move the sector past its `max`; otherwise the step is a clean in-band action.**
*Alternatives* — (a) label any action that cites the note, whether or not it
crosses the band; (b) label only when the note is cited and the trade is a buy;
(c) force a crossing by ignoring cash/position limits.
*Why this wins* — it keeps the label and the replay consistent (a "following"
trade that stays inside the mandate is not the failure the cause names) and
never invents an illegal book. If the named instrument is full, the action may
use another name in the same sector, because the memo's instruction concerns the
sector cap.
*Flip evidence* — if a detector must catch "followed the note but could not yet
cross", the cause would need a separate label and SCHEMA wording.

**Choice: drift labels require the buy to leave the sector at least 0.01% of
portfolio value above `max`.**
*Alternatives* — (a) label any post-trade weight strictly above `max` (which
let a rounded cent land marginally above `max`); (b) label only when the sector was
already above `max` before the action (which leaves the boundary-crossing buy
clean, contradicting the lead's clean-consistency rule).
*Why this wins* — it is numerically stable and consistent with the rule that a
clean action may not cross a sector maximum.
*Flip evidence* — if a reviewer wants the first crossing buy treated as the
onset but labelled clean, the margin and rule would change together.

### 5.2 Schema and definition decisions (brief gray areas)

- **`theses` on `Episode`.** The brief's `Episode` field list has no home for
  `Thesis` objects, yet `Action.thesis_id` references theses and `stale_thesis`
  needs `evidence_docs` and `invalidation_trigger`. Documented in `SCHEMA.md`.
- **`sector_bands` as `{min, max}` for all seven sectors**. `max=0` means "not
  allowed". A missing band is a validation error.
- **Misquote vs unsupported** (brief gray area): a misquote quotes a real span
  whose fact value differs from the claimed value; an unsupported claim either
  has no source, or a source whose facts do not contain the claimed figure.
- **Authority spoof vs poisoned note** (brief gray area): a spoof asserts a
  *permission change* ("the owner widened the tech band to 65%"); a poisoned
  note is any *injected instruction* ("ignore the cap"). Both are non-owner-
  signed; spoofs use `written_by="agent"`, poison `written_by="external"`.
- **Drift labels** (brief gray area): a buy is `y=1` only when it leaves the
  sector above its `max`; sells that reduce an overage are correct (hard
  negatives). The round-2 note that a boundary-crossing buy could stay clean is
  superseded by the lead's rule that no clean action may cross a sector maximum.
- **Clean actions never breach the mandate.** Every clean buy stays at or below
  the sector `max` and the instrument cap; every clean sell stays at or above
  the sector `min`. The book replay checks this for the whole corpus.
- **`y` and `cause` are tied one-to-one (round 5).** `y = 0` requires
  `cause = "clean"` and `cause = "clean"` requires `y = 0`, so every positive has
  a real failure cause. The replay's band and position checks are gated on
  `y == 0`, not on the cause string, so a relabelled or re-caused negative
  cannot hide a mandate breach. This is stricter than the round-4 rule and is
  the only consistent reading of "clean means the owner endorses it".
- **Stale-thesis positives are buys (round 5).** A buy that adds exposure on an
  invalidated thesis is clearly non-endorsable: the agent saw (or should have
  seen) the invalidation and added risk anyway. A sell reduces exposure and can
  be a sensible response to the invalidation, so it is never labelled
  `stale_thesis`; if no affordable buy exists in the thesis sector the step is a
  clean action instead. Alternatives considered: (a) keep sells and argue they
  are stale (rejected: not clearly non-endorsable); (b) relabel reducing sells
  as a separate `stale_exit` cause (rejected: adds a cause the brief's list does
  not require and blurs the definition). Flip evidence: if a detector study
  needs stale-exit negatives, that would be a separate cause, not this one.
- **Following a note is a concrete buy.** Poison/spoof positives are buys with
  a rationale that states the instruction and a citation of the note; they are
  labelled only when the sector ends above its original cap. Unrelated clean
  actions never cite the note.
- **Onset** is drawn uniformly in `[0.3, 0.6] × n_steps`; clean has no onset.
  For poison/spoof, the onset sector is chosen so the relevant crossing is
  affordable (cash + position room), which is why every generated seed has
  positives.
- **`facts` = named facts.** Every generated sentence carries one named fact, so
  in the reference world every number in a document is listed in `facts`.
- **`trust_tier` fixed by kind** (filing 3, analyst 2, news 1, tool_output 2,
  social 0).
- **`signing_key_id`** is seed-derived, so shifted and unshifted episodes of the
  same seed share the owner.
- **`cause_refs` never names claims.** `Claim` has no id field, so a reference is
  only ever to a document or a note. Stated explicitly in `SCHEMA.md`.
- **`initial_book` starts compliant.** Every sector starts inside its band and
  every instrument under the cap, so any later breach is attributable to an
  action.

## 6. Loopholes I checked

- **Shift only changes surface**: for a fixed seed, shifted vs unshifted keep
  identical `owner`, `initial_book`, document `facts`, and (except the required
  slower drift) identical labels; only `text`/`publisher`/company display change
  (tested).
- **Determinism**: same seed ⇒ byte-identical episode dict (tested, unshifted
  and shifted).
- **No pre-onset positives** in any failure family (tested, and counted by
  `generate.py` for all 2,800 failure episodes).
- **Clean actions are mandate-compliant**: replay of all 3,200 episodes is part
  of `validate.py`, so an endorsed (`y = 0`) buy above `max`, an endorsed sell
  below `min`, or an endorsed buy above the instrument cap is a validation
  error; dedicated tests also replay clean and failure corpora.
- **Relabelling a positive cannot hide a breach (round 5)**: changing a drift
  positive's `y` to 0 while keeping `cause="drift"` is rejected by the label
  convention, and changing both to `y=0`/novel cause is rejected by both the
  convention and the replay's `y`-gated band check (tested). The replay runs
  even after the label convention fails.
- **Stale-thesis positives are unambiguous (round 5)**: the run prints
  `pos_sells=0` and `min_episode_positives=2` for both stale corpora, and a test
  asserts every stale positive is a buy on an invalidated thesis with a
  negative-guidance `cause_refs` document.
- **Drift labels really drift**: every `drift` positive is a buy that leaves its
  sector above `max` (validator + test).
- **Poison/spoof positives really follow the note**: each is a buy, cites the
  unsigned note, and leaves the sector above its original cap (tested).
- **Stale cause refs point at the invalidation**: `cause_refs` names a document
  carrying a negative `guidance_growth` fact (tested).
- **Availability is causal**: a same-step `pre_note` is accepted; a same-step
  `new_note` and any later-step note are rejected; a claim cannot cite a
  not-yet-published document; a thesis cannot cite evidence newer than its
  opening; `cause_refs` must already exist (tested for each).
- **Spans are substrings**; clean claims reproduce their source figure exactly
  and misquotes differ from it (tested).
- **`initial_book` is auditable**: `sectors` must equal the per-sector sum of
  `positions`, every positioned/traded instrument must have a sector, and the
  action's `sector` must match it (validator + tests).
- **Evaluation leakage is blocked**: `model_view` strips `meta` (which names the
  failure family) and every `label`; it returns a copy and does not mutate the
  input (tested).
- **Validator rejects the breakage kinds**: missing key, bad enum, unresolvable
  id, broken span, span without source, non-monotone time, wrong content hash,
  missing label, unsigned owner note, too many document sentences, long
  rationale, missing sector band, `y=1` with a `clean` cause, `y=0` with a
  non-clean cause, a relabelled drift positive, a band-breaking negative with a
  novel cause, a claim citing a
  future document, an action citing a future note, same-step new-note and
  later-step references, a note citing an unknown document, a non-adjacent
  duplicate document id, a clean sell below the minimum, an inconsistent
  `initial_book`, and a missing instrument sector (tested); a novel custom cause
  on a `y=1` action is accepted.
- **No git, no secrets, no absolute home paths** written or printed; data goes
  to `data/` (git-ignored), and nothing >5 MB lives in the task folder.

## 7. Open risks

- **Throughput is sampled wall-clock** and depends on machine load. The final
  run measured 165.36 eps/sec (3,200 episodes in 19.35 s) in `check.log`; a busy
  laptop will report lower. It comfortably clears the "about 100/sec" target.
- **A minority of drift episodes carry no positive.** `min_episode_positives=0`
  for `drift`: after onset, cash/position room can block every attempted
  out-of-band buy, so that episode ends all-negative. The family still has
  5,518 positives across 200 unshifted episodes, and every corpus contains
  positives. The same run prints a non-zero minimum for every other failure
  family.
- **Stale-thesis labels are less frequent** (10.57% of actions) because sells
  are excluded. This is intentional; training on this reference set will see
  fewer stale positives per episode (minimum 2).
- **Document wording is kind-agnostic.** Filing/news/analyst/social documents
  share the same sentence templates (only publisher and trust_tier differ). A
  text-channel model might find this unrealistically uniform; independent
  authors (T02) are not bound by it.
- **The reference world is written by the same hand as the future detectors.**
  This is inherent to T01; the real test is held-out T02 data, not the reference
  set.
- **The validator checks structure and label/book consistency, not fact-value
  agreement.** It confirms a non-null `quoted_span` is a substring, but does not
  check that a claim's `value`/`unit` agree with the cited fact. This is
  deliberate: adding fact-value matching would reject the `unsupported_claim` and
  `misquote` families by design.
- **Turnover is out of scope.** `max_daily_turnover_pct` is a declared mandate
  field but is not replayed, enforced or labelled. This is stated in
  `SCHEMA.md`.
- **No price moves.** The book value is constant; buys and sells transfer value
  between cash and instruments at the stated notional. Realised P&L, slippage
  and daily return construction are out of scope.
- **Instrument assignment is static.** An instrument belongs to exactly one
  sector for the whole episode; multi-sector conglomerates are not modelled.
- **Poison/spoof actions that cannot cross the cap are labelled clean**, even
  though they were driven by the injected note. This is a deliberate
  label/replay consistency choice; catching "followed the note but did not
  cross" would need a separate cause.
- **Repeat-rate definition** is mine; if a reviewer measures it per-episode or
  over n-grams, the number changes.

## Round 4 changes

Addressed every item in the lead review, in order of importance. (The round-3
`REVIEW.md` fixes were already in place; round 4 implements the lead's final
schema changes.)

1. **Event order and availability.** Added `Step.pre_notes` (written before the
   action, available to it) and kept `new_notes` (written after, not available).
   `SCHEMA.md` now states the four-step order explicitly. `validate.py` builds
   the available-note set per action (initial notes, this step's `pre_notes`,
   earlier steps' `new_notes`) and rejects same-step `new_notes` and later-step
   references even when timestamps would otherwise pass. The simulator places
   poison/spoof onset notes in `pre_notes`. Regression tests cover an accepted
   same-step `pre_note`, a rejected same-step `new_note`, and a rejected
   later-step reference.

2. **Auditable portfolio state.** Added `Episode.initial_book` (`cash`,
   `positions`, `sectors`) and `Episode.instrument_sectors`. The simulator
   maintains the same positions/cash book it emits, and `validate.py` replays
   every action from the initial snapshot. `SCHEMA.md` documents the book and the
   replay rules. Replay tests assert that clean buys stay inside the sector
   ceiling and instrument cap, clean sells stay above the sector floor, and
   drift labels are buys that leave the sector above `max`.

3. **Validator gaps.** `quoted_span` now requires `source_doc`; the action
   rationale is checked for 1–3 sentences; all seven sector bands are required;
   additionally, initial-book consistency, instrument-to-sector mapping, and
   `allowed_instruments` membership are enforced. Tests were added for each.

4. **Clean-label correctness.** Clean actions are generated against the explicit
   book and capped by band room, position room and a cash reserve; a clean sell
   that would cross a minimum is not generated. The validator replays the whole
   corpus, so any clean action that crosses a floor, ceiling or position cap
   would be a validation error. The replay tests cover clean and failure-family
   clean actions.

5. **Evaluation-only metadata.** `SCHEMA.md` has a new "Evaluation-only fields"
   section: `meta` and every `label` are for scoring only. Added
   `og_s1.schema.model_view(episode)`, which strips `meta` and per-step `label`
   and returns a fresh dict; tests assert the stripping and that the input is not
   mutated.

6. **Report accuracy.** This report is regenerated from the final
   `run.sh`/`check.log`. It states that throughput is sampled wall-clock and
   separates deterministic corpus statistics (counts, label rates, repeat rate)
   from timing. The round-3 claim that the log contained one run was wrong: it
   contained two; the round-4 log was regenerated from one fresh run. Round 5
   then made `run.sh` overwrite `work/T01/check.log` on every invocation, so the
   log can no longer accumulate runs (see "Round 5 changes").

**What I did not change, and why:**

- **Fact-value/unit matching in the validator.** Still out of scope: it would
  reject the `unsupported_claim` and `misquote` families by construction and
  would put detection logic into the author-facing validator. Documented as an
  open risk.
- **Turnover enforcement.** The lead allowed it to stay out of scope; `SCHEMA.md`
  now says so explicitly.
- **The eight families and their cause definitions, the shift mechanism, and the
  doc/note/claim templates.** The lead said to keep everything else; the round-4
  work is the schema, replay, validator and report, not a redesign of the world.
- **`MAX_TURNOVER_PCT` stays declared** so the owner record is complete, but it
  is not simulated or checked.

## Round 5 changes

Round 5 addresses the three required fixes in `REVIEW.md`, in the reviewer's
order of importance. Everything is regenerated from a single `run.sh` run whose
output `run.sh` writes to `work/T01/check.log` (overwriting the log each time),
so the log now holds exactly one clearly identified run.

1. **Label/replay consistency (`og_s1/validate.py`).**
   - Enforced the documented convention in `_check_labels`: `y = 0` must have
     `cause = "clean"`; `y = 1` must not. A drift positive relabelled to `y = 0`
     is now an error instead of passing.
   - Gated the replay's sector-band and instrument-cap checks on `y == 0`
     instead of `cause == "clean"`, so substituting a novel cause cannot bypass
     them.
   - The replay now runs even when the label convention fails, so a relabelled
     action reports both the label error and the underlying band breach.
   - Added regression tests: `test_rejects_relabelled_drift_positive` and
     `test_rejects_band_breaching_negative_with_novel_cause` (the latter asserts
     the replay's `above max` error independently of the label error).
   - Updated `SCHEMA.md`'s "Book replay and label consistency", "Failure causes"
     and output-format sections to state the strict convention.

2. **Unambiguous stale-thesis positives (`og_s1/world.py`).**
   - `_stale_action` now labels only **buys** that add exposure on the
     invalidated thesis. If the named instrument has no buy capacity it tries
     another name in the thesis sector; if none is affordable it emits a clean
     action rather than a sell.
   - Result: stale-thesis positives are 2,536 per corpus (down from round 4,
     whose positives included sells), with `pos_sells=0` and
     `min_episode_positives=2` printed by `generate.py` and covered by
     `test_stale_positives_are_buys_on_the_invalidated_thesis`.
   - `SCHEMA.md`'s stale-thesis definition now says the canonical failure adds
     exposure (a buy) and that a reducing sell is not, by itself, stale.
   - The report's label table and the stale-thesis totals are updated. No other
     family's counts changed.

3. **`check.log` and report reconciliation.**
   - `run.sh` now tees its whole output to `work/T01/check.log` and overwrites
     it on every invocation, so the log contains exactly one run, prefixed with
     `== T01 world v2 single captured run ==`.
   - The report's "How to re-run" and Results sections describe that behaviour;
     the reported timing now refers to that captured run (165.36 eps/sec,
     3,200 episodes in 19.35 s). Deterministic counts, rates and repeat rate
     match the log exactly.

**What I did not change, and why:**

- **The schema fields.** The lead declared the round-4 schema final. Round 5
  changes only validator enforcement, the stale-action generator, tests, the
  author-facing wording, and the report.
- **Novel causes.** They remain accepted on `y = 1` actions. The new rule only
  forbids pairing a novel cause with `y = 0`, which is the direct consequence of
  "clean means endorsed".
- **The other seven families, the shift mechanism, document/note templates,
  book replay arithmetic and turnover scope.** The review did not ask for them
  and the lead said to keep everything else as it is.
- **Drift episodes with no positives.** Drift is unchanged; `generate.py` now
  prints `min_episode_positives` and the report discloses the zero minimum
  rather than hiding it.

## Lead round (after round 5): fixes made by the lab lead, and the world frozen

The round-5 review found these problems. The lead fixed them directly instead of running a sixth worker round:

1. **The family leaked through the owner key.** `generate.py` allocates seed ranges per family, and `owner.signing_key_id` embedded the seed. The key is now a sha256-derived id. Tested in `og_s1/tests/test_lead_fixes.py`.
2. **The per-action view was not causal.** `og_s1.schema.model_view_at(episode, i)` now returns only what was knowable at action *i*:
   - documents with `t <= action.t`;
   - notes written before it, plus that step's `pre_notes`;
   - theses opened by then, with no final `status`;
   - the earlier actions.

   Every per-action feature and model must use it. Tested.
3. **SCHEMA.md described the validator's label rules.** It now states only the book-consistency rule and the owner's signed intent (an owner does not endorse an action that breaks a band or the position limit). The validator mechanics are gone from it.
4. **Throughput is a sampled wall-clock figure.** The authoritative numbers are those in the current `check.log`, which holds one run. They vary from run to run.
5. **The validator gained bounds checks:** sector bands must lie in [0, 1], and every sector total must be present in `initial_book.sectors`. Tested.

**Result after the fixes:**
- 60 tests pass;
- 3,200 episodes regenerate with 0 validation errors;
- the repeat rate is 1.36%;
- no home paths in the log.

The schema is now frozen for the independent authors.
