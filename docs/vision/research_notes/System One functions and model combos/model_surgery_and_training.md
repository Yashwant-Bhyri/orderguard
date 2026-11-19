# Model surgery and training for a narrow judgement model

Scope: techniques for building a small, narrow classifier or judge (claim-evidence support, manipulation detection, endorsement risk) out of pretrained parts. Target: p99 at most 300 ms on one RTX A6000 (48 GB), easy post-training later, and generalisation to unfamiliar wording and failure types. Evidence cutoff: this session's searches, as of 2026-11-19.

Method note: this pass used 15 standard-mode web searches. Only one search returned abstract-level content that was checked against its listing. I fetched no full papers. Most numbers below come from abstracts, search-result snippets, or secondary summaries, and are marked as such. Where a number is from a secondary source, the claim is flagged. Nothing here has been reproduced. The task settings are noted for each result, because most of the evidence comes from generation or maths benchmarks, not classification.

## Layer surgery (intermediate-layer features, layer pruning, early exit)

### Takeaway
Intermediate layers often give better frozen features for classification than the final layer, and decoder LLMs tolerate substantial layer removal before generation-style quality drops. Neither result has been tested here on claim-evidence or manipulation classification. Early-exit evidence was not found in this pass.

### Cited Findings
- Skean et al., "Layer by Layer: Uncovering Hidden Representations in Language Models" (ICML 2025). Intermediate layers consistently give stronger embedding features than final layers across 32 text-embedding tasks, and across transformer and state-space models, and across language and vision. Setting: embedding and classification-style evaluation. [Abstract](https://arxiv.org/abs/2502.02013); [ICML poster](https://icml.cc/virtual/2025/poster/45028)
- "Layer Enhanced Classification" (arXiv 2412.13435). A penalised logistic regression on the hidden state of the best intermediate layer reached the highest F1 with the fewest training examples, on content-safety and prompt-injection classification. The best layer differs by task. Secondary review says intermediate layers beat the final layer across these tasks. Source is a preprint; check the paper's tables. [arXiv HTML](https://arxiv.org/html/2412.13435v1); [review](https://themoonlight.io/review/lightweight-safety-classification-using-pruned-language-models)
- ShortGPT (Men et al., arXiv 2403.03853). Block Influence (how much a layer changes its hidden state) ranks layers; the lowest-ranked layers are deleted. Authors report about 90% performance kept with about 25% of parameters removed. The "up to 55%" figure comes from a third-party summary, not the paper. Setting: generation benchmarks on LLaMA-family models. Authors say the last layer is especially important. [arXiv](https://arxiv.org/abs/2403.03853); [v3 HTML](https://arxiv.org/html/2403.03853v3)
- Gromov et al., "The Unreasonable Ineffectiveness of the Deeper Layers" (ICLR 2025). On open-weight models including Llama-2-70B, QA benchmark performance stays roughly flat up to about 40% layer removal, then falls off. Deep-end removal without a similarity search does about as well as the similarity-guided method, but only after "healing" (fine-tuning). Without healing it performs poorly. Reasoning-heavy GSM8K degrades under any pruning. Setting: QA benchmarks and maths. [arXiv](https://arxiv.org/abs/2403.17887); [ICLR poster](https://iclr.cc/virtual/2025/poster/28400)

### Inferences
- The strongest cheap move is to use an intermediate layer (or a learned mix of layers) as the frozen feature source, then add a small head. This is supported for embedding and safety classification. It is not yet supported for judgement tasks with evidence pairs.
- Pruning deep layers is reasonable for classification-only models because the evidence for pruning is on QA, not on the reasoning-heavy tasks where it degrades fastest. Expect to need healing or a short post-training pass after any cut.
- Truncation below about 50% of layers is outside what the evidence covers.

### Gaps
- No direct comparison of layer pruning on claim-evidence or manipulation tasks was found.
- LaCo (layer collapse) was not searched in this pass. Its numbers are not reported here.
- Early exit for classifiers: no evidence was retrieved. Needs a separate search.
- Interaction of layer selection with later LoRA fine-tuning was not checked.

## Heads on frozen backbones (linear probes, MLP, attention pooling, span and pointer heads, multi-task heads)

### Takeaway
Small, task-specific heads on a frozen or lightly tuned backbone are the cheapest path to a narrow classifier. Data needs are low: about 100 labelled examples to break even with a general LLM on text classification, on average, with wide variance. Evidence for span and pointer heads that point at evidence was not found in this pass.

### Cited Findings
- Pecher, Srba, Bielikova, "Comparing Specialised Small and General Large Language Models on Text Classification: 100 Labelled Samples to Achieve Break-Even Performance" (EMNLP 2025). Eight LMs and eight text-classification tasks, comparing fine-tuning, instruction tuning, prompting, and in-context learning. Specialised models needed about 100 labels on average to match or beat general models. Accounting for variance raised the requirement by 100 to 200%. The count depends heavily on the task; binary tasks needed more labels. Larger models did not consistently reduce variance. 4-bit quantisation had negligible effect. Setting: text classification, not evidence-based judgement. [ACL Anthology](https://aclanthology.org/2025.emnlp-main.9); [arXiv](https://arxiv.org/abs/2402.12819)
- SetFit (Tunstall et al., "Efficient Few-Shot Learning Without Prompts", arXiv 2209.11055). Contrastive fine-tuning of a sentence transformer on text pairs, then a classification head. Reported as competitive with PEFT and PET and about an order of magnitude faster to train. Numbers came from a secondary site. Setting: few-shot text classification, NLP benchmarks from 2022. [arXiv](https://arxiv.org/abs/2209.11055); [code](https://github.com/huggingface/setfit)
- Hsieh et al., "Distilling Step-by-Step!" (arXiv 2305.02301). Multi-task training: a small model predicts labels and LLM-generated rationales. Reported: an 11B T5 beats 540B PaLM on the authors' tasks; a 770M T5 reaches the baseline with about 80% of the data; rationales add training cost but not inference cost. Setting: 2023 T5-era reasoning and NLI-style tasks. [arXiv](https://arxiv.org/abs/2305.02301); [code](https://github.com/google-research/distilling-step-by-step)

### Inferences
- A multi-task head (labels plus rationale, or labels plus evidence span) is a reasonable design. Distilling step-by-step supports rationales as auxiliary supervision in training only. Whether it helps on evidence-based judgement is not established here.
- At about 100 labels, the head approach is likely enough for a narrow task, but the EMNLP result shows the number is task-dependent and that variance can double it. Plan for a few hundred labels per judgement and measure variance across seeds.
- The EMNLP result is measured on text classification. Its break-even numbers should not be transferred to evidence reasoning without a pilot.

### Gaps
- Evidence for span or pointer heads (extractive evidence selection on a frozen backbone) was not retrieved.
- Attention-pooling vs CLS vs mean pooling: no specific comparison retrieved.
- Joint schema heads and multi-task head interference: not searched.

## Changing input and output (typed inputs, number encodings, claim-evidence cross-attention, tabular fusion)

### Takeaway
Number encoding has evidence, but only from models trained from scratch on scientific data. Cross-attention between claim and evidence, typed inputs, and tabular fusion were not evidenced in this pass.

### Cited Findings
- xVal (Golkar et al., Polymathic AI; arXiv 2310.02989, revised as "xVal: A Continuous Numerical Tokenization for Scientific Language Models"). Each number becomes one token, scaled by a learned embedding vector, with a dedicated number head on output. Authors report better interpolation and better compute efficiency than prior digit-level encodings. Setting: models trained from scratch on synthetic and scientific data. [arXiv](https://arxiv.org/abs/2310.02989); [code](https://github.com/PolymathicAI/xVal)

### Inferences
- xVal is a candidate for numeric fields (confidence scores, dates, amounts) if the model is trained from scratch or heavily adapted. Adding it to a frozen pretrained model is untested here.

### Gaps
- No evidence retrieved for claim-evidence cross-attention heads vs concatenation.
- No evidence retrieved for typed or structured input formats.
- No evidence for tabular plus text fusion.

## Parameter-efficient post-training (LoRA, QLoRA, DoRA, adapters, selected-layer LoRA)

### Takeaway
LoRA and DoRA are the standard cheap post-training options. Forgetting and out-of-distribution (OOD) effects depend heavily on rank, alpha, and learning rate, so they are not a fixed property of the method. The sample-efficiency evidence here is weak. Selected-layer LoRA was not evidenced in this pass.

### Cited Findings
- Biderman et al., "LoRA Learns Less and Forgets Less" (2024). As summarised by a 2024 follow-up, LoRA at common low ranks underperforms full fine-tuning in continued pretraining. It can match full fine-tuning in instruction tuning at higher ranks. The authors attribute the gap to full fine-tuning learning weight changes 10 to 100 times larger. The original paper was not retrieved, so its number is taken from the follow-up. [Follow-up cited below](https://arxiv.org/pdf/2410.21228)
- "LoRA vs Full Fine-tuning: An Illusion of Equivalence" (arXiv 2410.21228). In RoBERTa experiments where both methods reach equal fine-tuning accuracy, LoRA forgets less than full fine-tuning in the reported setting. In later versions, different alpha and learning-rate choices give starkly different generalisation, and LoRA can forget more. The authors attribute this to "intruder dimensions", high-ranking singular vectors that appear only in LoRA models. [arXiv](https://arxiv.org/pdf/2410.21228v1.pdf); [v3](https://arxiv.org/pdf/2410.21228v3)
- EMNLP 2026 Findings paper (ACL Anthology 2026.findings-emnlp.918), on QLoRA for factual knowledge acquisition. Reported: rank sets a clear acquisition-versus-retention frontier. Low-rank setups keep out-of-domain performance but learn fewer facts. Known only from a search summary. [ACL Anthology](https://aclanthology.org/2026.findings-emnlp.918.pdf)
- DoRA (Liu et al., ICML 2024; arXiv 2402.09353). Decomposes weights into magnitude and direction and applies LoRA to the direction. Reported gains over LoRA on commonsense reasoning across LLaMA-7B, 13B, LLaMA2-7B, and LLaMA3-8B. Early arXiv version: +3.4 and +1.0 on LLaMA-7B and 13B. Later summary: about 3.7% on LLaMA-7B. At rank 4, reported 61.89% vs LoRA's 39.49%. Setting: generative commonsense benchmarks scored as multiple choice. No extra inference cost. [arXiv HTML](https://arxiv.org/html/2402.09353v4); [ICML proceedings](https://proceedings.mlr.press/v235/liu24bn.html)

### Inferences
- For a narrow classifier, LoRA on attention and MLP projections with moderate rank is the cheapest reasonable default. DoRA is a low-cost upgrade where gains are wanted, with the caveat that the reported gains are on generative benchmarks.
- Forgetting is only a meaningful concern if the model keeps a general-purpose role. For a narrow judge, the relevant risk is OOD drift on new wording, which the evidence says to test directly per rank and learning-rate setting.
- Selected-layer LoRA follows from the layer-surgery findings, but this pass found no evidence for it.

### Gaps
- No evidence for LoRA sample efficiency on classification tasks with fewer than about 1,000 examples.
- No QLoRA-specific classification comparison retrieved.
- Adapter and selected-layer LoRA results were not retrieved.

## Distillation (rationales, disagreement or difficulty-aware, counterfactual and contrastive data, hard negatives, on-policy)

### Takeaway
Rationales as an auxiliary task help small models in the step-by-step setting. On-policy distillation is an active 2025 to 2026 direction. It has a known diversity-loss failure mode. Counterfactual and hard-negative augmentation was not evidenced in this pass.

### Cited Findings
- Distilling step-by-step (see the Heads section): rationales used only as training supervision. [arXiv](https://arxiv.org/abs/2305.02301)
- On-policy distillation: the student generates rollouts, and a teacher scores each token, usually minimising per-token reverse KL. The origin is a Thinking Machines blog post from October 2025. Only a Medium summary was retrieved, so the blog's claims are secondhand. [Summary](https://medium.com/@maheshlambe/mira-murati-thiking-machines-on-policy-distillation-cheap-accuracy-real-gains-85ac523b20f7)
- Reverse KL is mode-seeking. One 2026 paper argues it reduces reward hacking compared with forward KL, and another (Veto, January 2026) reports diversity loss and mode collapse, proposing a tunable objective. Both are preprints surfaced by search. Their identifiers were not verified against titles. [Veto-related link](https://arxiv.org/html/2601.18734v2)
- Weak-to-strong on-policy distillation (2026 preprint): a small RL-trained expert transfers capability to a larger student via reverse KL on the student's rollouts. Unverified; listed for lead value only. [alphaXiv](https://www.alphaxiv.org/abs/2607.26246.md)

### Inferences
- For classification, on-policy rollouts are less useful than for generation: the output is a label, so the teacher can score the label distribution directly with no rollouts. On-policy distillation is most relevant only if the judge produces generated rationales.
- The "structured labels beat long traces" question is not answered here. Distilling step-by-step gives evidence that rationales can be dropped at inference, which is the relevant point for a cheap judge.

### Gaps
- No evidence found for disagreement- or difficulty-aware distillation.
- No evidence found for counterfactual or contrastive augmentation effects on OOD judgement.
- Hard-negative mining: not searched.
- No direct comparison of structured-label training vs long-trace training on classification.

## Decoder-to-classifier conversion (scalar heads, LLM2Vec, bidirectional attention)

### Takeaway
A decoder with a scalar or classifier head works well for reward-style judgements. Converting it to bidirectional attention needs an adaptation step: LLM2Vec shows that switching attention alone hurts embedding quality. Encoder-vs-decoder comparisons for narrow classification were not found in this pass.

### Cited Findings
- LLM2Vec (BehnamGhader et al., COLM 2024; arXiv 2404.05961). Three steps: enable bidirectional attention, masked next-token prediction training, then unsupervised contrastive learning. Bidirectional attention alone decreases embedding performance for most models. Reported unsupervised state of the art on MTEB at 56.8. Setting: text embedding (MTEB). [arXiv](https://arxiv.org/abs/2404.05961); [code](https://github.com/McGill-NLP/llm2vec)
- Bradley-Terry scalar reward heads: the standard reward model is a transformer with the LM head replaced by a scalar output, trained on pairwise preferences. RewardBench is the common evaluation, with strong models reported at 80 to 90%. A December 2025 preprint (arXiv 2512.06343) reports a representation-distance bias in the BT loss. Sources are blogs and preprints, not official documentation. [arXiv 2512.06343](https://arxiv.org/html/2512.06343v2)

### Inferences
- A decoder backbone with a head is a sensible choice when the backbone already knows the domain and the judgement is pairwise or scored. An encoder is more likely to be cheaper per token at the same accuracy, but no comparison was retrieved, so this is an inference.
- Bidirectional conversion should be done only if the judge reads the whole claim and evidence together and the decoder is causal. Budget for an MNTP-style step.

### Gaps
- No direct classification comparison of decoder-with-head vs encoder at matched latency.
- Bidirectional conversion results for classification (not embedding) were not found.

## RL for classifiers and verifiers (RLCR and when RL helps)

### Takeaway
RL helps when the output is generated reasoning with a verifiable reward and when out-of-distribution generalisation matters. For a discrete label with a proper loss, RL is probably a waste. RLCR is the most relevant calibration method, but its evidence is on maths and QA, not classification.

### Cited Findings
- RLCR (Damani et al., "Beyond Binary Rewards: Training LMs to Reason About Their Uncertainty", arXiv 2507.16806; ICLR 2026 poster). Adds a Brier-score term to a binary correctness reward. Authors show that bounded proper scoring rules are maximised by answering the most likely answer with its true confidence. Reported: better calibration without accuracy loss, in and out of domain. Setting: GRPO on Qwen2.5-7B with format rewards, maths and QA. OOD calibration error remains high, and SFT followed by RLCR slightly reduces OOD accuracy. [arXiv](https://arxiv.org/abs/2507.16806); [ICLR poster](https://iclr.cc/virtual/2026/poster/10011036)
- Chu et al., "SFT Memorizes, RL Generalizes" (ICML 2025; arXiv 2501.17161). Outcome-reward RL generalised to unseen rule and visual variants, while SFT memorised. SFT still matters for stabilising output format before RL. Setting: a card game and visual navigation, not classification. Effect sizes came from a secondary summary. [PMLR](https://proceedings.mlr.press/v267/chu25c.html); [arXiv](https://arxiv.org/abs/2501.17161)
- Counterpoint: arXiv 2508.16546 describes SFT forgetting, where OOD accuracy first rises and then falls over long SFT. Overfitted SFT is hard to recover by RL. [alphaXiv](https://www.alphaxiv.org/overview/2508.16546)

### Inferences
- For a narrow judge with label output, cross-entropy with a calibration step (temperature scaling, or a held-out calibration set) is the cheaper route to calibrated confidence. The RLCR result is for generated confidence in reasoning models; it is not evidence that RL beats supervised training on a head.
- If the judge emits rationales, RL with calibration rewards may be worth testing on a held-out OOD set. Expect the RLCR OOD calibration gap to persist.
- Early stopping on SFT, plus a short RL phase, is one way to limit forgetting. Evidence is mixed.

### Gaps
- No evidence found for RL vs SFT on claim-evidence or manipulation classification.
- Verifier training with RL on a small backbone: not searched.

## Model merging and ensembles under shift

### Takeaway
Weight averaging improves OOD robustness in vision evidence (model soups). LLM-specific evidence exists only as recent preprints and surveys, and was not checked against full results. No classifier-specific merging study was found.

### Cited Findings
- Model Soups (Wortsman et al., arXiv 2203.05482). Averaging weights of fine-tunes with different hyperparameters improves accuracy with no inference cost. Robustness evaluated on ImageNet-V2, -R, -Sketch, ObjectNet, and -A. Setting: vision. [Paper page](https://huggingface.co/papers/2203.05482.md)
- Survey "Model Merging in the Era of Large Language Models" (arXiv 2603.09938, March 2026). Reports that soups have been applied to LLMs. Not checked in detail. [arXiv](https://arxiv.org/pdf/2603.09938)
- "Model soups need only one ingredient" (arXiv 2602.09689, EPFL, 2026). Targets the trade-off where fine-tuning helps in-distribution accuracy and hurts OOD. Preprint; claims not verified. [arXiv HTML](https://arxiv.org/html/2602.09689v2)
- Adapter Soups: averaging domain-specific adapters on base LLMs. Known only from a topic summary. [Topic page](https://api.emergentmind.com/topics/model-souping)

### Inferences
- Averaging several seeds or hyperparameter settings of a narrow judge is a low-cost robustness check with no latency cost. Test it on a held-out OOD set before relying on it.
- Ensembles would add serving cost. Soups do not.

### Gaps
- No LLM or classifier evidence on claim-evidence or manipulation tasks.
- Adapter merging for swapping judgement types: no direct evidence found.

## Combinations known to work together

Evidence for combinations is thin. The following are inferences built on the individual results above.

- Intermediate-layer features + linear or MLP head + about 100 to a few hundred labels (layer-selection and EMNLP results support this as a baseline).
- Intermediate-layer features + LoRA on upper layers only + head, with rank and learning-rate sweeps for OOD drift (LoRA rank and learning rate change forgetting; selected-layer LoRA is untested here).
- Multi-task head with rationale or evidence-span auxiliary loss, trained once and dropped at inference (distilling step-by-step).
- Decoder backbone with scalar or classifier head for pairwise or scored judgements (reward-model practice).
- Weight averaging across seeds for OOD robustness (soups evidence is vision-based, plus a 2026 preprint).

No combination above has been tested together in the cited sources.

## Overall gaps for the project

- No direct evidence on claim-evidence support, manipulation detection, or endorsement risk classification from any of these techniques.
- Early exit, span or pointer heads, cross-attention between claim and evidence, hard-negative mining, and counterfactual augmentation were not evidenced here.
- Numbers from secondary summaries (Layer Enhanced Classification, DoRA follow-ups, the Biderman LoRA result, RLCR and SFT-vs-RL effect sizes) should be checked against the primary PDFs before any design decision.
- Next search pass: LaCo and other layer-collapse methods; early exit for classification; span-extraction heads for evidence; hard-negative and counterfactual augmentation for NLI and fact-checking; RL vs SFT on classifiers; a 2025 to 2026 search for decoder vs encoder at matched latency.
