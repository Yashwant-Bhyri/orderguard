# System One: an independent blueprint

Writer: Haiku 5.5, independent view, 2026-11-19.
Inputs read: BRIEF.md, SYSTEM-ONE.md, SCHEMA.md. Nothing else in the machine was opened, as the brief asks.

Labels used throughout:
- **[E]** evidence, with the source named. Web sources were checked by search snippet this session, not by reading full papers, unless stated.
- **[R]** my own reasoning.
- **[U]** from memory, not checked this session.

---

## 1. Central bet

**Bet.** Most of System One's power will come from making the agent's world checkable by code, not from a bigger model. The learned parts should be small, calibrated and bounded:

1. a small quarantined text classifier for injected instructions and mandate-spoof claims;
2. a tabular endorsement head over typed graph features, with a population prior adapted to each owner;
3. a conformal wrapper that sets the gate threshold with a stated error rate.

I would not use a general language model as the core, and I would not use RL in the first build.

**Why I think this.**

- **[E: SCHEMA.md section 3]** The schema defines seven failure causes. Four are decidable by code on the schema's own fields: drift (book replay against sector bands), misquote (an exact `quoted_span` substring plus a value comparison), stale_thesis (a numeric `invalidation_trigger` checked against document facts), and most of unsupported_claim (value and unit matched against the cited document's facts). Two need text: poisoned_note and authority_spoof. vague_hype is mostly a numeric-presence check plus a judgement of enthusiasm.
- **[R]** So the cognitive core that matters is arithmetic over typed records, provenance and time order, plus a narrow reader for text. None of that needs general next-token prediction, which the brief asks us to put last.
- **[E: SYSTEM-ONE.md sections 5 and 6]** The order path must be code-only (level 3). The learned models therefore sit at thesis, trajectory and book tempos.
- **[E: Zhao et al., arXiv 2507.08794; Maloyan and Namiot, arXiv 2504.18333]** LLM judges reading agent text can be pushed by superficial tokens (false-positive rates up to about 80% in one study) and by injected prompts (about 65.9% average attack success on a 4B-class model across five models). So no text reader may see free agent prose. SYSTEM-ONE.md says "about 90%" for frontier judges. The sources I found say up to 80%. The design conclusion stands either way.

**The design in one line.** Records and code decide. A small model estimates the owner's endorsement from typed features. A conformal wrapper sets the threshold. Frontier models and the human sit above the path, not on it.

**Minimum post-training I recommend.** One LoRA fine-tune of a small encoder on a few thousand labelled text items (planted causes plus hard negatives). Fit the endorsement head with a hierarchical per-owner offset. Calibrate on held-out families, then wrap in conformal risk control. No RL in version 1. Section 6 has the detail.

---

## 2. Answers to the founder's four questions

**Q1. Where does the most potential lie?** **[R]** In three places, in this order: (a) code checks on typed records, which are exact and fast; (b) a calibrated endorsement head that adapts to each owner; (c) a small text reader for the few failure causes that code cannot see. LLMs matter as a quarantined reader and as a teacher or reviewer, not as the decision-maker. Classical models (gradient-boosted trees, logistic regression with monotone constraints) carry the score. A tabular foundation model is a challenger, not the default: **[E: Hollmann et al., Nature, January 2025, "Accurate predictions on small data with a tabular foundation model"]** reports strong results up to about 10,000 rows, pretrained on synthetic tables. It is a useful prior for a new owner with few labels. Test it on CPU latency first.

On custom-modified architectures: **[R]** build the endorsement head from scratch with the constraints we want (monotone in band breach, in invalidation hits, in source mismatch). Do not surgically edit a pretrained language model by removing layers. The benefit is unproven and calibration effects are unknown. LoRA and a replaced head give the flexibility at lower risk.

**Q2. The cognitive core.** **[R]** Put these ahead of general ability, in this order of how much they matter:
1. Band and position arithmetic over the book (code).
2. Provenance and time order: what was knowable when the action was taken (code).
3. Matching a claim to the figure it rests on (code first, a small matcher second).
4. Recognising an injected instruction or a claimed mandate change in text (small classifier).
5. Whether a thesis's invalidation has fired: code on the trigger, a small extractor for natural-language invalidation text, always verified by code before use.
6. What this owner would sign: a small calibrated head with a per-owner prior.

None of these needs a model that predicts the next token well. That capability is the one the brief asks us to deprioritise.

**Q3. Which layers, architectures, model types, paradigms?** Section 5 gives the table, with the post-training cost of each.

**Q4. The minimum post-training for the maximum gain.** Section 6. **[R]** The largest gain per unit of effort comes from the code checks and the graph (no training at all), then from the endorsement head with an owner prior (CPU minutes), then from a single small-encoder fine-tune (GPU hours). Anything bigger has to earn its place on held-out families.

