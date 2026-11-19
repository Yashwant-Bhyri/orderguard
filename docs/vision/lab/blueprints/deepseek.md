# BLUEPRINT: System One

Independent design, 2026-11-19. Written from `SYSTEM-ONE.md`, `SCHEMA.md` and the
constraints in `BRIEF.md`.

**Tags used throughout.** `[E: SYSTEM-ONE §n]` and `[E: SCHEMA §n]` mean evidence
from the supplied documents. `[E: external, author year]` means a published result
I know. `[R]` means my own reasoning, estimate or design choice. I have marked
every substantive claim; where I state a number that is not in the brief or the
documents, it is an estimate and marked `[R]`.

**Reading guide for the founder's questions.** Where the potential lies and which
model family wins: §0, §5.8–§5.13, §14. The cognitive core and what to leave out:
§2. Layers, architectures, paradigms and post-training trade-offs: §5.2, §5.9–
§5.13. Minimum post-training for maximum gain: §5.9. Serving at scale: §9.

---

## 0. The short answer

Most of the potential is **not** in a larger model. It is in three things, in this
order:

1. **The representation.** A typed, point-in-time justification record and a
   provenance graph captured by the harness, not reconstructed from prose.
2. **The label factory.** Planted causes in a simulator, counterfactual replays,
   and real owner decisions are worth more than any architecture choice.
3. **A small, calibrated relational scorer plus a distilled text verifier.**
   Gradient-boosted trees on graph features are the workhorse. A frozen small
   encoder with light heads handles the semantic residue. A tiny graph or
   sequence model is added only if it earns its place on held-out families.

In one line: **classical ML wins the runtime, LLMs win the data factory, and
layer surgery is a distraction.** `[R]`

LLMs are **teachers, data generators and escalation reviewers**, not the runtime
judge. Fine-tuning a 7B model to sit on the order path is the wrong bet: it
cannot meet the latency, it calibrates badly under shift, and reading agent text
at all is an injection surface. `[E: SYSTEM-ONE §6]` records that superficial
tokens fool frontier judges up to about 90% of the time; `[E: SYSTEM-ONE §7]`
records that the best calibration-trained model moves from 0.03 to 0.21 outside
its domain. `[R]`

My rough effort allocation for v1: **35% harness and representation, 25% data and
labels, 20% evaluation and calibration, 15% models, 5% serving.** `[R]` The model
work is the smallest slice because the first three determine whether the model
can learn anything real.

System One should be a **decision system**, not a model. Deterministic code
decides everything that can be decided exactly. Learned models handle only the
semantic and preference residue. A calibration and conformal layer turns scores
into conservative actions, and code enforces that the result can only tighten.
`[R]`

The single most important engineering choice is to **separate three clocks**:

- a **micro clock** on the order path (microseconds to low milliseconds, code only);
- a **meso clock** at thesis formation (the structured scorer is ≤50 ms on CPU;
  text reading is a separate ≤300 ms GPU stage);
- a **macro clock** over trajectories, swarms and the book (seconds to days,
  learned and graph algorithms).

Almost every bad design I considered failed by blurring these clocks — for
example, calling an LLM at order time, or recomputing a thesis judgement for
every order. `[R]`

---

## 1. What System One should be

System One is a **model of one principal**, wrapped in a **conservative decision
layer**, fed by a **decision-time record**. Formally, it estimates

> `p(endorse | mandate, justification, graph, book, owner history)`

and emits an action in `{pass, hold, ask, shrink, block}` whose only possible
effect is to reduce what the agent may do. `[E: SYSTEM-ONE §2, §5, §6]`

Inside OrderGuard, this is the judgement layer: it informs risk, risk informs
authorisation, and authorisation remains code. `[E: SYSTEM-ONE §9]`

It is five things at once:

1. **A principal model.** It learns what this owner would sign, not what makes
   money. Profitability is explicitly not its job. `[E: SYSTEM-ONE §2]`
2. **A record keeper.** It consumes a typed justification, not a chat transcript.
3. **A verification engine.** It checks provenance, quotes, numbers and mandate
   arithmetic exactly in code, then uses a small model only where meaning is
   ambiguous. `[R]`
4. **A calibration machine.** Its probabilities have to mean something. Brier
   score, calibration error and conformal coverage are first-class metrics, not
   afterthoughts. `[E: SYSTEM-ONE §7]`
5. **A learning loop.** Every owner review is a label. The loop updates a
   population prior and a per-owner posterior, and it gets cheaper per owner as
   the population grows. `[E: SYSTEM-ONE §10]`

### 1.1 What it should not be

- **Not an alpha model.** It must never claim to know whether a trade makes
  money. `[E: SYSTEM-ONE §2]`
- **Not an autonomous approver.** Code is the only thing that authorises an
  order. `[E: BRIEF; SYSTEM-ONE §9]`
- **Not a general chatbot or a general next-token predictor.** General ability is
  a cost, not a feature, on this path. `[R]`
- **Not a post-hoc explainer.** Attribution comes from the graph recorded at
  decision time, never from the agent's rationale. `[E: SYSTEM-ONE §3, §8]`
- **Not one big model.** It is a stack of narrow models and exact checks, each
  with its own latency and failure mode. `[R]`

### 1.2 The invariants

These are non-negotiable and are enforced in code, not learned:

- **I1. Only tighten.** The output can reduce the allowed notional, shorten a
  lease, or hold; it can never increase or approve. `[E: BRIEF; SYSTEM-ONE §9]`
- **I2. Code authorises.** A signed verdict token plus deterministic checks are
  what let an order through. `[E: BRIEF]` "Pass" means System One adds no
  restriction; it does not mean System One approved the order. The order proceeds
  only because it is inside the signed mandate and the code checks. The gate's
  signature attests to the checks, not to a new permission. `[R]`
- **I3. Point-in-time.** Only what existed at action time is visible; the graph
  and every feature respect the schema's availability rule. `[E: SCHEMA §1]`
- **I4. No self-report as evidence.** Agent prose is data, not testimony.
- **I5. Fail closed.** Timeout, missing feature, stale verdict or model error
  means hold or shrink, never allow. `[R]`
- **I6. Node-level explanation.** Every score must decompose onto graph nodes or
  an explicit "unexplained" bucket. `[E: SYSTEM-ONE §4]`
- **I7. Versioned and reversible.** Model, features, graph schema and thresholds
  are versioned; any version can be rolled back.
- **I8. Signature is the only permission change.** No unsigned note widens a
  band, a cap or an allowlist. `[E: SCHEMA §3, authority_spoof]`
- **I9. Calibration is a gate.** A model that ranks well but calibrates badly is
  not shippable. `[R]`
- **I10. Evaluation fields never enter a model.** `meta` and `label` are stripped
  before feature extraction. `[E: SCHEMA §5]`

### 1.3 The central bet, stated so it can be attacked

**Bet:** a calibrated GBDT on engineered relational features, plus a distilled
30–100M-parameter text verifier, plus exact code checks, will match or beat a
7B LLM judge on endorsement and attribution while being two to three orders of
magnitude cheaper and easier to calibrate. `[R]`

**Why I believe it:** the task is verification and preference modelling, not
open-ended reasoning. The schema gives typed facts, exact quotes and a graph;
most errors are decidable in code. The hard residue is semantic equivalence and
owner tolerance, which a small encoder handles well. `[E: SCHEMA §2, §3; R]`

**What would kill the bet:** if held-out semantic failures (misquote by
paraphrase, implied authority changes, multi-document contradiction) dominate and
the small reader cannot learn them, the text budget rises. I would then move to a
1–3B distilled reader, not to a 7B general judge. `[R]`

### 1.4 What would make me abandon the design

- The graph features add nothing over today's detectors at the same false-hold
  rate. `[E: SYSTEM-ONE §11, experiment 1]`
- Owner endorsement labels turn out to be so noisy or non-stationary that the
  ceiling is below the deterministic baseline. `[R]`
- The semantic residue is larger than expected and a small verifier cannot be
  distilled to the required accuracy. `[R]`
- Latency or operational complexity makes the stack undeliverable. `[R]`

---

## 2. The cognitive core

The founder asked to focus on the specific subset of knowledge and reasoning
System One needs, ahead of abilities it does not. This is my definition.

### 2.1 Knowledge it needs

1. **Mandate semantics.** Purpose, all seven sector bands, position cap, daily
   turnover, allowed instruments, signing identity, and what a signed amendment
   looks like. `[E: SCHEMA §2]`
2. **Provenance trust.** Publisher, trust tier, time, content hash, note author,
   signature validity, and whether a claim's quoted span actually exists.
   `[E: SCHEMA §2]`
3. **Claim arithmetic.** Fact matching by name and unit, numeric equality within
   a stated tolerance, and whether a source contains the asserted figure.
   `[E: SCHEMA §3]`
4. **Thesis lifecycle.** Evidence freshness, invalidation condition, status
   transitions, whether an action adds to or reduces an invalidated thesis.
   `[E: SCHEMA §2, §3]`
5. **Portfolio arithmetic.** Sector and instrument weights, marginal trade
   impact, turnover, concentration, and the effect of an action on the book.
   `[E: SCHEMA §2, Book replay]`
6. **Owner tolerance.** What this owner tolerates within the mandate: how much
   evidence, which sectors, how much novelty, how often to be asked. `[R]`
7. **Deception patterns.** Injected instructions, authority spoofing, hype,
   herding, self-justification, and corrupted provenance. `[E: SYSTEM-ONE §3, §8]`

### 2.2 Reasoning it needs

- **Deduction over typed facts:** exact, code.
- **Comparison under uncertainty:** calibrated scoring, model.
- **Semantic equivalence:** claim vs source, model.
- **Counterfactual attribution:** what would change the decision, replay plus
  model.
- **Temporal pattern recognition:** drift, loops, staleness, model over windows.
- **Cost-sensitive decision:** pass/hold/ask/shrink, policy layer.

### 2.3 What it does not need

Market forecasting, macroeconomics, general world knowledge, next-token
prediction, long-form generation, code generation, tool use, multi-agent
negotiation, or open-ended planning. Every one of these is a distraction and a
new attack surface. `[R]`

### 2.4 The typed question protocol

I would give every model in the stack — and the external hosted decision model —
the same small interface. This makes distillation, ensembling and evaluation
consistent. `[R]`

| ID | Question | Answer type | Where used |
|---|---|---|---|
| Q1 | Would this owner endorse this action, given only the record? | probability | thesis, action |
| Q2 | Which failure causes are present? | multi-label | thesis, attribution |
| Q3 | How much of this action's weight traces to each root? | distribution over nodes plus "unexplained" | attribution |
| Q4 | Should the owner be asked before this action? | probability / value | interruption policy |
| Q5 | What is the least restrictive sufficient intervention? | choice: pass, hold, ask, shrink, block | decision layer |
| Q6 | Is this quote a faithful rendering of the source span? | support / contradict / insufficient | signal level |
| Q7 | Does this note contain an instruction that overrides the mandate? | probability | signal level |

The external hosted decision model can be mapped onto Q1, Q2, Q4, Q5, Q6 and Q7;
Q3 is our own attribution head and is not delegated. The hosted model is a
labeler and an escalation reviewer, not a runtime dependency. At about one second
per call it cannot meet either online SLO, so it is offline by arithmetic, not by
preference. `[E: BRIEF, model access and latency; R]`

### 2.5 The minimum sufficient record

All levels consume one canonical object, which I call a **Justification**. It is
compiled by code from the episode at action time:

