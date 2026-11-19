# System One blueprint: what it is, what it must do, and how to build it

Written by the lab lead on 2026-11-19, for the founder. This is the end-to-end plan: the job, the inputs, every function the system needs, the architecture, the data, the training, the safety properties, the evaluation, the runtime and the build order.

Each statement carries a status:

- **Decided** means a numbered decision in [DECISIONS.md](DECISIONS.md).
- **Evidence** means we measured it.
- **Proposed** means the lead's reasoning, not yet tested or approved.

Background documents: [SYSTEM-ONE.md](../SYSTEM-ONE.md) (the vision), [ARCHITECTURE.md](ARCHITECTURE.md) (the architecture study) and [SPRINT.md](../../../research/system_one/SPRINT.md) (the sprint now running).

---

## 0. In one paragraph

System One is the judgement layer of OrderGuard. It sits between an owner's AI trading agent and the code that authorises orders. For each thing the agent does, it answers one question: **would this owner endorse this, given what the agent legitimately knew at the time?**

It answers with:

- a calibrated probability;
- the cause, named and pointing at the evidence;
- a decision of allow, hold or ask, under a stated bound on how often it lets through something the owner would reject.

It can only make things stricter. Code is still the only thing that says yes.

It is not one big model. It is a chain:

1. **Exact code checks.** Most of the work, and provable.
2. **A few narrow learned readers.** They read wording and decide whether evidence supports a claim.
3. **A monotone score combiner.**
4. **A statistical error-rate guarantee.**
5. **A strong judge for the rare unclear case.**
6. **A per-owner adjustment.**

The LLM is used mostly **before** decision time, as a compiler, a data source and a teacher. It is used at decision time only for the rare escalation. The edge over competitors is **labels we can generate with certainty, and the reasoning graph recorded at decision time**, not any one model.

---

## 1. The job

### 1.1 Where System One sits

```
 owner ── signs ──▶ mandate (purpose, bands, limits, who may approve)
                        │
 agent ──▶ harness ─────┼──▶ records the "why graph": documents, notes, claims, quotes, theses, actions
                        │
                        ▼
                  SYSTEM ONE  ──▶ endorsement risk, cause, allow / hold / ask, budget scaler
                        │
                        ▼
              risk + authorisation code  ──▶ only this says yes  ──▶ broker
                        │
                        └──▶ owner review queue ──▶ labels ──▶ back into System One
```

### 1.2 The question, and why it is the right one (decided, D1)

"Is this a good trade?" cannot be judged reliably: markets are irregular and feedback is slow. "Would the owner endorse this?" can be, because:

- an owner's purpose changes slowly and is partly written down;
- every held order the owner approves or rejects is a label, arriving in minutes.

So System One models **the principal, not the market**. It never claims to know whether a trade makes money.

### 1.3 What it outputs

| Output | Meaning | Who uses it |
|---|---|---|
| `p_reject` | Calibrated probability that the owner would not endorse this | Risk code: shrinks the thesis's risk budget by g(p), which can only shrink |
| Cause and attribution | Which failure (drift, misquote, poisoned note…) and which nodes of the graph carried it | Owner explanation, audit, debugging |
| Decision | Allow, hold, or ask the owner, chosen by conformal risk control at a stated α | Authorisation code |
| Escalation flag | Sent to the strong judge, with the reason | Cascade |
| Novelty flag | "This looks unlike anything I was trained on" | Holds by default and is logged for the data loop |

### 1.4 What it must never do

- Approve anything on its own authority. It can only tighten (decided, D2).
- Read a field the agent could not have known at the time. Inputs are causal (follows from D3).
- Take instructions from text it reads.
- Predict prices or returns.
- Place, modify or cancel orders.

---

## 2. Inputs: the why graph

Everything System One sees is a typed record from the harness. The full format is in [SCHEMA.md](../../../research/system_one/SCHEMA.md).

