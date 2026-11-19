---
id: T20
title: Hosted decision-model triage - classify data, failures and findings; compare decision models on OpenRouter
depends: T01
worker: opencode-go/deepseek-v4.1-flash
variant: high
isolate: false
env_keys: OPENROUTER_API_KEY
check: bash run.sh
timeout_min: 120
max_rounds: 4
---

# T20. A triage service on hosted decision models

Read `research/system_one/POLICY.md`, `docs/vision/lab/COMBOS.md` and `work/T05/REPORT.md` (for how the external decision model is called) first. Your task folder is `research/system_one/work/T20/`. Code goes in `og_s1/triage.py`.

**Isolation rule:** do not open `work/T02*`, `work/T06`, `work/T16` or `data/heldout*`.

## Why

The lab produces thousands of generated examples, reviewer findings and failure cases. A fast, cheap typed classifier can sort them, so the lead and the workers spend attention where it matters. Hosted decision models answer typed questions in about a second, for a fraction of a cent.

## Build

1. **`triage(items, questions)`** with typed questions over:
   - generated training examples: is the label plausibly wrong? Which FinVerify category? How difficult?
   - reviewer findings in `work/*/REVIEW.md`: bug, missing evidence, leakage, or style?
   - failed cases from any evaluation: missing information in the case, or a reasoning error by the reader?
2. **Compare decision models.** List the decision-style models currently on OpenRouter. Run the external decision model and up to three alternatives on a **hand-checked set of 200 items** from `data/ref/` and from existing REVIEW.md files. Report:
   - accuracy against your hand labels;
   - cost per 1,000 items;
   - latency.
3. **Recommend one default,** and explain why. Cap the total spend at $5.

## run.sh

Re-score from the cache and print the comparison table and the recommendation.

## Pass bar

- The 200 hand labels are written down, with a sentence of reasoning for every 10th.
- Every number reproduces from the cache.
- Spend ≤ $5.
- `og_s1/triage.py` has a test using a recorded response, with no network.
