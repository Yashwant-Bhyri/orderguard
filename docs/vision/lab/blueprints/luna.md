# System One: build blueprint

## Basis and recommendation

- **[Evidence: `SYSTEM-ONE.md`, §§1–9; `SCHEMA.md`, §§1–5]** System One is intended to estimate whether an owner would endorse an agent action, using a signed mandate and the evidence available at that action's time. Its output may tighten controls; code alone authorizes orders.
- **[Reasoning]** Build it as a compact, owner-conditioned risk judge around a deterministic authority boundary: exact policy checks first, calibrated tabular prediction second, and a small quarantined text reader only where language carries information that typed features miss.
- **[Reasoning]** Do not start with a general LLM, a graph neural network, reinforcement learning, or a custom surgery of a large decision model. The target is narrow, labels are structured, CPU order-path latency is strict, and data quality is the main constraint.
- **[Reasoning]** Use planted failures to learn failure patterns and attribution; use real owner decisions to set endorsement probabilities and calibrate thresholds. Synthetic cause labels are not substitutes for owner preferences.

## Product boundary and functions

- **[Evidence: `SYSTEM-ONE.md`, §§5–6, 9; `SCHEMA.md`, §§2–5]** The owner is the principal; the delegation, contract, theses, documents, notes, claims, actions, and current book form the model's decision context.
- **[Evidence: `SYSTEM-ONE.md`, §§5, 9]** System One may hold an action or shrink a thesis risk budget. It cannot approve an order, expand a budget, change a signed mandate, or override a code check.
- **[Evidence: `SCHEMA.md`, §§2–5]** An action's owner label is `y=0` when endorsed and `y=1` when not endorsed; `meta` and every step label are evaluation-only and must be removed with `model_view` before feature extraction.
- **[Reasoning]** Build the functions below in increasing order of authority and latency; give each a typed result and an audit record.

| Function | Output / effect | Basis |
|---|---|---|
| Contract and state validation | Reject malformed, unsigned, out-of-time, or internally inconsistent state before scoring. | **[Evidence: `SCHEMA.md`, §§1–2, 6]** |
| Signal and memory scrutiny | Trust features, quote/fact consistency, source lineage, and an optional hold flag for suspect roots. | **[Evidence: `SYSTEM-ONE.md`, §§3, 5; `SCHEMA.md`, §§2–3]** |
| Thesis endorsement | A calibrated probability of non-endorsement, cause-risk scores, and an optional reduced risk ceiling or hold. | **[Evidence: `SYSTEM-ONE.md`, §§2, 5–7; `SCHEMA.md`, §§2–3]** |
| Action-to-thesis check | Verify in code that an order is within the still-valid thesis, mandate, and precomputed ceiling; hold on a failed check. | **[Evidence: `SYSTEM-ONE.md`, §§5, 9; `SCHEMA.md`, §§2–3] [Reasoning: attach a bounded validity lease to each cached verdict]** |
| Trajectory and swarm watch | Track drift, repeated causes, loops, and shared evidence roots over time; tighten budgets or request review. | **[Evidence: `SYSTEM-ONE.md`, §§3, 5]** |
| Book and owner review | Detect portfolio-level mismatch and decide when a human review is worth the interruption. | **[Evidence: `SYSTEM-ONE.md`, §§2, 5]** |

## Architecture and authority flow

