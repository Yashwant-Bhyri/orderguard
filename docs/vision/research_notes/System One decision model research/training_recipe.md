# Training recipe for System One: a domain-specific, calibrated decision model

Scope: how a specialised judge that reads a typed delegation record and outputs calibrated probabilities ("serves purpose?", "evidence supports claim?", "context corrupted?", "adaptation or drift?") would be trained. Current as of November 2026. Searched 2026-11-17.

Source note: items marked [prior knowledge, not re-fetched] are well-known primary papers cited by arXiv ID from the researcher's background knowledge; they were not opened in this session and the report writer should verify the exact figures before quoting numbers from them. Everything else was found in this session's searches.

## 1. Base model choice, and whether small fine-tuned judges match frontier models

### Takeaway
On narrow, well-defined classification tasks, small fine-tuned models (100M to 8B) repeatedly match or beat zero-shot frontier models, but the wins are task-specific and mostly self-reported; for System One the evidence favours a small model (1B to 8B decoder, or an encoder) fine-tuned on in-domain labels, with a frontier model used as a teacher and an independent check, not as the production judge.

### Cited Findings
- Fine-tuned BERT-style models beat zero-shot GPT-3.5, GPT-4 and Claude Opus on sentiment, stance, emotion and party-position classification; gains level off at roughly 200 labelled examples per task. Single preprint; other work finds rough parity on some tasks — [Bucher and Martini 2024, arXiv 2406.08660](https://arxiv.org/abs/2406.08660)
- Llama Guard 3 1B (INT4, about 440MB, compressed from Llama 3.2 1B, distilled from an 8B teacher) reports English F1 0.904 / false-positive rate 0.084 versus GPT-4 zero-shot 0.805 / 0.152 on Meta's internal test set; the 8B version scores 0.939 / 0.040. On XSTest, GPT-4 does better (0.895 F1) than the 1B-INT4 (0.737). Meta's own test set — [Llama Guard 3 1B model card](https://huggingface.co/alpindale/Llama-Guard-3-1B); [Meta paper, arXiv 2411.17713](https://arxiv.org/html/2411.17713v1)
- A 2026 EMNLP comparison of 53 models found large commercial models (GPT-4.1, GPT-5, Gemini 2.5 Pro and others) score highest on a broad safety benchmark, with Llama-Guard-3-8B having the highest QA point estimate (78.6%). This is a caution: small guards win on the distribution they were trained for, not universally — [EMNLP 2026 main 1748](https://aclanthology.org/2026.emnlp-main.1748.pdf)
- GLIDER (3.8B judge, Patronus AI) reports higher correlation with human ratings than GPT-4o on FLASK, but its own pairwise F1 table shows GPT-4o ahead on most datasets — [GLIDER, arXiv 2412.14140](https://arxiv.org/html/2412.14140v2)
- Prometheus 2 (7B and 8x7B) halves the agreement gap to GPT-4 among open evaluators; it does not claim to beat GPT-4 — [Prometheus 2, arXiv 2405.01535](https://arxiv.org/html/2405.01535v2)
- Atla Selene Mini (8B) is claimed to beat GPT-4o on RewardBench, EvalBiasBench and Auto-J; vendor blog, not independent — [Atla blog](https://www.atla-ai.com/post/selene-1-mini)
- Distilling step-by-step: a 770M T5 trained on LLM rationales plus labels beats few-shot 540B PaLM on ANLI using 80% of the training data; a 220M T5 beats PaLM on e-SNLI. Baseline is few-shot PaLM, not fine-tuned PaLM — [Google Research blog](https://research.google/blog/distilling-step-by-step-outperforming-larger-language-models-with-less-training-data-and-smaller-model-sizes/); [arXiv 2305.02301](https://arxiv.org/abs/2305.02301)

### Inferences
- Encoder vs decoder: an encoder (ModernBERT/DeBERTa class) with classification heads gives native probabilities and cheap multi-task heads, but caps context length and cannot produce a rationale. A 1B to 8B decoder can read a long serialised trace and emit a rationale plus a confidence, and is the only option compatible with RLCR-style calibration training (section 2). A sensible first build is both: an encoder or tabular model as the fast first pass, a small decoder for cases the first pass is unsure about.
- Reasoning vs non-reasoning: reasoning tokens cost latency on a pre-trade path. Distilled reasoning (rationale used in training, short or no rationale at inference, as in distilling step-by-step) is the pattern most consistent with a latency budget.
- Every "small beats frontier" claim above is on the vendor's own or a narrow test set. The honest claim for System One is "matches a frontier judge on our held-out families at a fraction of the latency and cost," and that has to be measured, not assumed.

### Gaps
- No published head-to-head of small judges vs frontier models on financial or agent-delegation judgement tasks was found.
- Lynx (Patronus hallucination judge) results were not retrieved in this session.

## 2. Post-training methods: SFT, preference optimisation, RLVR, calibration rewards, rejection sampling, distillation, multi-task heads

### Takeaway
The best-evidenced recipe for a calibrated judge is: SFT warm-up on expert or teacher-labelled examples (with rationales), then RL with a reward that combines correctness and a proper scoring rule (RLCR), then post-hoc recalibration checked under shift. Plain binary-reward RLVR improves accuracy but measurably damages calibration, which is exactly the property System One sells.

### Cited Findings
- RLCR (Damani et al., ICLR 2026): the model outputs an answer and a numeric confidence; reward = correctness + negative Brier score. Bounded proper scoring rules make the joint objective incentive-compatible (any bounded proper rule works in place of Brier). On HotpotQA, ECE falls from 0.37 (RLVR) to 0.03 and Brier from 0.37 to 0.21 with no accuracy loss; plain RLVR degrades out-of-distribution calibration relative to the base model. Base model Qwen2.5-7B, GRPO, light SFT warm-up for maths — [arXiv 2507.16806](https://arxiv.org/abs/2507.16806); [HTML v2](https://arxiv.org/html/2507.16806v2); [ICLR 2026 poster](https://iclr.cc/virtual/2026/poster/10011036)
- Verbalised confidence from RLCR can be used at test time for confidence-weighted aggregation, improving both accuracy and calibration — [arXiv 2507.16806](https://arxiv.org/html/2507.16806v2)
- RLVR mostly sharpens sampling of answers the base model could already reach: RL-trained models beat base models at pass@1 but base models win at large k; six RLVR algorithms perform similarly; the capability boundary often narrows during RLVR; distillation from a stronger teacher does add new reasoning patterns. NeurIPS 2025 oral — [Yue et al., arXiv 2504.13837](https://arxiv.org/abs/2504.13837)
- s1: SFT on 1,000 carefully selected reasoning traces made a 32B Qwen model competitive with o1-preview on maths; training took 26 minutes on 16 H100s. Cost sat in data curation (59K candidates filtered to 1K) — [s1, arXiv 2501.19393](https://arxiv.org/html/2501.19393v1); [project page](https://simplescaling.github.io)
- Llama Guard 3 1B was produced by pruning plus distillation from an 8B teacher and quantisation to INT4, ending near the 8B's quality at about 1/7 the size — [arXiv 2411.17713](https://arxiv.org/html/2411.17713v1)
- Distilling step-by-step trains labels and rationales as two tasks in one multi-task setup; this multi-task framing is what produces the data efficiency — [arXiv 2305.02301](https://arxiv.org/abs/2305.02301)
- DPO optimises preferences directly without a separate reward model [prior knowledge, not re-fetched] — [Rafailov et al., arXiv 2305.18290](https://arxiv.org/abs/2305.18290)
- DeepSeek-R1 distilled reasoning into small Qwen and Llama models via SFT on about 800K curated samples [prior knowledge, not re-fetched; search could not confirm the 800K figure] — [DeepSeek-R1, arXiv 2501.12948](https://arxiv.org/abs/2501.12948)
- Temperature scaling as the standard post-hoc calibration fix [prior knowledge, not re-fetched] — [Guo et al. 2017, arXiv 1706.04599](https://arxiv.org/abs/1706.04599)

### Inferences
- Map to System One:
  1. SFT stage: (record, question) -> (short rationale, label, probability). Labels from simulator ground truth (section 3) and from a frontier teacher's rationales filtered by agreement with ground truth (rejection sampling: keep only teacher traces whose verdict matches the known outcome).
  2. RL stage: GRPO with RLCR reward, where "correctness" is the simulator's known outcome. This is a verifiable reward because the arena knows the long-run result. Brier or log-loss over the stated probability is the calibration term.
  3. Multi-task heads: the four questions share one encoder of the record; separate heads (or separate prompts to one decoder) avoid training four models and let rare tasks borrow signal from common ones.
  4. Post-hoc: temperature or isotonic recalibration per question on a held-out set, re-checked on shifted sets because section 6 shows in-distribution calibration does not transfer.
- DPO is a weak fit for the core task: System One's targets are probabilities against outcomes, not pairwise preferences. DPO is useful only for the rationale style (preferring rationales that cite the right evidence field).
- Given Yue et al., RL will not teach the model new detection skills its base lacks; new skills come from the data (adversarial families, teacher distillation). RL's job here is calibration and sharpening.

### Gaps
- No published RLCR replication on a non-QA, structured-record domain was found.
- No reported GPU-hour figure for the RLCR training runs was retrieved.

## 3. Simulation and synthetic data: labelled episodes, sim-to-real, adversarial generation, rare-event labels in other domains

### Takeaway
Every mature rare-event domain combines three data sources: large volumes of real or realistic traffic, simulation or synthesis targeted at the long tail, and deliberate adversarial generation, with real-world labels kept as the final judge. OrderGuard's arena gives the simulated tail; it lacks the real-traffic base and needs an explicit sim-to-real check.

### Cited Findings
- Stripe's Payments Foundation Model is self-supervised on tens of billions of transactions, producing a dense embedding per transaction; a downstream classifier reads sequences of embeddings to flag attacks. Stripe reports card-testing detection on large users rising from 59% to 97%. Company-reported, not independently audited — [Stripe Sessions 2025 newsroom](https://stripe.com/newsroom/news/sessions-2025); [Stripe blog](https://stripe.com/en-ee/blog/using-ai-optimize-payments-performance-payments-intelligence-suite)
- Anthropic's Constitutional Classifiers: a written constitution of allowed and disallowed categories drives synthetic prompt and completion generation, which trains input and output classifiers. Over about 3,000 hours of human red teaming (about 183 participants) no universal jailbreak was found; automated jailbreak success fell from 86% unguarded to far lower; an updated version added only 0.38% refusal increase at moderate compute cost — [Anthropic research](https://anthropic.com/research/constitutional-classifiers); [arXiv 2501.18837](https://arxiv.org/abs/2501.18837)
- Waymo World Model (Feb 2026, built on DeepMind Genie 3) generates rare scenarios (tornado, elephant) that are impractical to capture at scale, with control over driving actions, scene layout and language, and supports counterfactual "what if the car had driven more assertively" tests. Waymo argues reconstruction methods break down when the simulated route diverges from the logged one. Company claims — [Waymo blog](https://waymo.com/blog/2026/02/the-waymo-world-model-a-new-frontier-for-autonomous-driving-simulation)
- Waymax initialises simulations from real logged driving data; WOD-E2E is curated for long-tail scenarios each occurring under 0.03% of the time — [search summary of Waymo research; see Waymo blog above]
- Agent-based market simulators (ABIDES) are calibrated by matching stylised facts (heavy tails, no return autocorrelation, volatility clustering); choosing which facts to match introduces human bias, real data does not always satisfy all stylised facts, and many simulators have low behavioural fidelity. Embedding-network and Bayesian calibration are proposed fixes — [arXiv 2402.09563](https://arxiv.org/html/2402.09563v2); [arXiv 2307.12987](https://arxiv.org/html/2307.12987v3); [arXiv 2311.11913](https://arxiv.org/pdf/2311.11913v2.pdf)
- Fraud detection works under concept drift, extreme class imbalance and verification latency (most labels arrive days later via customer reports). Dal Pozzolo et al. train one classifier on fast investigator feedback and one on delayed labels and combine them, improving alert precision — [Dal Pozzolo et al. 2015 IJCNN](https://boracchi.faculty.polimi.it/docs/2015_04_Credit_Card_Fraud_Detection_DalPozzolo_Boracchi_Caelen_Alippi_Bontempi.pdf)
- Under delayed labels, drift is detectable only when P(y|X) shifts together with P(X) — [E-commerce fraud research agenda, arXiv 2107.01979](https://arxiv.org/pdf/2107.01979)

### Inferences
- The arena should be used the way Waymo uses its world model: to generate and label the tail (corruption, drift, adversarial citations) and to run counterfactuals, not as the sole source of the base distribution.
- The Constitutional Classifiers pattern transfers almost directly: write a "delegation constitution" (what serving the purpose means, what counts as drift), generate synthetic violating and benign records from it with an LLM, and train on them. Their result that synthetic-only training survived 3,000 hours of human attack is the strongest public evidence that synthetic adversarial data generalises.
- The 0.97 -> 0.63 drop is the classic sign of a model learning simulator-specific shortcuts. Remedies, in order: hold out whole attack families (section 6), add an automated attacker that is rewarded for fooling the current judge (red-team loop), and randomise simulator parameters (domain randomisation) so no single stylised-fact setting is learnable.
- Sim-to-real check: before trusting arena labels, show the arena reproduces the stylised facts OrderGuard cares about, and keep a small set of real or replayed-real episodes with independent labels as the final gate.

### Gaps
- No public detail on Stripe Radar's labelling pipeline beyond the foundation-model announcement was retrieved (e.g., how chargeback delay is handled in training).
- No published study of sim-to-real transfer for a judge of AI trading agents exists that this search found.

## 4. Learning from delayed outcomes

### Takeaway
System One's labels (did this action hurt the owner months later) are delayed and confounded by what the guard itself allowed; the relevant tools are fraud-style dual-speed labelling, hindsight relabelling in the simulator, and off-policy evaluation to estimate how a new gate would have done on logged traffic it did not control.

### Cited Findings
- Dual-model approach for fast feedback plus delayed labels in fraud — [Dal Pozzolo et al. 2015](https://boracchi.faculty.polimi.it/docs/2015_04_Credit_Card_Fraud_Detection_DalPozzolo_Boracchi_Caelen_Alippi_Bontempi.pdf)
- Drift detection with delayed labels is an open problem as of 2021 — [arXiv 2107.01979](https://arxiv.org/pdf/2107.01979)
- Waymo's counterfactual testing (what would have happened under a different action) is the simulation analogue of off-policy evaluation — [Waymo blog](https://waymo.com/blog/2026/02/the-waymo-world-model-a-new-frontier-for-autonomous-driving-simulation)
- Hindsight Experience Replay relabels failed trajectories with the goal actually achieved, turning sparse delayed reward into dense signal [prior knowledge, not re-fetched] — [Andrychowicz et al., arXiv 1707.01495](https://arxiv.org/abs/1707.01495)
- Conservative Q-Learning penalises value estimates for actions outside the logged data, the standard guard against offline-RL overestimation [prior knowledge, not re-fetched] — [Kumar et al., arXiv 2006.04779](https://arxiv.org/abs/2006.04779)
- Doubly robust off-policy evaluation combines a reward model and importance weights to evaluate a new policy on logs from an old one [prior knowledge, not re-fetched] — [Dudík et al., arXiv 1103.4601](https://arxiv.org/abs/1103.4601)

### Inferences
- In the arena, long-run outcomes are known, so the delayed label can be attached to the decision point directly (hindsight labelling). Temporal credit assignment then becomes: which of the actions in the trace caused the eventual loss. A practical approach is counterfactual replay: re-run the episode from the decision point with the action blocked and label the action by the outcome difference. This needs the simulator to be cheap enough to branch.
- In production, labels will be delayed and biased by the guard's own blocks (blocked actions never produce outcomes). Off-policy evaluation, or a small randomised "allow with monitoring" slice, is needed to measure the guard honestly; fraud teams face the same selection problem.
- System One is a classifier, not a policy, so full offline RL is probably unnecessary. Credit assignment and counterfactual labels are what matter.

### Gaps
- No source in this session quantified how much counterfactual branching costs or how many branches per decision are needed for stable labels.

## 5. Structured inputs: tabular/graph models vs text serialisation; neuro-symbolic hybrids

### Takeaway
For numeric features of a delegation record (exposure history, limits, position changes) a tabular foundation model or gradient-boosted trees is the strong, cheap baseline; text serialisation into an LLM is needed only for the free-text parts (purpose, thesis, evidence, trace). The likely best design is hybrid: code computes typed features, a tabular model scores them, a small LLM reads the text fields, and a final calibrated combiner weighs both.

### Cited Findings
- TabPFNv2 (Nature, January 2025) is a transformer pretrained on synthetic tabular tasks that predicts in one forward pass, strong up to 10,000 samples and 500 features — [TabPFN-2.5 report, arXiv 2511.08667](https://arxiv.org/abs/2511.08667v2)
- TabPFN-2.5 (Nov 2025) extends to 50,000 rows and 2,000 features (20x the cells), reports beating tuned XGBoost and AutoGluon on TabArena-lite, and a real-data fine-tuned variant (Real-TabPFN-2.5) does better still; a later "Scaling Mode" handles millions of rows. Author-reported — [arXiv 2511.08667](https://arxiv.org/abs/2511.08667v2); [Prior Labs scaling mode](https://priorlabs.ai/technical-reports/large-data-model)
- TabPFN is itself trained entirely on synthetic data from a prior over generating processes — the same idea as using a simulator to generate training tasks — [arXiv 2511.08667](https://arxiv.org/abs/2511.08667v2)
- Stripe's design is a hybrid: a foundation model embeds each transaction, then a separate classifier reads sequences of embeddings — [Stripe newsroom](https://stripe.com/newsroom/news/sessions-2025)
- Set Transformers handle permutation-invariant sets (e.g., a set of open theses or positions) [prior knowledge, not re-fetched] — [Lee et al., arXiv 1810.00825](https://arxiv.org/abs/1810.00825)

### Inferences
- The existing logistic baseline is already a "code computes features, model weighs them" design. Its failure under shift suggests the features, not the weigher, are the weak link: adversarial episodes change the text-level content (fake citations, poisoned context) that hand features do not see.
- Recommended stack: (a) deterministic features plus TabPFN or GBDT for the numeric half; (b) small LLM for the text-reasoning questions (evidence support, context corruption); (c) a calibrated stacker over both, trained on held-out data. This keeps most decisions fast and auditable and reserves LLM calls for the questions only language can answer.
- Graph neural nets are worth it only if the record has real relational structure across agents (e.g., the million-agent arena's interaction graph for swarm or collusion detection); for a single delegation record a set or sequence model is enough.

### Gaps
- No direct comparison of TabPFN vs LLM-over-serialised-records on the same structured decision task was retrieved.
- TabPFN's behaviour under adversarial (not natural) shift was not found.

## 6. Evaluation: held-out families and time, adversarial shift, calibration under shift, lead time vs false alarm, independent labels

### Takeaway
Calibration measured in distribution does not survive shift, models become "confidently wrong," and LLM judges favour outputs that resemble their own; so System One's evaluation must hold out whole attack families and time periods, report calibration on those shifted sets, and use labels that come from outcomes or independent humans, never from the model or its teacher.

### Cited Findings
- Under dataset shift, post-hoc calibration such as temperature scaling falls short; improving in-distribution calibration often makes shifted calibration worse; models become confidently wrong rather than uncertain; deep ensembles of about 5 members were the most robust method tested. Covers images, text, ads and genomics — [Ovadia et al., NeurIPS 2019](https://papers.nips.cc/paper/2019/hash/8558cb408c1d76621371888657d2eb1d-Abstract.html); [Google Research blog](https://research.google/blog/can-you-trust-your-models-uncertainty/)
- LLM evaluators recognise their own outputs above chance (GPT-3.5, GPT-4, Llama 2) and self-recognition strength correlates linearly with self-preference bias — [Panickssery et al., NeurIPS 2024](https://papers.nips.cc/paper_files/paper/2024/hash/7f1f0218e45f5414c79c0679633e47bc-Abstract-Conference.html); [arXiv 2404.13076](https://arxiv.org/abs/2404.13076v1)
- RLVR degrades out-of-distribution calibration; RLCR reports improvement in both in-domain and out-of-domain evaluation — [arXiv 2507.16806](https://arxiv.org/abs/2507.16806)
- Constitutional Classifiers were validated by external human red teamers (3,000 hours) as well as automated attacks — the attacker was independent of the training data — [Anthropic](https://anthropic.com/research/constitutional-classifiers)
- Fraud teams measure alert precision because investigator capacity, not AUROC, is the binding constraint — [Dal Pozzolo et al. 2015](https://boracchi.faculty.polimi.it/docs/2015_04_Credit_Card_Fraud_Detection_DalPozzolo_Boracchi_Caelen_Alippi_Bontempi.pdf)

### Inferences
- Splits: (1) held out by attack family (train on prompt injection and fake citations, test on context poisoning); (2) held out by time (train on earlier simulated regimes, test on later); (3) held out by simulator configuration; (4) a small real or replayed-real set. Report AUROC, Brier, ECE and reliability diagrams on each, not just the pooled number.
- The headline metric for a pre-trade gate is closer to fraud's: false alarms per thousand actions at a fixed recall, and lead time (how many steps before loss the risk crossed threshold) against false-alarm rate. Plot this as a curve.
- Independence: never let the teacher model that wrote rationales also label the test set; never evaluate with a judge from the same family as System One's base model (self-preference). Ground truth for the test set should be simulator outcomes plus human-reviewed real cases.
- Ensembling (5 seeds or 5 heads) is the cheapest measured defence for calibration under shift and should be the default before more exotic methods.

### Gaps
- No public "lead time vs false alarm" benchmark for agent-supervision systems was found; OrderGuard would be defining it.

## 7. Compute and data budgets for comparable specialised models

### Takeaway
Reported numbers suggest the fine-tuning itself is cheap (minutes to a few GPU-days for 1B to 8B models); the real costs are data curation, simulator rollouts for labels and counterfactuals, and red teaming.

### Cited Findings
- s1-32B: 1,000 examples, 26 minutes on 16 H100s (about 7 H100-hours); curation from 59K candidates was the main effort — [arXiv 2501.19393](https://arxiv.org/html/2501.19393v1)
- Fine-tuned BERT-class classifiers plateau around 200 labelled examples per task on the tested tasks — [arXiv 2406.08660](https://arxiv.org/abs/2406.08660)
- RLCR trains a 7B model (Qwen2.5-7B) with GRPO; no GPU-hour figure retrieved — [arXiv 2507.16806](https://arxiv.org/abs/2507.16806)
- Llama Guard 3 1B: distilled and quantised to about 440MB for on-device use — [arXiv 2411.17713](https://arxiv.org/html/2411.17713v1)
- Stripe: tens of billions of transactions for self-supervised pretraining (the scale tier OrderGuard does not have) — [Stripe newsroom](https://stripe.com/newsroom/news/sessions-2025)
- Constitutional Classifiers: about 3,000 human red-teaming hours for validation; the production version runs at "moderate" additional inference compute — [Anthropic](https://anthropic.com/research/constitutional-classifiers)
- TabPFN needs no training per task (one forward pass); fine-tuning on real data is optional — [arXiv 2511.08667](https://arxiv.org/abs/2511.08667v2)

### Inferences
- A plausible first budget for System One, extrapolated from the above (not a sourced figure): 10K to 100K labelled arena episodes across at least 8 attack families; a few thousand teacher rationales filtered by outcome agreement; SFT of a 1B to 8B model in single-digit GPU-hours to a few GPU-days; one RLCR run on a 7B model in the range of tens to low hundreds of GPU-hours; plus TabPFN/GBDT on features at near-zero training cost. The simulator rollouts (especially counterfactual branches) will likely dominate compute.
- Order of work that spends least before learning most: (1) fix the evaluation splits and re-score the logistic baseline on them; (2) add a 5-member ensemble and TabPFN on the same features; (3) add a small fine-tuned LLM for the text questions; (4) only then RLCR.

### Gaps
- No public compute figures for a calibration-trained judge in finance or risk were found.
- No public compute for Stripe's foundation model or Radar retraining cadence was found.
