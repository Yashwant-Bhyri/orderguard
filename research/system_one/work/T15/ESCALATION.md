# Escalation: is the T15 primary metric required to be conformal?

## The problem

The T15 brief asks for "coverage at a conformal false-allow bound of 0.05" as the
primary metric (task item 4; COMBOS.md section 4 says "at a conformal bound of at
most 5% of allowed actions being ones the owner would reject"). The delivered
bench does not implement a conformal bound. It implements an empirical add-one
calibration rule: on the calibration split it chooses the largest observed
threshold whose `(bad allowed + 1) / (allowed + 1)` statistic is at most 0.05,
and reports coverage of clean test actions at that threshold. The code and
SPEC.md call this an "empirical add-one calibration bound" and explicitly say it
has no finite-sample test guarantee; REPORT.md 5.2, section 4 and section 7 say
the same. The realized test conditional false-allow rate is 0.0497 on the owner
split, 0.0574 on the unseen-episode split and 0.0553 on the company split, so
the 0.05 target is already missed on two splits.

## What was tried

The worker's REPORT.md records the choice and alternatives: an exact
Clopper-Pearson upper bound on the same conditional proportion, unconditional
conformal risk control on the bad-allowed indicator, a fixed hold-rate recall
number, and a proper conformal-risk-control quantile with a selection correction.
It argues that COMBOS asks for conditional precision (the share of allowed
actions that are bad), not P(allow | bad), and that the add-one form is
conservative and auditable. It also says a previous reviewer allowed relabelling
the metric as empirical rather than conformal; no `SOL_ADVICE.md` or other
binding ruling is present in `work/T15/`, so the current review cannot treat that
recollection as a ruling. The code's threshold selection also considers only
observed calibration scores, so it is conservative relative to the largest
feasible real-valued threshold; that is a separate REVISE item, not this
question.

## The gray area

Is an empirical, data-selected calibration rule an acceptable stand-in for the
brief's "conformal false-allow bound" when the bench's purpose is to score every
lane on identical metrics, or does the word "conformal" require a method with a
finite-sample guarantee and a correction for the threshold search? The report is
honest about the limitation and reports the overshoots, so this is a
methodology/acceptance question rather than a hidden defect. A lead ruling that
accepts the empirical rule would also need to be written down and quoted by
future lanes; otherwise each lane's report will quote a specification that says
"conformal" while the implementation says "empirical".

## One precise question

Should T15 pass with the documented empirical add-one calibration rule, or must
it implement a finite-sample conformal (e.g. Clopper-Pearson with a
selection correction, or conformal risk control on the bad-allowed indicator)
bound and re-run the headline tables before it can pass?

The concrete REVISE fixes in REVIEW.md (None/fail-closed coverage, the threshold
candidate set, the artifact-scan hole, the latency provenance and the
unit-wildcard in `_fact_matches`) are independent of this question and can be
fixed while the lead answers it.
