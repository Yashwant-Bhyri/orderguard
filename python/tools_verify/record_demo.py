"""Make docs/demo.mp4: a roughly two-minute recording of the real demo.

It starts the gateway and review page, runs the three agent scenarios over MCP (capturing their real output), then records
a Chrome window that (1) replays that output in a terminal-style page, (2) shows the live review page and approves the held
order, and (3) shows the results table. Needs `playwright` and ffmpeg (not project dependencies) and a local Chrome:

    /path/to/venv-with-playwright/bin/python tools/record_demo.py
"""
from __future__ import annotations

import html
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"
PY = str(ROOT / ".venv" / "bin" / "python")
ENV = {**os.environ, "PYTHONPATH": str(ROOT)}
W, H = 1280, 720

SCENES = [("1. An honest memo: the real 10-K figures", "honest"),
          ("2. The same story with a made-up revenue figure and a rumour", "poisoned"),
          ("3. A rumour-led memo: no verified fact behind the trade", "rumour_led")]
GATEWAY_PORT = int(os.getenv("OG_GATEWAY_PORT", "8765"))
UI_PORT = int(os.getenv("OG_UI_PORT", "8766"))

PAGE = """<!doctype html><meta charset=utf-8><style>
body{margin:0;background:#0f1218;color:#d8dee9;font:15px/1.45 Menlo,monospace;overflow:hidden}
#bar{background:#1b2029;padding:8px 14px;color:#8b95a7;font-size:13px}
#t{margin:0;padding:14px 18px;white-space:pre-wrap;height:660px;overflow:hidden}
.h{color:#7fd1ae;font-weight:bold}.k{color:#ff8a80}.o{color:#7fd1ae}.w{color:#f2b45a}.d{color:#8b95a7}
#title{position:fixed;inset:0;background:#0f1218;display:flex;flex-direction:column;align-items:center;justify-content:center;font:28px -apple-system,system-ui,sans-serif;color:#e8ebf1;text-align:center;gap:14px}
#title small{font-size:17px;color:#98a2b3;max-width:900px}</style>
<div id=bar>$ og demo &nbsp;(gateway over MCP · review page · outside agent)</div><pre id=t></pre><div id=title></div>
<script>
const SCENES = __SCENES__;
const t = document.getElementById('t'), title = document.getElementById('title');
function paint(line){
  let c=''; if(/^={5,}/.test(line)) c='h'; else if(/BLOCKED|XX|CONTRADICTED/.test(line)) c='k'; else if(/EXECUTED|\\[OK|CONFIRMED/.test(line)) c='o';
  else if(/HELD|OLD|\\?\\?|UNVERIFIABLE/.test(line)) c='w'; else if(/^agent>|^\\s+evidence|hash /.test(line)) c='d';
  const s=document.createElement('span'); s.className=c; s.textContent=line+'\\n'; t.appendChild(s); t.scrollTop=t.scrollHeight;
}
function card(a,b){title.innerHTML='<div>'+a+'</div><small>'+b+'</small>';title.style.display='flex'}
async function sleep(ms){return new Promise(r=>setTimeout(r,ms))}
window.play = async function(){
  card('OrderGuard Verify','It checks what an AI wrote against what was true on the date it was written, and decides in code. An outside research agent proposes a trade with a memo; nothing is sent anywhere. Unaffiliated research prototype.');
  await sleep(7000); title.style.display='none';
  for (const sc of SCENES){
    paint('='.repeat(78)); paint(sc.title); paint('='.repeat(78));
    for (const line of sc.lines){ paint(line); await sleep(line.trim()==='' ? 150 : 520); }
    await sleep(4500); paint('');
  }
  window.done = true;
}
</script>"""


def wait_port(port: int) -> None:
    for _ in range(150):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
            return
        except OSError:
            time.sleep(0.2)
    raise SystemExit(f"port {port} never opened")


def capture_scenes() -> list[dict]:
    scenes = []
    for title, packet in SCENES:
        out = subprocess.run([PY, "-m", "orderguard_verify.finance.agent", f"data/demo/packets/{packet}.txt"], cwd=ROOT, env=ENV,
                             capture_output=True, text=True, timeout=900)
        scenes.append({"title": title, "lines": (out.stdout + out.stderr).replace("\r", "").splitlines()})
    return scenes


