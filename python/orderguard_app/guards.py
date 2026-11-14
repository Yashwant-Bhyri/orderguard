"""Pure-ASGI protections in front of every route: body-size cap (also for chunked bodies), per-route concurrency cap and
wall-clock deadline for the heavy routes, a simple in-process rate limit, and the security headers.

Everything is in-process and per client address. It is a safety net for a single local instance, not a distributed limiter:
behind a reverse proxy, rate-limit there too (docs/OPERATIONS.md).

Limits are environment-tunable: ORDERGUARD_RATE_LIMIT=0 disables rate limiting; ORDERGUARD_RATE_SCALE=2 doubles every
per-minute allowance; ORDERGUARD_TIMEOUT_SCALE=2 doubles every deadline.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from collections import deque
from dataclasses import dataclass

MAX_BODY = 1_000_000


@dataclass(frozen=True)
class Limit:
    prefix: str            # path prefix the limit applies to
    per_minute: int        # requests allowed per client per minute
    timeout_s: float       # wall-clock deadline: the client gets 504 after this, whatever the handler is still doing
    concurrent: int        # at most this many in flight across all clients; the rest get 503 immediately


# Longest prefix wins. Heavy simulation routes are tight; cheap routes are generous but still bounded.
LIMITS = (
    Limit("/api/arena/", 30, 30.0, 2),
    Limit("/api/run-scenario", 20, 120.0, 2),      # live mode can include model calls
    Limit("/api/review/", 60, 30.0, 4),            # one decision-model call each (about a second live)
    Limit("/api/screen", 120, 60.0, 8),
    Limit("/api/check-order", 240, 60.0, 8),
    Limit("/api/trigger-graph", 120, 30.0, 4),
)
DEFAULT = Limit("/api/", 600, 30.0, 32)

SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"content-security-policy", b"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; "
                                 b"object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
)


def limit_for(path: str) -> Limit | None:
    best = None
    for lim in LIMITS:
        if path.startswith(lim.prefix) and (best is None or len(lim.prefix) > len(best.prefix)):
            best = lim
    if best is None and path.startswith("/api/"):
        return DEFAULT
    return best


def _scale(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


class Guards:
    def __init__(self, app, max_body: int = MAX_BODY, token: str | None = None):
        self.app, self.max_body, self.token = app, max_body, token
        self._hits: dict[tuple[str, str], deque] = {}
        self._inflight: dict[str, int] = {}
        self._last_sweep = time.monotonic()

    # ---- helpers ---------------------------------------------------------------------------------------------------
    @staticmethod
    async def _json(send, status: int, body: dict, extra: list[tuple[bytes, bytes]] | None = None) -> None:
        raw = json.dumps(body).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()), (b"cache-control", b"no-store"), *SECURITY_HEADERS,
                   *(extra or [])]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": raw})

    def _rate_ok(self, client: str, lim: Limit) -> int:
        """0 when allowed, else the seconds to wait."""
        if (os.getenv("ORDERGUARD_RATE_LIMIT") or "1") == "0":
            return 0
        allowance = max(1, int(lim.per_minute * _scale("ORDERGUARD_RATE_SCALE", 1.0)))
        now = time.monotonic()
        if now - self._last_sweep > 120:                       # forget idle clients so the table cannot grow without bound
            self._last_sweep = now
            for k in [k for k, q in self._hits.items() if not q or now - q[-1] > 60]:
                del self._hits[k]
        q = self._hits.setdefault((client, lim.prefix), deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= allowance:
            return max(1, int(60 - (now - q[0])) + 1)
        q.append(now)
        return 0

    async def _buffer_body(self, receive):
        """Read a body that arrived without a trusted Content-Length, up to the cap. Returns (chunks, too_big)."""
        chunks, total = [], 0
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return chunks, False
            chunk = msg.get("body", b"")
            total += len(chunk)
            if total > self.max_body:
                return chunks, True
            chunks.append(chunk)
            if not msg.get("more_body"):
                return chunks, False

    def _authorised(self, headers: dict) -> bool:
        scheme, _, value = headers.get(b"authorization", b"").decode("latin-1").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(value.encode(), self.token.encode())

    # ---- ASGI ------------------------------------------------------------------------------------------------------
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Authentication first, before any body is read or parsed, so an unauthenticated caller learns nothing (not even a schema error).
        # The per-route dependency stays as a second line of defence.
        if self.token and path.startswith("/api/") and not self._authorised(headers):
            await self._json(send, 401, {"error": "a valid bearer token is required"}, [(b"www-authenticate", b"Bearer")])
            return

        declared = headers.get(b"content-length")
        try:
            too_big = declared is not None and int(declared) > self.max_body
        except ValueError:
            await self._json(send, 400, {"error": "malformed Content-Length header"})
            return
        if too_big:
            await self._json(send, 413, {"error": f"request body too large (limit {self.max_body} bytes)"})
            return
        if declared is None and method in ("POST", "PUT", "PATCH") and headers.get(b"transfer-encoding"):
            chunks, over = await self._buffer_body(receive)
            if over:
                await self._json(send, 413, {"error": f"request body too large (limit {self.max_body} bytes)"})
                return
            replay = iter(chunks)

            async def receive():                                # noqa: F811 - replays the buffered body to the app
                chunk = next(replay, None)
                if chunk is None:
                    return {"type": "http.request", "body": b"", "more_body": False}
                return {"type": "http.request", "body": chunk, "more_body": True}
            # Terminate the stream: the final empty message above ends it.

        lim = limit_for(path) if method != "OPTIONS" else None
        if lim is None:
            await self.app(scope, receive, self._with_headers(send, path))
            return

        client = (scope.get("client") or ("unknown", 0))[0]
        wait = self._rate_ok(client, lim)
        if wait:
            await self._json(send, 429, {"error": "too many requests for this route", "hint": f"wait {wait}s and retry; limit is {lim.per_minute}/minute per client"},
                             [(b"retry-after", str(wait).encode())])
            return
        if self._inflight.get(lim.prefix, 0) >= lim.concurrent:
            await self._json(send, 503, {"error": "the server is busy with other requests of this kind", "hint": "retry in a few seconds"}, [(b"retry-after", b"3")])
            return

        deadline = lim.timeout_s * _scale("ORDERGUARD_TIMEOUT_SCALE", 1.0)
        self._inflight[lim.prefix] = self._inflight.get(lim.prefix, 0) + 1
        timed_out = False
        started = False

        async def guarded_send(message):
            nonlocal started
            if timed_out:
                return                                          # the client already has its 504; discard whatever the handler produces late
            if message["type"] == "http.response.start":
                started = True
                message = {**message, "headers": self._merge(message.get("headers"), path)}
            await send(message)

        async def run():
            try:
                await self.app(scope, receive, guarded_send)
            finally:
                self._inflight[lim.prefix] -= 1                 # released when the work really ends, not when the client gave up

        task = asyncio.ensure_future(run())
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=deadline)
        except asyncio.TimeoutError:
            timed_out = True
            if not started:
                await self._json(send, 504, {"error": f"the request took longer than {deadline:.0f}s and was abandoned",
                                             "hint": "reduce agents/steps or the input size and try again"})
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        except asyncio.CancelledError:                          # client went away
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            raise

    # ---- headers ---------------------------------------------------------------------------------------------------
    @staticmethod
    def _merge(existing, path: str) -> list:
        have = {k.lower() for k, _ in (existing or [])}
        out = list(existing or [])
        for k, v in SECURITY_HEADERS:
            if k not in have:
                out.append((k, v))
        if b"cache-control" not in have:
            out.append((b"cache-control", b"no-store" if path.startswith("/api/") else b"no-cache"))
        return out

    def _with_headers(self, send, path: str):
        async def wrapped(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": self._merge(message.get("headers"), path)}
            await send(message)
        return wrapped