- **[Reasoning]** Keep four components separately deployable: (1) the order harness and deterministic policy engine, (2) an append-only point-in-time event/why-graph store, (3) an asynchronous thesis/text scoring service, and (4) a training, calibration, and monitoring pipeline.
- **[Evidence: `SYSTEM-ONE.md`, §§3, 9; `SCHEMA.md`, §§1–2]** The harness sees tool reads, memory reads and writes, thesis changes, and typed intents; the schema supplies time, trust, signature, citation, claim, book, and thesis fields. This is the natural place to record causal edges at decision time.
- **[Reasoning]** Store immutable nodes for contract versions, documents, notes, theses, claims, intents, tool results, peer observations, and orders. Store typed edges such as `read`, `cites`, `supports`, `derived_from`, `opens`, and `proposes`; hash source content and retain writer, time, trust tier, and signature state.
- **[Evidence: `SCHEMA.md`, §1 and §6]** A note in `new_notes` is unavailable to the action in the same step, and future documents/notes cannot be cited. **[Reasoning]** Enforce this with one point-in-time resolver shared by feature generation, replay, and serving; never reconstruct availability from a language model's transcript.
- **[Evidence: `SCHEMA.md`, §§2, 5]** `model_view` removes `meta` and labels while retaining the rest of the episode. **[Reasoning]** Make this the only supported training and scoring entry point, then compute versioned features from that view.
- **[Reasoning]** The model API returns data only: `p_not_endorsed`, cause-risk vector, uncertainty/support status, model and calibration versions, and cited graph node IDs. It has no broker credentials, order tool, or API that can increase authority.
- **[Reasoning]** A small policy adapter may translate a score into `continue-to-code-check`, `shrink-ceiling`, or `hold-for-review`; the adapter only applies pre-signed thresholds and monotone reductions. Final order authorization remains a deterministic code path.

## Models: smallest useful stack first

- **[Reasoning]** The main prediction is tabular: a shallow-to-moderate histogram gradient-boosted tree model over contract, book, action, thesis, provenance, and history features. It handles nonlinear interactions in mixed numeric/categorical data, stays small, and can score on the CPU.
- **[Reasoning]** Keep a regularized logistic model as the interpretable baseline and fallback. Start with one boosted model plus the baseline; add an ensemble only if held-out calibration or error reduction is worth its latency and operational cost.
- **[Reasoning]** Add a small owner adapter only after pooled training works: a regularized per-owner intercept first, then a low-dimensional calibration layer when there are enough reviewed examples. Back off to a population prior for new or sparse owners; do not train a full model per owner from a handful of decisions.
- **[Evidence: `SYSTEM-ONE.md`, §§6–7]** The vision proposes numeric graph features, a small model for quarantined text, ensembles, and a conformal wrapper. **[Reasoning]** Treat these as candidates to earn in ablation, rather than requirements for the first release.
- **[Reasoning]** Use a compact pretrained bidirectional text encoder (roughly 100–300 million parameters as an initial search range) for fields such as document text, rationale, claim text, and note text. Its outputs feed small task heads for instruction/spoof detection, semantic support, and text-to-thesis consistency.
- **[Evidence: `SYSTEM-ONE.md`, §6; `SCHEMA.md`, §§2–3]** Agent-written text is a possible injection channel, while the schema provides typed facts, exact quote spans, publisher, trust tier, signature, and citations. **[Reasoning]** Keep exact arithmetic, hash checks, quote matching, permissions, and time checks in code; use the text model only for residual meaning that code cannot reliably type.
- **[Reasoning]** Start with the text encoder frozen and train small heads. If there is enough diverse, reviewed data and the heads plateau, unfreeze with parameter-efficient adapters (for example LoRA) on the encoder's upper blocks. Keep the encoder's vocabulary and general language weights mostly intact; do not train a decoder to generate free-form justifications.
- **[Reasoning]** Do not put a graph neural network on the critical path initially. Compute transparent graph summaries in code—trusted-root share, root concentration across agents, cycles, unsupported paths, thesis age, and exposure contributions—then let the tabular model learn their combinations. Test a relation-aware graph model later only if graph topology adds repeatable held-out value.
- **[Reasoning]** No model is trained from scratch. The available A6000 pair is sufficient for compact encoder adaptation and data generation, but the bottleneck is representative, correctly labeled episodes rather than parameter count.

### Features and targets

