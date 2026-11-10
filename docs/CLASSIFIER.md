# Local injection classifier (L2 first stage)

A small, offline, explainable detector that reads a chunk of untrusted text before the model screen does. It is a first stage, not a
replacement for the model screen and not a security boundary. Off by default.

## Method

- Features: L1 `normalise.clean()` first (zero-width and bidi characters removed, NFKC, base64 decoded inline; invisible Unicode-tag text is
  decoded and scored as its own line). Then digit-folded character n-grams (3-5, inside word boundaries) and word 1-2 grams, TF-IDF with
  sublinear tf and L2 norm per block, 45k features at most.
- Model: logistic regression (C=10.0, class-balanced). The unit is a **line** (paragraph, feed event, page line); a chunk's score is the
  maximum over its lines, so one planted line is not diluted by 11 clean ones.
- Export: plain JSON (`data/models/injection_clf.json`, 0.76 MB): vocabulary, idf, coefficients, intercept, thresholds, config, metrics and
  the SHA-256 of the training data. No pickle. `orderguard_guard/classifier.py` scores in pure Python (no sklearn, numpy or scipy at runtime).
  `classifier.score(text)` returns `{"p_attack", "label", "top_features"}`.
- Training is deterministic: `python -m orderguard_lab.train_classifier --out data/models/injection_clf.json` reproduces the artifact byte for byte.
  scikit-learn is needed only for training (a training-only extra).

## Data

8755 chunks (431 attack, 8324 clean) in 96 groups, deduplicated:
the 99 attack and 174 clean chunks of the lab's detector test (`og-lab detect`), plus the sandbox's attacked worlds and their benign twins for
16 seeds of every technique (attack chunks are the chunks holding a line the twin does not; every twin chunk, all surfaces, is clean).
Line labels are exact: a line of an attack chunk is an attack line unless the same line occurs in clean text of the same source. A group is a lab
case or a sandbox technique; it never straddles train and test. Attack lines that differ from a clean line only in digits (an edited figure, a
lied price) have identical features, so they are dropped from training; they still count as misses in evaluation.
Clean text is only what the lab and sandbox generate (a real Apple 10-K, templated filings, pages and feeds): no other real-world text.

## Held-out evaluation

technique-grouped CV; test lines removed from training; threshold chosen by inner CV (nested). Folds: 5, assigned greedily and deterministically. Test attack lines are removed from the training side; the
threshold of each fold is picked by an inner grouped CV of that fold's training data only (target 1.5% false alarms on clean chunks), so
nothing below was tuned on the chunks it is measured on. Chunk level: a chunk is flagged if its best line is at or above the threshold.

| slice | attack chunks | recall | clean chunks | false-alarm rate | precision | AUC |
|---|---|---|---|---|---|---|
| all | 431 | 68.7% | 8324 | 2.1% | 62.7% | 0.9482 |
| family A: instruction | 59 | 61.0% | 8324 | 2.1% | 17.0% | 0.9547 |
| family B: authority | 125 | 95.2% | 8324 | 2.1% | 40.3% | 0.9974 |
| family C: false data | 120 | 61.7% | 8324 | 2.1% | 29.6% | 0.9233 |
| family D: spoofed data | 105 | 48.6% | 8324 | 2.1% | 22.5% | 0.9124 |
| family E: denial of service | 22 | 72.7% | 8324 | 2.1% | 8.3% | 0.9571 |
| source: lab | 99 | 59.6% | 174 | 9.2% | 78.7% | 0.771 |
| source: sandbox | 332 | 71.4% | 8150 | 2.0% | 59.7% | 0.9604 |
| surface: doc | 43 | 55.8% | 1495 | 1.0% | 61.5% | 0.8813 |
| surface: feed | 225 | 72.0% | 4824 | 3.3% | 50.1% | 0.9465 |
| surface: tool | 41 | 43.9% | 402 | 0.0% | 100.0% | 0.9595 |
| surface: web | 122 | 75.4% | 1603 | 0.0% | 100.0% | 0.9697 |

Sandbox rows dominate the pooled numbers (many seeds of the same templates), so read the **lab** row (the same 99 + 174 chunks the model screens
are measured on; it is the row in the detector table of docs/RESULTS.md) as the headline: recall 59.6%, false alarms 9.2%.
Pooled false alarms are near the target, but on the lab's clean chunks (mostly real 10-K prose) they are several times higher, so the 2% target is **not** met there.
Clean sandbox text shares templates across seeds, so its false-alarm rate is optimistic; the lab figure is the more honest one.
For comparison, the model screen (DeepSeek v4.1 flash) in docs/RESULTS.md reaches 83% recall and 2% false alarms on the same lab chunks.
A clean chunk's lines can also appear in training (shared 10-K lines occur in many groups); only attack-line text of the test chunks is excluded from training.

Cross-source (train on one source only, test on the other, threshold from inner CV):

| setting | attack chunks | recall | false-alarm rate | AUC |
|---|---|---|---|---|
| train lab -> test sandbox | 332 | 34.9% | 8.0% | 0.748 |
| train sandbox -> test lab | 99 | 78.8% | 86.2% | 0.5295 |

Training on the sandbox alone fails on the real 10-K: its clean prose is unlike the sandbox's templated filings and most of it is flagged.
That is the out-of-distribution risk in one number.

Techniques never caught out-of-fold (recall 0): lab:A-D2, lab:A-zhHant-doc, lab:B-xyz-feed, lab:C-D3, lab:C-D8, lab:C-fakewire-web, lab:C-guidance-web, lab:C-seclike-web, lab:C-stale-doc, lab:C-tableonly-doc, lab:D-F1, lab:D-basket-crash, lab:D-lowprice-web, lab:D-msft-crash, lab:D-venue-lie, sbx:fake_tool_json, sbx:spoofed_ticks, sbx:venue_lie.
Per-technique recall is in the artifact under `metrics.held_out.by_technique`.

## How it plugs in

`OG_CLASSIFIER=off|prefilter|ensemble` (or `Screen(..., classifier=...)`), default `off`:

- `off`: nothing is loaded; screen behaviour and every model request body are unchanged (replay recordings stay valid).
- `prefilter`: a chunk whose score is at or above `prefilter_threshold` (0.881) is quarantined without a model call (category
  `instruction`, source `classifier`); everything else goes to the model as before.
- `ensemble`: the model is asked exactly as before; the chunk is flagged if the model OR the classifier (at `threshold` 0.878) flags it. The
  model's cached verdict is never altered.

The detector row is produced offline by `og-lab detect --screens local:clf` from the out-of-fold predictions only.

## Limitations

- Trained on OrderGuard's own synthetic attacks. A different phrasing, language or format can score clean (a zero-width-obfuscated variant of a
  training-style directive is caught only because L1 first removes the zero-width characters; an unfamiliar tag-smuggled sentence can fall under the threshold).
- Text alone cannot catch a figure edited to a plausible value or a lied quote. False-data and spoofed-data recall is the lowest by design;
  those need the trusted-figure and price checks (L6, L7).
- Real filings and news outside the lab's Apple 10-K are untested. Expect more false alarms on unfamiliar prose until retrained on real clean text.
- The classifier does not give an attack category (it reports `instruction`) and is easy to probe once published: an adaptive attacker can
  rephrase until the score drops. Treat it as a cheap filter in front of the model screen and the deterministic layers.
- Small data: 431 attack chunks from 96 groups; the pooled metrics have wide uncertainty and one different split of techniques would move them.
