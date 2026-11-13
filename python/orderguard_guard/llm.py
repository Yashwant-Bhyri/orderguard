"""The shared chat-completions client for DeepSeek direct and compatible providers (CONTRACT §4).

Every model call in OrderGuard goes through `LLM.chat`. It:
  - records and replays responses, content-addressed by a hash of the canonical request body (data/replay/);
  - reserves worst-case cost within the per-process budget (OG_BUDGET_USD, default 0.05) before each live call;
  - checks the provider balance once before live calls and limits spend to the headroom above US$0.30;
  - logs settled costs and unconfirmed exposures to results/spend.jsonl;
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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

import httpx

from . import DEFAULT_MODEL, REPLAY_DIR, RESULTS_DIR

API_URL = os.getenv("OG_API_URL", "https://openrouter.ai/api/v1/chat/completions")
CREDITS_URL = os.getenv("OG_CREDITS_URL", "https://openrouter.ai/api/v1/credits")
KEY_VAR = "OPENROUTER_API_KEY"
CREDIT_FLOOR_USD = 0.30

# Provider: OG_PROVIDER=deepseek (default; DeepSeek's own API, key DEEPSEEK_API_KEY) or openrouter.
# Replay keys hash the logical request (OpenRouter model ids), so recordings are provider-independent.
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"
DEEPSEEK_MODELS = {"deepseek/deepseek-v4.1-flash": "deepseek-flash",
                   "deepseek/deepseek-v4.1-flash-1017": "deepseek-flash",
                   "deepseek/deepseek-v4-pro": "deepseek-v4-pro"}
CNY_PER_USD = float(os.getenv("OG_CNY_PER_USD", "7.1"))
# US$ per million tokens, used when DeepSeek direct does not report cost. Use peak cache-miss input pricing
# so preflight reservations remain conservative; override with OG_PRICE_IN / OG_PRICE_OUT only deliberately.
PRICE_IN = float(os.getenv("OG_PRICE_IN", "0.30"))
PRICE_OUT = float(os.getenv("OG_PRICE_OUT", "1.20"))
# DeepSeek direct peak, cache-miss rates per million tokens (USD).
DEEPSEEK_PEAK_RATES = {"deepseek-flash": (0.30, 1.20), "deepseek-v4-pro": (1.32, 3.96),
                       "deepseek-v4-flash": (0.30, 1.20), "deepseek-v4-flash-vision-exp": (0.30, 1.20)}


def provider() -> str:
    return os.getenv("OG_PROVIDER", "deepseek").lower()


def key_var() -> str:
    return "DEEPSEEK_API_KEY" if provider() == "deepseek" else KEY_VAR


class LLMError(RuntimeError):
    """Base class for every failure the client reports."""


class ReplayMiss(LLMError):
    """OG_LLM=replay and no recorded response for this request."""


class BudgetExceeded(LLMError):
    """The request cannot fit within the remaining live budget."""


class CreditFloor(LLMError):
    """The provider account is under the hard floor."""


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
    """Return the selected provider key from the environment or OG_ENV_FILE. Never print it."""
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


def _nonnegative_decimal(value: Any) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("expected a finite, nonnegative amount")
    return result


@dataclass
class _Reservation:
    amount: Decimal
    active: bool = True


@dataclass
class Spend:
    """Per-process ledger of live spend. Shared by every LLM instance in the process."""
    budget_usd: float = field(default_factory=lambda: float(os.getenv("OG_BUDGET_USD", "0.05")))
    calls: int = 0
    credits_checked: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _credit_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _spent: Decimal = field(default=Decimal(0), init=False, repr=False)
    _reserved: Decimal = field(default=Decimal(0), init=False, repr=False)
    _inflight: int = field(default=0, init=False, repr=False)
    _unconfirmed: Decimal = field(default=Decimal(0), init=False, repr=False)
    _credit_headroom: Decimal | None = field(default=None, init=False, repr=False)
    _estimate_failed: bool = field(default=False, init=False, repr=False)

    @property
    def spent_usd(self) -> float:
        return float(self._spent)

    def reset(self) -> None:
        with self._credit_lock, self.lock:
            if self._inflight:
                raise RuntimeError("cannot reset spend while live requests are in flight")
            self.budget_usd = float(os.getenv("OG_BUDGET_USD", "0.05"))
            self._spent = self._unconfirmed = Decimal(0)
            self.calls, self.credits_checked = 0, False
            self._credit_headroom, self._estimate_failed = None, False

    def _require_room(self, amount: Decimal, *, already_reserved: Decimal = Decimal(0)) -> None:
        try:
            limit = _nonnegative_decimal(self.budget_usd)
        except (ValueError, InvalidOperation):
            raise BudgetExceeded("OG_BUDGET_USD must be a finite, nonnegative amount") from None
        if self._credit_headroom is not None:
            limit = min(limit, self._credit_headroom)
        available = limit - self._spent - self._reserved - self._unconfirmed + already_reserved
        if self._estimate_failed:
            raise BudgetExceeded("a provider charge exceeded its reservation; refusing further live calls")
        if amount > available or limit == 0:
            raise BudgetExceeded(f"live call needs US${amount:.6f}; only US${max(Decimal(0), available):.6f} available "
                                 f"under the US${limit:.6f} live cap")

    def reserve(self, amount: Decimal, check_credits: Callable[[], Decimal]) -> _Reservation:
        # Serialize the first credit check and publish its result before allowing another reservation.
        # The ledger lock is never held during HTTP.
        reservation = _Reservation(amount)
        with self._credit_lock:
            with self.lock:
                self._require_room(amount)
                self._reserved += amount
                self._inflight += 1
                if self.credits_checked:
                    return reservation
            try:
                balance = _nonnegative_decimal(check_credits())
                with self.lock:
                    self._credit_headroom = max(Decimal(0), balance - Decimal(str(CREDIT_FLOOR_USD)))
                    self.credits_checked = True
                    self._require_room(amount, already_reserved=amount)
            except BaseException:
                self.release(reservation)
                raise
        return reservation

    def _close(self, reservation: _Reservation) -> None:
        self._reserved -= reservation.amount
        self._inflight -= 1
        reservation.active = False

    def release(self, reservation: _Reservation, *, unconfirmed: bool = False) -> bool:
        with self.lock:
            if not reservation.active:
                return False
            self._close(reservation)
            if unconfirmed:
                self._unconfirmed += reservation.amount
            return True

    def settle(self, reservation: _Reservation | None, cost: Decimal) -> None:
        with self.lock:
            self._spent += cost
            self.calls += 1
            if reservation is not None:
                self._close(reservation)
                if cost > reservation.amount:
                    self._estimate_failed = True


SPEND = Spend()


class LLM:
    """Budgeted chat completions over DeepSeek direct or OpenRouter, with tools support.

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
        self.record_dir = Path(os.getenv("OG_RECORD_DIR") or self.replay_dir) if replay_dir is None else self.replay_dir
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
        filename = f"{h}.json"
        if self.mode in ("replay", "record"):
            for directory in dict.fromkeys((self.record_dir, self.replay_dir)):
                path = directory / filename
                if path.is_file():
                    rec = json.loads(path.read_text(encoding="utf-8"))
                    resp = rec["response"]
                    resp["_meta"] = {"cached": True, "cost_usd": float(rec.get("cost_usd") or 0.0), "hash": h}
                    return resp
        if self.mode == "replay":
            raise ReplayMiss(f"OG_LLM=replay and no recorded response for request {h} (model {body['model']})")
        resp = self._live(body)
        cost = float((resp.get("usage") or {}).get("cost") or 0.0)
        self.record_dir.mkdir(parents=True, exist_ok=True)
        recorded = {"hash": h, "model": body["model"], "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "cost_usd": cost, "request_summary": _summary(body), "response": resp}
        with TemporaryDirectory(dir=self.record_dir, prefix=".record-") as staging:
            path = Path(staging) / filename
            path.write_text(json.dumps(recorded, indent=1, ensure_ascii=False), encoding="utf-8")
            path.replace(self.record_dir / filename)
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
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if provider() == "openrouter":
            headers.update({"HTTP-Referer": "https://github.com/orderguard", "X-Title": "OrderGuard"})
        return headers

    def check_credits(self) -> Decimal:
        """Fetch the provider's remaining USD balance and refuse under the floor."""
        if provider() == "deepseek":
            r = self._http().get(DEEPSEEK_BALANCE_URL, headers=self._headers())
            r.raise_for_status()
            remaining = Decimal(0)
            for b in r.json().get("balance_infos") or []:
                v = Decimal(str(b.get("total_balance") or 0))
                remaining += v / Decimal(str(CNY_PER_USD)) if b.get("currency") == "CNY" else v
        else:
            r = self._http().get(CREDITS_URL, headers=self._headers())
            r.raise_for_status()
            d = r.json().get("data") or {}
            remaining = Decimal(str(d.get("total_credits") or 0)) - Decimal(str(d.get("total_usage") or 0))
        if not remaining.is_finite():
            raise CreditFloor(f"{provider()} returned an invalid balance; refusing live calls")
        if remaining < Decimal(str(CREDIT_FLOOR_USD)):
            raise CreditFloor(f"{provider()} balance US${remaining:.2f} is under the US${CREDIT_FLOOR_USD:.2f} floor; refusing live calls")
        return remaining

    def _live(self, body: dict) -> dict:
        url, wire = self._wire(body)
        payload, estimate, rates = self._budgeted_payload(wire)
        reservation = self.spend.reserve(estimate, self.check_credits)
        may_have_billed = False
        last = "no attempt"
        try:
            headers = self._headers()
            for attempt in range(self.retries + 1):
                if reservation is None:
                    reservation = self.spend.reserve(estimate, self.check_credits)
                try:
                    may_have_billed = True
                    last = "unconfirmed POST"
                    r = self._http().post(url, headers=headers, content=payload)
                except (httpx.TransportError, http.client.IncompleteRead, ConnectionError) as e:
                    # Connect/pool failures precede submission; a truncated response or timeout may be billed.
                    may_have_billed = not isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
                    last = type(e).__name__
                else:
                    if r.status_code in (408, 409, 425, 429, 500, 502, 503, 504):
                        may_have_billed = r.status_code not in (409, 425, 429)
                        last = f"HTTP {r.status_code}"
                    elif r.status_code >= 400:
                        may_have_billed = r.status_code >= 500
                        last = f"HTTP {r.status_code}"
                        raise LLMError(f"{provider()} HTTP {r.status_code}: {r.text[:300]}")
                    else:
                        try:
                            resp = r.json()
                        except ValueError as e:
                            last = f"bad JSON body ({type(e).__name__})"
                        else:
                            if isinstance(resp, dict) and "choices" in resp:
                                self._record_spend(body["model"], resp, reservation=reservation, rates=rates)
                                return resp
                            err = (resp.get("error") or resp) if isinstance(resp, dict) else resp
                            code = err.get("code") if isinstance(err, dict) else None
                            may_have_billed = code != 429
                            last = "API error response"
                            if code not in (429, 502, 503):
                                raise LLMError(f"{provider()} error: {json.dumps(err)[:300]}")
                            last = f"API error {code}"
                if may_have_billed:
                    # Keep exposure for an attempt whose charge could not be observed. A retry needs its own room.
                    self._release_attempt(reservation, body["model"], reason=last)
                    reservation = None
                    may_have_billed = False
                if attempt < self.retries:
                    self._backoff(attempt)
            raise LLMError(f"{provider()} unreachable after {self.retries + 1} attempts: {last}")
        finally:
            if reservation is not None:
                self._release_attempt(reservation, body["model"], reason=last if may_have_billed else None)

    def _budgeted_payload(self, wire: dict) -> tuple[bytes, Decimal, tuple[Decimal, Decimal]]:
        max_tokens = wire.get("max_tokens")
        if type(max_tokens) is not int or max_tokens <= 0 or "max_completion_tokens" in wire:
            raise BudgetExceeded("live requests need a positive integer max_tokens as their only output limit")
        if wire.get("stream") or wire.get("n", 1) != 1:
            raise BudgetExceeded("live reservations require a single non-streamed completion")
        messages, tools = wire.get("messages") or [], wire.get("tools") or []
        for message in messages:
            content = message.get("content")
            if content is not None and not isinstance(content, str) and not (
                isinstance(content, list) and all(isinstance(p, dict) and p.get("type") == "text"
                                                  and isinstance(p.get("text"), str) for p in content)
            ):
                raise BudgetExceeded("live reservations require text message content")
        if (any(tool.get("type") != "function" for tool in tools) or wire.get("plugins") or wire.get("web_search_options")
                or wire.get("modalities") not in (None, ["text"]) or str(wire["model"]).endswith(":online")
                or any(str(model).endswith(":online") for model in wire.get("models") or [])):
            raise BudgetExceeded("live reservations cannot bound provider-side tools or non-text charges")
        try:
            rate_in, rate_out = _nonnegative_decimal(PRICE_IN), _nonnegative_decimal(PRICE_OUT)
            if provider() == "deepseek":
                peak = DEEPSEEK_PEAK_RATES.get(wire["model"])
                if peak is None:
                    raise BudgetExceeded(f"no peak rates configured for DeepSeek model {wire['model']!r}")
                rate_in = max(rate_in, _nonnegative_decimal(peak[0]))
                rate_out = max(rate_out, _nonnegative_decimal(peak[1]))
            else:
                routing = dict(wire.get("provider") or {})
                ceilings = dict(routing.get("max_price") or {})
                rate_in = min(rate_in, _nonnegative_decimal(ceilings.get("prompt", rate_in)))
                rate_out = min(rate_out, _nonnegative_decimal(ceilings.get("completion", rate_out)))
                ceilings.update(prompt=float(rate_in), completion=float(rate_out), request=0, image=0)
                routing.update(max_price=ceilings, require_parameters=True)
                wire = {**wire, "provider": routing}
        except (ValueError, InvalidOperation) as e:
            raise BudgetExceeded("live token pricing must be finite and nonnegative") from e
        payload = canonical(wire).encode("utf-8")
        # Allow one token per wire byte (including tool schemas) plus server-side chat framing.
        prompt_bound = len(payload) + 256 + 64 * (len(messages) + len(tools))
        estimate = (prompt_bound * rate_in + max_tokens * rate_out) / 1_000_000
        return payload, estimate, (rate_in, rate_out)

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

    def _release_attempt(self, reservation: _Reservation, model: str, *, reason: str | None) -> None:
        if self.spend.release(reservation, unconfirmed=reason is not None) and reason is not None:
            self._append_spend(model, outcome="unconfirmed", exposure_usd=float(reservation.amount), reason=reason)

    def _record_spend(self, model: str, resp: dict, *, reservation: _Reservation | None = None,
                      rates: tuple[Decimal, Decimal] | None = None) -> None:
        usage = resp.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        try:
            cost = _nonnegative_decimal(usage.get("cost"))
        except (ValueError, InvalidOperation):
            rate_in, rate_out = rates or (_nonnegative_decimal(PRICE_IN), _nonnegative_decimal(PRICE_OUT))
            try:
                prompt = _nonnegative_decimal(usage.get("prompt_tokens"))
                completion = _nonnegative_decimal(usage.get("completion_tokens"))
                cost = (prompt * rate_in + completion * rate_out) / 1_000_000
            except (ValueError, InvalidOperation):
                # A successful response without billable usage cannot safely refund any reservation.
                cost = reservation.amount if reservation is not None else Decimal(0)
            usage["cost"] = float(cost)
            usage["cost_estimated"] = True
        resp["usage"] = usage
        self.spend.settle(reservation, cost)
        self._append_spend(model, cost_usd=float(cost), cost_estimated=bool(usage.get("cost_estimated")),
                           prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))

    def _append_spend(self, model: str, **entry: Any) -> None:
        try:
            self.spend_file.parent.mkdir(parents=True, exist_ok=True)
            with self.spend_file.open("a") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": model,
                                    "provider": provider(), "pid": os.getpid(), **entry}) + "\n")
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
