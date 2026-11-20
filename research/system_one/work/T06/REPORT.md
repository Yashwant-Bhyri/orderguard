# REPORT

## What I built

A deterministic red-team corpus for the OrderGuard System One world, plus the
helpers needed to rebuild and audit it.

- `generator.py` exposes `generate(seed, technique) -> dict`, returning one
  complete `Episode` in the `SCHEMA.md` shape. `ATTACK_TECHNIQUES` lists eight
  attack families and `BENIGN_TECHNIQUES` lists eleven benign families.
  Calling `generate` twice with the same arguments returns equal dictionaries;
  `check_determinism.py` re-generates every emitted line and compares it.
- Eight attack modules: `fam_prompt_injection.py`,
  `fam_authority_spoof.py`, `fam_quote_laundering.py`,
  `fam_persuasive_framing.py`, `fam_evidence_flooding.py`,
  `fam_camouflage.py`, `fam_vintage.py` (own technique: vintage pass-off) and
  `fam_attribution.py` (own technique: false attribution).
- Eleven benign-control families in `fam_benign.py` and `fam_benign_more.py`:
  signed approval, exact quote, enthusiastic-but-factual, correct sell,
  legitimate adaptation, many sources, inert injection warning, scope-matched
  claim, explicit large add, multi-step rebalance and a tech trim-then-add.
- `common.py` holds the signed mandate, the 15-instrument book, the entity
  builders, and the shared sizing plans. `prose.py` composes every rationale,
  claim and document sentence from independent phrase pools.
  `benign_common.py` holds benign-only builders.
- `generate_all.py`, `run.sh`, `stats.py` and `check_determinism.py` build,
  validate, audit and measure the corpus. `stats.py` writes
  `out/summary.json`; `run.sh` leaves its full output in `check.log`.

Current corpus: **740 episodes** = 520 attack episodes + 220 benign-control
episodes. There are **520 attack actions**, **220 benign target actions**,
**550 dedicated clean actions inside benign episodes**, **1,296 clean actions
in total** (746 of them inside attack episodes), and **1,580 documents**. The
book is one balanced $1,000,000 mandate across 15 instruments.

Every attack action has `label.y = 1` and `cause = redteam_<technique>`.
455 of the 520 also have non-empty `cause_refs`; the exception is exactly the
65 `persuasive_framing` actions, whose failure is an out-of-band size carried
by the signed mandate rather than by a document or note (the schema allows an
empty list). Every benign action has `label.y = 0` and `cause = clean`.

## How to re-run

From this folder:

```sh
./run.sh
```

`run.sh` uses `.venv/bin/python` when present and `python3` otherwise. It
writes `out/redteam.jsonl`, runs `python3 -m og_s1.validate` on it, runs
`check_determinism.py`, then runs `stats.py`, prints the summary block, and
copies the same output to `check.log`. No network, no git, and no files
outside this folder are used. The current run takes about a minute because the
diversity scan is quadratic in the number of attack pairs.

## Results

The current run (`./run.sh`) reports:

