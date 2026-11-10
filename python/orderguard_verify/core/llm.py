"""Thin OpenRouter client with an on-disk replay cache.

Every model call goes through `ask_json`. The cache makes runs repeatable and lets a stranger run the
demo and the eval without an API key: a recorded answer is reused when the exact same prompt was
asked before, and the original cost and latency are kept so the results table stays honest.

OG_LLM=auto (default)  cache hit -> reuse, miss -> call the API
OG_LLM=replay          cache only; a miss is an error (what CI and a keyless stranger get)
OG_LLM=live            always call the API and overwrite the cache
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# Any OpenAI-compatible chat endpoint works: OG_API_URL + OG_KEY_VAR (name of the env var holding the key).
API_URL = os.getenv("OG_API_URL", "https://openrouter.ai/api/v1/chat/completions")
KEY_VAR = os.getenv("OG_KEY_VAR", "OPENROUTER_API_KEY")
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl:free"   # free on OpenRouter; the recorded answers in data/llm_cache are for this model
from ..paths import DATA

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


def _api_key() -> str | None:
    key = os.getenv(KEY_VAR)
    if key:
        return key
    env_file = Path(os.getenv("OG_ENV_FILE") or os.getenv("ORDERGUARD_ENV_FILE") or Path.home() / ".env.local")
    if env_file.exists():  # read only the one variable we need
        for line in env_file.read_text().splitlines():
            if line.startswith(KEY_VAR + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


def _cache_path(model: str, system: str, user: str) -> Path:
    digest = hashlib.sha256(json.dumps([model, system, user]).encode()).hexdigest()[:32]
    return CACHE_DIR / f"{digest}.json"


def parse_json(text: str) -> dict:
    """Pull a JSON object out of a model reply, tolerating code fences and chatter."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start:end + 1], strict=False)


def ask_json(system: str, user: str, *, model: str | None = None, max_tokens: int | None = None) -> tuple[dict, LLMCall]:
    model = model or os.getenv("OG_MODEL", DEFAULT_MODEL)
    max_tokens = max_tokens or int(os.getenv("OG_MAX_TOKENS", "24000"))   # reasoning models spend most of this thinking
    mode = os.getenv("OG_LLM", "auto")
    path = _cache_path(model, system, user)
    if mode != "live" and path.exists():
        rec = json.loads(path.read_text())
        return parse_json(rec["text"]), LLMCall(**{**rec["call"], "cached": True})
    if mode == "replay":
        raise LLMUnavailable(f"OG_LLM=replay and no recorded answer for this prompt ({path.name})")
    key = _api_key()
    if not key:
        raise LLMUnavailable(f"no {KEY_VAR}; run with the recorded answers (OG_LLM=replay) or set the key")
    t0 = time.time()
    last_error = "no answer"
    for attempt in range(6):   # busy and free models rate-limit or return empty text; back off and retry
        try:
            r = httpx.post(API_URL, timeout=float(os.getenv("OG_TIMEOUT", "400")), headers={"Authorization": f"Bearer {key}"}, json={
                "model": model, "temperature": 0, "max_tokens": max_tokens, "usage": {"include": True},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        except httpx.TransportError as e:   # timeouts and dropped connections are retried like rate limits
            last_error = type(e).__name__
            time.sleep(min(60, 4 * 2 ** attempt))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last_error = f"HTTP {r.status_code}"
            time.sleep(min(60, 4 * 2 ** attempt))
            continue
        r.raise_for_status()
        try:
            body = r.json()
            text = (body["choices"][0]["message"].get("content") or "").strip()
            parsed = parse_json(text)
            break
        except (ValueError, KeyError, IndexError, TypeError) as e:   # includes JSONDecodeError and odd response bodies
            last_error = f"unparseable reply ({type(e).__name__})"
    else:
        raise LLMUnavailable(f"model {model} gave no usable JSON after retries: {last_error}")
    usage = body.get("usage", {})
    call = LLMCall(model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                   float(usage.get("cost") or 0.0), round(time.time() - t0, 2), cached=False)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"text": text, "call": {**call.__dict__, "cached": False}}, indent=1))
    return parsed, call
