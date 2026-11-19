---
id: T15
title: Frozen evaluation specification and a model-neutral reader adapter
depends: T01, T03
worker: opencode-go/deepseek-v4.1-flash
variant: high
isolate: false
check: bash run.sh
timeout_min: 120
max_rounds: 4
---

# T15. One scoring sheet and one adapter for every lane

Read `research/system_one/POLICY.md`, `docs/vision/lab/COMBOS.md` (sections 0, 3 and 4), `og_s1/schema.py` and `work/T03/REPORT.md` first. Your task folder is `research/system_one/work/T15/`. Code goes in `og_s1/eval/` and `og_s1/readers/base.py`.

**Isolation rule:** do not open `work/T02*`, `work/T06` or `data/heldout*`. Build and test everything on `data/ref/`. T07 later points the same code at the unseen sets.

## Why

Every lane (code-only, encoders, decoder probes, decision models, judges) must be scored on **identical** inputs, labels and metrics. Otherwise a difference in prompt, schema or data difficulty will look like a difference in intelligence.

## Build

1. **Case extraction.** `cases(episode) -> list[Case]`, read from `model_view_at` only. A Case holds:
   - the action;
   - its claims, each with quoted span, cited source text and the source's facts;
   - the notes it cites;
   - its trust and provenance fields.

   It is the one input every reader receives.

   Every label carries a `truth_type`:
   - `formal`: decidable by rules;
   - `evidential`: needs reading the source;
   - `preference`: depends on the owner's purpose.

   Report every metric per truth type. Synthetic labels never stand in for real owner preference.
2. **Four renderings of a Case,** for experiment R:
   - raw text;
   - typed fact slots written as text;
   - claim and evidence pairs;
   - a package from the why graph.

   Each is deterministic, and its length is reported.
3. **Reader interface.** Every reader implements `score(cases, rendering) -> dict[question, prob]` for the questions in T11: `supported`, `hype`, `authority`, `addresses_reviewer`. Readers that cannot answer a question return None, never a guess.
4. **Metrics.** One function per metric in COMBOS.md section 4. Each takes scores and labels and returns the number with a bootstrap 95% CI:
   - coverage at a conformal false-allow bound of 0.05 (the primary metric);
   - AUROC and ECE;
   - top-cause accuracy and pointer accuracy;
   - false holds per 1,000;
   - escalation rate.

   Latency and GPU-seconds are recorded, never used as a filter.
5. **Shift axes.** Tag every Case with the shift axes it exercises (semantic, financial, temporal, behavioural, adversarial), where the episode's metadata allows it. Report every metric per axis.
6. **Splits.** Use group splits by company, author, agent and owner, never random rows. Add a test that fails if any group appears on both sides.
7. **Frozen.** Write `og_s1/eval/SPEC.md`, with the exact definitions, and its sha256. Every lane's report must quote that hash.

## run.sh

- Run the tests.
- Score two trivial readers (a constant, and T03's code features through a logistic model) on `data/ref/`, to show the pipeline end to end.
- Print the spec hash.

## Pass bar

- The case extraction reads only `model_view_at`. A test proves no future field reaches a Case.
- The group-split leak test passes.
- Every metric has a unit test on a hand-computed example.
- The spec hash is printed and stable across two runs.