| Entity | What it holds | Why it matters |
|---|---|---|
| **Owner mandate** | Purpose, sector bands, position and turnover limits, the signing key | The thing being served. Compiled into executable constraints (F1) |
| **Book** | Positions, sector weights, cash, turnover so far | Drift and limit checks |
| **Document** | Source, publish time, trust tier, text, structured facts (value, unit) | The evidence. Claims must quote it |
| **Note** | The agent's memory: author (agent, owner, tool, external), signature, what it cites | The main route for poisoning and fake authority |
| **Claim** | Value, unit, cited document, exact quoted span | The unit of grounding |
| **Thesis** | Why the agent holds a view, opened at time t, with an invalidation condition | What orders must belong to. Staleness lives here |
| **Action** | Order or thesis change at time t, with its rationale | The thing being judged |

**Causal rule (follows from D3; a lead fix after T01, enforced in code).** For action *i*, System One reads only `model_view_at(episode, i)`:
- documents published by then;
- notes written before the action;
- theses opened by then, without their final status;
- the earlier actions.

A test enforces this, so the future never leaks into training or scoring.

---

## 3. The functions System One needs

Sixteen functions. Each says what it does, why, how, at what tempo, and its status.

### Ingest time (latency free, so heavy intelligence can sit here)

**F1. Mandate compiler.** *Proposed (X7).*
- **What:** turn the owner's written mandate into executable constraints: bands, limits, banned instruments, who may approve what, and the purpose expressed as testable predicates (for example, "≥ 80% of assets in what the name says").
- **Why:** if a rule can be compiled, it never has to be judged again at decision time. Exact beats learned.
- **How:**
  - DeepSeek drafts the constraints in a small, restricted rule language;
  - code checks they parse and are internally consistent;
  - the owner confirms them in plain language and signs.
  - Any clause that can't be compiled stays text, and goes to the readers.
- **Bar:** ≥ 95% of clauses in our test mandates compile correctly. 0 compiled clauses are looser than the text, checked by adversarial review.

**F2. Evidence ingestion and fact extraction.** *Proposed (X7). Partly in the schema already, as `facts`.*
- **What:** when a document arrives, pull out its facts (value, unit, entity, period), each **anchored to the exact quote** it came from.
- **Why:** claims are then checked against a fact table by code, not by reading.
- **How:**
  - DeepSeek extracts;
  - code rejects any fact whose quote is not an exact substring of the document;
  - a sample is cross-checked by a second extraction pass.
- **Bar:** fact precision ≥ 98% on a hand-checked sample. Every fact carries its quote.

### Decision time: code (exact, provable)

**F3. Structural checks.** *Built (T03), in review.*
- **What:** 41 signals, each oriented so that a larger value means more risk. Grouped by cause:
  - **drift:** out-of-band weight, CUSUM, turnover, position excess;
  - **unsupported claim:** no source, source not yet published, quote not in source, unit not in source;
  - **misquote:** relative error against the nearest fact, unit swaps, scale errors;
  - **poisoned note:** an external or tool note citing only low-trust sources, unsigned, not visible yet;
  - **authority spoof:** unsigned notes asserting permission;
  - **stale thesis:** invalidation conditions met, age.
- **Why:** these failures are facts in the record. Code finds them exactly and explains itself.
- **Tempo:** microseconds to milliseconds per action.

**F6. Trajectory monitor.** *Partly built: CUSUM and turnover are in T03.*
- **What:** across many actions, is the agent drifting, looping, overtrading, or acting on context that changed under it?
- **How:** sequential tests (CUSUM, change-point), fee drag, cancel ratios, thesis churn. All code.

**F7. Swarm monitor.** *Later (phase 4).*
- **What:** are agents that look "independent" actually driven by one root source?
- **How:** shared-citation graph, correlated entries; cap the combined exposure to one root.

### Decision time: learned readers (narrow, never generative in the hot path)

**F4. Grounding verifier.** *The core learned skill. T05 and T11 now; X6 proposed.*
- **What:** given a claim, its quote and the source's facts and surrounding text, does the source actually **support** the claim? It catches:
  - a quote lifted out of context;
  - "revenue grew 12%" when the source says "guidance for 12%";
  - a right number for the wrong period or entity.
- **Why:** this is the only real reasoning left once F1–F3 have run. Code catches exact mismatches; this catches meaning mismatches.
- **How:** see section 6.

**F5. Manipulation reader.** *T05 and T11 now.*
- **What:** three questions:
  - is this wording hype?
  - is this text claiming authority it doesn't have?
  - is this text addressing the reviewer, which is prompt injection?
