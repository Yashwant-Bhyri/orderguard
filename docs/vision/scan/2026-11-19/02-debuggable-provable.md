# Scan 02: What is debuggable, inspectable and provable in a model today

Date of scan: 2026-11-19. Scout notes, not a decision.

Labels: **EVIDENCE** = paper, benchmark or released code. **CLAIM** = blog, vendor page, tweet or marketing. Items marked **[memory]** were not re-checked in this session and should be verified before anyone relies on them.

Context for the reader: System One is a small, fast, calibrated scorer of whether a portfolio owner would endorse an agent's action. Its outputs may only tighten limits. Two properties matter most: monotonicity ("more leverage never raises approval") and bounded, calibrated outputs. Everything below is judged against those two needs, plus the ability to debug the model when it misbehaves.

---

## 1. Summary

- **Interpretability tooling is real but built mostly for LLMs.** SAEs, transcoders and attribution graphs are open for Gemma and Llama. The 2025 evidence says they do not beat linear probes on standard tasks, so they are not a cheap debugging win for a small scorer.
- **Glass-box and monotone-by-construction models are the practical route to checkable properties.** Monotonicity can be built in, or certified after training on small networks.
- **Formal verification reaches small networks only.** alpha-beta-CROWN leads the 2025 competition; scale on our architecture must be measured.
- **Conformal risk control gives finite-sample guarantees on a risk we define**, and its monotonicity requirement fits a tighten-only product.
- **SR 11-7 was replaced in April 2026.** Its reach over AI is disputed in secondary sources; read the primary text first.

---

## 2. Open-weight checkpoints and interpretability tooling

### 2.1 Gemma Scope 2 (Google DeepMind, December 2025)

- **What it is:** an open suite of SAEs and transcoders for the Gemma 3 family, covering sizes from 270M to 27B parameters. Model cards on Hugging Face (for example `google/gemma-scope-2-4b-it`, `google/gemma-scope-2-12b-it`, `google/gemma-scope-2-27b-it`) describe SAEs on three sites per layer, transcoders, skip-transcoders and cross-layer transcoders for some sizes. Some model cards mention partial residual-stream crosscoders. SAEs load through SAELens; Neuronpedia hosts an interactive demo.
- **Release date:** the announcement is dated 19 December 2025 per secondary coverage; InfoQ covered it in January 2026.
- **Label:** EVIDENCE (released weights and model cards). The press framing is CLAIM.
- **Source:** https://huggingface.co/google/gemma-scope-2-4b-it ; https://infoq.com/news/2026/01/google-gemma-scope-2/ ; https://ai.google.dev/gemma/docs/gemmascope
- **Caveat:** one secondary article says the tools interpret "Gemini 3" models. The official materials and model cards say Gemma 3. Use Gemma 3.
- **What you can inspect:** feature activations per token and per layer, feature decoders (directions in the residual stream), transcoder paths from one layer's residual stream to later MLP outputs, and cross-layer contributions. You can ablate and steer features.
- **What you cannot inspect or prove:** that features are the model's "true" units. There is no guarantee of faithfulness or completeness. Nothing here proves a behavioural property. Cross-layer transcoders replace parts of the network, so conclusions are about the replacement, not the original.
- **Cost:** inference-time overhead for each SAE or transcoder at the chosen sites; storage for the weights; interpretation time for a human, which is the dominant cost.
- **Relevance to us:** the 270M and 1B members are the only sizes in the family small enough to be a plausible base for a fast scorer. The 270M size is the natural smallest candidate to test, not a finished choice.

### 2.2 Gemma Scope (original, Gemma 2, 2024)

- Earlier SAE suite for Gemma 2 models. Still the one most used in 2025 papers (see 2.6 critiques), because the probing and absorption studies ran on it.
- **Label:** EVIDENCE.
- **Source:** https://ai.google.dev/gemma/docs/gemmascope

### 2.3 Llama Scope (OpenMOSS, October 2024)

