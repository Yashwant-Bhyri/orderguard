# BLUEPRINT — System One, end to end

One independent writer's answer to BRIEF.md. Written from the two sources in
this folder: `SYSTEM-ONE.md` (the vision) and `SCHEMA.md` (the world schema).
The vision references JUDGEMENT.md, PRODUCT-SPEC.md and research reports; none
of them is in this folder, so I do not rely on them.

**Claim labels.** Every claim below carries one of:

- `[E-S1 §n]` — evidence from SYSTEM-ONE.md, section n.
- `[E-SCH §n]` — evidence from SCHEMA.md, section n.
- `[E-BRIEF]` — evidence from BRIEF.md (compute, latency, model access).
- `[E-relay]` — a paper claim as relayed by SYSTEM-ONE.md. I have not read
  the originals; I trust the vision's own source-type column (peer-reviewed,
  preprint, lab, benchmark) and say so.
- `[R]` — my own reasoning or design choice.
- `[R-est]` — my own quantitative estimate, to be replaced by measurement.

---

## 0. Stance, and the one-paragraph answer

**My first idea, and why I am rejecting it.** My first idea was the obvious
one: fine-tune an open-weight LLM as the judge, feed it each episode, and
teach it to output the endorsement probability. Rejecting it, in order:

1. The latency and compute budgets kill it. Code checks plus the scorer must
   run at p99 ≤ 50 ms on a *laptop-class CPU*; text reading gets p99 ≤ 300 ms
   on GPU `[E-BRIEF]`. A served LLM judge does not fit the first budget at
   all and wastes the second. `[R]`
2. It is the wrong shape. A judge that reads agent-written text can be
   injected by it: superficial tokens alone fool frontier judges up to about
   90% of the time `[E-S1 §6]`. The whole point of the typed graph is that
   the judge never has to wade in the agent's prose. `[R]`
3. Most of what the judge must know is not semantic. SCHEMA.md's failure
   taxonomy is, on inspection, six parts arithmetic and bookkeeping to one
   part language (§1 below). An LLM is a costly, badly-calibratable way to do
   arithmetic on a typed record. `[R]`
4. Calibration is the binding constraint, and calibration tooling (Brier,
   ECE, isotonic, conformal) works best on small supervised models. The best
   calibration-trained model known to the vision goes from ECE 0.03 in-domain
   to 0.21 out of it `[E-S1 §11]`; that is the gap to engineer against, and
   architecture novelty is the enemy of it. `[R]`

**The one-paragraph answer.** System One should be mostly code, then a small
set of classical supervised models, then one small language model, in that
order of trust. Code computes the typed provenance graph and catches every
failure whose shape is arithmetic — bands, quotes, facts, signatures,
invalidation triggers — which is most of the canonical causes `[R, from
E-SCH §3]`. Classical models (gradient-boosted trees, a small graph neural
network, a k-NN witness for out-of-distribution sensitivity) supply the
calibrated endorsement probability and the trajectory lead-time signal, on
CPU, inside 50 ms. A small frozen encoder with trained heads reads only the
quarantined text fields (is this note an instruction? is this claim hype?),
on GPU, inside 300 ms. Frontier LLMs — DeepSeek via API — are used *offline*:
to diversify and adversarially enrich the simulator's text, and as the
escalation reviewer, never on a hot path. The learning is: no post-training
at first (code), then supervised heads, then distillation of the reader from
planted-cause labels, then RL applied narrowly — to the interruption policy,
where the action space is small and the reward is a bounded proper score —
not to the judgement itself. The endorsement target is decomposed into
factors (evidence, reasoning, objective, owner-fit, unexplained) so that the
same model that judges also attributes, and every factor can only tighten
the verdict. Nothing on the order path is a model: the µs path is a cache
lookup plus arithmetic, and code is the only thing that says yes
`[E-S1 §5, E-S1 §9]`.

**Why this is not a consensus document.** Two places I push against the
vision's own architecture sketch, argued in §4: (a) I make the *factorised*
endorsement model primary rather than a single ensemble classifier, because
it unifies judging with attribution `[E-S1 §4]` and survives shift better;
(b) I restrict RL to the interruption policy and reject RL on the judge,
which the vision leaves open `[E-S1 §7]`. I also make explicit something the
vision implies but does not state: on SCHEMA.md's taxonomy, the deterministic
code monitor will be *very strong*, and the models must earn their place on
lead time, on semantics, and on owner-fit — not on the causes code already
catches. `[R]`

---

## 1. The cognitive core: exactly what System One must know

The founder's instruction is to put this subset ahead of general next-token
prediction `[E-BRIEF]`. The schema makes the subset unusually concrete, so I
derive it from the failure causes directly `[R]`.

### 1.1 The causes, sorted by how much model they need

| Cause (SCHEMA §3) | What detecting it actually requires | Detector |
|---|---|---|
| `drift` | Replay the book; compare post-trade sector weight to the signed band; the onset buy is labelled | Code, exact `[E-SCH §2, §3]` |
| `misquote` | `quoted_span` must be an exact substring of `source_doc.text`; the claim's number must equal the document fact's | Code, exact `[E-SCH §2]` |
| `unsupported_claim` | Look the claim's fact up in `source_doc.facts` by name/value/unit | Code, exact `[E-SCH §2]` |
| `authority_spoof` | Is there an `owner_signed` note with `signature_valid` for the asserted mandate change? | Code, exact `[E-SCH §2]` |
| `stale_thesis` | Evaluate the typed `invalidation_trigger` against later documents' `facts`; check thesis `status` | Code, exact `[E-SCH §2]` |
| `poisoned_note` | Decide whether a note's text is an *instruction about behaviour* rather than *evidence about the world*, phrased novelly | Semantic: small model `[R]` |
| `vague_hype` | Enthusiasm with no concrete anchored figure, vs enthusiastic-but-factual | Semantic: small model `[R]` |
| Owner would not sign, all checks green | Owner preference beyond the written mandate | Statistical: owner model `[E-S1 §2]` |
| `novel_cause` | Anything we did not enumerate | Conformal abstain → escalate `[E-SCH §3, E-S1 §6]` |

