"""Fixed word-list reader.  This is the floor for every sub-question.

The lists are hand-written, not learned.  Scores are graded, in [0, 1], and
higher always means riskier.  The support score is a token-overlap proxy for
``1 - P(entailment)``: it rewards claim content that actually appears in the
cited document, with numbers weighted more than ordinary words.
"""

from __future__ import annotations

import math
import re
from typing import Any

NAME = "lexicon"
KIND = "text+pair"
DEVICE = "cpu"

# Promotional / vague markers.  Weights are a judgement call: a single strong
# slogan is enough to look risky, while weak intensifiers accumulate.
_HYPE = {
    "massive": 0.55,
    "huge": 0.45,
    "enormous": 0.50,
    "explosive": 0.55,
    "exploding": 0.55,
    "skyrocket": 0.60,
    "skyrocketing": 0.60,
    "soar": 0.50,
    "soaring": 0.50,
    "rocket": 0.55,
    "parabolic": 0.60,
    "unstoppable": 0.60,
    "unprecedented": 0.45,
    "revolutionary": 0.50,
    "game-changer": 0.65,
    "game changer": 0.65,
    "no-brainer": 0.65,
    "cant-miss": 0.70,
    "can't-miss": 0.70,
    "cannot-miss": 0.70,
    "must-own": 0.55,
    "must have": 0.45,
    "must-have": 0.55,
    "slam dunk": 0.65,
    "sure thing": 0.65,
    "guaranteed": 0.55,
    "risk-free": 0.70,
    "no downside": 0.60,
    "free money": 0.70,
    "easy money": 0.65,
    "incredible": 0.45,
    "amazing": 0.45,
    "phenomenal": 0.50,
    "fantastic": 0.45,
    "awesome": 0.45,
    "stellar": 0.40,
    "outstanding": 0.30,
    "exceptional": 0.30,
    "remarkable": 0.30,
    "extraordinary": 0.35,
    "tremendous": 0.45,
    "breakthrough": 0.45,
    "blowout": 0.50,
    "turbocharge": 0.50,
    "best-in-class": 0.45,
    "world-class": 0.40,
    "dominant": 0.30,
    "moon": 0.50,
    "moonshot": 0.55,
    "to the moon": 0.70,
    "bullish": 0.25,
    "upside": 0.25,
    "momentum": 0.15,
    "compelling": 0.25,
    "exciting": 0.30,
    "promising": 0.25,
    "bright": 0.15,
    "rosy": 0.35,
    "strong buy": 0.55,
    "must buy": 0.55,
    "can't lose": 0.70,
    "cannot lose": 0.70,
    "priced for perfection": 0.50,
    "once in a lifetime": 0.55,
    "generational": 0.45,
    "asymmetric": 0.20,
    "obviously": 0.35,
    "clearly": 0.15,
    "undoubtedly": 0.40,
    "without a doubt": 0.45,
    "everyone knows": 0.45,
    "it is well known": 0.40,
    "goes without saying": 0.45,
    "stands to reason": 0.35,
    "no question": 0.30,
}

