"""The Swarm Theater: the timeline builder is deterministic and offline, every number the page shows traces to a committed file, the endpoint is
guarded like the others, and the page obeys the dashboard's static contract (CSP, no inline script or style, the asset budget)."""
import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

import pytest

from orderguard_app import theater as T

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "python" / "orderguard_app" / "static"


def _read(rel: str) -> str:
    return (REPO / rel).read_text()


@pytest.fixture(scope="module")
def built() -> dict:
    return T.build()


@pytest.fixture(scope="module")
def doc(built) -> dict:
    return json.loads(T.serialise(built))


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from orderguard_app.app import create_app
    return TestClient(create_app())


# ---- the builder ---------------------------------------------------------------------------------------------------------------

def test_build_is_deterministic_and_the_committed_file_is_current(built):
    again = T.serialise(T.build())
    assert again == T.serialise(built), "two builds of the same files must be byte-identical (no clock, path or random)"
    assert T.OUT.exists() and T.OUT.read_text() == again, "results/theater/timeline.json is stale: run python -m orderguard_app.theater build"
    assert T.main(["check"]) == 0


def test_the_timeline_is_compact_and_has_no_path_or_secret(doc):
    text = T.serialise(doc)
    assert len(text.encode()) < 400_000, "a few hundred KB, not the 5 MB stream"
    assert len(gzip.compress(text.encode())) < 120_000
    assert "/Users/" not in text and "@" not in text and "api_key" not in text.lower()
    assert doc["inputs"] == T.input_hashes()


def test_every_reconciliation_check_passed(doc):
    assert len(doc["checks"]) >= 7 and all(c["ok"] for c in doc["checks"]), [c for c in doc["checks"] if not c["ok"]]


def _stream():
    lines = _read("results/arena/arena-s7-k1000-t2000.jsonl").splitlines()
    return lines, json.loads(lines[0]), [json.loads(x) for x in lines[1:]]


def test_every_fact_traces_to_its_source_file(doc):
    docs = {"summary": json.loads(_read("results/arena/arena-s7-k1000-t2000.summary.json")), "risk": json.loads(_read("results/risk/arena-replay-arena-s7-k1000-t2000.json")),
            "latency": json.loads(_read("results/risk/latency.json")), "triage": json.loads(_read("results/review/triage.json")),
            "stream": _stream()[1]}
    l8 = _read("results/arena/l8-agreement-s23-k1000.txt")
    docs["l8"] = json.loads(l8[: l8.rindex("}") + 1])
    assert "L8 CHECK PASS" in l8
    lines, meta, events = _stream()
    pointed = 0
    for fid, f in doc["facts"].items():
        assert f["source"] in T.SOURCES and f["fmt"] in T.TOKENS_FORMAT and f["text"], fid
        if f["pointer"] is None:
            continue
        ptrs = [f["pointer"]] if isinstance(f["pointer"], str) else f["pointer"]
        want = sum(T._pointer(docs[f["source"]], p) for p in ptrs) * f["scale"]
        assert f["value"] == pytest.approx(want, rel=1e-9), fid
        pointed += 1
    assert pointed >= 30
    # the derived facts, recomputed here from the raw files
    f = doc["facts"]
    assert f["stopped_total_usd"]["value"] == pytest.approx(docs["summary"]["bad"]["blocked_usd"] + docs["risk"]["bad_held_usd"] + docs["risk"]["bad_refused_usd"], abs=0.01)
    assert f["stopped_total_usd"]["value"] + f["dup_usd"]["value"] == pytest.approx(f["attack_usd"]["value"], abs=0.02), "stopped plus absorbed duplicates is every bad dollar"
    assert f["legit_daily_refusals"]["value"] == sum(1 for e in events if e["label"] == "legit" and e["code"] == "daily")
    assert f["revoke_text"]["value"] in _read("docs/receiver/results.md")
    assert meta["config"]["revoke"] is None, "the page says this run set no revocation"
    chain = hashlib.sha256(lines[0].encode()).hexdigest()
    for line in lines[1:]:
        chain = hashlib.sha256((chain + line).encode()).hexdigest()
    assert f["chain_head"]["value"] == chain == doc["chain"]["head"] and f["chain_rows"]["value"] == len(events)
    assert f["checks_ok"]["value"] == f"{len(doc['checks'])} of {len(doc['checks'])}"


