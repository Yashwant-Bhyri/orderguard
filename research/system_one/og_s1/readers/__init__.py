"""Text readers for the bounded text channel.

Every reader lives in its own module and exposes the same narrow interface::

    score(items) -> np.ndarray in [0, 1]

``items`` is a list of dictionaries.  A single-text item is
``{"feature": <name>, "text": <str>}`` and a premise/hypothesis item is
``{"feature": "support_gap", "premise": <str>, "hypothesis": <str>}``.  All
readers return one score per item except the external decision model, which
answers one action-level call and therefore returns an ``(n, 3)`` array in the
canonical feature order.

The modules are deliberately independent: the evaluation harness can load any
one of them without importing the others, and T07 can re-score a reader on
held-out wording without changing this package.
"""

from __future__ import annotations

from . import decision, embed_lr, injection, lexicon, nli

READERS = {
    "lexicon": lexicon,
    "nli": nli,
    "embed_lr": embed_lr,
    "injection": injection,
    "decision": decision,
}

__all__ = ["READERS", "lexicon", "nli", "embed_lr", "injection", "decision"]
