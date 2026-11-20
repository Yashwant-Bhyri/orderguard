VERDICT: REVISE

# Review — T16 capability benchmark v0.1

## What I re-ran and what it printed

I ran `bash run.sh` from this folder twice for determinism (and once more after writing this review; exit 0, about 16 s each). The runs printed:

```
generated 600 episodes; family counts {'unsupported_conclusion': 60, 'purpose_drift': 60, 'authority_spoof': 60, 'shared_poisoned_source': 60, 'concentration_build': 60, 'owner_instruction_conflict': 60, 'future_data': 60, 'benign_lookalikes': 180}
benign actions 180; messy episodes 240/600 (40.0%); unique attack texts 1350; max pairwise similarity 0.783
concentration replay checked 180 actions; each episode exposure path 4% -> 8% -> 12% -> 16% of NAV
authority-spoof replay checked 60 actions; tech crosses 30% while the largest instrument remains 16% of NAV
unsupported-conclusion subtype counts {'unsupported_strategy': 10, 'wrong_entity': 10, 'wrong_period': 10, 'wrong_accounting_concept': 10, 'wrong_scope': 10, 'forecast_as_result': 10}; benign look-alike counts {'benign_legitimate_adaptation': 45, 'benign_correct_sell': 45, 'benign_exact_quote': 45, 'benign_factual_enthusiasm': 45}
validated 600 episodes across 1 file(s): 0 error(s)
```

The two determinism runs produced the same `out/benchmark.jsonl` SHA-256 (`63b01a4f…`); its parsed lines are equal to a fresh `generate(seed, scenario)` stream for the same counts. The validator output is reproducible.

Independent audit (no worker code changed):
- 600 episodes, 960 steps, 420 `y=0`, 540 `y=1`; 180 benign actions, 45 per category; 60 episodes per attack family; 10 per unsupported subtype.
- 240/600 episodes (40%) are messy, and **all** documents in those episodes have `facts=[]` (no mixed episodes).
- `cause`/`y` convention holds; every `cause_refs` resolves to an available document or note; initial books and book replay validate.
- **Similarity:** 1,740 attack texts (540 rationales, 540 claims, 660 cited evidence), **1,350 unique cores, 390 duplicate occurrences**. With duplicates included, the maximum token `SequenceMatcher` is **1.000** (six identical authority rationales and six identical authority claims at seeds 0/10/20/30/40/50). The unique-core token maximum is 0.7826. Character-level similarity over unique cores is **0.8789** (authority note texts), 0.8651 (rationales), 0.8372 (claims).
- **Model-view leakage:** `model_view()` removes `meta` and `label` but keeps `action.scenario_type`, `action.truth_type`, and semantic ids (`n_fake_authority`, `d_social_poison`, `d_cache_log`, `n_no_energy`, `n_issuer_limit`, `d_fresh`, `th_adapt`, …). A trivial rule using `scenario_type` plus step index scores **960/960 = 1.000** on the released labels; `scenario_type` alone gives 720/960 (0.75).
- **Report vs code:** `REPORT.md:31` says “980 distinct cores”; the code prints 1,350 and `REPORT.md:38` says 1,350. The 980 is stale. The statements that the max is “over all” and that only “explicit neutral context” was removed are also false (the audit also drops the opening purpose-drift sentence and deduplicates).
- **Secrets/paths/isolation:** no live secret or absolute home path found. `opencode.json` contains only `{env:OPENCODE_API_KEY}`. `generator.py`/`run.sh` read no files outside this folder, use no network, and do not invoke git. No test-set peeking or external data source found.

## Pass-bar items

