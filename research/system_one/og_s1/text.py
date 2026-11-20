"""Bounded text channel: three risk-only features per action.

The channel reads only ``og_s1.schema.model_view_at(episode, i)``.  It never
sees labels, ``meta``, or any document/note written after action ``i``.  Every
feature is in [0, 1] and higher means riskier, so a monotone-increasing term in
the glass-box scorer can only raise risk.

Features
--------
``hype``
    Promotional or vague language in the action's claims and rationale.
``authority_language``
    Text in the rationale or in notes the action cites that asserts a
    permission, approval, exception, or instruction to a reviewer.
``support_gap``
    ``1 - P(cited document entails claim)``.  For a claim with no source the
    per-claim value is 0.5; the action-level feature is the worst claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from og_s1.schema import model_view_at

FEATURES = ("hype", "authority_language", "support_gap")

# The winner per sub-question is filled from the T05 reader tournament.  A
# single mapping keeps T07's integration explicit and swappable.
#
# Authority is deliberately the pre-registered generic decision-model
# question.  The NLI authority hypothesis was selected on shifted ref, so the
# lead ruled it out of the pass bar and out of the channel default
# (SOL_ADVICE.md, round-4 addendum).  It remains a named sensitivity reader.
# If the decision reader has neither a cached response nor a key, the channel
# returns NaN for authority (the array encoding of ``None``) and records a
# reason in ``TextChannel.last_reasons``; it never falls back to NLI.
DEFAULT_READERS = {
    "hype": "nli",
    "authority_language": "decision",
    "support_gap": "nli",
}

SUPPORT_NEUTRAL = 0.5


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _join(parts: list[str]) -> str:
    return " ".join(p for p in (_clean(x) for x in parts) if p)


def action_texts(view: dict[str, Any]) -> dict[str, Any]:
    """Extract the text fields the channel is allowed to read for one action."""
    action = view.get("action") or {}
    notes_by_id = {str(n.get("id")): n for n in view.get("notes") or []}
    docs_by_id = {str(d.get("id")): d for d in view.get("documents") or []}

    claims = action.get("claims") or []
    claim_texts = [_clean(c.get("text")) for c in claims]
    rationale = _clean(action.get("rationale"))

    cited_notes = []
    for note_id in action.get("cites_notes") or []:
        note = notes_by_id.get(str(note_id))
        if note is not None:
            cited_notes.append(note)
    note_texts = [_clean(n.get("text")) for n in cited_notes]

    pairs: list[tuple[str, str]] = []
    unsourced = 0
    for claim in claims:
        source = claim.get("source_doc")
        doc = docs_by_id.get(str(source)) if source is not None else None
        if doc is None:
            unsourced += 1
        else:
            pairs.append((_clean(doc.get("text")), _clean(claim.get("text"))))

    return {
        "rationale": rationale,
        "claim_texts": claim_texts,
        "note_texts": note_texts,
        "pairs": pairs,
        "unsourced": unsourced,
        "n_claims": len(claims),
        "hype_text": _join([rationale] + claim_texts),
        "authority_text": _join([rationale] + note_texts),
    }


def make_items(view: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """All reader items for one action, grouped by feature.

    Hype and authority are scored sentence by sentence (rationale, each claim,
    each cited note) and aggregated with a max.  A single promotional claim is
    evidence even when the action also states several facts; concatenating the
    text first would let the facts drown it.
    """
    t = action_texts(view)
    hype_texts = [x for x in [t["rationale"]] + t["claim_texts"] if x]
    authority_texts = [x for x in [t["rationale"]] + t["note_texts"] if x]
    return {
        "hype": [{"feature": "hype", "text": text} for text in hype_texts],
        "authority_language": [
            {"feature": "authority_language", "text": text} for text in authority_texts
        ],
        "support_gap": [
            {"feature": "support_gap", "premise": premise, "hypothesis": claim}
            for premise, claim in t["pairs"]
        ],
    }


def make_decision_item(view: dict[str, Any]) -> dict[str, Any]:
    """The action-level state and three questions for the external model."""
    from og_s1.readers.decision import QUESTIONS

    t = action_texts(view)
    state = {
        "rationale": t["rationale"],
        "claim_texts": t["claim_texts"],
        "cited_note_texts": t["note_texts"],
        "claim_document_pairs": [
            {"claim": claim, "document": premise} for premise, claim in t["pairs"]
        ],
    }
    return {
        "state": state,
        "questions": {
            name: {"type": "noul", "instructions": QUESTIONS[name]}
            for name in FEATURES
        },
        "support_override": SUPPORT_NEUTRAL if not t["pairs"] else None,
    }


def score_groups(module: Any, items: dict[str, list[dict[str, Any]]], unsourced: int, **kwargs: Any) -> tuple[float, float, float]:
    """Score one action's items with one reader and aggregate per feature."""
    raw = module.score(
        items["hype"] + items["authority_language"] + items["support_gap"], **kwargs
    )
    n_h = len(items["hype"])
    n_a = len(items["authority_language"])
    hype = float(max(raw[:n_h])) if n_h else SUPPORT_NEUTRAL
    authority = float(max(raw[n_h : n_h + n_a])) if n_a else SUPPORT_NEUTRAL
    support = _aggregate_support(list(raw[n_h + n_a :]), unsourced)
    return hype, authority, support


