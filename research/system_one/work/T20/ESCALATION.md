# T20 escalation: a binding report sentence that the result contradicts

## Problem

T20's binding `work/T20/SOL_ADVICE.md` (round-6 addendum, item 2) orders the report to "State plainly that no hosted decision model is shown to beat the majority baseline on any reliable question." The worker ranks only on `finding_kind`, the one question whose rule labels clear 0.85 blind agreement (14/15). On that question all four hosted models score 0.783-0.957 against a 0.391 majority baseline. The report therefore says the sentence is true for `label_ok` (best 0.743 vs 0.836) but false for `finding_kind`, and it refuses to state the blanket sentence (`work/T20/REPORT.md` line 152, judgement call 14, repeated at line 399). The measurements reproduce from `work/T20/results.json` and the two caches: spend $0.213661, nine offline tests pass, and every table and interval re-runs identically.

## What was tried

The worker implemented the addendum's other items: both blind checks side by side, `finding_kind`-only ranking, `label_ok` descriptive, FinVerify and failure kind as a 60-item side-by-side descriptive table, difficulty unranked, and no re-fetch. It recomputed the no-rules check from the raw labels: `label_ok` falls from 26/30 to 22/30, while `finding_kind` stays 14/15. It did not write the blanket sentence because the `finding_kind` result contradicts it and POLICY rule 7 forbids overclaims. I re-ran `bash work/T20/run.sh` and independently recomputed the counts; the four pass-bar items are met.

## Gray area

The addendum is binding and says it binds reviewers, so its sentence cannot simply be ignored. But the only reliable question is `finding_kind`, and there all four models beat the 0.391 majority baseline. Writing the sentence verbatim would make `REPORT.md` factually false on the only question it ranks, while keeping the report's precise per-question statement does not follow the ruling's literal wording. The sentence may have been intended only for the label stream / `label_ok`, where it is true, or written before the `finding_kind` result was final; the addendum does not say. A REVISE cannot resolve this: complying literally creates an overclaim, and keeping the precise statement violates the binding ruling. The worker's compromise (report the per-question result and explain why the blanket sentence is false) is the honest reading, but only the lead or the escalation reviewer can say whether that satisfies the ruling.

## Question

Should T20's round-6 report state the addendum's blanket sentence verbatim ("no hosted decision model is shown to beat the majority baseline on any reliable question") despite the `finding_kind` result, or is that sentence intended to apply only to `label_ok` (or is it withdrawn) in favor of the report's per-question statement: no model beats the 0.836 `label_ok` baseline, and all four beat the 0.391 `finding_kind` baseline?
