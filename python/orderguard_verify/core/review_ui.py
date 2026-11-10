"""Review page: shows each decision with its evidence card; a human approves or rejects held requests.

Read-only on the database. Approvals are sent to the gateway (which alone can carry anything out).

    python -m orderguard_verify.serve ui          # http://127.0.0.1:8766
"""
from __future__ import annotations

import hmac
import os
import secrets
from html import escape
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ..paths import DB as DEFAULT_DB
from .card import html_card
from .mcp_server import PORT as GATEWAY_PORT
from .mcp_server import admin_token
from .runs import RunStore

UI_PORT = int(os.getenv("OG_UI_PORT", "8766"))
CSS = """
:root{--bg:#f6f7f9;--fg:#1c2330;--mute:#5b6678;--card:#fff;--line:#dde1e8;--ok:#14733f;--bad:#b3261e;--warn:#9a5b00;--hold:#6a3fb5}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--fg:#e8ebf1;--mute:#98a2b3;--card:#1a1f28;--line:#2c3340;--ok:#4cc38a;--bad:#ff8a80;--warn:#f2b45a;--hold:#b79cff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,Segoe UI,sans-serif}
main{max-width:920px;margin:0 auto;padding:20px 16px 60px}h1{font-size:20px;margin:0}header p{color:var(--mute);margin:.2rem 0 1rem}
h2.sec{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);margin:28px 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.card h2{font-size:17px;margin:0 0 2px}.card h3{font-size:13px;margin:12px 0 4px;color:var(--mute)}.meta{color:var(--mute);font-size:13px;margin:0 0 8px}
.act{font-weight:700;padding:1px 8px;border-radius:5px;color:#fff;font-size:13px}.act.pass{background:var(--ok)}.act.revise{background:var(--warn)}.act.block{background:var(--bad)}.act.escalate{background:var(--hold)}
.alert{color:var(--bad);font-weight:700;font-size:12px;margin-left:6px}small{color:var(--mute);font-weight:400}
table{width:100%;border-collapse:collapse}td{vertical-align:top;padding:7px 6px;border-top:1px solid var(--line)}td:first-child{width:130px;white-space:nowrap}
.tag{font-size:12px;font-weight:700;padding:1px 7px;border-radius:5px;border:1px solid currentColor}.tag.confirmed{color:var(--ok)}.tag.contradicted{color:var(--bad)}.tag.stale{color:var(--warn)}.tag.unverifiable{color:var(--mute)}
.why{color:var(--mute);font-size:13px}.ev{font-size:12px;color:var(--mute);margin-top:3px}code{font-size:11px}a{color:inherit}
form.act-row{display:flex;gap:8px;margin-top:10px}button{font:inherit;font-weight:600;padding:7px 16px;border-radius:7px;border:1px solid var(--line);cursor:pointer;background:var(--card);color:var(--fg)}
button.go,button.chk{background:var(--ok);color:#fff;border-color:transparent}button.no{border-color:var(--bad);color:var(--bad)}
.empty{color:var(--mute)}
form.paste{display:grid;gap:8px}form.paste .row{display:flex;gap:8px;flex-wrap:wrap}input,textarea{font:inherit;padding:7px 9px;border-radius:7px;border:1px solid var(--line);background:var(--bg);color:var(--fg)}
textarea{width:100%;min-height:120px}.hint{color:var(--mute);font-size:13px}
"""


POLL_JS = ("let v=null;setInterval(async()=>{try{const j=await (await fetch('/api/version')).json();"
           "const t=document.querySelector('textarea');if(v!==null&&j.v!==v&&!(t&&t.value))location.reload();v=j.v}catch(e){}},3000)")


def page(body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>OrderGuard Verify review</title><style>{CSS}</style></head><body><main>'
            f'<header><h1>OrderGuard Verify <small>review desk</small></h1><p>Unaffiliated research prototype. Nothing here carries out a real-world action.</p></header>{body}</main><script>{POLL_JS}</script></body></html>')