def md_to_html(md: str) -> str:
    out, rows = [], []

    def flush():
        if rows:
            head, *body = [r for r in rows if not set(r.replace("|", "").strip()) <= set("-: ")]
            cells = lambda r, tag: "".join(f"<{tag}>{html.escape(c.strip())}</{tag}>" for c in r.strip().strip("|").split("|"))
            out.append("<table><tr>" + cells(head, "th") + "</tr>" + "".join("<tr>" + cells(r, "td") + "</tr>" for r in body) + "</table>")
            rows.clear()

    for line in md.splitlines():
        if line.startswith("|"):
            rows.append(line)
        else:
            flush()
            if line.strip():
                out.append(f"<p>{html.escape(line)}</p>")
    flush()
    return "".join(out)


def headline() -> str:
    """The hold-out table, produced by the project's own environment (this script runs in one that only has playwright)."""
    code = "from orderguard_verify.native import run; print(run.headline('holdout'))"
    return subprocess.run([PY, "-c", code], cwd=ROOT, env=ENV, capture_output=True, text=True, check=True).stdout


def results_html() -> str:
    return ("<!doctype html><meta charset=utf-8><style>body{margin:0;background:#12151b;color:#e8ebf1;font:16px/1.5 -apple-system,system-ui,sans-serif}"
            "table{border-collapse:collapse;margin:10px 0 18px}th,td{border:1px solid #2c3340;padding:5px 12px;text-align:left}th{background:#1a1f28}p{margin:6px 0}</style>"
            "<div style='max-width:1150px;margin:26px auto;padding:0 20px'><h2 style='margin:0 0 4px'>Memos nobody prepared: hold-out run</h2>"
            "<p style='color:#98a2b3'>Run once from a frozen commit. Free models, 16 companies not used for tuning.</p>"
            + md_to_html(headline()) + "</div>")


CLOSING = ("<body style='margin:0;background:#0f1218;color:#e8ebf1;font:26px -apple-system,system-ui,sans-serif;display:flex;flex-direction:column;"
           "align-items:center;justify-content:center;height:100vh;gap:14px;text-align:center'><div>LLMs read and interpret. Code decides.</div>"
           "<div style='font-size:17px;color:#98a2b3;max-width:900px'>Hold-out result on free models, labels by a separate agent and not yet human-reviewed; "
           "every failure is published in results/. Unaffiliated research prototype. Run it yourself: <code>og demo</code></div></body>")


def main() -> None:
    var = Path(os.getenv("OG_VAR", ROOT / "var"))
    (var / "orderguard.db").unlink(missing_ok=True)
    procs = [subprocess.Popen([PY, "-m", "orderguard_verify.serve", n], cwd=ROOT, env=ENV) for n in ("gateway", "ui")]
    try:
        wait_port(GATEWAY_PORT), wait_port(UI_PORT)
        scenes = capture_scenes()
        OUT.mkdir(exist_ok=True)
        var.mkdir(exist_ok=True)
        (var / "results.html").write_text(results_html())
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(var / "video"),
                                      record_video_size={"width": W, "height": H}, color_scheme="dark")
            page = ctx.new_page()
            (var / "player.html").write_text(PAGE.replace("__SCENES__", json.dumps(scenes)))
            page.goto(f"file://{var / 'player.html'}")
            page.wait_for_timeout(500)
            page.evaluate("setTimeout(() => play(), 0)")      # do not wait for the whole animation here
            page.wait_for_function("window.done === true", timeout=600_000)
            page.wait_for_timeout(1500)
            page.goto(f"http://127.0.0.1:{UI_PORT}")                       # the live review page
            page.wait_for_timeout(5000)
            for y in (0, 500, 1000, 1600):
                page.evaluate(f"window.scrollTo({{top:{y},behavior:'smooth'}})")
                page.wait_for_timeout(5500)
            page.evaluate("window.scrollTo({top:0,behavior:'smooth'})")
            page.wait_for_timeout(2500)
            page.locator("button.go").first.scroll_into_view_if_needed()
            page.wait_for_timeout(3000)
            page.locator("button.go").first.click()                   # the human approves the held order
            page.wait_for_timeout(4000)
            page.evaluate("window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'})")
            page.wait_for_timeout(9000)
            page.goto(f"file://{var / 'results.html'}")
            page.wait_for_timeout(26000)
            page.set_content(CLOSING)
            page.wait_for_timeout(8000)
            ctx.close()
            video = Path(page.video.path())
            browser.close()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "26",
                        "-r", "25", str(OUT / "demo.mp4")], check=True)
        print("wrote", OUT / "demo.mp4")
    finally:
        for pr in procs:
            pr.terminate()


if __name__ == "__main__":
    main()
