"""The one place a decision-model failure becomes "no advice", and the one way advice can touch a decision.

`safe_ask` never raises: no key, a replay miss, an exhausted budget, a transport error and a malformed answer all return
`(None, code)`. `apply_advice` is the tighten-only rule: the result is the stricter of the deterministic decision and what the advice
asks for, and advice can only ask for a hold, so it can never turn a hold or a refusal into an allow.
"""
from __future__ import annotations

import math
import os

from orderguard_guard.decisions import Decisions
from orderguard_guard.llm import BudgetExceeded, LLMError, NoApiKey, ReplayMiss

AUTHORITY = "advice_only"
ACTIONS = ("none", "warn", "hold")               # all the advice may ever ask for
_ORDER = {"allow": 0, "hold": 1, "refuse": 2}
DEFAULT_MODEL = "typesafe/jev-1.14"


def model_name() -> str:
    return os.getenv("OG_REVIEW_MODEL") or DEFAULT_MODEL


def no_advice(code: str | None = None) -> dict:
    """The advice block when the model did not (or could not) answer. Everything downstream treats it as absent."""
    return {"available": False, "authority": AUTHORITY, "suggested_action": "none", "error": code}


def failure_code(exc: BaseException) -> str:
    if isinstance(exc, ReplayMiss):
        return "replay_miss"
    if isinstance(exc, NoApiKey):
        return "no_key"
    if isinstance(exc, BudgetExceeded):
        return "budget"
    if isinstance(exc, LLMError):
        return "model_error"
    if isinstance(exc, (ValueError, KeyError, TypeError, AttributeError)):
        return "malformed"
    return "unavailable"


def safe_ask(state: dict, questions: dict, decisions: Decisions | None = None) -> tuple[dict | None, str | None]:
    """Ask the decision model; return (answers, None) or (None, code). Never raises."""
    try:
        d = decisions if decisions is not None else Decisions(model_name())
        answers = d.ask(state, questions)
        if not isinstance(answers, dict):
            return None, "malformed"
        return answers, None
    except Exception as exc:        # noqa: BLE001  every failure, whatever its type, means "no advice"
        return None, failure_code(exc)


# ---- reading typed answers defensively (a reply that parses but is not what was asked for is also "no advice") ---------------

def probability(answer) -> float | None:
    v = answer.get("noul") if isinstance(answer, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0.0 <= v <= 1.0:
        return None
    return float(v)


def choice(answer, options) -> tuple[str, float | None, dict[str, float]] | None:
    """(chosen option, its confidence, probability by option) or None."""
    if not isinstance(answer, dict) or answer.get("choice") not in options:
        return None
    probs = answer.get("probabilities") if isinstance(answer.get("probabilities"), dict) else {}
    probs = {k: float(v) for k, v in probs.items() if k in options and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1}
    conf = answer.get("confidence")
    conf = float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) and math.isfinite(conf) and 0 <= conf <= 1 else None
    return answer["choice"], conf, probs


def level(answer, n_levels: int) -> float | None:
    """A score answer normalised to 0..1 (the model reports an expected level from 0 to n-1)."""
    v = answer.get("score") if isinstance(answer, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0.0 <= v <= n_levels - 1:
        return None
    return float(v) / (n_levels - 1)


def merge_probability(*ps: float | None) -> float | None:
    """Noisy-OR of the probabilities that are present. Adding a source can only raise the result, never lower it."""
    present = [p for p in ps if p is not None]
    if not present:
        return None
    q = 1.0
    for p in present:
        q *= 1.0 - min(max(p, 0.0), 1.0)
    return 1.0 - q


def action_for(p: float | None, hold_at: float, warn_at: float) -> str:
    if p is None:
        return "none"
    return "hold" if p >= hold_at else "warn" if p >= warn_at else "none"


def apply_advice(decision: str, advice: dict | None) -> str:
    """The stricter of the deterministic decision and what the advice asks for. Pure and total:
    allow -> hold is the only change advice can cause; hold and refuse never move down; an unknown decision fails closed."""
    if decision not in _ORDER:
        return "refuse"
    ask = (advice or {}).get("suggested_action") if isinstance(advice, dict) and advice.get("available") is True else "none"
    want = "hold" if ask == "hold" else "allow"
    return decision if _ORDER[decision] >= _ORDER[want] else want
