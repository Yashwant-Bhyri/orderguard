Native-error test, dev companies. Labels by a separate labelling agent from the filing documents; agent-labelled, not human-reviewed.

### native memos (written from memory): 18 memos, 325 labelled claims (272 false)

| Arm | Honest memos wrongly stopped | False claims: sentence flagged wrong | ...exact figure named | True claims flagged wrong | ...no false figure in that sentence | Memos with a false claim stopped | Claims it could check at all (any matching quote) | Strict one-to-one count (superseded) | Time / memo |
|---|---|---|---|---|---|---|---|---|---|
| none | n/a | 0/240 = 0% (95% CI 0% to 2%) | 0/240 = 0% (95% CI 0% to 2%) | 0/44 = 0% (95% CI 0% to 8%) | 0 | 0/18 = 0% (95% CI 0% to 18%) | 0/284 = 0% (95% CI 0% to 1%) | 0/240 = 0% (95% CI 0% to 2%) | 0s |
| judge_same | n/a | 230/240 = 96% (95% CI 93% to 98%) | 113/240 = 47% (95% CI 41% to 53%) | 19/44 = 43% (95% CI 30% to 58%) | 4 | 18/18 = 100% (95% CI 82% to 100%) | 274/284 = 96% (95% CI 94% to 98%) | 164/240 = 68% (95% CI 62% to 74%) | 80s |
| judge_other | n/a | 215/240 = 90% (95% CI 85% to 93%) | 141/240 = 59% (95% CI 52% to 65%) | 17/44 = 39% (95% CI 26% to 53%) | 5 | 18/18 = 100% (95% CI 82% to 100%) | 260/284 = 92% (95% CI 88% to 94%) | 177/240 = 74% (95% CI 68% to 79%) | 178s |
| engine | n/a | 223/240 = 93% (95% CI 89% to 96%) | 213/240 = 89% (95% CI 84% to 92%) | 5/44 = 11% (95% CI 5% to 24%) | 1 | 18/18 = 100% (95% CI 82% to 100%) | 264/284 = 93% (95% CI 89% to 95%) | 215/240 = 90% (95% CI 85% to 93%) | 67s |

none: flagged / named by error class other 0/0 of 2, wrong_derived 0/0 of 39, wrong_figure 0/0 of 161, wrong_growth 0/0 of 23, wrong_period 0/0 of 15; by memo writer: cohere: flagged 0/139, true flagged 0/7; flint: flagged 0/101, true flagged 0/37; model failures: 0

judge_same: flagged / named by error class other 2/1 of 2, wrong_derived 34/23 of 39, wrong_figure 157/75 of 161, wrong_growth 22/4 of 23, wrong_period 15/10 of 15; by memo writer: cohere: flagged 132/139, true flagged 1/7; flint: flagged 98/101, true flagged 18/37; model failures: 0

judge_other: flagged / named by error class other 2/2 of 2, wrong_derived 28/22 of 39, wrong_figure 150/103 of 161, wrong_growth 22/6 of 23, wrong_period 13/8 of 15; by memo writer: cohere: flagged 121/139, true flagged 1/7; flint: flagged 94/101, true flagged 16/37; model failures: 0

engine: flagged / named by error class other 2/2 of 2, wrong_derived 31/31 of 39, wrong_figure 153/153 of 161, wrong_growth 22/12 of 23, wrong_period 15/15 of 15; by memo writer: cohere: flagged 128/139, true flagged 0/7; flint: flagged 95/101, true flagged 5/37; model failures: 0

### honest controls (written from a table of filing figures): 9 memos, 132 labelled claims (4 false)

| Arm | Honest memos wrongly stopped | False claims: sentence flagged wrong | ...exact figure named | True claims flagged wrong | ...no false figure in that sentence | Memos with a false claim stopped | Claims it could check at all (any matching quote) | Strict one-to-one count (superseded) | Time / memo |
|---|---|---|---|---|---|---|---|---|---|
| none | 0/6 = 0% (95% CI 0% to 39%) | 0/3 = 0% (95% CI 0% to 56%) | 0/3 = 0% (95% CI 0% to 56%) | 0/107 = 0% (95% CI 0% to 3%) | 0 | 0/3 = 0% (95% CI 0% to 56%) | 0/110 = 0% (95% CI 0% to 3%) | 0/3 = 0% (95% CI 0% to 56%) | 0s |
| judge_same | 1/6 = 17% (95% CI 3% to 56%) | 0/3 = 0% (95% CI 0% to 56%) | 0/3 = 0% (95% CI 0% to 56%) | 2/107 = 2% (95% CI 1% to 7%) | 2 | 3/3 = 100% (95% CI 44% to 100%) | 105/110 = 95% (95% CI 90% to 98%) | 0/3 = 0% (95% CI 0% to 56%) | 40s |
| judge_other | 1/6 = 17% (95% CI 3% to 56%) | 0/3 = 0% (95% CI 0% to 56%) | 0/3 = 0% (95% CI 0% to 56%) | 0/107 = 0% (95% CI 0% to 3%) | 0 | 1/3 = 33% (95% CI 6% to 79%) | 89/110 = 81% (95% CI 73% to 87%) | 0/3 = 0% (95% CI 0% to 56%) | 42s |
| engine | 0/6 = 0% (95% CI 0% to 39%) | 0/3 = 0% (95% CI 0% to 56%) | 0/3 = 0% (95% CI 0% to 56%) | 0/107 = 0% (95% CI 0% to 3%) | 0 | 1/3 = 33% (95% CI 6% to 79%) | 92/110 = 84% (95% CI 76% to 89%) | 0/3 = 0% (95% CI 0% to 56%) | 52s |

none: flagged / named by error class wrong_growth 0/0 of 3; by memo writer: control: flagged 0/3, true flagged 0/107; model failures: 0

judge_same: flagged / named by error class wrong_growth 0/0 of 3; by memo writer: control: flagged 0/3, true flagged 2/107; model failures: 0

judge_other: flagged / named by error class wrong_growth 0/0 of 3; by memo writer: control: flagged 0/3, true flagged 0/107; model failures: 0

engine: flagged / named by error class wrong_growth 0/0 of 3; by memo writer: control: flagged 0/3, true flagged 0/107; model failures: 0

