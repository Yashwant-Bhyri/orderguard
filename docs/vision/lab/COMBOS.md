# Which combination of parts System One should be: the lead's verdict, and the bench that will settle it

Written by the lab lead on 2026-11-19, after the deep-research pass [System One functions and model combos](../reports/System%20One%20functions%20and%20model%20combos.md). It updates [BLUEPRINT.md](BLUEPRINT.md) where the evidence disagreed with it. Its last section is what the lab now runs.

---

## 1. The verdict in six lines

1. **Most of System One is exact code and classical statistics.** Only two duties need a language model: "does this source support this claim?" and "is this wording manipulative?".
2. **For those two, start by probing a frozen, cut-down open decoder** (S2 below): read its middle layers with small heads. This pairing has the most evidence, is the cheapest to retrain, and answers every reading question in one pass.
3. **Train only when a measurement says so.** Order: frozen heads, then LoRA (only if it adds ≥ 0.03 AUROC on unseen worlds), then distillation (only if serving cost demands it). No RL.
4. **The real threat is evasion, not loosening.** Tighten-only stops text from *loosening* a decision. An attacker's actual goal is to get a bad action through *without raising any signal*, and adaptive attackers beat almost every published text classifier. So the structural defence comes first: **taint propagation** through the why graph. Anything that traces back to untrusted text inherits its low trust.
5. **Our biggest methodological risk is one model family doing everything.** DeepSeek generates the data, writes the test worlds, and would be teacher and judge. Agreement numbers get inflated, so the judge and at least one test world must come from other families.
6. **Data difficulty matters more than which stack we pick.** Our reference world scores every model at 0.97–0.99 AUROC, which means it is too easy. Keep only the generated cases the current best model gets wrong, and add hard cases written by people.

---

## 2. Your ideas, graded honestly

You asked me to act as the engineer. Here is each idea you raised, and where it stands.

