"""L8 client: talks to the receiver bridge (CONTRACT §5.1) and can start and stop the bridge subprocess.

    with Bridge.start(mandate_path) as b:        # node receiver/bridge/serve.mjs --port 0 --mandate <file>, reads "READY <port>"
        b.receiver.propose(symbol="AAPL", side="buy", quantity=10, limit_price=222.7, client_order_id="o1")

`bridge_available()` says whether node and the bridge script exist; the demo falls back to a local paper ledger when they do not.
"""
from __future__ import annotations

import math
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import httpx

from . import ROOT

BRIDGE_SCRIPT = ROOT / "receiver" / "bridge" / "serve.mjs"


def scrub(text: object) -> str:
    """Remove the home directory, the checkout path, bearer tokens and the values of secret-looking environment variables from text
    that will be shown to a person or written to a log."""
    out = str(text)
    for secret in (v for k, v in os.environ.items() if v and len(v) >= 8 and re.search(r"KEY|SECRET|TOKEN|PASSWORD", k, re.I)):
        out = out.replace(secret, "***")
    for path, label in ((str(ROOT), "<orderguard>"), (str(Path.home()), "~")):
        if len(path) > 1:
            out = out.replace(path, label)
    out = re.sub(r"/(?:Users|home)/[^\s/'\"]+", "~", out)
    out = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", out, flags=re.I)
    return re.sub(r"(?i)\b((?:api[_-]?key|secret|token|password)\s*[=:]\s*)[^\s,;'\"]+", r"\1***", out)


class ReceiverError(RuntimeError):
    """The receiver could not be used. The text says what happened and what to do, with no secrets and no absolute paths.

    `outcome_unknown` is True when the request may have reached the receiver (a timeout or a dropped connection after sending): a
    retry with the SAME client order id is then safe, because the receiver applies each id at most once. `transient` is True when a
    later retry may succeed (unreachable, timeout, 5xx)."""

    def __init__(self, message: str = "", *, transient: bool = False, outcome_unknown: bool = False):
        super().__init__(scrub(message))
        self.transient, self.outcome_unknown = transient, outcome_unknown

_DECISIONS = ("filled", "denied", "held")
_SAFE_TO_RETRY = {("GET", "/health"), ("GET", "/snapshot"), ("GET", "/policy"), ("POST", "/propose"), ("POST", "/revoke"), ("POST", "/approve")}


def bridge_available() -> tuple[bool, str]:
    if shutil.which("node") is None:
        return False, "node is not installed"
    if not BRIDGE_SCRIPT.exists():
        return False, "receiver/bridge/serve.mjs does not exist yet"
    return True, ""