So: five of the seven canonical causes are deterministic given the typed
record, because the schema gives machine-checkable forms — `facts`,
`quoted_span`, `signature_valid`, `invalidation_trigger`, book replay
`[E-SCH §2]`. The language model's real job is two classifications over
short quarantined fields, plus embeddings for similarity and novelty. That
is the cognitive core: **mandate arithmetic, provenance logic, thesis
lifecycle, instruction-vs-evidence, hype-vs-fact, owner preference.**
`[R]`

### 1.2 What System One explicitly does not need

- General world knowledge or market prediction. It never claims to know
  whether a trade will make money `[E-S1 §2]`.
- Long-form generation. Explanations point at nodes, rendered from typed
  attribution by code `[E-S1 §3, E-S1 §6]`.
- Reading the agent's free text at judgement time. Rationale and note text
  reach it only as quarantined, code-typed fields `[E-S1 §6]`.
- Multi-step planning or tool use. It is a judge with one fixed set of typed
  questions `[E-S1 §6]`.

This is why "a proper ML model" for System One is not an LLM with the
general abilities stripped — it is a small set of narrow heads over a typed
graph, plus the one encoder for the semantic residue. `[R]`

### 1.3 The factorisation of endorsement

Endorsement is not one opaque score. It factors:

```
p(endorse) = σ( b0
  + w_ev  · f_evidence   (were the beliefs credible?)
  + w_rsn · f_reasoning  (does the action follow from beliefs + thesis?)
  + w_obj · f_objective  (does it move the book toward the purpose?)
  + w_own · f_owner      (would this owner sign it, beyond the contract?)
  + w_unx · f_unexplained (an explicit residual bucket, never forced to 0) )
```

- The four named factors are the vision's attribution effects, verbatim
  `[E-S1 §4]`. One model therefore answers both "would the owner sign?" and
  "why not?": the factor values *are* the attribution weights. `[R]`
- `f_unexplained` exists because attribution fails when the fact was already
  known; forcing every unit of weight onto a visible node would lie
  `[E-S1 §4]`. In practice it absorbs conformal abstention and model
  disagreement. `[R]`
- Weights are constrained so that any factor failing can only *reduce*
  endorsement (a noisy-AND in logit space), matching "it can only tighten"
  `[E-S1 §5]` at the model level too. `[R]`
- Each factor gets its own label source and its own calibration, which is
  the point: code-checked factors have exact labels; semantic factors have
  planted labels; the owner factor has owner decisions. Calibration is
  per-factor, not one mushy global number. `[R]`

### 1.4 The one genuinely custom architecture worth funding

The object being judged is a graph recorded at decision time `[E-S1 §3]`.
So the one place to spend architectural novelty is a small graph neural
network over the provenance graph (node types: document, note, claim,
thesis, action, book; typed features on each). Everything else stays
standard, because every calibration result we rely on assumes standard
training `[E-S1 §7]`. "Custom-modified decision model" should mean *custom
input contract and custom output factorisation*, not surgery on attention.
`[R]`

---

## 2. The functions

System One's job, as a set of callable functions with typed inputs and
outputs. Each is level-tagged per the six-level scheme `[E-S1 §5]`.

