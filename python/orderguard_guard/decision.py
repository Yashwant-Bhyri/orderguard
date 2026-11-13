"""Explainable decision layer over the local classifier (L2 stage 1).

A small logistic regression over a handful of structured features, exported as JSON inside the classifier artifact and evaluated in pure
Python. Features: the classifier's max-line logit (and the mean of its top two lines), L1 findings (hidden characters, mixed scripts,
base64, tag smuggling), cues that text addresses an AI, imperative-to-agent phrasing, money-movement and mandate vocabulary, numeric
density, the share of CJK letters, and benign-cue phrases ("please refer to note 7") that push the other way.

Not here, on purpose: a numbers-versus-trusted-figure check. L2 has no trusted figures, so a plausible edited number looks identical to a
true one. Data-lie detection belongs to L5/L6 (figure lookup and price checks); this layer does not pretend to do it.
"""
from __future__ import annotations

import math
import re

FEATURES = ("z_max", "z_top2", "hidden_chars", "mixed_script", "base64", "agent_address", "imperative_to_agent", "money_move",
            "mandate_words", "digit_density", "money_amounts", "cjk_share", "benign_cues", "log_lines")
Z_CLIP = 12.0

_AGENT = re.compile(r"\b(?:ai|a\.i\.|llm|assistants?|agents?|bots?|models?|automated (?:systems?|trading|agents?)|trading (?:systems?|agents?|assistants?)|"
                    r"processors?|copilots?|language models?|machine readers?)\b", re.I)
_IMPER = re.compile(r"\b(?:ignore|disregard|override|forget|bypass|you (?:must|should|shall|will|are required)|(?:must|shall) (?:now )?(?:sell|buy|place|execute|send|transfer|"
                    r"raise|increase|set)|do not (?:mention|tell|reveal|disclose|inform|alert)|don'?t (?:mention|tell)|always|never|immediately|at once|without (?:asking|confirmation|review)|"
                    r"from now on|new instructions?|instead)\b", re.I)
_AGENT_IMPER = re.compile(r"(?:\b(?:ai|llm|assistants?|agents?|bots?|models?|systems?|processors?)\b[^.\n]{0,60}"
                          r"\b(?:must|should|shall|ignore|disregard|do not|never|always|override|execute|sell|buy|transfer)\b)|"
                          r"(?:\b(?:ignore|disregard|override|forget)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|your|all|any)\b[^.\n]{0,30}"
                          r"\b(?:instructions?|rules?|limits?|mandate|guidelines|prompts?)\b)", re.I)
_MONEY = re.compile(r"\b(?:sell (?:all|the entire|everything)|liquidate|wire|transfer|withdraw|withdrawal|deposit|short(?:ing)? (?:all|the)|place (?:an? )?(?:order|trade)|"
                    r"market order|buy (?:\d|all|the)|entire position|full position|raise (?:the )?(?:order|position|risk)? ?limits?|order size|settle)\b", re.I)
_MANDATE = re.compile(r"\b(?:mandate|risk limits?|position limits?|order limits?|permissions?|authori[sz](?:ed|ation|e)|override|compliance (?:officer|desk)|"
                      r"supersed(?:es|ed)|effective immediately|policy update|margin call|new limits?|suspend(?:ed)? (?:the )?(?:limits|checks))\b", re.I)
_AMOUNT = re.compile(r"[$€£]\s?\d[\d,\.]*\s?(?:[kmb]|million|billion|thousand)?\b|\b\d[\d,\.]*\s?(?:%|percent|bps)\b", re.I)
_BENIGN = re.compile(r"\b(?:investors should (?:consider|review|read|carefully)|please (?:refer|see)|refer to note|see note|see (?:part|item) [ivx\d]|should be read in conjunction|"
                     r"readers? (?:should|are encouraged)|stockholders? (?:should|are urged)|for (?:more|further) information|forward-looking statements)\b", re.I)
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")


def text_features(lines: list[str], findings: list[str], tag_payload: bool) -> dict[str, float]:
    """Everything except the classifier logits, from the L1-cleaned lines and L1 findings."""
    body = "\n".join(lines)
    n = max(1, len(body))
    fl = " ".join(findings)
    letters = sum(c.isalpha() for c in body) or 1
    return {
        "hidden_chars": 1.0 if (tag_payload or "zero-width" in fl or "bidi" in fl or "tag" in fl) else 0.0,
        "mixed_script": 1.0 if "mixed-script" in fl else 0.0,
        "base64": 1.0 if "base64" in fl else 0.0,
        "agent_address": float(min(3, len(_AGENT.findall(body)))),
        "imperative_to_agent": float(min(3, len(_AGENT_IMPER.findall(body)) + (1 if _IMPER.search(body) and _AGENT.search(body) else 0))),
        "money_move": float(min(3, len(_MONEY.findall(body)))),
        "mandate_words": float(min(3, len(_MANDATE.findall(body)))),
        "digit_density": min(0.5, sum(c.isdigit() for c in body) / n),
        "money_amounts": min(10, len(_AMOUNT.findall(body))) / 10.0,
        "cjk_share": min(1.0, len(_CJK.findall(body)) / letters),
        "benign_cues": float(min(3, len(_BENIGN.findall(body)))),
        "log_lines": math.log1p(len(lines)),
    }


def vector(tf: dict[str, float], z_sorted_desc: list[float]) -> list[float]:
    """Feature vector in FEATURES order; z_sorted_desc are the chunk's line logits, highest first."""
    clip = lambda z: max(-Z_CLIP, min(Z_CLIP, z))
    z1 = clip(z_sorted_desc[0]) if z_sorted_desc else -Z_CLIP
    z2 = clip(sum(z_sorted_desc[:2]) / min(2, len(z_sorted_desc))) if z_sorted_desc else -Z_CLIP
    d = dict(tf, z_max=z1, z_top2=z2)
    return [float(d[k]) for k in FEATURES]


class Decision:
    def __init__(self, art: dict):
        self.features = tuple(art["features"])
        if self.features != FEATURES:
            raise ValueError("decision model feature list does not match this code")
        self.mean, self.scale, self.coef = art["mean"], art["scale"], art["coef"]
        self.intercept = float(art["intercept"])

    def logit(self, x: list[float]) -> float:
        return self.intercept + sum(c * (v - m) / s for v, m, s, c in zip(x, self.mean, self.scale, self.coef))

    def explain(self, x: list[float], top: int = 4) -> list[dict]:
        parts = [(c * (v - m) / s, f, v) for v, m, s, c, f in zip(x, self.mean, self.scale, self.coef, self.features)]
        return [{"feature": f, "value": round(v, 3), "contribution": round(c, 3)} for c, f, v in sorted(parts, key=lambda t: -abs(t[0]))[:top]]
