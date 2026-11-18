# Decisions

Only the lab lead writes here, and the founder can overrule any entry. A decision is never edited after the fact: a new entry supersedes an old one by number.

Every entry states **what would reverse it**. That is the exit condition, and it is the part a summary loses first.

---

### D1. The target is the owner's endorsement, not trade quality
- **Date:** 2026-11-19
- **Status:** active
- **Decision:** System One predicts the probability that this owner would endorse this thesis or action, given what the agent legitimately knew. It does not predict returns.
- **Why:** Fast judgement is only trustworthy where the environment is regular and feedback is quick (Kahneman and Klein, 2009), and markets are neither. Endorsement has real ground truth, the owner's approve or reject, and that feedback is fast.
- **Would reverse it:** owners' approve and reject decisions prove so noisy or inconsistent that a model cannot beat a per-owner base rate, measured on held-out reviews.

### D2. System One can only tighten
- **Date:** 2026-11-19
- **Status:** active
- **Decision:** Its outputs can hold, shrink a budget or escalate. They can never loosen a hard limit. Hard refusals come only from code.
- **Why:** This makes it deployable before it is trusted, and deployment is what starts the data flywheel.
- **Would reverse it:** never as a product rule. Within research, a loosening variant may be studied offline.

### D3. Provenance is recorded at decision time, never reconstructed
- **Date:** 2026-11-19
- **Status:** active
- **Decision:** The harness records the why-graph (sources, theses and the orders they cause) when the action happens.
- **Why:** Agents' own explanations omit what drove them most of the time. Finding a failure's cause after the fact reaches only about 33–50%.
- **Would reverse it:** a post-hoc method that matches recorded provenance on our planted-cause tests.

### D4. Judge theses; check orders in code
- **Date:** 2026-11-19
- **Status:** active
- **Decision:** The model judges once per thesis, in seconds. Each order proves in code that it belongs to a judged thesis. Turnover, fee drag and cancel ratios are checked in code on every order.
- **Why:** This keeps the order path at microseconds and closes the gap where many small orders drain the book.
- **Would reverse it:** a per-order model under 1 ms that beats the code checks on held-out drift.

### D5. Two calibration targets
- **Date:** 2026-11-19
- **Status:** active
- **Decision:** ECE under 0.05 in distribution after recalibration, and about 0.10 under shift.
- **Why:** The best published result goes from 0.03 to 0.21 out of domain, and nothing published reaches 0.05 under shift.
- **Would reverse it:** an experiment that reaches 0.05 under shift, which would raise the bar.

### D6. Research feeds exploration; it is not truth
- **Date:** 2026-11-19
- **Status:** active
- **Decision:** Scouts collect options and mark each one as evidence or claim. Decisions here cite our own tests where possible, and research only where no test is possible.
- **Why:** The founder's direction. Quoting papers to support choices already made is the self-justification failure we design against.
- **Would reverse it:** none. This is how the lab works.

### D8. Sprint S1: prove the core on ground truth we did not write
- **Date:** 2026-11-19
- **Status:** active
- **Decision:** Before building anything else, a short burst tests six claims (C1–C6 in `research/system_one/SPRINT.md`) on worlds written by independent models and on real SEC fund data. Every pass bar is written before the tests run.
- **Why:** The founder asked for tangible, robust proof within days. The 0.97 baseline showed that a world we write ourselves proves little.
- **Would reverse it:** if T01's world cannot be made rich enough to judge, stop and redesign the world before testing any model.

### D9. Division of labour
- **Date:** 2026-11-19
- **Status:** active
- **Decision:**
  - DeepSeek, through OpenCode Go, does the work.
  - Other labs' models write the held-out worlds and the red team, so that the authors are truly independent.
  - Codex Luna (`xhigh`) reviews every round adversarially, in a fresh run.
  - Codex Sol (`high`) answers only escalations that Luna has written down.
  - Haiku audits while the lead is present.
  - A disk-backed runner keeps all of this moving without the lead. The lead reviews at checkpoints.
- **Why:** Claude and Codex usage are both limited and can run out unpredictably. The work must keep a principle to follow while the lead is away.
- **Would reverse it:** if review rounds keep passing work that the lead later finds broken, then reviews move to Sol, or the lead reviews every task.

### D10. System One's architecture: provisional
- **Date:** 2026-11-19
- **Status:** provisional, written by the lead in [ARCHITECTURE.md](ARCHITECTURE.md), which supersedes the delegated T10
- **Provisional choice:** a cascade (architecture C):
  - code for structural checks and attribution;
  - a tournament-chosen reader for each semantic sub-question;
  - a monotone aggregator, either an EBM or monotone boosted trees, chosen by X1;
  - conformal risk control;
  - escalation of uncertain or unusual actions to a strong judge that can only tighten;
  - owner adaptation chosen by X4.
- **What would switch it:**
  - to A alone, if escalation adds less than 0.1 recall on novel families;
  - to the decision model as base reader, if it beats local readers by more than 0.05 AUROC on held-out wording;
  - to fine-tuning a reader, if every off-the-shelf reader is more than 0.10 AUROC below the frontier judge.
- **Original rule, still in force:**
- **Decision:** No model is chosen by habit. Until D10 is written, no weights are downloaded for training, fine-tuned or RL-trained, and nothing is built from scratch.
- **How it gets decided:**
  - T10 explores nine model families, from code with glass boxes through in-context learners, hosted decision models, encoders, probes, small judges, weight-space methods and program synthesis, to cascades.
  - It iterates its top designs against their strongest challengers.
  - It runs the cheapest experiments that separate the final three.
  - The S1 verdict (T07) adds the held-out evidence.
- **Why:** The founder caught a defaulted choice: the first T09 brief staged Qwen and a QLoRA run before any architecture was decided. Every choice here now records its alternatives, and what evidence would flip it.
- **Would reverse it:** n/a. This is a rule of process.

### D7. One GPU, approval-gated, as its own campaign
- **Date:** 2026-11-19
- **Status:** active
- **Decision:** GPU work runs through the founder's Codex lab chat and job controller, as a campaign separate from the robotics campaign. It uses one A6000 at a time, with weights and data staged in advance. The founder approves the campaign and its GPU-hour cap.
- **Why:** That machine is shared with other students, jobs there are network-isolated, and the controller requires a protected approval file.
- **Would reverse it:** dedicated compute.
- **Update, 2026-11-19:** the founder approved testing or deploying any model on that machine, strictly one GPU at a time. T09 provisions it. No GPU operator may type a password: any step that needs one goes back to the founder.
