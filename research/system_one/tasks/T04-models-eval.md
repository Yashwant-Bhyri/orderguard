---
id: T04
title: Model zoo and evaluation harness
depends: T01, T03
worker: opencode-go/deepseek-v4.1-flash
isolate: false
check: bash run.sh
timeout_min: 120
max_rounds: 3
---

# T04. Model zoo and evaluation harness

Read `research/system_one/POLICY.md`, `SPRINT.md` and `SCHEMA.md` first. Your task folder is `research/system_one/work/T04/`. Code goes in `research/system_one/og_s1/models.py`, `og_s1/evaluate.py` and their tests.

**Isolation rule:** do not open `work/T02*`, `work/T06` or `data/heldout*`. You build the harness so that held-out data can be plugged in later by a directory path. You never look at it yourself.

## Problem

We need one honest evaluation harness that every later claim (C1, C2, C4 and C6 in SPRINT.md) runs through, and the models to compare. Train only on `data/ref/` with `shifted=False`. Tune only on a calibration split of that data. Everything else is test.

## Models

These go in `og_s1/models.py`, behind one interface: `fit(X, y, groups)`, `predict_proba(X)`, and `explain(X) -> per-feature contributions in logit space`.

1. **Logistic regression** (the baseline), with Platt calibration.
2. **The glass box:** an Explainable Boosting Machine (`interpret` package). Every feature gets a monotone-increasing constraint, since all features are "higher means riskier". After fitting, monotonise, and check again by enumerating each shape function's bins. Allow at most 10 pairwise interactions. `explain` returns the exact additive terms.
3. **Boosted trees:** sklearn HistGradientBoosting, in two versions: unconstrained, and **monotone** (`monotonic_cst=+1` on every feature, which is the tighten-only challenger to the EBM; see `docs/vision/lab/ARCHITECTURE.md` experiment X1). Both versions use with `shap` TreeExplainer contributions for `explain`. LightGBM cannot load on this Mac, because libomp is missing.
4. **Factorised noisy-AND** (from the independent GLM blueprint, `docs/vision/lab/blueprints/glm.md` section 1.3). The endorsement logit is a sum of separately fitted factors:
   - evidence credibility;
   - reasoning (does the action follow from the beliefs and thesis?);
   - objective fit;
   - owner fit;
   - an explicit unexplained residual.

   Each factor is monotone and can only lower endorsement, and each is calibrated separately. The factor values are the attribution. Compare it with the EBM on AUROC, ECE and top-cause accuracy.
4. **Optional:** TabPFN, if it installs and runs on CPU in under 10 minutes. It is a comparison only; its licence is non-commercial.

## Evaluation

`og_s1/evaluate.py`, with the CLI `python -m og_s1.evaluate --train data/ref --test <dir> [--test <dir> ...] --out <json>`.

**Metrics, per test set:**
- AUROC.
- Brier.
- ECE: 15 equal-width bins, plus adaptive bins.
- Hold rate on clean episodes at the threshold chosen on the calibration split, for a 2% hold rate.
- Recall at that threshold.
- Lead time: steps from failure onset to the first hold.

**Confidence intervals:** 95% bootstrap, resampling **episodes**, not actions (1,000 resamples). Run 5 training seeds and report the mean and spread.

**Attribution score (C2):** for every held action with y = 1, does the feature group with the largest positive contribution equal the label's cause group? The feature-to-group map comes from T03's `groups` and is fixed before any held-out data is seen. Report accuracy per cause.

**Latency:** p50 and p99 per action, for featurise plus predict, on one core.

**Bounded-influence hook (for C3 later):** `score_with_and_without(X, text_feature_idx)` returns both risk scores.

## run.sh

1. Train all models on ref (clean split), calibrate, and evaluate on the ref test split and on ref shifted.
2. Write `work/T04/results_ref.json` and a short Markdown table.
3. Show that adding a new `--test` directory requires no code change: create a tiny fake directory by copying 5 ref episodes into `work/T04/fake_test/`.
4. Run the tests: the metric functions against hand-computed toy cases (AUROC, ECE, bootstrap), monotonicity enumeration, and episode-level bootstrap grouping.

## Pass bar

- The tests pass.
- The metric implementations are checked against `sklearn` where possible.
- The EBM monotonicity check passes, for every feature and every bin.
- Results on ref and ref shifted are reported with CIs.
- No held-out paths are used.
- The latency numbers are reported.

The models' accuracy has no bar here. The harness must be correct; the claims are judged in T07.

**Leakage guard:** featurise and score only `og_s1.schema.model_view(episode)`. `meta` (which names the planted family) and `label` are for evaluation only. The reviewer checks this.

**Causal input (lead, after T01):** per-action features, readers and models must read only `og_s1.schema.model_view_at(episode, i)`, which holds just what was knowable at action *i*. The whole-episode `model_view` leaks the future: later documents, and the final status of each thesis. The reviewer checks this.