- **How:** the reader tournament (X2). The output can only raise risk.

### Decision time: combining and deciding

**F8. Score combiner.** *T04 and T07 (X1).*
- **What:** all signals in, one calibrated `p_reject` out, plus each signal's share of it.
- **Rule:** monotone. More evidence of risk can never lower the score. This is certified by enumerating every shape function (claim C3).
- **Candidates:** an Explainable Boosting Machine, where each term *is* the explanation, against monotone boosted trees with TreeSHAP. X1 picks between them.

**F9. Risk control.** *T07.*
- **What:** turn `p_reject` into allow, hold or ask, with a guarantee: the rate of allowed actions the owner would reject is ≤ α (0.05), per action class.
- **How:** conformal risk control on a calibration set. The guarantee holds only while live data resembles that set, so calibration drift is monitored (F15).

**F10. Escalation judge.** *X3 and X5.*
- **What:** the few actions that are uncertain (near the threshold) or novel (F12) go to a strong judge. Its answer can only move the decision towards hold.
- **Who:** DeepSeek at max reasoning or the external decision model, whichever agrees more with the true labels (T11 decides).
- **Budget:** at most 15% of actions escalate, or the cheap stack is failing (X3 kill rule).
- **Injection safety:** the judge's text output is parsed into a fixed verdict, and it can only tighten. So injecting the judge can at worst cause a hold.

**F11. Owner adaptation.** *T12 (X4).*
- **What:** this owner tolerates momentum language; that one never wants small caps. Learn each owner from a handful of decisions.
- **Candidates:** a per-owner offset with partial pooling towards the population, against an in-context tabular learner given k of the owner's past decisions, against conformal only.
- **Rule:** adaptation may tighten freely. It may loosen only within the compiled mandate, and only from the owner's own signed decisions.

**F12. Novelty detection.** *Proposed.*
- **What:** flag actions unlike anything seen.
- **How:** distance in the verifier's internal representation, plus conformal nonconformity scores. Novel actions hold or escalate.

### After the decision

**F13. Owner explanation.**
- Each hold reads like this: "Held: the claim '12% revenue growth' cites the Q3 note, which says *guidance* of 12%. Cause: misquote. Evidence: [quote]."
- It is generated from the attribution, never from a model's free-form story (SYSTEM-ONE.md, section 8: no self-justification).

**F14. Learning loop.**
- Every owner decision on a hold is a label.
- A small random **audit slice** of *allowed* actions is shown to owners afterwards. This corrects the bias of only learning from holds.
- Labels feed F11 at once, and the population model on a schedule.

**F15. Monitoring.** Watch:
- calibration drift (the conformal guarantee depends on it);
- escalation rate;
- hold rate per owner;
- latency;
- reader agreement with the judge;
- novelty rate.

Alarms tighten automatically.

**F16. Audit and replay.**
- Every decision is stored with its exact inputs, model versions and outputs.
- Any decision can be replayed. Counterfactual replay (remove one cause and re-score) both explains decisions and creates training labels.

---

## 4. The cognitive core: what intelligence is actually needed

Strip the job to its mental operations and only four remain:

| Operation | Nature | Where it is solved |
|---|---|---|
| **Arithmetic** over the book and the rules | Exact | Code (F1, F3, F6) |
| **Grounding:** does this source, from someone this trusted at this time, support this claim? | Short, structured reasoning: find the quote, compare value, unit, period and entity, weigh trust | Code where exact (F2, F3); a narrow verifier where it is about meaning (F4) |
| **Manipulation:** is this text trying to steer the reviewer? | Reading intent in wording | Narrow reader (F5) |
| **Owner intent:** would *this* owner sign it? | Preference from few examples | F11 over the combined signals |

**What is not needed:**
- open-ended writing;
- broad world knowledge;
- long chains of thought;
- conversation;
- predicting the next word.

Next-word prediction is the most expensive part of an LLM and the least useful part for this job.

**The design principle that follows (proposed):**

> Put intelligence where time is free and its output can be checked: ingest time and training time. Keep the decision path exact, narrow and impossible to give orders to.

---

## 5. Architecture

### 5.1 By tempo

