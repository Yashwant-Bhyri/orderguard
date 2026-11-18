---
id: T11
title: GPU readers - hidden-state probes and a logprob judge on strong open models; distance to frontier judgement (X2 GPU part, X5)
depends: T01, T05, T09
worker: opencode-go/deepseek-v4.1-flash
variant: max
isolate: false
env_keys: OPENROUTER_API_KEY
check: bash run.sh
timeout_min: 180
max_rounds: 3
---

# T11. GPU readers and distance to frontier judgement

Read these first:

- `research/system_one/POLICY.md`, including "Choices are challenged";
- `docs/vision/lab/ARCHITECTURE.md`, sections 2b, 5 and 6. They govern this task;
- `work/T05/REPORT.md`;
- `work/T09/HOWTO.md`.

Your task folder is `research/system_one/work/T11/`.

**Isolation rule:** do not open `work/T02*`, `work/T06` or `data/heldout*`.

## GPU rules

- Run on the university host only through the wrapper in `work/T09/HOWTO.md`: `ssh wilson-gpu`, then `run_job.sh`.
- Use one card per job, and at most two cards at once in total. The wrapper enforces this.
- Keep every file on the host under the OrderGuard workspace named in HOWTO.md.
- The host's CPUs may also be used for CPU-heavy work.
- Never touch other users' processes, or the robotics project.

## Build

1. **Confirm the model shortlist from primary sources before downloading.** ARCHITECTURE.md section 6 asks for three classes:
   - a mid-size model with the best open interpretability tooling;
   - the strongest open model that fits one A6000 in bf16 with batching;
   - a small model, about 1–2B, to measure what size buys.

   Pick the current best member of each class. Write the alternatives you rejected, and why, under Judgement calls. Download weights on the host into the workspace.
2. **Hidden-state probe readers.** For each model and each sub-question (`hype`, `authority_language`, `support_gap`):
   - run one forward pass;
   - take the residual-stream activations at a few layers. Choose the layers on a validation split of the *training* text only;
   - pool them;
   - fit a logistic probe.

   Train only on T05's self-generated training text (`work/T05/make_train_text.py` output). Do not train on `data/ref/` labels; use `data/ref/` only to score.
3. **Logprob judge**, on the strongest model only: score each sub-question from P(yes) under a fixed prompt. This is the generative alternative to the probe.
4. **Expose every reader** through the interface in `og_s1/readers/`, with a Mac-side client that sends a batch to the host and returns scores, plus a local cache keyed by the sha256 of the input.
5. **X5, distance to frontier judgement.**
   - Sample 500 actions from `data/ref/`, stratified by cause, half of them shifted.
   - Get a frontier judge's labels: one strong frontier model through OpenRouter (`OPENROUTER_API_KEY`), asked the three sub-questions plus "would the owner endorse this?". Choose the model by reasoning, record the alternatives, and cap the spend at $10.
   - For every reader from T05 and from this task, report its agreement with the frontier judge (AUROC with the judge's output as the target) and its agreement with the true labels.

## run.sh

It reproduces everything from cached outputs: the Mac-side cache, plus the host-side outputs it copies back. It prints:

- per reader and sub-question: AUROC, ECE and latency (p50 and p99, per item, on the GPU);
- the X5 agreement table.

## Pass bar

- Every model choice records its alternatives.
- Probes are trained only on self-generated text.
- Every number reproduces from cache.
- No more than two GPUs were ever used, which the wrapper's logs show.
- Total API spend is at most $10.
