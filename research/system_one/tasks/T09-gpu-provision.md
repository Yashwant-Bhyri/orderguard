---
id: T09
title: GPU campaign provisioning for OrderGuard on the university machine
depends:
worker: codex-gpu
isolate: false
check: test -f READY -o -f BLOCKED.md
timeout_min: 120
max_rounds: 2
---

# T09. Provision a one-GPU OrderGuard campaign

You are the GPU operator for the OrderGuard System One lab. The founder (Yash) has approved using the university GPU machine for this lab: **any model may be tested or deployed, strictly one GPU at a time.** Use the lab bridge tools (`wan_lab`) and whatever access to that machine is *already configured* for you.

## Hard limits

- **Never type, request or store a password.** If a step needs credentials that are not already configured, stop. Write the exact step Yash must do himself into BLOCKED.md.
- Use at most one GPU at any time, and pick an idle one. Other students share this machine.
- **Do not change, pause or approve anything in the WAN or robotics campaign:** its files, its environment, its controller state or its approval file.
- No secrets in any file. Do not print keys.
- Run no git here.

## Goal

A working, isolated OrderGuard workspace on the machine, under its own directory (for example `<lab data root>/orderguard_s1/`), that can run:

- (a) inference with a 1–4B instruction model (Qwen3 1.7B and Qwen3 4B, or the nearest available), returning yes/no log-probabilities;
- (b) a DeBERTa-v3 NLI cross-encoder, scoring batches of premise and hypothesis pairs;
- (c) a QLoRA fine-tune of a 4B model for under 1 GPU-hour.

## Steps

1. Find the least-effort legitimate path:
   - reuse the existing controller, if it can take a second campaign without touching the WAN files;
   - or provision a separate OrderGuard controller and state path;
   - or run directly on one idle GPU through the access you have, if the controller is not required for this.

   Record which you chose and why.
2. Create a **separate** Python environment. Match the CUDA version to the driver. Install torch, transformers, peft, trl, bitsandbytes, accelerate and sentence-transformers.
3. Stage the model weights, and record their sha256:
   - Qwen3-1.7B;
   - Qwen3-4B;
   - a DeBERTa-v3 NLI checkpoint (for example `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`);
   - a small sentence-embedding model.

   Jobs run offline, so staging must happen through whatever path has network access.
4. **Smoke test on one GPU:**
   - 1,000 NLI pairs: throughput and p99 latency;
   - 200 yes/no prompts on each Qwen model: throughput and p99 latency;
   - a 10-minute QLoRA run on Qwen3-4B with a toy dataset: the loss goes down.
5. Write the results into this task folder (`research/system_one/work/T09/` on the Mac side):
   - `HOWTO.md`: exactly how another worker submits a job, where to put input files, and where outputs appear. These must be concrete commands or bridge calls;
   - `SMOKE.md`: the numbers;
   - a file named `READY` when (a) and (b) work.

If anything blocks you, write `BLOCKED.md` with:

- what is done;
- what is blocked, and why;
- the precise action Yash must take;
- what you will do once that is done.

Make sure the BLOCKED.md works as a reliable handover: someone who has never seen this task should be able to act on it.

## Lead review, 2026-11-19

The restricted bridge cannot do this task, as the lead has confirmed directly. Its tools are:

- status reads;
- text files up to 64 KiB in its workspaces;
- `submit_python_job`, which needs a WAN-style approved goal and runs offline.

That means it cannot stage model weights at all. The lab host is reachable from the Mac.

The path for round 2: when `ssh -o BatchMode=yes orderguard-gpu true` succeeds from this Mac, use plain SSH with that alias. The founder adds that alias with a dedicated key; no password is involved. Work only under the OrderGuard workspace. Check `nvidia-smi` before each job, and use one idle GPU. Download weights on the host into the OrderGuard workspace. Do not use the `wan_lab` bridge for this task. If the alias does not work yet, write BLOCKED.md again and stop.

## Lead review 2, 2026-11-19 (this supersedes the alias and folder in "Lead review")

- **SSH alias:** `wilson-gpu`, with a dedicated key and no password. It opens a normal shell. Use `orderguard-gpu` only if `wilson-gpu` does not exist.
- **Folder:** keep every project file, environment, log, cache and checkpoint under `/data_ft_7/wilson/wan2.1_robotics_research/workspaces/claude_unrelated_test_20261119/`. Never touch the robotics campaign's own files, environment or controller.
- **Scheduler first:** check for the university's scheduler (`sbatch`, `srun`, `qsub` or a module system). If one exists, follow its normal job process. If not, run directly.
- **GPU use:** check `nvidia-smi` immediately before every run, and use one A6000 that shows near-zero memory and utilisation.
- **Weights:** download them on the host into the folder above, with `HF_HOME` set there.

## Host facts from the machine's administrator, 2026-11-19

- The machine has CUDA 11 and CUDA 12. Pick the one that matches the torch build.
- **Home has too little space.** Every environment, cache and checkpoint goes under `/data_ft_7/wilson`.
- **GPU limit:** the administrator allows up to two cards. The founder's rule for this lab is stricter: **one GPU at a time.**
- The account is shared with the founder's team. Never change shell profiles, keys or anything outside the workspace folder.

## Lead review 3, 2026-11-19: scope cut (this supersedes "Goal" items (a) to (c) and steps 3 and 4)

The model choice is not made yet; architecture study T10 makes it. So in this task:

- **Do not** download Qwen, DeBERTa or any other model weights, and run no fine-tune.
- **Do:**
  - finish and verify the separate Python environment; reuse what round 1 installed if it is sound;
  - write a model-agnostic job wrapper, `run_job.sh`, on the host. It picks one idle A6000 by `nvidia-smi` (memory under 1 GiB and utilisation under 5%), sets `CUDA_VISIBLE_DEVICES`, `HF_HOME` and the workspace paths, runs a given script with a timeout, logs to the workspace, and refuses if no GPU is idle;
  - run one smoke test: a fp16 and bf16 matmul throughput benchmark, plus a torch CUDA sanity check;
  - write HOWTO.md: how a Mac-side worker copies a script up with `scp` and runs it through `run_job.sh` with `ssh wilson-gpu`;
  - create READY when the wrapper and the smoke test work. Write SMOKE.md with the numbers.

## Lead review 4, 2026-11-19: the idle rule was wrong (this supersedes the threshold in Lead review 3)

"Under 1 GiB used" never holds on this shared host. Other students' processes keep 5–11 GB allocated even when their GPU is idle.

**New rule:** a card qualifies when both of these hold:

- its utilisation stays at or below 10% at every 2-second sample over 30 seconds;
- it has at least the job's declared memory free. Default: 16 GiB. Jobs declare `ORDERGUARD_MIN_FREE_GIB`.

Among qualifying cards, pick the one with the most free memory. Use one card only, as before.

Update `run_job.sh` to this rule, run the smoke benchmark, and finish the task: SMOKE.md, HOWTO.md and READY. Do not touch or signal anyone else's processes.