- SAEs for Llama-3.1-8B-Base: 256 SAEs covering residual stream, attention output, MLP output and transcoders at each layer and sublayer, with 32K and 128K feature widths. Uses a TopK design, with modifications (decoder-norm-aware TopK, post-processing to JumpReLU, K-annealing).
- Checkpoints on Hugging Face at `fnlp/Llama-Scope`, with the model card listing Apache-2.0 and integration with SAELens. The model card advises against the 32x attention-output SAEs because many features are inactive.
- **Label:** EVIDENCE (arXiv 2410.20526 and released checkpoints).
- **Source:** https://arxiv.org/abs/2410.20526 ; https://huggingface.co/OpenMOSS-Team/Llama-Scope
- **What you can inspect:** same class as Gemma Scope, for an 8B base model. Too large to be our System One base, but useful as a worked example and as a teacher for the debugging workflow.
- **Caveat:** I did not check for later Llama Scope releases.

### 2.4 Attribution graphs and circuit tracing (Anthropic, May 2025)

- Anthropic released an open Python library (`circuit-tracer`) that builds attribution graphs using cross-layer transcoders on open-weight models, with a Neuronpedia frontend that lets you edit feature values and see outputs change. Demonstrations used Gemma-2-2B and Llama-3.2-1B, for multi-step reasoning and multilingual representations. The Gemma graphs used transcoders from the Gemma Scope project.
- **Label:** EVIDENCE for the method and the code. The "revolutionising" tone in secondary articles is CLAIM.
- **Source:** https://www.anthropic.com/research/open-source-circuit-tracing ; https://transformer-circuits.pub/2025/attribution-graphs/methods.html
- **What you can inspect:** a causal-looking path of features from input tokens to output logits, with the ability to intervene on features.
- **What you cannot prove:** the authors say explicitly that the replacement model may use different mechanisms from the original, so graphs must be validated. Graphs are per-prompt and do not give a global property.
- **Cost:** large. Graph construction is compute-heavy and each graph needs human reading. This is a tool for one-off investigations, not a monitoring method.
- **Relevance:** good for debugging a surprising score on a specific order, poor as a release gate.

### 2.5 Linear probes and steering

- **Linear probes:** train a logistic regression on residual-stream activations to predict a concept or label. Cheap, well understood, easy to version and test. The 2025 evidence (see 2.6) says these often beat SAE-based probes on standard tasks.
- **Steering vectors:** add a direction to activations to shift behaviour. The AxBench study (2025) found that "even simple baselines outperform sparse autoencoders" for steering; a May 2026 rebuttal (arXiv 2605.31183) argues SAE steering is stronger than reported under a different labelling method but still not clearly competitive with prompting.
- **Label:** EVIDENCE (benchmarks), preprints and the rebuttal not peer reviewed.
- **Source:** https://arxiv.org/pdf/2605.31183 (rebuttal); AxBench source link not captured in this session.
- **What you cannot prove:** a probe's accuracy on the concept does not show the model uses it. Steering is not a guarantee against a behaviour, only a shift.
- **Relevance:** the cheapest meaningful debugging tool we could build. A probe asking "does this representation encode leverage?" is a sanity check, not a proof.

### 2.6 Critiques of SAEs (2024 to 2026)

- **Sparse probing (Kantamneni et al., February 2025):** using Gemma Scope SAEs on Gemma-2-9B and Llama Scope on Llama-3.1-8B, SAE probes underperformed logistic regression across datasets. Under distribution shift they generalised worse. The authors say the apparent SAE advantage disappeared once baselines were aggregated properly.
- **Generalisation study (arXiv 2502.19964):** on Gemma 2 SAEs, residual-stream probes beat SAE features in-domain, and out-of-domain differences were large.
- **Feature absorption (arXiv 2409.14507, 2024 but widely cited in 2025):** SAEs split and absorb features. Gemma Scope SAEs underperformed linear probes on a first-letter task, partly because of absorption.
- **Label:** EVIDENCE.
- **Source:** https://arxiv.org/abs/2502.16681 ; https://arxiv.org/abs/2502.19964 ; https://arxiv.org/html/2409.14507v3
- **Implication for us:** do not budget SAE work as our main debugging method. If we use SAEs at all, use them as a hypothesis generator and confirm with probes.

### 2.7 Which families have the best tooling

- **Gemma 3 (with Gemma Scope 2):** best-covered open family for SAEs, transcoders and Neuronpedia-hosted exploration. The 270M to 27B range is the most relevant to a small scorer. EVIDENCE for coverage.
- **Llama 3.x (Llama Scope; circuit-tracer demos on Llama-3.2-1B):** good coverage at 1B and 8B. EVIDENCE.
- **Other families** (Qwen, Mistral, Phi, OLMo): not checked this session. Fully open lineages such as OLMo matter for provenance **[memory]**.

