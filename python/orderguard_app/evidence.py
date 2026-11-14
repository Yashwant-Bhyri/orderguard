"""`/evidence/<path>`: a read-only, public view of the committed result and doc files the dashboard cites.

A browser link cannot send a bearer header, so with ORDERGUARD_APP_TOKEN set a plain link to /api/... answers 401. The proof strip and the
Swarm Theater instead link here. This route never asks for the token, so everything it can reach must already be public in the repository.
The rules are in docs/APP.md ("Evidence endpoint"); in short: an explicit prefix and extension allow-list, a name deny-list, no traversal,
no symlinks, regular files only, and a size cap. Nothing outside `results/` and `docs/` is reachable, and nothing is ever written.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import stat
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

ROOT = Path(__file__).resolve().parents[2]          # the repository root; tests point this at a temporary tree
PREFIXES = ("results", "docs")                      # the only top-level directories that can be served
EXTENSIONS = {".json": "application/json", ".jsonl": "text/plain", ".md": "text/plain", ".txt": "text/plain"}
# Names that are never public even inside an allowed directory: spend and ledger records, keys, tokens, env files, databases.
DENY_NAME = re.compile(r"(key|secret|token|passw|credential|\benv\b|\.env|ledger|spend|\.pem|\.sqlite|\.db$|\.log$)", re.I)
MAX_PATH = 200
MAX_RAW = 8_000_000          # bytes served raw; a larger file answers 413 (the biggest committed result file is about 5 MB)
MAX_RENDER = 600_000         # bytes rendered into the readable page; a larger file shows a note and the raw link instead
router = APIRouter()


def resolve(rel: str, root: Path | None = None) -> Path | None:
    """The file for a request path, or None. Every check here is a refusal; None is answered as a plain 404 so a probe learns nothing."""
    root = root or ROOT
    if not rel or len(rel) > MAX_PATH or rel.startswith("/") or "\\" in rel or any(ord(c) < 32 or ord(c) == 127 for c in rel):
        return None
    parts = rel.split("/")
    if parts[0] not in PREFIXES or len(parts) < 2 or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        return None
    if Path(parts[-1]).suffix.lower() not in EXTENSIONS or any(DENY_NAME.search(p) for p in parts):
        return None
    cur = root
    for p in parts:                                  # no component may be a symbolic link, so a link cannot lead out of the tree
        cur = cur / p
        if cur.is_symlink():
            return None
    try:
        real, base = cur.resolve(strict=True), (root / parts[0]).resolve(strict=True)
        if not real.is_relative_to(base) or not stat.S_ISREG(real.stat().st_mode):
            return None
    except (OSError, ValueError):
        return None
    return real


def _read(p: Path) -> bytes | None:
    """Read at most MAX_RAW + 1 bytes without following a link that appeared since resolve()."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(p, flags)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        return f.read(MAX_RAW + 1)


def _not_found() -> Response:
    return Response('{"error": "no such evidence file"}', status_code=404, media_type="application/json", headers={"Cache-Control": "no-store"})


def _page(rel: str, data: bytes, kind: str) -> HTMLResponse:
    digest = hashlib.sha256(data).hexdigest()
    note, body = "", ""
    if len(data) > MAX_RENDER:
        note = f"This file is {len(data):,} bytes, too large to show here. Use the raw file."
    else:
        text = data.decode("utf-8", "replace")
        if kind == "application/json":
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except ValueError:
                pass
        body = html.escape(text)
    esc = html.escape(rel)
    doc = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{esc} - OrderGuard evidence</title><meta name="color-scheme" content="light dark"><meta name="robots" content="noindex">'
        '<script src="/static/theme.js"></script><link rel="stylesheet" href="/static/app.css"></head><body class="ev">'
        f'<header class="ev-head"><a href="/">OrderGuard</a><h1 class="mono">{esc}</h1>'
        f'<p>{len(data):,} bytes, sha256 <span class="mono">{digest[:16]}</span>. A committed file of the repository, shown read-only. '
        f'<a href="/evidence/{esc}?raw=1">Raw file</a></p>'
        + (f'<p class="notice">{html.escape(note)}</p>' if note else "")
        + f'</header><main><pre class="ev-body" tabindex="0">{body}</pre></main></body></html>')
    return HTMLResponse(doc, headers={"Cache-Control": "no-cache", "Content-Disposition": "inline"})


@router.get("/evidence/{path:path}", include_in_schema=False)
def evidence(path: str, request: Request, raw: str | None = None):
    p = resolve(path)
    if p is None:
        return _not_found()
    data = _read(p)
    if data is None:
        return _not_found()
    if len(data) > MAX_RAW:
        return Response('{"error": "file too large to serve"}', status_code=413, media_type="application/json", headers={"Cache-Control": "no-store"})
    kind = EXTENSIONS[p.suffix.lower()]
    if raw is not None:
        return Response(data, media_type=kind + "; charset=utf-8" if kind.startswith("text/") else kind,
                        headers={"Cache-Control": "no-cache", "Content-Disposition": "inline"})
    return _page(path, data, kind)
