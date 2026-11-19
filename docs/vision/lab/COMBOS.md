# Which combination of parts System One should be: the lead's verdict, and the bench that will settle it

Written by the lab lead on 2026-11-19, after the deep-research pass [System One functions and model combos](../reports/System%20One%20functions%20and%20model%20combos.md). It updates [BLUEPRINT.md](BLUEPRINT.md) where the evidence disagreed with it. Its last section is what the lab now runs.

---

## 0. What we optimise for, in order (founder, 2026-11-19)

1. **Primary:** robust functionality, very high intelligence, and doing System One's job strongly, measured on worlds the models never saw.
2. **Secondary:** size, latency, cost and context length. These are recorded for every run, but they kill nothing until the quality ceiling is proven.

So the lab works in two phases:
- **Find the ceiling.** Use the strongest models we can run (31B and 27B at full precision across both cards), the best evidence representation, and the best judges.
- **Compress.** Only then shrink, cut or distil, keeping only what holds up on unseen worlds.

The 50 ms and 300 ms targets (C6) apply in the compression phase, not before.

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
| **S2 Frozen decoder probes** | S0 plus a layer sweep over the two strongest decision models, Karpo-decision 31B (Gemma 4 base) and Clef 27B (Qwen3.8 base), both at full precision across both cards; their 9B-class siblings; heads at each question's best layer. Cutting comes only in the compression phase | Both cards | Which model and layer represent "supported", "manipulative" and the binding errors best | Expected primary reader. Must meet C1; C6 only when compressing |
| **S3 Lightly tuned S2** | S2 plus LoRA below the cut, a small rank and learning-rate sweep, a few seeds averaged | GPU 0, trained on GPU 1 | Does training add anything over probing? | Kill unless +0.03 AUROC over S2 on unseen worlds |
| **S4 Decision model as reader** | S0 plus Karpo-decision 31B and Clef 27B (and their 9B-class siblings) answering typed questions zero-shot, recalibrated, entered as monotone features | GPU 0, or both cards for the 27B | Does a vendor's decision head beat our own heads? | Switch to it if +0.05 AUROC on unseen wording |
| **S5 Cascade** | The best of S1–S4 plus an asynchronous judge from a family that neither generated the data nor wrote the worlds; can only tighten; its catches distilled into S3 | External | Does escalation add recall on new failure types? | Drop the judge if it adds < 0.10 recall; aim for a few percent escalated |

**Expected winner, if the evidence holds:** S0 + S2 (or S3) on GPU 0, S1 as the CPU fallback, and S5 for the tail. Our own unseen worlds decide, not leaderboards.

---

**One experiment cuts across all the stacks: R, the evidence representation.** Give the same model the same case in four forms:
- raw text;
- typed fact slots written as text;
- claim and evidence pairs;
- a package built from the why graph, with each claim's source, period, entity and trust.

Does better structure beat a bigger model? If it does, the gain is cheap and permanent.

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

**Unseen worlds must differ along five axes, and each result is reported per axis:**
- semantic: new wording;
- financial: new instruments, entities, accounting concepts;
- temporal: revisions, delays, stale theses;
- behavioural: long sequences, slow drift, several agents;
- adversarial: poisoned memory, forged authority.

Splits are by company, author, agent and owner, never random rows.

**Training data:**
- the reference world;
- the corruption operators from the blueprint, **filtered for difficulty** (keep what the current best stack gets wrong);
- **closest to the real job first.** Real financial-agent failures are mostly binding errors: the right number attached to the wrong entity, period, concept or scope. FinVerify (NeurIPS 2026) sorts 190 failed agent trajectories into five checkable categories:
  - temporal integrity;
  - source fidelity;
  - comparability;
  - accounting integrity;
  - financial-model fidelity.

  Our corruption operators are aimed at those five. SEC XBRL facts give real values with their concept, period and entity, so they are the natural source for real binding pairs;
