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

### D7. One GPU, approval-gated, as its own campaign
- **Date:** 2026-11-19
- **Status:** active
- **Decision:** GPU work runs through the founder's Codex lab chat and job controller, as a campaign separate from the robotics campaign. It uses one A6000 at a time, with weights and data staged in advance. The founder approves the campaign and its GPU-hour cap.
- **Why:** That machine is shared with other students, jobs there are network-isolated, and the controller requires a protected approval file.
- **Would reverse it:** dedicated compute.
