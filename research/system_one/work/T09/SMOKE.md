# GPU smoke test (2026-11-19)

- **Card:** the wrapper picked physical GPU 1, the lowest mean load, at 12% over 30 s, with 43.9 GB free. Other students' jobs were running on the other cards (12–100% load).
- **Software:** torch 2.6.0+cu124, CUDA build 12.4. One device was visible.
- **4096×4096 matmul, 200 timed iterations:**
  - fp16: 1.40 ms per matmul, about 98.5 TFLOPS;
  - bf16: 1.33 ms per matmul, about 103.6 TFLOPS.

  This is shared-card throughput.
- **Output:** `$W/outputs/gpu_smoke_20261118T231037Z.json`. **Log:** `$W/logs/`. Both are on the host.
- **Wrapper policy change, made by the lead:** "≤10% at every sample" became "lowest mean load, refuse above 50%", because the strict rule never fired on this shared host. The strict version is kept as `run_job.sh.bak-strict`.
