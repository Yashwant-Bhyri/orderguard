---
id: T32
title: Rescore decision-model triage on label_ok with the coherent reference world v2.1
depends: T20, T31
worker: opencode-go/deepseek-v4.1-flash
variant: high
isolate: false
env_keys: OPENROUTER_API_KEY
check: bash run.sh
timeout_min: 90
max_rounds: 3
---

# T32. Rescore `label_ok` on reference v2.1

Read `work/T20/REPORT.md`, `work/T20/SOL_ADVICE.md` (including the addendum) and `work/T31/REPORT.md`. Your folder is `research/system_one/work/T32/`.

In T20, the `label_ok` question could not be scored: 6 of the 8 blind disagreements were incoherent "clean" actions from reference v2. Rebuild T20's `label_ok` stratum (120 reference actions plus 20 flipped probes, same sampling rule and seed) from `data/ref_v21/`, and rerun the same models with T20's code. Keep a $0.25 cap. Then have the blind check rerun, with no rules shown: write `blind/items.jsonl` with family, id, source and `triage_rules` stripped, and tell the lead it is ready. Do not label it yourself.

## Pass bar
- The `label_ok` stratum is rebuilt from v2.1 by a script and reproduces from the cache.
- Every model's accuracy has a Wilson interval and is shown against the majority baseline, with the v2 result beside it.
- Spend is at most $0.25 in total.
- The blind items carry no rules and no identifying fields. A test checks this.
