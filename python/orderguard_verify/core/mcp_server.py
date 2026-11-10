"""The gateway process: an MCP server that is the only process that can carry a request out.

The domain pack registers the MCP tools (finance: `propose_order`, `check_memo`). A human approves or rejects held requests through
the review page, which calls /admin/review here with a local token; the review page itself never carries out anything.
Compose with a pack in `orderguard_verify/serve.py`."""
from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

import anyio
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..paths import DB
from .gateway import Gateway

HOST, PORT = "127.0.0.1", int(os.getenv("OG_GATEWAY_PORT", "8765"))
TOKEN_FILE = Path(DB).parent / "admin_token"


def admin_token() -> str:
    if os.getenv("OG_ADMIN_TOKEN"):
        return os.environ["OG_ADMIN_TOKEN"]
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_hex(16))
        os.chmod(TOKEN_FILE, 0o600)
    return TOKEN_FILE.read_text().strip()


def build(gateway: Gateway, instructions: str = "") -> FastMCP:
    lock = asyncio.Lock()
    mcp = FastMCP("OrderGuard Verify", host=HOST, port=PORT, instructions=instructions, log_level="WARNING")

    async def call(fn, *args):
        """Run a gateway call in a worker thread, one at a time (SQLite, and the model call can be slow)."""
        async with lock:
            return await anyio.to_thread.run_sync(fn, *args)

    gateway.pack.register_tools(mcp, gateway, call)

    @mcp.custom_route("/admin/review", methods=["POST"])
    async def review(request: Request) -> JSONResponse:
        if request.headers.get("x-admin-token") != admin_token():
            return JSONResponse({"error": "forbidden"}, status_code=403)
        body = await request.json()
        return JSONResponse(await call(gateway.review, body["run_id"], bool(body["approve"]), "human via review page"))

    @mcp.custom_route("/admin/check", methods=["POST"])
    async def check(request: Request) -> JSONResponse:
        """The review page's paste box: check any text, no request involved."""
        if request.headers.get("x-admin-token") != admin_token():
            return JSONResponse({"error": "forbidden"}, status_code=403)
        body = await request.json()
        return JSONResponse(await call(gateway.check, body["text"], body["context"]))

    return mcp