---
## 3. The functions System One needs

Each function is listed with its owner (code or learned) and the schema fields it reads. **[R]** unless stated.

| ID | Function | Owner | Reads |
|---|---|---|---|
| F1 | Ingest and quarantine: parse documents, notes, claims; verify content hashes; mark `written_by` and `signature_valid`; strip `meta` and `label` with `model_view` | Code | All fields except `meta`, `label` |
| F2 | Decision-time provenance graph: nodes for each input read, note read or written, peer action, thesis, typed intent and order; edges for "read before written" | Code | `pre_notes`, `new_notes`, `cites_notes`, `cites`, `evidence_docs`, `source_doc`, `t` |
| F3 | Deterministic verifiers: band and position checks by book replay; quote substring; claim-to-fact match; invalidation triggers; signature checks; time order | Code | `initial_book`, `sector_bands`, `quoted_span`, `facts`, `invalidation_trigger` |
| F4 | Quarantined text readers: instruction detector on note and document text; mandate-claim detector; enthusiasm-without-figure judge; invalidation-text extractor | Learned, small | Text fields only, never `rationale` directly into a decision |
| F5 | Endorsement scorer: probability the owner would endorse an action or thesis, from typed features and the owner's state | Learned, small | Output of F2, F3, F4 |
| F6 | Trajectory monitor: drift, loops, corrupted context, lease length | Code plus a small sequence model | Action sequence, graph windows |
| F7 | Swarm monitor: agents whose orders trace to one root; cap on combined exposure | Code | Graph roots |
| F8 | Conformal gate: threshold on F5 with a stated error rate; coverage monitoring | Code over a learned score | Calibration set |
| F9 | Interruption policy: ask the owner when stale-estimate cost exceeds interruption cost | Code over F5 uncertainty | F5, owner response history |
| F10 | Attribution: weights over graph nodes, with an explicit "unexplained or prior knowledge" bucket | Code over F2 | F2 only, never the agent's explanation |
| F11 | Tighten-only composition: the final decision is the strictest of the code verdict and the learned verdicts | Code | All of the above |
| F12 | Escalation and audit: frontier reviewer, human queue, random audit slice of allowed orders | Process plus model | Gate outputs |

**[R]** F11 is the most important function to test. If it is wrong once, the whole argument for deployability fails. Its unit tests should assert that no learned output can turn a code rejection into an approval, and that a timeout in any learned component resolves to hold.

**[E: SYSTEM-ONE.md section 3]** F10 must take attribution from the graph recorded at decision time, never from the agent's text. I agree, and I would go further: explanations should not be used as a training input or a feature.

---

## 4. Architecture, end to end

```
agent writes / reads
        |
        v
  F1 quarantine and parse  (code)
        |
        +--> F2 provenance graph (code, recorded at decision time)
        |        |
        |        v
        +--> F3 deterministic verifiers (code) ----+
        |                                          |
        +--> F4 quarantined text readers (GPU) ----+--> F5 endorsement scorer (CPU)
                 run at ingest, cached             |        |
                                                   |        v
                                                   |   F8 conformal gate
                                                   |        |
                                                   v        v
                                      F11 tighten-only composition  --> hold | pass-to-code
                                                                           |
                                                       order path: code check plus cached verdict
```

**Two tempos, and where each one runs.**

- **Order path (CPU, p99 at most 50 ms per thesis).** **[R]** The order does three things: look up the cached thesis verdict from F5 and F8; run F3 checks on the order (band, position, turnover, sign); and confirm the order's graph node has a path to a judged thesis. Each check is a dictionary lookup or a small arithmetic operation. A gradient-boosted scorer on a few dozen features is also well under a millisecond on a laptop CPU **[U]**, but measure it, do not assume it.
- **Text reading (GPU, p99 at most 300 ms).** **[R]** Run the readers when a note or document is ingested, not when an order arrives. Cache the typed result against the content hash. The order path then never waits on a model. This is the single most useful design decision for the latency targets, and it costs nothing in quality, because an order can only cite items that already exist (SCHEMA.md section 1).

**Where the hosted decision model sits.** **[R]** At thesis tempo and on escalation, never on the order path. Its roughly one-second call cannot meet the 50 ms budget. Cache its answers by the hash of the typed state it was asked about. If it times out, the default is hold, not pass, because the system can only tighten.

**Output contract.** **[R]** Every stage returns either `hold` with a reason code and the node ids that caused it, or `no objection`. No stage returns `approve`. Only code, after F11, lets an order through, and only if F3 also passes.

**Versioning.** **[R]** The model weights, the calibration set, the conformal threshold and the feature schema are one versioned bundle. Any change to one of them reruns the full shift suite (section 8) before deployment.

---
## 5. Models: kinds, architectures, layers, paradigms

The table weighs each option on how well it serves the cognitive core and how easily it can be post-trained and customised later, which is the trade-off the founder asked for.