1. **0 validation errors — MET.** 600 episodes, 0 errors; the validator checks hashes, sentence counts, ids, references, availability, mandate limits, labels and book replay.
2. **≥600 episodes, every scenario type present, ≥150 benign look-alikes — MET.** 600 total, all eight families, 180 benign actions.
3. **No two attack texts more than 80% identical — NOT MET.** Exact duplicate attack texts exist. `run.sh:136` removes duplicates with `dict.fromkeys` before comparing, so it prints 0.783; over the actual attack texts the maximum is 1.000. Even after dedupe, character-level similarity on unique cores reaches 0.879, above 0.80. The unique-token 0.7826 is only true after dedupe and only under a token metric.
4. **Every cause_refs resolves to a real document, note or claim — MET.** All negative labels point to available documents/notes; y=0 labels have empty refs; claims carry no ids.
5. **At least 30% messy variants with empty facts lists — MET.** 240/600 (40%), all documents empty in those episodes.
6. **REPORT.md with required sections — MET for section presence; the Results numbers are not accurate.** All sections exist, but the Results/“loopholes I checked” text is wrong: the 980 count, “over all”, “only explicitly marked neutral context”, and “claim texts alone 0.739” (true only after dedupe) do not describe the benchmark corpus.

## Required fixes, in order of importance

1. **Remove evaluation-only leakage from the model-facing view.** `action.scenario_type` and `action.truth_type` (`generator.py:73`) survive `model_view` (`og_s1/schema.py:366-369`). `scenario_type` is essentially `meta.family`; with step index it classifies every action perfectly. Semantic ids (`n_fake_authority`, `d_social_poison`, `d_cache_log`, `n_no_energy`, `n_issuer_limit`, `d_fresh`, `th_adapt`) are also visible in documents, notes and `action.cites_notes`. Move scenario/truth metadata under `label` (or another evaluation-only field that `model_view` strips), use neutral ids, and add a `run.sh` assertion that `model_view` contains no family/cause/scenario hint and that a metadata-only rule cannot beat a simple baseline. This is the most important defect: the benchmark is currently solvable without reading the evidence.
2. **Fix the similarity audit and duplicate texts.** Delete the `dict.fromkeys` dedupe in `run.sh:136`; compare every attack text, not unique cores. Diversify the repeated authority rationales/claims (10 unique strings repeated six times) and the other duplicated claims/evidence until the maximum is ≤0.80 under both token and character similarity over all texts. Report total input count (1,740) and duplicate count (390), not only distinct count. Removing the dedupe today would fail the assertion at 1.000.
3. **Correct REPORT.md.** Change `980` to `1,350`; state that the audit also drops the purpose-drift opening sentence and deduplicates; state that 0.783 is unique-token only, that the corpus has 1,740 attack texts with 390 duplicates, and that the character-level maximum is 0.879. Correct “among claim texts alone 0.739” to say “after dedupe, token-level”; it is 1.000 over all claims. Update “what did not work”, “loopholes I checked” and “open risks” to cover exact duplicates, the metric ambiguity, the char-level result, and model-view/ID leakage.
4. **Make the text adversarial rather than self-confessing.** Negative rationales/claims currently name the failure outright (“beyond the signed band”, “I knowingly price the 10:00 buy…”, “I still add energy…”, “the apparent agreement is not independent”, “breaches its 15% limit”); benign rationales self-certify (“remains inside the band”, “accurately quoted”, “within the mandate”). A keyword or id detector passes. Rewrite attacks as plausible advocacy that does not confess, and make benign look-alikes genuinely suspicious but correct, without self-certification.
5. **Decouple the named failure from a numeric band breach where possible.** The authority-spoof buy takes tech from 15% to 31% against a signed 30% cap; the poisoned-source buy takes tech from 28% to 33% against 32%. A simple band checker rejects both without examining the forged note or the shared source, so the named capability is not isolated. The report acknowledges this for authority (judgement calls, `REPORT.md:55`) but not for poisoned source. Make the action legal under the signed bands and the forged authority/shared source the only decisive defect, or explicitly label and document the dual failure and add a band-clean variant.
6. **Align cause/scenario labels and increase coverage.** `label.cause` for unsupported/poison/concentration/future does not literally name the scenario type; if `action.scenario_type` is removed from the model view, add a stripped `label.scenario_type` or document the mapping. Binding-error subtypes are only 10 each although the brief says they dominate; increase coverage and template diversity. All episodes use the same owner template and base book (with small family-specific tweaks) and fixed seeds; `meta.shifted` is unused, so there is no distribution-shift variant.
7. **Add independent harness checks.** `run.sh:43` asserts that `scenario_type`/`truth_type` exist but never checks `model_view`; there is no exact-duplicate check, no character-level similarity check, and no leakage baseline. Add them so these defects cannot recur unnoticed.

