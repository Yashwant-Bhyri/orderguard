"""Verify's JSON adapter for the shared budgeted LLM client.

Replay and record modes can use existing Verify recordings in the legacy cache.
New responses are recorded and replayed by the shared client.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from orderguard_guard import llm as shared_llm
from orderguard_guard.llm import parse_json as parse_json

from ..paths import DATA

DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash-1017"
CACHE_DIR = Path(os.getenv("OG_LLM_CACHE", DATA / "llm_cache"))


@dataclass
class LLMCall:
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_s: float
    cached: bool


class LLMUnavailable(RuntimeError):
    pass


def _cache_path(model: str, system: str, user: str) -> Path:
    digest = hashlib.sha256(json.dumps([model, system, user]).encode()).hexdigest()[:32]
    return CACHE_DIR / f"{digest}.json"


def ask_json(system: str, user: str, *, model: str | None = None, max_tokens: int | None = None) -> tuple[dict, LLMCall]:
    model = model or os.getenv("OG_MODEL") or DEFAULT_MODEL
    mode = shared_llm.default_mode()
    if mode == "auto":  # Alias used by older Verify callers.
        mode = "record"
    path = _cache_path(model, system, user)
    has_legacy_recording = mode in ("record", "replay") and path.exists()
    max_tokens = max_tokens or int(os.getenv("OG_MAX_TOKENS", "24000"))
    # A shared recording from a live refresh takes precedence over the legacy answer.
    client = shared_llm.LLM(model=model, mode="replay" if has_legacy_recording else mode)
    started = time.monotonic()
    try:
        parsed, response = client.ask_json(system, user, max_tokens=max_tokens)
    except shared_llm.ReplayMiss as e:
        if has_legacy_recording:
            rec = json.loads(path.read_text())
            return parse_json(rec["text"]), LLMCall(**{**rec["call"], "cached": True})
        raise LLMUnavailable(f"{e}. No legacy Verify recording ({path.name}).") from None
    except (shared_llm.BudgetExceeded, shared_llm.CreditFloor, shared_llm.NoApiKey) as e:
        raise LLMUnavailable(str(e)) from None
    except (shared_llm.LLMError, httpx.HTTPError):
        raise LLMUnavailable(f"model {model} request failed") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise LLMUnavailable(f"model {model} gave no usable JSON") from None

    usage = response.get("usage") or {}
    meta = response["_meta"]
    # Legacy recordings retain their original latency. Shared recordings have no latency field.
    latency_s = 0.0 if meta["cached"] else round(time.monotonic() - started, 2)
    return parsed, LLMCall(model, usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0,
                           meta["cost_usd"], latency_s, meta["cached"])