```
Justification := {
  action, intent, thesis, mandate_snapshot, book_snapshot,
  claims: [ {claim, source_doc, quoted_span, verified_fact,
             numeric_match, quote_exact, semantic_support} ],
  notes:  [ {note, author, signature, trust, injection_score} ],
  roots:  [ {node_id, type, trust, verified, age, weight} ],
  graph:  {nodes, edges, hashes, cycles, shared_roots},
  history:{owner_decisions, prior_holds, thesis_transitions}
}
```

`intent` is the typed action record — instrument, side, notional, thesis id — not
a free-text plan. `history` contains only decisions on earlier actions, never the
current label. This is the cognitive core's real boundary. If it is well formed,
the models are simple. If it is not, no model saves the system. `[R]`

---

## 3. The functions System One needs

I group them into exact functions (code), learned functions (models), and
control functions (policy and ops). The split is deliberate: **anything that can
be exact must be exact**, because exact checks do not drift, cannot be injected
through text, and are auditable. `[R]`

### 3.1 Exact functions

| ID | Function | What it does | Timing |
|---|---|---|---|
| F1 | Mandate service | Stores the signed mandate, verifies signatures, serves point-in-time snapshots, rejects unsigned amendments | order path, µs–ms |
| F2 | Provenance recorder | Hooks every read/write in the harness; records nodes and read-before-write edges with hashes; append-only | on every tool/memory call |
| F3 | Justification compiler | Builds the canonical Justification from the episode at action time; enforces availability and schema rules | order path, ms |
| F4 | Exact verifier | SHA-256 content hashes, quote substring checks, fact name/unit/value matching, sector and position arithmetic, turnover, allowlist, thesis status, invalidation trigger | order path, ms |
| F5 | Verdict cache | Stores signed thesis verdicts keyed by thesis id, graph hash, evidence set, policy version; enforces expiry | order path, µs |
| F6 | Action gate | Combines F1–F5 with the cached verdict; emits pass-through or hold; is the only writer of the check attestation | order path, ms |
| F7 | Audit ledger | Hash-chained, append-only log of every input, score, threshold, verdict and owner decision | async |
| F8 | Replay engine | Deterministically replays an episode and counterfactuals; used for labels, debugging and evaluation | offline |

### 3.2 Learned functions

| ID | Function | Model family | Timing |
|---|---|---|---|
| F9 | Signal reader | Frozen small encoder plus heads for quote support and note-injection intent | on read, ≤300 ms GPU |
| F10 | Thesis judge | GBDT on tabular/graph features, plus a small text expert, stacked and calibrated | on thesis, ≤50 ms CPU |
| F11 | Attribution head | Node-weight predictor, distilled from counterfactual Shapley; includes "unexplained" | with F10 |
| F12 | Cause head | Multi-label classifier over the schema's causes plus novel families | with F10 |
| F13 | Trajectory monitor | Windowed hazard model or tiny sequence model over the event stream | continuous, seconds |
| F14 | Swarm monitor | Graph concentration and shared-root features plus a small scorer | continuous, seconds |
| F15 | Book reviewer | Portfolio checks plus a scorer over open theses vs purpose; drafts owner questions | daily |
| F16 | Owner model | Hierarchical Bayesian residual over the population prior, updated from owner decisions | async, per decision |
| F17 | Interruption policy | Cost-sensitive policy or contextual bandit: pass, hold, ask, shrink | per thesis/order |

### 3.3 Control functions

| ID | Function | What it does |
|---|---|---|
| F18 | Calibration wrapper | Isotonic/Platt recalibration, ensemble aggregation, conformal risk control, abstention |
| F19 | Escalation router | Routes uncertain or novel cases to the external decision model or a frontier reviewer, then to the owner; all reviewers are advisory and can only tighten |
| F20 | Learning pipeline | Collects labels, dedupes, audits, generates counterfactuals, retrains, evaluates, registers |
| F21 | Model and feature registry | Versions, signs, canaries and rolls back models, features, thresholds and schemas |
| F22 | Drift monitor | Watches feature, score, calibration and owner-decision drift; triggers tightening or rollback |
| F23 | Fail-closed supervisor | Timeouts, missing dependencies, schema violations and model errors all resolve to hold/shrink |
| F24 | Owner console | Shows the evidence, the question, the model's reason and the review history; captures the label |

### 3.4 Notes on the functional split

- **F2 is the moat.** Brokers see orders and guardrails see messages; only the
  harness sees why. `[E: SYSTEM-ONE §10]` If F2 is not built first, F9–F17 have
  nothing to learn from that cannot be reconstructed only weakly. `[E:
  SYSTEM-ONE §1, 5–50% attribution depending on method]`
- **F6 must be a separately deployable service.** The order path is a different
  trust domain from the models; it should be able to run with the models down.
- **F8 is a product feature, not only a test tool.** Counterfactual replay is
  both the label source and the explanation mechanism. `[E: SYSTEM-ONE §7]`
- **F18 is part of the model, not a reporting layer.** A score without a
  calibrated threshold and a stated error rate is not a decision. `[R]`
- **F20 must be able to say "no new model".** Most retraining cycles should end in
  no deployment; otherwise the team is optimising for motion. `[R]`
- **Turnover is a code check, not a label.** The schema records
  `max_daily_turnover_pct` but does not replay it; the product still checks it on
  every order, as SYSTEM-ONE §5 requires. `[E: SCHEMA §2; E: SYSTEM-ONE §5]`

---

## 4. Architecture

### 4.1 The shape

```
                     ┌────────────────────────────────────────────┐
                     │              Owner console (F24)           │
                     │   review queue · questions · audit view    │
                     └───────────────▲────────────────────────────┘
                                     │ labels, decisions
┌────────────────────────────────────┴───────────────────────────────────────┐
│                          Control plane (offline/async)                     │
│  F16 owner model · F20 learning pipeline · F21 registry · F22 drift        │
│  F8 replay · F19 escalation router · evaluation harness                    │
└───────────────▲──────────────────────────────▲─────────────────────────────┘
                │ models, thresholds           │ labels, traces
┌───────────────┴──────────────┐   ┌───────────┴─────────────────────────────┐
│      Meso/macro serving       │   │        Decision-time harness (F2)       │
│  F9 text reader (GPU)         │   │  tool calls · memory reads/writes ·     │
│  F10–F12 thesis judge (CPU)   │   │  model calls · order intents · hashes   │
│  F13 trajectory · F14 swarm   │   └───────────┬─────────────────────────────┘
│  F15 book                     │               │ graph + justification
└───────────────▲───────────────┘               ▼
                │ signed verdicts      ┌─────────────────────────────────────┐
                └──────────────────────│      Micro order path (F1,F3–F6)    │
                                       │  Rust/Go · code only · fail closed  │
                                       │  verify token · bands · caps ·      │
                                       │  turnover · thesis status · allow   │
                                       └─────────────────────────────────────┘
```

### 4.2 Planes and clocks

**Micro plane (order path).** Rust or Go, stateless, no Python, no network call
to a model. Inputs: order intent, book snapshot, signed thesis verdict, policy
version. Outputs: allow or hold, with a reason code. This path does not carry the
thesis latency target: it is a cached verdict plus code, so it should be
microseconds to low milliseconds. Design budget: 1 ms parse and signature, 2 ms
cache lookup, 3 ms arithmetic and checks, leaving slack. The brief specifies a
laptop-class CPU for this path; the design fits because it performs no inference.
`[E: BRIEF; E: SYSTEM-ONE §5 on the cached verdict; R for the split]`

**Meso plane (thesis path).** Python or C++ service. On thesis open or change,
compile the Justification, call F9–F12, calibrate, and mint a signed verdict with
a risk budget and expiry. The brief's target is **p99 ≤50 ms on CPU for code
checks plus the structured scorer**. Text reading is a separate **≤300 ms GPU**
stage on document read; its scores are attached to the Justification before the
thesis judgement. If they are not ready, the thesis is held or scored
conservatively without them. `[E: BRIEF, latency; R for the split]`

**Macro plane (continuous).** Event-driven workers consume the graph stream and
update per-agent and per-swarm state. These never block an order; they can only
shorten leases, shrink budgets or raise an alert. `[R]`

**Control plane (offline).** Everything that learns, replays, evaluates,
registers, or asks a human. It consumes the same immutable event log, so training
and serving features cannot silently diverge. `[R]`

### 4.3 Why not a single online model server

A single model server would put the thesis judge, text reader and trajectory
model behind one queue and one failure domain. It would also tempt someone to
call it from the order path. The three-plane split makes the latency invariant
structural: the order path **cannot** import the model client package, and a
build check enforces that. `[R]`

### 4.4 Level mapping

| SYSTEM-ONE level | Components | Authority |
|---|---|---|
| 1 Signal | F2, F4, F9 | Mark node untrusted; propagate |
| 2 Thesis | F3, F4, F10–F12, F16, F18 | Withhold/shrink risk budget; hold thesis |
| 3 Action | F1, F3–F6 | Hold order |
| 4 Trajectory | F13, F22 | Shorten lease, shrink budget, re-inject purpose |
| 5 Swarm | F14 | Cap combined exposure to a shared root |
| 6 Book | F15, F16, F24 | Ask owner; propose de-risking for signature |

`[E: SYSTEM-ONE §5]` for the levels and their tightening powers; `[R]` for the
mapping to components.

### 4.5 Data stores

- **Event log:** append-only, hash-chained, the source of truth for replay.
- **Graph store:** materialised provenance graph per episode/agent, with
  point-in-time indexes; supports 2-hop neighbourhood queries in milliseconds.
- **Feature store:** offline/online parity, versioned feature definitions,
  point-in-time joins; the online side is a compact key-value snapshot for the
  order path.
- **Verdict store:** signed tokens with TTL, keyed by thesis and graph hash.
- **Label store:** owner decisions, audit labels, planted causes, counterfactual
  labels, teacher labels, with provenance and weight.
- **Model registry:** artefacts, signatures, metrics, approvals, rollback.

### 4.6 Deployment topology on two A6000s

- **GPU 0:** online text reader and any small graph/sequence inference, int8/fp16,
  batched, with a CPU fallback that only tightens.
- **GPU 1:** offline teacher, distillation data generation, retraining, replay.
- When training needs both cards, online serving degrades to the CPU text reader
  and a tighter threshold. That is an explicit, rehearsed mode, not an accident.
  `[E: BRIEF, compute; R]`
- Because the machine is shared, containerise serving, pin CUDA and driver
  versions, and assume a GPU can disappear mid-run; the CPU fallback is not
  optional. Assume other tenants: encrypt owner data at rest and keep no
  plaintext owner data in shared temporary directories. `[R]`

### 4.7 Security boundaries

- The harness signs events; agents cannot write trust, tier, signature or hash
  fields directly. `[E: SCHEMA §2; R]`
- Agent text enters only through quarantined fields with length limits, and is
  never inserted into a privileged prompt unescaped. `[E: SYSTEM-ONE §6]`
- The order path accepts only signed verdicts from the meso plane.
- Every component has a kill switch that resolves to hold.
- No secrets in features, logs or notebooks; keys live in a managed secret store.
  `[R]`

---

## 5. The models

### 5.1 The portfolio

