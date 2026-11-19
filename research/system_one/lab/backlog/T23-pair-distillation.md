---
id: T23
title: Train the reader heads on counterfactual pairs, with a hard-case teacher
depends: T11, T19
worker: opencode-go/deepseek-v4.1-flash
variant: max
isolate: false
env_keys: OPENROUTER_API_KEY
check: bash run.sh
timeout_min: 240
max_rounds: 3
---

# T23. Counterfactual pair training

Read `docs/vision/lab/COMBOS.md`, `work/T11/REPORT.md`, `work/T19/REPORT.md` and `work/T09/HOWTO.md` first. Your task folder is `research/system_one/work/T23/`. Use at most two GPUs.

**Isolation rule:** do not open `work/T02*`, `work/T06`, `work/T16` or `data/heldout*`.

On T11's best model and layer:
1. Train the heads on T19's pairs, with a pairwise loss: the changed member must score as riskier than its fine counterpart, and invariance pairs must score the same.
2. Compare against heads trained on the same number of unpaired examples.
3. Then add the teacher-labelled hard pairs, and measure whether they help or hurt.

Report every result on validation, with learning curves at 250, 1,000, 3,000 and all pairs.

## Pass bar

- The same validation split and the same metrics as T11.
- Learning curves are reported.
- Kill rule: if pairs do not beat unpaired data by ≥ 0.02 AUROC on validation, say so plainly.
