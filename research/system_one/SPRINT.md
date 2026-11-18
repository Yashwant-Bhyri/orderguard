# Sprint S1: prove the System One core on ground truth we did not write

Started 2026-11-19. Planned as a short burst of a few days, not weeks. The lead is Claude. Work is done by DeepSeek workers, reviewed by Codex. Policy: [POLICY.md](POLICY.md). Questions: [docs/vision/lab/QUESTIONS.md](../../docs/vision/lab/QUESTIONS.md).

## Why this sprint exists

The baseline (docs/vision/JUDGEMENT.md) scored 0.974 AUROC in distribution and 0.634 under shift. The 0.974 mostly measured how well the features matched a generator written by the same hand. Its world was also too thin to judge: evidence was only an ID, so no code could check a claim against its source.

This sprint makes the world real enough to judge. Independent authors then re-write that world, and we test whether the System One design holds on data it was never shaped around.

## The design under test

The question each layer answers:

1. **Provenance and code checks** (the harness records them, D3): does the quoted number appear in the cited document? Who wrote this note, and is it signed? Is the thesis stale? Is the book drifting from the purpose?
2. **A bounded text channel**: is this wording hype? Does this note claim authority? Does the cited document support the claim? Each answer is a feature in [0, 1] that can **only raise** risk.
3. **An additive, monotone glass-box scorer** (an Explainable Boosting Machine with monotone constraints). Its terms *are* the attribution.
4. **Conformal risk control** per action class: a stated bound on the rate of approved actions the owner would not endorse.

## Claims, and the bar each one must clear

All held-out numbers come from data the model, the features and the thresholds never saw.

| # | Claim | Pass bar |
|---|---|---|
| C1 | **It judges, not memorises.** Trained only on our reference world, it holds up on three independently written worlds | Mean AUROC ≥ 0.85 across the three authors, none below 0.75. ECE ≤ 0.10. Holds on clean episodes ≤ 2% |
| C2 | **The explanation is the model.** The largest term names the planted cause | Top-term cause accuracy ≥ 80% on flagged held-out actions, and at least as good as SHAP on boosted trees |
| C3 | **Text cannot loosen.** No adversarial text from an independent red team lowers the risk score | 0 violations across ≥ 500 red-team cases and all held-out data, plus a certificate that every shape function is monotone, found by enumeration |
| C4 | **The guarantee holds.** Conformal risk control at α = 0.05 | Rate of approved but unendorsable actions ≤ 0.05 on each held-out author, with a 95% CI |
| C5 | **Purpose fit works on real data.** The names-rule test on real SEC fund holdings | ≥ 1,000 real funds scored. ≥ 90% agreement when the reviewer checks 30 flagged funds against the filings |
| C6 | **It is fast enough to sit in the path.** | Code checks plus scorer: p99 ≤ 50 ms per thesis on a laptop CPU. Text channel: p99 ≤ 300 ms on GPU, or report the CPU number |

The authors' new failure families, which nobody has seen, are reported separately. We expect less there and say so: recall at a 2% hold rate is reported, with no bar.

If a claim misses its bar, that is a result. It gets written up as plainly as a pass.

## Tasks and order

| Task | What | Depends on | Worker |
|---|---|---|---|
| T01 | World v2: schema, reference simulator, validator, author-facing SCHEMA.md | none | DeepSeek V4 Pro |
| T08 | Real-world purpose fit: SEC N-PORT and the names rule | none | DeepSeek Flash |
| T09 | GPU campaign provisioning on the university machine | none | Codex Luna (GPU operator) |
| T02a, T02b, T02c | Independent world authors, each in an isolated folder | T01 | Kimi K3, GLM 5.3, Qwen 3.8 Max |
| T06 | Independent red team: ≥ 500 adversarial cases | T01 | MiniMax M3 |
| T03 | Code checks v2: provenance, span verification, drift, staleness | T01 | DeepSeek Flash |
| T04 | Model zoo and evaluation harness, with confidence intervals and attribution scoring | T01, T03 | DeepSeek V4 Pro |
| T05 | Bounded text channel: lexicon, NLI cross-encoder, small LM; latency | T01 | DeepSeek Flash |
| T07 | Integration, conformal risk control, final verdict on C1–C6 | all of the above | DeepSeek V4 Pro |

The lead reviews at three checkpoints:

1. after T01, which freezes the world;
2. after T02, T03 and T06;
3. after T07.
