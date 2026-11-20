# Escalation: can the 2026q1 quarter be the primary evaluation?

## Problem

The T08 report calls the 2026q1 N-PORT quarter the "frozen-rule evaluation" and the 2026q2 quarter "exploratory". The distinction matters because one classifier edge case ("Equity Plus Bond" treated as equity) was corrected after a 2026q2 sample row was seen in round 2. The report then froze `names.py` and `score.py` by SHA-256 at 2026-11-19T03:50:03Z, downloaded 2026q1 at 03:51:54Z, and scored it with `--require-freeze`. It reports 5,935 q1 series with a strong test and 175 strong flags.

## What was tried

- The rule was frozen before the q1 data was downloaded; the current `names.py` and `score.py` match the freeze manifest, and `score.py --require-freeze` passes.
- The q2 quarter is clearly labelled exploratory; q1 is the stated evaluation.
- The report measures fund overlap with `overlap.py`: 12,232 of 12,388 q1 series with a non-empty `SERIES_ID` (98.7%; 93.2% of all 13,122 q1 unique series) also appear in 2026q2.
- The report discloses that the holdout is one quarter, not a disjoint-fund split, and that a fund-specific edge case appearing in both quarters would not be caught. It still says "the holdout tests whether that general rule generalises".

## The gray area

The q1 data itself was not seen before the freeze, so this is not direct test-set peeking on q1 outcomes. But the classifier is name-based, and nearly every q1 fund also files in q2. The q2 sample row that prompted the fix is therefore likely a row for the same fund family that appears in q1. It is unclear whether a later quarter with 93–99% fund overlap can support an "evaluation" claim, or whether it is only a descriptive score of the same funds at a later snapshot. The task's pass bar does not actually require a holdout; the report's additional holdout claim is what is at issue.

## Question

Should the lab accept the 2026q1 quarter as the primary evaluation of the frozen classifier given that 12,232 of 12,388 identified q1 series (98.7%; 93.2% of all 13,122) also appear in the 2026q2 exploratory quarter used for the one classifier fix, or must the "evaluation" claim be dropped, or a disjoint-fund or multi-quarter holdout be required before the q1 counts are treated as an evaluation rather than a descriptive score?

Files: `work/T08/REPORT.md`, `work/T08/overlap.json`, `work/T08/holdout_freeze.json`, `work/T08/results.json`.
