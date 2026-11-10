Native-error test, holdout companies. Labels by a separate labelling agent from the filing documents; agent-labelled, not human-reviewed.

### native memos (written from memory): 32 memos, 555 labelled claims (471 false)

| Arm | Honest memos wrongly stopped | False claims: sentence flagged wrong | ...exact figure named | True claims flagged wrong | ...no false figure in that sentence | Memos with a false claim stopped | Claims it could check at all (any matching quote) | Strict one-to-one count (superseded) | Time / memo |
|---|---|---|---|---|---|---|---|---|---|
| judge_same | n/a | 352/429 = 82% (95% CI 78% to 85%) | 270/429 = 63% (95% CI 58% to 67%) | 16/62 = 26% (95% CI 17% to 38%) | 3 | 32/32 = 100% (95% CI 89% to 100%) | 411/491 = 84% (95% CI 80% to 87%) | 309/429 = 72% (95% CI 68% to 76%) | 44s |
| judge_other | n/a | 347/429 = 81% (95% CI 77% to 84%) | 246/429 = 57% (95% CI 53% to 62%) | 10/62 = 16% (95% CI 9% to 27%) | 2 | 32/32 = 100% (95% CI 89% to 100%) | 408/491 = 83% (95% CI 80% to 86%) | 296/429 = 69% (95% CI 64% to 73%) | 10s |
| engine | n/a | 342/429 = 80% (95% CI 76% to 83%) | 325/429 = 76% (95% CI 71% to 80%) | 4/62 = 6% (95% CI 3% to 15%) | 1 | 32/32 = 100% (95% CI 89% to 100%) | 397/491 = 81% (95% CI 77% to 84%) | 333/429 = 78% (95% CI 73% to 81%) | 55s |

judge_same: flagged / named by error class other 1/1 of 3, wrong_derived 37/24 of 70, wrong_figure 248/203 of 281, wrong_growth 31/17 of 36, wrong_period 35/25 of 39; by memo writer: cohere: flagged 185/238, true flagged 0/7; flint: flagged 167/191, true flagged 16/55; model failures: 0

judge_other: flagged / named by error class other 1/1 of 3, wrong_derived 33/21 of 70, wrong_figure 248/189 of 281, wrong_growth 31/11 of 36, wrong_period 34/24 of 39; by memo writer: cohere: flagged 195/238, true flagged 1/7; flint: flagged 152/191, true flagged 9/55; model failures: 0

engine: flagged / named by error class other 3/3 of 3, wrong_derived 44/40 of 70, wrong_figure 237/233 of 281, wrong_growth 28/20 of 36, wrong_period 30/29 of 39; by memo writer: cohere: flagged 189/238, true flagged 0/7; flint: flagged 153/191, true flagged 4/55; model failures: 0

### honest controls (written from a table of filing figures): 16 memos, 218 labelled claims (7 false)

| Arm | Honest memos wrongly stopped | False claims: sentence flagged wrong | ...exact figure named | True claims flagged wrong | ...no false figure in that sentence | Memos with a false claim stopped | Claims it could check at all (any matching quote) | Strict one-to-one count (superseded) | Time / memo |
|---|---|---|---|---|---|---|---|---|---|
| judge_same | 1/15 = 7% (95% CI 1% to 30%) | 0/5 = 0% (95% CI 0% to 43%) | 0/5 = 0% (95% CI 0% to 43%) | 2/197 = 1% (95% CI 0% to 4%) | 2 | 0/1 = 0% (95% CI 0% to 79%) | 182/202 = 90% (95% CI 85% to 93%) | 0/5 = 0% (95% CI 0% to 43%) | 32s |
| judge_other | 1/15 = 7% (95% CI 1% to 30%) | 5/5 = 100% (95% CI 57% to 100%) | 5/5 = 100% (95% CI 57% to 100%) | 1/197 = 1% (95% CI 0% to 3%) | 1 | 1/1 = 100% (95% CI 21% to 100%) | 182/202 = 90% (95% CI 85% to 93%) | 5/5 = 100% (95% CI 57% to 100%) | 9s |
| engine | 4/15 = 27% (95% CI 11% to 52%) | 1/5 = 20% (95% CI 4% to 62%) | 1/5 = 20% (95% CI 4% to 62%) | 3/197 = 2% (95% CI 1% to 4%) | 3 | 1/1 = 100% (95% CI 21% to 100%) | 182/202 = 90% (95% CI 85% to 93%) | 1/5 = 20% (95% CI 4% to 62%) | 42s |

judge_same: flagged / named by error class wrong_period 0/0 of 5; by memo writer: control: flagged 0/5, true flagged 2/197; model failures: 0

judge_other: flagged / named by error class wrong_period 5/5 of 5; by memo writer: control: flagged 5/5, true flagged 1/197; model failures: 0

engine: flagged / named by error class wrong_period 1/1 of 5; by memo writer: control: flagged 1/5, true flagged 3/197; model failures: 0

