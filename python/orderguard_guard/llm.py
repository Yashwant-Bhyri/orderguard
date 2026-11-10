"""The one OpenRouter chat-completions client (CONTRACT §4).

Every model call in OrderGuard goes through `LLM.chat`. It:
  - records and replays responses, content-addressed by a hash of the canonical request body (data/replay/);
  - enforces a per-process budget (OG_BUDGET_USD, default 0.05) and appends every live call's cost to results/spend.jsonl;
  - checks the OpenRouter credit balance once per process before the first live call and refuses under US$0.30;
  - retries transport errors, incomplete reads and 429/5xx with backoff;
  - never prints the key.

Modes (OG_LLM):  replay  cache only, a miss is an error
                 record  cache hit -> reuse; miss -> live call, then store
                 live    always call, then store
Default: replay under pytest or CI, record otherwise.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import DEFAULT_MODEL, REPLAY_DIR, RESULTS_DIR

API_URL = os.getenv("OG_API_URL", "https://openrouter.ai/api/v1/chat/completions")
CREDITS_URL = os.getenv("OG_CREDITS_URL", "https://openrouter.ai/api/v1/credits")
KEY_VAR = "OPENROUTER_API_KEY"
CREDIT_FLOOR_USD = 0.30

# Provider: OG_PROVIDER=openrouter (default) or deepseek (DeepSeek's own API, key DEEPSEEK_API_KEY).
# Replay keys hash the logical request (OpenRouter model ids), so recordings are provider-independent.
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"
DEEPSEEK_MODELS = {"deepseek/deepseek-v4.1-flash": "deepseek-flash", "deepseek/deepseek-v4-pro": "deepseek-v4-pro"}
CNY_PER_USD = float(os.getenv("OG_CNY_PER_USD", "7.1"))
# US$ per million tokens, used when the provider does not report cost (DeepSeek direct). Defaults are the
# OpenRouter list prices for V4.1 Flash, a conservative stand-in; override with OG_PRICE_IN / OG_PRICE_OUT.
PRICE_IN = float(os.getenv("OG_PRICE_IN", "0.051"))
PRICE_OUT = float(os.getenv("OG_PRICE_OUT", "0.567"))


def provider() -> str:
    return os.getenv("OG_PROVIDER", "openrouter").lower()


def key_var() -> str:
    return "DEEPSEEK_API_KEY" if provider() == "deepseek" else KEY_VAR


class LLMError(RuntimeError):
    """Base class for every failure the client reports."""


class ReplayMiss(LLMError):
    """OG_LLM=replay and no recorded response for this request."""


class BudgetExceeded(LLMError):
    """The per-process budget (OG_BUDGET_USD) is spent."""


class CreditFloor(LLMError):
    """The OpenRouter account is under the hard floor."""


class NoApiKey(LLMError):
    pass


def default_mode() -> str:
    mode = os.getenv("OG_LLM")
    if mode:
        return mode
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("CI"):
        return "replay"
    return "record"


def api_key() -> str | None:
    """OPENROUTER_API_KEY from the environment, else read by name from the dotenv file at OG_ENV_FILE. Never printed."""
    var = key_var()
    key = os.getenv(var)
    if key:
        return key.strip()
    env_file = os.getenv("OG_ENV_FILE")
    if env_file and Path(env_file).exists():
        for line in Path(env_file).read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if line.startswith(var + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


def canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_hash(body: dict) -> str:
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()[:32]


@dataclass
class Spend:
    """Per-process ledger of live spend. Shared by every LLM instance in the process."""
    budget_usd: float = field(default_factory=lambda: float(os.getenv("OG_BUDGET_USD", "0.05")))
    spent_usd: float = 0.0
    calls: int = 0
    credits_checked: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def reset(self) -> None:
        with self.lock:
            self.budget_usd = float(os.getenv("OG_BUDGET_USD", "0.05"))
            self.spent_usd, self.calls, self.credits_checked = 0.0, 0, False


SPEND = Spend()


class LLM:
    """OpenAI-compatible chat completions over OpenRouter with tools support.

    `chat(messages, tools=None, ...)` returns the raw response body (choices, usage) plus a `_meta` key
    {"cached": bool, "cost_usd": float, "hash": str}.
    """

    def __init__(self, model: str | None = None, *, mode: str | None = None, replay_dir: Path | None = None,
                 spend_file: Path | None = None, client: httpx.Client | None = None, timeout: float | None = None,
                 retries: int | None = None, spend: Spend | None = None):
        self.model = model or DEFAULT_MODEL
        self.mode = mode or default_mode()
        if self.mode not in ("replay", "record", "live"):
            raise ValueError(f"OG_LLM must be replay, record or live, not {self.mode!r}")
        self.replay_dir = Path(replay_dir or REPLAY_DIR)
        self.spend_file = Path(spend_file or os.getenv("OG_SPEND_FILE", RESULTS_DIR / "spend.jsonl"))
        self.timeout = timeout if timeout is not None else float(os.getenv("OG_TIMEOUT", "300"))
        self.retries = retries if retries is not None else int(os.getenv("OG_LLM_RETRIES", "4"))
        self._client = client
        self.spend = spend or SPEND

    # ---- public API -----------------------------------------------------------------------------

    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, model: str | None = None,
             max_tokens: int = 4000, temperature: float = 0.0, extra: dict | None = None) -> dict:
        body: dict[str, Any] = {"model": model or self.model, "messages": messages, "max_tokens": max_tokens,
                                "temperature": temperature, "usage": {"include": True}}
        if tools:
            body["tools"] = tools
        if extra:
            body.update(extra)
        h = request_hash(body)
        path = self.replay_dir / f"{h}.json"
        if self.mode in ("replay", "record") and path.exists():
            rec = json.loads(path.read_text())
            resp = rec["response"]
            resp["_meta"] = {"cached": True, "cost_usd": float(rec.get("cost_usd") or 0.0), "hash": h}
            return resp
        if self.mode == "replay":
            raise ReplayMiss(f"OG_LLM=replay and no recorded response for request {h} (model {body['model']})")
        resp = self._live(body)
        cost = float((resp.get("usage") or {}).get("cost") or 0.0)
        self.replay_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"hash": h, "model": body["model"], "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    "cost_usd": cost, "request_summary": _summary(body), "response": resp}, indent=1, ensure_ascii=False))
        resp["_meta"] = {"cached": False, "cost_usd": cost, "hash": h}
        return resp

    def ask_json(self, system: str, user: str, *, max_tokens: int = 1500, model: str | None = None) -> tuple[dict, dict]:
        """One system+user exchange whose answer is a JSON object. Returns (parsed, response)."""
        resp = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                         max_tokens=max_tokens, model=model)
        text = (resp["choices"][0]["message"].get("content") or "")
        return parse_json(text), resp

    # ---- live path --------------------------------------------------------------------------------

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _headers(self) -> dict:
        key = api_key()
        if not key:
            raise NoApiKey(f"no {key_var()} in the environment and none in OG_ENV_FILE; use OG_LLM=replay or set the key")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/orderguard", "X-Title": "OrderGuard"}

    def check_credits(self) -> float:
        """GET /credits once per process; refuse under the floor. Returns the remaining balance."""
        if provider() == "deepseek":
            r = self._http().get(DEEPSEEK_BALANCE_URL, headers=self._headers())
            r.raise_for_status()
            remaining = 0.0
            for b in r.json().get("balance_infos") or []:
                v = float(b.get("total_balance") or 0.0)
                remaining += v / CNY_PER_USD if b.get("currency") == "CNY" else v
        else:
            r = self._http().get(CREDITS_URL, headers=self._headers())
            r.raise_for_status()
            d = r.json().get("data") or {}
            remaining = float(d.get("total_credits") or 0.0) - float(d.get("total_usage") or 0.0)
        if remaining < CREDIT_FLOOR_USD:
            raise CreditFloor(f"{provider()} balance US${remaining:.2f} is under the US${CREDIT_FLOOR_USD:.2f} floor; refusing live calls")
        return remaining

    def _live(self, body: dict) -> dict:
        with self.spend.lock:
            if self.spend.spent_usd >= self.spend.budget_usd:
                raise BudgetExceeded(f"budget US${self.spend.budget_usd:.3f} spent (US${self.spend.spent_usd:.4f} over {self.spend.calls} calls)")
            need_credits = not self.spend.credits_checked
        if need_credits:
            self.check_credits()
            self.spend.credits_checked = True
        last = "no attempt"
        for attempt in range(self.retries + 1):
            try:
                url, wire = self._wire(body)
                r = self._http().post(url, headers=self._headers(), content=canonical(wire).encode("utf-8"))
            except (httpx.TransportError, http.client.IncompleteRead, ConnectionError) as e:
                # httpx surfaces a truncated body as RemoteProtocolError / ReadError; retry like a timeout
                last = f"{type(e).__name__}"
                self._backoff(attempt)
                continue
            if r.status_code in (408, 409, 425, 429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                self._backoff(attempt)
                continue
            if r.status_code >= 400:
                raise LLMError(f"{provider()} HTTP {r.status_code}: {r.text[:300]}")
            try:
                resp = r.json()
            except ValueError as e:
                last = f"bad JSON body ({type(e).__name__})"
                self._backoff(attempt)
                continue
            if "choices" not in resp:
                err = resp.get("error") or resp
                code = err.get("code") if isinstance(err, dict) else None
                if code in (429, 502, 503):
                    last = f"API error {code}"
                    self._backoff(attempt)
                    continue
                raise LLMError(f"OpenRouter error: {json.dumps(err)[:300]}")
            self._record_spend(body["model"], resp)
            return resp
        raise LLMError(f"OpenRouter unreachable after {self.retries + 1} attempts: {last}")

    def _wire(self, body: dict) -> tuple[str, dict]:
        """Translate the logical (OpenRouter-shaped) request for the configured provider."""
        if provider() != "deepseek":
            return API_URL, body
        wire = {k: v for k, v in body.items() if k not in ("usage", "reasoning")}
        effort = (body.get("reasoning") or {}).get("effort")
        if effort:
            wire["reasoning_effort"] = effort
        wire["model"] = DEEPSEEK_MODELS.get(body["model"], body["model"].split("/")[-1])
        return DEEPSEEK_URL, wire

    def _backoff(self, attempt: int) -> None:
        time.sleep(min(30.0, 1.5 * (2 ** attempt)))

    def _record_spend(self, model: str, resp: dict) -> None:
        usage = resp.get("usage") or {}
        if usage.get("cost") is None:
            usage["cost"] = ((usage.get("prompt_tokens") or 0) * PRICE_IN + (usage.get("completion_tokens") or 0) * PRICE_OUT) / 1e6
            usage["cost_estimated"] = True
            resp["usage"] = usage
        cost = float(usage.get("cost") or 0.0)
        with self.spend.lock:
            self.spend.spent_usd += cost
            self.spend.calls += 1
        try:
            self.spend_file.parent.mkdir(parents=True, exist_ok=True)
            with self.spend_file.open("a") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": model, "cost_usd": cost,
                                    "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                                    "provider": provider(), "pid": os.getpid()}) + "\n")
        except OSError:
            pass


def _summary(body: dict) -> dict:
    """What a recording keeps of its request: the replay key is the hash, so the full prompt (often a whole 10-K) is not stored."""
    msgs = body.get("messages") or []
    return {"model": body.get("model"), "messages": len(msgs), "tools": len(body.get("tools") or []),
            "max_tokens": body.get("max_tokens"), "chars": sum(len(str(m.get("content") or "")) for m in msgs)}


def parse_json(text: str) -> dict:
    """Pull one JSON object out of a model reply, tolerating code fences and chatter around it."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model reply")
    return json.loads(t[start:end + 1], strict=False)


