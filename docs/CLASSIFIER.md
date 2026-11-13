# Local injection classifier (L2 first stage)

A small, offline, explainable detector that reads a chunk of untrusted text before (or instead of) a model screen. It is a cheap first
stage, not a replacement for the model screen and not a security boundary. Off by default.

## What shipped, in one paragraph

Classifier v2 is a single logistic-regression model (char + word n-gram TF-IDF over L1-cleaned lines, chunk score = max line) with a Platt
calibration map, an explainable decision layer exported next to it, and stage thresholds for an optional screening cascade. We tried the full
weight-space programme (adversarial augmentation, hard negatives, uniform and greedy model soups, task arithmetic, output ensembles). **None of it
beat the plain single model technique-held-out on the lab chunks**, so the shipped weights are the un-augmented member. The decision layer
did not improve ranking either and is exported for explanation only (`use_decision: false`). Those are the honest results below; the machinery,
the evaluation and the calibration are what is new.

## Method

- Text path (`classifier.analyse`): L1 `normalise.clean()` (zero-width and bidi removed, NFKC, base64 decoded inline), look-alike letters inside
  mixed-script tokens folded to Latin, invisible Unicode-tag text decoded and scored as its own line. Digit-folded char n-grams (3-5, in word boundaries)
  and word 1-2 grams, sublinear TF-IDF, L2 per block.
- Unit and export: the unit is a line; a chunk's score is the maximum over its lines. The artifact `data/models/injection_clf.json` (1.2 MB, format
  `orderguard-injection-clf/2`) holds vocabulary, idf, coefficients, intercept, Platt map, decision layer, thresholds, metrics, and the SHA-256 of the training
  data; `injection_clf.sha256` holds the artifact hash (a test checks it). No pickle; inference is pure Python (no sklearn, numpy or scipy at runtime) and
  deterministic. Training: `python -m orderguard_lab.train_classifier` (needs scikit-learn; about 6 minutes).
- Data: 8755 chunks (431 attack, 8324 clean) in 96 technique groups: the lab's 99 attack and 174 clean detector chunks plus the sandbox's attacked worlds and
  benign twins for 16 seeds. Line labels are exact. Same data as v1.

### Protocol (nothing is tuned on a test fold)