| Model | Task | Architecture | Size | Runtime | Training |
|---|---|---|---|---|---|
| M1 text verifier | Q6 quote support, Q7 note intent | Pretrained encoder, last 2–3 layers tuned, 2-layer heads | 22–110M | GPU, ONNX/TensorRT | Distillation + supervised |
| M2 thesis judge | Q1 endorsement | GBDT on tabular + graph-relational features | 200–600 trees | CPU, Treelite | Supervised, calibrated |
| M3 cause head | Q2 causes | Multi-class GBDT plus an any-failure head | small | CPU | Supervised, class-balanced |
| M4 attribution head | Q3 node weights | GBDT or 2-layer MLP on node features, softmax with "unexplained" | small | CPU | Distilled from replay Shapley |
| M5 graph expert | Q1/Q3 structural patterns | 3-layer GraphSAGE/GAT, hidden 64–128 | 1–5M | CPU/GPU | Supervised, from scratch |
| M6 sequence expert | Q1/Q4 trajectory | 4-layer causal transformer or GRU over event tokens | 3–10M | CPU/GPU | Self-supervised + supervised |
| M7 owner model | Q1/Q4 owner residual | Hierarchical Bayesian logistic | 10–50 per owner | CPU | Laplace update, not SGD |
| M8 stacker | Q1/Q4/Q5 | Logistic regression with non-negative weights | tiny | CPU | Out-of-fold stacking |
| M9 calibration | thresholds | Isotonic/Platt + split conformal (Mondrian) | tiny | CPU | Post-hoc |
| M10 teacher | labels, rationales, adversarial data | DeepSeek API + hosted decision model + optional 7B LoRA | large | offline | Prompting + LoRA |

The default stack is **M2 + M1 + M7 + M8 + M9**. The minimum viable model set is
even smaller: **M2 + M9 plus exact checks**. Add M1 for semantic cases, M7 for
owner adaptation, M3/M4 for explanations, and M5/M6 only on held-out gains. M10
never runs online. `[R]`

### 5.2 Text: a verifier, not a judge

**Choice: a pretrained encoder, not a generative LLM.** The tasks are
classification and entailment over short, quarantined fields: does this quote
support this claim, is this number the same, does this note contain an
instruction that overrides the mandate, does this rationale follow from this
thesis. Encoders are cheaper, more stable, easier to calibrate, and less
injectable than decoders. `[R]`

**Concrete starting point.** A 6-layer, 384-hidden encoder in the MiniLM/BGE-small
family (22–33M parameters), or a 110M base encoder if accuracy demands it. Freeze
embeddings and the bottom three layers; fine-tune the top three plus a pooled
projection and two heads. On a 48 GB card this trains in hours on a few million
pairs. `[R; E: external, Wang et al. 2020 for MiniLM]`

**Inputs.** Never the raw episode. Only: the claim text, the quoted span, the
source document's relevant passage (retrieved by exact quote or BM25), the
document's typed facts, the note text with its provenance fields, and the
mandate's relevant clause. This is the quarantine boundary. `[E: SYSTEM-ONE §6]`

**Heads.**
- support: `{entailed, contradicted, insufficient}`;
- numeric match: exact / same-unit-different-value / unit-mismatch / absent
  (exact equality is code first; the head handles rounding, units and paraphrase);
- injection: probability that the note contains an override instruction;
- coherence: does the rationale's stated belief match the thesis's claim.

**Why not fine-tune a 7B.** A 7B forward pass on a thesis with several documents
and notes is unlikely to meet a 300 ms p99 on one A6000 at useful batch sizes; it
is also roughly 20–50× the serving cost of a small encoder. Large fine-tuned
models are often poorly calibrated, and instruction tuning can make this worse.
`[E: external, Guo et al. 2017 on neural calibration; R for the rest]` Use the 7B
as a teacher: it labels millions of pairs, the encoder distils them, and the
teacher is never on the critical path. `[R]`

**Which layers to adapt.** If the encoder is 6 layers: freeze embeddings and
layers 1–3, train layers 4–6. If it is 12 layers: freeze 8, train 4. Use LoRA
(rank 8–16) only when full fine-tuning of the top block overfits. The point is
to preserve general language representation and adapt the task-specific top.
`[R]`

**Distillation.** Teacher answers Q6/Q7 with rationales; student trains on hard
labels plus teacher logits (temperature 2–4) and a contrastive loss over
(claim, correct span) vs (claim, hard negative span). Hard negatives come from
the simulator: exact-but-wrong numbers, real spans with a changed unit, paraphrased
authority changes, and clean enthusiastic text. `[R]`

### 5.3 Tabular: the workhorse

**Choice: gradient-boosted trees, not a neural net.** The features are
heterogeneous, partly missing, low-cardinality, and the dataset is small and
shifting. GBDTs are strong there, train in minutes on CPU, infer in microseconds,
and support monotonic constraints. `[E: external, Ke et al. 2017 for LightGBM;
R]`

**Feature blocks.** Each is versioned and ablatable:

1. **Mandate block:** purpose one-hot, band distances (current weight minus min/max
   in basis points), cap utilisation, allowed-instrument flag, turnover today.
2. **Action block:** side, notional / portfolio, sector, instrument concentration,
   distance to band, marginal effect on sector and instrument, cash after.
3. **Thesis block:** age, status, number of evidence docs, min/max trust tier,
   freshness, invalidation trigger present/met, evidence overlap with action,
   opens-thesis flag.
4. **Claim block:** counts by verification status, numeric match, quote exactness,
   unsupported fraction, hype score, max/min trust of sources, source age.
5. **Note block:** counts by author, signature validity, injection score, age,
   share of the action's cited notes that are unsigned or external.
6. **Graph block:** depth, number of roots, root concentration (HHI), share of
   weight on unverified roots, cycles, shared-root exposure, path lengths,
   whether the action's roots all trace to one source.
7. **History block:** owner decisions on similar theses, prior holds, agent's
   recent failure rate, time since last review, drift/loop flags.
8. **Text block:** the small set of M1 scores, never raw embeddings.
9. **Interaction block:** a few explicit ratios (e.g., unverified-root share ×
   notional, band distance × side).

**Monotonic constraints.** Where domain knowledge is unambiguous, constrain the
model: a larger unverified-root share cannot decrease risk; an unsigned note
that asserts a permission change cannot decrease risk; a larger band excess on a
buy cannot decrease risk. Do not constrain trust tier itself: a high-trust filing
can carry bad news, so trust is not monotone in risk. This improves calibration
and makes the model harder to game. `[R]`

**Calibration.** Out-of-fold isotonic regression on a held-out calibration set,
then split conformal for the allow/hold threshold. Recalibrate by owner and by
purpose (Mondrian conformal) when enough labels exist. `[E: external, Vovk et al.
2005; Angelopoulos & Bates 2021; R]`

**Why not a tabular foundation model.** It adds a large dependency, opaque
features and a new failure mode for a task where the features are already
hand-designed and interpretable. Revisit only if GBDT plateaus well below the
label ceiling. `[R]`

### 5.4 Graph: relational features first, GNN second

**Choice: compute graph features in code; add a GNN only if it beats them.**
Provenance graphs here are small (tens to hundreds of nodes), typed, and
heterogeneous. Engineered features — root concentration, verified share, cycle
membership, shared-root overlap, min-cut to the intent — capture most of the
signal and are auditable. A GNN's advantage is learning multi-hop patterns at
scale; with scarce labels, it usually loses to feature engineering. `[R]`

**If adopted:** 2–3 GraphSAGE or GAT layers, hidden 64–128, mean or attention
aggregation, residual connections, edge features for trust, verification, recency
and read-before-write. Prune to the 2-hop neighbourhood and top-k roots; the
schema's graphs are shallow. Three layers are enough; deeper over-smooths and
memorises simulator artefacts. `[E: external, Hamilton et al. 2017; Velickovic
et al. 2018; R]`

**Training.** Supervised on endorsement and causes, with an auxiliary link-
prediction task (does this edge carry the true cause?) and a contrastive task
(real vs rewired graph). Rewiring is a cheap, strong hard negative: keep node
features, shuffle edges, and require the model to notice that the story no longer
holds. `[R]`

**Adoption gate:** the GNN must improve Brier score and attribution F1 on
held-out families by a pre-registered margin, at acceptable latency. Otherwise it
stays in the laboratory. `[R]`

### 5.5 Sequence: hazard before transformer

**Choice: a hazard model on windowed features first; a tiny transformer only if
it earns it.** Trajectory failures are rare events with strong tabular precursors
(CUSUM, loop windows, root-source counting). A survival/hazard model gives
calibrated time-to-failure and lead time directly, which is what the product
needs. `[R]`

**If adopted:** a 4-layer causal transformer, `d=128`, 4 heads, rotary
positional encoding, over event tokens:

```
[time_bucket, event_type, sector, trust, verified, thesis_id, size_bucket]
```

Trained with next-event prediction (self-supervised) plus supervised failure
labels. Parameter count 3–10M. Why so small: few trajectories, high noise, and a
need for sample efficiency. A GRU is a fair baseline and often wins on small
data. `[R]`

**Critical caution.** Self-supervised next-event prediction on simulator data
learns the generator's regularities, not necessarily real failure structure.
Every sequence model must be evaluated on held-out authors and shifted families,
and ablated against the hazard baseline. `[R]`

### 5.6 Attribution: distill counterfactuals, not attention

**Choice: a node-weight predictor trained on counterfactual Shapley values from
the simulator.** Attention weights are not reliable explanations by themselves.
`[E: external, Jain & Wallace 2019]` Post-hoc SHAP on the scorer is a reasonable
fallback, but it explains the scorer, not the cause. `[E: external, Lundberg &
Lee 2017]` The simulator can compute the real thing: replay with one root removed
or corrected, and measure the change in endorsement probability. `[E:
SYSTEM-ONE §7]`

**Target.** For each action, a distribution over its roots plus an explicit
"unexplained / prior knowledge" mass. The finance analogy in SYSTEM-ONE insists
on that bucket, and the schema supplies the node ids to fill the rest; forcing
every unit of weight onto a visible node would lie. `[E: SYSTEM-ONE §4]`

**Training.** Distil the replay Shapley targets into M4 with a softmax over
nodes, a KL loss and a calibration loss on the bucket. Use group Shapley over
node types (documents, notes, theses, prior actions) for stability. `[R]`

**Why not let the LLM explain.** The agent's explanation is unreliable; the
SYSTEM-ONE evidence records that the hint the model used was mentioned only 25% /
39% of the time. `[E: SYSTEM-ONE §1, §8]` Explanations must be generated from
the graph, not authored.

### 5.7 The owner model: a scorecard, not a fine-tune

**Choice: a hierarchical Bayesian logistic model.** One global prior over
features, plus a per-owner offset vector with shrinkage. It is a credit
scorecard for endorsement. `[R]`

- **Population term:** `w · φ(justification)`, trained on all owners.
- **Owner term:** `u_owner · ψ(justification)`, with a Gaussian prior centred at
  zero and variance learned from data.
- **Posterior:** Laplace approximation after each owner decision; no gradient
  descent, no catastrophic forgetting.
- **Output:** mean and variance, so the system knows when it is still guessing.
- **Stability:** freeze the stacker weights between retrains; only the owner
  residual moves online, and periodic recalibration catches the drift.

**Why this over fine-tuning per owner.** Owners are many, labels per owner are
few, and preferences change slowly. A hierarchical model pools correctly, gives
uncertainty, is interpretable, and updates in milliseconds. It also gives the
cold-start curve directly: how many decisions before an owner is well modelled.
`[R]`

**Cold start.** Use the population prior; label it as low-confidence; ask more
often. As the posterior tightens, the interruption rate should fall. That curve
is a product metric, not a research afterthought. My estimate: 20–50 decisions
give a coarse owner residual; 100–200 give a stable one. The population prior
carries the rest. `[R]`

### 5.8 What I rejected, and why