- licence-checked public sets, in order of closeness to our job:
  - SEC XBRL hard negatives;
  - financial NLI (FinNLI);
  - agent finance reasoning trajectories (check whether the licence allows training or only evaluation);
  - FinQA (MIT);
  - generic contrastive pairs such as VitaminC (share-alike), last.

Never the unseen sets.

---

## 5. What the lab runs now

| Task | Change | Worker |
|---|---|---|
| **T02d** (new) | A fourth independent world, written by a different model family, so DeepSeek-on-DeepSeek agreement can be checked | Codex Luna, isolated |
| **T11** (rewritten) | Becomes the GPU lanes: S2 layer sweep, S4 decision model, and S3 if S2 is within reach. Judges come from outside DeepSeek's family where possible | DeepSeek V4.1 Flash (max) |
| **T14** (new) | Taint propagation through the why graph, and the code-only single-root-source cap | DeepSeek V4.1 Flash (high) |
| **T15** (new, runs first) | A frozen evaluation specification and one model-neutral adapter, so every lane is scored on identical inputs, labels and metrics. Without it, differences between prompts, schemas and data would pass for differences in intelligence | DeepSeek V4.1 Flash (high) |
| **T07** (extended) | Runs the race S0–S5 on the same unseen sets, adds coverage at fixed false-allow and adaptive evasion, writes the final table | DeepSeek V4.1 Flash (high) |

| **T16** (new) | The capability benchmark: 600+ product-level scenarios in eight types, written by a different model family, each with decisive evidence and a truth type | Codex Luna, isolated |
| **T17** (new) | Public data adapters and a licence audit, closest to the job first; no evaluation-only data can reach training | DeepSeek V4.1 Flash (high) |
| **T19** (new) | Counterfactual minimal pairs: change one factor, label by code, keep the hard ones | DeepSeek V4.1 Flash (high); V4 Pro only for hard evidential cases |
| **T20** (new) | A triage service on hosted decision models, with a comparison of the ones on OpenRouter | DeepSeek V4.1 Flash (high) |
| **T21, T23** (backlog) | Is the why graph enough? Then train the heads on the pairs. Promoted automatically when their dependencies pass | DeepSeek V4.1 Flash |

**Execution order:**
1. T15, T16, T17 and T20 now.
2. T19 and T14 when T03 and T15 pass.
3. T11 when T05 and T15 pass, then T21 and T23.
4. T07 last.

**The lab never stalls.** When nothing is runnable, the runner promotes the next backlog brief whose dependencies have passed. If there is none, it runs a steward (Codex Luna, at most every 3 hours). The steward:
- reopens tasks that failed on infrastructure;
- proposes new briefs into the backlog, tied to this plan;
- writes `lab/STEWARD.md`.

It never changes a pass bar or makes a decision. The Mac is kept awake while the runner runs.

## 6. What we took from the founder-shared master plan (2026-11-19)

**Taken:**
- three kinds of truth on every label: formal, evidential, preference (T15);
- the capability benchmark with eight product scenarios (T16);
- "change one factor" counterfactual pairs as the main training paradigm (T19, T23);
- separating missing information from reasoning failure (T21);
- hosted decision models as a triage and monitoring service (T20);
- Clef and Karpo on equal footing, with Clef first for adaptation because its trainable head ships with code.

**Adjusted:**
- DeepSeek V4 Pro teaches only the hard evidential cases. It never grades evaluation, because DeepSeek also generates our data.
- Karpo's licence is reported differently by different sources (Apache-2.0 vs a community licence with a revenue threshold). T11 records the exact licence from the repository revision it downloads.

**Not yet:**
- latent-reasoning modules;
- RL on the whole system;
- any compression before the ceiling is known.

**One thing only you can add.** The research is clear that hard examples written by people help most on the hardest unseen cases. If you write 30 short cases where an agent's claim *looks* supported but isn't (or looks wrong but is fine), they become the hardest test set we have. Ten minutes of yours is worth more than ten thousand generated rows. I'll send a template if you want it.
