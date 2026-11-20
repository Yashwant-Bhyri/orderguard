# Lab status

Updated 2026-11-20T03:26:28Z by lab/run_lab.py. Do not edit by hand.

| Task | Title | Worker | Status | Round | Last verdict | Depends on |
|---|---|---|---|---|---|---|
| T01 | World v2 - schema, reference simulator, validator, author-facing SCHEMA.md | opencode-go/deepseek-v4.1-flash | passed | 5 | PASS (lead fixes) |  |
| T02a | Independent world author A | opencode-go/deepseek-v4.1-flash | needs-lead | 6 | REVISE | T01 |
| T02b | Independent world author B | opencode-go/deepseek-v4.1-flash | working | 6 | REVISE | T01 |
| T02c | Independent world author C | opencode-go/deepseek-v4.1-flash | reviewing | 2 | REVISE | T01 |
| T02d | Independent world author D (a different model family) | hermes:qwen | working | 5 | REVISE | T01 |
| T03 | Code checks v2 - provenance, span verification, drift, staleness | opencode-go/deepseek-v4.1-flash | passed | 4 | PASS (lead) | T01 |
| T04 | Model zoo and evaluation harness | opencode-go/deepseek-v4.1-flash | working | 2 | ERROR | T01, T03 |
| T05 | Bounded text channel - hype, authority language, claim support | opencode-go/deepseek-v4.1-flash | needs-lead | 4 | REVISE | T01 |
| T06 | Independent red team - adversarial cases | opencode-go/deepseek-v4.1-flash | working | 5 | REVISE | T01 |
| T07 | Integration, conformal risk control, and the verdict on C1-C6 | opencode-go/deepseek-v4.1-flash | pending | 0 |  | T02a, T02b, T02c, T02d, T03, T04, T05, T06, T11, T14, T15 |
| T08 | Real-world purpose fit - SEC N-PORT holdings against fund names (the 80% names rule) | opencode-go/deepseek-v4.1-flash | review-wait | 4 | ERROR |  |
| T09 | GPU campaign provisioning for OrderGuard on the university machine | codex-gpu | passed | 1 | PASS (lead) |  |
| T11 | GPU reader lanes S2, S4 and S3 - cut-down decoder probes, decision models as readers, and light tuning | opencode-go/deepseek-v4.1-flash | pending | 0 |  | T01, T05, T09, T15, T31 |
| T12 | Owner adaptation - partial-pooling offset vs in-context tabular learner vs conformal only (X4) | opencode-go/deepseek-v4.1-flash | pending | 0 |  | T01, T03, T04 |
| T14 | Taint propagation through the why graph, and a single-root-source cap | opencode-go/deepseek-v4.1-flash | passed | 3 | PASS | T01, T03 |
| T14b | Why-graph v2 - agent words as hypotheses, a fidelity channel, proof status, the decisive-claim gate on every action, hotspots | opencode-go/deepseek-v4.1-flash | pending | 0 |  | T14 |
| T15 | Frozen evaluation specification and a model-neutral reader adapter | opencode-go/deepseek-v4.1-flash | reviewing | 4 | ERROR | T01, T03 |
| T16 | Capability benchmark v0.1 - product-level scenarios written by a different model family | hermes:qwen | working | 5 | REVISE | T01 |
| T17 | Public data adapters and licence audit - closest-to-the-job datasets first | opencode-go/deepseek-v4.1-flash | pending | 0 |  | T15 |
| T19 | Counterfactual minimal pairs - change one factor, label by code, keep the hard ones | opencode-go/deepseek-v4.1-flash | pending | 0 |  | T01, T03, T15, T31 |
| T20 | Hosted decision-model triage - classify data, failures and findings; compare decision models on OpenRouter | opencode-go/deepseek-v4.1-flash | review-wait | 7 | ESCALATE | T01 |
| T24 | Fact extraction from prose, quote-anchored - the input real documents will not give us for free (F2, X7) | opencode-go/deepseek-v4.1-flash | pending | 0 |  | T01, T15 |
| T31 | Binding coherence - the reference world labels incoherent actions as clean; fix it as v2.1 and add a binding-error family | opencode-go/deepseek-v4.1-flash | working | 2 | ERROR | T01, T03 |

Budget used today: {"fallback_reviews": 13}. Free disk: 19.9 GB.

Checkpoints reached: world-frozen
