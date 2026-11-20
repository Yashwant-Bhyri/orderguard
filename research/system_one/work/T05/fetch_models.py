"""Ensure every reader's weights are cached under data/models/hf.

This script is idempotent.  It never prints a filesystem path.  If the local
cache is complete it performs no network request.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "models" / "hf"
CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(CACHE))

MODELS = [
    ("MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli", "MIT", "NLI cross-encoder"),
    ("sentence-transformers/all-MiniLM-L6-v2", "Apache-2.0", "sentence encoder"),
    ("protectai/deberta-v3-base-prompt-injection-v2", "Apache-2.0", "injection classifier"),
    ("fmops/distilbert-prompt-injection", "Apache-2.0", "injection classifier"),
]

ALLOW = ["*.bin", "*.h5", "*.msgpack", "*.ot", "*.onnx", "*.tflite", "*.safetensors.index.json"]


def _have(repo: str) -> bool:
    from huggingface_hub import snapshot_download

    try:
        path = snapshot_download(repo, cache_dir=str(CACHE),
                                 ignore_patterns=ALLOW, local_files_only=True)
    except Exception:
        return False
    files = [p for p in Path(path).rglob("*") if p.suffix in (".safetensors", ".bin")]
    return bool(files)


def main() -> int:
    from huggingface_hub import snapshot_download

    missing = 0
    for repo, licence, role in MODELS:
        if _have(repo):
            print(f"cached: {repo} ({role}, {licence})")
            continue
        missing += 1
        print(f"fetching: {repo} ({role}, {licence})")
        try:
            snapshot_download(repo, cache_dir=str(CACHE), ignore_patterns=ALLOW)
        except Exception as exc:
            print(f"FAILED: {repo}: {type(exc).__name__}")
            return 1
    if missing == 0:
        print("all reader weights already cached")
    print("cached under data/models/hf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
