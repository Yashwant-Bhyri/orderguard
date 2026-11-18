---
id: T12
title: Owner adaptation - partial-pooling offset vs in-context tabular learner vs conformal only (X4)
depends: T01, T03, T04
worker: opencode-go/deepseek-v4.1-flash
variant: high
isolate: false
check: bash run.sh
timeout_min: 150
max_rounds: 3
---

# T12. Owner adaptation (experiment X4)

Read these first:

- `research/system_one/POLICY.md`;
- `docs/vision/lab/ARCHITECTURE.md`, sections 2d and 5;
- the reports of T03 and T04.

Your task folder is `research/system_one/work/T12/`.

**Isolation rule:** do not open `work/T02*`, `work/T06` or `data/heldout*`.

## Problem

Real owners differ. One tolerates momentum language. Another never wants small caps, even inside the bands. Another treats any unsigned note as a red line. System One gets only a few approve/reject decisions per owner, and they keep arriving. Which adaptation method learns an owner fastest without breaking calibration or the tighten-only rule?

## Build

1. **Simulated owners.** Write a generator for 50 owners. Each has a hidden preference function, written as code, that modifies endorsement on top of the reference label. Examples:
   - a stricter or looser view on particular causes;
   - a sector dislike;
   - tolerance of hype;
   - a size limit.

   Each owner reviews actions from `data/ref/`, and their hidden function produces the labels.
   - Hold out 10 owners whose preference *types* never appear among the 40 training owners.
   - Record everything with seeds.
2. **Methods.** Each sits on top of the T04 aggregator, using its logit as a feature:
   - (i) no adaptation;
   - (ii) a per-owner offset with partial pooling (hierarchical logistic on the logit; fit the shrinkage on the training owners);
   - (iii) an in-context tabular learner given the owner's last k = 5, 10 and 20 decisions as context. TabPFN-2.5 is a research-only comparison because of its licence; also try a commercially licensed in-context learner if one runs. Record the alternatives;
   - (iv) per-owner conformal recalibration only.
3. **Tighten-only.** Every method's output passes through `max(global_risk, adapted_risk)`, so adaptation can only add strictness. Also report the variant without that guard, to show what it costs.
4. **Report**, per method and per k:
   - AUROC and ECE on new actions of the training owners;
   - the same on the 10 held-out owner types;
   - the label count needed to reach 90% of the best AUROC;
   - the latency per decision.

   Apply the X4 kill criterion exactly as written in ARCHITECTURE.md.

## Pass bar

- The owner generator is seeded, and the held-out owner types are truly unseen.
- Every number reproduces from `run.sh`.
- The kill criterion is applied, and the verdict is stated plainly.

**Leakage guard:** featurise and score only `og_s1.schema.model_view(episode)`. `meta` (which names the planted family) and `label` are for evaluation only. The reviewer checks this.
