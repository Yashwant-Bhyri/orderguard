---
id: T21
title: Is the why graph enough? Separate missing information from reasoning failure
depends: T11, T15
worker: opencode-go/deepseek-v4.1-flash
variant: high
isolate: false
check: bash run.sh
timeout_min: 120
max_rounds: 3
---

# T21. Oracle-information analysis

Read `docs/vision/lab/COMBOS.md`, `work/T11/REPORT.md` and `og_s1/eval/SPEC.md` first. Your task folder is `research/system_one/work/T21/`.

**Isolation rule:** do not open `work/T02*`, `work/T06`, `work/T16` or `data/heldout*`.

For every case the best T11 reader gets wrong on the validation split, re-score it with the decisive evidence handed over explicitly: the planted cause's `cause_refs`, rendered at the top of the input.
- If it now gets the case right, the failure was **missing or buried information**. The fix is in what the harness records, or how we render it.
- If it still fails, the failure is **reasoning**. The fix is in the model or its training.

Report the split per cause family and per FinVerify category, with 10 worked examples of each kind.

## Pass bar

- Every validation miss is classified.
- The re-scoring uses the same model and heads.
- run.sh reproduces the table from the cache.
