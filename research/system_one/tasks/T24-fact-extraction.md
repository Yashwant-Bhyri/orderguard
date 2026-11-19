---
id: T24
title: Fact extraction from prose, quote-anchored - the input real documents will not give us for free (F2, X7)
depends: T01, T15
worker: opencode-go/deepseek-v4.1-flash
variant: high
isolate: false
env_keys: OPENROUTER_API_KEY
check: bash run.sh
timeout_min: 150
max_rounds: 4
---

# T24. Quote-anchored fact extraction

Read `research/system_one/POLICY.md`, `docs/vision/lab/BLUEPRINT.md` (F2), `docs/vision/lab/blueprints/COMPARISON.md` and `og_s1/eval/SPEC.md` first. Your task folder is `research/system_one/work/T24/`. Code goes in `og_s1/extract.py`. Heavy work runs on the university host (see POLICY.md).

**Isolation rule:** do not open `work/T02*`, `work/T06`, `work/T16` or `data/heldout*`.

## Why

Our code checks read each document's structured `facts`. Real filings, news and research notes have none. Every independent blueprint flagged the same open question: if the facts have to be extracted, the extractor is a learned component with its own error rate, and that error flows into every code check.

## Build

1. **`extract(document) -> list[Fact]`.** Each fact has a name, value, unit, period, entity, and the **exact quote** it came from. Any fact whose quote is not an exact substring of the document is rejected in code.
2. **Compare three extractors:**
   - DeepSeek V4.1 Flash through the API;
   - the external decision model, asked typed questions per candidate number;
   - a rule-based number-and-unit parser as the floor.
3. **Score each against the true `facts`** of 500 documents from `data/ref/`, given only the document text:
   - precision and recall;
   - accuracy of value, unit, period and entity;
   - the rate of "right number, wrong attachment" errors.
4. **Downstream effect.** Re-run T03's code checks on 200 ref episodes with extracted facts in place of the true ones. Report how much each check's AUROC drops.
5. Cap the API spend at $8.

## run.sh

Re-score from the cache, print the comparison and downstream tables, and run the tests.

## Pass bar

- Every extracted fact is quote-anchored. A test proves rejection of an unanchored fact.
- Precision and recall per extractor, with bootstrap 95% CIs.
- The downstream table is reported per cause family.
- Spend ≤ $8.
