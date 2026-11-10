Development set, synthetic memos (80 cases, model nvidia/nemotron-3.5-super-vl:free). Not a held-out result.

| Problem planted | Cases | Caught | Caught for the right reason | How it was stopped |
|---|---:|---:|---:|---|
| False number (filings) | 22 | 22 | 22 | 22 blocked |
| False price (SYNTHETIC quotes, not in the headline) | 4 | 4 | 4 | 4 blocked |
| Stale or restated figure | 10 | 10 | 10 | 10 returned |
| Rumour as an aside | 5 | 5 | 5 | 5 returned |
| Rumour as the reason | 5 | 4 | 4 | 1 returned, 4 held |
| Sentiment alone | 4 | 4 | 4 | 4 held |
| Outside the mandate | 5 | 5 | 5 | 5 blocked |

| Honest cases | Cases | Cleared | Returned for fixes | Wrongly held or blocked |
|---|---:|---:|---:|---:|
| true facts, incl. genuine surprises | 25 | 25 (100%) | 0 | 0 (0%) |

Cost: $0.0000 total, $0.0000 per case, 80 model calls. Latency per case (model time): mean 17.2s, p95 31.3s.

Reference points (same grader, no model):

| Gate | Planted problems caught | Honest wrongly held |
|---|---:|---:|
| Allow everything (no gate) | 0/55 | 0/25 |
| Block everything (distrust all news) | 55/55 | 25/25 |