| Your idea | Verdict | What to actually do |
|---|---|---|
| "Is it LLMs, or ML?" | **Right question; the answer is "split by duty".** | Code for the ~41 exact checks. Classical ML for combining, calibrating, adapting to owners, novelty and drift. Pretrained language models only for the two reading duties. |
| Strip away layers | **Yes, and the evidence backs it.** Middle layers give better classification features than the last ones, and about 40% of a decoder's layers can go with little loss on simple tasks (reasoning suffers). | Cut the model at the best layer for each question, found by a sweep. Keep nothing above the deepest layer we read from. |
| Add or modify layers (new heads) | **Yes.** | Small heads on frozen features: one per question, several per question for a cheap ensemble. |
| Change inputs and outputs (numbers as embeddings, typed slots, claim-evidence cross-attention) | **No evidence it helps on pretrained models.** Number embeddings were only shown working when trained from scratch. I proposed this in the blueprint; the research doesn't support it. | Compare numbers **in code**, which is exact. Text in, scores out. Get the "which fact decides it" pointer by scoring the claim against each candidate fact and taking the best match. That needs no new architecture. |
| "A proper ML model" | **Yes, for the decision layer.** | Monotone EBM or monotone boosted trees, temperature calibration, conformal risk control, kNN novelty, e-detector drift alarms. All CPU, all fast. |
| Teacher-student distillation from curated examples | **Yes, with two conditions.** (1) The teacher must be a different family from the data generator. (2) Curated means hard: filter out what the student already gets right. | Distil the escalation judge's catches into the heads. Use its rationale only as an extra training signal, never as text to imitate. |
| Distillation from agent traces | **Half right.** We judge the agent; we don't copy it. | Agent traces are *input evidence* (history, drift), never imitation targets. |
| "Focus on the cognitive core, not token prediction" | **Exactly right.** This is the main idea. | Cutting the model and adding heads *is* this: keep the understanding, discard the word generator. |
| "Minimum post-training for maximum gain" (with ChatGPT) | **Right, and now measurable.** About 100 labels typically let a specialised small model match a general large one, and 200–300 allowing for variance (EMNLP 2025, general text classification, not our task). | Zero-shot → heads on 250 → 1,000 → 5,000 hard examples, measured at each step. Stop when the gain flattens. |
| A 27B decision model (ChatGPT's suggestion) | **A full contender.** It needs about 54 GB at full precision, which fits across our two 48 GB cards (96 GB). The one open question is speed: the only independent figure (0.50 s, cloud) misses our 300 ms target, so we measure it on our own cards. | Run the 27B at full precision across both cards, and at 8-bit on one card, alongside the 9B (Clef-flash). Size is chosen by measured quality per millisecond, not by fear of size. |

**Where I was wrong in the blueprint, and have corrected it:**
- typed cross-attention, numeric embeddings and the special pointer head (no evidence);
- DeepSeek as the judge (self-preference);
- treating "can't be commanded" as if it covered evasion;
- leaving the single-root-source cap for the swarm monitor until phase 4. One poisoned feed moves every agent that reads it, so a code-only cap comes earlier now.

---

## 3. The six stacks to race

Each stack adds one thing to the one before, so every comparison settles one question.

| Stack | What it is | Hardware | What it settles | Keep or kill |
|---|---|---|---|---|
| **S0 Exact core** | Code checks with taint propagation; monotone EBM; global temperature; conformal risk control; kNN novelty; e-detector plus CUSUM | CPU | How far code and statistics go alone | The floor. Every reader must beat it on unseen worlds at the same hold rate |
| **S1 Encoder heads** | S0 plus a ~400M encoder cross-encoder with several heads and the best-match pointer; injection classifiers as hold-only signals; a 340M decision model zero-shot, for reference | CPU or GPU 1 | Does a cheap encoder carry to new wording? | If it beats S0, it becomes the fail-closed CPU fallback |
| **S2 Frozen cut-down decoder probes** | S0 plus a layer sweep over a decision-tuned 9B, a 9B base decoder **from a different family**, and a decision-tuned 27B (full precision across both cards, and 8-bit on one); heads at each question's best layer; cut at the deepest one, which also shrinks the 27B | GPU 0, or both cards for the 27B | Which model, size and layer represent "supported" and "manipulative" best | Expected primary reader. Must meet C1 and C6 |
| **S3 Lightly tuned S2** | S2 plus LoRA below the cut, a small rank and learning-rate sweep, a few seeds averaged | GPU 0, trained on GPU 1 | Does training add anything over probing? | Kill unless +0.03 AUROC over S2 on unseen worlds |
| **S4 Decision model as reader** | S0 plus the 9B and 27B decision models answering typed questions, recalibrated, entered as monotone features | GPU 0, or both cards for the 27B | Does a vendor's decision head beat our own heads? | Switch to it if +0.05 AUROC on unseen wording |
| **S5 Cascade** | The best of S1–S4 plus an asynchronous judge from a family that neither generated the data nor wrote the worlds; can only tighten; its catches distilled into S3 | External | Does escalation add recall on new failure types? | Drop the judge if it adds < 0.10 recall; aim for a few percent escalated |

**Expected winner, if the evidence holds:** S0 + S2 (or S3) on GPU 0, S1 as the CPU fallback, and S5 for the tail. Our own unseen worlds decide, not leaderboards.

---

## 4. How every stack is scored (the same for all)

**Primary metric:** *coverage at a controlled false-allow rate.* At a conformal bound of at most 5% of allowed actions being ones the owner would reject, what share of good actions get through? A stack that holds everything scores zero, so tightening can't hide behind safety.

**Also reported, per unseen world:**
- AUROC and calibration error (ECE);
- the share of flagged actions whose top cause is the planted one;
- pointer accuracy: did it point at the deciding fact?
- **adaptive evasion:** an attacker gets 20 attempts per case and sees only the hold or allow outcome. What share gets a bad action through?
- false holds per 1,000 actions;
- escalation rate;
- p99 latency on the A6000 and on CPU;
- GPU-seconds per 1,000 decisions.

**Unseen test sets:**
- three DeepSeek-written worlds (T02a/b/c);
- one Codex-written world (T02d, a different family);
- the red team (T06);
- an optional hand-written hard set from the founder;
- evaluation-only public sets for transfer: LLM-AggreFact for grounding and TRAIL for agent failures. Their licences allow evaluation only.

**Training data:**
- the reference world;
- the corruption operators from the blueprint, **filtered for difficulty** (keep what the current best stack gets wrong);
- licence-checked public pairs: FinQA (MIT on GitHub) and VitaminC (share-alike, contrastive pairs).

Never the unseen sets.

---

## 5. What the lab runs now

| Task | Change | Worker |
|---|---|---|
| **T02d** (new) | A fourth independent world, written by a different model family, so DeepSeek-on-DeepSeek agreement can be checked | Codex Luna, isolated |
| **T11** (rewritten) | Becomes the GPU lanes: S2 layer sweep, S4 decision model, and S3 if S2 is within reach. Judges come from outside DeepSeek's family where possible | DeepSeek V4.1 Flash (max) |
| **T14** (new) | Taint propagation through the why graph, and the code-only single-root-source cap | DeepSeek V4.1 Flash (high) |
| **T07** (extended) | Runs the race S0–S5 on the same unseen sets, adds coverage at fixed false-allow and adaptive evasion, writes the final table | DeepSeek V4.1 Flash (high) |

**One thing only you can add.** The research is clear that hard examples written by people help most on the hardest unseen cases. If you write 30 short cases where an agent's claim *looks* supported but isn't (or looks wrong but is fine), they become the hardest test set we have. Ten minutes of yours is worth more than ten thousand generated rows. I'll send a template if you want it.
