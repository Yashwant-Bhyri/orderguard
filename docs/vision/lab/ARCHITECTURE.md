# What kind of model is System One? (lead's architecture study)

Written by the lab lead on 2026-11-19. It replaces the delegated T10, at the founder's direction: the research and architecture thinking stay with the lead. DeepSeek (V4 Flash) runs the experiments this study prescribes, and Codex reviews them. This document ends in **D10 (provisional)** and in the experiments that will confirm it or overturn it.

## 1. Start from the problem, not from a model

"System One" has been talked about as one model. It is really **six different computations**. They have different natures, so the rational tool differs for each. A single model for all six, whether an LLM fine-tune, a classifier or a decision model, is the paradigm trap the founder warned about.

| # | Computation | Its nature | Examples |
|---|---|---|---|
| a | **Structural verification** | Exact. The answer is in the record | The quoted span is in the cited document; the value matches the fact; the note is signed by the owner; the book is outside its band; the CUSUM has fired; the thesis invalidation has triggered |
| b | **Semantic reading** of short texts | Language understanding, open-ended wording | Is this claim hype? Does this note *assert* a permission or address a reviewer? Does the cited document *support* the claim? |
| c | **Aggregation** into one probability that the owner would not endorse | Low-dimensional, calibrated, must be monotone (tighten-only) | Many signals in, one number out, plus which signal carried it |
| d | **Owner adaptation** | Few labels per owner, arriving continuously | This owner tolerates momentum language; that owner never wants small caps |
| e | **Novelty**: failures nobody wrote a check for | Open-ended; needs general judgement | The authors' invented failure families |
| f | **Purpose attribution**: weights over the evidence, notes and claims | Bookkeeping over the why-graph | Which nodes carried the risk |

Two consequences follow:

- **a and f need no learning at all.** They are code over the recorded graph, and that code is provable.
- **The open questions are b, c, d and e.** Each has its own candidates.

## 2. Candidates for each open computation, challenged

### b. Semantic reading: which reader understands wording it has never seen, and resists text built to fool it?

