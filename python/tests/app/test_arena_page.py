"""The Swarm arena page: the API gives it what it needs, the markup has its hooks, arena.js obeys the dashboard's static contract."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "orderguard_app" / "static"
Q = "seed=7&agents=150&steps=400"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from orderguard_app.app import create_app
    return TestClient(create_app())


def test_arena_endpoints_return_what_the_page_needs(client):
    r = client.get("/api/arena/run?" + Q).json()
    sm = r["summary"]
    assert {"proposals", "replays_absorbed", "bad", "legit", "by_label", "timing", "utilisation_peak", "envelopes", "config"} <= set(sm)
    assert {"attack_notional_usd", "blocked_usd", "leaked_usd", "blocked_share"} <= set(sm["bad"])
    assert {"notional_usd", "refused_usd", "false_refusal_rate"} <= set(sm["legit"])
    assert {"p50", "p95", "p99"} <= set(sm["timing"]["latency_us"]) and "authority_decisions_per_s" in sm["timing"]
    assert {"name", "daily"} <= set(sm["envelopes"][0]) and sm["config"]["steps_per_day"] > 0
    assert {"step", "day", "core"} <= set(r["utilisation"][0]) and r["events_total"] >= len(r["events"]) > 0
    assert {"step", "agent", "label", "order", "risk", "d", "code", "env", "replay"} <= set(r["events"][0])
    assert {"allow_usd", "hold_usd", "refuse_usd", "n"} <= set(next(iter(sm["by_label"].values())))
    f = client.get("/api/arena/frontier?" + Q).json()
    c = f["recommendation"]["candidate"]
    assert {"per_order", "daily", "band_pct", "breadth", "step_up", "agent_share", "leaked_per_day_usd", "utility_per_day_usd", "utility_share", "false_refusal_rate", "approvals_per_day", "label"} <= set(c)
    assert f["frontier"] and {"leaked_per_day_usd", "utility_per_day_usd"} <= set(f["frontier"][0])
    assert {"max_leak_per_day_usd", "max_approvals_per_day", "max_false_refusal_rate"} <= set(f["recommendation"]["risk_budget"])
    assert "utility_per_day_usd" in f["baseline"] and f["recommendation"]["proposed_mandate"]["symbols"] and f["recommendation"]["explanation"]
    assert client.get("/api/arena/envelopes").json()["envelopes"]


def test_arena_requires_the_same_token(client, monkeypatch):
    from fastapi.testclient import TestClient
    from orderguard_app.app import create_app
    monkeypatch.setenv("ORDERGUARD_APP_TOKEN", "t")
    assert TestClient(create_app()).get("/api/arena/run?" + Q).status_code == 401


def test_page_markup_and_hooks():
    html = (ROOT / "index.html").read_text()
    assert 'href="#arena"' in html and "Swarm arena" in html and re.search(r'data-view="arena".*L5.*L7.*L8', html)
    assert html.index('data-view="scenario"') < html.index('data-view="arena"') < html.index('data-view="ledger"')
    assert 'id="arena"' in html and 'aria-labelledby="h-arena"' in html and 'id="ar-out"' in html and 'aria-live="polite"' in html
    assert "Many agents, one signed envelope." in html and "No orders reach any exchange." in html
    for hook in ('id="ar-seed"', 'name="ar-agents"', 'id="ar-steps"', 'name="ar-routing"', 'id="ar-share-on"', 'id="ar-feed"', "Run arena", 'id="ar-cli"', 'id="ar-copy"'):
        assert hook in html, hook
    assert html.index("pages2.js") < html.index("arena.js") < html.index("app.js")
    js = (ROOT / "arena.js").read_text()
    for text in ("The tape", "Envelopes over time", "Who got through", "Latency", "Envelope lab", "Reveal ground truth", "Show the numbers", "Arena: run 1,000 agents", "Arena: envelope lab",
                 "A per-agent share limits how much one agent can consume", "the order-risk layer below scores behaviour across agents", "It can only tighten", "is not re-simulated",
                 "Agents can never choose or widen their own envelope", 'role: "img"', "reduceMotion"):
        assert text in js, text
    assert "arena:" in (ROOT / "app.js").read_text() and 'a: "arena"' in (ROOT / "app.js").read_text()


def test_arena_js_static_contract():
    js = (ROOT / "arena.js").read_text()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", ".cssText", 'setAttribute("style"', "XMLHttpRequest", "WebSocket"):
        assert bad not in js, bad
    assert not re.search(r"https?://", js) and not re.search(r"""style\s*[:=]\s*["']""", js)
    assert js.count("fetch(") == 0                      # all data access goes through OG.api
    assert sum(p.stat().st_size for p in ROOT.iterdir() if p.is_file()) < 260_000   # ceiling raised from 200 KB for the Swarm Theater (its own page, stylesheet and script, about 60 KB): a canvas swarm, five beats and keyboard controls without a framework or build step


def test_arena_js_runs_in_a_dom_if_jsdom_is_available(client, tmp_path, monkeypatch):
    """Set OG_JSDOM to a jsdom install (read-only) to render the page with real API JSON."""
    import json
    import os
    import shutil
    import subprocess
    node, jsdom = shutil.which("node"), os.environ.get("OG_JSDOM")
    if not node or not jsdom or not Path(jsdom).exists():
        pytest.skip("node or OG_JSDOM not available")
    from orderguard_arena import api as arena_api
    from orderguard_arena.feeds import DEFAULT_SYMBOLS

    feed_dir = tmp_path / "feeds"
    feed_dir.mkdir()
    monkeypatch.setattr(arena_api, "FEEDS", feed_dir)
    feed = "recorded demo & tape.jsonl"
    tick = {"type": "tick", "ts": "2026-01-05T09:30:00Z", "quotes": {symbol: {"venue": 100} for symbol in DEFAULT_SYMBOLS}}
    (feed_dir / feed).write_text((json.dumps(tick) + "\n") * 12)
    feeds = client.get("/api/arena/feeds").json()
    replay = client.get("/api/arena/run?" + Q, params={"feed": feed})
    assert replay.status_code == 200, replay.text
    assert replay.json()["ran"]["feed"] == feed and replay.json()["ran"]["steps"] == 12
    data = tmp_path / "api.json"
    data.write_text(json.dumps({
        "run": client.get("/api/arena/run?" + Q).json(), "front": client.get("/api/arena/frontier?" + Q).json(),
        "feeds": feeds, "replay": replay.json(),
    }))
    out = subprocess.run([node, str(Path(__file__).with_name("arena_dom.cjs")), str(ROOT), jsdom, str(data)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
