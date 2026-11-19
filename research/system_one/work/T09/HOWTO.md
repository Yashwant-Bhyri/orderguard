# Using the university GPU host (for workers)

Written by the lab lead on 2026-11-19, after the smoke test passed.

- **Host:** reached as `ssh wilson-gpu`. The key-based login is already set up on this Mac. Never use a password.
- **Workspace:** `W=/data_ft_7/wilson/wan2.1_robotics_research/workspaces/claude_unrelated_test_20261119/orderguard_s1`. Everything stays under `$W`: code, inputs, outputs, model weights (`$W/hf_home`, set by the wrapper) and logs. The robotics project's files are off-limits.
- **Python:** `$W/venv/bin/python` (Python 3.10). It has torch 2.6.0+cu124, transformers 4.51.3, peft, trl, accelerate, bitsandbytes and sentence-transformers. The pinned versions are in `$W/requirements.lock`. Install extra packages with `$W/venv/bin/pip install ...` and note them in your REPORT.md.
- **Network:** the host has internet access, so jobs can download weights from Hugging Face into `$W/hf_home`.

## Run a GPU job

```bash
scp my_script.py wilson-gpu:$W/inputs/<task>/
ssh wilson-gpu "cd $W && ORDERGUARD_MIN_FREE_GIB=24 ORDERGUARD_TIMEOUT_SECONDS=3600 ./run_job.sh inputs/<task>/my_script.py --arg value"
scp -r wilson-gpu:$W/outputs/<task>/ ./results_from_host/
```

**Two cards (lead, 2026-11-19):** set `ORDERGUARD_NUM_GPUS=2` to get two idle A6000s in one job (for example a 27B model at full precision with `device_map="auto"`). The cap is two cards; the wrapper refuses more, and only one OrderGuard job runs at a time.

What `run_job.sh` does:

1. It samples every A6000 for 30 seconds.
2. It takes the card with the lowest mean utilisation that has at least `ORDERGUARD_MIN_FREE_GIB` free (default 16).
3. It refuses (exit 2) if every such card averages above `ORDERGUARD_MAX_MEAN_UTIL`% (default 50).
4. It sets `CUDA_VISIBLE_DEVICES` to that one card, and logs to `$W/logs/`.

Your script sees exactly one GPU, as `cuda:0`. Write outputs to `$W/outputs/<task>/`.

## GPU rules

- One job at a time from this lab: the wrapper serialises our jobs. Never run more than two GPUs in total. Never bypass the wrapper for GPU work.
- Never signal, kill or inspect other users' processes.
- If the wrapper refuses, wait and retry: one try every 5 minutes, at most 6 tries. Then write the situation into your REPORT.md.

## CPU-heavy jobs

The host has 128 cores and about 750 GB of RAM. Run CPU-only work directly, politely:

```bash
ssh wilson-gpu "cd $W && OMP_NUM_THREADS=32 nice -n 10 venv/bin/python inputs/<task>/cpu_job.py"
```

Cap a job at 32 threads.
