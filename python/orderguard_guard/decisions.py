"""Typed decision models (TypeSafe Jev) through OpenRouter's decisions endpoint, recorded and replayable like the chat client.

A decision model answers typed questions about a `state` with probabilities instead of generating text:

    d = Decisions("typesafe/jev-1.14")
    ans = d.ask({"order": ..., "history": [...]}, {"hold": {"type": "noul", "instructions": "..."}})
    ans["hold"]["noul"]            # P(yes), 0..1

Modes follow OG_LLM: replay (default under tests/CI; a missing recording raises ReplayMiss), record (replay if present, else call and
save), live (always call, save). Recordings live in data/replay/decisions/<hash>.json, keyed by the canonical request body, so a
replay is byte-for-byte the recorded answer. Live spend is capped by OG_BUDGET_USD for the process and appended to results/spend.jsonl.
The key is read by name (OPENROUTER_API_KEY) from the environment or OG_ENV_FILE and never printed.

Like every model in OrderGuard, a decision model can only tighten: its answer feeds `tighten`, never an approval.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import httpx

from .llm import LLMError, ReplayMiss, BudgetExceeded, NoApiKey, canonical, request_hash, default_mode, KEY_VAR

ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / "data" / "replay" / "decisions"
SPEND_LOG = ROOT / "results" / "spend.jsonl"
URL = os.getenv("OG_DECISIONS_URL", "https://openrouter.ai/api/alpha/decisions")
TYPES = {"noul", "choice", "score"}


def _key() -> str | None:
    k = os.getenv(KEY_VAR)
    if k:
        return k.strip()
    f = os.getenv("OG_ENV_FILE")
    if f and Path(f).exists():
        for line in Path(f).read_text().splitlines():
            line = line.strip().removeprefix("export ")
            if line.startswith(KEY_VAR + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


class _Budget:
    def __init__(self):
        self.lock = threading.Lock()
        self.spent = 0.0
        self.calls = 0

    def cap(self) -> float:
        return float(os.getenv("OG_BUDGET_USD", "0.05"))


BUDGET = _Budget()


def validate_questions(questions: dict) -> None:
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a non-empty mapping")
    for k, q in questions.items():
        if not isinstance(q, dict) or q.get("type") not in TYPES or not q.get("instructions"):
            raise ValueError(f"question {k!r} needs a type in {sorted(TYPES)} and instructions")
        if q["type"] == "choice" and not isinstance(q.get("criteria"), dict):
            raise ValueError(f"choice question {k!r} needs criteria as an object")
        if q["type"] == "score" and not (isinstance(q.get("criteria"), list) and 2 <= len(q["criteria"]) <= 10):
            raise ValueError(f"score question {k!r} needs 2 to 10 ordered criteria")


class Decisions:
    def __init__(self, model: str = "typesafe/jev-1.14", *, mode: str | None = None, timeout: float = 30.0, retries: int = 2,
                 replay_dir: Path | None = None):
        self.model, self.mode = model, (mode or default_mode())
        self.timeout, self.retries = timeout, retries
        self.dir = Path(replay_dir or REPLAY)
        self._client: httpx.Client | None = None

    def ask(self, state, questions: dict) -> dict:
        """Answers keyed like `questions`. Raises LLMError on an unusable reply (callers fail closed)."""
        validate_questions(questions)
        body = {"model": self.model, "state": state, "questions": questions}
        h = request_hash(body)
        path = self.dir / f"{h}.json"
        if self.mode in ("replay", "record") and path.exists():
            return self._check(json.loads(path.read_text())["response"], questions)
        if self.mode == "replay":
            raise ReplayMiss(f"no recorded decision for request {h}")
        resp = self._live(body)
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"request": body, "response": resp}, ensure_ascii=False, indent=1, sort_keys=True))
        return self._check(resp, questions)

    @staticmethod
    def _check(resp: dict, questions: dict) -> dict:
        ans = (resp or {}).get("answers")
        if not isinstance(ans, dict) or set(ans) != set(questions):
            raise LLMError("decision reply does not answer exactly the questions asked")
        for k, q in questions.items():
            a = ans[k]
            if q["type"] == "noul" and not (isinstance(a.get("noul"), (int, float)) and 0.0 <= a["noul"] <= 1.0):
                raise LLMError(f"decision reply for {k!r} has no probability in [0, 1]")
            if q["type"] == "choice" and a.get("choice") not in q["criteria"]:
                raise LLMError(f"decision reply for {k!r} chose an option that was not offered")
        return ans

    def _live(self, body: dict) -> dict:
        key = _key()
        if not key:
            raise NoApiKey(f"no {KEY_VAR} in the environment and none in OG_ENV_FILE; use OG_LLM=replay or set the key")
        # Input-token billing: bound one call by one token per request byte at a conservative US$0.10 per million.
        estimate = (len(canonical(body)) + 512) * 0.10 / 1e6
        with BUDGET.lock:
            if BUDGET.spent + estimate > BUDGET.cap():
                raise BudgetExceeded(f"decision call needs about US${estimate:.6f}; US${BUDGET.cap() - BUDGET.spent:.6f} left under OG_BUDGET_USD")
            BUDGET.spent += estimate
        self._client = self._client or httpx.Client(timeout=self.timeout)
        last = "no attempt"
        try:
            for attempt in range(self.retries + 1):
                t0 = time.perf_counter()
                try:
                    r = self._client.post(URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                                        "X-Title": "OrderGuard"}, content=canonical(body).encode())
                except httpx.TransportError as e:
                    last = type(e).__name__
                    time.sleep(1.0 * (attempt + 1))
                    continue
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"HTTP {r.status_code}"
                    time.sleep(1.0 * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    raise LLMError(f"decisions HTTP {r.status_code}: {r.text[:300]}")
                resp = r.json()
                cost = float(((resp.get("usage") or {}).get("cost")) or estimate)
                with BUDGET.lock:
                    BUDGET.spent += cost - estimate
                    BUDGET.calls += 1
                estimate = 0.0
                try:
                    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
                    with SPEND_LOG.open("a") as f:
                        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": self.model, "provider": "openrouter-decisions", "cost_usd": cost,
                                            "prompt_tokens": (resp.get("usage") or {}).get("input_tokens"),
                                            "completion_tokens": (resp.get("usage") or {}).get("output_tokens"),
                                            "cost_estimated": False}) + "\n")
                except OSError:
                    pass
                return resp
            raise LLMError(f"decisions unreachable after {self.retries + 1} attempts: {last}")
        finally:
            pass                                           # a failed call keeps its reservation: it may have been billed