def paste_form(fields: str, hint: str) -> str:
    """The pack supplies the input fields (their names are the pack's Context fields) and a one-line hint."""
    return ('<h2 class="sec">Check a text</h2><form class="card paste" method="post" action="/check" onsubmit="this.querySelector(\'button\').disabled=true;'
            'this.querySelector(\'button\').textContent=\'Checking, this can take a minute...\'">'
            f'<div class="row">{fields}</div><textarea name="text" placeholder="Paste the text to check" required></textarea>'
            f'<div class="row"><button class="chk">Check it</button><span class="hint">{escape(hint)}</span></div></form>')


def make_app(db_path: str | Path = DEFAULT_DB, form_fields: str = "", form_hint: str = "", token: str | None = None) -> FastAPI:
    """`token` is the per-boot secret a human must type to approve or reject; a random one is made if none is given (see app.state.token).
    The page never contains it: it is printed once, on the terminal that started the page."""
    app = FastAPI(title="OrderGuard Verify review")
    app.state.token = token or secrets.token_urlsafe(18)
    form = paste_form(form_fields, form_hint)

    def store() -> RunStore | None:
        return RunStore(db_path, read_only=True) if Path(db_path).exists() else None

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        rs = store()
        if rs is None:
            return page(form + '<p class="empty">No checks yet.</p>')
        held = rs.pending()
        rows = [r for r in rs.all_runs() if r["run_id"] not in held]
        out = ['<h2 class="sec">Waiting for you</h2>']
        for rid in held:
            r, _ = rs.get(rid)
            out.append(html_card(r, "held: needs a human decision") + (
                f'<form class="act-row" method="post" action="/review/{escape(rid)}">'
                f'<input type="password" name="token" placeholder="review token (printed at startup)" autocomplete="off" required size="26">'
                f'<button class="go" name="decision" value="approve">Approve</button>'
                f'<button class="no" name="decision" value="reject">Reject</button></form>'))
        if not held:
            out.append('<p class="empty">Nothing is waiting.</p>')
        out.append('<h2 class="sec">Decided</h2>')
        for run in rows[:12]:
            r, row = rs.get(run["run_id"])
            out.append(html_card(r, row["status"].replace("_", " ")))
        if not rows:
            out.append('<p class="empty">No decisions yet.</p>')
        return page(form + "".join(out))

    @app.post("/check")
    async def check(request: Request):
        fields = {k: str(v).strip() for k, v in (await request.form()).items()}
        text = fields.pop("text", "")
        try:
            r = httpx.post(f"http://127.0.0.1:{GATEWAY_PORT}/admin/check", timeout=900, headers={"x-admin-token": admin_token()},
                           json={"text": text, "context": {k: v or None for k, v in fields.items()}})
            r.raise_for_status()
        except httpx.HTTPError:
            return HTMLResponse(page('<div class="card"><h2>Could not reach the checker</h2><p class="meta">The gateway is not running or did not answer. '
                                     'Start it with <code>python -m orderguard_verify.serve gateway</code> and try again. Your text is below.</p>'
                                     f'<textarea readonly>{escape(text)}</textarea></div>'), status_code=502)
        return RedirectResponse("/", status_code=303)

    @app.post("/review/{run_id}")
    def review(run_id: str, decision: str = Form(...), token: str = Form("")):
        if not hmac.compare_digest(token.encode(), app.state.token.encode()):
            return PlainTextResponse("forbidden: the review token is missing or wrong", status_code=403)
        httpx.post(f"http://127.0.0.1:{GATEWAY_PORT}/admin/review", timeout=30, headers={"x-admin-token": admin_token()},
                   json={"run_id": run_id, "approve": decision == "approve"})
        return RedirectResponse("/", status_code=303)

    @app.get("/api/version")
    def version() -> dict:
        """Changes whenever a decision or its status changes, so the page reloads only when there is something new."""
        rs = store()
        return {"v": "|".join(f"{r['run_id']}:{r['status']}" for r in rs.all_runs()) if rs else ""}

    @app.get("/healthz")
    def health() -> dict:
        return {"ok": True}

    return app