| Tempo | What runs | Latency target |
|---|---|---|
| **Onboarding**, once per owner | F1 mandate compiler, owner confirms | Minutes; human in the loop |
| **Ingest**, per document | F2 fact extraction, quote-anchored | Seconds; off the order path |
| **Thesis**, when a thesis forms or changes | F3, F4, F5, F8, F9, F11; the verdict is cached on the thesis | p99 ≤ 300 ms with GPU readers; ≤ 50 ms for code plus combiner (C6) |
| **Order**, on every order | Code proves the order belongs to a judged, still-valid thesis, plus F3 per-order checks (turnover, limits) | Microseconds to milliseconds |
| **Escalation**, rare | F10 judge | Seconds; the order waits as a hold |
| **Continuous** | F6 trajectory, F7 swarm, F15 monitoring | Background |
| **Offline** | Training, calibration, the label factory | Hours |

Judgement happens when a thesis forms, not on every order (decided, D4). An order only has to prove, in code, that it belongs to a thesis already judged. That is why System One never slows the order path (SYSTEM-ONE.md, section 5).

### 5.2 The chain

```
 why graph (causal view)
   │
   ├─▶ F3 code checks (41 signals) ───────────────┐
   ├─▶ F4 grounding verifier   (score per claim) ──┤
   ├─▶ F5 manipulation reader  (3 scores) ─────────┤──▶ F8 monotone combiner ──▶ p_reject + attribution
   ├─▶ F6 trajectory signals ──────────────────────┤            │
   └─▶ F11 owner offset / context ─────────────────┘            ▼
                                                     F9 conformal risk control ──▶ allow / hold / ask
                                                                 │
                                                uncertain or novel (F12)
                                                                 ▼
                                                     F10 judge (can only tighten)
```

**Tighten-only, by construction (decided, D2):**
- every reader's score enters the combiner with a monotone-increasing constraint;
- the judge can only move the decision towards hold;
- owner adaptation loosens only within the compiled, signed mandate.

So a reader that adversarial text fools can cause a hold, never a breach.

### 5.3 The three candidate stacks (from ARCHITECTURE.md)

- **A. Local:** every reader runs on our hardware.
- **B. Decision-model readers:** the external decision model answers the reading questions.
- **C. Cascade:** A or B is always on, with escalation for the tail.

**Provisional pick: C (D10).** These results would switch it:
- escalation adds < 0.10 recall on novel failures → **A alone**;
- the decision model beats local readers by > 0.05 AUROC on unseen wording → **B as the base**.

---

## 6. The learned parts, in detail

### 6.1 The grounding verifier (F4): the proposed design (X6)

The proposal is a **cut-down pretrained transformer that scores, not writes.**

1. **Choose the base model on evidence.**
   - T11 runs hidden-state probes on a few strong open models, at every few layers.
   - The model and layer whose features best separate supported from unsupported claims, on wording it has never seen, wins.
   - No default model (decided, D10: nothing is chosen by habit).
2. **Cut it.**
   - Keep the layers up to the best layer L\*; drop the rest and the word-prediction head.
   - Published work finds the middle layers of large models often give better features for classification than the last ones, because the top layers specialise in next-word prediction.
   - Cutting roughly halves the cost.
3. **Typed input slots, not one blob of prose.** The input is:

   `[CLAIM] text, value, unit, period, entity [QUOTE] span [SOURCE] nearby text [FACTS] value, unit, period, entity rows [META] source trust tier, author kind, signed?`

   - Numbers go in as numeric values through a small embedding, not as text tokens, because LLMs are weak at numbers written as text.
   - Claim and evidence attend to each other directly.
4. **Score outputs instead of words.** Small heads on the pooled state:
   - `supported`;
   - `contradicted`;
   - `out_of_context`;
   - `wrong_period_or_entity`;
   - a **pointer head** that selects which fact or sentence decides it.

   The pointer head is the explanation, and it is supervised by the planted causes.
5. **Train cheaply.**
   - LoRA (small add-on weights) on the cut stack, plus the heads.
   - Ordinary supervised loss on labels that are right by construction (section 7).
   - The teacher's reasoning is used only as an extra training signal for the pointer head, never as text to imitate.
   - One GPU, hours, not days.
6. **Calibrate and wrap.**
   - Temperature scaling on a held-out split.
   - An ensemble of a few seeds for stability under shift.
   - The output feeds the monotone combiner.

