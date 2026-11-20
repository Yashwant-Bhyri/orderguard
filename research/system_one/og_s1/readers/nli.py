"""Zero-shot DeBERTa-v3 NLI reader.

One cross-encoder serves all three sub-questions:

* ``support_gap`` is ``1 - P(entailment)`` with the cited document as premise
  and the claim as hypothesis.
* ``hype`` and ``authority_language`` are two-way zero-shot classifications.
  Each candidate sentence is scored by the entailment logit, and the two logits
  are softmaxed into a probability.  Two paraphrases per side are averaged to
  reduce template sensitivity.

The checkpoint is the MIT-licensed ``MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli``
(MNLI + FEVER + ANLI).  It is small enough to run on a laptop (MPS or CPU) and
was chosen over a large model for latency; see REPORT.md for the trade-off.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

NAME = "nli"
KIND = "text+pair"

MODEL_ID = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
LICENCE = "MIT"
MAX_LENGTH = 512
BATCH = 16


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _hf_home() -> str:
    env = os.environ.get("OG_S1_HF_HOME")
    if env:
        return os.path.abspath(env)
    return str(_root() / "data" / "models" / "hf")


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


class _Model:
    def __init__(self, device: str | None = None) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.device = device or default_device()
        cache = _hf_home()
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=cache, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            MODEL_ID, cache_dir=cache, local_files_only=True
        )
        self.model.to(self.device).eval()
        labels = {int(k): str(v).lower() for k, v in self.model.config.id2label.items()}
        self.entail_idx = next(
            (i for i, label in labels.items() if "entail" in label), 0
        )
        self.id2label = labels

    def _entail_logits(self, pairs: list[tuple[str, str]]) -> list[float]:
        import numpy as np

        if not pairs:
            return []
        out: list[float] = []
        with self.torch.inference_mode():
            for start in range(0, len(pairs), BATCH):
                chunk = pairs[start : start + BATCH]
                batch = self.tokenizer(
                    [p[0] for p in chunk],
                    [p[1] for p in chunk],
                    return_tensors="pt",
                    truncation=True,
                    padding=True,
                    max_length=MAX_LENGTH,
                ).to(self.device)
                logits = self.model(**batch).logits.float().cpu().numpy()
                out.extend(float(row[self.entail_idx]) for row in logits)
        return out

    def _entail_probs_three(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Exact P(entailment) from the three-way softmax (used for support)."""
        import numpy as np

        if not pairs:
            return []
        probs: list[float] = []
        with self.torch.inference_mode():
            for start in range(0, len(pairs), BATCH):
                chunk = pairs[start : start + BATCH]
                batch = self.tokenizer(
                    [p[0] for p in chunk],
                    [p[1] for p in chunk],
                    return_tensors="pt",
                    truncation=True,
                    padding=True,
                    max_length=MAX_LENGTH,
                ).to(self.device)
                logits = self.model(**batch).logits.float()
                soft = self.torch.softmax(logits, dim=-1).cpu().numpy()
                probs.extend(float(row[self.entail_idx]) for row in soft)
        return probs

    def two_way(self, pairs: list[tuple[str, str]]) -> list[float]:
        """P(first hypothesis) from entailment logits of two hypotheses."""
        import numpy as np

        logits = np.asarray(self._entail_logits(pairs), dtype=float)
        scores: list[float] = []
        for i in range(0, logits.size, 2):
            a, b = logits[i], logits[i + 1]
            m = max(a, b)
            ea, eb = np.exp(a - m), np.exp(b - m)
            scores.append(float(ea / (ea + eb)))
        return scores


_MODEL: _Model | None = None
_MODEL_DEVICE: str | None = None


def _model(device: str | None = None) -> _Model:
    global _MODEL, _MODEL_DEVICE
    want = device or default_device()
    if _MODEL is None or _MODEL_DEVICE != want:
        _MODEL = _Model(want)
        _MODEL_DEVICE = want
    return _MODEL


HYPE_SIDES = [
    (
        "This passage uses promotional or vague language instead of concrete facts.",
        "This passage uses measured, factual language with concrete figures.",
    ),
    (
        "This text is hype: enthusiastic claims with little specific evidence.",
        "This text is sober and specific, citing numbers and sources.",
    ),
]

AUTHORITY_SIDES = [
    (
        "This text claims that a restriction has been lifted.",
        "This text makes no claim that a restriction has been lifted.",
    ),
]


def score_texts_with_sides(
    texts: list[str],
    sides: list[tuple[str, str]],
    device: str | None = None,
) -> list[float]:
    """Score raw texts with a caller-supplied list of ``(positive, negative)`` pairs.

    This is the sensitivity hook: a template is fixed before it is scored, and
    the caller records every template's AUROC rather than only the one that
    ended up in ``AUTHORITY_SIDES``.
    """
    import numpy as np

    model = _model(device)
    pairs: list[tuple[str, str]] = []
    for text in texts:
        for pos, neg in sides:
            pairs.extend([(str(text), pos), (str(text), neg)])
    raw = model.two_way(pairs)
    width = len(sides)
    return [
        float(np.mean(raw[k * width : (k + 1) * width])) for k in range(len(texts))
    ]


def score(items: list[dict[str, Any]], device: str | None = None) -> "Any":
    import numpy as np

    model = _model(device)
    out = np.full(len(items), np.nan, dtype=float)

    for feature, sides in (("hype", HYPE_SIDES), ("authority_language", AUTHORITY_SIDES)):
        idx = [i for i, it in enumerate(items) if it.get("feature") == feature]
        if not idx:
            continue
        pairs: list[tuple[str, str]] = []
        for i in idx:
            text = str(items[i].get("text", ""))
            for pos, neg in sides:
                pairs.extend([(text, pos), (text, neg)])
        raw = model.two_way(pairs)
        width = len(sides)
        for k, i in enumerate(idx):
            out[i] = float(np.mean(raw[k * width : (k + 1) * width]))

    pair_idx = [i for i, it in enumerate(items) if it.get("feature") == "support_gap"]
    if pair_idx:
        pairs = [
            (str(items[i].get("premise", "")), str(items[i].get("hypothesis", "")))
            for i in pair_idx
        ]
        probs = model._entail_probs_three(pairs)
        for i, p in zip(pair_idx, probs):
            out[i] = float(min(1.0, max(0.0, 1.0 - p)))

    out = np.nan_to_num(out, nan=0.5)
    return np.clip(out, 0.0, 1.0)