### 2.8 Internals

The residual stream is where probes and steering live, and the natural place to ask "does the model represent leverage as a direction?". Attention shows which fields are read but is weak evidence of causal use. MLP blocks hold most features and are the hardest to read. Layer norms must be inside any bounds argument. For System One, a transformer is a debugging object, not a proof object.

---

## 3. Glass-box and structurally constrained models

### 3.1 InterpretML / Explainable Boosting Machines (EBM)

- **What it is:** a generalised additive model fit with boosting, with per-feature shape functions and a small number of pairwise interactions. Original paper 2019.
- **Monotonicity:** `monotone_constraints` per feature (+1, -1 or 0). The official docs recommend applying `monotonize` after fitting, because boosting can compensate for a constrained feature through a correlated one and hide violations. EVIDENCE of the doc, but the caveat itself is an important finding: constraints at fit time are not sufficient.
- **Label:** EVIDENCE (paper 1909.09223; docs at interpret.ml).
- **Source:** https://arxiv.org/pdf/1909.09223 ; https://interpret.ml/docs/python/api/ExplainableBoostingRegressor.html
- **What you can inspect:** each shape function is a plot; each interaction term is inspectable; the whole model is a sum of tables. Debugging is direct.
- **What you can prove:** monotonicity along a feature after `monotonize`, checked on the stored tables rather than on samples. Pairwise interactions complicate joint monotonicity; check them separately.
- **What you cannot prove:** calibration or bounds beyond what the tables permit. Coverage of rare regions depends on data.
- **Cost:** very low inference cost; training is fast on tabular data.
- **Relevance:** the strongest baseline for "readable and checkable" on tabular inputs such as our order features. The gap to examine is whether its accuracy is good enough for the endorsement task.

### 3.2 Neural additive models and the Actuarial Neural Additive Model (ANAM)

- **Neural additive models (NAM)**: one small network per feature, summed. Original idea 2021 (Agarwal et al.) **[memory]**.
- **ANAM (Laub, Pho and Wong, UNSW, arXiv 2509.08467, submitted 10 September 2025):** an inherently interpretable model for insurance pricing. Adds sparsity, smoothness and monotonicity to NAM, with lattice models for pairwise interactions. A secondary review says monotonicity is enforced strictly rather than by penalty, using monotonic lattice regression for some shape functions. A third-party implementer's blog says monotonicity comes from non-negative weights in ReLU networks. These two mechanisms are not the same, and I did not confirm either in the paper.
- **Performance claims:** a review says ANAM beats GLM, GAM, EBM and LocalGLMnet and is competitive with GBM. A blog says the EBM comparison is hard to verify from public evidence. Treat as CLAIM until the paper's tables are read.
- **Label:** EVIDENCE for the paper's existence and abstract; mechanism and performance from secondary sources are CLAIM.
- **Source:** https://arxiv.org/pdf/2509.08467 ; https://pypi.org/project/insurance-anam/0.1.0/ (a third-party implementation)
- **What you can prove:** if the non-negative-weights mechanism holds, monotonicity holds by construction for the whole network, not just on samples. That would be the most useful property we could get without a verifier.
- **Cost:** low. Training is standard.

### 3.3 Monotone by construction: non-negative weights and lattices

