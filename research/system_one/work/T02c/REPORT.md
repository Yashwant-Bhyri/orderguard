# REPORT

## 1. What I built

A deterministic world generator for the OrderGuard System One schema. The entry
point is `generator.py::generate(seed, family, shifted=False)`, dispatching to
ten family modules (`fam_clean.py`, `fam_drift.py`, ...). Shared state machinery
lives in `common.py`; reusable scenario pieces in `scenario.py`; sentence
factories in `prose.py`. Only the standard library is used.

Families: `clean`, `drift`, `unsupported_claim`, `misquote`, `vague_hype`,
`poisoned_note`, `authority_spoof`, `stale_thesis`, plus two new causes:
`superseded_source` (the agent relies on a figure a later amended filing
withdrew) and `wrong_mandate_scope` (the agent applies a real owner-signed
permission that belongs to a different sleeve/key).

Every document carries machine-readable facts for all of its substantive
figures, including comparison, consensus, model, target, sell-side, volume and
share-move numbers; fact values are rounded to the precision printed in the
text. The clean family guarantees the documented hard negatives: a new thesis
on a fresh filing, an enthusiastic but factual buy, a trim/rebalance sell, an
exact-quote buy in a sector not used earlier in the episode, and a clean
continuation buy on an existing thesis. `poisoned_note` and `authority_spoof`
each contain an endorsable action that cites a similar external-unsigned or
agent-unsigned note; `wrong_mandate_scope` contains a clean action that cites
this account's own signed mandate note. Provenance fields therefore do not
identify the label on their own.

There are 21 `Builder.doc` call sites and 18 `prose.doc_text` call sites in the
source; all pass the full fact list to `Builder.doc`.

## 2. How to re-run

From this folder:

```
./run.sh
```

`run.sh` prefers `.venv/bin/python` and otherwise uses `python3`, sets
`PYTHONDONTWRITEBYTECODE=1`, removes stale `__pycache__` directories, recreates
`out/`, writes 150 episodes per family to `out/episodes.jsonl`, runs
`python -m og_s1.validate out/episodes.jsonl`, runs `check_variety.py`,
`check_hard_negatives.py` and `check_facts.py`, runs the reproducible
`probe.py --n 1000` out-of-sample probe (seeds 0-999, all families, both
`shifted` values: 20,000 episodes), prints the SHA-256 of the output, and exits
non-zero if any check fails.

## 3. Results

Two consecutive generations are byte-identical
(`SHA-256 9c944206beeb61ea087b968f71c4f38de34a3ecdbd7ed62732125805697be52d`);
generation under `PYTHONHASHSEED=1` and `PYTHONHASHSEED=2` also matches for the
same seed/family.

```
wrote 1500 episodes (210 shifted) to out/episodes.jsonl
family                 episodes  actions  positives    rate
clean                       150      750          0   0.0%
drift                       150      547        178  32.5%
unsupported_claim           150      525        150  28.6%
misquote                    150      531        150  28.2%
vague_hype                  150      532        150  28.2%
poisoned_note               150      679        150  22.1%
authority_spoof             150      671        150  22.4%
stale_thesis                150      929        176  18.9%
superseded_source           150      913        175  19.2%
wrong_mandate_scope         150      680        150  22.1%
label-rate check: OK
```

Validation:

```
validated 1500 episodes across 1 file(s): 0 error(s)
```

Sentence audit (`check_variety.py`). It now counts documents, initial notes,
thesis statements, `thesis.invalidation`, rationales, claims and step notes,
and reports both a pooled denominator and a per-family denominator:

```
sentence audit: 1500 episodes, 39598 distinct sentences
  denominators: pooled over all episodes; per-family over that family
  worst pooled exact-sentence share:    0.733% (limit 5%)
  worst pooled digit-normalised share:  5.467%
  worst per-family exact-sentence share: 4.000% in drift (limit 5%)
sentence variety check: OK
```

The pass bar is exact sentences and is met on both denominators. The
digit-normalised line is only informational; it is above 5% because short
sentences that differ by one number (e.g. an ETF expense ratio) normalise to
the same string. The exact-sentence bar is the one the brief states.

