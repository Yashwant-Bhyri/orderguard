"""One shared guard LLM client per model per process (budget and replay live in orderguard_guard.llm)."""
from __future__ import annotations

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
