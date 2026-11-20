VERDICT: REVISE

Review of T02a "Thornbury" independent world generator. SOL_ADVICE.md is absent,
so there is no binding ruling to check. The pre-existing ESCALATION.md was the
worker's round-5 "no escalation" note; this review supersedes it.

Bottom line: every pass-bar item is met and every number in REPORT.md reproduces
exactly under my own re-run and an independent recomputation. The verdict is
REVISE, not PASS, because BRIEF section 3 ("Do not make failures detectable by an
obvious marker word or field") is violated by several *perfect* residual markers
that I measured in the corpus. These are concrete and locally fixable; the
artifact is valid, deterministic and reproducible, so it is not a FAIL.


## 1. What I re-ran and what it printed

Entry point: `bash run.sh` (uses python3, no .venv present). Full run exited 0.
Key printed lines (identical to the final block of check.log):

- wrote 1500 episodes across 10 families
- sha256 out/episodes.jsonl 4bf9cd9abfdad4d084ec815bdb37a613ab5e2f7788b7c3dd0a8eb8442356b55f
- validated 1500 episodes across 1 file(s): 0 error(s)
- semantic audit: 41/41 checks passed
- stress: 6000 episodes generated and validated, 0 error(s); semantic 9/9 checks pass
- scan: 10000 episodes over seeds 0-499, 0 error(s); semantic 9/9 checks pass;
  smallest trade 0.5305% in unsupported_claim seed 286
- seed 104 clean: smallest trade 1.0000%
- TOTAL 1500 eps / 6747 actions / 1350 positives / rate 0.200
- failure-family rate range: 0.217-0.229
- sentences: 72101 distinct; worst repeats in 9 episodes (0.600%) -> OK
- per-family worst sentence: poisoned_note 6/150 (4.000%) OK
- misquote buy diff 12.92%..39.00% (77), sell -44.80%..-19.23% (73)
- drift overshoot 1.213%..2.595%; liquidity planted buy 4.306%..5.000%,
  largest y=0 order 2.200%; label-rate check: OK

Determinism: the SHA above matches the file that was already in out/ before my
re-run, so two independent full regenerations are byte-identical. I also called
generate(1000,"drift") and generate(104,"clean") twice each: identical dicts.
generate(104,"clean") smallest trade = 1.0000% (matches REPORT).

Independent recomputation (my own script over out/episodes.jsonl, not run.sh's
summary): per-family episodes/actions/positives/rates, step-length ranges, and
sentence variety (regex splitter `(?<=[.!?])\s+`, pooled and per family) all
match REPORT.md and check.log to the printed precision. I re-derived the
planted-failure semantics from the raw text/numbers: unsupported (claim asserts
backlog, filing lacks the fact, span is a real revenue span) 0 bad; misquote
(span carries the real EPS, claim value differs) 0 bad; stale (trigger
organic_growth<3.0, exactly two post-thesis company filings both <3, status
weakened, claim quotes the second filing, non-opening buy) 0 bad; withdrawn
(claim uses the note's implied_upside, note carries a suspend status) 0 bad.
y=0 orders above 4% of book: 0. model_view/model_view_at strip meta and labels
and leave the input untouched. shifted=True vs False changes only meta.shifted
(content identical), as REPORT discloses.

Isolation/secrets/leakage sweep: generator and audit are standard-library only
and read/write only inside this folder; no os/subprocess/socket/urllib/requests
/ network / git calls; no absolute home paths and no literal secrets in any
file (opencode.json references {env:OPENCODE_API_KEY} and denies
external_directory and git). The only pathlib import is in the provided
og_s1/validate.py. No train/test split exists, so there is no test-set peeking;
the retry loop, the 0.5%-of-book trade floor and the 4.0% policy scope are
author-side quality design tuned to the generated corpus, and meta.seed records
the requested seed. Nothing here is a leakage or isolation breach.


## 2. Pass-bar items

1. 0 validation errors — MET. `python -m og_s1.validate` reports 0 errors on
   1500 episodes in my re-run (and on the 6000 stress + 10000 scan corpora).
2. Every family is present — MET (against BRIEF's explicit enumeration). All 8
   enumerated families (clean, drift, unsupported_claim, misquote, vague_hype,
   poisoned_note, authority_spoof, stale_thesis) are present, 150 each. See the
   binding_error gray area in section 4.
3. The two new families are present — MET. liquidity_breach and
   withdrawn_target, 150 each, both absent from SCHEMA's cause list, both
   realistic and labelled with cause + cause_refs.
4. Label rates 5%-60% in failure families, 0% in clean — MET. Action-level
   rates 0.2174-0.2294 (in band); clean 0.0000. Metric reading resolved in
   section 4.
5. Sentence variety: no sentence in >5% of episodes — MET. Pooled worst 9/1500
   = 0.600%; worst per family 6/150 = 4.000%. Both readings satisfied and
   enforced by run.sh.

All five pass-bar items are met and all numbers reproduce. REVISE is driven by
the section-3 marker requirement below, not by the pass bar.


## 3. Required fixes (in order of importance)

Each item is a measured, near-perfect detector cue that violates BRIEF section 3
("as hard to spot as you can ... Do not make failures detectable by an obvious
marker word or field"). Counts are positives-with-cue / family-size, and the
cue's occurrence in clean.

1. unsupported_claim: the constant "$2.4 billion". Every one of the 150 positive
   claims ends "to $2.4 billion"; the string appears in 0 clean episodes and 0
   episodes of any other family. A one-substring rule detects this family with
   100% precision and recall. It is also unrealistic (an identical fabricated
   backlog dollar figure across 150 different issuers). Randomize the backlog
   dollar amount per episode and vary the claim wording. (fam_unsupported.py
   hard-codes "$2.4 billion" in all three variants.)

2. withdrawn_target: the price-target range. The positive note's price_target
   fact is in [$1.03, $11.61] (pt = book_value/1e6 * U(0.04,0.16)); every other
   analyst note in the whole corpus is >= $18.08. "analyst price_target < 18"
   flags all 150 withdrawn positives with zero false positives. The tie of a
   share price target to portfolio size is also economically meaningless. Sample
   pt from the same [18,240] distribution used by every other analyst note.

3. Opening-order-size family fingerprint. The first action's notional/book is an
   exact constant per family: stale_thesis 1.000% (150/150), drift 2.000%
   (150/150), unsupported_claim/misquote 2.400% (147/150 each), vague_hype/
   poisoned_note/authority_spoof/liquidity_breach/withdrawn_target 2.200%
   (146-150/150). Clean openings span [1.90%, 2.60%] and never equal 1.0/2.0/
   2.2/2.4% exactly. A single numeric field therefore classifies the family
   near-perfectly (1.0%->stale, 2.0%->drift, 2.4%->unsupported/misquote,
   2.2%->the five 2.2% families). Draw the opening fraction from one shared
   per-episode random distribution across all families, including clean.

4. liquidity_breach: the policy-days field. The signed liquidity policy uses
   days in {2,3} (109x2, 41x3) only in liquidity_breach; every other family uses
   {3,4,5}. "more than 2 trading days" identifies 109 liquidity episodes with
   perfect precision, and days in {4,5} excludes the family entirely. Sample
   days from the same {3,4,5} set in every family and adjust the breach
   arithmetic (adv/desired) to keep the planted buy above the limit.

5. Fixed positive-only templates in stale_thesis and misquote. The stale
   rationale clause "We read the two quarters as timing" occurs in 150/150 stale
   positives and 0 elsewhere; the misquote claim template "The {tk} filing
   reports adjusted earnings per share of ${x}" occurs in 150/150 misquote
   positives and 0 elsewhere (clean never makes an EPS claim). Vary these with
   several phrasings and/or add a clean analogue (e.g. a clean exact-EPS claim)
   so the templates are not label-perfect.

6. Positive thesis-statement skeletons. Each failure family's positive thesis is
   a single fixed skeleton present in 100% of that family's positives and 0% of
   clean: drift "should carry a larger allocation"; vague_hype "on the cusp of a
   step change in relevance"; poisoned_note "top-of-book position as the";
   authority_spoof "recovery is under-owned after"; liquidity_breach "without
   disturbing the price"; withdrawn_target "upside to the price target and a
   re-rating catalyst"; unsupported_claim and misquote opening+sell skeletons
   cover 117/150 and 119/150 (the add-on variants reuse clean's mid-teens
   thesis). This is the same class of near-perfect marker the worker already
   removed for poison/spoof note wording. Add variant pools and/or clean
   analogues, and broaden check_marker_phrases (currently only three hard-coded
   phrases) to scan thesis/claim/rationale skeletons for the >=90%-family /
   <=5%-clean condition the worker already uses.

7. Report accuracy / disclosure. REPORT section 6 ("Loopholes I checked") and the
   audit line "no poison/spoof wording is a near-perfect family marker" imply a
   marker parity the data contradicts for items 1-6; section 7 discloses only
   generic "family vocabulary". Either fix items 1-6 (then refresh the numbers
   and the audit) or explicitly disclose these specific perfect markers. As
   written the report overclaims by omission.

Lower-priority robustness notes (fix if convenient, not blocking):
- check_unsupported verifies the absent fact name and a real span but never
  checks from the claim text that the claim actually asserts the absent fact; a
  regression asserting an existing fact would still pass. Compare claim.value /
  subject against the document's facts.
- check_clean_analogues is corpus-level (counts > 0), not per-episode. Per-episode
  coverage happens to hold (relative / social-numeric / null-value / tool-thesis
  all 150/150, verified), but the check would not catch a regression that
  concentrates them in a few episodes. Make it per-episode.
- check_facts matches abs(value), so it cannot catch a sign error between prose
  and facts.
- Suspended-analyst-note presence is 150/150 in withdrawn_target vs 56/150 in
  clean and 0 in every other family — a family presence cue. Lower severity
  (the note is the semantic cause and clean analogues exist); consider equalizing
  presence across families.


## 4. Loopholes found / gray areas

- binding_error scope (spec inconsistency, resolved in the worker's favour).
  SCHEMA.md section 3 lists binding_error as a cause and og_s1/validate.py
  enforces its cause_refs, but BRIEF's explicit family enumeration omits it and
  the worker generated exactly the enumerated 8 + 2 novel. I read "Every family
  is present" against BRIEF's explicit list, which is met. If the lab intends
  "all the causes in SCHEMA.md" literally, a binding_error family is missing —
  that would be a REVISE item (add the family), not an architecture dispute. I
  record one precise, non-blocking question for the lead in ESCALATION.md.

- Label-rate metric (resolved, not escalated). The pass bar says "label rates
  5%-60% in failure families". SCHEMA defines Label as the ground truth for one
  *action*, so the natural rate is positives/all-actions (21.7%-22.9%, in band).
  The worker prints the episode-level positive share separately (1.000 for every
  failure family, 0.000 clean) and discloses it. The episode-level reading is
  incoherent with "meta.family names the planted failure family" (an episode with
  no positive has no family to name), so I accept the action-level reading as
  meeting the pass bar. The one-positive-per-episode design that forces the
  episode-level share to 1.0 is disclosed as an open risk.

- Residual structural cues (disclosed in REPORT section 7, acceptable but noted):
  positive index varies by family (stale cannot place one before index 2),
  episode length is close-but-not-identical across families, every failure
  episode has exactly one positive, and stale positives are universally
  non-opening. These are weaker than the section-3 markers and are disclosed.

- shifted is a recorded flag only (verified: content identical for True/False).
  SCHEMA says the generator "may use" it, so this is permissible; REPORT makes no
  shift-robustness claim. Not a defect.

- No leakage, isolation breach, wrong metric, hard-coded result, secret or
  absolute home path was found (section 1). The audit is substantive (41 real
  checks re-deriving meaning from text/numbers), not a rubber stamp; its gaps are
  the robustness notes above.
