# Training a calibrated decision model on one A6000: scan notes

Scout date: 2026-11-19. Scope: post-training and calibration recipes that fit on one 48 GB NVIDIA A6000, with jobs network-isolated. This is a collection of options, not a decision.

Tags: **EVIDENCE** = paper, benchmark or code. **CLAIM** = blog, tweet, vendor or marketing. **ESTIMATE** = my own back-of-envelope number, not measured on an A6000; treat as a planning guess until benchmarked.

Search coverage note: the web search tool did not return X/Twitter posts, so the practitioner section relies on blogs and arXiv write-ups. Active learning and selective labelling got no dedicated search and are covered only from general knowledge, marked as such.

---

## 1. Headline findings

1. **Binary correctness RL tends to hurt calibration, especially out of domain.** RLCR (Damani et al.) adds a Brier-score term to a correctness reward and reports better calibration than RLVR, including out of domain. [EVIDENCE: arXiv 2507.16806, ICLR 2026 poster, code at rl-calibration.github.io]. A January 2026 paper (Yaldiz et al., arXiv 2601.13284) reports that RLVR makes models extremely overconfident while SFT gives better calibration even under shift, and proposes a calibration-aware RL variant. [EVIDENCE: arXiv 2601.13284]. The implication for us is that a plain RL stage is a risk to the calibration we are paying for, so calibration must be part of the objective, or RL must come after SFT and be checked against ECE on a shifted split.

2. **The Brier reward is the cheapest published calibration signal.** Three independent 2025–2026 papers use it: RLCR, a behavioural-calibration RL paper from ByteDance Seed and CMU (arXiv 2512.19920), and ConfTuner, which uses a tokenised Brier loss in plain SFT with no ground-truth confidence labels (arXiv 2508.18847). [EVIDENCE for all three; the 2512.19920 reward decomposition is stated in the paper as correctness reward minus Brier score.]

3. **Our 0.21 out-of-domain number is not comparable to the literature.** A secondary review summary gives RLCR an ECE of 0.21 on HotpotQA, which is coincidentally our 0.21 figure. [CLAIM: second-hand summary of arXiv 2507.16806; not verified in the paper.] Different tasks, different metrics. Do not cite it as a benchmark.

4. **Small models are fragile under GRPO.** A September 2026 paper on GRPO dynamics for 1.5B–7B models reports mode collapse, catastrophic forgetting and naive reward hacking as the main failure modes, and releases its pipeline. [EVIDENCE: arXiv 2609.39321, abstract read via WebFetch; full recipe not checked.]

5. **Simplest good path is probably SFT with a proper scoring loss, then a small KTO or DPO stage on approve/reject logs.** Multiple sources agree on LoRA as the default. Whether RL adds value over this is open for our task.

6. **No verified A6000 throughput numbers exist in what I found.** Every tokens-per-second figure for the A6000 is an estimate from me or a third-party blog that did not name the GPU. We need our own benchmark run before scheduling anything.

---

## 2. What fits on one 48 GB card

Memory numbers below are ESTIMATES from first principles and from secondary sources. The only sourced anchors are the Hyperstack tutorial (Qwen3-8B QLoRA needs at least 16 GB at short context; 48 GB gives headroom at max_seq_length 2048) [CLAIM] and a hobbyist Qwen3 LoRA run (8B with 4-bit base at 2048 context peaked at 15.95 GB; 4B in bf16 at 13.37 GB) [CLAIM, GPU not named].

| Method | 1.5B | 4B | 8B |
|---|---|---|---|
| Full fine-tune, bf16 + AdamW | fits with checkpointing (~24 GB states) | borderline; needs 8-bit optimiser (ESTIMATE) | does not fit (ESTIMATE, 60–80 GB per secondary source) |
| Full fine-tune + 8-bit Adam + checkpointing | fits | probably fits | does not fit |
| LoRA, bf16 base | fits easily | fits easily | fits (~16 GB base + activations) |
| QLoRA, 4-bit base | fits easily | fits easily | fits, most headroom for long context |
| DoRA | fits; ~4% more memory and noticeably slower than LoRA, depending on PEFT version [CLAIM: PEFT docs] | same | same |
| GRPO with vLLM colocated | fits | fits with care on rollout length | fits with QLoRA and short completions; tight (ESTIMATE) |