- **[Evidence: `SCHEMA.md`, §§2, 5]** Candidate features include purpose and signed sector/position limits; current and post-action exposures; turnover proxy; document trust, age, and source diversity; numeric fact/claim agreement; exact-quote match; note writer/signature/citation status; thesis age/status/invalidation; and action-to-thesis relation.
- **[Evidence: `SYSTEM-ONE.md`, §§3–4; `SCHEMA.md`, §§2–3]** The graph supports features for untrusted-root dependence, shared roots across agents, self-reinforcing loops, broken provenance, and the path from evidence through thesis to order.
- **[Reasoning]** Preserve missingness and provenance explicitly; do not convert “no evidence” into “evidence of safety.” Include owner-level history only as of the action, and prevent the model from inferring future owner choices from later events.
- **[Evidence: `SCHEMA.md`, §§2–5]** Train the primary probability target directly on `y`: `p_not_endorsed` means the probability of `y=1`; use cause and cause references, where label provenance supports them, as separate training-split targets and evaluation metrics, never as model inputs.
- **[Reasoning]** Use a multi-task objective only where labels are trustworthy: endorsement classification on owner decisions, cause classification and graph-node ranking on planted/counterfactual cases, and text support/injection heads on verified examples. Keep task heads separable so synthetic cause learning cannot silently redefine owner endorsement.

## Data, labels, and learning plan

- **[Evidence: `SCHEMA.md`, §§3–5]** The generator can provide exact planted causes (`drift`, unsupported claims, misquotes, hype, poisoned notes, authority spoof, stale theses) and clean hard negatives such as valid adaptation, corrective sells, exact quotes, and factual enthusiasm.
- **[Evidence: `SYSTEM-ONE.md`, §7]** The vision also identifies counterfactual replay and owner review decisions as label sources. **[Reasoning]** Record which source produced each label and never blend them without source-aware weights and separate evaluation.
- **[Reasoning]** Use synthetic episodes to pretrain cause detection, root attribution, and robustness to rare attacks. Use owner endorsement/rejection decisions as the authoritative target for owner-specific calibration and hold policy. A simulator's declared purpose is a useful proxy, not proof of what a real owner endorses.
- **[Reasoning]** For replay labels, change or remove one causal root at a time, replay the same point-in-time state, and label whether the action or endorsement outcome changes. Mark ambiguous or interacting interventions as uncertain rather than forcing a single cause.
- **[Evidence: `SYSTEM-ONE.md`, §2]** Reviewing held actions supplies rapid feedback but creates selection bias. **[Reasoning]** Add a small, randomized, owner-approved audit sample of low-risk allowed actions; log its sampling probability and use propensity-aware evaluation so the model is not calibrated only on held cases.
- **[Evidence: `SCHEMA.md`, §5]** The full episode includes evaluation-only labels and `meta`. **[Reasoning]** Strip these before every split-specific feature transform; keep episode, owner, cause family, seed, and time grouping metadata in a separate evaluator so related actions cannot leak across train and test.
- **[Reasoning]** Split by whole episode and owner, with later time periods and entire failure families held out. Include a shifted set and a clean set rich in hard negatives; report results per owner, family, text source, and risk level.
- **[Reasoning]** Train in this order: (1) deterministic features and logistic baseline, (2) boosted tabular predictor, (3) calibrated owner adapter, (4) frozen text encoder plus heads, (5) selective adapter fine-tuning if needed, and (6) distillation/ensemble only if measured benefit remains.
- **[Evidence: `SYSTEM-ONE.md`, §7]** The vision proposes supervised fine-tuning before bounded proper-scoring RL and cautions that RL may sharpen rather than create detection skill. **[Reasoning]** Skip RL in the first versions: supervised proper losses directly fit the observable target and make data and calibration failures easier to diagnose. Reconsider bounded Brier-reward policy optimization only after stable owner labels, locked evaluation, and evidence that supervised training has plateaued.
- **[Evidence: `BRIEF.md`]** The allowed model sources are open-weight models on two RTX A6000 GPUs, DeepSeek through an API, and an external hosted typed decision model with roughly one-second calls. **[Reasoning]** Use hosted models offline or on the slow thesis/review path to propose comparisons and soft targets; never depend on their availability or opinions for per-order authority. Distill only after checking teacher disagreement against actual labels.

## Evaluation and release gates