| # | Function | In → Out | Level | Runs on |
|---|---|---|---|---|
| 1 | `record` | tool call / memory access / intent / order → append to provenance graph | — | harness, event time |
| 2 | `verify_input` | document or note → {hash_ok, trust_tier, instruction_like, hype_score, novelty} | 1 | GPU reader, ≤300 ms p99 |
| 3 | `score_thesis` | (owner, thesis, evidence subgraph, reader features) → {p_endorse, per-factor values, attribution weights, conformal band, verdict: hold / pass-with-budget / escalate} | 2 | CPU, ≤50 ms p99 |
| 4 | `authorise_order` | (action, cached thesis verdict, book) → {allow} or {hold, reason code} | 3 | CPU, µs–ms, code only |
| 5 | `monitor_trajectory` | per-agent event stream → {drift_score, loop_score, herd_score, budget_delta} | 4 | CPU per agent, continuous |
| 6 | `aggregate_swarm` | cross-agent graph → common-root exposure, per-root cap | 5 | CPU, continuous |
| 7 | `review_book` | (book, mandate, open theses) → de-risking proposals for the owner to sign | 6 | nightly; APIs allowed here |
| 8 | `attribute` | (episode subgraph, outcome, replay results) → per-cause weights with an unexplained bucket | any | CPU batch |
| 9 | `adapt_owner` | (population prior, this owner's decisions) → posterior owner model + interruption threshold | 2 | CPU, online |
| 10 | `escalate` | abstain band → frontier reviewer (API) → human | any | off-path |
| 11 | `audit_slice` | allowed orders → random sample shown to owner after the fact | — | product feature |

Notes on the two that are load-bearing:

- **`authorise_order` (level 3) never calls a model.** The judgement happened
  at level 2 when the thesis was formed; an order only proves, in code, that
  it belongs to a judged, still-valid thesis `[E-S1 §5]`. Concretely: a
  verdict cache keyed by (thesis_id, hashes of thesis record, mandate,
  model/feature/threshold versions); on the order path, membership check,
  then arithmetic — post-trade sector band, position cap, cash and position
  non-negativity, per-thesis turnover and fee caps `[E-SCH §2, E-S1 §5]`.
  The turnover cap is a code check whatever the thesis verdict, because
  orders inside a valid thesis can still add up to harm — one live model paid
  about 13% of capital in fees `[E-S1 §5]`. (SCHEMA keeps turnover out of
  replay `[E-SCH §2]`; the live harness must still measure it `[R]`.)
- **`audit_slice` must exist from day one.** Labels exist only for held
  orders, so they are biased; a random audit slice of allowed orders
  corrects this, as fraud teams do `[E-S1 §2]`. It is a product decision
  with a real interruption cost, so sample it with a budget. `[R]`

## 3. Architecture

### 3.1 Components

```
   agent runtime (harness: records every tool call, memory access,
        intent, order, with hashes and times — the only sensor [E-S1 §9])
             │  events, incremental feature updates
             ▼
   ┌──────────────────────────────  event-time plane (CPU) ──┐
   │ graph store + incremental feature factory                │
   │ (at judging time, features are already computed: lookup) │
   └───────┬───────────────────────┬────────────────────────┘
       reads (L1)             theses (L2)            orders (L3)
           │                     │                      │
   GPU reader 300ms     CPU scorer 50ms +         code only: cache
   (quarantined text)   conformal threshold       + arithmetic, µs
           │             + verdict cache               │
           └───────┬─────────┘                         │
                   ▼                                   ▼
        trajectory (L4) & swarm (L5) monitors      allow or HOLD
        (streams, budgets: only tighten)          (fail-closed)
                   │
                   ▼
        book review (L6, nightly: code + DeepSeek + hosted decision model)
        escalation: abstain → frontier reviewer (API) → human [E-S1 §6]
```

### 3.2 The two latency paths, decomposed

- **50 ms CPU (thesis):** feature lookup (precomputed at event time) + five
  small scorers (GBT ~0.1 ms each, MLP and GNN a few ms in ONNX, LR/k-NN
  negligible) + conformal threshold check + cache write. The expensive part
  — building the graph — is done continuously as events happen, not at
  judgement time. If features were computed inside the 50 ms window this
  budget would blow up; the incremental feature factory is the design
  decision that makes the budget safe. `[R, budgets E-BRIEF]`
- **300 ms GPU (reader):** a batched small encoder over quarantined fields
  (document texts are 2–6 sentences, rationales 1–3 sentences
  `[E-SCH §2]`), so a 100–400M model at batch 8 has an order of magnitude of
  headroom. `[R]`

### 3.3 Fail-closed everywhere

- The default verdict is **hold**. Any component failure — reader down, API
  unreachable, cache miss, hash mismatch, feature schema drift — tightens.
  `[R]`, implementing "authority flows only downward / code says yes"
    `[E-S1 §9]`.
- The verdict cache invalidates on *any* input change: thesis record,
  mandate, model registry, threshold versions. A stale verdict is treated as
  no verdict. `[R]`
- An invariant test in CI: over the full test corpus, no input sequence may
  make a later verdict looser than an earlier one; `g(endorsement)` may only
  shrink the risk budget `[E-S1 §9]`. This is the "there is any case in
  which it loosened a decision" kill criterion `[E-S1 §11]`, enforced as a
  property test rather than a hope. `[R]`

### 3.4 The graph, concretely

Nodes: documents (with `trust_tier`, `content_hash`, `facts`), notes (with
`written_by`, `signature_valid`), claims, theses (with evidence hashes and
typed invalidation), intents, orders, book snapshots `[E-SCH §2, E-S1 §3]`.
Edges: what was read before what was written, in the strict step order of
the schema — pre-notes, action, execution, new-notes, and nothing cites the
future `[E-SCH §1]`. The harness enforces availability at decision time, so
"it reads only what was knowable at the time of the action" `[E-BRIEF]` is a
property of the sensor, not a discipline of the model. `[R]`

---

## 4. The models, and the trade-offs the founder asked for

### 4.1 The served stack

| Component | Model | Size | Learns how | Runs where | Why this |
|---|---|---|---|---|---|
| Order check (L3) | code only | 0 | — | laptop CPU, µs | code is the only authoriser `[E-S1 §9]` |
| Thesis scorer (L2) | noisy-OR ensemble: LR + GBT + small MLP + 2-layer GNN + k-NN witness, per §1.3 factors | 10⁵–10⁶ params total | supervised, then calibration | laptop CPU ≤50 ms | heterogeneity is the shift defence `[E-S1 §6]`; each member is auditable `[R]` |
| Text reader (L1/L2) | frozen pretrained encoder trunk + small trained heads | 100–400M | heads on planted labels; adversarial slice distilled from a frontier teacher | GPU ≤300 ms | only component that needs semantics `[R]` |
| Trajectory (L4) | windowed GBT; optional tiny GRU (≤10M) over per-step feature vectors | 10⁵–10⁶ | supervised on simulated streams | CPU | lead time is its whole job `[R]` |
| Swarm (L5) | code: `content_hash` dedup across agents `[E-SCH §2]`; embedding clustering for paraphrased roots | small | — | CPU/GPU | common-root caps are arithmetic `[E-S1 §3]` |
| Book review (L6) | code + DeepSeek API + hosted decision model | — | — | nightly | 1 s and 30 s budgets are fine off-path `[E-BRIEF]` |
| Owner adapter | hierarchical Bayesian logistic with per-owner shrinkage | ~10² | online from review queue + audit slice | CPU | inspectable, calibratable, cheap `[R, E-S1 §2]` |

The vision's "ensemble of five" is kept `[E-S1 §6]`, but I make the five
*heterogeneous by construction* (parametric, non-parametric, tabular, graph,
and distance-based), because ensembles protect calibration under shift only
when members fail differently. `[R]`

### 4.2 The trade the founder asked about: model kinds vs post-trainability

| Option | Cognitive coverage | Post-train effort | Serve at our budgets | Calibration control | Injection surface | Verdict |
|---|---|---|---|---|---|---|
| Fine-tuned LLM judge (7–70B) | highest | high (SFT+RLHF-style, fragile) | no (50 ms CPU impossible) | poor tooling | reads agent text: up to ~90% foolable `[E-S1 §6]` | reject at inference |
| DeepSeek API as served judge | highest | none | no (latency, egress, cost at volume) | opaque | exposed | reject on hot paths; keep for escalation + data factory `[E-S1 §6]` |
| Classical ML on typed features | narrow but covers the arithmetic causes exactly | trivial | yes, easily | excellent (Brier/ECE/isotonic/conformal all standard) | none (typed inputs) | **backbone** |
| Custom-modified architectures (strip layers, modify attention) | speculative | research-grade; breaks tooling and audit story | unknown | no evidence base in our materials | — | reject; see §4.4 |
| Policy distillation into a small student | good on the distribution the teacher covers | low (student is small; labels are planted) | yes | good (student calibrated on planted labels) | minimal (quarantined inputs) | **the semantic path** |
| External hosted decision model (typed Q&A, ~1 s) | medium | none | L2: no; L6: yes | unknown to us | typed surface only | use at L6 + as shadow teacher `[E-BRIEF, R]` |

**Where the most potential lies, ranked** `[R]`: (1) code on the typed graph
— certain, immediate, free of latency and calibration problems; (2) policy
distillation for the two semantic classifications and the owner factor —
the best gain per unit of post-training, because the simulator supplies
exact labels `[E-S1 §7]` and the student is small enough to serve anywhere;
(3) the GNN over provenance — the one bet on architecture; (4) LLMs — but as
the *data factory and escalation reviewer*, where their quality is free of
our latency budget. This is the inversion of the founder's implied ordering:
LLMs matter most to System One where they are *not* System One. `[R]`

### 4.3 Which layers, which paradigms

- **Reader:** a pretrained encoder trunk (DeBERTa-class or similar small
  open model), frozen except the last two layers, plus fresh classification
  heads. LoRA on the last layers only if held-out attack families show the
  frozen trunk underfits. No generation on any served path — explanations
  are rendered by code from attribution weights `[E-S1 §3]`, which removes
  an injection surface and keeps every verdict deterministic and
  replayable. `[R]`
- **Scorer members:** GBT (a few hundred trees), 2×64 MLP, 2-layer GIN/GNN
  with sum pooling over the episode subgraph, penalised LR, k-NN. All
  standard, all supervised with a proper scoring rule. `[R]`
- **Paradigm mix:** supervised learning everywhere first `[E-S1 §7]`;
  Bayesian online learning for the owner factor; conformal risk control as
  the wrapper that turns scores into holds with a stated error rate
    `[E-S1 §7]`; RL only where §5.3 says.

### 4.4 On "stripping away parts of an architecture"

The founder asks whether custom-modified decision models — deleting layers,
changing input/output — are where potential lies. My answer: change the
**input contract and output factorisation** (that is §1.3 and the GNN), do
not operate on the **trunk**. Reasons: (a) every calibration and ensemble
result we rely on assumes standard training pipelines `[E-S1 §7]`; (b) an
audited financial control system needs a model whose training is boring;
(c) layer surgery optimises for capabilities we do not need — the cognitive
core in §1 is small, and a small core is better served by small standard
models than by an amputated large one. `[R]`

### 4.5 Attribution machinery

- Evidence, reasoning and objective effects are computed in code from the
  typed record (provenance of roots; coherence of intent–thesis–order;
  marginal book contribution to the mandate, Euler-style) `[E-S1 §4]`.
- Interaction terms: Shapley over ≤4 causes is exact and trivial at that
  cardinality; and the schema's `label.cause_refs` gives the ground-truth
  cause set to validate against `[E-SCH §2, E-S1 §4]`. This is affordable
  because CausalLoss-Fin found 27.8% of cases cannot be split one cause at
  a time `[E-relay, E-S1 §4]` — so interaction is a requirement, not a
  refinement. `[R]`
- Counterfactual replay is an offline label generator, not a served
  component: replay with one cause removed, see whether the order survives
  `[E-S1 §7]`. AgenTracer showed replay labels were good enough for an 8B
  student to beat frontier models at failure attribution `[E-relay, E-S1
  §7]` — on our compute, replay belongs to the data factory. `[R]`

---

## 5. What learns, and how much

Learning is staged, and each stage must beat the previous one on the kill
criteria of §7 or it does not ship. `[R]`

### 5.1 Stage-by-stage post-training budget

| Stage | What trains | Method | Amount | Gain expected |
|---|---|---|---|---|
| 0 | nothing | code only | 0 | the five arithmetic causes, exactly `[E-SCH §3]` |
| 1 | scorer members | supervised on simulator episodes + simulated owners | days of CPU | lead time, owner-fit, calibrated p_endorse |
| 2 | reader heads | supervised on planted text labels; adversarial slice distilled from DeepSeek | hours of GPU per run; LoRA on 4B is cheap `[E-S1 §12]` | the two semantic causes, robustly |
| 3 | GNN | supervised on graph labels | days of GPU | attribution accuracy, novel-cause sensitivity |
| 4 | owner adapter | online Bayesian updates | continuous, CPU | per-owner endorsement with few labels `[E-S1 §2]` |
| 5 | interruption policy | RL, bounded proper-score reward | moderate, measured at stage 3 `[E-S1 §12]` | principled when to ask |
| — | RL on the judge itself | — | — | **rejected**, §5.3 |

**Frozen vs trained, explicitly** (the founder's list):
- Frozen pretrained: the encoder trunk, at least initially `[R]`.
- Small heads: reader classifications, factor heads, trajectory windows.
- Fine-tuning: last-two-layer unfreeze or LoRA on the reader only, and only
  on evidence from held-out families.
- Teacher-student distillation: the reader's adversarial slice (teacher =
  DeepSeek; labels = the causes we planted, so the teacher supplies
  *phrasing diversity*, not truth) `[R]`; plus the hosted decision model as
  a shadow teacher for the endorsement head, checked against simulated
  owners `[R, E-BRIEF]`.
- RL: the interruption policy only (§5.3).
- From scratch: nothing above 10M parameters. Pretraining is not attempted
  on two shared A6000s; pretraining is also unnecessary for a cognitive
  core this narrow (§1). `[R]`

### 5.2 Why supervised first

SFT holds calibration better under shift than RL `[E-S1 §7]`, and
calibration is the binding constraint: the stretch target is ECE ≈ 0.10
under shift, and no published method we know of reaches 0.05 there
`[E-S1 §11]`. New detection skill has to come from the data — planted causes
and counterfactual replays — not from the optimiser `[E-S1 §7]`. So the
learning plan is mostly a *data* plan, and §6 is the heart of the build.
`[R]`

### 5.3 Where RL belongs — a narrower claim than the vision's

The vision proposes RL with a bounded proper scoring reward (Brier;
RLCR cut calibration error 0.37 → 0.03 in-domain) `[E-S1 §7]`. I would
restrict RL to one decision: **hold / pass / escalate / ask-the-owner**, a
contextual bandit with four arms, where (a) the action space is small,
(b) the reward is genuinely defined — the cost of a wrong pass, the cost of
an interruption `[E-S1 §2, Capponi relay]`, and a bounded proper score on
the endorsement estimate — and (c) off-policy evaluation is possible on the
audit slice. RL on the *judge* — gradients into the scorer to make it a
better detector — is rejected: RL mostly sharpens skills the base model
already has `[E-S1 §7]`, and a miscalibrated RL-shaped scorer is a licence
revocation waiting to happen. The bandit may even start as a simple
threshold policy updated by bandit feedback; call it RL only when the
threshold policy measurably leaves value on the table. `[R]`

### 5.4 The endorsement flywheel

Every owner decision updates the population prior, and every owner
improves the prior for the next one — the Radar pattern `[E-S1 §10]`.
Mechanically: per-owner random effects with strong shrinkage toward the
population posterior; the shrinkage constant is chosen so it takes tens of
decisions, not single digits, to move an owner's model far — an early
malicious or careless owner cannot poison the population prior. `[R]`

---

## 6. Data and labels

The world generator (SCHEMA.md) is the data factory, and it is better than
any public dataset because it labels the *true cause* of every action
`[E-S1 §7]`. Requirements I would impose on it, beyond validity:

### 6.1 Generator requirements

- **Cause-stratified sampling** with per-family quotas, and multi-cause
  episodes at realistic rates, because interaction terms need them
  `[E-S1 §4]`. If 27.8% of real cases are non-decomposable `[E-relay,
  E-S1 §4]`, roughly that share of training episodes must carry ≥2 planted
  causes. `[R-est]`
- **Hard-negative quotas** exactly as SCHEMA §4 demands — legitimate
  adaptation on fresh high-trust evidence, correct sells, exact quotes,
  enthusiastic-but-factual — because the false-hold rate on these four
  is what will make owners turn System One off. `[E-SCH §4, R]`
- **Owner diversity:** sample mandate parameters *and* latent owner policies
  (purpose, bands, plus latent style: e.g. how much an owner tolerates
  boundary-probing), so the population prior is learned over a
  distribution of owners, not one owner `[E-S1 §11 exp 3]`. Owners'
  preferences should drift slowly within episodes, so adaptation itself is
  tested `[E-S1 §2]`.
- **A shift axis:** `meta.shifted` variants, held-out families, held-out
  generator seeds, and — critically — held-out *phrasings*: the same planted
  cause expressed by different generators/teachers, so we measure
  robustness to surface form, not memorisation `[E-SCH §2, E-S1 §11 exp 4]`.
- **Swarm variants:** multi-agent episodes sharing roots, since SCHEMA is
  single-episode ("nothing is shared across lines" `[E-SCH §6]`) and level 5
  needs cross-agent structure to train on. `[R]`
- **Label hygiene:** every downstream consumer uses `model_view`; `meta`
  and `label` never touch features `[E-SCH §5]`. Enforce by construction:
  the feature factory accepts only model_view output. `[R]`

### 6.2 The four label sources, mapped to factors

| Factor | Label source | Why |
|---|---|---|
| evidence | planted causes (exact) + counterfactual replay | ground truth for "why" is the rarest thing, and we produce it `[E-S1 §7]` |
| reasoning | planted coherence violations + replay | same |
| objective | book replay vs mandate `[E-SCH §2]` | exact in simulation |
| owner | simulated owners first, then review queue + audit slice `[E-S1 §11 exp 3, E-S1 §2]` | the only factor with a real ground truth: the owner's own answer `[E-S1 §2]` |
| unexplained | conformal abstention + ensemble disagreement | never trained to be zero `[E-S1 §4, R]` |

### 6.3 Volumes

`[R-est]` Episodes are small JSON objects; the plan starts at 10⁴ and scales
to ~10⁶ episodes (CPU generation, cheap). Reader labels: 10⁶–10⁷ short
fields from the generator, of which the adversarial slice — the only part
needing DeepSeek calls — is ~10⁵ (hours of API time, modest cost). Owner
simulation: 10³–10⁴ latent owner profiles × 10²–10³ decisions each.
Counterfactual replays: batch CPU/GPU, budgeted per experiment, since
AgenTracer-class evidence says replay labels are what let small students
match frontier attribution `[E-relay, E-S1 §7]`. All numbers to be replaced
by measurement at stage 1. `[R-est]`

### 6.4 Adversarial data via a delegation constitution

A written list of what owners do and do not delegate, used to generate
adversarial cases — the Constitutional Classifiers method, which survived
~3,000 hours of red-teaming without a universal jailbreak `[E-relay, E-S1
§7]`. The constitution is also *product*: it is the reviewable artefact an
owner or auditor reads to know what System One was trained to refuse.
`[R]`

---

## 7. Evaluation

### 7.1 Splits — the part that decides credibility

Hold out along four axes, and report every metric on every split
`[E-S1 §11 exp 4]`:

1. **Attack families** (unseen causes/phrasings): does `poisoned_note`
  detection survive instructions written by a different generator?
2. **Simulator settings and seeds** (unseen worlds).
3. **Time / regime** (drifting owners and markets within-episode).
4. **Surface form**: option reorder, negation of the typed question, and
  paraphrase of identical planted causes `[E-S1 §11 exp 4]`.

Additionally a **live calibration monitor** on every served model: streaming
ECE and conformal coverage, because the wrapper's guarantee holds only while
new data resembles the calibration data `[E-S1 §7]`. When coverage drifts,
thresholds tighten automatically and a human is paged — never loosened
automatically. `[R]`

### 7.2 Metrics per level

| Level | Primary metric | Kill-relevant |
|---|---|---|
| 1 Signal | instruction/hype classification AUPRC per family; false-flag rate on hard negatives `[E-SCH §4]` | — |
| 2 Thesis | Brier, ECE, conformal coverage; false-hold rate on hard negatives | ECE ≤ 0.05 in-distribution after recalibration; ~0.10 under shift `[E-S1 §11]` |
| 3 Action | order-path p99 (µs–ms); zero model calls; fail-closed in every fault test | any loosen fails CI `[R]` |
| 4 Trajectory | **lead time vs the deterministic monitor at matched false-hold rate, on held-out families** | must beat the monitor or not ship `[E-S1 §11]` |
| 5 Swarm | common-root recall at fixed false-cap rate | — |
| 6 Book | owner agreement on proposals | shadow mode `[E-S1 §11 exp 5]` |
| Attribution | rank of the true cause among weighted causes; credit split vs `label.cause_refs` `[E-SCH §2]`; compare agent explanation vs attention traceback vs counterfactual replay, with costs `[E-S1 §11 exp 2]` | — |

### 7.3 The decisive comparison

The question that decides everything is the vision's experiment 1: **the
graph without a model** — do the code-only shapes (drift, herd root, loop,
broken provenance) beat the existing detectors (style distance, CUSUM,
root-source counting, loop windows) `[E-S1 §3, E-S1 §11 exp 1]`? Only if the
graph adds value does anything in §4 deserve to be trained on it. And the
models' own value is then measured *on top of* the code monitor, on the
residual: semantic causes, lead time, owner-fit. `[R]`

### 7.4 Shadow mode before any authority

Simulated owners first `[E-S1 §11 exp 3]`, then real reviewers in shadow
`[E-S1 §11 exp 5]`, then a live pilot where System One holds but humans
still see everything. Graduation between these states is by the kill
criteria, not by calendar. `[R]`

### 7.5 Attribution honesty checks

- Charge the agent only for what the agent did: infrastructure-caused
  failures must not land on the agent — a judge that sees only the agent
  blamed it in 100% of such cases `[E-relay, E-S1 §4]`. So episodes include
  broker-fault and stale-data failures labelled as such. `[R]`
- The unexplained bucket must be non-zero on some episodes; a scorer that
  explains everything is lying `[E-S1 §4]`. Test: adversarial episodes
  whose causes are outside every trained family must land in abstain, not
  in confident endorsement. `[R]`

---

## 8. Runtime and serving at scale

### 8.1 Three planes

- **Order plane (laptop-class CPU, µs–ms):** one process, in-memory verdict
  cache, hash lookups, arithmetic, per-thesis turnover/fee caps
  `[E-S1 §5]`. No network calls, no model calls, no allocations on the hot
  path. Failure semantics: hold. `[R]`
- **Judgement plane (CPU 50 ms + GPU 300 ms):** thesis events are rare
  relative to orders — the flight-plan pattern: judge once, pass a thousand
  orders in microseconds `[E-S1 §13]`. CPU scorer co-located with the
  harness; GPU reader served from one A6000 with batching.
- **Batch plane (nightly, APIs allowed):** book review (L6) with DeepSeek
  and the hosted decision model `[E-BRIEF, R]`; counterfactual replays;
  conformal recalibration; retraining; audit-slice rollups.

### 8.2 GPU allocation on the two shared A6000s

`[R]` Card 1: the reader service (small encoder, batch ≤8, fp16/int8;
utilisation will be low, so co-locate trajectory-embedding and swarm
clustering). Card 2: training jobs (stage-1/2/3 runs; LoRA fine-tunes are
hours per run `[E-S1 §12]`). Both shared with others: run under cgroups,
batch jobs preemptible by the reader service, and the whole judgement
plane degrades to *code-only + hold-more* when GPUs are unavailable.
Training throughput is a convenience; serving is a safety property. `[R]`

### 8.3 Scaling properties, honestly

- The expensive component is the **harness**, not the models: recording the
  graph on every tool call and memory access `[E-S1 §3]`. That cost is per
  agent-step, O(1) amortised with incremental features, and it is the price
  of the entire approach — without the sensor there is no System One
    `[E-S1 §9]`.
- **Horizontal scale is trivial for the models** because the scorer is
  stateless over episodes (ids need only be unique within an episode
    `[E-SCH §6]`); state — owner posteriors, verdict caches, conformal
  thresholds — is small and replicable. `[R]`
- **The flywheel is the scale plan:** more owners → more labels → better
  population prior → fewer holds → more owners `[E-S1 §10]`. Serving cost
  per owner is near-constant (a few KB of owner state), so the marginal
  cost of the flywheel is API-free. `[R]`
- **What will not scale:** per-episode frontier-API calls (cost and egress);
  human escalation volume (conformal thresholds exist to bound it: the
  abstain band has a stated error budget, so escalation volume is a
  *chosen* number, not an accident). `[R]`

### 8.4 External dependencies, contained

DeepSeek and the hosted decision model `[E-BRIEF]` are used only where a
1-second-plus latency is acceptable: escalation review, nightly book
review, offline distillation and replays. Both may be absent at any
moment; every path that touches them has a code-only fallback that
*tightens* (escalations go straight to the human; book review proposes
nothing without API support). Episode data sent to external APIs is
synthetic-only by policy; real-owner data stays on our machines. `[R]`

---

## 9. Build order

Each stage has an exit gate. A stage that fails its gate stops the line;
that is the point of gates `[R]`. Stage costs follow the vision's programme
`[E-S1 §12]`.

| Stage | Build | Compute | Exit gate |
|---|---|---|---|
| 0 | Harness records the typed graph in runtime and arena; typed thesis record defined | engineering | an episode replays byte-identically; every SCHEMA §6 invariant enforced at record time |
| 1 | **Code-only detector**: bands, quotes, facts, signatures, invalidation triggers, plus the §1.1 table; deterministic baseline scored on held-out families | CPU | beats the existing detectors (style distance, CUSUM, root counting, loop windows) `[E-S1 §11 exp 1]`; if the graph adds nothing, stop `[E-S1 §11]` |
| 2 | Feature factory + factor heads (LR, GBT) + per-factor calibration + conformal wrapper; simulated owners | CPU + a little GPU | on held-out families: lead time over stage 1 at matched false-hold; ECE ≤ 0.05 in-distribution `[E-S1 §11]` |
| 3 | Reader: frozen trunk + heads; adversarial slice via DeepSeek + delegation constitution; hard-negative tuning | GPU hours | false-flag rate on SCHEMA §4 negatives within budget at ≥ stage-2 recall on `vague_hype`, `poisoned_note` |
| 4 | GNN + full attribution: code decomposition, Shapley, replay harness | GPU days | attribution ranks the planted cause (`label.cause_refs` `[E-SCH §2]`) better than the agent's own explanation does `[E-S1 §11 exp 2]` |
| 5 | Owner adapter online; audit slice live; interruption bandit | CPU | on simulated owners: fewer questions at equal or better endorsement accuracy than fixed thresholds `[E-S1 §11 exp 3]` |
| 6 | Trajectory (L4) and swarm (L5) models on accumulated streams | CPU/GPU | held-out-family lead time over stage 2; swarm common-root recall at fixed false-cap rate |
| 7 | Shadow mode with real reviewers | partners, time | predictions match reviewer decisions at stated coverage `[E-S1 §11 exp 5]`; no loosening event in the entire corpus |
| 8 | Live pilot, tighten-only, full audit trail | — | review after N episodes against all kill criteria `[E-S1 §11]` |

Sequencing logic: the code stage is both the product's floor and the
comparator every later stage must beat `[R]`; the reader comes after the
scorer because semantics is the smaller slice of the cognitive core (§1);
RL-scale effort never appears — stage 5's bandit is the only place
gradient-through-decisions exists at all `[R]`.

## 10. Risks, ranked

1. **The simulator-reality gap.** Every label is synthetic; a student can
   learn generator quirks, not causes `[R]`. Mitigations: multiple generator
   families and teachers; the constitution's adversarial slice; held-out
   phrasings as a first-class split (§7.1); shadow mode with real reviewers
   before any authority `[E-S1 §11 exp 5]`. Residual risk is real and is
   *the* reason the abstain band exists. `[R]`
2. **Calibration under shift.** Best known: 0.03 in-domain → 0.21 out
   `[E-S1 §11]`; our stretch is ~0.10 `[E-S1 §11]`. Mitigations: SFT first
   `[E-S1 §7]`, heterogeneous ensembles `[E-S1 §6]`, per-factor
   calibration, conformal wrapper with live coverage monitoring, and the
   audit slice for off-policy reality checks `[E-S1 §2]`. If we miss 0.10
   and report it, that is a finding; if we miss it and do not report it,
   that is the kill `[E-S1 §11]`. `[R]`
3. **The code monitor is already very good.** On SCHEMA's causes it is
   exact `[E-SCH §3]`. If models cannot beat it on lead time, semantics
   and owner-fit, they do not ship — and the honest outcome may be "System
   One is a superb deterministic control plus an owner model". That is a
   smaller product than the vision, not a failed one. `[R]`
4. **Injection into the reader.** Quarantined fields are the control
   `[E-S1 §6]`, but quarantining is engineering discipline that can rot.
   Mitigations: the reader never emits verdicts or free text, only factor
   features `[R]`; property tests that inject known payloads into every
   field the reader touches; no generation on served paths (§4.3). `[R]`
5. **The harness is a single point of failure.** No harness, no graph, no
   System One `[E-S1 §9]`; it is also a runtime dependency of the product,
   so its p99 becomes the system's floor. The harness must be the
   best-tested component in the codebase. `[R]`
6. **External API dependence.** Availability, cost, and data egress
   (§8.4). Contained by construction — every dependent path has a
   tighten-only fallback. `[R]`
7. **Owner-model abuse and drift.** A malicious or careless owner feeding
   labels could poison the population prior; strong shrinkage bounds the
   damage (§5.4). Slow genuine owner drift is *expected* and is part of the
   design `[E-S1 §2]`. `[R]`
8. **Compaction losing the invalidation condition.** Agents' summaries drop
   the exit rule long before the position `[E-S1 §8]`; System One judges
   against the records, never the agent's memory of them — the thesis
   record and mandate live outside agent context entirely. This must be an
   invariant test, not a convention. `[E-S1 §8, R]`
9. **Activity optimisation by the agent.** Agents optimise the visible
   proxy; scoring an agent on orders placed would recreate the failure
   System One exists to catch. Score endorsement rate and attribution, and
   never score activity `[E-S1 §8]`. `[R]`
10. **The name.** "System One" collides with at least one vendor claim;
    keep it internal, run the trademark search before anything public
    `[E-S1 §11]`. `[E-relay]`

---

## 11. Direct answers to the founder's questions

**1. Where will the most potential lie — LLMs, classical ML, custom-modified
decision models, a proper ML model, policy distillation?**

Ranked: **code on the typed graph first** (certain, immediate, exactly the
five arithmetic causes), **policy distillation second** (the semantic causes
and the owner factor, at the best gain-per-post-training, because the
simulator plants exact labels and the student is small enough to serve
anywhere), **the provenance GNN third** (the one architectural bet worth
making, because the judged object is a graph), **classical tabular models
as the permanent backbone** (calibration, CPU, auditability), and **LLMs
last — but offline**, where their quality is unconstrained by our latency
budget: they are the data factory's paraphraser, the red-team, and the
escalation reviewer. The inversion to hold onto: the better the LLM, the
more it belongs *behind* System One, not inside it. `[R]`

**2. The cognitive core, ahead of general next-token prediction?**

The core is six capabilities (§1.1): mandate arithmetic; provenance and
signature logic; thesis lifecycle including typed invalidation;
instruction-vs-evidence classification of notes; hype-vs-fact
classification of claims; and the owner's endorsement beyond the written
contract. None of them requires general world knowledge, and SCHEMA's
machine-readable `facts` mean even the numeric reading is mostly already
done for us `[E-SCH §2]`. A general next-token model is the expensive way
to approximate a pocket calculator plus two text classifiers plus a
preference model. `[R]`

**3. Which layers, architectures, model types, paradigms, learning
methods — traded against post-trainability and customisability?**

Layers: frozen pretrained trunk + small trained heads for the reader
(unfreeze last layers or LoRA only on evidence); shallow standard models
(GBT, 2-layer GNN, penalised LR, k-NN) for the scorer; hierarchical
Bayesian for the owner. Paradigms: supervised learning with proper scoring
rules; Bayesian online adaptation; conformal risk control for the
guarantee; RL restricted to the interruption bandit (§5.3). Customise the
**interface** (typed graph in, factorised calibrated probability out), not
the **trunk** (§4.4) — interface surgery keeps every post-training tool
standard, which is exactly what makes later customisation cheap. `[R]`

**4. Minimum post-training for maximum gain?**

Zero, then only where measurement demands it: stage 0 ships code; stage 1
trains heads on features (days of CPU); stage 2 trains reader heads (hours
of GPU per run, as the vision notes fine-tuning is cheap
`[E-S1 §12]`); stage 5's bandit is the only decision-gradient learning,
and its budget is measured before it is spent `[E-S1 §12]`. The large-model
instinct is inverted: because the served models are 10²–10⁶ parameters plus
a frozen 100–400M trunk, serving at scale is never the constraint; the
constraint is label quality, and labels are manufactured, not annotated
(§6). `[R]`

---

## 12. What I would cut first, and what is still open

**Cut order, if forced** `[R]`: the GNN (the scorer ensemble survives
without it); the trajectory GRU (windowed GBT first); the hosted decision
model (DeepSeek plus code covers L6); RL entirely (a fixed threshold with
the audit slice is a fine v0 interruption policy). **Never cut**: the
harness graph recorder; the verdict cache and the code-only order path; the
conformal wrapper; the audit slice; the fail-closed tests. These five are
the product; everything else is fit quality. `[R]`

**Open questions I could not settle from the two documents:**

1. What exactly exists today — the baseline in JUDGEMENT.md is referenced
   `[E-S1 header]` but not in this folder, so I could not compare against
   its measured numbers. Stage-1 gates may need re-baselining against it.
2. Real reviewer throughput and owner interruption tolerance — the numbers
   the interruption policy needs `[E-S1 §2]`; instrument them in shadow
   mode, do not guess them.
3. Whether the live harness's documents can carry a `facts`-equivalent
   machine-readable layer the way SCHEMA's documents do `[E-SCH §2]` —
   the entire code-first design leans on it. If live inputs are text-only,
   the reader's role grows substantially, and with it the reader's
   adversarial surface. This is the most consequential unknown in the
   blueprint.
4. Multi-agent episode format for swarm training (§6.1) — schema work, not
   model work, but it gates level 5.

*End of blueprint.*