| Candidate | Why it could win | Why it could lose |
|---|---|---|
| NLI cross-encoder (DeBERTa-v3-large, trained on MNLI, FEVER and ANLI) for *support* | Entailment is exactly the support question. ANLI training is adversarially hardened. Runs in milliseconds | Trained on general text, not finance. Hype and authority are not entailment |
| **Purpose-built prompt-injection classifiers** (for example Meta Prompt Guard 2 at 86M and 22M, or ProtectAI's DeBERTa injection classifier) for *authority* | "A note that addresses the reviewer or asserts a permission" is close to what they were built to catch. Tiny and fast | Tuned to jailbreak style, not to "the owner said it's fine" phrasing |
| Hosted decision model (`typesafe/jev-1.14`) answering one yes/no question per sub-question | Built for typed probabilities. About 1 s and $0.00002 a call. Already correct on our authority-spoof probe | External dependency. It reads attacker text, so its own robustness is unknown |
| **Linear probes on a strong open model's hidden states** (one forward pass, no generation) | A capable model's representations transfer across wording better than a small encoder's. Calibrated by construction (logistic). About 50 ms on an A6000. This is "weight-space" leverage without training the model | Needs the GPU. Probes can latch onto surface features if the training text is narrow |
| Small generative judge scored by logprob | Flexible | Slower, and generative judges are easier to steer with adversarial text than a probe on the same model |
| Fine-tuned small encoder | Fast and specialised | Only worth it if every off-the-shelf reader fails on held-out wording. **It must earn its place by evidence** |

**How the reasoning moved:**

- **v1** "Use one NLI model for everything."
- **Challenge:** hype and authority are not entailment, and injection classifiers exist for authority.
- **v2** "Use a specialist reader per sub-question."
- **Challenge:** specialists generalise worst to new wording, and that is our exact failure (0.97 fell to 0.63).
- **v3** "Run a reader tournament on wording written by other hands. The winner per sub-question goes in. If two are close, the faster one wins."

Probes on a strong model's hidden states are my prior favourite for robustness, but it is a prior to test, not a choice.

### c. Aggregation

| Candidate | For | Against |
|---|---|---|
| Monotone Explainable Boosting Machine (EBM) | Additive, so attribution is the model. Monotonicity provable by enumerating each term | In T10's first experiment it lost calibration under shift (ECE 0.08 against 0.003) |
| **Monotone gradient-boosted trees** (sklearn `monotonic_cst`) with TreeSHAP | Monotone by construction, since every split respects the constraint. TreeSHAP gives exact Shapley values for trees. It was best under shift in that same experiment | Attribution is exact Shapley rather than additive terms. Pairwise effects are less legible |
| Logistic regression | Simplest. Monotone through the signs of its weights | It misses interactions, such as an unsigned note *and* an out-of-band action |

**How the reasoning moved:**

- **v1** "EBM: the explanation is the model."
- **Challenge:** monotone boosted trees give the same tighten-only guarantee, exact attributions, and better calibration under shift.
- **v2** "The aggregator is whichever of the two wins on the *held-out* worlds."

"The explanation is the model" survives either way, because both give exact attributions. What changes is the form of the attribution.

### d. Owner adaptation

| Candidate | For | Against |
|---|---|---|
| A per-owner offset with partial pooling (hierarchical logistic on the aggregator's logit) | Few parameters, stable with 5 labels, monotone | It only shifts the threshold. It cannot learn "this owner cares about X" |
| **In-context tabular learner** (TabPFN-2.5, TabICL or LimiX), with the owner's past decisions as the context | It learns preference *shape* from about 10 examples, with no training and no retraining as labels arrive | Licence (TabPFN weights are non-commercial). Calibration under shift unproven |
| Per-owner conformal recalibration only | It keeps the stated guarantee per owner | No learning of preferences |

This is a real fork, decided by experiment X4.

### e. Novelty

| Candidate | For | Against |
|---|---|---|
| **Escalation**: when the cheap stack is unsure (the conformal set holds both answers) or the action is unusual, ask a stronger end-to-end judge, whose answer can only tighten | The general intelligence is spent only where needed | Latency and cost on the escalated share |
| Always-on general judge | Simple | Spends a strong model on the 95% of actions that are obvious |
| No novelty handling | Cheapest | It misses exactly what we cannot anticipate |

## 3. Three architectures

- **A. Local verified stack.** Code checks, then the best local readers (encoders and probes), then the monotone aggregator, then conformal risk control. Everything runs on our hardware, and every stage is provable. **Main risk:** novel failures.
- **B. Decision-model reader stack.** The same as A, but the hosted decision model answers the semantic sub-questions. **Main risk:** dependency on an outside service, and its unknown robustness to adversarial text. Its output can only raise risk, so a fooled reader causes a hold, never a breach.
- **C. Cascade.** A (or B) is always on. Uncertain or unusual actions escalate to a strong end-to-end judge that can only tighten. Owner adaptation sits on top. **Main risk:** the escalation rate. If more than 15% of actions escalate, the cheap stack is not doing its job.

**My provisional pick is C, built on whichever of A or B wins the reader tournament.** This is D10, provisional.

What would make me switch:
- **To A alone:** escalation adds less than 0.1 recall on the novel families.
- **To B as the base:** the decision model beats every local reader on held-out wording by more than 0.05 AUROC.
- **To fine-tuning a reader:** every off-the-shelf reader is more than 0.10 AUROC below the frontier judge on held-out wording. That would be the first point at which training is the rational move.

## 4. What is deliberately not on the plan, and why

- **Fine-tuning or RL on an LLM.** No computation above needs it yet. It becomes rational only under the switch condition just above.
- **Training anything from scratch.** Never needed here.
- **Text-to-LoRA and hypernetwork adapters.** They are demo-stage for classification. Revisit them if per-owner adaptation needs more than X4's candidates.
- **Graph neural networks over the why-graph.** The graph's useful signals are already exact code features, and nothing published shows a gain.
- **Sparse autoencoders as the debugging method.** Plain probes match them in published evaluations. They may be used later to *explain* a probe.

## 5. The experiments that decide it

DeepSeek V4 Flash runs these. Codex Luna reviews them. Each kill criterion is fixed now.

| # | Question | Where | Kill criterion |
|---|---|---|---|
| X1 | Aggregator: monotone EBM against monotone boosted trees with TreeSHAP against logistic | T07, on held-out worlds | Drop the EBM if the trees beat it by more than 0.02 AUROC or 0.03 ECE on held-out data |
| X2 | Reader tournament, per sub-question (hype, authority, support): lexicon; NLI cross-encoder; injection classifiers; small embedding with a probe; decision model; hidden-state probes on strong open models; logprob judge | T05 for the CPU and API readers; T11 for the GPU readers. Scored on text written by other hands, plus the red team | Drop a reader more than 0.05 AUROC below the best on held-out wording, unless it is at least 10× faster |
| X3 | Is the cascade worth it? | T07 | Drop the cascade if it escalates more than 15% of actions or adds less than 0.10 recall on the novel families at a 2% hold rate |
| X4 | Owner adaptation: offset with partial pooling against an in-context tabular learner (k = 5, 10, 20) against conformal only. Uses 50 simulated owners with hidden preferences | T12 | Drop the in-context learner if it does not beat the offset by 0.03 AUROC at k = 10 |
| X5 | How close to frontier judgement is each cheap reader? Measured as agreement with a frontier judge and with the true labels, on 500 sampled actions | T11 | Used to set the escalation threshold, not to kill anything |

## 6. Model choice for the GPU readers (X2 and X5), reasoned rather than defaulted

What matters for a probe reader:

1. the quality of the representation for reading comprehension and instruction semantics, per GPU-second;
2. fitting one A6000 in bf16 with batching (up to about 20B parameters);
3. a licence that allows commercial use;
4. interpretability tooling, for debugging the probe later.

The shortlist covers three points on the size–quality curve, not one favourite model:

- **a mid-size model with the best open interpretability tooling** (for example Gemma 3 12B, which has Gemma Scope 2);
- **the strongest open model that fits one card in bf16** (for example a 14B-class reasoning model);
- **a small model** (about 1–2B), to measure how much size buys.

T11 confirms the current best member of each class from primary sources before downloading. It may swap any of them, and must record why.