| Option | Why it is tempting | Why I reject it here |
|---|---|---|
| Fine-tuned 7B judge | Strong language understanding, single model | Latency, cost, calibration, injection surface; cannot be on the order path `[R]` |
| Decision transformer | Learns policies from traces | Target is a calibrated probability, not a return-conditioned policy; data-hungry, hard to calibrate `[E: external, Chen et al. 2021; R]` |
| From-scratch text model | Full control, no pretraining baggage | Needs orders of magnitude more text than we have; pretrained representations are the cheap win `[R]` |
| GNN only | Elegant, end-to-end | Small graphs, scarce labels; feature engineering plus GBDT wins first `[R]` |
| Pure rules/symbolic | Exact, auditable | Cannot handle paraphrase, implication or owner tolerance `[R]` |
| Deep RL for the scorer | Could optimise the decision | RL sharpens existing skills and damages calibration; use it only for the interruption policy, with OPE `[E: SYSTEM-ONE §7; R]` |
| One model for all six levels | Simpler ops | Different tempos, labels and failure modes; a monolith would be slow and uncalibratable `[R]` |

### 5.9 Post-training and customisation trade-off

| Method | Gain per unit cost | Ease of post-training | When to use |
|---|---|---|---|
| Frozen encoder + linear/GBDT head | High | Very easy, hours on CPU | Always, as baseline |
| Distil teacher into small encoder | Highest for text | Moderate, 1–2 GPU-days | Once teachers and pairs exist |
| GBDT on new features | High | Easy, minutes | Every feature iteration |
| LoRA on a 1–3B teacher | Medium | Moderate | Offline labelling, not serving |
| Full fine-tune 7B | Low for this task | Hard, unstable | Only if distillation fails |
| Train tiny sequence model from scratch | Medium, conditional | Moderate | After hazard baseline plateaus |
| RL / contextual bandit | Medium for policy, low for scorer | Hard, needs OPE | Interruption policy only, last |
| Train text model from scratch | Low | Very hard | No |

My answer to "minimum post-training for maximum gain": **a frozen pretrained
encoder plus calibrated heads, and a GBDT on engineered features, gives most of
the gain.** The highest-return gradient-based work is distilling a teacher into
the small text verifier. Everything beyond that is measured, not assumed. `[R]`

### 5.10 On custom-modified decision models

The founder asked whether the answer is LLMs, classical ML, or a custom-modified
decision model — stripping parts of an architecture, changing input and output,
adding, deleting or modifying layers. My view, item by item. `[R]`

- **Changing the input and output is the big lever, and we should take it.** The
  input is a typed Justification, not a prompt. The output is a calibrated
  probability, a cause vector and a node-weight distribution, not text. That
  redefinition is worth more than any layer surgery.
- **Stripping an LLM to a classifier head** (remove the generation head, pool the
  hidden state, add heads) works, but you still pay the full forward pass, inherit
  the calibration and injection surface, and need a large fine-tune. A
  22–110M encoder gives most of the language benefit at a fraction of the cost.
  Use the stripped LLM as an offline teacher, not as the scorer.
- **Adding or deleting layers** is a weak lever here. Depth changes capacity, not
  the task's structure. Freezing and LoRA on the top block are the useful
  customisation knobs; architecture surgery is not.
- **A "proper ML model" is exactly right**, provided "proper" means a calibrated
  model with a code contract, not a single neural network. The GBDT plus small
  encoder plus Bayesian owner model is a proper ML system.
