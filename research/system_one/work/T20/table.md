# T20 comparison - rule labels (blind-checked)

Ranking uses `finding_kind` only: it is the one question whose rule labels clear 0.85 agreement with both blind checks (rules shown 14/15, rules removed 14/15).  `label_ok` is descriptive and its reference is defective until T31/v2.1.  FinVerify and failure kind are descriptive negative results; difficulty is not rankable.

| Model | Finding-kind accuracy (ranking) | 95% Wilson | Label ok (descriptive) | Cost / 1k | Mean latency | Coverage |
|---|---:|---:|---:|---:|---:|---:|
| Majority-class baseline | 0.391 (n=23) | [0.222, 0.592] | 0.836 (140) | $0.000000 | n/a | - |
| Displayed-label rule | 0.391 (n=23) | [0.222, 0.592] | 0.836 (140) | $0.000000 | n/a | - |
| TypeSafe Jev 1.14 | 0.957 (n=23) | [0.790, 0.992] | 0.457 (140) | $0.236177 | 1.418 s | 1.000 |
| Cloudflare Clef Flash | 0.783 (n=23) | [0.581, 0.903] | 0.379 (140) | $0.098794 | 1.539 s | 1.000 |
| Liquid d1.2-ultra | 0.957 (n=23) | [0.790, 0.992] | 0.650 (140) | $0.211079 | 1.594 s | 1.000 |
| Perplexity Decider v1.3 (free) | 0.913 (n=23) | [0.732, 0.976] | 0.743 (140) | $0.000000 | 1.623 s | 1.000 |

Ranking metric = correct `finding_kind` answers / asked `finding_kind` questions (23 of 440); a missing or refused answer counts as wrong.  The Label ok column is descriptive: its reference drops to 22/30 once the blind reader cannot see the rules, so it is not a ranking signal.  FinVerify and failure kind are on the 60-item side-by-side table; difficulty is on a different scale.

**Recommendation:** `perplexity/pplx-decider-v1.3:free`. The best finding-kind accuracy (the only reliable question) is 0.957 (TypeSafe Jev 1.14). The chosen default is `Perplexity Decider v1.3 (free)` at $0.000000 per 1,000 items and 1.623 s mean latency. The best model is +0.043 above it (95% bootstrap interval [+0.000, +0.150]), so the two are statistically indistinguishable. `Liquid d1.2-ultra` is the paid alternative with the highest finding-kind accuracy (0.957) and all-question micro 0.566, but it costs $0.211079 per 1,000 and buys no clear accuracy gain.  The ranking is 23 reviewer findings, so its interval is wide; `label_ok` is descriptive only because its reference is defective until T31/v2.1.  This is a reviewer-finding sorter, not a general label-audit gate.