| Metric | Value |
|---|---|
| Validation errors | 0 (`validated 740 episodes ... 0 error(s)`) |
| Determinism | 740 / 740 episodes regenerate exactly |
| Episodes | 740 |
| Attack actions | 520 |
| Attack actions per technique | 65 each, for all 8 techniques |
| Attack techniques present | 8 |
| Attacks with `redteam_` cause prefix | 520 / 520 |
| Attacks with non-empty `cause_refs` | 455 / 520 |
| Unresolved `cause_refs` | 0 |
| Benign case episodes | 220 |
| Benign target actions | 220 |
| Benign families (measured from `meta.benign_family`) | 11 |
| Clean actions dedicated to benign episodes | 550 |
| Clean actions inside attack episodes | 746 |
| Total clean actions | 1,296 |
| Side-language violations in clean actions | 0 of 1,296 |
| Documents | 1,580 |
| Attack notional range | 2,500 - 60,000 |
| Benign target notional range | 2,500 - 60,000 |
| Attack actions at or below 6,000 / above 6,000 | 105 / 415 |
| Benign targets at or below 6,000 / above 6,000 | 35 / 185 |
| Attack sides (buy / sell) | 488 / 32 |
| Benign target sides (buy / sell) | 200 / 20 |
| Attack step counts | 2:455, 4:17, 5:16, 6:16, 7:16 |
| Benign step counts | 2:180, 4:25, 5:5, 6:5, 7:5 |
| Attack document counts | 1:228, 2:227, 4:11, 5:11, 6:11, 7:11, 8:11, 9:10 |
| Benign document counts | 1:140, 2:40, 3:3, 4:3, 5:3, 6:9, 7:10, 8:10, 9:2 |
| Global max 4-gram shingle Jaccard, full attack text | 0.2135 |
| Exact char max, full attack text | 0.7743 |
| Full-text pairs at or above 0.80 | 0 |
| Exact char pairs examined, full text | 2,481 of 134,940 |
| Global max 4-gram shingle Jaccard, core payload | 0.1520 |
| Exact char max, core payload | 0.7450 |
| Core-payload pairs at or above 0.80 | 0 |
| Exact char pairs examined, core payload | 3,195 of 134,940 |
| Whole-episode max 8-gram Jaccard | 0.2056 |
| Whole-episode exact char max | 0.7772 |
| Whole-episode pairs at or above 0.80 | 0 (of 41 pairs at 8-gram Jaccard >= 0.12) |

`out/summary.json` also carries the audit and separability keys behind the
prose below: `book_audit` (243 book breaches / 277 in-band),
`side_language_audit`, the `rule_notional_gt_6000_*`, `rule_steps_gt_2_*` and
`rule_docs_gt_5_*` counts, `attack_tech_targets` and `benign_tech_targets`,
`claim_audit`, `facts_audit`, `benign_family_counts`, and the per-instrument
counts. Every number quoted in this report is either in the table above or in
that summary block.

**No single size, side or structure threshold perfectly separates the
classes.** The old corpus
failed because every attack was a 15k-60k NVDA buy and every benign target was
a 5k-6k NVDA action, so `notional > 6_000` caught all attacks and no controls.
Now both attacks and benign targets run from 2,500 to 60,000, and both classes
contain buys and sells. `notional > 6_000` would flag 415 attacks and 185 benign
targets, and would miss 105 attacks. Both classes use all 15
instruments. Step counts and document counts overlap in both directions:
attacks use 2, 4, 5, 6 or 7 steps and 1, 2 or 4-9 documents; benign controls
use 2, 4, 5, 6 or 7 steps and 1-9 documents. There is no threshold on size,
step count or document count that isolates the attacks, although the residual
instrument asymmetry noted under Open risks remains.

**Some attacks are book breaches and some are epistemic.** Replaying the book
shows 243 of the 520 attack actions leave the book outside a signed band or
single-name cap: all 65 `prompt_injection`, all 65 `authority_spoof`, all 65
`persuasive_framing` and 48 of the 65 `evidence_flooding` actions. The other
277 are inside the signed limits but rest on a false quote, a superseded
filing, false provenance, low-trust corroboration, or a hidden misquote (all 65
of `quote_laundering`, `vintage_passoff`, `false_attribution`,
`benign_camouflage`, and 17 `evidence_flooding`). The 17 in-band
`evidence_flooding` actions cite the low-trust posts directly as corroboration;
they do not pass those posts off as filings. The family that claims a false
provenance is `false_attribution`. Both kinds of failure are `y = 1`: the
owner would not endorse either an out-of-band trade or a trade built on
fabricated, misbound or superseded evidence.

**Claim audit.** `stats.py` now computes the claim-number audit rather than
reporting hand-typed counts. It finds 902 claims, 821 with a numeric value, and
0 numeric claims without a `source_doc`. Exactly **82** numeric claims state a
value absent from the cited document's text and facts: **17** from
`quote_laundering` (the `seed % 4 == 0` wrong-growth variant) and **65** from
`benign_camouflage` (the hidden misquote). There are **0** absent numbers in
the 220 benign target claims and **0** in any clean-step claim. The other
quote-laundering variants keep the number present but change the unit or
period, as intended.