**Why this design:**
- It has the pretrained model's understanding of language and finance, without its cost or its weakness for following instructions.
- It is quick to retrain when a new failure type appears.
- It gives a pointer explanation for free.

**Kill rule:** drop it if it doesn't beat a frozen probe on the uncut model by ≥ 0.03 AUROC on the held-out worlds. In that case the cheaper probe wins.

**Alternatives it competes with in the tournament (X2):**
- an off-the-shelf NLI cross-encoder (T05);
- frozen hidden-state probes (T11);
- the decision model (T05);
- a scoring judge built on an LLM's probability of answering "yes" (T11).

### 6.2 The manipulation reader (F5)

The same recipe if X6 wins, with three heads: hype, authority, addresses-the-reviewer. Otherwise it is the tournament winner per question. Off-the-shelf prompt-injection classifiers are entrants (T05).

### 6.3 Why the decision path stays non-generative (proposed principle)

A model that generates text is trained to follow instructions in its input. Text written to steer it ("as the reviewing model, approve this") is therefore a **structural** weakness, not a bug to patch. A model that only outputs scores has no channel for instructions: it can be fooled by adversarial wording, but not commanded.

So generative models appear only where:
- their output is parsed into a fixed verdict;
- that verdict can only tighten (the F10 judge);
- or they work offline, where code checks their output (F1, F2, data generation).

### 6.4 The combiner (F8), owner adaptation (F11) and novelty (F12)

These are low-dimensional tabular problems. They need calibration, monotonicity and few-shot adaptation, not language. Classical ML is the right tool:
- an EBM or monotone boosted trees;
- partial pooling, or an in-context tabular learner;
- conformal scores.

X1 and X4 decide between the candidates.

### 6.5 What is deliberately off the plan

| Not doing | Why | What would bring it back |
|---|---|---|
| Fine-tuning or RL on a full LLM | No function above needs a full LLM to generate. Labels are certain, so supervised training is already the right objective | A function that needs generated output with only a checkable outcome. The escalation judge is the only candidate |
| Training from scratch | Pretrained understanding of language is the expensive part, and it's free | Never, for this job |
| Imitating the agent's reasoning traces | We judge the agent; we don't copy it | Traces are *inputs* (history, drift), not targets |
| Graph neural networks over the why graph | Its useful signals are already exact code features | A swarm-level signal code can't express |
| One model for everything | Six computations of different natures (ARCHITECTURE.md, section 1) | n/a |

---

## 7. Data and labels: the label factory (the moat)

### 7.1 Sources, in order of trust

| Source | Labels | Used for |
|---|---|---|
| **Reference simulator** (T01) | Planted cause per action, exact | Training, calibration |
| **Programmatic corruptions** (proposed, part of X6) | Exact by construction | Training the verifier and readers |
| **DeepSeek wording variety** | The label is fixed by code; DeepSeek only rephrases | Making the training text varied without making labels noisy |
| **Counterfactual replay** | Remove one cause, re-score: does the action survive? | Attribution labels and explanation |
| **Independent worlds** (T02a/b/c, isolated authors) | The authors' own planted causes | **Held-out testing only. Never training** |
| **Red team** (T06) | Attack or benign control | Held-out testing; later a separate split for hardening |
| **Real filings** (T08, SEC N-PORT) | Rule-based purpose fit, sampled for review | Real-world purpose check (C5) |
| **Owner decisions plus the audit slice** | The real target | Owner adaptation, population updates, calibration |
| **Teacher labels** (DeepSeek at max reasoning) | Judgement, possibly wrong | Only for cases code cannot label, and always marked as teacher labels |

### 7.2 The corruption operators (proposed)

Each takes a correct claim and makes a wrong one with a known cause:

- **number shift:** ±1–30%;
- **unit swap:** % and bp, $M and $B;
- **period swap:** Q2 and Q3, guidance and actual;
- **entity swap:** subsidiary and parent, peer company;
- **context lift:** quote "could grow 20%" as "will grow 20%";
- **negation drop;**
- **source swap:** cite a trust-tier-0 blog for a filing's number;
- **signature strip** on an owner note;
- **time travel:** cite a document published after the action.