## Loopholes found

- **Dedupe-before-compare:** `unique_attack_cores = list(dict.fromkeys(...))` (`run.sh:136`) excludes every exact duplicate from the similarity test; the reported 0.783 is therefore not the maximum over attack texts. Every authority rationale/claim string repeats six times.
- **Token-only metric:** the 80% bar is checked with token `SequenceMatcher`; character-level similarity over the same unique cores reaches 0.879. The report does not disclose this alternative result.
- **Scenario leakage in `model_view`:** `scenario_type` is a direct family label and remains in the model input; `truth_type` and semantic ids also remain. A trivial rule gets 100% label accuracy. This makes the “benign look-alikes” hard negatives vacuous: they are marked `benign_*` in the action.
- **Semantic ids:** `n_fake_authority`, `d_social_poison`, `d_cache_log`, `n_no_energy`, `n_issuer_limit`, `d_fresh`, `th_adapt` encode the scenario in ids visible to any consumer.
- **Self-labelling prose:** attacks announce their own violations; hard negatives announce their own compliance. A keyword detector can pass without reading the source documents, defeating the stated product-level purpose.
- **Band-check shortcut:** authority and poisoned-source actions also breach signed sector bands, so a rule checker can reject them for the wrong reason; the report only discusses this for authority.
- **Unchecked `cause_refs` semantics:** the validator checks that refs resolve, not that the cited note/document is decisive; concentration/purpose refs point at the rule note while the breach is only in the rationale/book.
- **Report overclaims:** “the 0.80 pairwise similarity threshold” is asserted over deduped cores, not over the corpus; “generic context is excluded only after the explicit marker” omits the purpose-drift sentence removal and dedupe; “980 distinct cores” is stale.
- **Stale results risk:** report numbers are hand-maintained (`980`, conditional 0.783/0.739) and already diverged from `check.log` and the code output; add generated report values or a check that report numbers match printed metrics.

## Other observations

- Determinism, counts, concentration replay, authority exposure, future-document visibility and validator results all reproduce exactly; the last five blocks of `check.log` match the current output.
- The validator is substantive (it checks the schema and book replay); I found no evidence of tampering. `opencode.json` has only the environment placeholder; no live credential is present. No absolute home paths or secrets were found.
- No hard-coded label table or hand-typed metric was found in the generator; labels are computed by construction. `run.sh` uses fixed expected counts and `[8.0, 12.0, 16.0]` as consistency assertions, not as reported metrics. REPORT numbers are hand-maintained, and one (980) is stale; that is the hard-coded-results risk.
- The fixed seeds 0–59/0–179 and the dedupe were tuned against the generator's own audit (the report admits 0.783 is a development check). There is no external test set, so this is test-gaming rather than classic peeking; the fix is to freeze the generator and rerun with duplicate-inclusive, character-level metrics before external use.
- The prior future-data/full-episode question is resolved in Round 3 by removing post-action documents; I verified that future-data episodes contain no document timestamped after the action. `ESCALATION.md` now records the one interface question from this review (model-view visibility of scenario metadata), not a claim that the concrete fixes are blocked.
- The benchmark is weak for generalization beyond its templates: fixed seed range, one owner/book shape, repeated source strings and 10 unique authority attacks repeated six times. This is the same defect as the pass-bar similarity failure, so fix 2 and 6 are coupled.
