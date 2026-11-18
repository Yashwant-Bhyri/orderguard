# Scan 01: Architectures and model families for System One

Date of scan: 2026-11-19
Angle: newest architectures and model families that could be System One (fast, small, calibrated model that scores an agent's proposed action and trace, and outputs P(owner endorses) plus purpose). Options only, no decision.

## Method and caveats

- Web search only. Sources were arXiv papers, vendor pages, vendor-run benchmarks, Substack and blog posts.
- Searches with `site:x.com`, and general queries for Hacker News threads, returned no x.com or news.ycombinator.com pages. The "what practitioners say right now" section is therefore thin and is mostly secondary blog commentary. This is a gap, not a finding that practitioners are silent.
- Many 2026 model names (TabPFN-3, TabPFN-3.5, LimiX-2, LimiX-2M, TabICLv2) appeared only in search snippets, secondary guides or vendor pages. Treat their numbers as unverified until the full paper or model card is read.
- Labels: EVIDENCE = paper, benchmark or code. CLAIM = blog, tweet, vendor or marketing.
- Latency and size figures below are as reported; where none were found, the entry says so.

---

## 1. Tabular foundation models (TFMs)

### 1a. TabPFN family (Prior Labs)

- **What it is:** Transformer pretrained on synthetic tabular datasets. Predicts on a new table in one forward pass, with no per-dataset training (in-context learning). TabPFN v2 was published in Nature in early 2025.
- **Versions:** TabPFN-2.5 report (arXiv 2511.08667) scales to about 50,000 rows and 2,000 features, and reports strong results up to 100,000 training rows. Its authors say it has 18 layers. A distillation engine converts the model to a compact MLP or tree ensemble (EVIDENCE for the report; the distillation speedup is CLAIM until we see numbers).
- **Later versions:** Secondary sources say TabPFN-3 (about May 2026) and a TabPFN-3.5 (about Sept 2026) exist, with a higher-performance variant described as API-only. Source: vendor and blog pages only (CLAIM).
- **Latency and size:** Not measured here. Inference is described as slow in some practitioner guides, with optimisation underway (CLAIM).
- **Calibration:** Prior Labs says it is designed to be well calibrated without tuning (CLAIM from vendor report). Independent TabTune benchmark (arXiv 2511.02802, EVIDENCE) finds ECE and Brier for TabPFN-2.5 in the same range as TabPFN-2.0 and OrionMSP, with no clear win. No independent large-data calibration study found.
- **Mixed tabular, graph, text input:** Tabular only. Text must be pre-embedded into columns. Graph structure must be turned into features. No native graph or text pathway.
- **Licence:** TabPFN-2.5 weights are for research and non-commercial use; commercial use requires a contract (EVIDENCE from the project page). This matters for a product.
- **Trade-off:** Strongest zero-shot tabular prior we found, but the calibration advantage is vendor-claimed, it is limited to tabular input, and the licence blocks a commercial product without a deal.

### 1b. TabICLv2 (arXiv 2602.11139, Feb 2026)

- **What it is:** In-context learning TFM for classification and regression, with a new synthetic prior generator and architecture changes. Authors released code and weights (EVIDENCE: paper, release claimed).
- **Latency and size:** Paper says "faster and scalable" than predecessor. No numbers collected here.
- **Calibration:** Not characterised in the snippets we saw.
- **Mixed input:** Tabular only.
- **Trade-off:** Open weights and a permissive route to a product, but we have not checked its calibration or latency numbers.

### 1c. Mitra (AWS, mixed prior)

- **What it is:** TFM trained on mixed synthetic priors (SCM plus tree ensembles), with hybrid row and column attention (described in the LimiX-2M paper and TabICLv2 paper).
- **Latency:** A vendor-run benchmark (see 1e) reports Mitra-v2 at about 1.5 seconds per fold and the fastest of the foundation models in that test (CLAIM).
- **Calibration and mixed input:** Tabular only.
- **Trade-off:** Fast in one vendor test but reported behind TabICLv2 and LimiX on accuracy in the same test.

### 1d. LimiX and LimiX-2M

- **What it is:** LimiX is a tabular foundation model family. LimiX-2M (arXiv 2606.04485, June 2026) is a 2-million-parameter variant that its authors say beats TabPFN-v2 (7M) and TabICL (27M) on most benchmarks, with lower train and inference cost. Its paper targets low-rank collapse and attention bottlenecks (EVIDENCE for paper; authors include Stable AI-affiliated people, so the claim needs independent checking).
- **Size:** 2M parameters. This is the smallest TFM we found with a claimed quality lead. It is the most relevant size class for a millisecond budget.
- **Calibration:** Not reported in snippets.
- **Mixed input:** Tabular only.
- **Trade-off:** Smallest of the strong TFMs and the best fit for latency, but the evidence is self-reported and we have not checked its calibration.

### 1e. Cross-model comparison and ensembling

- **AIMultiple tabular models page** (updated Oct 2026, CLAIM, vendor-run): 19 datasets; ranks LimiX-2 above TabICLv2, Mitra-v2 and TabPFN-3. Says every foundation model except Mitra beats every classical model in all six regimes.
- **Ensembling study** (arXiv, May 2026, EVIDENCE): six TFMs on 153 OpenML classification tasks. Median accuracy spread between best and worst TFM on one dataset is 1.95%. Recommends greedy selection for ensembling.
- **Limits, all families:** TFMs are mostly tested on classic tabular tasks with at most tens of thousands of rows. Our input is a mix of numbers, a graph and short text. None of these tested graph or text input. Calibration on rare, adversarial or out-of-distribution theses (the exact case that matters for an action gate) was not found in any source.
- **Practitioner view (CLAIM):** Blog guides name TabICL-v2 as a personal default and list TabPFN-3, TabICL-v2 and TabFM as the three leaders. A Qlik overview says zero-shot TabPFN-3 sits within 45 Elo of the best tuned model on 10K–100K rows. A guide puts the sweet spot near 10,000 rows, 100 columns, and says boosted trees pull ahead above about 50,000 rows.
- **Gradient boosting still a fair baseline:** The TabPFN-2.5 report says the default model beats one-hour tuned GBDT, but later analyses say "competitive" rather than "dominant" (CLAIM).

**Trade-off summary for TFMs:** Best zero-shot prior for small structured data and a natural candidate for the numeric-features branch. Weak on graph and text inputs, uncertain calibration in the tails, and licence limits on the strongest TabPFN.

---

## 2. Graph models over traces and provenance graphs

- **What we found:** Only generic graph anomaly detection work from 2026.
  - TA-GGAD (arXiv 2603.09349, March 2026): testing-time adaptive graph anomaly detection foundation model; 14 real graphs; code linked (EVIDENCE).
  - TFM4GAD (WWW '26, April 2026): adapts tabular foundation models to graph anomaly detection by treating node features as a table (EVIDENCE per abstract). Relevant idea: a TFM on graph-derived features, with no graph message passing.
  - AnomalyGFM (KDD 2025): zero- and few-shot graph anomaly detection with learned normal and abnormal prototypes (EVIDENCE).
- **Gap:** No paper found on provenance graphs or agent execution traces as an input to a learned scorer. The graph-ML papers above target fraud or social-network anomalies, not causal traces of LLM agents.
- **Fit for System One:** A GNN or graph transformer over the trace could produce a pooled trace embedding. Cost is a message-passing pass on a small graph, which should be fast. Calibration of graph anomaly scores is not established in these sources (they report AUC-type metrics).
- **Trade-off:** The graph branch is the least tested part of the design. Using graph-derived summary features in a TFM (the TFM4GAD idea) is the lower-risk path.

---

## 3. Small LMs as classifiers, verifiers and guardrails

### 3a. Guardrail models for tool calls and agent trajectories

- **ToolSafe / TS-Guard** (arXiv 2601.10156, Jan 2026, EVIDENCE): a dedicated step-level guardrail model for tool invocation. Reports about 8x less time per check than guardrail-agent methods such as AGrail, and better safety on general tool use. Model size and per-check latency not captured in snippets.
- **TraceSafe** (arXiv 2604.07223, April 2026, EVIDENCE): benchmark for guardrails on multi-step tool-calling trajectories. Concludes that current guardrails are inadequate for multi-step tool-call detection. Directly relevant to the trace input; no latency table seen.
- **Jev / Arize** (CLAIM, vendor): median 104 ms per call versus 1,915 ms for an LLM-as-judge guardrail, same decisions reported.
- **Mastyf Guard 1.5B** (CLAIM, Hugging Face card): claims 180–920 ms per tool call latency for existing guardrails. Self-reported.
- **Artificial Analysis with NVIDIA guardrail benchmark** (EVIDENCE-leaning, independent): safety, refusal and latency over 450 fixed prompts. Snippets had no numbers. Worth reading the full table.
- **Prompt Guard class (about 86M parameters)** (CLAIM, practitioner post): a classifier that costs a fraction of a frontier call.
- **Latency budget (CLAIM, Future AGI guide):** a tool-call rail should stay under about 100 ms p50 because it blocks an outbound side effect.

**Trade-off:** Small dedicated classifiers beat LLM judges on latency in every source. The ToolSafe result is the most rigorous. They classify safety of an action, not owner endorsement, so the label set is different and needs new data.

### 3b. Small LM as a verifier in general

- **SAPO** (AAAI 2026, arXiv 2601.20312, EVIDENCE): self-improvement for small reasoners that narrows the gap between reasoner and verifier; introduces process-reward benchmarks for math and code.
- **"When Small Models Are Right for Wrong Reasons"** (arXiv 2601.00513, Jan 2026, EVIDENCE per abstract): 7–9B agents; verification capability distilled into a neural classifier with 0.86 F1 and about 100x speedup (figures as reported in the search summary). Shows that correct outcomes can come from flawed reasoning, which argues for checking the trace, not only the outcome.

**Trade-off:** A 7–9B model is probably too slow for the millisecond target unless distilled to a classifier head, as that paper does. Distillation into a small head is the path that fits the budget.

---

## 4. Reward models and process reward models (PRMs)

- **Web-Shepherd** (NeurIPS 2025 spotlight, EVIDENCE per summary): first process reward model for web agent trajectories; scores each action, not the outcome. Closest published match to action-level judging of agents. Size and latency not captured.
- **ThinkPRM** (arXiv 2504.16828, EVIDENCE): repurposes reasoning models as generative step-level verifiers. Beats discriminative PRMs on ProcessBench, MATH-500 and AIME '24 under best-of-N and guided search. Generates a rationale per step, so latency is high (inference is long-form).
- **Calibration of PRMs:** Scores from PRMs are not probabilities by default. None of the sources we read reported ECE for a PRM on an action-gating task.
- **Mixed input:** Text trajectories only. Numbers and graphs must be serialised into text, which loses structure.
- **Trade-off:** Strong action-level signal from web-agent work, but it is generative (slow) and not calibrated out of the box. Use it as a teacher, not as the runtime model.

---

## 5. Generative verifiers

- **GenRM** (ICLR 2025, arXiv 2408.15240, EVIDENCE): verifier trained by next-token prediction; CoT variant writes a rationale, then emits Yes or No. The probability of "Yes", averaged over sampled rationales, gives a graded score. Authors report better scaling with model size than discriminative verifiers.
- **Certified by Abstention** (arXiv 2610.09541, Oct 2026): distribution-free guarantees for CoT verifiers at small calibration budgets. Only the bibliography snippet was seen. It may be the most useful 2026 paper for our calibration and abstention goal. Read in full.
- **Learning to Correct** (arXiv 2604.17912, April 2026): calibrated RL for multi-attempt CoT; notes that naive pass/fail weighting gives biased gradients. Read in full if we pursue verifier training.
- **Trade-off:** GenRM's Yes-probability is a usable soft score and is cheap to get from a small model, but it needs a rationale pass to be strong, which costs latency. Distill the verdict into a head if we use this family.

---

## 6. Distilled LLM judges and calibrated judge pipelines

- **Codifying the Judge: program distillation** (arXiv 2607.22561, 2026, EVIDENCE per abstract): turns an LLM judge's logic into executable programs. A reward model trained on those program verdicts beats one trained on a proprietary LLM's labels on RewardBench at about two orders of magnitude lower API cost. Strong fit: the output is auditable code, which suits a regulated gate.
- **RL with a judge reward from a single next-token probability** (arXiv 2604.02621, April 2026, EVIDENCE per abstract): small student trained against a large judge's next-token probability as a continuous reward. Not calibrated, but it shows the judge can supply a soft score.
- **Calibrate, Don't Curate** (arXiv 2605.09702, May 2026): aggregates judge-panel votes into a raw probability, corrects bias, then applies a calibration map to get calibrated win probabilities. Closest found to our output contract (calibrated probability from a judge panel). Read in full.
- **CJE** (arXiv 2512.11150, Dec 2025, EVIDENCE): maps a cheap judge's scores onto a small oracle-labelled set with isotonic regression. Directly reusable as the calibration layer on top of any scorer; needs a labelled set of owner decisions.
- **TinyJudge** (ACL 2026, lightweight specialist ensembles for unverifiable constraint alignment): calibration not confirmed.

**Trade-off:** Judge-to-oracle calibration (CJE, isotonic regression) is the most practical tool we found. It needs owner-labelled data, which we do not yet have. Program distillation gives auditability.

---

## 7. "Decision model" vendors selling typed probability outputs

- **Not found.** Searches did not surface vendors that sell fast, typed probability outputs for decisions. The closest were agent guardrail vendors (Arize Jev, Future AGI, Mastyf) and TFM vendors (Prior Labs, Kumo-Tabular mentioned in the AIMultiple page). This is a clear gap. Next step: search by vendor category (decision intelligence, policy engines, risk scoring APIs) rather than by model.

---

## 8. Energy-based and structured-prediction approaches

- **Energy-based training on tabular data** (arXiv 2412.01019, 2024, EVIDENCE): energy-discrepancy training for discrete and mixed data; authors call it the first working EBM training method on tabular data. Imputation and prediction are the stated uses. Older than the 2026 window but relevant to mixed-type inputs.
- **Structured Prediction Energy Networks (SPENs)** and energy-based inference networks for NLP (2021 dissertation, EVIDENCE-older): joint scoring of structured outputs. Fits the case where the output is (probability, purpose) with dependencies.
- **Distributional energy-based models for uncertainty-aware structured LLM reasoning** (ICML 2026 listing, EVIDENCE per listing): closest 2026 match to structured prediction plus LLMs. Read the paper.
- **HATI-EBM** (Zenodo, Feb 2026, CLAIM): energy-based safety governor beneath a generative model, reports 40–60% fewer constraint violations. Self-reported prototype numbers.
- **Trade-off:** EBMs give flexible joint scores and natural constraint terms, but sampling or inference is often slow and calibration needs extra work. Useful as a constraint-layer idea more than as the core scorer.

---

## 9. Hybrid designs

Not searched in depth. Two directions are standard and worth a targeted search next:

- **GBDT plus an LM embedding:** embed the short text with a small encoder, feed the vector plus numeric features to a gradient-boosted model. Fast, tabular-strong, and the text branch is cheap. Calibration of GBDT probabilities usually needs a post-hoc map (isotonic or Platt). This is the lowest-risk baseline and should be benchmarked before anything novel.
- **Mixture of experts:** a router selects a specialist per action type (trade, transfer, leverage change). Useful if the owner's endorsement differs by action class. Calibration per expert and routing error are the risks.
- **TFM plus graph summary features:** the TFM4GAD pattern applied to trace-derived features (see section 2).

---

## 10. 2026 architectures people are excited about

- **JEPA (joint-embedding predictive architecture):** predicts embeddings of missing content, not tokens. A July 2026 history essay frames it as the alternative to autoregressive LLMs (CLAIM, essay). FF-JEPA (arXiv, June 2026) applies it to long-horizon planning (EVIDENCE per abstract). JEDI (May 2026) reports 43% less VRAM and 2.5x faster training versus a pixel diffusion baseline in RL, not language (EVIDENCE per abstract). Relevance to System One: a latent world-model view of the portfolio state could give an embedding of "what happens if this action runs". Speculative for our scale.
- **Concept-level or continuous-space reasoning** (Coconut, Large Concept Models, Dynamic LCM, Byte Latent Transformer): mentioned in a secondary piece. Not verified.
- **Diffusion language models:** not found in searches. Status unknown.
- **Small efficient reasoning models and lab blog announcements from 2026:** not found in searches. Gap.

---

## Summary table (for the eight findings)

| Family | Latency / size | Calibration | Mixed tab + graph + text | One-line trade-off |
|---|---|---|---|---|
| TabPFN-2.5 / 3 | Slow-ish; distillable to MLP (claim) | Vendor-claimed; independent: no clear win | Tabular only | Best prior; licence blocks product use without a deal |
| TabICLv2 | Not measured | Not checked | Tabular only | Open weights; calibration unknown |
| LimiX-2M | 2M params (smallest strong TFM) | Not checked | Tabular only | Best size fit; self-reported |
| Mitra-v2 | ~1.5 s per fold (vendor) | Not checked | Tabular only | Fast in one test, behind on accuracy |
| Graph anomaly FMs | Not measured | AUC-based, not calibrated | Graph only | No provenance or trace results found |
| Guardrail classifiers (ToolSafe, TraceSafe) | ~100 ms class (vendor) | Not reported | Tool-call trajectories | Right latency class; wrong label set |
| PRMs (Web-Shepherd, ThinkPRM) | Generative: slow | Not calibrated | Text only | Good action signal; too slow at runtime |
| GenRM / CoT verifiers | Rationale pass: slow | Yes-probability, graded | Text only | Soft score; distil the head |
| Judge distillation (program distillation, CJE) | Cheap after distil | CJE gives calibration with labels | Any (via features) | Auditable, but needs owner-labelled data |
| EBMs | Sampling cost | Needs extra work | Mixed types (2024 paper) | Good constraint term; slow inference |

---

## Gaps and next searches

1. Read full text of: TabPFN-2.5 (calibration section), LimiX-2M, TabICLv2 (latency table), 2605.09702 (calibrate, don't curate), 2610.09541 (certified by abstention), 2607.22561 (program distillation).
2. Search by vendor category, not model: decision intelligence APIs, policy engines, risk-scoring APIs with probability outputs.
3. Search provenance-graph and agent-trace anomaly detection with different terms: "execution trace anomaly", "causal provenance intrusion detection", "agent audit log learning".
4. Hybrid baselines: GBDT with a small text encoder and isotonic calibration; MoE routers for action types.
5. X and Hacker News: the search tool did not index them. Try direct site searches later or ask a practitioner.

---

## Beyond what they asked

1. **Conformal abstention as the product, not the probability.** Output a prediction set, and treat "set size greater than one" as "send to the owner". Certified-by-abstention work (2610.09541) points this way. Calibrated sets are easier to defend to a regulator than a raw probability.
2. **Learn the owner, not the average owner.** Fit a per-owner preference model by inverse reinforcement learning on past overrides and mandate edits, so System One's output is the owner's own endorsement function, updated by the owner's behaviour.
3. **Monotone-by-construction networks.** Use monotone lattice or monotone-constrained GBDT in the risk dimensions, so "only tighten" is a property of the function class, not a policy hope.
4. **Compile the judge into code, then learn only the residual.** Program distillation (2607.22561) gives an auditable rule layer; a small learned model handles what the rules miss. The rule layer can be audited line by line.
5. **Probe the agent, not the action.** Read the agent's own hidden activations or chain-of-thought features with a linear probe. The agent's internal state may carry the reason for the action better than the surface text does.
6. **Adversarial canaries to measure tail calibration.** Inject synthetic bad theses at known risk levels, then measure calibration in the tails. Standard test sets will not show failures at the decision boundary.
7. **Purpose as a posterior over motives.** Model purpose as a latent variable with a distribution over motives (hedge, speculation, forced liquidation, error), not a single label. This fits the "purpose it serves" output better and gives a natural uncertainty signal.
8. **Market state as a feature of the thesis.** Use exchange microstructure at the moment of the proposal (spread, depth, recent volatility) as a feature. A thesis that is fine in calm markets may be dangerous in thin ones. Most agent-safety work ignores the market.
9. **Hypernetwork adapters from the mandate document.** Generate a small per-owner adapter from the owner's written mandate, so the model conditions on the owner's stated rules without retraining per owner.
10. **Decision-latency budget as a learning target.** Train a cascade: a tiny gate answers the easy cases in under 10 ms; a larger model answers the rest within a second. The cascade cost is a measured quantity to optimise, not a constraint to satisfy after the fact.
