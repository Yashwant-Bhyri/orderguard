# Training, evaluation and data: the paradigms that fit System One

**2026-11-20, lead.** A companion to [PLAN.md](PLAN.md), which has the decision tree and the training ladder. This note says *how* we learn: which learning paradigms suit a reviewer of agent decisions, how teacher–student learning should work here, how to make the data diverse on purpose, and how to evaluate without fooling ourselves.

---

## 1. Five principles that decide everything else

1. **Learn from verified labels, never from a teacher's opinion alone.** A label comes from code, a verified source, the case author's audited ground truth, or the owner. A model's output is a candidate label until something verifies it.
2. **Learn the boundary, not the average.** The most informative example is a pair that differs in one factor, with opposite labels. Our data should be mostly pairs and twins, not loose examples.
3. **The student sees only what the live system will see.** Anything privileged (the future, the labels, hidden notes) may shape the *teacher*, never the student's inputs.
4. **Diversity is built in, not hoped for.** Every axis we want robustness on is an explicit axis in generation, with quotas and an audit.
5. **No evaluation without a shortcut test.** If a model that does not read can score well, the data is broken, not the model clever.

---

## 2. The learning paradigms, ranked for our use

| # | Paradigm | What it is here | Why it fits | When |
|---|---|---|---|---|
| 1 | **Supervised head training** | Train only the decision model's small readout head on our typed questions (endorse, cause, decisive item, action). The backbone is frozen | Cheap and fast. It keeps the backbone's general reading, and the head learns *our* questions | First, after calibration |
| 2 | **Contrastive learning on minimal pairs** | For each twin pair (decisive item changed, verdict flips), a margin loss pushes the two scores apart. For each invariance pair (paraphrase or reorder), a consistency loss pulls them together | Teaches exactly what matters and what must not matter. This is what fixes binding errors | With 1, as soon as twins are materialised |
| 3 | **Multi-task learning** | One model answers endorse, cause, decisive item, action, period, entity, metric and scope together | Sub-skills such as "which period is this number?" are auxiliary tasks that make the main task easier. Decision models already answer many questions in one pass | With 1 and 2 |
| 4 | **Teacher–student distillation, verified** | Section 3 | A strong but slow judge teaches a fast reader | Once a teacher beats the student by ≥ 0.03 |
| 5 | **Learning with privileged information** | The teacher sees privileged context the student never sees: the case truths, which notes are poisoned, the future. It produces soft targets and evidence pointers. The student learns them from the causal view alone | Lets a teacher be right *for the right reason* and pass that reason down as attribution | With 4 |
| 6 | **Active learning** | Send the founder the items where models disagree most (a committee of readers) or are least certain | Each owner label is expensive. Spend them where they change the model most | From the first CS-1000 batch |
| 7 | **Adversarial data generation** | A red-team model writes new attacks against the *current* reader. The ones that fool it, once labelled by code or verified, join training | The attack surface is open-ended. This keeps the reader honest | After stage 2 |
| 8 | **Curriculum** | Order training from formal checks to single-document evidence, multi-document evidence, long chains and adversarial cases | Stabilises training of the head and the adapters | Stage 3 (LoRA) |
| 9 | **Calibration and conformal prediction** | Temperature per question, then conformal thresholds per action class (Mondrian) | The output is a decision with a stated error rate. It needs this whatever else we do | Always, last step |
| 10 | **Preference learning** | Pairwise learning from owner approvals and rejections ("approved A, rejected B") | Owner adaptation (F11), when real owners exist | Shadow mode |
| 11 | **Reinforcement learning from verifiable rewards** | Only for the *reasoning cascade's check-proposer* (PLAN section 6A). Reward = the checks it proposes catch real issues, verified by code | The reward is exact, so there is no reward hacking through the judge | Phase 3, if the cascade earns its place |
| — | Not for us now: full fine-tuning, RL on the verdict itself, self-generated labels without verification | | | |

---

## 3. Teacher–student learning, done safely

**Who teaches.** The teacher is an *ensemble that is allowed to be slow*:
- code checks (exact, and always right on formal truths);
- the big decision model (Karpo 31B or Clef 27B, after G1);
- a strong reasoner at max reasoning (DeepSeek or Qwen) running the cascade with verified checks;
- for training data only, privileged information (case truths).

**Who learns.** The student is the fast reader on the live path: a 9B decision model (Clef-flash already matches the hosted reader, per G1), and later possibly a small encoder.