Each also has a **hard negative**: a change that looks suspicious but is fine, such as an accurate rounding, a correct unit conversion, or a properly signed approval. Without these, a model learns "anything unusual is bad", and the benign controls catch it.

### 7.3 Rules

- Held-out worlds and red-team cases never enter training, features or thresholds (leakage guard in every brief).
- Every training row is built from the causal view.
- Teacher labels are kept separate and down-weighted. They never outvote a label made by code.

---

## 8. Training recipe

1. **Code first.** F1–F3 and F6 have no training.
2. **Readers.** Tournament (T05, T11). Then, if approved, the cut-down verifier trained on corruptions plus rephrasings (X6).
3. **Combiner.** Fit on the reference world with monotone constraints. Calibrate.
4. **Conformal.** Thresholds per action class on a calibration split.
5. **Owner adaptation.** Fit the pooling prior across simulated owners. Test on hidden owner preferences (T12).
6. **Escalation threshold.** Set from X5: how far each reader is from the judge, and at what uncertainty the judge adds recall.
7. **Distillation (proposed).** Where the judge reliably catches what the stack misses, distil those catches into the verifier as extra training data, labelled as teacher data. Over time, escalations shrink.

**Why no RL now.** Our outputs are labels with known answers, and standard supervised training is the right method for that. RL pays off when the output is a long generated text and only the end result can be checked. Published work also finds that RL mostly sharpens what a model can already do; new detection skill comes from data. RL is reconsidered only for the escalation judge, and only if X5 shows it is worth it.

---

## 9. Safety properties, and how each is enforced

| Property | Enforcement |
|---|---|
| Code is the only thing that says yes | System One's output only feeds g(p), which can only shrink, and holds |
| Tighten-only | Monotone constraints, certified by enumeration (C3); the judge can only tighten; adaptation loosens only within the signed mandate |
| No future leakage | `model_view_at` plus a regression test |
| Text cannot give orders | No generative model in the decision path except the parsed, tighten-only judge |
| Provenance over presence | Every note and claim is weighted by who wrote it, whether it is signed and its source's trust tier, never by the fact that it is in context |
| Honest confidence | Calibration (ECE) measured on held-out worlds; a conformal bound per class; drift alarms |
| Fail closed | If a reader or the judge is down, fall back to code plus the combiner with a tighter threshold. Never fail open |
| Explanations are not stories | Explanations come from attribution and pointers recorded at decision time |

---

## 10. Evaluation: how we know it works

### 10.1 Sprint S1 claims (running now)

| # | Claim | Bar |
|---|---|---|
| C1 | Judges, not memorises | Mean AUROC ≥ 0.85 on three independent worlds, none < 0.75; ECE ≤ 0.10; ≤ 2% holds on clean |
| C2 | The explanation is the model | Top term names the planted cause on ≥ 80% of flagged held-out actions |
| C3 | Text cannot loosen | 0 violations across ≥ 500 red-team cases, plus a monotonicity certificate |
| C4 | The guarantee holds | Bad-allowed rate ≤ 0.05 per held-out author, with a 95% confidence interval |
| C5 | Purpose fit on real data | ≥ 1,000 real funds; ≥ 90% reviewer agreement on 30 flagged |
| C6 | Fast enough | Code plus combiner p99 ≤ 50 ms; text p99 ≤ 300 ms on GPU |

### 10.2 Added by this blueprint

- **Recall on novel failures** at a 2% hold rate, reported separately. These are the families the authors invented.
- **Escalation rate**, which must stay ≤ 15%.
- **Distance to the judge** per reader (X5).
- **Pointer accuracy:** does the verifier point at the deciding fact?
- **Extraction precision and compile correctness** (X7).
- **Per-owner lift** from adaptation (X4).

### 10.3 What we know so far (evidence)

- The old baseline scored 0.974 AUROC in distribution and **0.634 under shift**. In-distribution scores flatter us.
- On the new reference world, every model scored 0.97–0.99 AUROC. That world **cannot tell models apart**, so the independent worlds are the real test.
- Real filings (T08, under review): 6,092 real funds testable. 191 are below the 80% names rule on a headline test, and 127 stay below on the strict test. This is not a legal finding.

---

## 11. Runtime and deployment