- **[Evidence: `SYSTEM-ONE.md`, §11]** The proposed kill criteria include beating the deterministic monitor on lead time at the same false-hold rate, in-distribution calibration error at or below 0.05 after recalibration, reporting shifted calibration (with about 0.10 as a stretch target), and no case where a decision was loosened.
- **[Reasoning]** Treat those as explicit release gates for expanding authority to new owners or causes; they are targets, not guarantees. Report confidence intervals and owner/family slices so aggregate scores cannot conceal a weak segment.
- **[Reasoning]** Compare, on identical held-out episodes: deterministic rules alone; logistic baseline; boosted structured model; structured plus text; and any ensemble or graph model. Include ablations for provenance, owner adaptation, and text to establish which parts earn their complexity.
- **[Evidence: `SYSTEM-ONE.md`, §§2, 11]** Endorsement is a repeated yes/no label and the vision names Brier score, calibration, false holds, and lead time as meaningful outcomes. **[Reasoning]** Report Brier score, log loss, reliability plots, calibration error, precision/recall and false-hold rate at each proposed threshold, review rate, and decision lead time.
- **[Reasoning]** Report cause macro-F1/AUPRC and root-node Recall@k against planted causes and counterfactual replays. Report exposure-weighted attribution error separately from endorsement classification, since a good risk score need not identify the right cause.
- **[Reasoning]** Evaluate selective behavior: risk and calibration among actions passed to code, held for review, or outside support. Test threshold stability by owner, family, time, text source, and distribution shift; report randomized-audit estimates with their sampling weights.
- **[Evidence: `SCHEMA.md`, §5]** Labels and `meta` are evaluator-only. **[Reasoning]** Add a leakage audit that confirms no features or model inputs can recover label, cause, author, seed, family, or shifted flags. This is a release check, not a feature-learning objective.
- **[Evidence: `SYSTEM-ONE.md`, §11]** The proposed research sequence compares graph features with existing detectors, attribution methods, simulated owners, held-out shifts, and real-owner shadow decisions. **[Reasoning]** Run those comparisons before using predictions to hold real orders; first operate in shadow mode and have owners judge sampled predictions.

## Runtime and serving

- **[Evidence: `BRIEF.md`]** The order-path budget is p99 ≤50 ms per thesis for code checks plus scorer on a laptop-class CPU; text reading is p99 ≤300 ms on GPU.
- **[Reasoning]** Keep all exact mandate/book/quote/time/provenance checks and the structured scorer on CPU. Batch or asynchronously encode newly arrived text on GPU at document/thesis ingestion, then cache versioned embeddings and thesis verdicts before an order references them.
- **[Reasoning]** On an order, read the latest valid thesis verdict and compact CPU features; run deterministic checks; intersect all applicable ceilings; then either hold or hand the proposal to the authorization code. Do not call a hosted model on this path.
- **[Evidence: `BRIEF.md`]** A hosted typed decision call takes about one second. **[Reasoning]** Reserve it for offline teacher comparisons, low-volume escalations, or owner-review preparation; timeout or disagreement can only add uncertainty/hold, never grant authority.
- **[Reasoning]** Version the mandate, feature schema, graph snapshot, model, calibration map, threshold policy, and verdict together. Invalidate cached verdicts when a signed contract, relevant thesis status, book exposure, or cited evidence changes.
- **[Reasoning]** Track p50/p95/p99 latency separately for CPU scoring, GPU text encoding, graph assembly, and queue delay, plus stale-cache rate, timeout rate, hold rate, calibration drift, missing provenance, and owner overrides.
- **[Reasoning]** Define a monotone fallback: if a required current verdict is absent, stale, or out-of-support, code may keep its independent hard limits but must not use that absence to undo an existing hold or enlarge a ceiling. Route risk-increasing proposals to review; permit only actions that deterministic policy independently classifies as risk-reducing under a predeclared rule.

## Build order

