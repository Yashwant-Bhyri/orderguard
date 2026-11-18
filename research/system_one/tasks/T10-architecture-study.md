---
id: T10
title: Architecture study - what kind of model System One should be, decided by exploration and evidence
depends:
worker: opencode-go/deepseek-v4-pro
variant: max
isolate: false
env_keys: OPENROUTER_API_KEY
check: test -f ARCHITECTURE-OPTIONS.md && bash run.sh
timeout_min: 180
max_rounds: 3
---

# T10. What kind of model should System One be?

Read `research/system_one/POLICY.md` first, especially "Choices are challenged, not defaulted". Then read:

- `SPRINT.md`;
- `docs/vision/SYSTEM-ONE.md`;
- `docs/vision/lab/READOUT.md`;
- the scans in `docs/vision/scan/2026-11-19/`. Treat these as leads to verify, not as facts.

Your task folder is `research/system_one/work/T10/`.

**Isolation rule:** do not open `work/T02*`, `work/T06` or `data/heldout*`.

## The problem, stated without a model in mind

An AI agent trades a portfolio for an owner. For every thesis the agent forms and every action it takes, System One must return:

1. a calibrated probability that the owner would *not* endorse it;
2. which cause carries that risk: drift from purpose, unsupported or misquoted claims, hype, poisoned or unauthorised notes, a stale thesis, or something new;
3. weights over the evidence, notes and claims that led to the action. This is the "purpose attribution".

It can only tighten, never loosen. It must hold up:

- on worlds and wording its builders never wrote;
- against adversarial text written to fool it.

**Budget:** milliseconds per order in code, and seconds per thesis.

**What learning can draw on:**
- simulated worlds with planted causes;
- public "stated purpose against actual holdings" data (SEC funds);
- in deployment, each owner's approve and reject decisions: few per owner, but they keep arriving;
- frontier models as teachers.

**What we do not know yet:** whether System One is a classical ML model, a classifier over embeddings, an LLM judge, a hosted decision model, compiled code, or a cascade of these. **Your job is to find out which design gets robust functionality fastest. Do not assume one.** The founder's warning, in their words: do not reach for "take a base model, then fine-tune, then RL" by habit. Do not build from scratch. Find the shortest path to robust, working judgement, and spend compute only where it creates an edge.

## Explore at least these families

Explore them as real options. For each, read primary documentation (model cards, papers, official docs, licences) with `webfetch`, and cite links.

1. **Code checks plus a glass-box learner:** EBM or GAM, monotone or lattice models, with conformal risk control. This is the sprint's current hypothesis. Treat it as a hypothesis, not a winner.
2. **Tabular and in-context learners that need no training:** TabPFN-2.5, TabICL, LimiX, and anything newer. In particular, **per-owner adaptation by putting that owner's past decisions in context.**
3. **Hosted decision models**, used directly or as teachers. One is available now through OpenRouter's decisions API (`typesafe/jev-1.14`; see the call format in `tasks/T05-text-channel.md`).
4. **Encoders:**
   - cross-encoders and NLI models;
   - rerankers;
   - modern encoder families such as ModernBERT, and whatever is newer in 2026;
   - small trained heads on top of them.
5. **Embeddings or hidden states with linear probes:** embeddings from a strong model, or a strong model's hidden states, with calibrated linear probes.
6. **Small generative judges:** score from logprobs, as generative verifiers, and distilled.
7. **Weight-space methods that buy functionality without a training run:**
   - task arithmetic and model merging;
   - LoRAs generated from a task description by a hypernetwork (for example Text-to-LoRA or Drag-and-Drop-style methods);
   - activation steering and representation engineering;
   - model editing.

   Say honestly what is mature and what is a demo.
8. **Program synthesis:** a strong model writes the checks as code, we test them, and we learn only the residual. Program distillation of a judge belongs here.
9. **Cascades and mixtures** of the above, with a confidence-based route to the slower or stronger stage.

## For each family, report

- what it is;
- the best concrete candidates as of 2026, with size, licence, latency on a laptop CPU and on one A6000, and context length;
- how it would represent our inputs: numbers, the provenance graph and short texts;
- how calibration is obtained and kept under shift;
- whether "can only tighten" can be guaranteed by construction;
- the data it needs, and the time to a working version;
- its debuggability;
- the cost per decision;
- what would make it fail on our problem.

## Then iterate

Do not stop at a ranking. Take your top three designs. For each one, write down the strongest alternative that could beat it and why. Revise the design. Repeat at least twice, and show the iterations: v1, then the challenge, then v2, then the next challenge, then v3.

**The output is three final candidate architectures.** Each comes with a diagram in text, the exact components, and the main risk.

## Discriminating experiments: the part that turns this into a decision

Design the **cheapest set of experiments that would separate the three candidates** on our real criteria. Each experiment must:

- fit in at most 2 GPU-hours on one A6000, or in CPU time on a laptop;
- use the sprint's data: `data/ref/` now, and the T04 harness when it exists;
- state a kill criterion in advance.

**Run the ones you can run now**, on the reference world in `data/ref/`, if T01 has produced it. Use only inference: off-the-shelf models through the API, and CPU models. Cap the API spend for this task at $3, and cache every response. GPU experiments go into the plan, with exact scripts, for the lab's GPU wrapper (`work/T09/HOWTO.md`) once it exists.

"Closest to frontier intelligence at small size" is itself a measurement. Use a frontier judge's labels on a sample of `data/ref/` actions as a reference. Then measure how closely each cheap candidate agrees with that judge and with the true labels.

## Deliverables

- `work/T10/ARCHITECTURE-OPTIONS.md`:
  - the families;
  - the iterations;
  - the three candidates;
  - the experiment plan;
  - the results of the experiments you ran;
  - your recommendation, with what would change it.
- `work/T10/run.sh`: reproduces every experiment you ran, from cached responses where possible.
- `REPORT.md`, with the POLICY sections.

## Pass bar

- All nine families covered, with primary sources.
- At least two documented iterations.
- Three candidates, each with its strongest challenger.
- At least three discriminating experiments, each with a kill criterion. At least one has actually been run, with a reproducible result.
- No unsupported claims: anything not verified from a primary source is marked as unverified.
