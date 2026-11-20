# System One: the plan, as a decision tree

**2026-11-20.** This is the lead's working plan: what we are testing, what each result would mean, what we do next in each case, the data, the training ladder and the architecture options, including extending a decision model so it can reason when it needs to.

It complements [BLUEPRINT.md](BLUEPRINT.md) (what System One must do) and [COMBOS.md](COMBOS.md) (the stack race), and it will be updated as results land.

---

## 1. Where we are (evidence, not hopes)

| What | Result | What it means |
|---|---|---|
| Exact code checks on our simulator (192k actions) | AUROC 1.00 on 5 of 6 failure types; 0.88 on stale theses; under 1 ms | The formal part is solved **in our world**. The world is too easy, so the real test is elsewhere |
| Small calibrated models (logistic, EBM, boosted trees) | AUROC about 0.996, calibration error about 0.1%, 95% recall at 2–3% false holds | Same caveat. They learn what the generator planted |
| Taint (where information came from) | Blocks 98% of poisoned-note and fake-approval actions, 0 false blocks in 24,000 | Provenance works as a hard gate. Gaps found: one path never fires on our data, and sells escape the authority gate |
| Hosted decision model as a narrow reader (one yes/no question at a time) | Hype 1.00, false authority 0.92, unsupported claim 0.998 (the keyword floor scores 0.67, 0.85, 0.84) | **Big models add real value on reading text**, the first clear evidence |
| Hosted decision models as general judges or labellers | No better than always giving the majority answer (0.77) | Narrow, well-posed questions work. Open-ended judging does not, yet |
| Real fund data (5,934 SEC N-PORT funds, the 80% names rule) | 184 flagged (3.1%), 134 robust | The holdings-test pipeline works on real filings |
| A reference-world defect (15% of clean actions were incoherent) | Found, fixed (v2.1), and a new `binding_error` family added | The headline numbers barely moved |
| **G1:** self-hosted Karpo 31B, Clef 27B and their 9B siblings as readers | **Running now** | Section 3.1 |
| Unseen worlds, red team, capability benchmark, CS-1000 | Built or being built; not yet scored | **The decisive tests. Nothing so far proves generalisation** |

---

## 2. The baselines everything is measured against

Every result is reported against all of these, on the same items:

| Code | Baseline | Why |
|---|---|---|
| B0 | Majority class, and "always hold" | The floor. A model must beat it to count |
| B1 | Code only (the 41 structural checks, taint, the mandate compiler) | What exact rules achieve with no learning |
| B2 | B1 plus a calibrated EBM over code features | The cheap, interpretable stack (S0+S1 in COMBOS) |
| B3 | B2 plus small text readers (keyword list, NLI, embeddings) | The best small stack |
| B4 | B2 plus the hosted decision model as a reader | Today's best measured reader |
| B5 | A self-hosted decision model as the reader, zero-shot (G1) | Can we own the reader? |
| B6 | A strong chat model as the judge (DeepSeek or Qwen at max reasoning), given the whole state | The "just ask an LLM" ceiling and cost |

**Headline metric:** coverage at a 5% false-allow rate. That is the share of actions we can let through while keeping the rate of allowed-but-the-owner-would-reject at or below 5%. Also reported:
- AUROC and calibration;
- cause and evidence-pointer accuracy;
- `ask_owner` recall;
- reasoning-probe pass rates;
- p99 latency and GPU-seconds per action.

Everything is reported per truth type (formal, evidential, preference) and per failure family.

---

## 3. The decision tree

### 3.1 G1: can a self-hosted decision model be the reader? (this week)

Same 1,440 actions as T05, zero-shot, on the harder shifted split. The bar is the hosted model's 0.92 on false authority.

| If… | Then… |
|---|---|
| A 31B or 27B model ≥ the hosted model on all three questions | **Self-host the reader.** No API dependency, so we can tune it. Next: G2, then head training (section 5, stage 2) |
| A 9B model is within 0.02 of its big sibling | Prefer the 9B for the hot path (latency, cost). Keep the big one as the escalation judge |
| The big models are clearly below the hosted model (> 0.03 on authority) | Keep the hosted reader for now. Check whether the gap is calibration (fixable with one temperature) or ranking (needs training). Plan head training |
| Everything is ≈ 1.0, including the keyword floor | Our questions are too easy. Move straight to CS-1000 and the messy benchmark (T16) |