**The rules:**
1. **Verified distillation.** Distil the teacher's soft probability only where it agrees with a verified label. Where they disagree, the verified label wins and the item becomes a hard example.
2. **Distil the attribution, not the story.** The student learns *which items are decisive* (a pointer target) and *which sub-checks fail* (multi-task targets). It never imitates the teacher's free-text explanation. Owner explanations are built from attribution (F13).
3. **Different families for teacher, student and data author.** If the same family writes the data, teaches and is graded, it agrees with itself. Mix families on purpose, and report results per family.
4. **Temperature.** Soften the teacher's targets (temperature 2–4) on gray and evidential items. Keep hard targets on formal items, where the answer is exact.
5. **A teacher must earn the role.** It must beat the student by ≥ 0.03 headline coverage on held-out cases, or distillation is just noise.

---

## 4. Diversity by construction

**The axes.** CS-1000's coverage matrix (paradigm section 7):
- owner, assets, persona, regime, theme, difficulty, clutter, length, grounding;
- plus the cross-cutting stressors.

Every training source carries these tags, so we can see what we are short of.

**The multipliers.** One authored case is worth 10–20 training examples:
- **Counterfactual twins:** remove, alter or delay the decisive item, so the verdict flips.
- **Invariance twins:** paraphrase, reorder, rename irrelevant entities, convert units correctly, so the verdict stays.
- **Perspective variants:** the same decision under a different owner or mandate (preference truths).
- **Clutter variants:** the same case at clutter 1, 2 and 3: strip the structured facts, add noise, add duplicates.
- **Attack variants:** the same decision with an injection, a spoofed approval or a laundered source added.

**Real anchors.** Synthetic data can drift away from reality, so real sources keep it honest:
- **XBRL** facts from SEC filings give exact binding pairs: the right value with the wrong period, concept, entity or scope.
- **N-PORT** holdings give real purpose tests.
- **EDGAR** text gives real document length and mess.
- Public financial QA and verification sets give table and numeric reading, after a licence audit (T17).

**Several authors.** At least three model families write cases, each ≤ 40%. The style of any one author must not be learnable as a label cue.

**Deduplication and near-duplicate control.**
- Hash and embedding deduplication across train and test.
- No twin of a test case in training.
- Fictional entities get unique names per split.

---

## 5. Evaluation without fooling ourselves

| Practice | How |
|---|---|
| **Splits by case, not by decision** | Decisions inside a case are correlated. All twins and variants of a case stay in its split |
| **A sealed test** | CS-1000 cases 701–1000, the independent worlds and the red team. Scored only at milestones |
| **Hold out by author family and by time** | Report results on cases written by a family not used in training, and on the latest-dated cases |
| **Bootstrap by case** | Confidence intervals resample whole cases |
| **Shortcut baselines on every set** | Majority, "always hold", surface-only (side, size, position, lengths), and keyword lists. A model's gain is measured over the best shortcut |
| **Estimate label noise** | A blind re-labelling of a sample by another family (as done in T20), with agreement per question. Questions below 0.85 agreement are reported, not ranked |
| **Contamination checks** | Fictional entities, canary strings in the test cases, and memorisation probes for real-filing cases |
| **Per-cell reporting** | Every metric by truth type, failure family, clutter, difficulty, length and author family |
| **Reasoning probes scored by checklist** | Required and forbidden reasoning elements per probe (paradigm section 10) |
| **Learning curves** | Score against the number of training cases (50, 100, 200, 400, 700). If the curve is still rising at 700, we need more data. If it is flat, we need a better model or better features, not more cases |

---

## 6. What this means for the next few weeks

1. **Now:** finish G1 (the self-hosted readers), then calibrate. Fix CS-0001 with `audit_case.py` (shortcuts, editorialising, runnable probes) and regenerate it before CS-0002.
2. **First 50–100 cases:** score every reader zero-shot. Draw the first learning curve with head training on cases 1–50, tested on cases 51–100.
3. **Materialise twins** for every case. Generate XBRL binding pairs. Train head + contrastive + multi-task on Clef-flash 9B (one card, about 18 GB, so it fits beside other users' jobs).
4. **Distil** from the teacher ensemble only when a teacher beats the student by ≥ 0.03.
5. Throughout: active learning picks what the founder labels next, and the red-team loop feeds new attacks.
