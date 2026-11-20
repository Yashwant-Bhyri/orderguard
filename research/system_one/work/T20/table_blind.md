# T20 comparison - rule labels (blind-checked), auxiliary-hint-free model input

Ranking uses `finding_kind` only: it is the one question whose rule labels clear 0.85 agreement with both blind checks (rules shown 14/15, rules removed 14/15).  `label_ok` is descriptive and its reference is defective until T31/v2.1.  FinVerify and failure kind are descriptive negative results; difficulty is not rankable.

| Model | Finding-kind accuracy (ranking) | 95% Wilson | Label ok (descriptive) | Cost / 1k | Mean latency | Coverage |
|---|---:|---:|---:|---:|---:|---:|
| Majority-class baseline | 0.391 (n=23) | [0.222, 0.592] | 0.836 (140) | $0.000000 | n/a | - |
| Displayed-label rule | 0.391 (n=23) | [0.222, 0.592] | 0.836 (140) | $0.000000 | n/a | - |
| TypeSafe Jev 1.14 | 0.913 (n=23) | [0.732, 0.976] | 0.250 (140) | $0.224972 | 1.894 s | 1.000 |
| Cloudflare Clef Flash | 0.826 (n=23) | [0.629, 0.930] | 0.486 (140) | $0.096834 | 1.851 s | 1.000 |
| Liquid d1.2-ultra | 1.000 (n=23) | [0.857, 1.000] | 0.771 (140) | $0.200450 | 2.077 s | 1.000 |
| Perplexity Decider v1.3 (free) | 0.913 (n=23) | [0.732, 0.976] | 0.764 (140) | $0.000000 | 2.253 s | 1.000 |

Ranking metric = correct `finding_kind` answers / asked `finding_kind` questions (23 of 440); a missing or refused answer counts as wrong.  The Label ok column is descriptive: its reference drops to 22/30 once the blind reader cannot see the rules, so it is not a ranking signal.  FinVerify and failure kind are on the 60-item side-by-side table; difficulty is on a different scale.

**Recommendation:** `perplexity/pplx-decider-v1.3:free`. The best finding-kind accuracy (the only reliable question) is 1.000 (Liquid d1.2-ultra). The chosen default is `Perplexity Decider v1.3 (free)` at $0.000000 per 1,000 items and 2.253 s mean latency. The best model is +0.087 above it (95% bootstrap interval [+0.000, +0.227]), so the two are statistically indistinguishable. `Liquid d1.2-ultra` is the paid alternative with the highest finding-kind accuracy (1.000) and all-question micro 0.573, but it costs $0.200450 per 1,000 and buys no clear accuracy gain.  The ranking is 23 reviewer findings, so its interval is wide; `label_ok` is descriptive only because its reference is defective until T31/v2.1.  This is a reviewer-finding sorter, not a general label-audit gate.
