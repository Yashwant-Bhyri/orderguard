"""Trivial reader baselines used to prove the bench end to end.

These are not contenders for the reader lanes.  They exist so ``run.sh`` can
push two very different readers -- a constant and T03's code features through
a logistic model -- through the same Case, rendering and metric pipeline.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from og_s1.checks import FEATURE_NAMES, GROUPS
from og_s1.readers.base import QUESTIONS, BaseReader, validate_scores

CAUSE_GROUPS: tuple[str, ...] = (
    "drift",
    "unsupported_claim",
    "misquote",
    "poisoned_note",
    "authority_spoof",
    "stale_thesis",
)


class CodeLogisticReader(BaseReader):
    """T03 causal features through one logistic risk model.

    The reader answers every question with the same action-level risk.  That is
    deliberately trivial: it is a pipeline probe, not a per-question reader.
    ``supported`` is the complement of the risk, the other questions are the
    risk itself.
    """

    name = "code_features_logistic"

    def __init__(self, seed: int = 20261119, c: float = 1.0) -> None:
        self.seed = int(seed)
        self.c = float(c)
        self._model: Any = None
        self._constant: float | None = None
        self._names: tuple[str, ...] = tuple(FEATURE_NAMES)

    def _matrix(self, cases: Sequence[Any]) -> np.ndarray:
        if not cases:
            return np.zeros((0, len(self._names)), dtype=float)
        rows = []
        names = tuple(cases[0].code_feature_names) if cases[0].code_feature_names else self._names
        if names != self._names:
            self._names = names
        for case in cases:
            if len(case.code_features) != len(self._names):
                raise ValueError(
                    f"case {case.case_id} has {len(case.code_features)} code features; "
                    f"expected {len(self._names)}"
                )
            rows.append(case.code_features)
        return np.asarray(rows, dtype=float)

    def fit(self, cases: Sequence[Any], y: Sequence[Any]) -> "CodeLogisticReader":
        names = tuple(cases[0].code_feature_names) if cases else self._names
        return self.fit_features(self._matrix(cases), y, names)

    def fit_features(
        self,
        X: Any,
        y: Sequence[Any],
        feature_names: Sequence[str] | None = None,
    ) -> "CodeLogisticReader":
        """Fit directly on a feature matrix (the bench's low-memory path)."""
        y_arr = np.asarray(list(y), dtype=float).ravel()
        X = np.asarray(X, dtype=float)
        if X.ndim != 2:
            raise ValueError("X must be a 2-D feature matrix")
        if feature_names is not None:
            self._names = tuple(str(n) for n in feature_names)
        if X.shape[0] != y_arr.size:
            raise ValueError("X and y must align")
        if X.shape[0] == 0:
            raise ValueError("cannot fit on zero cases")
        if np.unique(y_arr).size < 2:
            self._constant = float(y_arr.mean()) if y_arr.size else 0.0
            self._model = None
            return self
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        self._constant = None
        self._model = make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=self.c,
                solver="lbfgs",
                max_iter=2000,
                random_state=self.seed,
            ),
        )
        self._model.fit(X, y_arr.astype(int))
        return self

    def _prob(self, cases: Sequence[Any]) -> np.ndarray:
        if not cases:
            return np.zeros(0, dtype=float)
        if self._model is None:
            if self._constant is None:
                raise RuntimeError("CodeLogisticReader.fit() has not been called")
            return np.full(len(cases), float(self._constant), dtype=float)
        X = self._matrix(cases)
        prob = self._model.predict_proba(X)[:, 1]
        return np.clip(np.asarray(prob, dtype=float), 0.0, 1.0)

    def score(
        self,
        cases: Sequence[Any],
        rendering: str = "raw",
    ) -> dict[str, list[float | None]]:
        prob = self._prob(cases)
        supported = [float(1.0 - p) for p in prob]
        risk = [float(p) for p in prob]
        out = {
            "supported": supported,
            "hype": list(risk),
            "authority": list(risk),
            "addresses_reviewer": list(risk),
        }
        return validate_scores(out, len(cases))

    def cause_scores(
        self,
        cases: Sequence[Any],
        rendering: str = "raw",
    ) -> dict[str, list[float]] | None:
        if not cases:
            return {cause: [] for cause in CAUSE_GROUPS}
        X = self._matrix(cases)
        names = list(self._names)
        out: dict[str, list[float]] = {}
        for cause in CAUSE_GROUPS:
            indices = [j for j, name in enumerate(names) if GROUPS.get(name) == cause]
            if indices:
                values = np.max(X[:, indices], axis=1)
            else:
                values = np.zeros(X.shape[0], dtype=float)
            out[cause] = [float(v) for v in values]
        return out

    def cause_argmax(
        self,
        cases: Sequence[Any],
        rendering: str = "raw",
    ) -> list[str]:
        scores = self.cause_scores(cases, rendering)
        if not scores:
            return ["clean"] * len(cases)
        columns = [scores[cause] for cause in CAUSE_GROUPS]
        out: list[str] = []
        for i in range(len(cases)):
            best_cause = "clean"
            best = 0.5
            for cause, column in zip(CAUSE_GROUPS, columns):
                value = column[i]
                if value > best:
                    best = value
                    best_cause = cause
            out.append(best_cause)
        return out

    def pointers(
        self,
        cases: Sequence[Any],
        rendering: str = "raw",
    ) -> list[list[str]] | None:
        out: list[list[str]] = []
        for case in cases:
            hits: set[str] = set()
            for claim in case.claims:
                if claim.has_source and not claim.source_available and claim.source_doc:
                    hits.add(str(claim.source_doc))
                    continue
                if not claim.source_available:
                    continue
                if not claim.quoted_span_present or not claim.quoted_span_in_source:
                    if claim.source_doc:
                        hits.add(str(claim.source_doc))
                elif claim.value_matches_source_fact is False and claim.source_doc:
                    hits.add(str(claim.source_doc))
            if not hits:
                for note in case.notes:
                    if not note.available:
                        hits.add(str(note.id))
                    elif (
                        note.written_by in ("external", "tool")
                        and not note.signature_valid
                    ):
                        hits.add(str(note.id))
                    elif any(doc.trust_tier == 0 for doc in note.cited_docs):
                        hits.add(str(note.id))
            out.append(sorted(hits))
        return out