Practical conclusions:
- Full fine-tuning above about 4B is off the table on this card without tricks we have not validated.
- LoRA or QLoRA is the default. For a classifier-style output (probability plus short reasoning), LoRA rank 8–16 is what the sources recommend. [CLAIM: 2026 guides; the June 2026 merchant-extraction preprint found rank 8 within 0.2 points of rank 32 on an 8B model, arXiv 2606.08051, EVIDENCE for that single task.]
- GRPO on 8B is the most likely to run out of memory, because rollouts consume KV cache. Unsloth's memory-efficient RL docs say two generations per prompt is the minimum for GRPO to work and describe a shared vLLM standby mode that roughly doubles usable context in their own tests on H100 [CLAIM: vendor docs].

---

## 3. Post-training methods

### 3.1 SFT, LoRA, QLoRA, DoRA
- **LoRA.** Default in 2026 guides and in the team blog that says it uses LoRA exclusively and that Llama 3.x 8B is still the most versatile base. [CLAIM]
- **QLoRA.** Lower memory with small quality cost on most benchmarks. Used in the 2026 spam-detection comparison of Gemma 3, Qwen 3 and Llama 3.2. [EVIDENCE for the existence of the paper; results not retrieved.]
- **DoRA.** Original paper reports gains over LoRA on commonsense tasks on LLaMA-family models, with reported gains up to 14.4% on eight tasks. [EVIDENCE: arXiv 2402.09353, 2024; not re-verified.] Answer.AI's QDoRA results on Llama 3 8B were competitive with QLoRA and full fine-tuning, but without hyperparameter tuning. [EVIDENCE: answer.ai blog, April 2024; old.] No 2026 head-to-head found.
- **Fit to our problem.** Nothing I found tests DoRA on calibration. Keep DoRA as a later ablation, not a first experiment.

