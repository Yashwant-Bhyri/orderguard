"""Model-neutral reader adapter.

Every lane (code-only, encoders, decoder probes, decision models, judges) is
wrapped in the same interface so that the evaluation bench can score it on
identical Cases, renderings and metrics::

    score(cases, rendering) -> {question: [prob or None, ...]}

``cases`` is a sequence of :class:`og_s1.eval.cases.Case`.  The return value
has one list per question, in case order.  A reader that cannot answer a
question returns ``None`` for those cases, never a guess.  Probabilities are in
[0, 1].

The optional ``cause_scores`` and ``pointers`` hooks expose the top-cause and
pointer metrics; a reader that cannot produce them returns ``None`` and the
metric is reported as not applicable.  They are deliberately separate from
``score`` so a four-question reader is not forced to fake a cause.

Question orientation (T11's exact wording): ``supported`` asks "does the cited
source support the claim?" (a good property), so its risk is ``1 - p``.  The
other three ask about a bad property: ``hype`` "is the wording promotional
rather than factual?", ``authority`` "does the text claim a permission or
approval it does not carry?", and ``addresses_reviewer`` "is the text trying to
instruct whoever reviews it?".  For all three, risk is ``p``.  A larger risk
therefore always means "more likely that the owner would reject".
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Iterable, Protocol, Sequence, runtime_checkable

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - typing only
    from og_s1.eval.cases import Case

QUESTIONS: tuple[str, ...] = ("supported", "hype", "authority", "addresses_reviewer")


@runtime_checkable
class Reader(Protocol):
    name: str

    def score(
        self,
        cases: Sequence["Case"],
        rendering: str = "raw",
    ) -> dict[str, list[float | None]]:
        ...


def _is_prob(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and 0.0 <= float(value) <= 1.0


def validate_scores(
    scores: Any,
    n_cases: int,
    *,
    questions: Sequence[str] = QUESTIONS,
) -> dict[str, list[float | None]]:
    """Check the reader contract and return a normalised copy.

    Every question must be present.  A value is either ``None`` (cannot
    answer) or a finite probability in [0, 1].  Anything else is a programming
    error, not a low score.
    """
    if not isinstance(scores, dict):
        raise TypeError("score() must return a dict[question, list]")
    missing = [q for q in questions if q not in scores]
    if missing:
        raise KeyError(f"score() missing question(s): {missing}")
    out: dict[str, list[float | None]] = {}
    for question in questions:
        values = scores[question]
        if not isinstance(values, (list, tuple)):
            raise TypeError(f"score()[{question!r}] must be a list")
        if len(values) != n_cases:
            raise ValueError(
                f"score()[{question!r}] has {len(values)} values for {n_cases} cases"
            )
        clean: list[float | None] = []
        for value in values:
            if value is None:
                clean.append(None)
            elif _is_prob(value):
                clean.append(float(value))
            else:
                raise ValueError(f"score()[{question!r}] has a non-probability value: {value!r}")
        out[question] = clean
    return out


def scores_array(scores: dict[str, list[float | None]], question: str) -> np.ndarray:
    """Return a float array with ``nan`` for an unanswerable case."""
    values = scores.get(question)
    if values is None:
        return np.full(0, np.nan)
    return np.asarray([np.nan if v is None else float(v) for v in values], dtype=float)


def risk_array(scores: dict[str, list[float | None]], question: str) -> np.ndarray:
    """Orient a question's probabilities as risk (larger = more likely bad)."""
    values = scores_array(scores, question)
    return 1.0 - values if question == "supported" else values


class BaseReader(ABC):
    """Convenience base class; ``score`` is the only required method."""

    name = "base"

    @abstractmethod
    def score(
        self,
        cases: Sequence["Case"],
        rendering: str = "raw",
    ) -> dict[str, list[float | None]]:
        raise NotImplementedError

    def fit(self, cases: Sequence["Case"], y: Sequence[Any]) -> "BaseReader":
        """Optional training hook; frozen readers return ``self`` unchanged."""
        return self

    def cause_scores(
        self,
        cases: Sequence["Case"],
        rendering: str = "raw",
    ) -> dict[str, list[float]] | None:
        """Optional per-cause risk scores; ``None`` means not applicable."""
        return None

    def pointers(
        self,
        cases: Sequence["Case"],
        rendering: str = "raw",
    ) -> list[list[str]] | None:
        """Optional evidence pointers (document/note ids); ``None`` if unable."""
        return None


class ConstantReader(BaseReader):
    """A deliberately uninformative baseline: the same probability always."""

    name = "constant"

    def __init__(self, value: float = 0.5) -> None:
        if not _is_prob(value):
            raise ValueError("constant value must be a probability in [0, 1]")
        self.value = float(value)

    def score(
        self,
        cases: Sequence["Case"],
        rendering: str = "raw",
    ) -> dict[str, list[float | None]]:
        n = len(cases)
        return {question: [self.value] * n for question in QUESTIONS}
