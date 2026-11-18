#!/usr/bin/env python3
"""Single-GPU CUDA sanity check and FP16/BF16 matmul throughput benchmark."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import torch


def main() -> None:
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available to PyTorch")
    if torch.cuda.device_count() != 1:
        raise SystemExit(f"expected exactly one visible GPU, found {torch.cuda.device_count()}")

    device = torch.device("cuda:0")
    props = torch.cuda.get_device_properties(device)
    sanity = torch.randn((1024, 1024), device=device, dtype=torch.float32)
    sanity_result = sanity @ sanity
    torch.cuda.synchronize(device)
    if not torch.isfinite(sanity_result).all().item():
        raise SystemExit("CUDA sanity matmul returned non-finite values")

    size = int(os.environ.get("ORDERGUARD_BENCH_SIZE", "4096"))
    warmup = int(os.environ.get("ORDERGUARD_BENCH_WARMUP", "10"))
    iterations = int(os.environ.get("ORDERGUARD_BENCH_ITERATIONS", "200"))
    if size < 256 or warmup < 1 or iterations < 1:
        raise SystemExit("benchmark size must be >=256 and warmup/iterations must be positive")

    results = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "torch_version": torch.__version__,
        "torch_cuda_build": torch.version.cuda,
        "cuda_device_count_visible": torch.cuda.device_count(),
        "physical_gpu_index": os.environ.get("ORDERGUARD_GPU_PHYSICAL_INDEX"),
        "device_name": props.name,
        "compute_capability": f"{props.major}.{props.minor}",
        "sanity_matmul": "passed",
        "shape": [size, size],
        "warmup_iterations": warmup,
        "timed_iterations": iterations,
        "benchmarks": [],
    }

    for label, dtype in (("fp16", torch.float16), ("bf16", torch.bfloat16)):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
        a = torch.randn((size, size), device=device, dtype=dtype)
        b = torch.randn((size, size), device=device, dtype=dtype)
        for _ in range(warmup):
            c = a @ b
        torch.cuda.synchronize(device)

        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        for _ in range(iterations):
            c = a @ b
        end.record()
        end.synchronize()
        elapsed_ms = float(start.elapsed_time(end))
        if not torch.isfinite(c).all().item():
            raise SystemExit(f"{label} matmul returned non-finite values")
        total_flops = 2 * size**3 * iterations
        results["benchmarks"].append(
            {
                "dtype": label,
                "elapsed_ms": elapsed_ms,
                "mean_ms_per_matmul": elapsed_ms / iterations,
                "throughput_tflops": total_flops / (elapsed_ms / 1000.0) / 1e12,
                "peak_allocated_mib": torch.cuda.max_memory_allocated(device) / (1024**2),
            }
        )
        del a, b, c
        torch.cuda.synchronize(device)

    out_dir = Path(os.environ.get("ORDERGUARD_OUTPUTS", "outputs"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"gpu_smoke_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)
    print(f"result_json={out_path}", flush=True)


if __name__ == "__main__":
    main()
