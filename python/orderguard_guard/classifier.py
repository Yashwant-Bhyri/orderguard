"""Local prompt-injection / manipulation classifier: a fast, offline first stage of L2.

A linear model (char n-gram + word TF-IDF, logistic regression) trained by `orderguard_lab.train_classifier` on OrderGuard's own
attack lab and sandbox, exported as plain JSON (data/models/injection_clf.json) and evaluated here in pure Python: no sklearn, numpy
or pickle at runtime. The feature functions below are the single definition used both to train and to score, so the two cannot drift.

    score(text) -> {"p_attack": float, "label": "attack"|"clean", "top_features": [...]}

A chunk is split into lines (paragraphs, feed events, page lines); each line is scored and the chunk takes the maximum. Text goes through
L1 `normalise.clean()` first; invisible Unicode-tag text is decoded and scored as its own line, so a smuggled directive is read, not lost.
This is a cheap screen trained on synthetic attacks, not a security boundary: see docs/CLASSIFIER.md for the measured limits.
"""
from __future__ import annotations

import functools
import json
import math
import re
from pathlib import Path

from .normalise import TAG_HI, TAG_LO, clean

ARTIFACT = Path(__file__).resolve().parents[2] / "data" / "models" / "injection_clf.json"
FORMAT = "orderguard-injection-clf/1"
MIN_LINE_CHARS = 6
MAX_LINES = 400
MAX_LINE_CHARS = 4000
MAX_CHARS = 60000

_WS = re.compile(r"\s+")
_WORD = re.compile(r"(?u)\b\w\w+\b")
_DIGITS = re.compile(r"\d")


# ---- features (shared by training and inference) ---------------------------------------------------------------------

def prepare_lines(text: str) -> list[str]:
    """L1-clean `text` and return the lines to score (hidden Unicode-tag text, decoded, is added as its own line)."""
    text = (text or "")[:MAX_CHARS]
    extra = ""
    if any(TAG_LO <= ord(c) <= TAG_HI for c in text):
        extra = "".join(chr(ord(c) - TAG_LO) for c in text if 0x20 <= ord(c) - TAG_LO < 0x7F)
    cleaned, _ = clean(text)
    lines = [ln.strip() for ln in cleaned.split("\n")] + ([extra.strip()] if extra.strip() else [])
    return [ln[:MAX_LINE_CHARS] for ln in lines if len(ln) >= MIN_LINE_CHARS][:MAX_LINES]


def _norm(line: str) -> str:
    return _DIGITS.sub("0", _WS.sub(" ", line.lower()))


@functools.lru_cache(maxsize=200_000)
def analyze_char(line: str, lo: int = 3, hi: int = 5) -> tuple:
    """Character n-grams inside word boundaries (like sklearn 'char_wb'), digits folded to 0."""
    out = []
    for w in _norm(line).split():
        w = f" {w} "
        for n in range(lo, hi + 1):
            if len(w) < n:
                continue
            out.extend(w[i:i + n] for i in range(len(w) - n + 1))
    return tuple(out)


@functools.lru_cache(maxsize=200_000)
def analyze_word(line: str, lo: int = 1, hi: int = 2) -> tuple:
    toks = _WORD.findall(_norm(line))
    out = []
    for n in range(lo, hi + 1):
        out.extend(" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1))
    return tuple(out)


ANALYZERS = {"char": analyze_char, "word": analyze_word}


# ---- model ---------------------------------------------------------------------------------------------------------------

class Classifier:
    def __init__(self, art: dict):
        if art.get("format") != FORMAT:
            raise ValueError(f"unsupported classifier artifact format {art.get('format')!r}")
        self.meta = {k: art[k] for k in ("format", "threshold", "prefilter_threshold", "metrics", "training_data_sha256", "config") if k in art}
        self.threshold = float(art["threshold"])
        self.prefilter_threshold = float(art.get("prefilter_threshold", max(self.threshold, 0.9)))
        self.intercept = float(art["intercept"])
        self.blocks: dict[str, dict[str, tuple[float, float]]] = {}
        for name, b in art["blocks"].items():
            self.blocks[name] = {t: (i, c) for t, i, c in zip(b["terms"], b["idf"], b["coef"])}

    def _line_logit(self, line: str, explain: bool = False):
        z = self.intercept
        contrib: list[tuple[float, str]] = []
        for name, table in self.blocks.items():
            counts: dict[str, int] = {}
            for g in ANALYZERS[name](line):
                if g in table:
                    counts[g] = counts.get(g, 0) + 1
            if not counts:
                continue
            w = {g: (1.0 + math.log(c)) * table[g][0] for g, c in counts.items()}
            norm = math.sqrt(sum(v * v for v in w.values()))
            for g, v in w.items():
                x = v / norm * table[g][1]
                z += x
                if explain:
                    contrib.append((x, g if name == "word" else f"~{g.strip() or g}"))
        return z, contrib

    @staticmethod
    def _sigmoid(z: float) -> float:
        return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))

    def score_lines(self, lines: list[str]) -> list[float]:
        return [self._sigmoid(self._line_logit(ln)[0]) for ln in lines]

    def score(self, text: str, *, top: int = 5) -> dict:
        lines = prepare_lines(text)
        if not lines:
            return {"p_attack": 0.0, "label": "clean", "top_features": [], "line": ""}
        best_z, best_line, best_contrib = -1e9, "", []
        for ln in lines:
            z, contrib = self._line_logit(ln, explain=True)
            if z > best_z:
                best_z, best_line, best_contrib = z, ln, contrib
        p = self._sigmoid(best_z)
        feats = [{"feature": g, "weight": round(x, 4)} for x, g in sorted(best_contrib, reverse=True)[:top] if x > 0]
        return {"p_attack": p, "label": "attack" if p >= self.threshold else "clean", "top_features": feats, "line": best_line[:200]}


def load(path: Path | str | None = None) -> Classifier:
    p = Path(path) if path else ARTIFACT
    return Classifier(json.loads(p.read_text()))


@functools.lru_cache(maxsize=4)
def _cached(path: str) -> Classifier:
    return load(path)


def get(path: Path | str | None = None) -> Classifier:
    """Cached loader: the artifact is parsed once per process."""
    return _cached(str(path or ARTIFACT))


def score(text: str, path: Path | str | None = None) -> dict:
    return get(path).score(text)