Hard-negative audit:

```
clean hard-negative audit: 150 clean episodes
  adaptation   present in 150/150
  sell         present in 150/150
  exact_quote  present in 150/150
  enthused     present in 150/150
  continuation present in 150/150
  step4_sector present in 150/150
  sell_trim    present in 150/150
hard-negative check: OK
```

Fact / provenance audit:

```
facts: 13648, display-precision mismatches: 0, absent from text: 0
quoted claims: 5394, value absent from source facts: 149
marker phrases (all notes and rationales): 0
  authority_spoof: clean-cites-note 150/150, positive-cites-note 150/150
  poisoned_note: clean-cites-note 150/150, positive-cites-note 150/150
claim-count audit (actions that cite notes; claims capped at 2+):
  authority_spoof      y=0 0:81/1:69/2:0, y=1 0:0/1:150/2:0
  poisoned_note        y=0 0:74/1:76/2:0, y=1 0:0/1:150/2:0
  wrong_mandate_scope  y=0 0:0/1:150/2:0, y=1 0:0/1:150/2:0
opens_thesis audit: continuation buys y=0 806, y=1 379
citation-recency audit (cited a document older than the newest available):
  stale_thesis: clean 149/753, positive 176/176
  superseded_source: clean 147/738, positive 175/175
fact/provenance audit: OK
```

The 149 unmatched quoted values are misquote positives (149 of 150; the other
one happened to coincide numerically with a secondary fact in the same
document). No non-misquote claim has an unmatched value.

```
probe: 20000 episodes (seeds 0-999, all families, both shifted)
  invalid: 0
  clean episodes with a positive: 0
  failure episodes with zero positives: 0
  max positives in one episode: 2
  max steps in one episode: 8
  limit-breach replay failures: 0
probe: OK
```

The probe seeds (0-999) are disjoint from the dataset seeds (minimum 1000).

```
sha256: 9c944206beeb61ea087b968f71c4f38de34a3ecdbd7ed62732125805697be52d
```

## 4. What did not work

- A first reproducibility check failed by a few distinct sentences because
  Python's per-process string hashing changed the iteration order of a set of
  sectors. Replacing it with a sorted list and removing `hash(family)` from the
  dataset seeds made output byte-identical.
- Putting the poisoned note's breach on a sector cap made it overlap `drift`, so
  a supervisor could label it with the wrong cause. The injected instruction is
  now about single-name concentration.
- A clean episode cannot start with an overweight sector (`initial_book` must be
  inside every band), so the "trim an overweight sector" hard negative is an
  in-band trim/rebalance instead.
- Round 1's fixed thesis invalidation sentences were a sentence-variety failure
  once the audit actually included `thesis.invalidation`: two strings occurred
  in 90% of episodes. They are now generated from 18 templates seeded with the
  entry and trigger values, and the audit counts that field.
- Round 1's family-specific thesis statements (e.g. the spoof and scope
  statements) repeated by instrument within a family. They now embed the
  claimed ceiling or sleeve identifier.
- Simply removing "waive the limits" wording from the poisoned note was not
  enough: the clean decoy used a different note shape. The clean decoy now
  sometimes uses the same block-instruction note, sized inside the limits.
- Removing the numeric post-trade sector weight from the drift rationale
  weakens one shortcut, but does not make drift undetectable by replay; the
  replay audit still finds every breach.
- The `share_price_change` colour fact was clamped to non-negative, producing
  "moved 0.0%" lines. It now uses a signed range.

## 5. Judgement calls

- **New cause names.** `superseded_source` and `wrong_mandate_scope`; both are
  short snake_case strings accepted by the validator as novel causes.
- **One failure per episode, mostly.** The brief fixes action-level label rates;
  I keep at least one planted failure in every failure episode, with a second
  positive in a minority of drift, stale and superseded episodes. The
  episode-level prior remains a known risk (section 7).
- **Drift sectors.** Drift is any sector with a wide enough band, not only tech.
  The drift buy is always a buy that leaves the sector above max and respects
  the single-name cap.