def test_the_event_strip_and_series_reproduce_the_summary(doc):
    summary = json.loads(_read("results/arena/arena-s7-k1000-t2000.summary.json"))
    raw = base64.b64decode(doc["events"])
    n = len(raw) // 2
    assert n == summary["proposals"] == sum(doc["per_step"])
    words = [raw[2 * i] | (raw[2 * i + 1] << 8) for i in range(n)]
    states = [w >> 10 for w in words]
    names = doc["states"]
    count = lambda s: states.count(names.index(s))                                         # noqa: E731
    assert count("duplicate") == summary["replays_absorbed"]
    assert count("stopped_by_risk") + count("leak") + count("bad_hold") + count("bad_refuse") + count("duplicate") == summary["bad"]["proposals"]
    assert count("leak") == 0 and count("stopped_by_risk") == summary["bad"]["allowed"]
    assert count("refuse") == summary["legit"]["refused"] and count("hold") == summary["legit"]["held"]
    s = doc["series"]
    assert sum(s["legit"]) == summary["legit"]["proposals"] and sum(s["bad_n"]) == summary["bad"]["proposals"]
    total = (sum(s["bad_gate_usd"]) + sum(s["bad_risk_usd"]) + sum(s["bad_leak_usd"])) / 100
    assert total + summary["bad"]["duplicates_absorbed_usd"] == pytest.approx(summary["bad"]["attack_notional_usd"], abs=0.05)
    assert sum(s["bad_gate_usd"]) / 100 == pytest.approx(summary["bad"]["blocked_usd"], abs=0.05)
    assert max(w & 1023 for w in words) < doc["run"]["agents"]


def test_the_beats_use_only_known_facts_and_play_for_about_ninety_seconds(doc):
    beats = doc["beats"]
    assert [b["id"] for b in beats] == ["calm", "attack", "guard", "human", "proof"]
    for b in beats:
        for tok in re.findall(r"\{(\w+)\}", b["caption"]):
            assert tok in doc["facts"], (b["id"], tok)
    total = sum(sum(g[2] for g in b["segments"]) or b["dwell"] for b in beats)
    assert 80 <= total <= 100, total
    steps = doc["run"]["steps"]
    for b in beats:
        for a, z, secs in b["segments"]:
            assert 0 <= a < z <= steps and secs > 0
    first_attack = min(f["first_step"] for f in doc["families"] if f["first_step"] is not None)
    assert beats[0]["segments"] == [[0, first_attack, beats[0]["segments"][0][2]]], "the calm beat ends exactly where the first attack begins"
    assert beats[1]["segments"][0][0] == beats[2]["segments"][0][0] == first_attack, "the guard beat rewinds to the first attack"


def test_the_js_only_reads_facts_that_exist(doc):
    js = (STATIC / "theater.js").read_text()
    for fid in set(re.findall(r'fact\("(\w+)"\)', js)) | set(re.findall(r'D\.facts\.(\w+)', js)):
        assert fid in doc["facts"], fid


def test_reasons_are_plain_english_with_the_event_numbers(doc):
    lines, meta, events = _stream()
    envs = {e["name"]: e for e in meta["envelopes"]}
    over = next(e for e in events if e["label"] == "compromised_oversize" and e["code"] == "per_order")
    text = T._rule(over, envs[over["env"]], 0.0)
    assert f"${over['risk']:,.0f}" in text and f"${envs[over['env']]['per_order']:,.0f}" in text and "per-order cap" in text
    homo = next(e for e in events if e["label"] == "homoglyph")
    assert "look-alike" in T._rule(homo, envs[homo["env"]], 0.0)
    news = next(e for e in events if e["code"] == "l7")
    assert "two independent sources" in T._rule(news, None, 0.0) and news["trigger"]["news_id"] in T._rule(news, None, 0.0)
    assert all(t and (t[0].isupper() or t[0].isdigit() or t[0] == "$") and t.endswith(".") for t in doc["feed_texts"])
    assert all(0 <= row[4] < len(doc["feed_texts"]) for row in doc["feed"])