### 3.2 G2: the reader on messy and unseen inputs (after G1; needs T16 and T31)

The same readers on:
- documents with **no structured facts** (T16 has 30% messy episodes);
- the new `binding_error` family ("right number, wrong attachment").

| If… | Then… |
|---|---|
| Readers hold up (AUROC ≥ 0.90 on binding errors, messy cases ≥ 0.85) | The reader can carry the evidential truths. Go to the stack race |
| Binding errors drop below 0.80 | **This is the core training target.** Build the grounding verifier (X6): counterfactual pairs (T19) plus XBRL-derived binding pairs (section 4), head-train or LoRA the reader (section 5) |
| Messy cases fail mostly because facts were never extracted | The gap is **fact extraction (F2)**, not judgement. Fund T24 first: quote-anchored extraction feeding the code checks |

### 3.3 The stack race (T07): small stack against big model, on worlds no one tuned on

Four independently written worlds plus the red team (520 attacks, 220 benign lookalikes):

| If… | Then… |
|---|---|
| B2 or B3 is within 0.03 coverage of B5 or B6 | **The small stack ships as the hot path.** The big model is used only for escalations (the 10–15% uncertain or novel actions) and offline. This is the four independent blueprints' prediction |
| B5 beats B3 by > 0.05 on evidential and semantic failures, but not on formal ones | **Hybrid (the expected outcome):**<br>- code and the EBM decide formal truths;<br>- the decision model reads evidence;<br>- the combiner is monotone, so a reader can only raise risk |
| B6 (chat-model judge) beats everything by a wide margin | Reasoning matters more than we thought. Prioritise the reasoning extension (section 6), and distil the judge into the reader |
| Everything fails on the red team | Defences must be structural, not learned. Strengthen provenance, signatures, taint and injection isolation before any model work |

### 3.4 CS-1000: the real verdict (as cases arrive; first read at 200 cases)

The 1,000-case suite ([CASE_STUDY_PARADIGM.md](CASE_STUDY_PARADIGM.md)) is scored per cell. **Each failing cell maps to a specific fix:**

| What fails | Diagnosis | Fix | Cost |
|---|---|---|---|
| Formal truths (bands, limits, lookahead, corporate actions, arithmetic) | Missing code or a weak mandate compiler | Write the check or extend the compiler (F1). **Never train a model for a formal truth** | Days |
| Evidential truths with good ranking but bad calibration | The model knows, but its probabilities are off | Temperature or isotonic scaling per question, and conformal thresholds per action class | Hours |
| Evidential truths with bad ranking (binding, context lift, selective evidence) | The model cannot read the evidence correctly | Train the grounding verifier: head training first, then LoRA (section 5) | 1–2 weeks |
| Long-range dependencies and error chains | Context and memory, not intelligence | Trajectory features (F6), taint propagation, a **case memory** that carries forward which items are poisoned or stale (code, not model) | 1 week |
| Preference truths | The model does not know this owner | Owner adaptation (T12): a per-owner offset, plus in-context examples of the owner's past decisions | 1 week |
| Prompt injection and authority | The model obeys text it reads | Structural isolation: the reader never sees raw instructions as instructions; signatures are checked by code. Adversarial head training only on top of that | Days to a week |
| `ask_owner` recall | The model has no concept of "this is the owner's call" | An explicit `ask` class, with uncertainty and novelty triggers (F12) and conformal abstention | Days |
| Reasoning probes (unfaithful explanations) | Explanations are stories, not reasons | Explanations are **generated from attribution** (F13), never from free text. Reasoning, where used, is structured (section 6) | 1 week |

### 3.5 Kill rules, and what would change the plan