Technique-grouped 5-fold CV; a group never straddles train and test; the attack lines of the test chunks are excluded from every fit. Inside each outer
training side, validation scores are **cross-fitted** (inner grouped 4-fold: every training chunk is scored by members that never saw its group). Only those
cross-fitted scores choose the greedy soup, the task-arithmetic scale, every threshold, the Platt map and the decision layer. Thresholds target a
**source-balanced** false-alarm rate of 3%: lab and sandbox clean chunks get equal total weight, because the lab's real 10-K prose is a better proxy for
deployment text than the 20x larger templated sandbox. (A first attempt that took the threshold from a pooled, sandbox-dominated validation fold gave 40-60%
false alarms on the lab's clean chunks; that is why the weighting exists.) The headline is the **lab** row: the same 99 + 174 chunks the model screens are
measured on.

### Augmentation and hard negatives (training side only)

Attack lines get: zero-width insertion, tag smuggling, homoglyphs, base64 (all undone by L1 or the confusable fold), case/spacing, letter spacing, paraphrase
templates (prefix/suffix/synonyms), Chinese and Cantonese phrase mixing and zh prefixes, a directive split across 2-3 lines (every piece labelled attack),
markdown/HTML wrappers. Clean lines get the same format-type perturbations (wrappers, zero-width, case, homoglyphs) at matched rates so a wrapper alone is
never a signal. Hard negatives: 20 benign imperative sentences ("investors should consider...", "please refer to Note 7"), five true corporate-action
notice templates (dividend, split, buyback, meeting, credit facility), and wrapped versions. The robustness suite uses a **different** pool of prefixes,
wrappers, translations and benign sentences than training, so the perturbation numbers are not measured on augmentation instances.

## Weight-space results (technique-held-out; 5 outer folds; thresholds from cross-fitted training scores)

| model | lab recall (99) | lab false alarms (174) | lab AUC | pooled recall (431) | pooled false alarms | pooled AUC |
|---|---|---|---|---|---|---|
| **single, no augmentation (shipped)** | 56.6% | 5.2% | 0.750 | 62.0% | 2.0% | 0.941 |
| single, augmentation + hard negatives | 24.2% | 62.1% | 0.676 | 34.8% | 3.2% | 0.955 |
| uniform soup (8 members, weight average) | 41.4% | 39.7% | 0.701 | 48.5% | 0.8% | 0.953 |
| greedy soup (selected on cross-fitted validation) | 57.6% | 59.8% | 0.563 | 62.7% | 6.1% | 0.932 |
| output ensemble (mean of member probabilities) | 52.5% | 46.0% | 0.724 | 62.4% | 2.9% | 0.953 |
| task arithmetic (base + lambda * (aug - base)) | 56.6% | 67.2% | 0.513 | 64.0% | 4.3% | 0.944 |
| shipped model, Platt calibrated (same ranking) | 56.6% | 5.2% | 0.710 | 62.0% | 2.0% | 0.930 |
| decision layer over the shipped model | 17.2% | 1.2% | 0.723 | 13.5% | 0.0% | 0.924 |

Reading it:

- Augmentation raises **pooled** AUC (0.941 to 0.955: the sandbox techniques are paraphrase-like of each other) but lowers **lab** AUC (0.750 to 0.676): the
  lab's real prose and held-out technique styles do not benefit, and the synthetic perturbations push real clean text toward "attack" (false alarms jump). Honest
  conclusion: augmentation as built is not a win here. The soups inherit that. Averaging weights is exactly averaging logits for linear members, so a uniform soup is an
  output ensemble in logit space compressed into one model for free; it cannot fix a bad member.
- Greedy soup and task arithmetic pick up the base model's operating point (recall near 57%) but lose lab AUC badly; with only 99 lab attacks and 5 folds, differences of
  a few points are inside the noise, and the lab AUC gap (0.75 vs 0.51-0.72) is the sturdier signal.
- Selection caveat: the shipped model was chosen among these rows by pooled/lab AUC, which is a (mild) selection on the held-out folds. It is also the pre-existing baseline, so
  no tuning was needed to reach it.
- Greedy soups picked per fold: mostly `base` alone (folds 0, 2, 3), `base + l1ops_wrap_b3` (fold 1), `aug_c3_nocw_b6` (fold 4): selection on cross-fitted validation rarely finds an augmented member worth averaging in.

### Calibration (Platt on cross-fitted scores, source-balanced weights)

| probability | pooled Brier | pooled ECE | lab Brier | lab ECE |
|---|---|---|---|---|
| raw sigmoid of the max-line logit | 0.0860 | 0.148 | 0.378 | 0.398 |
| Platt (shipped `p_clf`) | 0.0305 | 0.0189 | 0.221 | 0.196 |
| decision layer | 0.0252 | 0.0116 | 0.209 | 0.161 |

Platt fixes the over-confidence of a class-balanced linear model on the pooled mix (ECE 0.148 to 0.019). It stays miscalibrated on the lab slice (ECE 0.20) because its base
rate is 36% attack, not the training mix's 5%: `p_attack` is a probability **at the training prior**; do not read it as a deployment probability without re-basing it.

### Decision layer (`orderguard_guard.decision`)

Logistic regression over 14 features: classifier max-line logit and top-2 mean, L1 findings (hidden characters, mixed script, base64), agent-address and imperative-to-agent
cues, money-movement and mandate vocabulary, digit density, money-amount count, CJK share, benign cues ("please refer to"), log line count. Every coefficient is in the artifact and
`score()["decision"]` returns the top contributions. Result: under technique-held-out evaluation it did **not** improve ranking over the calibrated model (pooled AUC 0.924 vs 0.930,
lab 0.723 vs 0.710) and its threshold (from cross-fitted scores) was too conservative on test folds (lab recall 17%). It is therefore exported with `use_decision: false`
(`p_attack` = calibrated classifier). It is useful as an explainer and is robust where the n-gram model is not (see below). A numbers-versus-trusted-figure check is **not** here and cannot
be: L2 has no trusted figures, so a plausible edited price looks like a true one. Data-lie detection belongs to L5/L6; the false-data recall below (about a third) is that limit made visible.

### Perturbation robustness (lab chunks, perturbations from the unseen eval pool; recall on attacks / false alarms on benignly perturbed clean chunks)

| perturbation | shipped model | uniform soup | decision layer |
|---|---|---|---|
| none | 56.6% / 5.2% | 41.4% / 39.7% | 17.2% / 1.2% |
| zero-width (L1) | 56.6 / 5.2 | 41.4 / 39.7 | 70.7 / 4.0 |
| tag smuggling (L1) | 52.5 / 4.6 | 34.3 / 80.5 | 66.7 / 5.8 |
| homoglyphs | 55.6 / 5.2 | 41.4 / 39.7 | 84.8 / 17.2 |
| base64 (L1 appends decoded text) | 34.3 / 4.6 | 51.5 / 70.1 | 62.6 / 2.9 |
| case and spacing (L1) | 56.6 / 5.2 | 41.4 / 39.7 | 15.2 / 1.1 |
| letter spacing | 54.5 / 5.2 | 44.4 / 46.0 | 17.2 / 1.1 |
| paraphrase template | 63.6 / 6.9 | 45.5 / 52.9 | 18.2 / 24.1 |
| zh mixing | 54.6 / 5.2 | 38.4 / 39.7 | 18.2 / 1.1 |
| yue mixing | 52.5 / 5.2 | 39.4 / 39.7 | 23.2 / 1.1 |
| zh prefix | 54.6 / 4.6 | 47.5 / 54.6 | 93.9 / 64.4 |
| directive split across lines | 58.6 / 10.9 | 37.4 / 58.0 | 8.1 / 1.1 |
| markdown/HTML wrapper | 52.5 / 5.2 | 35.4 / 40.8 | 14.1 / 1.1 |

The shipped model barely moves under every perturbation except base64 (the decoded text is appended to a long line and diluted: recall 57% to 34%) and, mildly, wrappers/tags/
split (a few points). Property tests (python/tests/guard/test_classifier.py) check that zero-width, case/spacing, tag smuggling and fullwidth letters do not lower the score by more than
0.05, scoring is deterministic, the artifact hash matches, and importing the module opens no network connection. Not measured: the hard-negative sentence pool as a stand-alone false-alarm set
(it is in training only; the eval pool exists in code for a future check). The decision layer's high recall under hidden-character perturbations comes with high false alarms: it keys on the L1 finding itself.

## Fast LLM screens on the same lab chunks (OpenRouter, recorded in data/replay)

Same SYSTEM prompt and request shape as the DeepSeek screen. Latency is wall time of live calls with 24-32 parallel workers (so a quiet-system figure would be lower); cost is per chunk from the provider's reported cost.

| screen | recall (99) | false alarms (174) | median / p95 latency | cost US$ per 1k chunks |
|---|---|---|---|---|
| deepseek/deepseek-v4.1-flash (main) | 82 (83%) | 4 (2%) | not timed | 0.106 |
| z-ai/glm-5.3-flash | 72 (73%) | 3 (2%) | 2.3 s / 6.5 s | 0.112 |
| qwen/qwen3.7-flash | 65 (66%) | 3 (2%) | 8.8 s / 17.2 s (96 timed calls) | 0.113 |
| anthropic/claude-haiku-5.5 | not measurable | not measurable | n/a | n/a |
| liquid/lfm-2.5-24b-a2b | not usable | not usable | n/a | n/a |

Haiku 5.5 returned HTTP 403 "not available in your region" from this machine on every call; its rows were dropped. LFM-2.5 is a reasoning model: with a 400-token cap it never reached an answer, and with
the default body 98 of 273 replies still failed to parse (fail closed), so it is not a usable screen as configured; its rows were dropped. qwen has 2 unparseable replies counted as flags. The cheapest fast screens
cost about the same per chunk as DeepSeek flash (0.11 vs 0.106 US$ per 1k) because DeepSeek flash is already cheap; their only edge is latency (glm), at lower recall. **Stage-2 pick: z-ai/glm-5.3-flash** (best recall at equal
false alarms and cost, 4x faster than qwen), the default for `OG_SCREEN_FAST_MODEL`. Spend for these live calls (plus discarded error rows): about US$0.32 of the US$0.60 cap, all through the audited client.

## Cascade (`OG_SCREEN_CASCADE`, default off)

`off | local+main | local+fast | local+fast+main`. Stage 1 (free, ms): final `p_attack` under `clean_below` passes, at or above `attack_above` is quarantined (source `cascade:local`). The uncertain band goes to stage 2,
the fast model (`OG_SCREEN_FAST_MODEL`, default glm-5.3-flash): a clean answer passes, a flag goes to stage 3 (the main model) if configured, else stands. Without a fast model the band goes straight to the main model.
`off` leaves the default screen's request bodies byte-identical (tests/guard/test_cascade.py asserts the exact body). Thresholds come from cross-fitted validation (clean_below: at most 1.5% of attacks under it; attack_above: 0.3% source-balanced false alarms). They are stage-1 out-of-fold on the lab chunks below.

| configuration (lab: 99 attack, 174 clean) | recall | false alarms | cost US$ per 1k chunks | share of chunks reaching a model |
|---|---|---|---|---|
| local only (shipped threshold) | 56 (57%) | 9 (5%) | 0 | 0% |
| main (DeepSeek) only | 82 (83%) | 4 (2%) | 0.106 | 100% |
| glm only | 72 (73%) | 3 (2%) | 0.112 | 100% |
| local pass, then main (no local quarantine) | 81 (82%) | 4 (2%) | 0.105 | 98% |
| local pass/quarantine, then main (`local+main`) | 83 (84%) | 10 (6%) | 0.089 | 86% |
| local pass, then glm (`local+fast`) | 72 (73%) | 3 (2%) | 0.110 | 98% |
| local pass, glm, main confirms glm flags (`local+fast+main`) | 71 (72%) | 3 (2%) | 0.148 | 98% |
| local pass, glm; glm-clean with p >= 0.05 also to main | 79 (80%) | 4 (2%) | 0.186 | 98% |
| main OR glm (no local) | 83 (84%) | 4 (2%) | 0.218 | 100% |
| main OR local (`OG_CLASSIFIER=ensemble`) | 84 (85%) | 12 (7%) | 0.106 | 100% |

Latency: stage 1 is about a millisecond of pure-Python scoring; glm adds 2.3 s median per routed chunk; DeepSeek latency was not timed in the recorded run, so cascade latency totals are not computed.
The honest finding: **the cascade barely saves money on these chunks**: the confident-clean band is only about 2% of lab chunks (real 10-K prose scores low but not under a threshold that
misses at most 1.5% of attacks), and at this price (0.1 US$ per 1k chunks for the main screen) the saving is a few percent, bought with 6 extra false alarms from the local quarantine. On a stream that is mostly
clean prose the band would be larger; this was not measured.

### Recommended production configuration

1. Keep the DeepSeek main screen as the decision-maker (82/99, 4/174 on the lab set) with `OG_CLASSIFIER=off`, `OG_SCREEN_CASCADE=off`. Nothing here beats it on recall at equal false alarms.
2. If a free offline layer is wanted, use `OG_CLASSIFIER=ensemble`: +2 attacks caught, +8 false alarms per 174 clean chunks; or `prefilter` to quarantine only very confident local hits (p >= 0.51) without a model call.
3. If cost or latency at volume matters more than 2 points of recall, use `OG_SCREEN_CASCADE=local+main` after re-measuring the pass band on real traffic. Do not use the fast models as a replacement screen: at equal cost they catch 8-17 fewer attacks.
4. Data lies (edited figures, lied quotes) are caught by none of these; they need L5/L6 (trusted figure lookup, price checks).

## Limitations

- Trained on OrderGuard's own synthetic attacks and one real 10-K: a new phrasing, language or format can score clean; the held-out lab recall of 57% is the realistic estimate, and 99 lab attack chunks make every lab percentage uncertain by roughly +/-10 points.
- Text alone cannot catch a figure edited to a plausible value; false-data and spoofed-data recall is lowest by design.
- Augmentation and weight-space averaging did not help on held-out lab data; the augmentation generators are our own and may simply not match real obfuscation.
- `p_attack` is calibrated to the training mix (5% attack), not to any deployment prior. The base64 case is weak (57% to 34% recall).
- An adaptive attacker who can query the classifier can rephrase until the score drops. Keep it as a cheap filter in front of the model screen and the deterministic layers.