- **Placement.** The code checks and combiner run in the OrderGuard harness process, on CPU. The readers run as a service: GPU if available, CPU fallback. The judge is an external call, used asynchronously while the action is held.
- **Caching.** Verdicts are cached per thesis. Reader scores are cached by a hash of their exact input.
- **Versioning.** Every decision records the model, rule and calibration versions. A new version runs in shadow mode first, with its decisions logged but not used.
- **Rollout per owner.** Start in **shadow mode**: scores logged, nothing held. Then **hold-only mode**, then full mode. Each step needs that owner's calibration to be checked.
- **Monitoring.** F15. Calibration drift past its alarm tightens thresholds automatically and pages the operator.

---

## 12. Build plan

| Phase | What | Exit criterion | State |
|---|---|---|---|
| **0. World and real-data check** | T01 world, T08 SEC check, T09 GPU | World frozen; real funds scored | **Done**: T08 is in its fix round |
| **1. Sprint S1** | T02 independent worlds, T03 checks, T04 harness, T05 readers, T06 red team, T07 verdict | C1–C6 each reported pass or fail, plainly | **Running** |
| **2. Readers and owners** | T11 GPU probes and judges (X2, X5), T12 owner adaptation (X4); proposed X6 cut-down verifier, X7 compile-once | Final D10 written from evidence | Next; X6 and X7 need founder approval |
| **3. In the product** | Wire into the harness; shadow mode; owner review queue; audit slice; F13 explanations | One real owner in shadow mode for 2 weeks, calibration holds | After phase 2 |
| **4. Higher levels** | F6 trajectory in full, F7 swarm, book-level review | Each with its own kill criterion | Later |

---

## 13. Risks, and what would kill the design

| Risk | Sign | Response |
|---|---|---|
| The readers don't carry to new wording | Held-out AUROC < 0.75 for any author | More corruption and rephrasing variety; X6; if still failing, B or C with a higher escalation rate |
| Same-lab authors (all DeepSeek) share blind spots | Held-out scores look too good | Report it next to C1. Add a human-written world, or one from a different lab, before claiming generality |
| Escalation becomes the system | > 15% escalate | The cheap stack failed. Revisit readers, don't buy more judge |
| Calibration breaks live | ECE drift alarm | Tighten automatically; recalibrate on owner decisions |
| Owners rubber-stamp holds | Approve rate near 100% with no reading | Audit slice; measure time spent per review; ask fewer, better questions |
| Extraction errors (X7) poison the fact table | Precision < 98% | Facts must quote exactly; a second-pass check; uncertain facts fall back to the reader |

**What would kill System One as designed:** if, after phase 2, no reader reaches the C1 bar on the independent worlds *and* the judge doesn't fix it within 15% escalation, then judging from the recorded graph is not enough. Back to the drawing board on inputs, not models.

---

## 14. Decisions waiting on the founder

1. **X6 and X7:** add the cut-down verifier and compile-once experiments to the lab. This includes downloading open models to the GPU as test subjects (never as workers).
2. **SEC contact:** a contact identifier for the live EDGAR check (C5's live part). Until then, the archived copy is used.
3. **The ChatGPT web bridge:** whether to push code publicly. No push without approval.

---

## 15. Glossary

| Term | Plain meaning |
|---|---|
| **AUROC** | How well a score ranks bad above good. 0.5 is a coin flip; 1.0 is perfect |
| **ECE** | Calibration error: how far "70% sure" is from being right 70% of the time |
| **Conformal risk control** | A statistical method that sets a threshold so the error rate stays under a chosen bound, if new data resembles the calibration data |
| **Monotone** | More risk evidence can only raise the score, never lower it |
| **EBM** | Explainable Boosting Machine: a model that is a sum of one-feature curves, so each curve is its own explanation |
| **TreeSHAP** | A way to split a tree model's score among its inputs |
| **Probe** | A small classifier trained on a frozen model's internal activations |
| **LoRA** | Training small add-on weights instead of the whole model: cheap and quick |
| **CUSUM** | A running sum that fires when a small, persistent drift adds up |
| **Hard negative** | A case that looks suspicious but is fine, used to stop a model from flagging everything unusual |
| **Why graph** | The recorded links from each action back to its thesis, claims, quotes, notes and documents |