- If no learned reader beats B1 (code only) by ≥ 0.03 coverage on CS-1000's evidential cells, **learned readers are not worth their attack surface**. Ship code plus calibration, and send the rest to the owner.
- If escalations exceed 15% of actions, the cheap path is failing. Fix it; do not just buy more judging.
- If CS-1000 scores differ from the unseen-world scores by > 0.10, our simulator is misleading us. Rebalance training data towards CS-style cases and real filings.

---

## 4. Data: what we train and calibrate on

**The principle (from the blueprints): distil verified labels, never teacher behaviour.** Every training label comes from code, from a verified source, or from an owner. Never from a model's opinion alone.

| Source | What it gives | Label quality | Use |
|---|---|---|---|
| **The label factory** (counterfactual pairs, T19): change one factor and label by code | Decision boundaries for every formal cause, plus invariance pairs | Exact | Head training, LoRA, and calibration of formal readers |
| **XBRL facts from SEC filings** (every reported number tagged with entity, period, unit and concept) | Unlimited **binding-error pairs** with exact labels: same value, different period, concept or entity | Exact, real | **The best source for the core skill.** Generate claims like "Q3 revenue was $X" with X from the wrong period or concept |
| SEC N-PORT holdings (T08, done) | Real purpose and mandate tests (the 80% rule) | Exact | Purpose-drift readers and the mandate compiler |
| Public financial question-answering and verification sets (numeric reasoning over tables and filings, and financial fact-checking; T17 audits the licences) | Numeric grounding and table reading | Human-labelled | Pre-training the grounding head. Each set's licence is checked first |
| Independent worlds (T02a–d), red team (T06), capability benchmark (T16) | Unseen distributions and attacks | Exact by construction | **Evaluation only** (held out) |
| **CS-1000 cases 1–700** | Realistic, cluttered, multi-decision cases | Generator-labelled, audited by the founder | Training and calibration (5-fold) |
| CS-1000 cases 701–1000 | — | — | **Sealed test** |
| Live owner decisions on holds, later, plus an audit slice of allowed actions | Real preferences | Ground truth | Owner adaptation, then the population model |

---

## 5. The training ladder: cheapest first, each step must earn the next

Each stage must beat the previous one by ≥ 0.03 headline coverage on held-out data, or we stop and keep the cheaper one.

| Stage | What changes | Data | Compute | When |
|---|---|---|---|---|
| **0. Zero-shot** | Nothing. Measure the ceiling (G1) | — | Hours on 2 A6000s | Now |
| **1. Calibration** | One temperature per question, isotonic per action class, conformal thresholds | Calibration split | Minutes, CPU | Right after G1 |
| **2. Head training** | Train only the small readout or joint head of the decision model on **our** typed questions. The backbone is frozen. The Karpo and Clef heads are a few million parameters | Label factory, XBRL pairs, CS-1000 train folds | Hours per model, 1–2 cards | After G2, if ranking is the gap |
| **3. LoRA** | Low-rank adapters on the upper backbone layers, plus the head | The same, plus hard examples mined from stage-2 errors | 1–2 days per model; on 2 A6000s, may need 4-bit loading for 31B training | Only if stage 2 plateaus and the gap is ≥ 0.03 |
| **4. Distil** | Train a 9B model or a small encoder to match the tuned big reader **on verified labels** (big-model scores used only as soft targets where labels agree) | Everything above | 1–2 days | Only after the big reader is proven, for latency |
| **5. Layer surgery** | Cut the upper layers for speed (a layer sweep finds where the useful signal peaks) | — | Hours | Last. Only if latency demands it and quality is proven |
| Not in v1 | Reinforcement learning, full fine-tuning, new architectures from scratch | — | — | Unless CS-1000 shows a gap nothing above closes |

---

## 6. Extending a decision model so it can reason when it must

The founder's question: decision models answer in one pass, without reasoning. Can we extend them so they reason when a case needs it? **Yes, and there are four ways, from least to most surgery.** The plan is to start with A and C, which need no surgery, and run B as a research experiment once CS-1000 shows where reasoning would help.

### A. Two-speed cascade ("System 1 / System 2")

