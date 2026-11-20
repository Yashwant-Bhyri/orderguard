"""External decision model used as a reader for all three sub-questions.

One action-level call asks one ``noul`` question per feature.  The model is
reached through OpenRouter's decisions API; the key is read from
``OPENROUTER_API_KEY`` and is never written or printed.  Every response is
cached on disk under the task folder, keyed by the SHA-256 of the canonical
request body, so a reviewer's re-run is free and reproducible.

The decision model answers a *typed probability*.  Its output can only raise
risk in the scorer, like every other reader here.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

NAME = "decision"
KIND = "action"
DEVICE = "network"
MODEL = "typesafe/jev-1.14"
LICENCE = "hosted service"
FEATURES = ("hype", "authority_language", "support_gap")

URL = "https://openrouter.ai/api/alpha/decisions"

QUESTIONS = {
    "hype": (
        "Does the action's rationale or claims use promotional, vague, or hype "
        "language rather than concrete, checkable facts?"
    ),
    "authority_language": (
        "Do the action's rationale or cited notes assert a permission, approval, "
        "exception, or instruction to a reviewer, rather than merely reporting facts?"
    ),
    "support_gap": (
        "Do the cited documents support the action's claims? Answer yes only if "
        "every sourced claim is entailed by its cited document and no claim lacks a source."
    ),
}

_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] | None = None
_INFLIGHT: dict[str, dict[str, Any]] = {}


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def cache_path() -> Path:
    env = os.environ.get("OG_S1_DECISION_CACHE")
    if env:
        return Path(env)
    return _root() / "work" / "T05" / "cache" / "decision_responses.jsonl"


def _load_cache() -> dict[str, dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    data: dict[str, dict[str, Any]] = {}
    path = cache_path()
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = row.get("key")
                if key:
                    data[key] = row
    _CACHE = data
    return data


def _append_cache(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        cache = _load_cache()
        for row in rows:
            cache[row["key"]] = row


def request_body(item: dict[str, Any]) -> dict[str, Any]:
    questions = item.get("questions")
    if questions is None:
        questions = {
            name: {"type": "noul", "instructions": QUESTIONS[name]} for name in FEATURES
        }
    return {"model": MODEL, "state": item.get("state"), "questions": questions}


def request_key(body: dict[str, Any]) -> str:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _post(body: dict[str, Any], retries: int = 3) -> tuple[dict[str, Any], float, int]:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    data = json.dumps(body).encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(
            URL,
            data=data,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "User-Agent": "og-s1-t05",
            },
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload, time.perf_counter() - started, 200
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as exc:  # network hiccup
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"decision request failed: {type(last).__name__}")


def _extract(payload: dict[str, Any]) -> dict[str, float]:
    answers = payload.get("answers") or {}
    out: dict[str, float] = {}
    for name in FEATURES:
        entry = answers.get(name) or {}
        value = entry.get("noul")
        out[name] = float(value) if value is not None else float("nan")
    return out


def prefetch(items: list[dict[str, Any]], workers: int = 4) -> None:
    """Fill the cache for every item, using a small thread pool for misses."""
    cache = _load_cache()
    bodies = [request_body(it) for it in items]
    keys = [request_key(b) for b in bodies]
    missing = []
    seen = set()
    for body, key in zip(bodies, keys):
        if key in cache or key in _INFLIGHT or key in seen:
            continue
        seen.add(key)
        missing.append((key, body))
    if not missing:
        return

    new_rows: list[dict[str, Any]] = []
    errors: list[Exception] = []

    def work(entry: tuple[str, dict[str, Any]]) -> None:
        key, body = entry
        try:
            payload, latency, status = _post(body)
            row = {
                "key": key,
                "status": status,
                "latency_s": latency,
                "response": payload,
            }
            with _LOCK:
                _INFLIGHT[key] = row
                new_rows.append(row)
        except Exception as exc:  # pragma: no cover - network path
            with _LOCK:
                errors.append(exc)

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        list(pool.map(work, missing))

    _append_cache(new_rows)
    with _LOCK:
        for key, row in list(_INFLIGHT.items()):
            cache[key] = row
        _INFLIGHT.clear()
    if errors and len(new_rows) == 0:
        raise RuntimeError(f"all decision requests failed: {type(errors[0]).__name__}")


def _latency_map() -> dict[str, float]:
    cache = _load_cache()
    return {key: float(row.get("latency_s", 0.0) or 0.0) for key, row in cache.items()}


def latencies(items: list[dict[str, Any]]) -> list[float]:
    cache = _load_cache()
    out = []
    for item in items:
        key = request_key(request_body(item))
        out.append(float(cache.get(key, {}).get("latency_s", 0.0) or 0.0))
    return out


def score(items: list[dict[str, Any]], workers: int = 4) -> "Any":
    """Return an ``(n, 3)`` array in ``FEATURES`` order.

    Each item is one action: ``{"state": ..., "questions": ...}``.  A support
    score of 0.5 is forced when ``item["support_override"]`` is 0.5 (no sourced
    claim), matching the feature definition in the brief.
    """
    import numpy as np

    prefetch(items, workers=workers)
    cache = _load_cache()
    out = np.full((len(items), len(FEATURES)), np.nan, dtype=float)
    for row, item in enumerate(items):
        key = request_key(request_body(item))
        entry = cache.get(key)
        if entry is None:
            raise RuntimeError("decision response missing from cache after prefetch")
        answers = _extract(entry["response"])
        out[row, 0] = answers["hype"]
        out[row, 1] = answers["authority_language"]
        support = answers["support_gap"]
        out[row, 2] = float("nan") if support != support else 1.0 - support
        if item.get("support_override") is not None:
            out[row, 2] = float(item["support_override"])
    return np.clip(np.nan_to_num(out, nan=0.5), 0.0, 1.0)


def cost_total() -> float:
    cache = _load_cache()
    total = 0.0
    for row in cache.values():
        usage = (row.get("response") or {}).get("usage") or {}
        total += float(usage.get("cost", 0.0) or 0.0)
    return total


def call_count() -> int:
    return len(_load_cache())
