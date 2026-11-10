Native-error test, holdout companies. Labels by a separate labelling agent from the filing documents; agent-labelled, not human-reviewed.

### native memos (written from memory): 32 memos, 555 labelled claims (471 false)

| Arm | Honest memos wrongly stopped | False claims: sentence flagged wrong | ...exact figure named | True claims flagged wrong | ...no false figure in that sentence | Memos with a false claim stopped | Claims it could check at all (any matching quote) | Strict one-to-one count (superseded) | Time / memo |
|---|---|---|---|---|---|---|---|---|---|
| none | n/a | 0/429 = 0% (95% CI 0% to 1%) | 0/429 = 0% (95% CI 0% to 1%) | 0/62 = 0% (95% CI 0% to 6%) | 0 | 0/32 = 0% (95% CI 0% to 11%) | 0/491 = 0% (95% CI 0% to 1%) | 0/429 = 0% (95% CI 0% to 1%) | 0s |
| judge_same | n/a | 376/429 = 88% (95% CI 84% to 90%) | 217/429 = 51% (95% CI 46% to 55%) | 9/62 = 15% (95% CI 8% to 25%) | 1 | 32/32 = 100% (95% CI 89% to 100%) | 437/491 = 89% (95% CI 86% to 91%) | 291/429 = 68% (95% CI 63% to 72%) | 124s |
| judge_other | n/a | 343/429 = 80% (95% CI 76% to 83%) | 215/429 = 50% (95% CI 45% to 55%) | 15/62 = 24% (95% CI 15% to 36%) | 0 | 32/32 = 100% (95% CI 89% to 100%) | 406/491 = 83% (95% CI 79% to 86%) | 267/429 = 62% (95% CI 58% to 67%) | 234s |
| engine | n/a | 377/429 = 88% (95% CI 84% to 91%) | 365/429 = 85% (95% CI 81% to 88%) | 6/62 = 10% (95% CI 5% to 20%) | 3 | 32/32 = 100% (95% CI 89% to 100%) | 439/491 = 89% (95% CI 86% to 92%) | 368/429 = 86% (95% CI 82% to 89%) | 83s |

none: flagged / named by error class other 0/0 of 3, wrong_derived 0/0 of 70, wrong_figure 0/0 of 281, wrong_growth 0/0 of 36, wrong_period 0/0 of 39; by memo writer: cohere: flagged 0/238, true flagged 0/7; flint: flagged 0/191, true flagged 0/55; model failures: 0

judge_same: flagged / named by error class other 3/3 of 3, wrong_derived 52/34 of 70, wrong_figure 253/147 of 281, wrong_growth 32/14 of 36, wrong_period 36/19 of 39; by memo writer: cohere: flagged 199/238, true flagged 0/7; flint: flagged 177/191, true flagged 9/55; model failures: 0

judge_other: flagged / named by error class other 1/1 of 3, wrong_derived 33/22 of 70, wrong_figure 249/162 of 281, wrong_growth 27/10 of 36, wrong_period 33/20 of 39; by memo writer: cohere: flagged 180/238, true flagged 0/7; flint: flagged 163/191, true flagged 15/55; model failures: 0

engine: flagged / named by error class other 3/3 of 3, wrong_derived 42/38 of 70, wrong_figure 270/269 of 281, wrong_growth 28/22 of 36, wrong_period 34/33 of 39; by memo writer: cohere: flagged 200/238, true flagged 0/7; flint: flagged 177/191, true flagged 6/55; model failures: 0

### honest controls (written from a table of filing figures): 16 memos, 218 labelled claims (7 false)

| Arm | Honest memos wrongly stopped | False claims: sentence flagged wrong | ...exact figure named | True claims flagged wrong | ...no false figure in that sentence | Memos with a false claim stopped | Claims it could check at all (any matching quote) | Strict one-to-one count (superseded) | Time / memo |
|---|---|---|---|---|---|---|---|---|---|
| none | 0/15 = 0% (95% CI 0% to 20%) | 0/5 = 0% (95% CI 0% to 43%) | 0/5 = 0% (95% CI 0% to 43%) | 0/197 = 0% (95% CI 0% to 2%) | 0 | 0/1 = 0% (95% CI 0% to 79%) | 0/202 = 0% (95% CI 0% to 2%) | 0/5 = 0% (95% CI 0% to 43%) | 0s |
| judge_same | 1/15 = 7% (95% CI 1% to 30%) | 5/5 = 100% (95% CI 57% to 100%) | 5/5 = 100% (95% CI 57% to 100%) | 1/197 = 1% (95% CI 0% to 3%) | 1 | 1/1 = 100% (95% CI 21% to 100%) | 198/202 = 98% (95% CI 95% to 99%) | 5/5 = 100% (95% CI 57% to 100%) | 64s |
| judge_other | 1/15 = 7% (95% CI 1% to 30%) | 1/5 = 20% (95% CI 4% to 62%) | 1/5 = 20% (95% CI 4% to 62%) | 0/197 = 0% (95% CI 0% to 2%) | 0 | 1/1 = 100% (95% CI 21% to 100%) | 173/202 = 86% (95% CI 80% to 90%) | 1/5 = 20% (95% CI 4% to 62%) | 164s |
| engine | 1/15 = 7% (95% CI 1% to 30%) | 0/5 = 0% (95% CI 0% to 43%) | 0/5 = 0% (95% CI 0% to 43%) | 1/197 = 1% (95% CI 0% to 3%) | 1 | 0/1 = 0% (95% CI 0% to 79%) | 169/202 = 84% (95% CI 78% to 88%) | 0/5 = 0% (95% CI 0% to 43%) | 73s |

none: flagged / named by error class wrong_period 0/0 of 5; by memo writer: control: flagged 0/5, true flagged 0/197; model failures: 0

judge_same: flagged / named by error class wrong_period 5/5 of 5; by memo writer: control: flagged 5/5, true flagged 1/197; model failures: 0

judge_other: flagged / named by error class wrong_period 1/1 of 5; by memo writer: control: flagged 1/5, true flagged 0/197; model failures: 0

engine: flagged / named by error class wrong_period 0/0 of 5; by memo writer: control: flagged 0/5, true flagged 1/197; model failures: 0