def _aggregate_support(scores: list[float], unsourced: int) -> float:
    values = [float(x) for x in scores]
    if unsourced:
        values.extend([SUPPORT_NEUTRAL] * int(unsourced))
    if not values:
        return SUPPORT_NEUTRAL
    return float(min(1.0, max(0.0, max(values))))


class TextChannel:
    """A reader per sub-question, scored causally one action at a time."""

    def __init__(
        self,
        hype: str | None = None,
        authority_language: str | None = None,
        support_gap: str | None = None,
        device: str | None = None,
    ) -> None:
        self.mapping = {
            "hype": hype or DEFAULT_READERS["hype"],
            "authority_language": authority_language or DEFAULT_READERS["authority_language"],
            "support_gap": support_gap or DEFAULT_READERS["support_gap"],
        }
        self.device = device
        self._modules: dict[str, Any] = {}
        # Why a feature is None/NaN (for example a missing decision cache/key).
        self.last_reasons: dict[str, str] = {}

    def _module(self, name: str):
        if name not in self._modules:
            from og_s1 import readers

            if name not in readers.READERS:
                raise ValueError(f"unknown reader {name!r}")
            self._modules[name] = readers.READERS[name]
        return self._modules[name]

    def score_view(self, view: dict[str, Any]) -> np.ndarray:
        self.last_reasons = {}
        items = make_items(view)
        texts = action_texts(view)
        out = np.full(len(FEATURES), SUPPORT_NEUTRAL, dtype=float)
        decision_item = None
        if "decision" in self.mapping.values():
            decision_item = make_decision_item(view)

        local = [f for f in FEATURES if self.mapping[f] != "decision"]
        if local and any(items[f] or f == "support_gap" for f in local):
            by_reader: dict[str, list[str]] = {}
            for feature in local:
                by_reader.setdefault(self.mapping[feature], []).append(feature)
            results: dict[str, float] = {}
            for name, features in by_reader.items():
                subset = [it for feature in features for it in items[feature]]
                raw = self._module(name).score(subset, **self._kwargs(name))
                pos = 0
                for feature in features:
                    chunk = raw[pos : pos + len(items[feature])]
                    pos += len(items[feature])
                    if feature == "support_gap":
                        results[feature] = _aggregate_support(list(chunk), texts["unsourced"])
                    else:
                        results[feature] = float(max(chunk)) if len(chunk) else SUPPORT_NEUTRAL
            for col, feature in enumerate(FEATURES):
                if feature in results:
                    out[col] = results[feature]

        decision_features = [f for f in FEATURES if self.mapping[f] == "decision"]
        if decision_item is not None and decision_features:
            try:
                row = self._module("decision").score([decision_item], workers=1)[0]
            except Exception as exc:
                # The lead's rule: authority has no local fallback.  Return
                # None (NaN in the float array) and say why.
                reason = f"decision reader unavailable: {type(exc).__name__}: {exc}"
                for feature in decision_features:
                    out[FEATURES.index(feature)] = np.nan
                    self.last_reasons[feature] = reason
            else:
                for feature in decision_features:
                    col = FEATURES.index(feature)
                    value = float(row[col])
                    if not np.isfinite(value):
                        out[col] = np.nan
                        self.last_reasons[feature] = "decision reader returned no answer"
                    else:
                        out[col] = value
        return np.clip(out, 0.0, 1.0)

    def _kwargs(self, name: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.device is not None and name in ("nli", "embed_lr", "injection"):
            kwargs["device"] = self.device
        return kwargs

    def features_at(self, episode: Any, i: int) -> np.ndarray:
        return self.score_view(model_view_at(episode, i))

    def features(self, episode: Any) -> np.ndarray:
        n = _n_steps(episode)
        if n == 0:
            return np.zeros((0, len(FEATURES)), dtype=float)
        rows = [self.score_view(model_view_at(episode, i)) for i in range(n)]
        return np.asarray(rows, dtype=float)


def _n_steps(episode: Any) -> int:
    if hasattr(episode, "steps"):
        return len(episode.steps)  # type: ignore[union-attr]
    return len(episode.get("steps") or [])


_DEFAULT_CHANNEL: TextChannel | None = None


def default_channel() -> TextChannel:
    global _DEFAULT_CHANNEL
    if _DEFAULT_CHANNEL is None:
        _DEFAULT_CHANNEL = TextChannel()
    return _DEFAULT_CHANNEL


def features(episode: Any, channel: TextChannel | None = None) -> np.ndarray:
    """Return ``(n_actions, 3)`` in T03's action order, using cached readers."""
    return (channel or default_channel()).features(episode)


def feature_names() -> list[str]:
    return list(FEATURES)


def max_logit_bound(scores: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """Placeholder bound on each feature's logit contribution.

    The final scorer is T07's.  For a univariate monotone logistic term fitted
    to ``P(any failure)``, the largest change in log-odds across the feature's
    observed [0, 1] range is the fitted slope.  We return that slope per
    feature, plus the unit-weight bound (1.0) that holds for any monotone term
    whose input is the raw feature.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    y = np.asarray(y, dtype=int)
    out: dict[str, float] = {}
    for j, name in enumerate(FEATURES):
        x = np.asarray(scores[:, j], dtype=float).reshape(-1, 1)
        if len(np.unique(y)) < 2 or np.allclose(x, x[0]):
            out[name] = 1.0
            continue
        model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
        model.fit(x, y)
        out[name] = float(max(0.0, model.coef_[0, 0]))
    return out


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]
