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

---

## 2026-11-20: the architecture, established (D11–D19)

The visual map is [ARCHITECTURE_MAP.html](ARCHITECTURE_MAP.html). Rules R1–R8 for the why graph are defined there. R2, R3, R5, R6 and R8 are new and go to the lab as T14b.

### D11. Hybrid cascade (supersedes D10)
- **Status:** active
- **Decision:** code and the why-graph engine decide formal truths; one self-hosted decision model reads evidence; a monotone combiner and conformal risk control give allow, hold or ask; a tighten-only judge takes at most 15% of actions; a per-owner adjustment sits on top.
- **Why:** G1 shows a self-hosted reader matches the hosted one; code already carries the formal truths; open-ended judging does not beat the majority answer.
- **Would reverse it:** no learned reader beats code only by ≥ 0.03 coverage on CS-1000's evidential cells (ship code plus calibration), or the judge adds < 0.10 recall on novel families (drop the judge).

### D12. Clef-flash 9B is the hot-path reader
- **Status:** active
- **Decision:** frozen, calibrated, then head-trained. The hosted reader stays only as a shadow comparator. The larger G1 winner (Clef 27B or Karpo 31B) is the escalation judge and the teacher.
- **Why:** G1, shifted split: hype 0.993, false authority 0.919, support gap 0.990, against the hosted 1.000, 0.924, 0.998. Within 0.02 on every question, with no outside dependency.
- **Would reverse it:** a larger sibling beats it by > 0.02 after calibration on G2 or CS-1000 evidential cells (quality first: the big model moves to the hot path), or binding errors stay < 0.80 after head training (build the X6 verifier).

### D13. Monotone boosted trees combine the signals
- **Status:** active
- **Decision:** monotone gradient-boosted trees with TreeSHAP; temperature per reader question; Mondrian conformal risk control per action class at α = 0.05. The EBM stays as an audit comparator.
- **Why:** the trees are monotone by construction and kept calibration under shift (ECE 0.003 against the EBM's 0.08 in T10).
- **Would reverse it:** the EBM beats the trees by > 0.02 AUROC or 0.03 ECE on the unseen worlds (X1).

### D14. The agent's words are hypotheses, never evidence
- **Status:** active; not built
- **Decision:** the recorder turns every factual sentence in the agent's rationale into a claim node. An agent note or claim with no document anchor starts at trust 1, not 2. Citing its own earlier note cannot raise a claim's trust; a claim whose every root is agent-authored is "self-grounded".
- **Why:** the agent's reasoning otherwise becomes its own evidence: a thought written into memory at t = 5 reads as confirmation at t = 9.
- **Would reverse it:** the rule holds more than 1 in 100 clean actions on CS-1000 and the unseen worlds, and anchoring at the harness cannot fix it.

### D15. Two-channel why graph, proof status and the decisive-claim gate
- **Status:** active; T14b builds it
- **Decision:** trust and fidelity both propagate by minimum. Each claim gets a proof status: proven, supported, unproven, reinterpreted, contradicted or tainted. The decisive claim must be proven or supported, for every action type (T14 checked authority only on buys). Hotspots are ranked by exposure × (1 − min(trust/4, fidelity)).
- **Why:** taint alone misses a trusted quote whose meaning was changed, and misses agent reasoning turned into evidence.
- **Would reverse it:** the gate adds no recall over T14's taint gate on CS-1000 and the red team at equal false holds.

### D16. Readers see evidence cards, not prose
- **Status:** active
- **Decision:** a reader gets the claim, the quote, nearby text, matched facts and trust metadata. Agent and third-party text reaches a model only as quoted data.
- **Would reverse it:** experiment R shows raw text beats the structured package by > 0.03 on the same model.

### D17. The judge reasons through checks
- **Status:** active
- **Decision:** escalations go to the big decision model with evidence cards. A reasoner from another family than the data authors proposes checks; code runs them; only check results and the model's typed score count. The verdict is parsed to a fixed value and can only tighten.
- **Would reverse it:** a plain chat-model judge (B6) beats it by > 0.05 on the escalated slice; then distil that judge into the reader.

### D18. Owner adaptation by partial pooling
- **Status:** active
- **Decision:** a per-owner offset pooled toward the population, plus per-owner conformal. It loosens only within the signed mandate, from the owner's own signed decisions. In-context tabular learners stay research (licence, untested under shift).
- **Would reverse it:** a commercially licensed in-context learner beats the offset by ≥ 0.03 AUROC at k = 10 (X4).

### D19. Training order
- **Status:** active
- **Decision:** calibration, then head training (contrastive minimal pairs, multi-task), then LoRA only if it adds ≥ 0.03, then distillation only for latency. No RL on the verdict, no full fine-tuning, nothing from scratch.
- **Would reverse it:** CS-1000 shows a gap none of these closes. RL from verifiable rewards is then allowed for the check proposer only.