```
decision model (one pass, calibrated)
   │  confident and familiar ──▶ decide
   │  uncertain, novel, or high severity ──▶
   ▼
reasoner (a chat model at max reasoning) ──▶ writes a structured analysis:
   claims to check, numbers to recompute, items to compare
   ▼
code executes each check against the fact table and the documents   (no free-text verdicts)
   ▼
decision model re-scores, with the verified results added to the state  ──▶ can only tighten
```

- **Why:** the reasoner proposes, code verifies, and the decision model decides. Injection into the reasoner can at worst cause a hold.
- **Cost:** reasoning runs only on the 10–15% of actions that escalate.
- **Test:** CS-1000's hard and expert tiers, and the `numeric_chain` and `authority_chain` probes.

### B. One backbone, two heads (the "chop and extend" option)

Karpo is Gemma 4 31B with a decision readout. Clef is Qwen 3.8 27B with a joint schema head. The backbone still has its language-model head, and the decision fine-tune changed its weights.

**Experiment X8:**
- keep the decision head for typed answers;
- restore generation with a small LoRA adapter on the same backbone, trained to write structured reasoning that ends in a typed verdict;
- switch adapters per request.

One set of weights then gives both a fast typed answer and, when needed, an explained answer, and the two can be checked against each other (a consistency probe). **Risk:** the adapter can disturb the decision head's calibration, so the two are evaluated separately. **Run only after G1 shows which backbone reads best.**

### C. Reasoning at ingest, not at decision time

Most heavy reasoning can happen **when a document arrives**, where latency is free:
- extract quote-anchored facts (F2);
- resolve periods, entities and concepts;
- note contradictions with earlier documents;
- build "evidence cards".

At decision time, the decision model reads these cards instead of raw text. This moves intelligence off the hot path. It also turns the binding problem ("which period is this number?") into a lookup.

### D. Program-of-thought checks

For numeric and binding questions, the reasoner writes a **small verification program** over the fact table: recompute the weight after this order; compare the claimed quarter to the filing's quarter. A sandbox runs it, and the program's output is evidence. This is A with a stricter interface, and probably the strongest option for financial-model fidelity.

**Recommendation:**
- C (ingest reasoning) and A (cascade) are the main path. They need no model surgery, and each part is testable.
- D is the interface for numeric checks inside A.
- B is the research bet, run once G1 and CS-1000 tell us which backbone and which failures are worth it.

---

## 7. Milestones and what to expect

| # | Milestone | Done when | Our honest expectation |
|---|---|---|---|
| M1 | **G1** zero-shot readers | All four models scored on T05's items | 70%: the 31B and 27B match the hosted reader within 0.02. 50%: a 9B is within 0.02 of its big sibling |
| M2 | Corrected world and benchmark | T31, T15, T16 passed | Binding errors are the hardest family. Messy cases cost readers 0.05–0.15 AUROC |
| M3 | **G2** readers on messy and binding cases | Scored | 60%: binding needs training (stage 2 or 3) |
| M4 | CS-1000, first 200 cases | Scored per cell | Formal cells: code ≥ 0.95. Evidential: best model 0.75–0.90. Preference: weak until owner adaptation. Probes: chat models fail injection and confident-agent probes often |
| M5 | Stack race (T07) | All baselines on unseen worlds and the red team | 65%: the hybrid wins. Code plus EBM carries the formal truths; the decision model reads evidence |
| M6 | Training (stages 1–3) on the weakest evidential cells | +0.03 or better per stage, or stop | Calibration alone fixes 1–2 cells. Head training gives the big jump on binding |
| M7 | Reasoning cascade (A, with C and D) | Escalation slice of CS-1000 hard and expert | It lifts the expert tier but not the standard tier. It earns its place only on the escalated slice |
| M8 | Shadow mode on a paper-trading agent | 4 weeks of live traces with owner review | The first real preference labels. The calibration drift monitor (F15) proves its worth |

---

## 8. What we are deliberately not doing yet

- Training a model for anything code can decide exactly.
- Picking a model by leaderboard. Only our own suite decides.
- Long-context or bigger models before quality is proven on CS-1000 (the founder's ordering: robust function first).
- Letting any model approve. System One only tightens (D2).
- Generating owner explanations from free text. They come from attribution.
