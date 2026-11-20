"""Purpose-built prompt-injection classifiers for ``authority_language``.

Two small, permissively licensed encoders are wrapped behind one interface:

* ``protectai/deberta-v3-base-prompt-injection-v2`` (Apache-2.0)
* ``fmops/distilbert-prompt-injection`` (Apache-2.0)

The current Meta Prompt Guard 2 checkpoints (86M and 22M) are gated on Hugging
Face and could not be fetched without an account token; this is recorded in
REPORT.md rather than worked around.

The classifier was trained to catch jailbreak-style instructions.  We use its
injection probability as the risk score for authority claims.  It sees only the
action's rationale and the text of notes the action cites; it never sees note
provenance fields or labels.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

NAME = "injection"
KIND = "text"
DEVICE = "mps"

MODELS = {
    "protectai": {
        "id": "protectai/deberta-v3-base-prompt-injection-v2",
        "licence": "Apache-2.0",
        "positive_label": "injection",
    },
    "fmops": {
        "id": "fmops/distilbert-prompt-injection",
        "licence": "Apache-2.0",
        "positive_label": "label_1",
    },
}

MAX_LENGTH = 256
BATCH = 16


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cache() -> str:
    env = os.environ.get("OG_S1_HF_HOME")
    return os.path.abspath(env) if env else str(_root() / "data" / "models" / "hf")


def default_device() -> str:
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


class _Classifier:
    def __init__(self, variant: str, device: str | None = None) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        meta = MODELS[variant]
        self.torch = torch
        self.device = device or default_device()
        cache = _cache()
        self.tokenizer = AutoTokenizer.from_pretrained(meta["id"], cache_dir=cache, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            meta["id"], cache_dir=cache, local_files_only=True
        )
        self.model.to(self.device).eval()
        labels = {int(k): str(v).lower() for k, v in self.model.config.id2label.items()}
        target = meta["positive_label"]
        self.pos_idx = next(
            (i for i, label in labels.items() if target in label),
            next((i for i, label in labels.items() if "inject" in label), 1),
        )

    def probs(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        out: list[float] = []
        with self.torch.inference_mode():
            for start in range(0, len(texts), BATCH):
                chunk = texts[start : start + BATCH]
                batch = self.tokenizer(
                    chunk,
                    return_tensors="pt",
                    truncation=True,
                    padding=True,
                    max_length=MAX_LENGTH,
                ).to(self.device)
                logits = self.model(**batch).logits.float()
                soft = self.torch.softmax(logits, dim=-1).cpu().numpy()
                out.extend(float(row[self.pos_idx]) for row in soft)
        return out


_CACHE: dict[str, _Classifier] = {}


def _get(variant: str, device: str | None = None) -> _Classifier:
    key = f"{variant}:{device or default_device()}"
    if key not in _CACHE:
        _CACHE[key] = _Classifier(variant, device)
    return _CACHE[key]


def score(items: list[dict[str, Any]], variant: str = "protectai", device: str | None = None) -> "Any":
    import numpy as np

    clf = _get(variant, device)
    texts = [str(it.get("text", "")) for it in items]
    vals = clf.probs(texts)
    return np.clip(np.asarray(vals, dtype=float), 0.0, 1.0)


def variant_meta(variant: str = "protectai") -> dict[str, str]:
    meta = MODELS[variant]
    return {"variant": variant, "model": meta["id"], "licence": meta["licence"]}