def test_each_focus_attack_is_followed_end_to_end_and_its_chain_verifies(doc):
    assert len(doc["focus"]) == 3
    for f in doc["focus"]:
        assert f["order"] and f["rule"]["text"] and f["decision"] in ("allow", "hold", "refuse") and f["ledger"]["effect"]
        ch = f["ledger"]["chain"]
        prev = ch["prev"]
        for row, want in zip(ch["rows"], ch["hashes"]):
            prev = hashlib.sha256((prev + row).encode()).hexdigest()
            assert prev == want
        assert json.loads(ch["rows"][ch["at"]])["i"] == f["row"] - 1 or json.loads(ch["rows"][ch["at"]])["agent"] == f["agent"]
    col = doc["focus"][2]
    assert col["decision"] == "allow" and col["then"] in ("hold", "refuse") and col["rule"]["layer"] == "RISK" and len(col["gate_checks"]) == 5
    assert any(u["name"] == "split_under_threshold" for u in col["rule"]["units"])
    assert doc["focus"][1]["rule"]["code"] == "per_order" and doc["focus"][1]["decision"] == "refuse"


def test_the_queue_is_ordered_as_in_review_md_and_advice_is_labelled(doc):
    q = doc["queue"]
    keys = [it["rank_key_usd"] for it in q["items"]]
    assert keys == sorted(keys, reverse=True) and len(q["items"]) == 8 and q["orders"] >= 8
    assert all(it["advice"]["available"] for it in q["items"]), "the recordings cover every order of the study"
    assert "docs/REVIEW.md" in q["ordering"]
    js = (STATIC / "theater.js").read_text()
    assert "Advice only." in js and "cannot approve or release" in js and "Reveal what they really were" in js


def test_bench_slot_reads_the_summary_only_when_it_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "ROOT", tmp_path)
    assert T.bench_headline() == {"present": False, "path": "results/bench/summary.json", "rows": [], "sha256": None}
    (tmp_path / "results" / "bench").mkdir(parents=True)
    (tmp_path / "results" / "bench" / "summary.json").write_text(json.dumps({"headline": {"decisions_per_s": 1234, "note": "x", "nested": {"a": 1}}}))
    got = T.bench_headline()
    assert got["present"] and got["rows"] == [["decisions_per_s", 1234], ["note", "x"]]
    (tmp_path / "results" / "bench" / "summary.json").write_text("{nope")
    assert T.bench_headline()["present"] is False


# ---- the endpoints ---------------------------------------------------------------------------------------------------------------

def test_timeline_endpoint_serves_the_committed_file_gzipped_and_plain(client):
    plain = client.get("/api/theater/timeline", headers={"Accept-Encoding": "identity"})
    assert plain.status_code == 200 and plain.headers["content-type"].startswith("application/json") and plain.headers["cache-control"] == "no-store"
    assert plain.text == T.OUT.read_text()
    gz = client.get("/api/theater/timeline", headers={"Accept-Encoding": "gzip"})
    assert gz.status_code == 200 and gz.headers.get("content-encoding") == "gzip"
    assert gz.json() == plain.json()
    assert client.get("/api/theater/bench").json()["path"] == "results/bench/summary.json"


