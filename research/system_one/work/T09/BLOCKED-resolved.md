# T09 blocked handover

## Status

The isolated OrderGuard environment and model-agnostic host wrapper are ready. The requested CUDA sanity and FP16/BF16 matmul benchmark could not start because no A6000 met the current shared-host idle rule in three 30-second scans. `READY` has not been created.

## Done

- Connected with the configured key-based `wilson-gpu` alias using `BatchMode=yes`; no password was requested, entered, stored, or printed.
- Confirmed `sbatch`, `srun`, `qsub`, and `module` are unavailable; the normal path on this host is direct execution through the OrderGuard wrapper.
- Kept the project under `/data_ft_7/wilson/wan2.1_robotics_research/workspaces/claude_unrelated_test_20261119/orderguard_s1/`.
- Reused and verified the isolated Python 3.10.12 venv. `pip check` and imports passed for torch 2.6.0+cu124, transformers 4.51.3, peft 0.15.2, trl 0.17.0, bitsandbytes 0.45.5, accelerate 1.6.0, and sentence-transformers 4.1.0.
- Installed `run_job.sh`. It samples each A6000 every 2 seconds over 30 seconds, requires every utilization sample to be at most 10%, checks the job's free-memory declaration (default 16 GiB), selects the qualifying card with the most free memory, and sets `CUDA_VISIBLE_DEVICES` to that single physical GPU. It logs under the workspace and refuses safely when no GPU qualifies.
- Updated `HOWTO.md` with concrete Mac-side `scp` and `ssh wilson-gpu` submission commands, input/output locations, and the host workspace.
- Did not use `wan_lab`, download model weights, run fine-tuning, or touch robotics campaign files, environment, controller state, or approvals. No git commands were run.

## Blocked

Three attempts to run `gpu_smoke.py` each found no qualifying card and exited with status 2 before Python started. In each 16-sample scan, every A6000 exceeded 10% utilization at least once. Free memory was sufficient (the latest final snapshot showed at least 35 GiB free on each card), so the blocker is sustained utilization, not capacity.

The host logs are:

- `/data_ft_7/wilson/wan2.1_robotics_research/workspaces/claude_unrelated_test_20261119/orderguard_s1/logs/20261118T230238Z_gpu_smoke_389317.log`
- `/data_ft_7/wilson/wan2.1_robotics_research/workspaces/claude_unrelated_test_20261119/orderguard_s1/logs/20261118T230346Z_gpu_smoke_390086.log`
- `/data_ft_7/wilson/wan2.1_robotics_research/workspaces/claude_unrelated_test_20261119/orderguard_s1/logs/20261118T230505Z_gpu_smoke_391423.log`

## Exact action for Yash

Coordinate a short quiet window with the lab administrator or students sharing the host so at least one A6000 remains at or below 10% utilization at every 2-second sample for 30 seconds and has at least 16 GiB free. Do not stop or signal anyone else's processes. Once that window is available, reply in this task so the operator can rerun the benchmark. No password or new credential is needed.

## Resume command

From the Mac task folder, run the following after the quiet window is arranged:

```sh
W=/data_ft_7/wilson/wan2.1_robotics_research/workspaces/claude_unrelated_test_20261119/orderguard_s1
ssh -o BatchMode=yes wilson-gpu "cd '$W' && ORDERGUARD_MIN_FREE_GIB=16 ORDERGUARD_TIMEOUT_SECONDS=900 ./run_job.sh gpu_smoke.py"
```

## What happens after the window is available

Rerun the wrapper, which makes a fresh 30-second check immediately before launching. If the CUDA sanity check and both matmul benchmarks pass, record their measured throughput in `SMOKE.md`, remove this blocker, and create `READY`.