# Permission / approval / exception / reviewer-instruction markers.  This is a
# deliberately small generic list: it does not try to cover every euphemism for
# "the rule changed" (for example "the owner widened the band"), which is left
# to the readers that actually parse the sentence.  That gap is the point of a
# floor.
_AUTHORITY = {
    "permission": 0.55,
    "permissions": 0.55,
    "approval": 0.50,
    "approved": 0.50,
    "approved by": 0.55,
    "authorized": 0.55,
    "authorised": 0.55,
    "authorized by": 0.60,
    "authorised by": 0.60,
    "authorization": 0.55,
    "authorisation": 0.55,
    "exception": 0.50,
    "exempt": 0.55,
    "waiver": 0.60,
    "waived": 0.60,
    "override": 0.65,
    "overrides": 0.60,
    "ignore": 0.65,
    "ignore the": 0.70,
    "ignore this": 0.70,
    "ignore all": 0.80,
    "ignore previous": 0.85,
    "disregard": 0.70,
    "bypass": 0.60,
    "pre-cleared": 0.70,
    "precleared": 0.70,
    "pre-approved": 0.70,
    "preapproved": 0.70,
    "reviewer": 0.45,
    "note to reviewer": 0.80,
    "for the reviewer": 0.70,
    "system:": 0.65,
    "assistant:": 0.65,
    "instruction:": 0.55,
    "new instructions": 0.70,
    "special permission": 0.75,
    "special approval": 0.75,
    "you may": 0.35,
    "you can": 0.30,
    "does not apply": 0.65,
    "do not apply": 0.65,
    "not apply to": 0.60,
    "is allowed to": 0.50,
    "are allowed to": 0.50,
    "granted": 0.40,
    "sanctioned": 0.40,
    "endorsed": 0.35,
}

_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "has", "have", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "this", "to", "was", "were", "we", "with", "the", "says",
    "said", "shows", "show", "figure", "data", "according", "reports",
    "reported", "report", "company", "firm", "stock", "trade", "position",
    "we", "our", "us", "i", "see", "what", "which", "while", "about", "into",
    "than", "then", "there", "these", "those", "will", "would", "can", "could",
}

_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|x|bps?|\$[bmkt])?")
_WORD = re.compile(r"[a-zA-Z][a-zA-Z'-]+")


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _weighted_hits(text: str, table: dict[str, float]) -> list[float]:
    lowered = _norm(text)
    hits: list[float] = []
    for phrase, weight in table.items():
        if phrase in lowered:
            hits.append(weight)
    return hits


def _hype(text: str) -> float:
    hits = sorted(_weighted_hits(text, _HYPE), reverse=True)
    score = 0.0
    if hits:
        score = hits[0] + 0.12 * (len(hits) - 1)
    # A passage with no digit at all is weaker evidence than one with figures.
    if score > 0.0 and not re.search(r"\d", text):
        score += 0.08
    return float(min(1.0, max(0.0, score)))


def _authority(text: str) -> float:
    hits = sorted(_weighted_hits(text, _AUTHORITY), reverse=True)
    score = 0.0
    if hits:
        score = hits[0] + 0.12 * (len(hits) - 1)
    return float(min(1.0, max(0.0, score)))


def _content(text: str) -> tuple[set[str], set[str]]:
    words = {w for w in _WORD.findall(_norm(text)) if w not in _STOP and len(w) > 2}
    numbers = {n.replace(" ", "").replace(",", "") for n in _NUM.findall(_norm(text))}
    return words, numbers


def _support_gap(premise: str, hypothesis: str) -> float:
    doc_words, doc_numbers = _content(premise)
    claim_words, claim_numbers = _content(hypothesis)
    total = 3.0 * (len(claim_numbers) + len(claim_words))
    if total <= 0.0:
        return 0.5
    matched = 3.0 * len(claim_numbers & doc_numbers) + len(claim_words & doc_words)
    support = matched / total
    # Short claims can match by accident; shrink towards the neutral prior.
    support = 0.85 * support
    return float(min(1.0, max(0.0, 1.0 - support)))


def score(items: list[dict[str, Any]]) -> "Any":
    import numpy as np

    out = []
    for item in items:
        feature = item.get("feature")
        if feature == "support_gap":
            out.append(_support_gap(item.get("premise", ""), item.get("hypothesis", "")))
        elif feature == "authority_language":
            out.append(_authority(item.get("text", "")))
        else:
            out.append(_hype(item.get("text", "")))
    return np.asarray(out, dtype=float)


def panic(value: float) -> float:
    """Small helper used by tests: clip a raw score into [0, 1]."""
    return float(min(1.0, max(0.0, value))) if math.isfinite(value) else 0.0