def test_source_endpoint_is_an_allow_list_of_exact_ids(client):
    listing = client.get("/api/theater/source").json()
    assert [s["id"] for s in listing["sources"]] == list(T.SOURCES) and listing["bench"] == "results/bench/summary.json"
    r = client.get("/api/theater/source", params={"id": "summary"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain") and r.headers["x-content-type-options"] == "nosniff"
    assert r.json()["proposals"] == 20503
    for bad in ("nope", "..%2F..%2Fetc%2Fpasswd", "%2e%2e", "stream%00", "model/../../x", "x" * 40):
        assert client.get("/api/theater/source?id=" + bad).status_code in (404, 422), bad
    assert client.get("/api/theater/source?id=nope").status_code == 404
    assert client.get("/api/theater/source?id=bench").status_code in (200, 404)
    assert set(T.SOURCES) >= {"stream", "summary", "risk", "triage", "l8", "receiver"}
    for sid, (rel, _) in T.SOURCES.items():
        assert not rel.startswith("/") and ".." not in rel and (REPO / rel).is_file(), sid


def test_theater_routes_need_the_token_and_the_page_stays_public(monkeypatch):
    from fastapi.testclient import TestClient
    from orderguard_app.app import create_app
    monkeypatch.setenv("ORDERGUARD_APP_TOKEN", "theater-token")
    c = TestClient(create_app())
    for path in ("/api/theater/timeline", "/api/theater/bench", "/api/theater/source?id=summary", "/api/theater/source?id=stream"):
        r = c.get(path)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer", path
        assert c.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/theater/timeline", headers={"Authorization": "Bearer theater-token"}).status_code == 200
    assert c.get("/theater").status_code == 200, "the page itself is public so it can explain the token"


def test_missing_results_are_a_sentence_not_a_crash(client, monkeypatch, tmp_path):
    monkeypatch.setattr(T, "ROOT", tmp_path)
    r = client.get("/api/theater/timeline")
    assert r.status_code == 404 and "recorded results" in r.json()["error"]


def test_the_page_is_served_with_versioned_assets_and_the_strict_csp(client):
    r = client.get("/theater")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp and "unsafe-inline" not in csp and "default-src 'self'" in csp
    for name in ("theater.css", "theater.js", "ui.js", "app.css", "theme.js"):
        want = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]
        assert f"/static/{name}?v={want}" in r.text, name
    assert r.text.index("ui.js") < r.text.index("theater.js")
    home = client.get("/").text
    assert 'href="/theater"' in home and "Watch a swarm get caught" in home


# ---- the page's static contract --------------------------------------------------------------------------------------------------

def test_theater_files_obey_the_dashboard_static_contract():
    js, html, css = (STATIC / "theater.js").read_text(), (STATIC / "theater.html").read_text(), (STATIC / "theater.css").read_text()
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", ".cssText", 'setAttribute("style"', "XMLHttpRequest", "WebSocket", "new Function"):
        assert bad not in js, bad
    assert not re.search(r"https?://", js + css) and not re.search(r"""style\s*[:=]\s*["']""", js)
    assert 'style="' not in html and "<style" not in html and not re.search(r"<script(?![^>]*src=)", html) and not re.search(r"\son\w+=", html)
    assert "@import" not in css and "url(" not in css
    assert all("try" in line for line in js.splitlines() if "localStorage" in line), "storage may be blocked: every access is guarded"
    assert js.count("fetch(") <= 4                                    # the timeline, the bench headline, a source file behind a token, and nothing else
    for tag in re.findall(r'<(?:script|link)[^>]+(?:src|href)="(/static/[^"?]+)', html):
        assert (STATIC.parent / tag.lstrip("/")).exists(), tag
    total = sum(p.stat().st_size for p in STATIC.iterdir() if p.is_file())
    assert total < 260_000, total


def test_theater_is_accessible_and_honours_reduced_motion():
    js, html, css = (STATIC / "theater.js").read_text(), (STATIC / "theater.html").read_text(), (STATIC / "theater.css").read_text()
    assert 'id="th-caption" aria-live="polite"' in html and 'role="status"' in html and 'class="skip"' in html and "<main" in html and html.count("<h1") == 1
    for label in ("Previous beat", "Next beat", 'aria-label="Scrub the story"', "Back one step in the run", "Playback speed"):
        assert label in html, label
    assert "OG.reduceMotion()" in js and "if (reduce) return;" in js and "$(\"b-play\").disabled = true" in js and "th-motion" in js
    assert 'role: "meter"' in js and "aria-valuenow" in js and '"aria-current", "step"' in js
    assert "prefers-reduced-motion" in css and "@media (max-width: 700px)" in css
    for key in ('" "', "ArrowRight", "ArrowLeft", '"."', '","'):
        assert key in js, key
    for token in ("--allow", "--hold", "--refuse", "--quarantine", "--text-3", "--accent"):
        assert token in (STATIC / "app.css").read_text() and token in js + css