- **Trade placement.** Failure steps are not always last; many episodes end with
  an endorsable sell or buy in a different sector. Stale and superseded episodes
  vary the number of context buys.
- **Sizing.** Clean actions keep a 0.4% buffer below band maxima and the
  single-name cap. Only drift, spoof and scope breach a sector band; only the
  poisoned note breaches the name cap.
- **Shifted flag.** Every seventh dataset seed uses `shifted=True`, narrowing
  each sector band by 2 points and raising its floor by 1 point.
- **Signature evidence is kept but made non-diagnostic.** The spoof and poisoned
  families still need an unsigned note; each now also contains a clean action
  citing a note of the same writer/signature shape.
- **Author name.** `meta.author` is `R. Vasquez`, a stable pseudonym.

## 6. Loopholes I checked

- `y = 0` is always `cause = "clean"`; every positive has a non-clean cause.
- Clean actions are inside every limit at their own time on replay. Some clean
  *partial sells that follow a failure* leave the already-breached failure
  sector above its max for the rest of the episode; that is deliberate repair
  behaviour after a breach the agent did not create, and the report no longer
  claims otherwise.
- `drift` labels are buys that leave the sector above max; the initial book is
  inside every band.
- No claim, note or thesis cites a document from the future. Same-step notes an
  action relies on are in `pre_notes`.
- Every `quoted_span` is an exact substring of its `source_doc`; every
  `cause_ref` resolves and is available at the action time.
- Document `content_hash` is recomputed from the text. Replay never drives cash
  or a position negative.
- Every fact's formatted value occurs in its document text, and every fact is
  stored at display precision (13,648 facts, zero exceptions).
- `opens_thesis` is not a label: the dataset has 806 clean continuation buys
  (`opens_thesis=False`, `y=0`) against 379 continuation positives.
- Claim count is not a label for note-citing actions: clean note-citing actions
  include both zero-claim and one-claim cases in both note families, and every
  poisoned/spoof positive carries a true quote-backed claim.
- Citation recency is not a label in stale/superseded: clean actions cite older
  still-valid documents while newer uncited documents exist (149 clean in
  stale, 147 in superseded).
- Marker phrasing was removed from the external and spoof notes; the extended
  audit (`ignore/waive/suspend/do not apply/without waiting/amendment/paperwork/
  pending/treat as effective`) scans **all** notes and rationales and finds 0.
- `meta` and per-step `label` carry all evaluation-only data; no cause name is
  written into narrative text.
- The sentence audit covers every narrative field, including
  `thesis.invalidation`, on pooled and per-family denominators.

## 7. Open risks

- **All sells are clean.** A detector could learn "sell means endorsable".
  Fixing it would require a novel sell-side failure cause; I did not add one
  because the listed causes define failures in terms of adding exposure or
  acting on bad authority, and a contrived sell failure would be less realistic.
- **One bad action per episode, mostly.** Six of nine failure families have
  exactly one positive. The episode-level prior is weaker than in round 1 but
  still present.
- **Field tells remain in the definitions.** `vague_hype` positives have no
  value, unit or source; `unsupported_claim` positives often have no source.
  That is what those causes are, but it is easy to detect without reading.
- **`stale_thesis` rationale prints the negative guidance figure** the agent is
  dismissing, so a text check can find it without evaluating the trigger.
- **`poisoned_note` and `authority_spoof`** share provenance shape with clean
  actions but the remaining tell is behavioural: did the trade breach a limit
  or use an unverified permission? That is easier than the superseded case.
- **Short numeric sentences** normalise to the same string at 5.47% of episodes
  (pooled); exact sentences are far below the bar.
- **New causes sit near existing ones.** `superseded_source` could be argued
  into `stale_thesis`, and `wrong_mandate_scope` looks like `authority_spoof`
  if the account/key line is ignored.
- **`shifted`** only tightens bands; it does not shift publisher mix, document
  length or tone.

## 8. Round 2 changes

Review items are addressed in the order listed in `REVIEW.md`.