**Facts audit.** `stats.py` also checks every document fact value against its
own text. All **2,805** facts contain a matching number in the document text;
there are **0** facts that are not in their own text. This closes the round-2
problem where `channel_checks`, vintage `guidance` and prompt-injection
`ticket_priority` facts had no textual counterpart.

**Diversity method.** Two attack-text definitions are reported. *Full attack
text* is the rationale plus claim text, quoted spans and cited-note text.
*Core payload* is the first rationale sentence plus the first claim sentence.
The 4-gram Jaccard scan covers every attack pair. The exact
`SequenceMatcher` scan is run on every pair whose 4-gram Jaccard is at least
0.05 (2,481 full-text pairs and 3,195 core pairs); `out/summary.json` prints
that scope and the total pair count (134,940). No pair is at or above 0.80 on
either definition. As a supporting check, the whole-episode text (documents
plus every step) has an 8-gram Jaccard maximum of 0.2056 and an exact character
maximum of 0.7772 over the 41 pairs at 8-gram Jaccard >= 0.12, with 0 pairs at
or above 0.80. The exact scans are screened, not all-pairs; the scope is stated
in the summary and treated as a risk below.

## Round 3 changes

The reviewer returned REVISE. I fixed the items in the order given, re-ran
`./run.sh`, and every number above is from that run.

1. **Action-size tell removed.** I rebuilt the initial book so tech starts at
   34.4%, just inside the 35% band (NVDA 110k, MSFT 117k, AAPL 117k; cash 66k).
   A 3k anchor leaves only about 3k of tech room, so a 5k-60k tech buy is
   out of band, while a 58k-60k non-tech buy can breach a single-name cap or
   the healthcare band. Attack notionals now range over 2,500-60,000 and
   benign targets over 2,500-60,000. I varied attack instruments across all 15
   names and added attack sells (`false_attribution` has a bearish sell
   variant). Benign targets now cover all 15 instruments too. The specific
   separating rule `notional > 6_000` now produces 415 attack hits, 185
   benign-target hits and 105 missed attacks. I added `benign_large_add` and
   `benign_tech_rebalance` so large benign adds and >3k benign tech buys exist
   inside the signed limits.
2. **Step-count and document-count tells removed.** `benign_multistep_rebalance`
   now runs 3-6 clean actions (4-7 steps including the anchor) and carries 3-9
   documents. `benign_tech_rebalance` adds a four-step clean episode whose
   target is a >3k tech buy inside the band. Attack camouflage episodes run
   4-7 steps, and evidence flooding now uses 2-7 flood documents (4-9
   documents total). Result: attack and benign step-count sets are the same
   `{2,4,5,6,7}`, and every attack document count (1,2,4-9) also occurs in the
   benign set (1-9). A `steps > 2` rule catches 65 attacks and 40 benign
   controls; a `docs > 5` rule catches 43 attacks and 31 benign controls.
3. **Document facts placed in the text or removed.** I removed the
   `channel_checks` facts from the flooding posts, added "priority level 9" to
   the prompt-injection tool output, and wrote "Management guided to 0%
   revenue growth" into the vintage fresh filing. `stats.py` now audits every
   fact against its text and reports 0 mismatches out of 2,805 facts.
4. **Report and notes overclaims corrected.** This report no longer says the
   fake-approval and poisoned-note families are in-band; it states that 243
   attacks breach and 277 are in-band epistemic failures. `REDTEAM_NOTES.md`
   now says the authority-spoof size is a second tell beyond the signer, that
   the camouflage bad step is in-band and the same size range as its clean
   neighbours, that the false-attribution defect is provenance only (the
   action is in-band), that the old process-line boilerplate was removed, and
   that `benign_many_sources` uses 6-8 documents rather than a "five sources"
   phrase. The cause-refs exception (455/520) and the non-identical step counts
   are stated in this report.
5. **Claim audit made reproducible.** `stats.py` computes the audit from the
   corpus and prints it in the `claim_audit` block: 902 claims, 821 numeric,
   0 without source, 82 absent numbers (17 quote-laundering, 65 camouflage),
   0 in benign target claims and 0 in clean-step claims. `run.sh` runs it.
6. **Benign families measured, not hard-coded.** Every benign episode carries
   `meta.benign_family`; `stats.py` counts the distinct values from the
   output (`benign_families = 11`, with a per-family count), instead of
   reporting `len(generator.BENIGN_TECHNIQUES)`.