class Receiver:
    """HTTP client for the bridge: /health, /propose, /revoke, /snapshot.

    Reads, `propose`, `revoke` and `approve` are retried (`retries` extra attempts, short backoff) on a connection failure, a timeout or
    HTTP 5xx. That cannot double-commit: the receiver applies each clientOrderId at most once and answers a repeat from its ledger, and
    `propose` fixes the id before the first attempt. `activate_policy` is never retried by this client."""

    def __init__(self, base_url: str, timeout: float = 20.0, client: httpx.Client | None = None, *, retries: int = 2, backoff: float = 0.2,
                 sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self._c = client or httpx.Client(timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)), trust_env=False)
        self.timeout, self.retries, self.backoff, self._sleep = timeout, max(0, int(retries)), backoff, sleep

    def _once(self, method: str, path: str, kw: dict) -> dict:
        try:
            r = self._c.request(method, self.base_url + path, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
            raise ReceiverError("receiver unreachable: nothing was sent. Start it (`orderguard paper-receiver`) and check ORDERGUARD_RECEIVER_URL.",
                                transient=True) from e
        except httpx.HTTPError as e:
            raise ReceiverError(f"receiver unreachable: no complete answer ({type(e).__name__}). The request may or may not have been applied. "
                                "Retry with the same client order id (applied at most once), or check the ledger snapshot.",
                                transient=True, outcome_unknown=True) from e
        if r.status_code >= 500:
            raise ReceiverError(f"receiver error HTTP {r.status_code}. The request may or may not have been applied. Retry with the same "
                                "client order id (applied at most once); if it persists, check the receiver's log.",
                                transient=True, outcome_unknown=True)
        try:
            body = r.json()
        except ValueError as e:
            raise ReceiverError("receiver sent a reply that is not JSON. Check that ORDERGUARD_RECEIVER_URL points at the OrderGuard "
                                "receiver and not another service.") from e
        if not isinstance(body, dict):
            raise ReceiverError("receiver sent a reply that is not a JSON object. Check ORDERGUARD_RECEIVER_URL.")
        return body

    def _req(self, method: str, path: str, **kw) -> dict:
        attempts = 1 + (self.retries if (method, path) in _SAFE_TO_RETRY else 0)
        for n in range(attempts):
            try:
                return self._once(method, path, kw)
            except ReceiverError as e:
                if not e.transient or n == attempts - 1:
                    raise
                self._sleep(self.backoff * (2 ** n))
        raise AssertionError("unreachable")

    def health(self) -> dict:
        return self._req("GET", "/health")

    def policy(self) -> dict:
        return self._req("GET", "/policy")

    def activate_policy(self, authorization: dict) -> dict:
        return self._req("POST", "/policy/activate", json=authorization)

    def approve_paper_order(self, order_id: str, authorization: dict) -> dict:
        return self._req("POST", "/approve", json={"orderId": order_id, "authorization": authorization})

    def propose(self, symbol: str, side: str, quantity: int, limit_price: float, client_order_id: str | None = None) -> dict:
        """-> {"decision": "filled"|"denied"|"held", "reason", "orderId"?, "ledgerEffect": bool}

        Raises ReceiverError, never returns a half-formed answer: a reply without a recognised decision is an error."""
        if isinstance(limit_price, bool) or not isinstance(limit_price, (int, float)) or not math.isfinite(limit_price):
            raise ReceiverError("limit_price must be a finite number; the order was not sent.")
        r = self._req("POST", "/propose", json={"symbol": symbol, "side": side, "quantity": quantity, "limitPrice": limit_price,
                                                "clientOrderId": client_order_id or uuid.uuid4().hex[:12]})
        if r.get("decision") not in _DECISIONS:
            detail = r.get("detail") or r.get("error") or "no decision in the reply"
            raise ReceiverError(f"receiver refused the request: {detail}. Check the order fields and ORDERGUARD_RECEIVER_URL.")
        return r

    def revoke(self) -> dict:
        return self._req("POST", "/revoke", json={})

    def snapshot(self) -> dict:
        """-> {"orders": [...], "ledgerIntegrity": bool}"""
        return self._req("GET", "/snapshot")

    def ledger_ok(self) -> bool:
        """True only if the receiver says its hash-chained ledger verifies. Any failure to ask is False."""
        try:
            return self.snapshot().get("ledgerIntegrity") is True
        except ReceiverError:
            return False

    def close(self) -> None:
        self._c.close()


class Bridge:
    """The bridge subprocess. Use `Bridge.start(mandate_path)` as a context manager."""

    def __init__(self, proc: subprocess.Popen, port: int, stderr_tail: "deque[str] | None" = None):
        self.proc, self.port = proc, port
        self.stderr_tail = stderr_tail if stderr_tail is not None else deque(maxlen=50)
        self.receiver = Receiver(f"http://127.0.0.1:{port}")

    @classmethod
    def start(cls, mandate_path, *, timeout: float = 30.0, node: str = "node", port: int = 0,
              owner_public_key=None, revocations=None, ledger=None) -> "Bridge":
        """`ledger=PATH` keeps the effect ledger in a persistent, verified SQLite file (see docs/receiver/bridge.md); the default is a
        throw-away ledger removed when the bridge stops."""
        ok, why = bridge_available()
        if not ok:
            raise ReceiverError(why)
        mode = ["--mandate", str(mandate_path)] if owner_public_key is None else [
            "--parent-proof", str(mandate_path), "--owner-public-key", str(owner_public_key)]
        if revocations is not None:
            mode.extend(["--revocations", str(revocations)])
        if ledger is not None:
            mode.extend(["--ledger", str(ledger)])
        proc = subprocess.Popen([node, str(BRIDGE_SCRIPT), "--port", str(port), *mode], cwd=str(ROOT),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        q: queue.Queue = queue.Queue()
        tail: deque = deque(maxlen=50)

        def drain():                        # an undrained stderr pipe would eventually block the bridge
            for line in proc.stderr:        # type: ignore[union-attr]
                tail.append(line.rstrip())
        threading.Thread(target=drain, daemon=True).start()

        def pump():
            for line in proc.stdout:        # type: ignore[union-attr]
                q.put(line.strip())
            q.put(None)                     # end of output: the process is gone
        threading.Thread(target=pump, daemon=True).start()
        try:
            while True:
                try:
                    line = q.get(timeout=timeout)
                except queue.Empty:
                    raise ReceiverError(f"the bridge did not print READY within {timeout:.0f}s") from None
                if line is None:
                    proc.wait(timeout=5)
                    time.sleep(0.05)        # let the stderr thread take the last line
                    err = [x for x in tail if x.strip()]
                    raise ReceiverError("the bridge exited before it was ready: " + (scrub(err[-1]) if err else f"exit code {proc.returncode}"))
                if line.startswith("READY"):
                    try:
                        port = int(line.split()[1])
                    except (IndexError, ValueError):
                        raise ReceiverError("the bridge printed a READY line without a port; it may be an incompatible version") from None
                    break
        except Exception:
            proc.kill()
            raise
        return cls(proc, port, tail)

    def stop(self) -> None:
        self.receiver.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def __enter__(self) -> "Bridge":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


class LocalLedger:
    """Paper ledger used when no bridge is available. Same `propose`/`snapshot` shape as `Receiver`, plus idempotency on clientOrderId."""

    def __init__(self, market=None):
        self.orders: list[dict] = []
        self._seen: dict[str, dict] = {}
        self.market = market
        self.revoked = False

    def health(self) -> dict:
        return {"ok": True, "ledger": "local"}

    def propose(self, symbol, side, quantity, limit_price, client_order_id=None) -> dict:
        cid = client_order_id or uuid.uuid4().hex[:12]
        if cid in self._seen:
            return dict(self._seen[cid], reason="duplicate clientOrderId: already filled, nothing repeated", ledgerEffect=False)
        if self.revoked:
            return {"decision": "denied", "reason": "the mandate has been revoked", "ledgerEffect": False}
        oid = f"L-{len(self.orders) + 1:05d}"
        self.orders.append({"orderId": oid, "symbol": symbol, "side": side, "quantity": quantity, "limitPrice": limit_price, "clientOrderId": cid})
        res = {"decision": "filled", "reason": "recorded on the local paper ledger", "orderId": oid, "ledgerEffect": True}
        self._seen[cid] = res
        return res

    def revoke(self) -> dict:
        self.revoked = True
        return {"revoked": True}

    def snapshot(self) -> dict:
        return {"orders": list(self.orders), "ledgerIntegrity": True}