- **Policy distillation is the highest-return post-training**, with one caveat:
  distil *verified labels*, not teacher behaviour. Behaviour cloning imitates
  teacher errors and injection susceptibility. Distil the teacher's answers after
  code checks; keep the student's calibration set separate. `[E: SYSTEM-ONE §7
  on teacher-student; R]`
- **Agent traces are useful for the trajectory model and for replay, not as a
  direct supervision signal for endorsement.** A trace shows what happened, not
  whether the owner would sign it. `[E: SYSTEM-ONE §1, §8; R]`

### 5.11 Paradigms, and how easy each is to post-train

| Paradigm | Role here | Post-train / customise ease | Verdict |
|---|---|---|---|
| Supervised discriminative | Endorsement, causes, claim support | Easy, stable | Primary |
| Distillation | Teacher to small text verifier | Moderate, highest text ROI | Primary |
| Contrastive | Claim/span and graph rewiring | Moderate, needs hard negatives | Support |
| Self-supervised | Sequence and graph pretraining | Moderate, risk of generator artefacts | Auxiliary |
| Bayesian / hierarchical | Owner residual and uncertainty | Easy, closed-form updates | Primary for owners |
| Conformal / distribution-free | Thresholds and error control | Easy, post-hoc | Primary for safety |
| Causal / counterfactual | Attribution and label generation | Hard, needs replay | Primary for labels |
| Contextual bandit / offline RL | Interruption policy | Hard, needs propensities and OPE | Last, policy only |
| Generative LLM | Teachers, data, escalation | Easy to prompt, hard to calibrate | Offline only |

`[R]` The ordering is deliberate: the paradigms at the top are cheap to
post-train and easy to audit; the ones at the bottom are expensive and hard to
trust with authority.

### 5.12 The architecture trade-off in one table

| Architecture | Strength here | Weakness here | Post-train ease | Verdict |
|---|---|---|---|---|
| GBDT on engineered features | Strong on heterogeneous tabular data; interpretable; microseconds on CPU | Needs feature engineering; cannot read text | Very easy | Runtime workhorse |
| Frozen small encoder + heads | Semantic verification; cheap; calibratable | Needs labelled pairs; limited reasoning depth | Easy | Text workhorse |
| Fine-tuned 7B decoder | Broad language skill; one model | Latency, cost, calibration, injection; hard to serve | Hard | Offline teacher only |
| GNN (GraphSAGE/GAT) | Learns multi-hop provenance structure | Small graphs, scarce labels; over-smooths | Moderate | Conditional |
| Tiny sequence transformer | Temporal patterns across events | Data-hungry; learns generator artefacts | Moderate | Conditional |
| Hierarchical Bayesian scorecard | Few-shot owner adaptation; uncertainty | Linear-ish; needs feature design | Easy | Owner layer |
| The hybrid stack above | Best accuracy and calibration per unit cost | More moving parts | Moderate | Chosen |

`[R]` The table is the answer to "which model should we build": none of them
alone. The hybrid is chosen because each part is cheap, auditable and replaceable.

### 5.13 Which causes are code, and which need a model

| Cause | Decidable in code | What still needs a model |
|---|---|---|
| drift | Sector/instrument arithmetic and bands | Nothing; it is arithmetic |
| unsupported_claim | Source presence and typed fact matching | Semantic absence and paraphrase |
| misquote | Quoted span existence and numeric mismatch | Rounding, units and implied numbers |
| vague_hype | No value or unit in the claim | Implied hype and unstated figures |
| poisoned_note | Provenance and whether the action follows the note | Instruction intent |
| authority_spoof | Signature validity and permission fields | Semantic assertion of a change |
| stale_thesis | Trigger evaluation and thesis status | Semantic staleness and relevance |
| clean hard negatives | Bands, quotes and arithmetic | Intent, coherence and owner tolerance |

`[R]` This table is why the text model is small and late in the build: for most
causes, code already decides the case. The model earns its place on the semantic
residue, not on the whole problem.

---

## 6. Learning

### 6.1 Five principles

1. **Data beats architecture; labels beat data volume; calibration beats
   accuracy.** The failure mode of this project is a well-ranking, badly
   calibrated model that cannot be trusted with a threshold. `[R]`
2. **Learn the residue, not the rules.** Exact checks stay code. Models only see
   what cannot be decided exactly. `[R]`
3. **Every learned output has a code fallback.** If a model is missing or
   disagreeing with an exact check, the exact check wins. `[R]`
4. **Features come from `model_view` only.** `meta` and labels are stripped from
   every input; labels are training targets, never features. Leakage tests are
   part of CI. `[E: SCHEMA §5]`
5. **No self-grading.** The model never generates its own training labels from
   its own explanations. `[E: SYSTEM-ONE §7]`

### 6.2 Label sources

| Source | What it gives | Volume target (v1) | Bias and caveat |
|---|---|---|---|
| L1 planted causes | Exact `y`, cause, `cause_refs` | 20k–50k episodes, 200k–500k actions | Simulator artefacts; may be too easy `[R]` |
| L2 counterfactual replay | Causal necessity/sufficiency, Shapley targets | 5–10 per labelled action | Replay is only as good as the world model `[R]` |
| L3 owner review queue | Real endorsement labels | 10k–50k decisions | Selection bias: only held orders `[E: SYSTEM-ONE §2]` |
| L4 random audit slice | Unbiased labels on allowed orders | 1–5% of allowed orders | Expensive owner time; needed for OPE `[E: SYSTEM-ONE §2]` |
| L5 teacher labels | Weak labels for distillation and coverage | 1–5M claim pairs | Teacher bias, prompt sensitivity `[R]` |
| L6 constitution/adversarial | Red-team and adversarial training | 50k–200k generated cases | Must be labelled by code or humans, not the generator `[E: SYSTEM-ONE §7]` |
| L7 self-supervised | Next-event and link prediction | all event streams | Learns generator regularities; use with caution `[R]` |

These are estimates from the scale of the schema and the compute budget; they
are not given in the brief. `[R]`

### 6.3 Training recipes

**M1 text verifier.** Two stages.
- Stage A: supervised on synthetic pairs with exact labels: exact quote, changed
  number, changed unit, unsupported claim, poisoned note, clean enthusiastic
  text. Balanced by family, with hard negatives mined from student errors.
- Stage B: distill teacher answers and logits on a broader, unlabelled corpus;
  keep only items where the teacher agrees with exact code checks or with a
  second teacher, and down-weight the rest.

Loss: cross-entropy on labels + KL to teacher logits (temperature 2–4) +
contrastive loss over (claim, supporting span) vs (claim, hard-negative span).
Optimiser AdamW, lr 2e-5 for pretrained layers and 1e-4 for heads, 3–5 epochs,
early stopping on a held-out author split. Freeze embeddings and bottom half.
`[R]`

**M2 thesis judge.** LightGBM binary log-loss with class weights, monotonic
constraints on the domain-signed features, 200–600 trees, depth 4–6, early
stopping on grouped folds by episode and family. Then isotonic calibration on a
separate calibration split, then split conformal. Report Brier and ECE before and
after calibration. `[E: external, Ke et al. 2017; R]`

**M3 cause head.** A multi-class classifier over the schema's causes plus a binary
any-failure head, grouped by a hierarchy: exactness causes (misquote, unsupported
claim), authority causes (poisoned note, spoof), lifecycle causes (stale thesis,
drift), style causes (vague hype), and novel families. If the simulator records
secondary causes internally, add a multi-label auxiliary head; the validator's
label stays single-cause. Use class-balanced or focal loss; report per-cause
AUPRC, not just micro-F1. `[R]`

**M4 attribution head.** Distil group Shapley values from replay into a softmax
over roots plus an "unexplained" logit. Loss: KL to the Shapley distribution plus
an MSE on the bucket. Train on counterfactual pairs so the model learns necessity,
not correlation. `[R]`

**M5 graph expert.** Supervised on endorsement and causes, plus link prediction
(does this edge carry the true cause?) and a rewiring contrastive task. Use
2–3 layers, hidden 64–128, residual, edge features. Early stop on family holdout.
`[R]`

**M6 sequence expert.** Two objectives: next-event prediction (self-supervised)
and failure-within-window (supervised). Compare against a hazard model on
windowed features. Adopt only if it beats the hazard model on lead time at the
same false-hold rate. `[R]`

**M7 owner model.** Fit the population term by penalised logistic regression;
fit each owner's residual by Laplace approximation with a Gaussian prior. Update
after every decision. Report posterior variance and the cold-start curve. No SGD,
no per-owner fine-tune. `[R]`

**M8/M9 stacking and calibration.** Out-of-fold predictions from M2, M5, M6, M7
and the M1 scores feed a logistic stacker with non-negative weights. Calibrate
the stacker with isotonic regression; set the allow threshold by split conformal
risk control, stratified by purpose and family where labels allow. `[E: external,
Vovk et al. 2005; Angelopoulos & Bates 2021; R]`

I would **not** start with a five-model ensemble. Start with one calibrated model;
add ensemble members only when they improve held-out calibration enough to pay
for the extra serving and failure surface. An ensemble is a calibration tool, not
a default. `[R]`

### 6.4 Distillation, in detail

The teacher is not one model. It is a panel: DeepSeek, the external hosted
decision model, a 7B LoRA reviewer, and the simulator's ground truth. The panel
is used in three ways.

1. **Coverage.** The teacher labels cases the simulator does not generate, so the
   student sees paraphrase, implication and novel phrasing. `[R]`
2. **Rationales as auxiliary supervision.** Teacher explanations are never copied
   as text. They are parsed into structured fields (which document, which quote,
   which cause) and checked by code; only checked fields become labels. `[R]`
3. **Disagreement mining.** Cases where teachers disagree, or where the teacher
   disagrees with the exact checks, are the most valuable: they are either
   genuine ambiguity (send to owner) or teacher error (do not train). `[R]`

Filtering rule: a teacher label is accepted only if (a) it agrees with exact
checks where those apply, or (b) two independent teachers agree and the case is
not numerically checkable. This prevents the student from learning a teacher's
injection susceptibility. `[R]`

### 6.5 Reinforcement learning: only where it belongs

I would **not** use RL to train the endorsement scorer in v1. The SYSTEM-ONE
evidence is that supervised fine-tuning holds calibration better under shift, and
that RL mostly sharpens skills the base model already has. `[E: SYSTEM-ONE §7]`
A proper scoring rule can be optimised supervised; RL adds variance and a reward
hacking surface. `[R]`

RL or a contextual bandit belongs in the **interruption policy**, where the
objective is a cost trade-off, not a probability:

- actions: `pass`, `ask`, `hold`, `shrink`, `block`;
- reward: `−c_allow · 1[owner rejects] − c_hold · 1[action was good] −
  c_ask · 1[asked]`;
- constraints: never allow more than the conservative policy; conformal bound on
  false-allow;
- learning: offline contextual bandit with logged propensities and doubly robust
  off-policy evaluation; exploration only in shadow mode, never with authority.
  `[R]`

The output is a policy with a measured cost curve, not a model that "decides".
`[E: SYSTEM-ONE §2 on Capponi et al.; R]`

### 6.6 Training from scratch: only the tiny models

- **Text:** never. Pretrained language representation is the cheapest, highest-
  quality prior available; from-scratch would need far more data than the
  project can generate. `[R]`
- **Graph and sequence:** yes, from scratch, because the vocabulary is events and
  graph structure, not natural language, and the models are 1–10M parameters.
  Even there, start with engineered features and a hazard model. `[R]`
- **Owner model:** from scratch by design; it is a Bayesian scorecard, not a
  neural network. `[R]`

### 6.7 Curriculum and active learning

**Curriculum:** clean single-cause episodes → clean hard negatives → multi-cause
episodes → shifted families → adversarial/injection episodes. This order matters:
a model trained on adversarial data first learns to detect the generator, not the
cause. `[R]`

**Active learning, in priority order:**
1. owner disagreements with the model (highest information);
2. high ensemble variance;
3. near the conformal threshold;
4. novel graph shapes or new publishers;
5. random audit slice, always, to keep an unbiased estimate.

Every batch is capped by owner time, which is the real budget. `[R]`

**Hard-negative mining:** exact quotes, legitimate adaptation on fresh filings,
correct sells that repair a band breach, enthusiastic but factual language,
near-miss band breaches that stay inside, and a poisoned note that the agent
correctly refuses. These are the cases that separate a real judge from a keyword
detector. `[E: SCHEMA §4]`

### 6.8 Label noise and causal discipline

- **Owner labels are noisy and non-stationary.** Elicit a subset twice, estimate
  the disagreement rate, and report the ceiling it implies. If owners disagree
  with themselves more than the model does, the target needs redefinition, not a
  better model. `[R]`
- **Planted labels are exact but simulator-specific.** Test for leakage: can a
  model predict the cause from metadata-like artefacts (document length, id
  patterns, ordering)? If yes, fix the generator before training. `[R]`
- **Selection bias.** Only held orders get labels. Use the audit slice with
  importance weighting and doubly robust estimation; never report review-queue
  accuracy as if it were population accuracy. `[E: SYSTEM-ONE §2; R]`
- **Causal labels.** Counterfactual replay gives necessity and sufficiency, not
  just correlation. Use it to train attribution and to evaluate explanations.
  `[E: SYSTEM-ONE §7]`

### 6.9 Compute plan on two A6000s

| Work | Resource | Estimate |
|---|---|---|
| M1 distillation, 1–2M pairs | 1 GPU, mixed precision | 1–2 GPU-days `[R]` |
| M1 supervised stage | 1 GPU | 4–8 GPU-hours `[R]` |
| M2/M3/M4 GBDTs | CPU | minutes per fit `[R]` |
| M5 GNN | 1 GPU | 4–12 GPU-hours `[R]` |
| M6 sequence | 1 GPU | 1–3 GPU-days `[R]` |
| Replay/label generation | CPU workers | dominant cost `[E: SYSTEM-ONE §12]` |
| Full retrain | both GPUs | weekly `[R]` |

The binding constraint is data generation and owner time, not GPU hours. That is
why the build order starts with the harness and simulator, not with a model.
`[R]`

---

## 7. Data and labels

### 7.1 The dataset is the product

The schema defines the world. My data strategy is to make the simulator produce
four things at once: **realistic episodes, exact causes, hard negatives, and
shifted variants**. Most teams generate only the first and then wonder why the
model learns the generator. `[R]`

An episode is one delegation: owner, documents, notes, theses, book, steps. The
label is per action. `[E: SCHEMA §1, §2]` The generator must satisfy every
validator rule, including book replay, availability, and cause/`y` consistency.
`[E: SCHEMA §6]` The initial book must already satisfy the mandate; a breach has
to be earned by actions, not assumed at the start. `[E: SCHEMA §2]`

### 7.2 What the generator must vary

| Axis | Values | Why |
|---|---|---|
| Purpose | income, balanced, growth, capital preservation | Different tolerances and band shapes `[E: SCHEMA §2]` |
| Mandate bands | tight, wide, asymmetric, one sector excluded | Near-miss hard negatives `[R]` |
| Failure family | drift, unsupported claim, misquote, hype, poisoned note, spoof, stale thesis, clean | Balanced and multi-cause `[E: SCHEMA §3]` |
| Evidence quality | tiers 0–3, verified/unverified, fresh/stale, conflicting | Provenance sensitivity `[E: SCHEMA §2]` |
| Adversarial shape | injection, paraphrase, authority claim, number swap, unit swap | Robustness `[R]` |
| Book state | inside band, at boundary, already breached | Onset vs continuation `[E: SCHEMA §3, drift]` |
| Agent behaviour | patient, overtrading, looping, herding, adapting | Trajectory and swarm `[E: SYSTEM-ONE §3]` |
| Shift | new publisher, new family, new phrasing, new sector mix | Held-out evaluation `[E: SCHEMA §2, meta]` |

### 7.3 Clean data and hard negatives

A clean episode is not an easy episode. It must contain the four hard-negative
classes the schema names:

- **legitimate adaptation:** a new thesis on a fresh, high-trust filing, inside
  the mandate;
- **correct sells:** trims and rebalances, including repairing a band breach;
- **exact quotes:** claims that reproduce the source number precisely;
- **enthusiastic but factual language:** positive wording backed by numbers.
  `[E: SCHEMA §4]`

I would add three more that I have seen fool simple detectors `[R]`:

- **near-miss bands:** a buy that takes a sector to 49.9% against a 50% cap;
- **stale-looking but valid thesis:** old evidence that has just been reconfirmed
  by a new filing;
- **poisoned note correctly refused:** the note is present and cited as context,
  but the action does not follow it.

Every hard negative is labelled `y=0`. A model that cannot separate these from
failures is not usable, whatever its AUROC on the easy set. `[R]`

### 7.4 How to generate text that does not leak

- **Facts first, text second.** Sample `facts` (name, value, unit), then render
  text deterministically from templates and a paraphrase model. The `facts` list
  is the machine-readable truth; the text must contain the same numbers.
  `[E: SCHEMA §2]`
- **Hash after rendering.** Compute SHA-256 of the final text, never of a
  template. `[E: SCHEMA §6]`
- **Vary surface, hold facts.** The same fact should appear in many phrasings,
  lengths and publishers, so the model cannot key on style. `[R]`
- **Adversarial paraphrase with a teacher.** Use DeepSeek to paraphrase and to
  write adversarial notes, but verify every number with code before accepting.
  `[R]`
- **Leakage audit.** Offline only, train a small diagnostic model to predict
  `meta.family` or `label.cause` from surface-only features (length, publisher,
  ordering, id pattern). If it succeeds, the generator leaks; fix it. This
  diagnostic is never a production feature. `[R]`

### 7.5 Planted causes: exact labels

The simulator knows the true cause of every order because it planted it. `[E:
SYSTEM-ONE §7]` The mapping must be exact and consistent with the schema:

- **drift:** only buys that leave a sector above its max; the first crossing is
  onset and is labelled; sells that repair are clean. `[E: SCHEMA §3]`
- **unsupported_claim:** claim has no source, or the source lacks the fact.
- **misquote:** real source and real span, wrong number.
- **vague_hype:** no concrete figure in the claim.
- **poisoned_note:** the action follows an injected instruction in a note.
- **authority_spoof:** the action relies on an unsigned permission change.
- **stale_thesis:** invalidation met or evidence stale, and the action adds
  exposure; a reducing sell is clean. `[E: SCHEMA §3]`

`cause_refs` must point only to documents or notes, never claims, and must be
available at the action's time. `[E: SCHEMA §2, §6]` The schema has one `cause`
per action, so multi-cause episodes label the dominant cause; generate
single-cause variants for the supervised cause head and use replay for
attribution. `[R]`

### 7.6 Counterfactual replay

For every labelled action, generate counterfactuals by:

1. removing one root document or note;
2. correcting a misquote or a wrong unit;
3. replacing a poisoned note with a clean note;
4. adding the missing signature to an authority claim;
5. updating the thesis status to invalidated;
6. changing the action's side or size while holding the story fixed.

Replay the episode and record whether the action survives and whether the
endorsement label flips. These pairs give:

- **necessity labels:** the cause is necessary if removing it removes the failure;
- **sufficiency labels:** the cause is sufficient if adding it to a clean episode
  creates the failure;
- **Shapley targets:** group Shapley over roots, with an "unexplained" bucket.
  `[E: SYSTEM-ONE §4, §7]`

For Shapley, use the simulated owner's endorsement probability or utility, not
the binary label, as the value function; a binary value makes the attribution
degenerate. `[R]`

Replay is only credible if the simulator is deterministic and the book replay is
exact; the validator's book replay is the foundation. `[E: SCHEMA, Book replay]`

### 7.7 Owners: simulated, then real

**Simulated owners.** Give each a latent vector: risk tolerance, sector bias,
evidence threshold, novelty preference, interruption cost, consistency. Let the
latent vector drift slowly and occasionally jump at a regime change. Generate
endorsements from a noisy threshold on the latent utility. This gives:

- a known ground truth for calibration;
- a cold-start curve per owner;
- controlled non-stationarity;
- a way to test whether the owner model tracks change or lags it. `[R]`

**Real owners.** The review queue is the first real dataset. It is biased because
only held orders are labelled. Add a random audit slice of allowed orders and use
importance weighting. `[E: SYSTEM-ONE §2; R]` Ask each owner a small, fixed set of
calibration questions at onboarding to seed the prior. `[R]`

**Endogeneity.** If owners see System One's verdict before deciding, their labels
are contaminated by it. Keep a blind review stream, or randomise whether the
verdict is shown, and train the owner model only on uncontaminated or randomised
decisions. Otherwise the flywheel learns to agree with itself. `[R]`

**Label quality.** Repeat a random 5–10% of reviews after a delay to estimate
intra-owner agreement. If agreement is below about 80%, the target is noisy;
either simplify the question or model the noise explicitly. The 80% is my
working threshold, not a published number. `[R]`

### 7.8 Teacher-generated data

DeepSeek and the external hosted decision model are used to:

- paraphrase documents and claims without changing facts;
- write poisoned notes and authority-spoofing rationales for red-team data;
- answer Q1/Q6/Q7 on a broad corpus for distillation;
- act as a second reviewer on escalated cases.

They are **not** used to label numeric checks, to set thresholds, or to generate
the ground truth for a cause. Every teacher output is filtered by code or by
agreement with planted truth. `[R]`

The hosted model costs about a second per call, so use it for hard, ambiguous and
escalated cases and for calibration, not for bulk paraphrase. DeepSeek is the
bulk generator; the hosted model is the specialist second opinion. `[E: BRIEF,
model access; R]`

### 7.9 Splits, leakage and governance

- **Group splits:** by episode, not by action; by author; by family; by seed; by
  time period. A random action split leaks thesis and document identity. `[R]`
- **Held-out families:** at least two failure families, and the test shift family
  of `shifted` episodes, are never seen in training. `[E: SCHEMA §3; SYSTEM-ONE
  §11]`
- **Held-out authors:** the generator's author string is a proxy for style;
  hold out at least one author entirely. `[E: SCHEMA §2, meta]`
- **Dedupe:** content hash for documents, normalised text for notes, and
  near-duplicate detection for episodes. `[R]`
- **Contamination checks:** search training data for evaluation canaries and
  exact quotes from held-out documents. `[R]`
- **Privacy:** owner decisions are personal data; store pseudonymised, restrict
  access, and never put them in prompts to external APIs without consent. `[R]`
- **Retention:** raw text and labels retained per policy; features and model
  artefacts reproducible from the event log.

### 7.10 Dataset mixture for v1

| Slice | Share | Purpose |
|---|---|---|
| Clean single-cause | 30% | Core signal |
| Clean hard negatives | 20% | Specificity |
| Multi-cause | 15% | Attribution and interaction |
| Adversarial/injection | 15% | Robustness |
| Shifted style | 10% | Generalisation (train on one shift style, test on a disjoint one) |
| Real/owner or teacher | 10% | Calibration to reality |

`[R]` These shares are a starting point; the evaluation harness should tune them
against held-out family performance, not against the overall average.

---

## 8. Evaluation

### 8.1 The causal ladder

I evaluate System One at four rungs. Most teams stop at the first.

1. **Prediction:** does it rank and calibrate endorsement?
2. **Intervention:** does removing the claimed cause change the score, and does
   adding it create the failure?
3. **Counterfactual:** would the owner have endorsed the action under the fix?
4. **Deployment:** does the policy reduce bad orders without over-holding, in
   shadow and then in production? `[R]`

Each rung needs its own metric; a model can pass rung 1 and fail rungs 2–4.

### 8.2 Endorsement metrics

| Metric | Why | Gate |
|---|---|---|
| Brier score | Proper, rewards calibration and sharpness | Report on every split `[E: SYSTEM-ONE §11]` |
| ECE (15 bins), MCE | Calibration | ≤0.05 in distribution after recalibration `[E: SYSTEM-ONE §11]` |
| Reliability slope | Over/under-confidence | 0.9–1.1 on held-out `[R]` |
| NLL | Tail behaviour | Report, not a gate `[R]` |
| AUROC/AUPRC | Ranking, secondary | Report per family; never the primary gate `[R]` |
| Risk–coverage | False-hold at fixed coverage | Primary product curve `[R]` |
| Conformal coverage | Guarantee validity | Empirical coverage within 2% of nominal `[R]` |

AUROC is seductive and misleading here: a model can rank well and still put the
threshold in the wrong place. The product decision is a threshold, so calibration
is the gate. `[R]`

All metrics are on `p(endorse)`. The gate thresholds a one-sided lower confidence
bound, not the point estimate, so a miscalibrated model errs toward holding
rather than allowing. `[R]`

### 8.3 Decision metrics

- **False-hold rate at fixed coverage:** of the orders the owner would endorse,
  what fraction does System One hold? This is the cost the owner feels. `[R]`
- **Lead time at fixed false-hold:** how early does it flag a bad trajectory
  before the existing detector, at the same false-hold rate? This is the
  SYSTEM-ONE kill criterion. `[E: SYSTEM-ONE §11]`
- **Interruption rate:** questions per owner per week; the price of asking.
- **Value of information:** the reduction in false-allow per interruption. `[R]`
- **Overtrading and fee drag:** turnover, cancel ratio, fees as a fraction of
  capital, per thesis. `[E: SYSTEM-ONE §5]`
- **Combined exposure to a shared root:** swarm-level metric, not per agent. `[E:
  SYSTEM-ONE §5]`

### 8.4 Attribution metrics

- **Cause top-1 accuracy** against planted causes, per family.
- **`cause_refs` precision, recall and F1**, with a strict match on node ids.
- **Attribution fidelity:** KL or total variation between predicted node weights
  and replay Shapley on held-out episodes.
- **Necessity/sufficiency accuracy:** does the model correctly predict whether
  removing or adding a cause flips the label?
- **Explanation faithfulness:** if the explanation says 62% of the weight is on
  headline H, does removing H reduce the score by roughly that amount? Test by
  occlusion. `[E: SYSTEM-ONE §3]`
- **Calibration of the "unexplained" bucket:** it should predict residual weight,
  not absorb errors. `[E: SYSTEM-ONE §4]`

### 8.5 Robustness and shift

Every model is evaluated on:

- **held-out failure families** (at least two never seen);
- **held-out authors and seeds**;
- **shifted episodes** (`meta.shifted`) from a held-out shift family;
- **time splits** for owner drift;
- **adversarial paraphrase and injection suites**;
- **option-order and negation consistency:** Q1 should not change if the
  question is rephrased, the options reordered or the mandate stated negatively;
- **numeric perturbation:** a 1% change in a fact should not flip a decision
  unless the fact is near a threshold;
- **graph rewiring:** preserve node features, shuffle edges; the model should
  notice. `[R]`

Report the **worst family**, not only the mean. A model that is excellent on
drift and useless on poisoned notes is not shippable. `[R]`

### 8.6 Operational metrics

- p50, p95, p99, p999 latency for the order path and the thesis path; separate
  text-reader latency.
- throughput per GPU and per CPU core; batch efficiency.
- memory footprint; cold-start time; model load time.
- availability and error rate of each service.
- **fail-closed rate:** how often a timeout or missing feature caused a hold.
  This is a product cost and must be monitored.
- **determinism:** same inputs, same verdict; replay hash equality.
- **cache hit rate** and **stale verdict rate**.

`[E: BRIEF, latency; R]`

### 8.7 Statistical discipline

- Pre-register primary metrics and gates before looking at held-out results.
- Use at least 3 seeds for learned models; report mean and 95% bootstrap CI.
- Correct for multiple comparisons when scanning families and thresholds.
- Never tune on the test family; use a validation family and a final blind test.
- Report per-family sample sizes and confidence intervals; small families produce
  unstable estimates. `[R]`

### 8.8 Human evaluation

- **Shadow mode:** run System One on real traffic with no authority; compare its
  endorsement prediction with the owner's actual decision.
- Measure reviewer agreement, time to decision, and the rate at which reviewers
  rubber-stamp. Automation bias is a real risk: if the console shows the model's
  answer first, reviewers may anchor. Show the evidence before the prediction.
  `[R]`
- A/B the interruption policy with owner time as the cost.
- Interview owners about surprising holds and surprising allows; these are the
  best error analyses. `[R]`

### 8.9 Tests that are not optional

- **Only-tighten property test:** fuzz the decision layer with arbitrary model
  outputs; assert the allowed set after System One is a subset of the allowed set
  before, and that lowering the score never increases exposure.
- **Leakage test:** train a surface-only classifier to predict `meta.family` or
  `label.cause`; if it beats chance, the generator leaks.
- **Schema conformance:** every generated episode passes `validate.py`; every
  feature extractor consumes `model_view`, never the full episode. `[E: SCHEMA
  §5, §6]`
- **Replay equality:** replayed book and decisions match the original exactly.
- **Injection suite:** known poisoned notes, spoofed authority, nested
  instructions, unicode tricks; the text reader must not follow instructions.
- **Canary episodes:** unique strings in held-out data; if they appear in
  training, the pipeline leaked.
- **Rollback drill:** deploy a bad model, verify the kill switch and rollback.

### 8.10 Go/no-go gates

I would use the SYSTEM-ONE kill criteria as the outer gates and add three:

1. **Graph value gate:** at the same false-hold rate, graph features must improve
   lead time over the deterministic monitor on held-out families, or the reframe
   is not paying for itself. `[E: SYSTEM-ONE §11]`
2. **Reader value gate:** the distilled text reader must improve attribution F1
   and endorsement Brier on semantic families by a pre-registered margin, or the
   system ships without it. `[R]`
3. **Complexity gate:** every additional model must justify itself with a
   held-out gain that survives a seed and family sweep; otherwise remove it. `[R]`

If the graph adds nothing, the correct response is to ship the deterministic
monitor plus the review queue and stop. That is a successful experiment, not a
failure. `[R]`

---

## 9. Runtime and serving at scale

### 9.1 Service level objectives

| Path | SLO | Enforcement |
|---|---|---|
| Thesis code checks plus structured scorer | p99 ≤50 ms, CPU | Hard timeout at 40 ms; fail closed `[E: BRIEF]` |
| Text reading | p99 ≤300 ms, GPU | Timeout at 250 ms; mark untrusted `[E: BRIEF]` |
| Order path (cached verdict plus code) | microseconds to low ms | Timeout; hold `[E: SYSTEM-ONE §5; R]` |
| Thesis end to end, with text | p99 ≤400 ms | Timeout; hold thesis `[R]` |
| Owner question generation | seconds | Asynchronous `[R]` |
| Verdict minting | p99 ≤50 ms | Asynchronous relative to order `[R]` |

The 50 ms thesis and 300 ms text targets are from the brief; the order-path and
end-to-end targets, and all internal budgets and timeouts, are my design. `[R]`

### 9.2 Capacity model

Let `N` be the number of active agents, `T` theses per agent per day, `O` orders
per agent per day, and `P` the peak-to-average ratio. The order path is
stateless and shards linearly:

- **Order QPS:** `N · O · P / 86400`. At `N=10k`, `O=100`, `P=10`, that is about
  116 QPS. The CPU path handles thousands per core per second, so this is easy.
  `[R]`
- **Thesis QPS:** `N · T · P / 86400`. At `T=5`, about 6 QPS. A single GPU text
  reader with batching handles this comfortably; the GBDT is microseconds.
  `[R]`
- **Text calls per thesis:** bounded by the number of claims and notes, say 5–20.
  Batch them per thesis; do not call the reader once per sentence. `[R]`

The design is not throughput-bound at first; it is latency- and correctness-
bound. Shard by owner when it is. `[R]`

### 9.3 The order path in detail

1. Receive an order intent over gRPC with a request id and a monotonic time.
2. Fetch the book snapshot and the signed thesis verdict from a local
   key-value cache; if absent, hold.
3. Verify the verdict signature, policy version, graph hash, expiry and thesis
   id. If any mismatch, hold.
4. Recompute sector and instrument weights; apply the action hypothetically.
5. Check: instrument allowed, side allowed, sector within band, position within
   cap, daily turnover, thesis status active, evidence hash unchanged, quote
   hashes unchanged, cached `g` applied to the risk budget.
6. Emit a pass-through attestation — the action is already inside the signed
   mandate and the tightened budget — or hold with a reason code. The attestation
   is not a new approval.
7. Write an audit event asynchronously; the audit write must never block the
   decision.

The code path is Rust or Go, with no dynamic allocation on the hot path, no
network calls to models, and no logging of personal data. `[R]`

### 9.4 The thesis path in detail

1. On thesis open or change, compile the Justification.
2. Run exact verifiers; short-circuit to hold if a hard rule fails.
3. Fetch M1 text scores for quarantined fields, batched. This is the separate
   ≤300 ms GPU stage; steps 1–2 and 4–6 are the ≤50 ms CPU path.
4. Compute graph features; fetch M2/M3/M4 scores; apply M7 owner residual.
5. Stack, calibrate, and choose the intervention via the policy.
6. Mint a signed verdict with: `g`, max notional, allowed instruments, expiry,
   graph hash, evidence hashes, model versions, reason codes.
7. Publish to the verdict store and the audit log.

The verdict is the contract between the meso and micro planes. It contains no
free text. `[R]`

The contract with risk is one line: `budget_thesis = ES_budget_thesis × g`, with
`g ∈ [0,1]`, so judgement can only shrink the budget. If `g` is a probability,
use a conservative lower bound, not the point estimate. `[E: SYSTEM-ONE §9; R]`

If the text scores are late, the thesis is not silently scored as if they were
clean: it is held, or scored with a conservative prior and flagged. That is the
fail-closed rule applied to latency. `[R]`

### 9.5 Model serving

- **M1:** ONNX Runtime or TensorRT, fp16 or int8, batch 8–32, dynamic batching
  with a 20 ms window. Keep the model under ~500 MB so it fits comfortably beside
  the rest.
- **M2/M3/M4:** Treelite or ONNX, one model per level and purpose, loaded in
  memory; inference is microseconds.
- **M5/M6:** only if adopted; ONNX or TorchScript; CPU fallback.
- **No vLLM or large-model server on the critical path.** The teacher runs
  offline in batch.
- **Version pinning:** each verdict records model and feature versions; rollback
  is a registry pointer change. `[R]`

### 9.6 Caching and invalidation

- **Verdict cache key:** `(thesis_id, graph_hash, evidence_hashes, policy_version,
  owner_model_version)`.
- **TTL:** short for active theses (minutes) and longer for stable theses; any new
  document, note write or thesis status change invalidates.
- **Order path:** never computes model features; it only verifies that the cached
  verdict still matches the hashes.
- **Negative cache:** do not cache holds longer than the evidence; a corrected
  document should be able to release a hold. `[R]`

The hash check is what makes caching safe: if the graph changed, the verdict is
stale, and stale means hold. `[R]`

### 9.7 Scaling and multi-tenancy

- **Stateless services** behind a load balancer; state in the graph/verdict
  stores.
- **Shard by owner** for the owner model and verdict cache; owners are independent.
- **Priority queues:** order path and thesis path are separate; text-reading
  batch jobs never starve interactive judgements.
- **Backpressure:** when the GPU queue is deep, the text reader returns
  "insufficient" and the system tightens; it does not block.
- **Per-owner quotas:** protect the system from one noisy agent; a flood of
  theses should not slow everyone.
- **Regional deployment:** if data residency requires it, shard by region; models
  are small enough to replicate. `[R]`

### 9.8 Failure modes and fail-closed behaviour

| Failure | Behaviour |
|---|---|
| Verdict missing/expired | Hold |
| Signature invalid | Hold and alert |
| Graph hash mismatch | Recompute or hold |
| Model timeout | Hold or shrink; never allow |
| GPU unavailable | CPU fallback with tighter threshold; if too slow, hold |
| Feature store stale | Hold |
| Owner model unavailable | Use population prior with wider uncertainty; ask more |
| Calibration drift alarm | Raise threshold; shadow the new model |
| Registry unavailable | Continue on the last signed model; do not reload |

`[R]` The table is a design commitment; each row needs a test.

### 9.9 Observability and audit

- **Metrics:** per-path latency, error rate, cache hit, fail-closed rate, score
  distribution, calibration by owner and family, hold rate, interruption rate.
- **Traces:** one trace per order/thesis, with model versions and feature hashes.
- **Audit log:** append-only, hash-chained, queryable by owner, thesis, action,
  model and time; supports replay.
- **Alerts:** calibration drift, score distribution shift, fail-closed spike,
  injection attempts, signature failures, latency SLO burn.
- **Dashboards:** product metrics (holds, asks, overrides) and safety metrics
  (false allows, incidents).

### 9.10 Cost

The dominant costs are owner time and data generation, not GPU inference.
`[R]` Two A6000s serve a small-to-medium customer base comfortably; the model
portfolio is small by design. The cost model should include:

- GPU amortisation and electricity;
- human review time per 1,000 actions;
- data generation and labelling;
- engineering on-call.

If inference cost ever dominates, the answer is a smaller student, not a bigger
GPU. `[R]`

### 9.11 Deployment and rollback

- **Shadow:** no authority, log only, compare to owner.
- **Hold-only canary:** authority to hold but not shrink, on 1% of traffic.
- **Shrink canary:** authority to shrink, on a small cohort.
- **Full:** all tighten actions.
- **Rollback:** one registry change; verdicts minted by the bad version are
  invalidated by policy version.
- **Kill switch:** resolves every decision to hold. `[R]`

---

## 10. Build order

The order is deliberately unfashionable: **no model before the graph, no text
model before the labels, no RL before calibration, no scale before shadow.**
`[R]` Each stage has an exit criterion; a failed criterion stops the stage, it
does not get averaged away. The durations are my estimates; the order is the
claim that matters. `[R]`

### Stage 0 — Foundations (2–4 weeks)

Build:

- the decision-time harness (F2): signed events, read-before-write edges, tool
  and memory hooks;
- the typed thesis record and the Justification compiler (F3);
- `model_view` integration and a CI test that no feature extractor sees `meta` or
  `label`; `[E: SCHEMA §5]`
- the replay engine (F8) and a validator-backed episode builder; `[E: SCHEMA §6]`
- the audit ledger (F7) and the only-tighten property test.

Exit: every action in the arena has a complete graph and a valid Justification;
replay is bit-exact; the only-tighten fuzz test passes.

### Stage 1 — Deterministic baseline (2–3 weeks)

Build:

- the five shape detectors in code: unverified-root share, root concentration,
  cycle membership, provenance break, path-to-intent;
- exact verifiers (F4) for hashes, quotes, facts, bands, caps, turnover, thesis
  status, invalidation;
- a logistic regression on a small, hand-built feature set;
- the evaluation harness with family and author splits.

Exit: on held-out families, the code shapes plus logistic model beat the existing
deterministic monitor on lead time at the same false-hold rate. If not, stop and
ship the monitor. `[E: SYSTEM-ONE §11, experiment 1]`

### Stage 2 — Data factory (3–5 weeks)

Build:

- simulator v2 with all seven failure families, multi-cause episodes, hard
  negatives, shifted variants and novel causes;
- counterfactual replay for necessity, sufficiency and Shapley targets;
- the label store with provenance, weights and splits;
- the leakage audit (surface-only family classifier).

Exit: at least 20k validator-clean episodes and 200k labelled actions; leakage
classifier is at chance; replay labels are stable across seeds.

### Stage 3 — Calibrated tabular stack (3–4 weeks)

Build:

- M2 thesis judge, M3 cause head, M4 attribution head;
- M7 owner model;
- M8 stacker, M9 isotonic plus conformal;
- the meso service and the signed verdict format;
- shadow mode on real or simulated owners.

Exit: ECE ≤0.05 in distribution after recalibration; lead-time gate met on
held-out families; conformal coverage within 2%; no case where the model loosened
a decision; p99 latency met.

### Stage 4 — Text verifier (4–6 weeks)

Build:

- M1 supervised stage on synthetic pairs;
- teacher panel and distillation pipeline;
- quarantine boundary and injection suite;
- integration of M1 scores into M2 and M3.

Exit: semantic families (paraphrase, implied authority, misquote-by-meaning)
improve attribution F1 and Brier by the pre-registered margin; injection suite
passes; text p99 ≤300 ms.

### Stage 5 — Optional structural models (4–6 weeks)

Build:

- M5 graph expert with link prediction and rewiring contrastive;
- M6 sequence expert against the hazard baseline;
- ablations for each.

Exit: each model beats the simpler alternative on held-out families by the
pre-registered margin, or is removed. No exceptions for elegance. `[R]`

### Stage 6 — Owner flywheel and policy (ongoing)

Build:

- owner console with evidence before prediction;
- random audit slice and importance weighting;
- interruption policy with offline contextual bandit and doubly robust OPE;
- per-owner cold-start tracking.

Exit: the cold-start curve improves with population size; interruption rate falls
at constant false-allow; reviewers report the questions are useful.

### Stage 7 — Scale and operations (ongoing)

Build:

- multi-tenant sharding, quotas and backpressure;
- canary, rollback, kill switch drills;
- drift monitors and calibration alarms;
- on-call runbooks.

Exit: SLOs met under peak; rollback drill passes; no single point of failure on
the order path.

### 10.1 What not to build early

- The 7B teacher fine-tune: wait until Stage 4 has data and a student baseline.
- The GNN: wait until Stage 5 and a feature plateau.
- The RL policy: wait until Stage 6 and enough logged decisions for OPE.
- A general-purpose agent or chat interface: never, for this product.
- A custom database or graph engine: use existing stores; the scale does not
  justify it. `[R]`

### 10.2 Team shape

Minimum: one systems engineer for the harness and order path, one applied ML
engineer for the tabular/text stack, one research engineer for labels and
evaluation, and a domain expert for the mandate and owner semantics. A part-time
security reviewer for the injection surface. `[R]`

---

## 11. Risks

Likelihood and impact are my judgements, not measurements. `[R]`

| # | Risk | Likelihood | Impact | Mitigation | Early warning |
|---|---|---|---|---|---|
| 1 | **Owner labels are too noisy or non-stationary**; the target is not learnable | Medium | Fatal | Repeated elicitation; latent noise model; narrow questions; abstain; redefine per decision class | Intra-owner agreement <80%; calibration plateaus above 0.10 |
| 2 | **Simulator-to-real gap**; model learns generator artefacts | High | Fatal | Author/family holdouts; leakage audits; real shadow data; adversarial generation; causal ablations | Surface-only classifier beats chance; collapse on held-out author |
| 3 | **Calibration fails under shift** | High | Severe | Ensembles; Mondrian conformal; drift monitors; conservative thresholds; deterministic fallback | ECE rises; conformal coverage misses; score distribution shift |
| 4 | **Injection or graph gaming**; agent fabricates a clean story | Medium | Severe | Harness-signed events; no agent-controlled trust; quarantine; hash checks; instruction hierarchy; no free text in privileged prompts | Red-team success; provenance anomalies; sudden clean-graph rate |
| 5 | **Latency creep**; models creep onto the order path | Medium | Severe | Hard timeouts; build check forbidding model imports; separate planes; budget tests in CI | p99 trend; new dependency in order path |
| 6 | **Operational complexity**; too many models and services | High | Medium | Cap the portfolio; one stack; registry; canary; runbooks; quarterly deletion review | Alert fatigue; deploy lead time; on-call load |
| 7 | **Selection bias in owner labels** | High | Medium | Random audit slice; importance weighting; doubly robust estimation | Review-queue vs audit gap |
| 8 | **Automation bias**; owners rubber-stamp the model | Medium | Severe | Show evidence before prediction; blind reviews; random audits; disagreement sampling | Review time collapse; agreement near 100% |
| 9 | **Privacy and legal exposure** from owner data | Medium | Severe | Pseudonymisation; consent; retention limits; data residency; DPIA; audit trail | Data access reviews; subject requests |
| 10 | **Teacher/API dependency**; model changes or disappears | Medium | Medium | Pin versions; cache labels; multiple teachers; no runtime dependency; student fallback | API drift; label distribution shift |
| 11 | **Benchmark overfitting / Goodhart** | High | Medium | Pre-registered metrics; held-out families; canaries; external red team; rotate test sets | Gains vanish on new family; suspiciously high scores |
| 12 | **False sense of safety**; product overclaims | Medium | Severe | Language: "can only tighten"; human accountability; incident process; conservative defaults | Marketing drift; users disabling holds |
| 13 | **Model supply-chain compromise** | Low | Severe | Signed artefacts; hashes; SBOM; isolated serving; no remote code | Signature mismatch; unexpected dependency |
| 14 | **Timeline and skills gap** | Medium | Medium | Staged build; kill criteria; hire systems and ML; narrow scope | Stage exits slip repeatedly |
| 15 | **Name/trademark conflict** | High | Low | Trademark search; public rename; keep internal working name | Search results; legal review `[E: SYSTEM-ONE §11]` |
| 16 | **Data generation cost dominates** | Medium | Medium | Reuse episodes; active learning; synthetic paraphrase; cache labels | Cost per labelled action rises |
| 17 | **Schema drift** breaks features and replays | Medium | Medium | Versioned schema; migrations; golden episodes; contract tests | Replay mismatches; feature nulls |
| 18 | **Owner endorses bad trades**; the target is not "good" | Certain | Low | Document that profitability is not the job; monitor outcomes separately | Owner losses on endorsed actions |

### 11.1 The three risks I would watch daily

1. **Leakage.** It is the most likely way to get a great benchmark and a useless
   product. The surface-only classifier and the author holdout are the cheapest
   canaries. `[R]`
2. **Calibration drift.** It is the most likely way to get a useful model that
   silently becomes unsafe. The conformal guarantee is only valid while new data
   resembles the calibration data; monitor exchangeability explicitly. `[E:
   SYSTEM-ONE §7; R]`
3. **Injection through the text reader.** It is the most likely way for an
   attacker to turn a safety system into an approval system. The quarantine is
   only as strong as its weakest field. `[E: SYSTEM-ONE §6; R]`

### 11.2 Risks that are not technical

- **The product may be judged on profitability.** It must not be. Owners can
  endorse bad trades; that is their right. Set expectations with a clear product
  contract. `[E: SYSTEM-ONE §2]`
- **The review queue may become the bottleneck.** If the model asks too often,
  owners disengage. The interruption policy is a product feature, not an
  optimisation detail. `[R]`
- **The name may be taken.** Settle it before public use. `[E: SYSTEM-ONE §11]`
- **Regulatory audit may ask for a single explanation.** The stack must produce a
  node-level, reason-coded explanation and an audit trail; "the model said so" is
  not acceptable. `[R]`

### 11.3 Residual risk statement

Even a perfect System One cannot stop an owner from endorsing a harmful action,
cannot stop a compromised harness from recording a false graph, and cannot
guarantee calibration outside the data it has seen. The design reduces these
risks; it does not eliminate them. That is why the authority model is "hold,
never approve", and why the owner remains the final signatory. `[E: BRIEF;
SYSTEM-ONE §6; R]`

---

## 12. Ideas I would prototype beyond the current plan

These are unconventional, cheap to test, and each attacks a specific weakness.

### 12.1 Compile each thesis into a decision circuit

At thesis formation, compile the thesis's invalidation trigger, evidence
freshness rule, mandate bands, allowed instruments and permitted graph shapes
into a small set of code-checkable predicates — a **decision circuit**. The
learned model does not output the decision; it outputs a scalar gain `g` and a
cause vector. The order path runs the circuit with `g` as a multiplier.

Why: it makes "only tighten" structural, makes the order path trivially fast,
and gives an explanation a regulator can read. It also separates what the model
is good at (setting a conservative gain) from what code is good at (enforcing
predicates). `[R]`

Risk: the circuit can be too rigid for legitimate adaptation. Mitigation: the
circuit is regenerated when a thesis changes, and unknown shapes route to ask,
not block. `[R]`

### 12.2 The owner card

Treat each owner like a credit scorecard: a small set of interpretable features
and a posterior. The population model is the prior; the owner card is the
residual. Show the owner their card ("you hold more on unverified social than
similar owners; you ask to be consulted when tech exceeds 45%"). This builds
trust, speeds labelling, and makes cold start visible. `[R]`

### 12.3 Attribution by counterfactual distillation

Train the attribution head on replay Shapley, not on attention or post-hoc SHAP.
Use group Shapley over node types to reduce variance, and keep the "unexplained"
bucket. Evaluate by occlusion: if the explanation says a node carries 60% of the
weight, removing it should move the score by about that much. `[R]`

### 12.4 Disagreement-driven escalation

Use ensemble disagreement and conformal set size as the escalation signal, not a
fixed uncertainty threshold. Ask the owner when the expected value of information
exceeds the interruption cost. This is the principled version of "ask when
unsure". `[E: SYSTEM-ONE §2 on Capponi et al.; R]`

### 12.5 Mystery-shopper theses

Plant a small number of synthetic "mystery" theses in production, with known
ground truth, that only the evaluation team can identify. They measure end-to-end
false allows and latency in the real system, the way banks mystery-shop branches.
Remove them from owner queues. `[R]`

### 12.6 A "negative" model of the owner

Model what the owner would **never** sign, not only what they would sign.
Negative constraints are sharper, easier to label, and more stable under shift.
Use them as a hard prior that the endorsement model cannot override. `[R]`

---

## 13. Open questions, and what would change my mind

### 13.1 Questions I cannot answer from the documents

1. **How consistent are owners?** If intra-owner agreement is low, the ceiling is
   low and the product must be reframed around "ask" rather than "predict".
2. **How much does the graph add over text and exact checks?** This is the first
   experiment in SYSTEM-ONE, and it decides whether the reframe earns its keep.
   `[E: SYSTEM-ONE §11]`
3. **What fraction of failures are semantic rather than structural?** This sets
   the text budget. If most failures are numeric or authority violations, the
   text model is a small add-on; if paraphrase dominates, it is central.
4. **Can the simulator produce realistic owners and agents?** If not, the
   planted-cause labels train a model that only works in the arena.
5. **What is the owner's real interruption cost?** The policy cannot be tuned
   without it; estimate from behaviour, not surveys. `[R]`
6. **What does the regulator require?** The explanation and audit format should
   be designed with compliance, not retrofitted. `[R]`

### 13.2 What would change my mind

- **If owners are highly consistent and semantic failures dominate:** keep the
  architecture but increase the text student to 1–3B, distilled from a stronger
  teacher; accept a higher GPU budget and move the text path fully asynchronous.
  `[R]`
- **If the graph adds nothing:** ship the deterministic monitor plus the review
  queue, and stop calling it System One. `[E: SYSTEM-ONE §11]`
- **If calibration under shift cannot be held below 0.10:** shift the product to
  abstention-heavy: more asks, lower coverage, deterministic fallback. Calibration
  is not negotiable; coverage is. `[R]`
- **If owner labels are sparse but teacher labels are good:** lean on
  distillation and treat owner data as a calibration set, not a training set.
  `[R]`
- **If latency budgets tighten:** remove the text reader from the thesis path and
  use only exact checks plus the GBDT; the semantic cases become asks. `[R]`

### 13.3 What I would do in the first ten working days

1. Instrument one episode end to end and dump the graph. Verify availability and
   hashes against the validator.
2. Implement the Justification compiler and the five shape features in code.
3. Run the existing deterministic monitor and the shape features on 1,000
   generated episodes; measure lead time and false-hold.
4. Build the only-tighten fuzz test and the leakage canary.
5. Write the evaluation sheet before training anything. `[R]`

---

## 14. Summary

1. **System One is a principal model plus a conservative decision layer**, not a
   general model and not an autonomous approver. `[E: SYSTEM-ONE §2, §6]`
2. **The representation is the moat**: the decision-time provenance graph and the
   typed Justification. Build them first. `[E: SYSTEM-ONE §10; R]`
3. **The label factory is the second moat**: planted causes, counterfactual
   replay, owner decisions, audit slice, constitution. `[E: SYSTEM-ONE §7]`
4. **The workhorse is a calibrated GBDT on engineered relational features**, not
   a fine-tuned LLM. `[R]`
5. **The text model is a small distilled verifier over quarantined fields**, not
   a judge over agent prose. `[E: SYSTEM-ONE §6; R]`
6. **A GNN and a sequence model are optional**, adopted only on held-out gains.
   `[R]`
7. **The owner model is a hierarchical Bayesian scorecard**, not a per-owner
   fine-tune. `[R]`
8. **Calibration and conformal risk control are the product**, not reporting.
   `[E: SYSTEM-ONE §7]`
9. **Three clocks keep latency honest**: code at order time, learned at thesis
   time, graph and sequence in the background. `[R]`
10. **Build order**: harness → deterministic shapes → data factory → calibrated
    tabular stack → text verifier → optional structural models → owner flywheel
    → scale. `[R]`
11. **The kill criteria are real**: if the graph does not beat the monitor, if
    calibration misses 0.05 in distribution or 0.10 under shift, or if anything
    ever loosens a decision, stop. `[E: SYSTEM-ONE §11]`

The founder's question was where the most potential lies. My answer: **in the
record, the labels and the calibration — not in the size of the model.** A small
system that knows what the owner signed, what the agent actually read, and how
confident it is will beat a large system that only reads the agent's story. `[R]`

---

## 15. References for external evidence

These are the external works cited above. The supplied-document citations are
inline as `[E: SYSTEM-ONE §n]` and `[E: SCHEMA §n]`.

- Angelopoulos, A. N., & Bates, S. (2021). *A Gentle Introduction to Conformal
  Prediction and Distribution-Free Uncertainty Quantification.* arXiv:2107.07511.
- Chen, L., et al. (2021). *Decision Transformer: Reinforcement Learning via
  Sequence Modeling.* NeurIPS.
- Guo, C., Pleiss, G., Sun, Y., & Weinberger, K. Q. (2017). *On Calibration of
  Modern Neural Networks.* ICML.
- Hamilton, W. L., Ying, R., & Leskovec, J. (2017). *Inductive Representation
  Learning on Large Graphs.* NeurIPS.
- Jain, S., & Wallace, B. C. (2019). *Attention is not Explanation.* NAACL.
- Ke, G., et al. (2017). *LightGBM: A Highly Efficient Gradient Boosting Decision
  Tree.* NeurIPS.
- Lundberg, S. M., & Lee, S.-I. (2017). *A Unified Approach to Interpreting Model
  Predictions.* NeurIPS.
- Velickovic, P., et al. (2018). *Graph Attention Networks.* ICLR.
- Vovk, V., Gammerman, A., & Shafer, G. (2005). *Algorithmic Learning in a Random
  World.* Springer.
- Wang, W., et al. (2020). *MiniLM: Deep Self-Attention Distillation for
  Task-Agnostic Compression of Pre-Trained Transformers.* NeurIPS.