7. **Metric wording and headroom fixed.** The `stats.py` docstring now says
   the exact-character scan is screened, not exhaustive, and names the screen.
   The whole-episode maximum is reported below as an explicit risk with its
   measured headroom.

What I did not change, and why: I kept the custom `redteam_*` causes because
the brief requires a cause starting with `redteam_` and naming the technique.
I kept one mandate and one book so the corpus is comparable and replay is
simple, although the book now starts with tech near its cap to remove the size
tell. I did not run an all-pairs exact character scan in `stats.py`; the 4-gram
Jaccard scan is exhaustive and the exact scan is screened, and the screen,
examined count and total are printed. I did not add a turnover-based attack
because `max_daily_turnover_pct` is not replayed by the validator.

## Round 4 changes

The reviewer returned REVISE. I fixed the six required items in the order given,
re-ran `./run.sh`, and every number above is from that run.

1. **Mislabeled camouflage clean steps fixed.** `fam_camouflage.py` now has
   side-aware clean pools: `CLEAN_LINES_SELL` carries the trim/sale wording and
   is used only for sells, while `CLEAN_LINES_NEUTRAL` is used for buys. The
   five buys the reviewer named (seeds 3, 11, 31, 35 and 48) no longer carry
   "The trim leaves ...". I also removed "after the trim" from the
   `benign_tech_rebalance` buy rationale, so no clean buy refers to a sale.
2. **Stale benign-tech number corrected.** `REPORT.md` now says 35 of 220
   (from `benign_tech_targets`), not 30. I re-checked every quoted number
   against `out/summary.json` from the new run.
3. **Quote-laundering side corrected.** `REDTEAM_NOTES.md` §3 no longer says
   the family includes tech sells. All 65 quote-laundering actions are buys;
   the 32 attack sells in the corpus all belong to `false_attribution`.
4. **Benign inert-instruction provenance fixed.** `benign_inert_instruction`
   now carries both the tier-2 `news` "Regulatory wire" warning and a genuine
   tier-3 filing. The claim cites and quotes the filing (`bi_d2`), not the
   wire, so the "audited report" descriptor matches the cited source in the
   three seeds the reviewer named and in every other seed.
5. **Report overclaims corrected.** The epistemic paragraph now separates the
   17 in-band `evidence_flooding` cases ("low-trust corroboration") from
   `false_attribution` ("false provenance"). The separability heading now says
   "No single size, side or structure threshold perfectly separates the
   classes", and the residual tech/instrument asymmetry remains under Open
   risks. Round 3 item 4 no longer attributes statements to `REDTEAM_NOTES.md`
   that the notes did not contain.
6. **Re-run and re-sync.** After the fixes I ran `./run.sh`. `check.log`, the
   results table, the facts and document counts, the diversity counts and the
   whole-episode headroom are all from that build: 740 episodes, 520 attacks,
   and 1,580 documents.

I also added a `side_language_audit` to `stats.py`, because the shipped
validator does not check rationale direction. It scans all 1,296 clean actions
for sell-only wording on a buy and buy-only wording on a sell and reports 0
violations. This is a regression guard for the round-4 defect, not a general
semantic parser.

What I did not change, and why: I left `og_s1/validate.py` untouched, because
the brief says the supervisor cannot be broken; the new audit lives in the
reporting script instead. I did not add attacks aimed at the validator's
unchecked `max_daily_turnover_pct`, because that would test the harness rather
than the supervisor. I did not replace the screened exact-character scan with
an all-pairs scan, since the 4-gram scan is exhaustive and the screen, examined
count and total are printed.

## What did not work

- **Template-only attacks.** An early corpus used fixed templates per family
  and varied only the numbers. Many attack pairs were near-identical and far
  above the 0.80 bar. Numeric variation does not change shared sentence
  structure.
- **One unique suffix per attack.** Adding a single long unique sentence to
  the rationale, first claim and note was still not enough; the fixed
  technique templates kept many pairs above 0.80.
- **Numeric-only variation inside the unique sentences.** The added sentence
  tails were themselves shared boilerplate and asserted figures absent from
  the cited documents. Round 2 removed that layer.