- **Non-negative weights with monotone activations:** a feed-forward network whose weights on a monotone input are constrained non-negative is non-decreasing in that input, if the activations are monotone non-decreasing (ReLU, sigmoid). This is standard theory **[memory]**. It is cheap and provable. The known cost: expressive capacity drops and weight constraints can hurt fit on features with non-monotone effects in the data.
- **Lattice networks (Google's TensorFlow Lattice, Deep Lattice Networks):** a lattice interpolates values on a grid of keypoints; monotonicity is enforced by constraining the lattice parameters. Used in production at Google for monotone-constrained ranking **[memory]**. I did not verify TF Lattice's specific guarantees in this session.
- **Label:** theory is EVIDENCE in general form; product claims CLAIM.
- **What you can prove:** monotonicity exactly, if the architecture is implemented correctly. Bounds on output are natural with a sigmoid or clamp at the output.
- **What you cannot prove:** that the constraint is the right constraint for the real-world risk. Monotonicity is a modelling assumption; the proof is conditional on it.

### 3.4 Certified monotonic networks (Liu, Han, Zhang, Liu, NeurIPS 2020)

- Train a general piecewise-linear network with a soft monotonicity regulariser, then check monotonicity exactly by encoding the network as a mixed-integer linear program. Increase the regulariser until the certifier passes. Outperforms Deep Lattice Networks on their benchmarks.
- **Label:** EVIDENCE (peer-reviewed NeurIPS paper).
- **Source:** https://arxiv.org/pdf/2011.10219
- **What you can prove:** exact monotonicity of the trained network over its input box. This is the strongest proof available for an ordinary feed-forward model of our kind.
- **Cost:** MILP solving scales poorly with width and depth. For a small scorer with a few dozen inputs this is feasible; it is not for large nets. The cost is in verification time, paid once per release.
- **What you cannot prove:** behaviour outside the box you verified. Calibration. Anything about the data distribution.
- **Relevance:** a good fit as a release gate: train, certify, and refuse to ship if the certificate fails.

### 3.5 Accuracy cost of monotonicity

A December 2025 preprint measures the accuracy cost of monotone constraints in XGBoost, LightGBM and CatBoost (not EBM or NAMs). EVIDENCE, preprint. Source: https://arxiv.org/pdf/2512.17945v2

---

## 4. Formal verification of small networks

### 4.1 alpha-beta-CROWN and VNN-COMP 2025

- **VNN-COMP 2025** (sixth edition; report by Kaulen et al., arXiv 2512.19007, submitted 22 December 2025): eight teams, 16 regular and 9 extended benchmarks. α,β-CROWN ranked first on the Zero Tolerance regular track (1566.9, ahead of NeuralSAT at 1430.2 and PyRAT at 1228.4) and on the Small Tolerance criterion (1600.0 against NeuralSAT's 1360.1). No time bonus was awarded in 2025.
- **Label:** EVIDENCE (competition report). The project page's claim of "top-1 in all scored benchmarks" is CLAIM by the team; I read the per-benchmark tables only in excerpt, so verify against the full PDF.
- **Source:** https://arxiv.org/pdf/2512.19007 ; https://github.com/Verified-Intelligence/alpha-beta-CROWN
- **What you can prove:** input-output properties on a fixed box, e.g. "output stays within [0, 1] for all inputs in this region" or "output is non-decreasing in feature k across this box". Both are expressible as verification queries. Verification can also return a counterexample (falsification), which is a useful debugging output.
- **What you cannot prove:** properties over unbounded inputs, properties on the training distribution without a box, or anything about the model's behaviour on real data beyond the box. Floating-point, quantised models and the exact deployment runtime are a separate gap.
- **Size limits:** the benchmark networks are small CNNs and MLPs. Verification of much larger networks is a research problem. Anything in the billions of parameters is out of reach. For a scorer of a few thousand to a few million parameters, feasibility needs a measured test on our own architecture **[memory on general scale]**.
- **Cost:** GPU time, plus a conservative bound that may be loose. A failed proof is not a counterexample.
- **Relevance:** the verifier is the practical tool for "bounded outputs" and "monotone within a box". Use it on the exported artifact, not on the training graph.

### 4.2 Marabou and NeuralSAT

- Marabou and NeuralSAT appear in the VNN-COMP 2025 standings (EVIDENCE). Use them as second opinions; if verifiers disagree, check numerical tolerance first.

### 4.3 Tolerances matter

- The VNN-COMP 2025 report scores under two tolerances (zero and small, 1e-6). A result that passes only under tolerance is a numerical result, not a clean proof. Any certificate we produce must state the arithmetic it was checked under and be re-checked on the deployed runtime.

---

## 5. Conformal prediction and risk control

### 5.1 Conformal risk control (Angelopoulos, Bates, Fisch, Lei, Schuster)

- Extends split conformal prediction to control the expected value of a monotone loss, using a calibration set and a threshold chosen to meet a target risk. Finite-sample, distribution-free under exchangeability. Tight up to an O(1/n) factor. ICLR 2024; arXiv revised as v4 in June 2025.
- **Label:** EVIDENCE (peer-reviewed; arXiv 2208.02814).
- **Source:** https://arxiv.org/abs/2208.02814 ; https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html
- **Why this matters to us:** the guarantee needs the loss to move monotonically with the threshold parameter. "Larger threshold means more conservative action" is exactly the shape of a tighten-only rule. The guarantee could be stated as: the expected loss from approvals the owner would not endorse is at most alpha, on exchangeable calibration data.

### 5.2 Non-monotone losses (2026)

- A 2026 preprint (arXiv 2604.01502) analyses non-monotone losses and proposes a finite-sample correction (CRC-NM) that controls risk uniformly over the parameter grid. It also describes a bootstrap-based stability approach. Learn-then-test (Angelopoulos et al., 2025) handles non-monotone losses through multiple testing.
- **Label:** EVIDENCE (preprint, not peer reviewed as far as I can tell).
- **Source:** https://arxiv.org/pdf/2604.01502
- **Relevance:** if our loss is not monotone in the threshold (for example, a loss that penalises both over- and under-tightening), CRC-NM or learn-then-test is the path.

### 5.3 What conformal does not give

- Exchangeability between calibration and deployment. Market regimes shift. Weighted or adaptive conformal variants exist for covariate shift **[memory]**, but a regime change breaks any guarantee unless we model it.
- It guarantees a risk level, not a model's internal correctness. A miscalibrated model can still pass a conformal guarantee through a wider threshold.
- Raw-score calibration (isotonic or Platt scaling) is a separate step and is not a conformal guarantee.

---

## 6. Provenance, reproducibility and attribution

### 6.1 Training-data attribution and influence functions

- **Grosse et al. (2023)** scaled influence functions to LLMs (up to about 52B parameters) using the EK-FAC approximation, and released Kronfluence **[memory for the original 2023 paper; the 52B figure comes from a secondary summary, TruEra]**.
- **Bao et al. (arXiv 2505.05017, IJCAI 2025):** multi-stage influence functions to attribute fine-tuned LLM predictions to pre-training data under full-parameter fine-tuning. They report EK-FAC scales better than other training-data-attribution methods; demo on dolly-v2-3b.
- **TRAK (Park et al., 2023)** is a cheaper random-projection attribution method **[memory; not verified this session]**.
- **Label:** EVIDENCE for Bao et al.; memory for the rest.
- **Source:** https://arxiv.org/pdf/2505.05017 ; a 2026 follow-up with a method for interventions on influential samples is at https://arxiv.org/pdf/2609.02771 (I read the methods section only).
- **What you can inspect:** which training examples most moved a prediction. Useful for explaining a single decision and for finding bad data.
- **What you cannot prove:** that the attributed examples caused the behaviour. Attribution is an approximation with known instability; it does not give a guarantee.
- **Cost:** large for LLMs; for a small scorer on tabular data it is cheap and plausible.

### 6.2 Model cards, data manifests and reproducible training

- Model cards are documentation, not proofs. For a scorer, the reproducible bundle should hold: data manifest with hashes and time ranges, config, seed, code commit, artifact hash, verification certificate, calibration set hash.
- **Label:** practice; no single source.

### 6.3 Provenance of the open-weight checkpoint

- Open weights are not open data. The Gemma and Llama releases are open-weight only, so System One would inherit their training-data gap unless we choose a fully open lineage.

---

## 7. What regulators expect

### 7.1 SR 11-7 and its 2026 replacement

- On 17 April 2026 the Federal Reserve (SR 26-2), OCC (Bulletin 2026-13) and FDIC replaced the 2011 model risk guidance (SR 11-7 and OCC 2011-12). Secondary sources say SR 21-8 (BSA/AML) is also superseded.
- **Disputed points:** commentary differs on whether SR 26-2 extends to AI and generative or agentic systems. One vendor says it covers AI, LLMs and agentic architectures. Another source says generative and agentic AI are explicitly out of scope. Several sources describe the guidance as non-enforceable. Effective dates are reported differently.
- **Label:** CLAIM (secondary commentary: a PwC summary, vendor blogs). The primary Fed letter was not verified in this session.
- **Source (secondary):** https://www.pwc.com/us/en/industries/financial-services/library/our-take/model-risk-guidance-private-fund-reporting-apr-24-2026.html ; primary to check: the Federal Reserve's SR 26-2 letter.
- **Implication:** whatever the scope, supervisors in model risk expect what SR 11-7 asked for: conceptual soundness, ongoing monitoring, outcomes analysis and independent validation, with documented limitations. Our debug and proof work supports those four items. We should not design around a scope reading we have not checked.

### 7.2 What a validator will ask us to explain

Based on the older framework that SR 26-2 replaces **[memory]**, a validator will want: a conceptual description and fit to use; sensitivity to each input (for example, leverage); calibration and out-of-sample evidence, including stress regimes; documented limitations; and monitoring with thresholds. Check against the SR 26-2 text.

### 7.3 Explainability in practice

- A glass-box or monotone model answers "why" directly. A transformer answers "why" only with attribution or probe evidence, which validators tend to treat as weaker.
- The strongest combined story is a readable student model (EBM or ANAM-style) with certified monotonicity, plus a verification certificate, plus conformal calibration, plus a documented teacher used only for debugging.

---

## 8. Where a moat could live

For each component: what is commoditised today, and what is not. "Commoditised" means an open tool or checkpoint can be used off the shelf without much work.

- **Data.** Commoditised: public market data, public order-book feeds, open tabular benchmarks. Not commoditised: the labelled record of what a portfolio owner actually endorsed and rejected, with the owner's stated mandate. That label is the thing competitors cannot download. Moat strength: high, if we can collect it legally and at scale.
- **Calibration layer.** Commoditised: conformal risk control and isotonic or Platt scaling are published and implemented in open libraries. Not commoditised: a defensible loss function that maps "endorsement" into a monotone risk, and the operational discipline to refresh calibration sets under regime shift. Moat strength: medium.
- **Architecture.** Commoditised: monotone constraints in EBM, lattice networks, non-negative-weight networks, NAM variants. Not commoditised: knowing which monotone family fits the endorsement task with the least accuracy loss, measured on our data. Moat strength: low to medium; the architecture itself is public.
- **Training procedure.** Commoditised: boosting with monotone constraints, regularised training, certified-regulariser loops (the NeurIPS 2020 method). Not commoditised: the combined procedure that trains, certifies, monotonises and calibrates in one reproducible pipeline with a release gate. Moat strength: medium, mostly in engineering.
- **Verification.** Commoditised: alpha-beta-CROWN and other top verifiers are open and ranked; MILP certification is published. Not commoditised: the mapping from our mandate-level properties (for example "more leverage never raises approval within a limit box") to verification queries, and the tolerance-aware certificate that a regulator can read. Moat strength: medium, and it grows with our own property library.
- **Interpretability.** Commoditised: SAEs, transcoders, attribution graphs and probes are all public for Gemma and Llama. Not commoditised: knowing which of them actually helps for a small scorer, which the 2025 evidence says is probably few. Moat strength: low for the tools, medium for the evaluation method that decides when they help.

---

## 9. Ideas we have probably not considered

1. **Monotone-by-construction plus certify-at-export.** Build monotonicity into the architecture (non-negative weights or lattices), then still run a certifier on the exported artifact in CI. Two independent guarantees, one cheap, one checkable.
2. **Conformal guarantee on the tightening function itself.** Choose the tightening map so that CRC with a monotone loss gives "expected unendorsed approvals at most alpha" on calibration data. This is a regulator-readable sentence.
3. **Student-teacher split.** Use an open-weight transformer and its SAEs only to debug and to generate candidate features; ship an EBM or ANAM-style student. Measure fidelity between them. The student is what gets proved.
4. **Metamorphic tests as the regression suite.** Encode the mandate as invariance and monotonicity relations (double the size, the score must not rise), run them on every retrain. Cheaper than verification and catches most regressions.
5. **Abstention by conformal set size.** When the prediction set spans both approve and reject, default to tightening. This turns calibration uncertainty into the safe direction by design.
6. **Regime-shift conformal.** Use weighted or adaptive conformal updates on volatility or liquidity features, so the guarantee degrades visibly rather than silently when markets change.
7. **Attribution on decisions that reach a regulator.** Store a TRAK-style or EK-FAC-style pointer from each high-impact score to its most influential training examples. Costly, but it answers "why this number".
8. **Evidence bundle as the product.** A signed release containing the certificate, calibration report, data manifest and metamorphic results, shared with owners and their validators instead of raw weights.
9. **Provenance as a base-model choice.** Pick a base with documented training data even if its SAEs are weaker. A validator may value provenance more than interpretability tooling.

---

## 10. Open questions and what to check next

- Read the Fed SR 26-2 letter and the OCC bulletin to settle the AI-scope question.
- Read arXiv 2509.08467 to settle whether ANAM monotonicity is by construction or by lattice.
- Run the NeurIPS 2020 certifier on a small monotone scorer to get a real verification time.
- Verify TRAK, Grosse et al. (2023) and TF Lattice guarantees directly; all three are from memory here.
