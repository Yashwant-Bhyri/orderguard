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