1. **[Evidence: `SYSTEM-ONE.md`, §§9, 12]** Instrument the harness and arena first; the vision identifies the harness as both security boundary and source of the decision-time graph.
2. **[Evidence: `SCHEMA.md`, §§1–2, 6]** Implement the point-in-time typed state builder, signature/contract verification, deterministic book replay, and validator-compatible episode writer. Keep this layer independent of learned predictions.
3. **[Reasoning]** Define episode/owner/time/family splits, label-source lineage, and the leakage audit before fitting anything; freeze a simple logistic baseline and current deterministic monitor for comparison.
4. **[Evidence: `SYSTEM-ONE.md`, §11]** First test graph-derived shapes in code against existing detectors and planted causes. **[Reasoning]** If the graph does not improve detection or attribution at matched false-hold rate, fix instrumentation or drop the added graph complexity.
5. **[Reasoning]** Train the boosted structured model, calibrate its pooled estimate, then add sparse-owner adaptation and validate with held-out owners and later time periods.
6. **[Reasoning]** Add the frozen text encoder and heads only for measurable residual error in claims, notes, or rationale; keep exact claim arithmetic and quote verification in code.
7. **[Evidence: `SYSTEM-ONE.md`, §§7, 11–12]** Counterfactual replay, teacher comparison, ensembles, conformal control, and owner shadow mode are candidate later stages. **[Reasoning]** Introduce each behind an ablation and release gate, not as a prerequisite architecture.
8. **[Reasoning]** Move from offline evaluation to shadow mode, then to reversible holds and budget reductions for a small owner cohort. Expand only after calibration and latency remain within gates; keep a versioned rollback to the deterministic baseline.

## Main risks and responses

- **[Evidence: `SCHEMA.md`, §§3–5]** Synthetic causes are explicitly planted and labels are evaluator-only. **[Reasoning]** A model may learn the generator's shortcuts or infer the declared family; split by generator family/seed, remove metadata, and validate on real-owner decisions before relying on synthetic performance.
- **[Evidence: `SYSTEM-ONE.md`, §§1–2]** Explanations can omit what influenced an agent, and reviewed actions are a selected sample. **[Reasoning]** Attribute from instrumented graph and intervention data, audit a random allow-sample, and never treat free-form rationale as ground truth.
- **[Evidence: `SYSTEM-ONE.md`, §§1, 3, 6; `SCHEMA.md`, §3]** Inherited context, injected memory, and poisoned inputs can corrupt decisions. **[Reasoning]** Quarantine agent text, verify roots and signatures in code, retain node-level evidence, and make out-of-support inputs trigger review rather than a confident pass.
- **[Reasoning]** A harness bypass or incomplete event capture makes the graph falsely reassuring. Require source coverage and provenance completeness indicators; a missing path should lower confidence and tighten, not be imputed as a clean history.
- **[Evidence: `SYSTEM-ONE.md`, §11]** Calibration can degrade under adversarial shift, and conformal validity depends on data resembling calibration data. **[Reasoning]** Monitor drift by owner and cause family, recalibrate only on an approved recent window, and keep hard code limits effective when the model is uncertain.
- **[Reasoning]** Owner preferences may change or be inconsistent. Preserve the signed mandate as the authority floor, estimate owner-level adaptation conservatively, surface disagreement, and ask rather than silently rewriting the purpose.
- **[Evidence: `BRIEF.md`]** The GPUs are shared and limited to two A6000s, while order checks have a CPU latency budget. **[Reasoning]** Keep GPU inference off the per-order path, bound text length/batching, and use model-size/queue limits so contention cannot stall authorization.
- **[Reasoning]** More model complexity can impair calibration and auditability. Ship the simplest model that beats code-only checks on held-out data; keep a change log for every threshold, model, feature, and calibration update.

## Exit condition

- **[Reasoning]** System One is ready for a narrow production trial when point-in-time inputs are enforceable, graph coverage is measured, no output can authorize or loosen, held-out owners and families meet agreed error/latency gates, and operators can explain every hold by citing typed records.
- **[Evidence: `SYSTEM-ONE.md`, §11]** The project vision says not to ship beyond baseline if kill criteria fail, calibration under shift is unreported, or any decision loosens. **[Reasoning]** If those conditions fail, retain the deterministic baseline and continue collecting shadow data rather than increasing the model's role.
