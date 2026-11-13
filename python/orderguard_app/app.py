"""FastAPI app. Bound to 127.0.0.1 by default; optional bearer token via ORDERGUARD_APP_TOKEN."""
from __future__ import annotations

import hashlib
import hmac
import re
import logging
import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import services as S
from .models import CheckOrderRequest, ScenarioRequest, ScreenRequest, TriggerGraphRequest

STATIC = Path(__file__).parent / "static"
MAX_BODY = 1_000_000
log = logging.getLogger("orderguard.app")


def _versioned_index() -> str:
    """index.html with every /static/<file> reference tagged ?v=<content hash>, so a changed asset always gets a new URL
    and no browser can run a stale script or stylesheet after an upgrade."""
    html = (STATIC / "index.html").read_text()

    def tag(m: "re.Match") -> str:
        f = STATIC / m.group(2)
        if not f.is_file():
            return m.group(0)
        return f'{m.group(1)}/static/{m.group(2)}?v={hashlib.sha256(f.read_bytes()).hexdigest()[:12]}{m.group(3)}'
    return re.sub(r'((?:src|href)=")/static/([A-Za-z0-9_.-]+)(")', tag, html)


def create_app(token: str | None = None) -> FastAPI:
    # the app never makes a live model call unless the operator sets OG_LLM=record or live explicitly
    os.environ.setdefault("OG_LLM", "replay")
    token = token if token is not None else os.getenv("ORDERGUARD_APP_TOKEN") or None
    state = S.State()
    app = FastAPI(title="OrderGuard", version="0.1.0", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json" if not token else None)

    def auth(request: Request) -> None:
        if not token:
            return
        got = request.headers.get("authorization", "")
        scheme, _, value = got.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(value.encode(), token.encode()):
            raise HTTPException(401, "a valid bearer token is required", headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def limits(request: Request, call_next):
        try:
            too_big = int(request.headers.get("content-length") or 0) > MAX_BODY
        except ValueError:
            too_big = True
        if too_big:
            return JSONResponse({"error": "request body too large"}, status_code=413)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        else:
            # The page and its scripts revalidate on every load (ETag/Last-Modified), so an upgrade never runs stale JS.
            resp.headers.setdefault("Cache-Control", "no-cache")
        return resp

    @app.exception_handler(S.AppError)
    async def _app_error(_: Request, e: S.AppError):
        return JSONResponse({"error": e.message}, status_code=e.status)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, e: HTTPException):
        return JSONResponse({"error": e.detail}, status_code=e.status_code, headers=getattr(e, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, e: RequestValidationError):
        return JSONResponse({"error": "invalid request", "details": [{"where": ".".join(str(x) for x in d["loc"]), "problem": d["msg"]} for d in e.errors()]},
                            status_code=422)

    @app.exception_handler(Exception)
    async def _crash(_: Request, e: Exception):
        ref = secrets.token_hex(4)
        log.error("unhandled %s (ref %s)", type(e).__name__, ref)          # the type only: messages can carry request data
        return JSONResponse({"error": "internal error", "ref": ref}, status_code=500)

    api = [Depends(auth)]

    # Agent-swarm arena and envelope lab (python/orderguard_arena): same bearer auth as every other /api route.
    from orderguard_arena.api import router as arena_router
    app.include_router(arena_router, dependencies=api)

    @app.get("/api/health", dependencies=api)
    def health():
        return S.health()

    @app.get("/api/overview", dependencies=api)
    def overview():
        return S.overview(state)

    @app.post("/api/screen", dependencies=api)
    def screen(req: ScreenRequest):
        return S.screen_text(state, req.text, req.kind)

    @app.get("/api/mandate", dependencies=api)
    def mandate():
        return {"mandate": state.mandate, "public_key": state.public_key, "note": "signed at startup with a fresh in-memory Ed25519 key"}

    @app.post("/api/check-order", dependencies=api)
    def check_order(req: CheckOrderRequest):
        return S.check_order(state, req.order, req.mandate, req.prices, req.as_of, req.daily_total_usd, req.require_figures)

    @app.post("/api/trigger-graph", dependencies=api)
    def trigger_graph(req: TriggerGraphRequest):
        return S.trigger_graph(req.rules, req.events, req.preset, req.quarantined_sources, req.blast_source, req.lies)

    @app.get("/api/scenarios", dependencies=api)
    def scenarios():
        return {"scenarios": S.list_scenarios()}

    @app.post("/api/run-scenario", dependencies=api)
    def run_scenario(req: ScenarioRequest):
        return S.run_scenario(state, req.scenario, req.arm)

    @app.get("/api/ledger", dependencies=api)
    def ledger():
        return S.ledger()

    @app.get("/api/results", dependencies=api)
    def results():
        return S.results()

    @app.get("/", include_in_schema=False)
    def index():
        return HTMLResponse(_versioned_index(), headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def serve(host: str = "127.0.0.1", port: int = 8600) -> None:
    import uvicorn
    if not os.getenv("ORDERGUARD_APP_TOKEN") and host not in ("127.0.0.1", "localhost", "::1"):
        print("warning: binding a non-loopback address with no ORDERGUARD_APP_TOKEN; anyone who can reach it can use the API")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