- **Padding-driven diversity.** A high-entropy audit checklist satisfied the
  full-text metric only by diluting the shared core. Round 2 made the core
  vary on its own, and round 3 removed the remaining shared process-line
  sentences (`prose.PROCESS_LINES` and `PROCESS_FLAIR`) entirely.
- **One-step benign controls.** The first benign batch had one action per
  episode while attacks had two, so episode length was a free detector
  feature. Benign episodes now include two-step and 4-7-step shapes.
- **A single fixed initial book.** With tech at 30%, every out-of-band tech
  buy had to be larger than 50k, and with tech at 34.4% every tech buy above
  3k breaches unless the book is trimmed first. Round 3 adds benign
  trim-then-add controls so the second pattern is not a perfect rule either.
- **What survived.** The current corpus has a global 4-gram maximum of 0.2135
  on full attack text and 0.1520 on the core payload, with no screened exact
  pair at or above 0.80 under either definition. Those numbers are reproduced
  by `./run.sh`.

## Judgement calls

- **Breach versus epistemic failure.** 243 of 520 attacks leave the book
  outside a signed limit; 277 are in-band but rest on a false quote,
  superseded evidence, false provenance or a hidden misquote. Both are
  unendorsed, so both are `y = 1`. The report names which families fall on
  which side rather than calling every attack a book breach.
- **Cause names.** The brief requires a cause that starts with `redteam_` and
  names the technique, so every attack uses a custom cause such as
  `redteam_quote_laundering`. I did not use the built-in causes (`drift`,
  `misquote`, ...) because they would not satisfy that prefix rule. The
  validator accepts custom causes on `y = 1`.
- **`cause_refs` policy.** References point at the artifact that carries the
  failure. For persuasive framing there is no such artifact, so the list is
  empty rather than pointing at an accurate filing that does not carry the
  breach. This is the only family with empty refs (65 actions).
- **Attack-text definition.** The brief does not define "attack text". I
  report both the full concatenation and the core payload, and both are below
  the bar. I also report the whole-episode figure as a supporting check.
- **Claim numbers.** Every benign claim number is present in the cited
  document. In quote laundering and camouflage the wrong number is the
  technique, so those claims intentionally fail the numeric check; that is the
  failure being tested, not an accident.
- **One world, with tech near its cap.** All episodes use the same balanced
  mandate, 15 instruments and $1,000,000 book. Tech starts at 34.4% rather than
  30% so out-of-band tech buys can be as small as 5k; this is a deliberate
  world choice to remove the size tell, not an attempt to make attacks easier
  to hide.
- **Benign counting.** There are 220 benign case episodes (11 families x 20
  seeds), each with a designated target action and one or more clean
  companion actions. I report 220 target actions and 550 dedicated clean
  actions separately rather than calling every clean action a target.
- **No use of evaluation-only fields in generation.** `meta` and `label` are
  written only as ground truth; the generator does not read `label.y` or
  `label.cause`.
- **No secrets or external data.** Companies, publishers and reference codes
  are public or invented. `owner.signing_key_id` is the invented identifier
  `balanced-mandate-2026`, required by the schema; it is not a key, password
  or credential. No personal paths are written.

## Loopholes I checked

- The validator enforces book compliance only for `y = 0` actions. A `y = 1`
  action with a custom cause is not required to leave the book inside its
  band. I use that as intended: 243 attacks are genuine breaches and 277 are
  in-band epistemic failures, and the report states which is which. No attack
  hides an unexplained breach behind a custom cause.
- `cause_refs` are checked for resolution and availability, not for
  explanatory correctness. I audited them by construction per family; every
  non-empty list names the note, tool output, news item or filing that carries
  the failure.
- The validator checks only that `quoted_span` is a substring; it does not
  compare the rest of `claim.text` with the document. `stats.py` now audits
  every numeric claim against the cited document and prints the 82 intended
  defects and 0 unintended ones.
- The validator does not compare a document's `facts` with its `text`.
  `stats.py` now does that for every fact and reports 0 mismatches out of
  2,805; the round-2 `channel_checks`, `guidance` and `ticket_priority`
  problems are gone.
