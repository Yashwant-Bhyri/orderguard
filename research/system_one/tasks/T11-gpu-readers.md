---
id: T11
title: GPU reader lanes S2, S4 and S3 - cut-down decoder probes, decision models as readers, and light tuning
depends: T01, T05, T09, T15
worker: opencode-go/deepseek-v4.1-flash
variant: max
isolate: false
env_keys: OPENROUTER_API_KEY
check: bash run.sh
timeout_min: 240
max_rounds: 4
---

# T11. GPU reader lanes

Read these first:

- `research/system_one/POLICY.md`;
- `docs/vision/lab/COMBOS.md`, which governs this task: sections 3 and 4 define the stacks and the scoring;
- `docs/vision/reports/System One functions and model combos.md`, the section "Readers";
- `work/T05/REPORT.md`;
- `work/T09/HOWTO.md`, including the two-card option.

Your task folder is `research/system_one/work/T11/`.

**Isolation rule:** do not open `work/T02*`, `work/T06` or `data/heldout*`. T07 scores the unseen worlds. You score only `data/ref/` and your own validation splits.

## The questions every reader answers

For each claim, note or rationale in the causal view (`og_s1.schema.model_view_at(episode, i)`), the readers answer these, each as a probability:

- `supported`: does the cited source support the claim?
- `hype`: is the wording promotional rather than factual?
- `authority`: does the text claim a permission or approval it does not carry?
- `addresses_reviewer`: is the text trying to instruct whoever reviews it?

Numbers are compared in code (T03), not by the readers.

## Lanes

### S2: frozen, cut-down decoder probes (the main lane)

**Quality comes first** (COMBOS.md section 0). Latency and cost are recorded but kill nothing in this task.

1. **Find the ceiling first. Confirm each model from its primary model card before downloading:**
   - Karpo-decision 31B (MachinePulseAI, Gemma 4 base), at full precision across two cards (`ORDERGUARD_NUM_GPUS=2`);
   - Clef 27B (Cloudflare, Qwen3.8 base), at full precision across two cards;
   - their 9B-class siblings (Karpo 9B or 12B, Clef-flash 9B), to see what size buys.

   Record the alternatives you rejected, and why, under Judgement calls. Record each licence exactly.
2. **Layer sweep.**
   - Run one forward pass per input, and pool the hidden states at every fourth layer.
   - Fit a logistic head and a small MLP head per question per layer.
   - Choose the best layer per question on a validation split of the **training** data only.
3. **Evidence representation (experiment R).** On the best model, compare four input forms on the same cases:
   - raw text;
   - typed fact slots written as text;
   - claim and evidence pairs;
   - a package from the why graph (source, period, entity, trust).

   Report the gain from structure against the gain from size.
4. **Cut**, only after steps 1–3. Rebuild the winner with only the layers up to the deepest layer any question uses, and remove its language-model head. Report what the cut costs in quality, and what it saves in latency.
5. **Ensemble of heads.** Train five heads per question on different seeds and splits of the same features, and average them. They share one forward pass.

### S4: decision models as readers

Ask the same decision models (31B, 27B and their 9B-class siblings) the four questions as typed yes/no questions, through their own decision heads, zero-shot. Recalibrate each probability with one global temperature, fitted on the training split.

### S3: light tuning (run only if S2's best model is within 0.10 AUROC of the best S4 or S2 result on validation)

- Apply LoRA to the layers below the cut, with a sweep of ranks 8 and 32 and two learning rates.
- Train on the training data, with a five-head ensemble.
- Average three seeds.
- Keep the result only if it beats frozen S2 by ≥ 0.03 AUROC on validation. Otherwise report it and drop it.

## Training data (identical for every lane)

1. Use `data/ref/` causal views, with T05's self-generated training text.
2. Add the corruption operators listed in `docs/vision/lab/BLUEPRINT.md` section 7.2, each with its hard negative. **Weight them towards binding errors**: the right value attached to the wrong entity, period, concept or scope. Cover FinVerify's five categories (see COMBOS.md section 4). Use real SEC XBRL facts (value, concept, period, entity) as sources where you can.
3. **Apply a difficulty filter.** Keep a generated example only if the current best lane gets it wrong or is unsure (probability between 0.2 and 0.8). Report how many examples survive.
4. You may add FinQA-derived pairs (MIT licence, from its GitHub repository) and VitaminC (CC BY-SA 3.0). Record the licence next to each source.

## Judges, for distance-to-judge (X5)

1. Sample 500 actions from `data/ref/`, stratified by cause.
2. Collect labels from two judges:
   - **primary:** the external decision model through OpenRouter, a different model family from DeepSeek;
   - **secondary:** DeepSeek V4.1 Flash at its highest reasoning setting, through OpenRouter.
3. DeepSeek also generated much of the data, so report its agreement figures **with a self-preference warning**.
4. For every reader, report AUROC against each judge, and against the true labels.
5. Cap the total spend at $10.

## Interface

- Expose every reader through `og_s1/readers/`.
- Write a Mac-side client that sends a batch to the host and returns scores, with a local cache keyed by the sha256 of each input.

## run.sh

Reproduce every number from the cached outputs, and print:

- per lane, model, layer and question: AUROC, ECE and **coverage at a false-allow rate of 0.05** on the validation split;
- p50 and p99 latency per item and GPU-seconds per 1,000 items, for the full and the cut model, on one card and on two;
- the X5 agreement table.

## Pass bar

- Every model choice records its alternatives and its licence.
- Training data never includes `data/heldout*` or `work/T02*`.
- Every number reproduces from the cache.
- No job ever used more than two cards; the wrapper logs show it.
- API spend is at most $10.
- The cut models load and run on their own, without the removed layers.

**Causal input:** read only `og_s1.schema.model_view_at(episode, i)`. The reviewer checks this.