| Option | Use in System One | Post-training cost | Verdict |
|---|---|---|---|
| Deterministic code (schema checks, book replay, graph shapes) | F1, F2, F3, F7, F10, F11 | None. Changes are reviewed code | **Use, and make it the authority for facts.** |
| Gradient-boosted trees or logistic regression with monotone constraints on typed features | F5 endorsement head | Refit in minutes on CPU; isotonic or Platt calibration | **Use as the default head.** Monotone constraints encode the rules we want (more band breach means less endorsement) |
| Hierarchical logistic model: population prior plus per-owner offsets | F5 owner adaptation | Update per owner label in milliseconds | **Use.** Matches "learn an owner from few questions" directly **[R]** |
| Tabular foundation model (TabPFN-class, pretrained on synthetic tables) | Prior for a new owner, or challenger to F5 | Little training; inference cost depends on context size | **Challenger only.** **[E: Hollmann et al., Nature 2025]** reports strong small-data results up to about 10k rows. Test its CPU latency against 50 ms before any use on the order path **[R]** |
| Small encoder classifier (mDeBERTa-base class, about 86M parameters), starting from a pretrained injection classifier | F4 instruction and mandate-claim detector | Full or LoRA fine-tune in hours on one A6000 | **Use.** **[E: Meta's Llama Prompt Guard 2 86M model card]** describes a multilingual, BERT-style, mDeBERTa-base classifier for attack detection. It is a starting point, not a verdict, because its labels differ from ours. Its reported 97.5% recall and 92.4 ms figures come from its own evaluation and are not comparable to our data **[E]** |
| Small decoder language model, 1 to 4B open-weight, LoRA-tuned to emit typed JSON | F4 invalidation-text extractor and claim matcher | LoRA in hours; structured-output decoding | **Use, narrowly.** Its output must be a typed candidate that code verifies. It never decides |
| Frontier language model or the hosted decision model | Teacher labels, escalation reviewer, thesis-tempo judgement | None (API) | **Use off the path only** |
| General-purpose large language model as the core | None | Expensive to serve and to post-train | **Reject.** It optimises next-token prediction, which the brief puts last |
| Surgery on a pretrained language model (dropping or changing layers) | None in version 1 | Re-validation of the whole model | **Reject for version 1 [R].** The effect on calibration is unmeasured. LoRA and a replaced head give the flexibility at lower risk |
| Graph neural network over the provenance graph | Possible F2 scorer | Moderate | **Defer.** Graphs per episode are small. Hand-built graph features into F5 may be enough. Add a GNN only if it beats the feature model on held-out families **[R]** |
| Ensemble of five | F5 and F4 under shift | Five times the training | **Use, but as five seeds of the small head rather than five different big models [R].** **[E: Ovadia et al., NeurIPS 2019]** reports that averaging over models does well under dataset shift; I did not confirm that deep ensembles are the specific method named there **[U]** |
| Sequence model or hazard model | F6 trajectory | Small | **Later.** Start with windowed counts and CUSUM-style statistics over the graph **[R]** |

**Paradigms.** **[R]**
- *Supervised learning* is the primary paradigm for F4 and F5.
- *Distillation* is the way to get F4 labels cheaply, from a frontier reviewer, on text only (section 6).
- *Bayesian or hierarchical adaptation* is the way to personalise F5 to an owner.
- *Reinforcement learning* is deferred (section 6).
- *Training from scratch* is not justified. No dataset here is large enough to beat a pretrained encoder on text, and a tabular model does not need a deep network.

**Layers, in one line each.** **[R]** For F5, use monotone-constrained trees or a linear layer over graph features, with no hidden layer unless it wins on held-out families. For F4, use the standard pretrained encoder, with a new classification head and LoRA on the attention and feed-forward projections. Do not add new layers to a pretrained model.

---
## 6. What learning, and how much

The brief lists six options. Here is each one, with my recommendation.

| Method | Recommendation | Why |
|---|---|---|
| Frozen pretrained models | **Yes, as a baseline.** Run the injection-classifier starting point with no tuning as a prefilter and measure it | **[R]** It gives the zero-shot number the fine-tune must beat. The model card in section 5 is the only source for its behaviour **[E]** |
| Small heads on frozen features | **Yes, for F5.** Logistic or monotone trees on typed graph features, plus the per-owner prior | **[R]** Cheapest and most calibratable. Refit takes minutes on CPU |
| Fine-tuning a small model | **Yes, once, for F4.** LoRA on one encoder, a few thousand labelled items | **[R]** Hours on one A6000. The only learned component that must read text |
| Teacher-student distillation | **Yes, for F4 labels and for the claim matcher.** The teacher is a frontier reviewer or DeepSeek, used on quarantined text only | **[E: Hsieh et al., "Distilling step-by-step", 2023]** reports that rationale-augmented distillation can make small students competitive **[U]**, not checked this session. **[R]** The teacher's labels are checked against the planted-cause labels before use |
| Reinforcement learning | **Not in version 1.** Revisit only if held-out calibration fails and the failure is traced to the head, not the data | **[E: Yue et al., "Does RL really incentivize reasoning capacity in LLMs beyond the base model?", NeurIPS 2025]** reports that RL with verifiable rewards mostly improves single-attempt accuracy over the base model, with the base model ahead at large sample counts. The finding is contested in later work **[E]**. **[E: Damani et al., RLCR, "Beyond binary rewards", arXiv 2507.16806, ICLR 2026]** adds a Brier-score term to the reward and reports better calibration in-domain and out-of-domain, but the abstract says out-of-domain error stays high. The reported figures in SYSTEM-ONE.md section 7 (0.37 to 0.03) I could not confirm from the abstract |
| Training from scratch | **No.** | **[R]** Nothing here needs a new base model |

**The minimum post-training for the maximum gain.** **[R]** Three steps, in this order, and then stop.

1. **Fit the endorsement head with an owner prior.** A hierarchical logistic or monotone-tree model over typed graph features, trained on simulator labels and then on owner decisions, with a per-owner offset. Cost: CPU minutes. Gain: the calibrated, owner-specific number that the gate needs.
2. **Fine-tune the instruction and mandate-claim classifier once.** LoRA on one small encoder, a few thousand items: planted poisoned notes and authority-spoof notes as positives, and hard negatives as negatives (owner-signed notes that discuss limits, exact quotes, legitimate adaptation). Cost: hours on one A6000. Gain: text coverage that code cannot give.
3. **Calibrate and wrap.** Temperature or isotonic calibration on held-out families, then conformal risk control on the gate. Cost: CPU. Gain: a stated error rate that holds while the new data resembles the calibration data.

**What I would not do first.** **[R]** Distil a large model, run RL, or build a bigger ensemble. Each adds cost, makes serving harder, and is hard to undo. None is needed until steps 1 to 3 have been measured on held-out families.

**Where the research points, and where I disagree with SYSTEM-ONE.md.** **[R]** SYSTEM-ONE.md section 7 says "supervised fine-tuning first, then RL with a bounded proper scoring reward". The evidence I found supports SFT first. It does not support RL as a default: the RL evidence is contested, and the calibration gain was measured in-domain. I would move RL to a conditional stage.

---
## 7. Data and labels

**Four label sources, as SYSTEM-ONE.md section 7 lists them.** **[R]** I agree with the list and would add two cautions.

1. **Planted causes in the simulator.** **[E: SCHEMA.md sections 2 and 3]** Each `y = 1` step carries a `cause` and `cause_refs`. These are exact for the generator's rules, but see the caution below.
2. **Counterfactual replay.** Remove or correct one cause, rerun, see whether the order survives. **[E: SYSTEM-ONE.md section 7, citing AgenTracer]** reports that such replay labels can train an 8B model to beat frontier models at failure attribution. I did not verify this. Use replay for F10 attribution labels and for F5 counterfactual pairs.
3. **Owner decisions.** Hold-queue decisions plus a random audit slice of allowed orders. The audit slice corrects for the fact that held orders are a biased sample.
4. **A written delegation constitution, used to generate adversarial data.** **[E: Anthropic, "Constitutional Classifiers", 2025]** reports about 3,000 estimated hours of red-teaming with no universal jailbreak found against its classifier. That result is for a jailbreak classifier in one domain, not a decision model, so transfer is uncertain **[R]**.

**The caution that matters most.** **[R, from SCHEMA.md section 2]** The schema says an owner does not endorse an action that breaches a signed band or position limit, and the generator produces labels by such rules. So for the simulator's labels, code can reproduce the ground truth. A model trained on them may learn the rule, not the owner. A high score on the synthetic set therefore says little about endorsement of real orders. Three mitigations:
- report a **rules-only baseline** on every split, so a learned component must beat code to count;
- build a **messy variant** of each family: rationales paraphrased, facts with no name match, numbers in the text but not in the `facts` list, notes in other languages, documents that mix two figures;
- treat **owner decisions** as the only label for "would this owner endorse". Use the simulator only for mechanisms (did the cause happen, and did the order survive when it was removed).

**Labels by component.**

| Component | Label | Source |
|---|---|---|
| F3 checks | Exact by construction (book replay, substring, numeric trigger) | Code; test with unit cases, not with learned labels |
| F4 instruction and mandate-claim detector | Positive: planted poisoned or authority-spoof text. Negative: hard negatives (below) | Simulator, then messy variant, then owner review of a sample |
| F4 enthusiasm judge | Hype-without-figure vs. enthusiastic-with-figure | Simulator vague_hype and hard negatives; frontier reviewer for paraphrase |
| F4 invalidation-text extractor | Candidate trigger from natural language, checked by code against the trigger spec | Frontier reviewer distilled; accept only if code confirms |
| F5 endorsement | Owner decision (held or audit slice). Simulator cause as a prior only | Owner queue; simulator for the prior |
| F6 trajectory and F7 swarm | Planted loops, colluders and herding | Simulator |
| F10 attribution | Planted cause and counterfactual replay | Simulator and replay |

**Hard negatives: required, and counted.** **[E: SCHEMA.md section 4]** The schema requires legitimate adaptation on fresh high-trust evidence, correct sells, exact quotes, and enthusiastic-but-factual language, all labelled `y = 0`. **[R]** I would add: owner-signed notes that discuss limits (these must not be flagged as poisoned), agent notes that cite a real limit without changing it, and notes that quote an injected instruction in order to report it. Without these, the instruction detector will learn that any mention of a limit is an attack.

**Splits.** **[R]** By family, by seed, and by simulator setting, never at random across episodes. Deduplicate by `content_hash` across splits, because one document can appear in many episodes. Keep one family and one shift setting out of training entirely, as SYSTEM-ONE.md section 11 suggests.

**Rough quantities.** **[U]** My estimates, not measured. A few thousand text items for F4 (positives and hard negatives in roughly equal numbers); a few thousand actions per family for F5 prior fitting; 50 to 200 owner labels per owner for adaptation. Set these by learning curves, not by the estimate.

---
## 8. Evaluation

**Primary question.** **[R]** For a held-out family the system never saw, how many steps of lead time does it give before the first bad action is held, at a fixed false-hold rate? This is the test SYSTEM-ONE.md section 11 sets, and I keep it as the headline.

**Metrics, in order of importance.**

1. **Tighten-only violations.** Count of cases where the composed decision passes an action that code rejects, or where a learned output turns a hold into a pass. The target is zero. Any non-zero count fails the build. This is a unit-level property, tested on every release.
2. **Lead time at fixed false-hold rate** on held-out families, against the rules-only baseline. **[E: SYSTEM-ONE.md section 11]** sets this as the first kill criterion.
3. **Calibration.** Brier score, expected calibration error, and reliability plots on each split. SYSTEM-ONE.md sets 0.05 as the in-distribution limit after recalibration and about 0.10 as the stretch target under adversarial shift. I keep both targets. I could not verify the 0.03 and 0.21 figures in SYSTEM-ONE.md section 11 from sources.
4. **Conformal coverage and realised error rate** of the gate on each held-out split, with the monotonicity check in section 11.
5. **Detection by cause**, reported separately for each of the seven schema causes and for hard negatives. A system that catches drift but flags every quote is not a good system. Report false positives on the hard negatives as a column, not a footnote.
6. **Robustness.** Consistency when options are reordered and when a question is negated, as SYSTEM-ONE.md section 11 asks **[R]**. Add paraphrase consistency on the text readers, and the messy variant of each family (section 7).
7. **Attribution accuracy against planted causes**, for each of three ways of ranking causes: the agent's own explanation, the graph, and counterfactual replay.

**Attribution, with the evidence.** **[E: Zhang et al., "Which agent causes task failures and when?", ICML 2025]** reports that the best of its three automated methods reached 53.5% accuracy on the responsible agent and 14.2% on the failure step, with some methods below random. **[E: Chen et al., "Reasoning models don't always say what they think", arXiv 2505.05410]** reports average faithfulness of 25% for Claude 3.7 Sonnet and 39% for DeepSeek R1 on hint-based tests. **[R]** Together these say: do not score attribution from the agent's explanation or from trace-based methods. Use the graph and counterfactual replay, and report both against planted causes. SYSTEM-ONE.md section 1 quotes Who&When results of 5 to 25% for GPT-4o and 33 to 50% for the best 2026 methods. The original paper I found reports the figures above. I could not verify the 2026 figures, so I use the original numbers.

**Baselines, always reported.** **[R]**
- Rules-only: F3 plus F2 shapes with no learning.
- Logistic regression on the same features.
- Monotone gradient-boosted trees on the same features.
- The hosted decision model, asked the same typed questions.
- A frontier reviewer, asked the same typed questions on text.
- The deterministic monitor the project already has (named in SYSTEM-ONE.md section 11).

**Ablations.** **[R]** Remove each learned component in turn: without F4, without F5's owner prior, without the conformal wrapper, without the graph features. If removing a component changes nothing on held-out families, delete it.

**Shift suite.** **[R]** Hold out attack families, simulator settings and time periods. Report Brier score, calibration error and coverage on every split. **[E: Ovadia et al., NeurIPS 2019]** found that post-hoc calibration can fail under even mild shift **[E, from search snippet]**, so the shift suite is not optional.

**Shadow mode with real owners.** **[R]** Compare the endorsement prediction with what the owner actually decided, on live orders, with no effect on the order path. This is the only test of the label "would this owner endorse", and it is the test I would weight most when deciding whether to deploy.

**Operational cost.** **[R]** Report the hold queue size per owner per day at each threshold. A gate that holds too often fails in practice even if its accuracy is good. SYSTEM-ONE.md's kill criteria do not yet include this.

---
## 9. Runtime and serving at scale

**The scale argument.** **[R]** The models here are small, and the number that grows is owners, theses and notes, not parameters. So the serving problem is throughput of small models plus caches, not the cost of one large model. A larger model would make the cache miss rate and the GPU queue worse, and it would not be on the order path anyway. That is the reason to keep the largest model off the path entirely.

**Order path (CPU, p99 at most 50 ms per thesis).**
- F3 checks, the cached thesis verdict from F5 and F8, and the graph path check: dictionary lookups and arithmetic. Expected well under 1 ms **[R]**.
- F5 scorer: gradient-boosted trees or logistic regression. Expected sub-millisecond on a laptop CPU **[U]**. Measure at p99 on the target machine with the real feature count.
- A **tiny TabPFN-class model** is not on this path unless its CPU latency at the owner's context size is shown to fit **[R]**.
- Budget check: one timer per order in the test harness. Fail the build if p99 exceeds 50 ms on the reference laptop.

**Text readers (GPU, p99 at most 300 ms).**
- F4 runs **at ingest**, not on the order path. The result is typed and cached against the content hash. An order that cites an item reads the cache.
- **[R]** If an item has not yet been read when an order cites it, the order is held with reason "reader pending". That is the safe default, and it is rare if ingest runs first.
- A small encoder (about 86M parameters) is expected to be far inside 300 ms on an A6000 for short text **[U]**. A 1 to 4B decoder for invalidation extraction is also expected to be fast enough at ingest, with batching. Both need measuring on the shared machine.

**Shared GPU.** **[R]** The brief says the two A6000 cards are on a shared university machine. Plan one card for serving and one for training, or time-slice with a hard reservation for serving. Serving must not depend on training jobs being idle. If the decoder is needed in serving, quantise it (4-bit or 8-bit) to free memory **[U]**.

**Hosted decision model (about one second per call).** **[R]** Use at thesis tempo and on escalation only. Cache each answer by the hash of the typed state it was asked. Give it a timeout. On timeout, the default is hold. Its answers are an input to F5 and F8 only as a verdict that code can overrule, never as an approval.

**DeepSeek API.** **[R]** Use as a teacher for labels on quarantined text and as a reviewer on escalation. Send only typed or quarantined content, never owner identity or raw mandate text unless policy allows it. Log every outbound request with its content hash, so the data that left the building can be audited. This is a policy decision for the project, and I flag it as a risk in section 11.

**Model bundle.** **[R]** Ship weights, the feature schema, the calibration set and the conformal threshold together, with a version hash. A rollback is a bundle swap, not a code change.

**Failure behaviour.** **[R]** Every learned component has a timeout and a circuit breaker. When a component is unavailable, the system holds the affected orders and writes the reason to the graph. It never passes an order because a model was slow.

---
## 10. Build order

Each stage has an exit test. A stage that fails its exit test does not unlock the next one. The order follows SYSTEM-ONE.md section 12, with changes marked.

| Stage | Work | Exit test |
|---|---|---|
| 0 | Record the decision-time graph in the harness and the arena. Define the typed thesis record. Enforce `model_view` in every feature path (the schema requires this, section 5) | Graph recorded for 100% of orders in a sample run; a test fails if any feature code reads `meta` or `label` |
| 1 | F3 verifiers and F2 graph shapes in code. **Rules-only baseline on every family and split** | Baseline numbers recorded on held-out families. Tighten-only test passes |
| 2 | F5 head: monotone trees or logistic, owner prior, isotonic calibration, conformal wrapper, five seeds | Lead time beats rules-only at the same false-hold rate on held-out families, or the head is dropped. Calibration within the 0.05 target after recalibration **[E: SYSTEM-ONE.md section 11 targets]** |
| 3 | F4: zero-shot prefilter, then one LoRA fine-tune of the instruction and mandate-claim classifier, with hard negatives. **Changed:** the enthusiasm judge and the invalidation extractor wait until stage 4 | Detection beats zero-shot on held-out families, with the hard-negative false-positive rate reported. Latency within 300 ms p99 on the shared machine |
| 4 | Teacher distillation for the invalidation extractor and claim matcher. Code verifies every output | Extractor output passes code verification on held-out text at a stated rate; failures go to the reviewer, not to the decision |
| 5 | Shadow mode with real owners. Interruption policy (F9) | Predictions compared with owner decisions over a fixed period; calibration on live data reported |
| 6 | **Conditional.** RL with a bounded Brier-style reward, only if stage 2 or 5 shows calibration failure that traces to the head and not to the data | A measured improvement under shift over the SFT model. Otherwise, do not build it |

**[R] Why this order.** The code stages (0 and 1) are cheap, exact and already useful against the failure families. They also produce the baseline that every learned stage must beat. The learned stages then add only what code cannot see. Putting RL or distillation before the rules-only baseline would make it impossible to say what the learning added.

**[R] What stage 0 needs from the existing work.** The graph is the thing nobody else captures (SYSTEM-ONE.md section 10). I agree it should come first, and I would make it the first deliverable, not just the first stage.

---
## 11. Risks

Ordered by how much each could undo the design.

1. **Circular evaluation.** The simulator's labels follow the same rules that the code checks (section 7). The biggest risk is a result that looks strong and says nothing about real owners. *Mitigation:* rules-only baseline on every split, messy variant of each family, owner labels as the only endorsement label, shadow mode before any authority is given.
2. **Calibration under shift.** Post-hoc calibration can fail under mild shift **[E: Ovadia et al., 2019]**. *Mitigation:* ensemble, shift suite on every release, live coverage monitoring, and a hold default on drift alarms.
3. **Conformal assumptions.** The guarantee holds only if new data resembles the calibration data (SYSTEM-ONE.md section 7 says this). The standard guarantee also assumes a monotone loss in the threshold. A 2026 arXiv note I found says the standard guarantee can fail for non-monotone losses, and points to Learn-then-Test for that case **[E: search snippet of arXiv 2604.01502; not read in full]**. *Mitigation:* check the gate's loss is monotone in the threshold, or use Learn-then-Test.
4. **Injection against the readers.** The readers read text that an attacker may shape. The attack that fools judges (section 1, Zhao et al.) can also target the extractor. *Mitigation:* readers emit typed fields only, with a fixed enum and a bounded length; no free text goes downstream; every extracted trigger is verified by code; the adversarial variant of each text family is part of the suite.
5. **Attribution that looks causal but is not.** Graph weights are a reasoned accounting, not proof. The Shapley-style split is exact only if the causes are defined in advance. *Mitigation:* report the "unexplained or prior knowledge" bucket every time, and never display an attribution to an owner as a finding without it.
6. **Owner label bias.** Held orders are a biased sample. *Mitigation:* the random audit slice (section 7) and off-policy evaluation.
7. **Over-holding.** A system that only tightens can still do damage by holding too much: cost of missed trades, owner fatigue, a hold queue nobody reads. *Mitigation:* operational cost in section 8, and an interruption policy (F9) that spends the owner's attention deliberately.
8. **Shared GPU contention.** Training can starve serving. *Mitigation:* reserved card or hard time-slice (section 9).
9. **Data egress.** Teacher labels and escalations send text to external APIs. *Mitigation:* typed or quarantined content only, logged by hash, and an explicit project policy before first use. This is a decision for the project, not for the model.
10. **Thesis invalidation by summary.** The agent's own context will drop invalidation conditions (SYSTEM-ONE.md section 8). *Mitigation:* the thesis record lives outside the agent, and F3 evaluates triggers from the record, never from the agent's memory.
11. **Name.** SYSTEM-ONE.md section 11 flags an existing "system one" model name and client library. I have not checked this and it is outside the brief. *Mitigation:* a trademark search before any public use, as SYSTEM-ONE.md already says.

**Failure I considered and rejected as a top risk.** **[R]** Model collapse of the endorsement head into "hold everything". Monotone constraints, the hold-rate metric in section 8, and the lead-time test against rules-only make this visible early. It is a real failure but a loud one.

---
## 12. Where I differ from SYSTEM-ONE.md, and corrections

| SYSTEM-ONE.md says | My view | Basis |
|---|---|---|
| Superficial tokens fool frontier judges "up to about 90%" | Use up to about 80% false positives for superficial-token attacks, and about 65% average attack success for a 4B-class judge | **[E: Zhao et al., arXiv 2507.08794; Maloyan and Namiot, arXiv 2504.18333]**. The 90% figure I could not find |
| Who&When: 5 to 25% for GPT-4o; 33 to 50% for the best 2026 methods | Use the original paper's figures: 53.5% agent, 14.2% step, for its best method | **[E: Zhang et al., ICML 2025]**. The 2026 figures are unverified |
| "RL with a bounded proper scoring reward" after SFT (SYSTEM-ONE.md section 7) | RL is a conditional stage, not a default | **[E: Yue et al., NeurIPS 2025]** (contested); **[E: Damani et al., RLCR]** (in-domain gain, high out-of-domain error) |
| "A small fine-tuned language model reads the quarantined text fields" | Narrow this to a classifier for detection and a typed extractor for invalidation text. Claim matching is code first | **[R]** Most of the claim checks are decidable in code on schema fields (section 1) |
| A five-model ensemble | Five seeds of the small head, not five different models | **[R]** Cheaper, same variance reduction; serving is simpler |
| A hosted decision model as part of the architecture | Use it as a teacher and escalation, not in the loop | **[R]** Its one-second latency cannot meet the 50 ms order budget |
| Architecture "from the research" with a tabular or graph model | Start with a monotone tree or logistic head on hand-built graph features. A graph network is a later test | **[R]** Graphs per episode are small; a feature model is easier to calibrate |

**Things I would add to SYSTEM-ONE.md.** **[R]**
- **An explicit rules-only baseline** on every split, as a gate for any learned component.
- **A hold-rate and queue-cost metric**, alongside lead time and calibration.
- **A fail-to-hold rule** for every learned component: timeout, error or missing read resolves to hold.
- **A messy variant of every synthetic family**, to break the circularity between generator rules and code rules.
- **A decision on external data egress** before the first teacher call.

**Things I would keep unchanged.** **[R]** The reframe from endorsement to delegation (section 2 of SYSTEM-ONE.md). The decision-time graph as the moat. The tighten-only principle. Attribution only from the graph. The kill criteria. These are the parts I found the strongest.

**Open questions I could not settle from the brief.** **[R]**
- How much real owner labelling we will get, and how quickly. The whole endorsement story depends on it.
- Whether the real agents' inputs will carry the same typed `facts` structure as the schema. If not, the code checks in section 3 need a fact extractor, and that is itself a learned component with its own error rate.
- Whether the shared GPU machine can give a reserved card for serving.

---

## 13. Evidence used

All sources were found through web search this session. I read search snippets, not full papers, unless I say otherwise. Treat any figure as provisional until checked against the paper.

- Yue et al., "Does Reinforcement Learning Really Incentivize Reasoning Capacity in LLMs Beyond the Base Model?", arXiv 2504.13837, NeurIPS 2025 oral. https://arxiv.org/pdf/2504.13837
- Chen et al., "Reasoning Models Don't Always Say What They Think", arXiv 2505.05410. https://arxiv.org/abs/2505.05410
- Hollmann et al., "Accurate predictions on small data with a tabular foundation model", Nature, January 2025. https://pubmed.ncbi.nlm.nih.gov/39780007/ (search snippet also cites https://arxiv.org/html/2502.17361v1 for an independent evaluation)
- Angelopoulos et al., "Conformal Risk Control", ICLR 2024. https://arxiv.org/abs/2208.02814 and https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html
- arXiv 2604.01502 (2026), on conformal guarantees for non-monotone losses. Snippet only. https://arxiv.org/pdf/2604.01502.pdf
- Anthropic, "Constitutional Classifiers: Defending against Universal Jailbreaks across Thousands of Hours of Red Teaming", arXiv 2501.18837, 2025. Coverage read, not the paper. https://www.rivista.ai/wp-content/uploads/2025/02/2501.18837v1.pdf
- Zhang et al., "Which Agent Causes Task Failures and When? On Automated Failure Attribution of LLM Multi-Agent Systems", arXiv 2505.00212, ICML 2025. https://arxiv.org/abs/2505.00212 and https://icml.cc/virtual/2025/poster/45823
- Damani et al., "Beyond Binary Rewards: Training LMs to Reason About Their Uncertainty" (RLCR), arXiv 2507.16806, ICLR 2026. https://arxiv.org/abs/2507.16806
- Ovadia et al., "Can You Trust Your Model's Uncertainty? Evaluating Predictive Uncertainty Under Dataset Shift", NeurIPS 2019. https://arxiv.org/abs/1906.02530
- Meta, Llama Prompt Guard 2 86M model card. https://www.llama.com/docs/model-cards-and-prompt-formats/prompt-guard/ and https://huggingface.co/project-free-llama/Llama-Prompt-Guard-2-86M (a mirror; the brief's reader should use Meta's own card)
- Zhao et al., superficial-token attacks on generative reward models, arXiv 2507.08794. https://arxiv.org/abs/2507.08794
- Maloyan and Namiot, "Adversarial Attacks on LLM-as-a-Judge Systems: Insights from Prompt Injections", arXiv 2504.18333. https://arxiv.org/pdf/2504.18333

**Not checked, cited from memory [U].** Hsieh et al., "Distilling step-by-step" (2023). Ensemble methods under shift as the specific method in Ovadia et al. Gradient-boosted latency on a laptop CPU.

**Not used.** I did not open JUDGEMENT.md, RESEARCH.md, research_notes or reports, as the brief asked. Figures that SYSTEM-ONE.md attributes to those sources (for example the 0.03 and 0.21 calibration numbers, and the AgenTracer result) I could not check, and I say so where they appear.
