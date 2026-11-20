VERDICT: REVISE

# Adversarial review — T02d round 4

## What I re-ran and what it printed

I ran the task's entry point from this folder, without changing any worker file:

```
bash run.sh
```

There is no `.venv`, so the script used `python3` (3.12). `run.sh` has `set -eu`, completed to the final echo, and printed:

```
total: episodes=1650 actions=6750 positives=1500 label_rate=22.222%
sentence audit: episodes=1650 distinct_sentences=33191 maximum_reuse=53 max_rate=3.212% over_5pct=0
punctuation audit: episodes=1650 distinct_sentences=33181 maximum_reuse=53 max_rate=3.212% over_5pct=0
dataset_sha256=fce1ea77fd0fa81b6a07332e551e4c43591615c9bdd5030d46d93d4279ecc348
validated 1650 episodes across 1 file(s): 0 error(s)
...
audit: 0 problems
seed sweep: episodes=220000 validator_errors=0
determinism: cross_process_sample=308 mismatches=0
bytecode audit: cache_dirs=0 pyc_files=0
elapsed_seconds=48
```

Every printed section-3 number in `REPORT.md` matches this run and `check.log`; the dataset SHA is identical. The two `check.log` runs also share that SHA. So the printed numbers reproduce. That is the only good news.

I also wrote independent read-only checks: I replayed each book, checked every `y=0` action against the signed review/compliance conditions, verified every clean claim's quoted span, checked the thesis statements against their evidence documents, and computed sentence reuse per family. Those checks found several problems the worker's `audit.py` does not cover.

## Pass-bar items

1. **0 validation errors — MET.** `validated 1650 episodes across 1 file(s): 0 error(s)`; the 220,000-episode sweep also reports 0.
2. **Every family present — MET.** 11 families × 150 episodes: the brief's eight, the SCHEMA's `binding_error`, and the two novel families `signed_restriction_breach` and `embargo_breach`.
3. **Two new families present — MET.** Both have 150 episodes and a distinct non-SCHEMA cause.
4. **Label rates 5–60% in failure families, 0% in clean — MET on the declared labels** (all failure families 25%, clean 0%). However, the declared labels are not all true: fixes 1 and 2 below identify clean actions that a careful owner would not endorse.
5. **Sentence variety — NOT MET under the natural per-family reading; MET only when all 1,650 episodes are pooled.** The pooled maximum is 53/1650 = 3.212%. Per family, all 11 families exceed 5% of that family's 150 episodes: `poisoned_note` 53/150 (35.3%), `misquote` 53/150 (35.3%), `embargo_breach` 51/150 (34.0%), `clean` 45/150 (30.0%), `unsupported_claim` 43/150 (28.7%), `vague_hype` 33/150 (22.0%), `binding_error` 50/150 (33.3%), `signed_restriction_breach` 24/150 (16.0%), `authority_spoof` 17/150 (11.3%), `drift` 9/150 (6.0%), `stale_thesis` 9/150 (6.0%). The brief says "no sentence repeats in more than 5% of episodes"; pooling families into one 1,650-episode denominator hides repetition inside each 150-episode family. Either the sentences must vary per family or the lab must rule that the pooled denominator is the intended one.
6. **Every number in `REPORT.md` section 3 reproduces — MET for the printed corpus metrics**, with one semantic exception: the "150 clean wait hard negatives" count is printed but those 150 actions are not clean (fix 1). The historical numbers in section 4 are explicitly marked not reproducible; that is acceptable as a record.

## Required fixes, in order of importance