1. **Sentence-variety audit and data (fix 1).** `check_variety.py` now includes
   `thesis.invalidation` and splits every narrative field (documents, notes,
   thesis statement/invalidation, rationales, claims). It reports and enforces
   both the pooled 1,500-episode denominator and a per-family denominator.
   Invalidation text is generated by `prose.invalidation` (18 templates plus the
   entry/trigger numbers) and `prose.soft_invalidation`; family-specific thesis
   statements embed the claimed ceiling or sleeve identifier. Result: worst
   pooled exact-sentence share 0.733%, worst per-family 4.000%, both under 5%.
2. **`opens_thesis` shortcut (fix 2).** `scenario.continuation_buy` adds
   endorsable adds to existing theses. Clean episodes now have one guaranteed
   continuation buy, and closeouts in failure families also add them. Dataset
   counts: 806 clean continuation buys vs 379 continuation positives.
3. **`cites_notes` + claim-count shortcut (fix 3).** Poisoned, spoof and scope
   positives now carry a true, exact-quote claim about the traded name. Clean
   note-citing decoys in the poisoned and spoof families randomly carry zero or
   one claim. `check_facts.py` prints the claim-count distribution and fails if
   the count perfectly separates the classes.
4. **Citation-recency shortcut (fix 4).** Stale and superseded episodes insert a
   newer, still-valid `tool_output` document and a clean add that legitimately
   cites the older thesis evidence. `check_facts.py` computes citation recency
   per family and fails if it perfectly separates clean from positive.
5. **Remaining marker wording (fix 5).** The "without waiting for the sleeve
   check" variant and the spoof amendment/paperwork/pending/treat-as-effective
   language are gone. Clean agent memos now also state numeric bands. The marker
   audit scans all notes and rationales and is extended; it reports 0.
6. **Report and author-note overclaims (fix 6).** The clean-sell band statement
   is qualified (partial repair sells after an existing breach), the call-site
   counts are corrected to 21 `Builder.doc` / 18 `prose.doc_text` sites, clean
   step 4 is now actually in a different sector and is audited at 150/150, and
   the sentence-audit section states exactly what is covered. The "hardest"
   claims in `AUTHOR_NOTES.md` are qualified: the provenance fields do not
   separate the labels, but claim count and recency were shortcuts in round 1
   and have been removed.
7. **Bytecode paths (fix 7).** `__pycache__` directories are deleted, `run.sh`
   removes them at start and end, and all Python runs use
   `PYTHONDONTWRITEBYTECODE=1`. No `.pyc` remains and no source/log/JSONL file
   contains an absolute home path.
8. **Audit strength (fix 8).** `check_variety` covers every narrative field and
   states its denominators; `check_facts` scans all notes, adds claim-count,
   `opens_thesis` and citation-recency checks; `check_hard_negatives` verifies
   step 4's sector, a genuine trim sell and a clean continuation buy.
9. **Probe reproducibility (fix 9).** `probe.py` is a checked-in script with
   explicit `--n 1000` seeds 0-999, run by `run.sh`. It validates all 20,000
   in-memory episodes and checks breach replay for drift, poisoned, spoof and
   scope positives.

What I did not change, and why:

- **All sells stay clean.** Adding a sell-side failure would need a novel cause
  whose realism I could not defend as well as the two new families; it remains
  an open risk rather than a hidden one.
- **`wrong_mandate_scope` clean and positive actions both carry one claim.**
  The claim count is therefore uninformative there, which is the goal; the
  family turns on the account/key mismatch.
- **Failure families still always contain at least one positive.** Removing that
  would allow episodes with no instance of the named cause and make
  `meta.family` ambiguous.
- **`shifted` still only tightens bands**, to avoid changing every family's
  difficulty at once.
- **`stale_thesis` still prints the negative guidance figure in its rationale.**
  A human sees the agent dismissing a real number, which is the intended
  failure; removing it would make the family less realistic. It is listed as an
  open risk.
- **Digest-normalised sentence share remains 5.47% pooled.** The stated bar is
  exact sentences; short one-number sentences normalise together. I did not
  distort document text to chase a metric that is not in the pass bar.