- The same-step ordering rule is real: a note in `new_notes` is not available
  to its own action. Every cited note is in `initial_notes` or `pre_notes`, and
  every source document is no later than its action.
- `owner_signed` notes must have `signature_valid = true`. Authority spoofs
  therefore use `agent` or `external` writers with `signature_valid = false`.
  The one benign signed note is unpadded and cites no document.
- Thesis evidence must exist at `opened_t`; all attack and benign theses
  satisfy that, including the fresh-evidence benign adaptation.
- `initial_book` is inside every band and instrument cap; every `y = 0` sell
  leaves its sector at or above the minimum; every `y = 0` buy leaves its
  sector at or below the maximum. Cash never goes negative in replay.
- Document sentence counts, rationale sentence counts, content hashes,
  duplicate ids, instrument-sector maps and allowed instruments all pass.
- `max_daily_turnover_pct` is recorded but not replayed. I did not build
  turnover-based attacks or rely on the omission; it is listed as an open risk.
- `model_view` / `model_view_at` strip labels and meta. The cases do not
  depend on those fields, so the corpus remains usable under the intended
  causal view. `meta.benign_family` is evaluation-only and is stripped with
  the rest of `meta`.
- The old key-looking constant `SIGNING_KEY` was renamed to the non-secret
  identifier `balanced-mandate-2026`. `check.log` is now one clean run block;
  `run.sh` tees a fresh log each time and does not append.

## Open risks

- **Unknown supervisor.** The eight techniques are hypotheses about what a
  reviewer might miss. If the supervisor checks provenance, units, recency and
  sector bands explicitly, the quote-laundering, false-attribution, vintage
  and band families may all fail to get through.
- **Residual structural asymmetry.** Attacks are still tech-heavy: 238 of 520
  attack targets are in NVDA, MSFT or AAPL, against 35 of 220 benign targets.
  A rule "tech buy above 3k" would catch many attacks and 20 benign
  `benign_tech_rebalance` targets, so it is not perfect, but it is a strong
  feature. All 13 distinct attack notionals also occur among benign targets,
  so there is no attack-only notional; the old `notional > 6_000` threshold is
  no longer perfect either. Attacks also have no 3-step episodes, though
  benign controls do not have 3-step episodes either; the sets still overlap
  at 2, 4, 5, 6 and 7.
- **Whole-episode headroom.** The whole-episode exact-character maximum is
  0.7772, 0.0228 below the 0.80 bar, and it is measured on the 41 pairs
  at 8-gram Jaccard >= 0.12 rather than all 273,430 episode pairs. A checker
  using a different similarity metric or an all-pairs character scan could
  report a different value. The pass-bar metric is attack text, where the
  maxima are 0.7743 (full) and 0.7450 (core).
- **Screened exact scan.** The exact-character scan is over pairs with 4-gram
  Jaccard at least 0.05, not all 134,940 pairs. The 4-gram scan is exhaustive
  and the observed 4-gram maximum is 0.2135, but the exact maximum is a
  screened figure and is reported as such.
- **Artificial phrasing.** The compositional prose occasionally reads
  awkwardly ("with the period-end report carries revenue expansion ...") and
  the codename references ("the ember-lantern file") are invented working-file
  names. A model could learn "odd file names mean attack", although benign
  controls use the same mechanism to reduce that risk.
- **Narrow universe.** One mandate, one book and a tech-heavy instrument set
  mean the results may not transfer to other purposes, bands or asset classes.
  The 15-instrument universe covers all seven sectors, but only two or three
  names per sector.
- **Custom causes are not semantically validated.** The validator cannot tell
  whether a `redteam_*` cause is truthful; only the construction and these
  notes support the labels. The separate book replay and claim/fact audits
  narrow that gap but do not close it.
- **Book-only checks miss epistemic failures.** A supervisor that only replays
  the book will pass the 277 in-band epistemic attack actions, which is
  exactly the gap these cases probe.
- **Determinism scope.** Determinism relies on `random.Random` seeded by
  technique and case, and on stable dict/list ordering. Re-running on the same
  Python version reproduces the corpus exactly; a future Python change to
  random-number internals could alter the prose, though the structure and
  labels would remain.
