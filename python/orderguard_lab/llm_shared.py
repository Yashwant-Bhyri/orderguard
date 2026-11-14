"""One shared guard LLM client per model per process (budget and replay live in orderguard_guard.llm)."""
from __future__ import annotations

import os
import threading

_LOCK = threading.Lock()
_CACHE: dict = {}


def shared_llm(model):
    if hasattr(model, "chat"):
        return model
    from orderguard_guard.llm import LLM
    with _LOCK:
        if model not in _CACHE:
            _CACHE[model] = LLM(model)
        return _CACHE[model]


class ReplayIncomplete(RuntimeError):
    """A strict offline replay needed a model reply that has no recording. Never papered over as an errored run."""


def strict_replay() -> bool:
    """True when a missing recording must stop the run loudly instead of becoming an errored (and later excluded) record.

    On with OG_REPLAY_STRICT=1, which scripts/check_all.sh and the lab tests set. Off by default so the dashboard can show a
    missing recording as a labelled result to its user.
    """
    return os.getenv("OG_REPLAY_STRICT", "").strip().lower() in ("1", "true", "yes", "on")


def check_replay_complete(transcript: dict, what: str) -> None:
    """Raise ReplayIncomplete when strict replay is on and the transcript shows a ReplayMiss (agent error) or a failed screen call."""
    if not strict_replay():
        return
    err = str(transcript.get("error") or "")
    if "ReplayMiss" in err:
        raise ReplayIncomplete(f"{what}: {err}. Offline replay must not fall back to a live call; re-record with OG_LLM=record and a budget, "
                               f"or fix the case so it matches an existing recording.")
    if transcript.get("screen_errors") and (transcript.get("model") or "") and os.environ.get("OG_LLM", "replay") == "replay":
        raise ReplayIncomplete(f"{what}: {transcript['screen_errors']} screen call(s) failed in replay mode (a missing recording quarantines content "
                               f"and silently changes the result).")