### 3.2 Calibration-aware SFT
- **ConfTuner** (arXiv 2508.18847). Tokenised Brier-score loss in SFT, so the model writes a verbal confidence token sequence without ground-truth confidence labels. [EVIDENCE: paper; single-GPU fit likely; the paper's reported gains not re-checked.] This is the cheapest path to a calibrated verbal output.
- **Self-consistency distillation** (arXiv 2506.03723, Jang et al.). Fine-tune on confidence labels derived from answer agreement across samples. [EVIDENCE.] Useful when we lack ground truth for some decisions.
- **CaTS** (ICLR 2026, arXiv listed via search). Distils self-consistency confidence into one forward pass. [CLAIM: abstract only.]
- **Small-model caveat.** A April 2026 preprint on Gemma 3 4B reports degenerate verbal confidence (ceiling above 95%) under minimal elicitation, and a pre-registered negative result before a post-hoc rescue. [EVIDENCE: preprint, single model; treat as a warning, not a verdict.] This matters for us: check the verbal confidence distribution before trusting ECE numbers.

### 3.3 RL post-training
- **GRPO.** Standard group-relative baseline. Public small-model results mostly on math. Reward design matters more than the variant: one practitioner write-up reports that their reward code was about 250 lines against the one-liners in most public write-ups, and that a learning rate that is too high with too weak a KL anchor drifted a 14B model into a reward-hacking mode that scored well and was useless. [CLAIM: blog.]
- **DAPO, Dr. GRPO, MC-GRPO.** A 2026 paper (arXiv 2601.09085) compares GRPO, Dr. GRPO and DAPO across 1.5B, 7B and 8B models on five math benchmarks. [EVIDENCE.] MC-GRPO (arXiv 2601.22582, January 2026) targets small rollout budgets of 2–4 rollouts, which fits our memory, using Qwen3-1.7B on GSM8K. [EVIDENCE.] A later paper (arXiv 2607.00152, the ID suggests July 2026) argues that GRPO, Dr. GRPO and DAPO differ only in how they normalise by the group standard deviation. [EVIDENCE: theory paper, not an empirical ranking.]
- **RLVR.** Verifiable reward RL. Our labels are not verifiable in the usual sense (we score endorsement), so RLVR fits only if we can verify outcomes against realised portfolio results. Possible but needs thought.
- **RL with proper scoring rewards.** RLCR (above). A "behaviourally calibrated" RL paper derives the reward from a risk-threshold prior and shows that under a uniform prior the reward is correctness minus Brier. [EVIDENCE: arXiv 2512.19920.] Confidence-aware scaling (arXiv 2607.01612, July 2026) reports gains over majority vote on in-domain and out-of-domain sets while cutting inference budget up to 12x. [CLAIM from abstract; not verified.]
- **Calibration-aware RL alternative.** RLCM (arXiv 2604.23333, April 2026) adds a margin-based process reward and reports better out-of-domain calibration while holding accuracy. [EVIDENCE: abstract.] COREA (arXiv 2603.03752, March 2026) mixes verifiable reward and a confidence reward in a small-large cascade. [EVIDENCE: abstract.]
- **Study on small-model RL.** A 1.5B distilled model under tight compute reportedly went from 63% to 80% on AMC23 with 7,000 samples at about $42 of compute. [CLAIM: blog.] Useful as a cost reference.
- **Ordering.** A 2026 RL guide suggests SFT first so RL has a learning signal, then GRPO. [CLAIM.] Consistent with the Yaldiz result that SFT alone can be better calibrated than RLVR.

### 3.4 Calibration-specific tools (non-RL)
- **Temperature scaling.** Strong baseline in earlier work; repeatedly noted to fail under distribution shift, because the scale is fit on in-domain validation. [CLAIM: practitioner sources; the 2026 bilevel-optimisation preprint, arXiv 2608.07419, reports results I did not verify.] Requires logits, which API models do not expose. We do have logits, so it is cheap for us.
- **Adaptive temperature scaling** (arXiv 2409.19817). Per-token temperature for RLHF-induced calibration shift, with no reported accuracy loss on the benchmarks tested. [EVIDENCE, 2024.]
- **Focal loss and label smoothing.** I did not find a 2025–2026 study of either for LLM calibration under shift. Both are classical. Label smoothing is known to soften probabilities, which can help or hurt ECE depending on the base calibration. Treat as untested for us.
- **Calibration under shift, general.** UQ4CT (arXiv 2410.06431, v2 January 2025) reports ECE reductions over 25% with functional-level uncertainty and shift gains on commonsense and domain QA. [EVIDENCE; numbers from abstract.] EUA-Cal (arXiv 2610.12048) trains Llama3-8B on ARC-E and tests shift on ARC-C, SciQ and CSQA, with the lowest AECE on all three shifted sets. [EVIDENCE: abstract.] A Stiefel-manifold Bayesian PEFT paper (arXiv 2609.08354) finds calibration degrades most on the largest shifts (MMLU chemistry and physics). [EVIDENCE: abstract.]

### 3.5 Test-time scaling
- **Verbal confidence as a stopping rule.** Adaptive self-consistency that stops when calibrated verbal confidence is high (arXiv 2607.01612). [CLAIM from abstract.]
- **Verbal confidence beats self-consistency early.** A March 2026 study on reasoning models finds verbal confidence beats self-consistency under moderate sampling and that the two combine well, even with two samples (arXiv 2603.19118). [EVIDENCE: reasoning models, not 4B.]
- **Label-free test-time calibration.** SECL (arXiv 2604.09624) reports 56–78% ECE reduction on four small models with no labels at test time. [CLAIM from abstract; check the protocol before relying on it.]

For us, test-time scaling costs inference compute per decision. The product is a single probability per proposed action, so this is a second-stage option, not a training recipe.

---

## 4. Distillation from frontier judges

- **Codifying the Judge** (arXiv 2607.22561, 2026). Distils judging logic into executable programs. Reports a reward model trained on programmatic-judge labels beats one trained on a proprietary LLM's preferences, at about 50x lower API cost. Its confidence-aware fallback routes uncertain cases to an LLM judge. [EVIDENCE: abstract.] The routing idea maps directly onto a tighten-only design.
- **TinyJudge** (ACL 2026, aclanthology 2026.acl-long.1204). Distils frontier expertise into tiny specialist ensembles; reports about 10% average and 12% reward-precision gains. [EVIDENCE: abstract.]
- **RM-Distiller** (IJCAI 2026). Distils generative judges into discriminative reward models. Motivated by latency and cost; calibration not the focus. [EVIDENCE: abstract.]
- **RL with judge rewards from next-token probability** (April 2026 preprint, arXiv 2604.02621). Uses the judge's probability of "yes" as a continuous reward. [EVIDENCE: abstract; preprint.]
- **Gap.** I found no paper whose main contribution is calibration of a distilled small reward model. We would be doing this on our own terms. The main risk is that a student copies the teacher's overconfidence; a judge's score is not a probability. We need to calibrate the student against human labels, not against the judge.

---

## 5. Learning from approve/reject data

- **KTO.** Built for binary desirable/undesirable labels, which is what thumbs-up/down logs are. Authors say it matches or beats DPO from 1B to 30B with only binary signal, and is the natural choice when classes are imbalanced. [EVIDENCE: arXiv 2402.01306, KTO paper.] A Stanford CS224R course project found KTO a strong baseline and DPO more fragile on a small instruction model. [CLAIM: student report, small study.]
- **BCO** (arXiv 2404.04656). Binary feedback follow-up; reports beating KTO and matching DPO on paired data. [EVIDENCE: paper; 2024.]
- **DPO.** Needs paired responses, which usually means synthetic pairs. Better only when we can collect clean pairwise human comparisons. [CLAIM: blog; KTO paper argues DPO wins when preferences are low-noise and transitive.]
- **Reward modelling.** Not searched. Standard practice, but for our case a reward model over (decision, context) is essentially a calibrated classifier, so the reward-model literature and the calibration literature overlap.
- **Active learning and selective labelling.** Not searched in this scan. General knowledge: uncertainty sampling and disagreement sampling are standard; with a small probability model, label where the model's ensemble variance or the judge-versus-model disagreement is highest. Mark this as untested for us.

---

## 6. Tabular foundation-model fine-tuning

- **TabPFN fine-tuning** (arXiv 2506.08982, June 2025). Studies full fine-tuning and parameter-efficient methods on TabPFNv2. Full fine-tuning converged fastest and did not consistently overfit on medium datasets. Experiments ran on a single 80 GB GPU; a 48 GB card may limit dataset size. [EVIDENCE.]
- **TabPFNv2.5 with unseen scoring rules** (March 2026). Fine-tuning with scoring rules not used in pretraining gave consistent gains on those metrics. [CLAIM from search summary; check the paper.] This is directly relevant if we want a proper-scoring fine-tune of a tabular head.
- **Secondary claims.** A Qlik overview says a higher-tier TabPFN variant became API-only in May 2026, and that the newer model has a lower feature limit on wide data. [CLAIM: secondary; not verified against Prior Labs.] Check before depending on any of this.
- **Fit to us.** Our inputs are a mix of structured context and text rationale, so a tabular foundation model may serve as a cheap calibrated baseline or a stacking layer on top of the LM's features, not as the main model.

---

## 7. Frameworks: state and maturity

Version numbers across sources conflict, so only qualitative status is given. Check PyPI and GitHub before any decision.

| Framework | What it is good for | Status as found | Confidence |
|---|---|---|---|
| **TRL** | SFT, DPO, KTO, GRPO, many post-training methods | v1.0 shipped 31 March 2026; claims over 75 methods; no native tensor parallelism | EVIDENCE: Hugging Face release post |
| **Unsloth** | Fast single-GPU LoRA/QLoRA, GRPO with memory tricks | Widely used; docs claim under 48 GB fine-tuning and a shared vLLM standby mode | CLAIM: vendor docs and blogs |
| **verl** | Large-scale RL, vLLM/SGLang rollouts, multi-node | Active; version numbers conflict across sources | CLAIM: aggregator; overkill for one GPU |
| **OpenRLHF** | Ray-based RLHF at 70B+ scale | Paper (arXiv 2405.11143) and active releases; overkill for one GPU | EVIDENCE: paper |
| **Axolotl** | YAML-config fine-tuning, broad HF integration | Active; version conflicts | CLAIM |
| **torchtune** | PyTorch-native recipes for SFT, DPO, PPO, GRPO | Paper exists (arXiv 2605.21442); one 2026 overview calls its lineage vanished after a 2025 release | Uncertain maintenance; check |
| **LLaMA-Factory** | GUI-first, broad model support, medium scale | Popular; not suited to the largest RL runs | CLAIM |

Recommendation from the sources, and mine: for one 48 GB card and a calibration-focused objective, TRL plus Unsloth covers SFT, KTO, DPO and GRPO, and the custom part (Brier loss, calibration evaluation) is small enough to write ourselves. verl and OpenRLHF add complexity we do not need.

---

## 8. Realistic throughput on an A6000

No verified A6000 tokens-per-second number for Qwen3 or any 4B/8B model was found. Official Qwen speed numbers are inference, batch size 1, on unnamed or H20 hardware (about 46 tokens/s for Qwen3-4B and Qwen3-8B in BF16). [CLAIM: Qwen docs.] The only training timing found is a hobbyist run (about 42 s per step for 4B and 50 s per step for 8B, 4-bit base for 8B), GPU not named. [CLAIM.] Unsloth's R1 blog gives about 4,000 tokens/s for a 3B 4-bit model on an A100 40 GB. [CLAIM: vendor.]

My planning estimates for an A6000 (48 GB, roughly 150 TFLOPS dense BF16 peak, realistic 30–40% utilisation with LoRA):

| Model | LoRA training tokens/s | QLoRA tokens/s | GRPO rollout generation | Hours for 10M training tokens |
|---|---|---|---|---|
| 1.5B | ~4,000–6,000 | ~3,000–4,500 | ~2,000–4,000 aggregate | ~0.5–1 h |
| 4B | ~1,500–2,500 | ~1,000–1,800 | ~800–1,500 aggregate | ~1.5–3 h |
| 8B | ~700–1,200 | ~500–900 | ~400–900 aggregate | ~3–5.5 h |

Rule used: training FLOPs about 4·N per token with LoRA (no weight gradients for the frozen base), against the peak above. These are ESTIMATES. A 6-hour budget per experiment means that 8B is feasible only for a single SFT or KTO pass over about 10M tokens; GRPO on 8B will need short completions and few steps.

The first thing to do with the card is a 30-minute benchmark: measure tokens/s and peak VRAM for 1.5B, 4B and 8B at our real sequence length, for LoRA and QLoRA. That number decides the rest of the plan.

---

## 9. Base models people prefer for small classifiers and verifiers

- **Qwen3.5-4B.** Most-recommended pragmatic base for custom fine-tunes; Apache 2.0. [CLAIM: aiwiki and similar roundups.] A June 2026 preprint found Qwen 3.5 4B with JSON-only prompting at 96.6% F1 on merchant extraction, within 0.35 points of an 8B model. [EVIDENCE: single task, arXiv 2606.08051.]
- **SmolLM3-3B.** Apache 2.0 with full training recipe and data mix, so the least guesswork if we want reproducibility. Main languages are six European languages. [CLAIM: model card summaries.]
- **Gemma 3 4B.** Long community track record of fine-tunes and 128K context. [CLAIM.] Gemma 4 E4B and 12B are described as Apache-2.0 bases. [CLAIM: aggregator.]
- **Qwen3 0.6B and 1.7B.** Small enough for fast iteration; community reports of 93% accuracy on a 12-class question task in 18 minutes on an RTX 3060 12 GB. [CLAIM: anecdotal.]
- **Llama 3.x 8B.** Still cited as the most versatile 8B base in practitioner blogs. [CLAIM.]
- **MiniCPM5-2B** (released September 2026, per one source). Vendor or aggregator claim of top score among open models under 4B on Artificial Analysis. [CLAIM; not verified.]
- **Advice from the sources.** Do not pick by leaderboard. Fine-tune two or three candidates on our labelled data and compare ECE, not accuracy. [CLAIM: practitioner consensus across the sources.]

---

## 10. Practitioner signals (what works, what does not)

The search did not return X/Twitter posts. The following is from blogs and arXiv.

**What people report works**
- LoRA with modest rank as the default. [CLAIM: several 2026 guides.]
- Ordering: SFT first, RL second. [CLAIM.]
- Reward design takes most of the effort. Long, multi-term rewards with a KL anchor. [CLAIM: practitioner write-ups.]
- Brier or proper-scoring reward for confidence. [EVIDENCE: RLCR and related papers.]
- Verbal confidence paired with sampling, with calibration checked before use. [EVIDENCE: 2603.19118, with the small-model caveat above.]

**What people report does not work**
- Plain binary-reward RL for calibration, particularly out of domain. [EVIDENCE: Yaldiz et al.; RLCR baseline.]
- Trusting verbal confidence on small instruct models without checking the distribution (degenerate ceilings). [EVIDENCE: Gemma 3 4B preprint.]
- Temperature scaling fit on in-domain data alone under shift. [CLAIM: practitioner consensus; also EVIDENCE in the adaptive-temperature line of work.]
- Overtraining. Too many epochs or too high a learning rate causes drift into reward hacking. [CLAIM.]
- Monitoring reward hacking with linear probes alone. One LessWrong experiment found probes detect planted hacks well but add little over output checks, because subtle hacks are rarely sampled. [CLAIM: single small experiment.]

---

## 11. Gaps and unverified items

- No X/Twitter results returned by search.
- No A6000 throughput data.
- No calibration-under-shift head-to-head of SFT versus RL versus temperature scaling for sub-8B models.
- Focal loss and label smoothing: no 2025–2026 LLM study found.
- Active learning and selective labelling: not searched.
- Reward modelling: not searched.
- Framework version numbers conflict across sources.
- Several numbers above come from abstracts only.

---

## Beyond what they asked

Ideas we have probably not considered, for a calibrated, tighten-only, domain-specific decision model. These are my suggestions, not evidenced results.

1. **Train the model to block, not to approve.** Frame the output as the probability that the owner would reject. A tighten-only system only needs to be reliable on the reject side, so calibrate and evaluate that side specifically, with a cost-weighted proper score.
2. **Conformal wrapper for coverage.** Put a split-conformal or Mondrian-conformal layer on top of the small model, conditioned on owner segment and market regime. This gives a distribution-free coverage guarantee under exchangeability, and the guarantee degrades under shift; measure that degradation directly.
3. **Synthetic shift generation.** Create training and held-out sets by perturbing regime, volatility and instrument mix, rather than waiting for real shifts. Use it to choose calibration methods before we need them.
4. **Privileged-information training.** Use the frontier judge's rationale as training-time-only input (the student never sees it at test time). Labels stay human; the rationale speeds learning without importing the judge's overconfidence.
5. **Disagreement-driven labelling.** Send to a human only where the small model and the judge disagree, or where ensemble variance is highest. This targets scarce approve/reject labels where they change the decision.
6. **Decision-weighted proper scores.** Use a Brier or log score weighted by the cost of each error type (a missed reject versus a false reject). The score is still proper, so calibration is preserved while the operating point matches the business.
7. **Adapter soups across time windows.** Train one LoRA per time window and average or merge them. This is a cheap robustness test for drift, and it fits on one card.
8. **Teacher-ensemble soft labels.** Average several judge runs or seeds into a soft target, then train the student on that. Reduces label variance; the student's calibration is still checked against human labels.
9. **Abstention as a first-class output.** Train an explicit abstain token or a second head that says "defer to a human." For a tighten-only product, deferral is the safe default, and calibrated abstention is measurable.
10. **Owner-persona conditioning with a calibration check per persona.** Condition on a stated risk profile and report ECE per persona. A model that is calibrated overall can still be miscalibrated for a small segment.

---

## First three experiments (each under 6 GPU-hours on the A6000)

**Experiment 1. Brier-loss SFT versus plain SFT (about 3 GPU-hours).**
- Base: one small model from section 9 (try Qwen3.5-4B with LoRA rank 16, and Qwen3-1.7B as the cheap comparison).
- Data: our existing labelled decisions, split in-domain and a held-out shifted slice (by regime or time).
- Arms: (a) plain cross-entropy SFT with a verbal confidence; (b) ConfTuner-style tokenised Brier SFT; (c) (a) followed by temperature scaling fit on in-domain only.
- Metrics: in-domain ECE, out-of-domain ECE, Brier score, accuracy, and the verbal confidence distribution (check for ceiling collapse).
- Decision it informs: whether a calibration term in SFT is enough, before any RL.

**Experiment 2. Shift stress test and cheap baselines, no training (about 2 GPU-hours).**
- Build a shift split (synthetic regime perturbation plus any real time-based split).
- Measure, on the untrained base models: logit-based probability, verbal confidence, self-consistency across five samples, and temperature scaling fit in-domain then applied out-of-domain.
- Metrics: ECE and Brier per arm, in and out of domain, with bootstrap intervals.
- Decision it informs: how bad shift is for free, and whether a test-time method is worth its inference cost. Also gives us a benchmark throughput number for the same runs.

**Experiment 3. KTO on approve/reject logs versus SFT on approved only (about 4–5 GPU-hours).**
- Base: the best model from Experiment 1, LoRA.
- Arms: (a) SFT on approved decisions only; (b) KTO on all approve/reject labels with class-balanced weights; (c) (b) with the Brier term from Experiment 1 added to the objective, if the library allows it, otherwise as a post-hoc calibration step.
- Metrics: ECE and Brier in and out of domain, plus the reject-side metrics from idea 1 (recall and precision on rejects at a fixed operating point).
- Decision it informs: whether human approve/reject data adds value beyond SFT, and whether it helps calibration or only accuracy.

Each experiment uses frozen seeds, a fixed validation split, and writes its metrics to a file on the card so the network-isolated job needs no outbound access.

---

## Sources

- arXiv 2507.16806 (RLCR): https://arxiv.org/pdf/2507.16806
- ICLR 2026 poster for RLCR: https://iclr.cc/virtual/2026/poster/10011036
- arXiv 2601.22582 (MC-GRPO): https://www.alphaxiv.org/abs/2601.22582v1
- arXiv 2601.09085 (GRPO, Dr. GRPO, DAPO on small models): https://arxiv.org/pdf/2601.09085v1
- arXiv 2607.00152 (group-standard-deviation identity): https://huggingface.co/papers/2607.00152
- arXiv 2609.39321 (GRPO training dynamics for SLMs): https://arxiv.org/pdf/2609.39321
- arXiv 2512.19920 (behaviourally calibrated RL): https://arxiv.org/html/2512.19920
- arXiv 2508.18847 (ConfTuner): https://arxiv.org/html/2508.18847v2
- arXiv 2601.13284 (Yaldiz et al., calibration-aware RL): https://www.alphaxiv.org/abs/2601.13284
- arXiv 2604.23333 (RLCM): https://arxiv.org/html/2604.23333v1
- arXiv 2603.03752 (COREA): https://arxiv.org/html/2603.03752v1
- arXiv 2607.01612 (confidence-aware scaling): https://arxiv.org/abs/2607.01612
- arXiv 2506.03723 (verbalised confidence triggers self-verification): https://arxiv.org/html/2506.03723v1
- arXiv 2603.19118 (uncertainty scaling with sampling): https://www.alphaxiv.org/abs/2603.19118.md
- arXiv 2604.24070 (distilling self-consistency into verbal confidence): https://www.alphaxiv.org/abs/2604.24070.md
- arXiv 2604.09624 (SECL): https://www.alphaxiv.org/abs/2604.09624.md
- arXiv 2410.06431 (UQ4CT): https://arxiv.org/html/2410.06431v2
- arXiv 2610.12048 (EUA-Cal): https://arxiv.org/pdf/2610.12048
- arXiv 2609.08354 (Stiefel Bayesian PEFT): https://arxiv.org/pdf/2609.08354
- arXiv 2608.07419 (bilevel calibration): https://arxiv.org/pdf/2608.07419
- arXiv 2409.19817 (adaptive temperature scaling): https://arxiv.org/pdf/2409.19817
- arXiv 2402.01306 (KTO): https://arxiv.org/pdf/2402.01306
- arXiv 2404.04656 (BCO): https://arxiv.org/pdf/2404.04656
- arXiv 2402.09353 (DoRA), not re-fetched: https://arxiv.org/abs/2402.09353
- Answer.AI QDoRA: https://www.answer.ai/posts/2024-04-26-fsdp-qdora-llama3.md
- arXiv 2506.08982 (fine-tuning TabPFN): https://arxiv.org/html/2506.08982v1
- arXiv 2607.22561 (Codifying the Judge): https://www.alphaxiv.org/abs/2607.22561
- ACL 2026 TinyJudge: https://aclanthology.org/2026.acl-long.1204/
- IJCAI 2026 RM-Distiller: https://www.ijcai.org/proceedings/2026/0681.pdf
- arXiv 2604.02621 (RL with judge probability reward): https://arxiv.org/abs/2604.02621
- arXiv 2606.08051 (merchant extraction LoRA comparison): https://arxiv.org/html/2606.08051
- arXiv 2605.21442 (torchtune): https://arxiv.org/pdf/2605.21442
- arXiv 2405.11143 (OpenRLHF): https://arxiv.org/pdf/2405.11143
- TRL v1.0 (Hugging Face): https://huggingface.co/blog/trl-v1
- Unsloth memory-efficient RL: https://unsloth.ai/docs/get-started/reinforcement-learning-rl-guide/memory-efficient-rl
- Qwen speed benchmark: https://qwen.readthedocs.io/en/latest/getting_started/speed_benchmark.html
- LessWrong, linear probes for reward hacking: https://www.lesswrong.com/posts/NzzmNREX4qR54q33j/linear-probes-add-little-for-verifiable-reward-hacking
- Qlik, table-native foundation models (secondary): https://www.qlik.com/blog/the-shift-to-table-native-foundation-models
- Small-model roundups (secondary, several): https://tinyweights.dev/posts/best-small-language-models-2026/
- Hyperstack Unsloth tutorial (secondary): https://docs.hyperstack.cloud/docs/tutorials/fine-tuning-unsloth
