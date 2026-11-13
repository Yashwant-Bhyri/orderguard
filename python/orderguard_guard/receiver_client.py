"""L8 client: talks to the receiver bridge (CONTRACT §5.1) and can start and stop the bridge subprocess.

    with Bridge.start(mandate_path) as b:        # node receiver/bridge/serve.mjs --port 0 --mandate <file>, reads "READY <port>"
        b.receiver.propose(symbol="AAPL", side="buy", quantity=10, limit_price=222.7, client_order_id="o1")

`bridge_available()` says whether node and the bridge script exist; the demo falls back to a local paper ledger when they do not.
"""
from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

import httpx

from . import ROOT

BRIDGE_SCRIPT = ROOT / "receiver" / "bridge" / "serve.mjs"


class ReceiverError(RuntimeError):
    pass


def bridge_available() -> tuple[bool, str]:
    if shutil.which("node") is None:
        return False, "node is not installed"
    if not BRIDGE_SCRIPT.exists():
        return False, "receiver/bridge/serve.mjs does not exist yet"
    return True, ""


class Receiver:
    """HTTP client for the bridge: /health, /propose, /revoke, /snapshot."""

    def __init__(self, base_url: str, timeout: float = 20.0, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self._c = client or httpx.Client(timeout=timeout)

    def _req(self, method: str, path: str, **kw) -> dict:
        try:
            r = self._c.request(method, self.base_url + path, **kw)
        except httpx.HTTPError as e:
            raise ReceiverError(f"receiver unreachable: {type(e).__name__}") from e
        if r.status_code >= 500:
            raise ReceiverError(f"receiver error HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ReceiverError("receiver sent a reply that is not JSON") from e

    def health(self) -> dict:
        return self._req("GET", "/health")

    def policy(self) -> dict:
        return self._req("GET", "/policy")

    def activate_policy(self, authorization: dict) -> dict:
        return self._req("POST", "/policy/activate", json=authorization)

    def approve_paper_order(self, order_id: str, authorization: dict) -> dict:
        return self._req("POST", "/approve", json={"orderId": order_id, "authorization": authorization})

    def propose(self, symbol: str, side: str, quantity: int, limit_price: float, client_order_id: str | None = None) -> dict:
        """-> {"decision": "filled"|"denied"|"held", "reason", "orderId"?, "ledgerEffect": bool}"""
        return self._req("POST", "/propose", json={"symbol": symbol, "side": side, "quantity": quantity, "limitPrice": limit_price,
                                                   "clientOrderId": client_order_id or uuid.uuid4().hex[:12]})

    def revoke(self) -> dict:
        return self._req("POST", "/revoke", json={})

    def snapshot(self) -> dict:
        """-> {"orders": [...], "ledgerIntegrity": bool}"""
        return self._req("GET", "/snapshot")

    def close(self) -> None:
        self._c.close()


class Bridge:
    """The bridge subprocess. Use `Bridge.start(mandate_path)` as a context manager."""

    def __init__(self, proc: subprocess.Popen, port: int):
        self.proc, self.port = proc, port
        self.receiver = Receiver(f"http://127.0.0.1:{port}")

    @classmethod
    def start(cls, mandate_path, *, timeout: float = 30.0, node: str = "node", port: int = 0,
              owner_public_key=None, revocations=None) -> "Bridge":
        ok, why = bridge_available()
        if not ok:
            raise ReceiverError(why)
        mode = ["--mandate", str(mandate_path)] if owner_public_key is None else [
            "--parent-proof", str(mandate_path), "--owner-public-key", str(owner_public_key)]
        if revocations is not None:
            mode.extend(["--revocations", str(revocations)])
        proc = subprocess.Popen([node, str(BRIDGE_SCRIPT), "--port", str(port), *mode], cwd=str(ROOT),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        q: queue.Queue = queue.Queue()

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
                    err = (proc.stderr.read() or "").strip().splitlines()      # type: ignore[union-attr]
                    raise ReceiverError("the bridge exited before it was ready: " + (err[-1] if err else f"exit code {proc.returncode}"))
                if line.startswith("READY"):
                    port = int(line.split()[1])
                    break
        except Exception:
            proc.kill()
            raise
        return cls(proc, port)

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