class ScriptedLLM:
    """A fake with the `chat` interface for tests and offline smoke runs.

    `turns` is a list of assistant messages to return in order; each is either a string (final answer) or a list of
    (tool_name, args) tool calls. `screen` is an optional function chunk -> dict used when asked a screen question.
    """

    def __init__(self, turns: list, model: str = "fake/scripted", screen=None, cost_per_call: float = 0.0):
        self.turns = list(turns)
        self.model = model
        self.screen = screen
        self.cost_per_call = cost_per_call
        self.requests: list[dict] = []
        self._n = 0

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kw) -> dict:
        self.requests.append({"messages": messages, "tools": tools})
        if self.screen is not None and messages and "screen" in (messages[0].get("content") or "").lower() and not tools:
            verdict = self.screen(messages[-1]["content"])
            return self._wrap({"role": "assistant", "content": json.dumps(verdict)})
        if not self.turns:
            return self._wrap({"role": "assistant", "content": "Done."})
        turn = self.turns.pop(0)
        if isinstance(turn, str):
            return self._wrap({"role": "assistant", "content": turn})
        calls = []
        for name, args in turn:
            self._n += 1
            calls.append({"id": f"call_{self._n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}})
        return self._wrap({"role": "assistant", "content": "", "tool_calls": calls})

    def ask_json(self, system: str, user: str, **kw) -> tuple[dict, dict]:
        resp = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        return parse_json(resp["choices"][0]["message"]["content"]), resp

    def _wrap(self, message: dict) -> dict:
        return {"choices": [{"message": message, "finish_reason": "stop"}], "usage": {"cost": self.cost_per_call},
                "model": self.model, "_meta": {"cached": True, "cost_usd": self.cost_per_call, "hash": "scripted"}}


def as_llm(model_or_llm) -> LLM | ScriptedLLM:
    """Accept a model name or anything with `.chat`."""
    if hasattr(model_or_llm, "chat"):
        return model_or_llm
    return LLM(model_or_llm)