1. **Fix the `embargo_breach` clean wait hard negative.** In `fam_embargo_breach.py:20` the release is session 60; every action is at t=15/25/35/45. The wait step is at `fam_embargo_breach.py:55-69` with `t=35` or `45`, its desk note says the release is session 60, and the action cites that pre-release desk note (`cites_notes` includes `wait_desk`). The owner-signed compliance condition says "orders must wait for the scheduled publication" and "not for dealing use before then"; all 150 wait steps are therefore pre-publication orders with the desk copy in hand, yet labelled `y=0`. The clean wait hard negative is invalid and the label is wrong. Make the wait action occur after publication (e.g. add a post-60 step and a public document carrying the figure), or make the desk note's release precede the action and make the figure public; then update `audit.py:175-198` to check `action.t` against the release and remove/rebuild the `embargo_wait_has_hardneg` invariant. After the fix, update `REPORT.md` and `AUTHOR_NOTES.md`, which currently claim these 150 steps wait for publication.
2. **Fix the false `vague_hype` clean rebalance exit.** In 113 `vague_hype` episodes the clean INDEX_FUND sell is justified by a `REBALANCE_CHECK` tool output (`fam_vague_hype.py:40-49`) that says "basket weight 28.00% is above the 25.0% target". The actual initial book has INDEX_FUND = $10,000 of $100,000 (10%), and the sell moves the weight further below 25%, not toward it. The action's claim/rationale ("trimmed back toward its target weight") is false, the tool output is false, and `y=0` is not defensible. Rebook the index sleeve to $28,000 with funded cash (as `fam_clean.py:73-76` does) or generate the check from the replayed book. `audit.py` currently counts these among `clean_ff_sells=263` without checking the claim.
3. **Fix the clean-family thesis publisher misattribution.** `fam_clean.py:39` takes `publisher = d0["publisher"]` and `fam_clean.py:138` uses it for every thesis. T1 (evidence D1) and T3 (evidence D3) — and sometimes T2 (evidence D2) — name D0's publisher instead of the evidence document's publisher. I found 226 wrong-publisher thesis statements in 145 of 150 clean episodes. Seed 0: T1 says "from North Quay Registry" while D1 is published by Cairn Point Filings; T3 says "North Quay Registry" while D3 is Canopy Market Wire. These are clean episodes containing binding-style misattribution; use the evidence document's publisher or omit the publisher, and add an audit for it.
4. **Make sentence variety pass per family, or document an explicit lab ruling for the pooled metric.** The repeated sentences are mostly fixed templates: the three poisoned-note variants repeat 47–53 times each in 150 `poisoned_note` episodes; the five embargo desk-copy variants repeat up to 51 times; the three misquote rationales repeat up to 53 times; the clean thesis-invalidation sentences repeat 34–45 times. Add per-episode variables or clause pools to these fixed sentences and print per-family maximum reuse as well as the pooled figure. This is a pass-bar item, not only a style point.
5. **Fix the `signed_restriction_breach` thesis trigger.** `fam_signed_restriction.py:41-45` replaces the target thesis's statement and written invalidation with a tender thesis, but leaves the old numeric `invalidation_trigger` (revenue_growth, turnover_pct, comparable_sales_growth, or distribution_coverage) in place. All 150 target theses have a trigger unrelated to the tender. Set a tender-relevant trigger (`tender_unaccepted_pct`) or `null`, and audit it.
6. **Remove the structural family cue.** Every failure family has exactly four actions and every clean episode has exactly five (`Counter` over `out/episodes.jsonl`: all ten failure families `4`, clean `5`). `steps` length alone identifies clean episodes, whose labels are all 0. The report admits "clean always has five actions" in section 7 but does not fix it. Mix the action counts (e.g. add a clean hard-negative step to some failure episodes, or make some clean episodes four-action) so episode length is not a family classifier.
7. **Close the audit/report gaps and correct the overclaims.** `audit.py` checks `PLAIN_CLAIM` scope truth but never checks `EXIT_CLAIMS` against the book (`vague_hype` false rebalance), never checks thesis publishers (`fam_clean`), never checks the signed-restriction trigger, and never checks wait-action timing (`embargo`). The `clean_ff_sells=263` and `clean_missing_hardneg=0` numbers therefore overstate cleanliness. `REPORT.md:44` and the `AUTHOR_NOTES` claim "150 clean wait hard negatives" and "waits for publication, trading only on the public record"; that is false for the current data. `REPORT.md:66` says "The review note is always N0, identical across seeds"; the ID is always N0, but the text is not identical (the audit itself prints 1,650 distinct signed wordings). Update both documents after the code fixes, and add the new checks to `audit.py` without altering `og_s1/validate.py`.

## Loopholes found

- **The pooled sentence metric is the main metric loophole.** 53/1650 = 3.2% hides 53/150 = 35.3% within a family. The pass-bar wording does not explicitly say "per family", but each family is a separate 150-episode test; a stricter evaluator will fail it.
- **Family structure is a classifier.** All failure episodes have four actions and one positive (25%); all clean episodes have five actions and zero positives. Action count and positive rate are free labels at episode level; the report acknowledges the five-action clean family but not that it is a clean/failure marker.
- **The clean figure-free consumer entry is a "cites the exception" cue.** It is a legitimate mandate provision, but the report itself lists it as an open risk; a detector can learn the cue rather than read the exception's scope.
- **`audit.py` only audits `PLAIN_CLAIM` text.** `EXIT_CLAIMS`, thesis statements, and rebalance/reserve tool-output facts are outside the semantic checks; the `vague_hype` false rebalance and clean publisher errors pass "0 problems".
- **The `embargo` check tests the figure's publicness, not the action's timing.** A pre-publication order with a public claim passes the current `embargo_wait_nonpublic=0` check; that is why the wait hard negative looks valid.
- **`clean_ff_sells=263` is not a clean-claim count.** It contains the 113 false `vague_hype` exits; the counter should be split and the claims replayed.
- **The side-aware digit shortcut is only weakened, not broken.** The detector still scores tp=150, fp=150; a supervisor can use "cites the exception" or the family's action count to separate the clean and failure sides.
- **The `binding_error` direction variant is easy.** The report acknowledges it: side-versus-words is a shallow check; entity/period variants are harder.
- **The `unsupported_claim` value-only collision is deliberate.** The report acknowledges that a value-only matcher can call a claim supported; the metric name is the only discriminator.
- **The author-added signed-note question is unresolved.** There is no `SOL_ADVICE.md`; the worker's `ESCALATION.md` is a self-resolution explicitly marked "NOT a lab ruling". I accept the `owner_signed` notes as mandate content because SCHEMA says a valid owner-signed note is part of the world, but the lab has not accepted it; this remains a methodology risk for `vague_hype`, `embargo_breach`, and the clean consumer entry.
- **The historical figures in `REPORT.md` section 4 are hand-typed and not reproducible.** They are explicitly marked historical, so this is not a current-result mismatch, but they should not be used as evidence for the current code.
- **No isolation breach, secret, or absolute home path was found.** All code is inside this folder, imports are local or standard library, and `opencode.json` references `{env:OPENCODE_API_KEY}` rather than a key. `check.log`/`REPORT.md` contain no personal paths. The `ESCALATION.md` is the only unresolved process artifact.

## Bottom line

The corpus is large, deterministic, structurally valid, and many numbers reproduce. It is not yet a fair test: three clean-action families are mislabelled or contain false statements, the sentence-variety bar passes only by pooling families, and the audit is structurally blind to exactly those failures. These are REVISE items, not an escalation; I did not edit the worker's code.
