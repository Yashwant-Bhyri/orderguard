"""API robustness: auth on every route, validation, size/time/rate limits, headers, no 500 on hostile input, no CORS."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from orderguard_app import guards
from orderguard_app.app import create_app

ORDER = {"ticker": "AAPL", "side": "buy", "quantity": 40, "limit_price": 222.9}
JSON = {"content-type": "application/json"}


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def _api_routes(app):
    """Every (method, path) under /api, from the router and from the generated OpenAPI schema (which also covers included routers,
    whatever shape the framework gives them), so a route added later cannot silently skip authentication."""
    out = set()
    for r in app.routes:
        for m in getattr(r, "methods", None) or ():
            if r.path.startswith("/api") and m not in ("HEAD", "OPTIONS"):
                out.add((m, r.path))
    for path, item in app.openapi()["paths"].items():
        for m in item:
            if path.startswith("/api") and m.upper() not in ("HEAD", "OPTIONS"):
                out.add((m.upper(), path))
    out.discard(("GET", "/api/openapi.json"))          # served only when no token is set (checked separately)
    return sorted(out)


# ---- auth on every route --------------------------------------------------------------------------------------------

def test_every_api_route_requires_the_token_and_401_wins_over_validation(monkeypatch):
    monkeypatch.setenv("ORDERGUARD_APP_TOKEN", "route-test-token")
    app = create_app()
    routes = _api_routes(app)
    assert len(routes) >= 10 and ("GET", "/api/health") in routes and any(p.startswith("/api/arena") for _, p in routes)
    c = TestClient(app, raise_server_exceptions=False)
    for method, path in routes:
        r = c.request(method, path, content=b"{not json" if method == "POST" else None, headers=JSON)
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} without a token"
        assert r.headers["www-authenticate"] == "Bearer" and r.json()["error"]
        wrong = c.request(method, path, headers={"Authorization": " ".join(["Bearer", "nope"])})
        assert wrong.status_code == 401, f"{method} {path} accepted a wrong token"


def test_token_never_echoed_and_openapi_hidden_with_token(monkeypatch):
    monkeypatch.setenv("ORDERGUARD_APP_TOKEN", "route-test-token")
    c = TestClient(create_app(), raise_server_exceptions=False)
    r = c.get("/api/openapi.json", headers={"Authorization": " ".join(["Bearer", "route-test-token"])})
    assert r.status_code == 404
    r = c.get("/api/health", headers={"Authorization": " ".join(["Bearer", "route-test-token"])})
    assert "route-test-token" not in r.text and "route-test-token" not in str(r.headers)


# ---- validation: 422 with field-level messages, never a 500 ---------------------------------------------------------------

BAD_BODIES = [
    ("/api/screen", {"text": "x", "kind": "bogus"}, "body.kind"),
    ("/api/screen", {"text": "x", "extra": 1}, "body.extra"),
    ("/api/check-order", {"order": ORDER, "prices": {"AAPL": -5}}, "body.prices.AAPL"),
    ("/api/check-order", {"order": ORDER, "prices": {"AAPL": 0}}, "body.prices.AAPL"),
    ("/api/check-order", {"order": ORDER, "as_of": "2024-13-45"}, "body.as_of"),
    ("/api/check-order", {"order": ORDER, "as_of": "tomorrow"}, "body.as_of"),
    ("/api/check-order", {"order": ORDER, "daily_total_usd": -1}, "body.daily_total_usd"),
    ("/api/check-order", {"order": ORDER, "daily_total_usd": 1e30}, "body.daily_total_usd"),
    ("/api/check-order", {"order": {"quantity": [[[[[[[[[[1]]]]]]]]]]}}, "body.order"),
    ("/api/check-order", {"order": {"note": "x" * 3000}}, "body.order"),
    ("/api/check-order", {}, "body.order"),
    ("/api/trigger-graph", {"lies": [5000]}, "body.lies.0"),
    ("/api/trigger-graph", {"preset": "bogus"}, "body.preset"),
    ("/api/trigger-graph", {"events": [1]}, "body.events.0"),
    ("/api/run-scenario", {"scenario": ""}, "body.scenario"),
    ("/api/run-scenario", {"scenario": "demo-1", "arm": "bogus"}, "body.arm"),
]


@pytest.mark.parametrize("path,body,where", BAD_BODIES)
def test_invalid_bodies_are_422_with_the_field_named(client, path, body, where):
    r = client.post(path, json=body)
    assert r.status_code == 422, r.text
    d = r.json()
    assert d["error"] and any(x["where"].startswith(where) and x["problem"] for x in d["details"]), d
    assert "Value error," not in r.text and "Traceback" not in r.text


@pytest.mark.parametrize("path,raw", [
    ("/api/check-order", b'{"order":{"ticker":"AAPL","side":"buy","quantity":1e400,"limit_price":1}}'),
    ("/api/check-order", b'{"order":{"ticker":"AAPL","side":"buy","quantity":1,"limit_price":NaN}}'),
    ("/api/check-order", b'{"order":{"ticker":"AAPL"},"prices":{"AAPL":NaN}}'),
    ("/api/check-order", b'{"order":{"ticker":"AAPL"},"daily_total_usd":Infinity}'),
    ("/api/trigger-graph", b'{"lies":[NaN]}'),
    ("/api/trigger-graph", b'{"rules":[{"id":"R","kind":"pct_change","inputs":["A"],"threshold":NaN,"notional":1,"side":"sell"}]}'),
    ("/api/screen", b'{"text":"\\ud800"}'),
    ("/api/screen", b"\xff\xfe"),
    ("/api/screen", b"[]"),
    ("/api/screen", b""),
])
def test_non_finite_and_malformed_json_never_500(client, path, raw):
    r = client.post(path, content=raw, headers=JSON)
    assert r.status_code in (200, 422), (r.status_code, r.text[:200])
    if r.status_code == 422:
        assert r.json()["error"]


def test_domain_errors_name_the_field(client):
    r = client.post("/api/check-order", json={"order": ORDER, "mandate": {"mandate": {"x": 1}}})
    assert r.status_code == 422 and r.json()["details"][0]["where"] == "body.mandate.mandate"
    r = client.post("/api/trigger-graph", json={"rules": [{}]})
    assert r.status_code == 422 and r.json()["details"][0]["where"] == "body.rules"
    r = client.post("/api/run-scenario", json={"scenario": "nope"})
    assert r.status_code == 404 and r.json()["details"][0]["where"] == "body.scenario"


def test_unknown_paths_and_methods_use_the_same_error_shape(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and set(r.json()) == {"error"}
    r = client.delete("/api/health")
    assert r.status_code == 405 and set(r.json()) == {"error"}
    assert client.get("/static/nope.js").json() == {"error": "Not Found"}
    assert client.get("/static/../services.py").status_code == 404


# ---- size limits ----------------------------------------------------------------------------------------------------------

def test_declared_and_chunked_bodies_over_the_cap_are_413(client):
    r = client.post("/api/screen", content=b"x" * (guards.MAX_BODY + 1), headers=JSON)
    assert r.status_code == 413 and "limit" in r.json()["error"]

    def chunks():                                                   # no Content-Length: sent chunked
        for _ in range(12):
            yield b"x" * 100_000
    r = client.post("/api/screen", content=chunks(), headers=JSON)
    assert r.status_code == 413


def test_chunked_body_under_the_cap_still_works(client):
    body = json.dumps({"text": "Apple shares were steady."}).encode()

    def chunks():
        yield body[:10]
        yield body[10:]
    r = client.post("/api/screen", content=chunks(), headers=JSON)
    assert r.status_code == 200 and r.json()["l1"]["changed"] is False


def test_malformed_content_length_is_400():
    async def go():
        sent = []

        async def app(scope, receive, send):
            raise AssertionError("must not reach the app")

        async def send(m):
            sent.append(m)
        await guards.Guards(app)({"type": "http", "method": "POST", "path": "/api/screen", "headers": [(b"content-length", b"abc")]}, None, send)
        return sent
    sent = asyncio.run(go())
    assert sent[0]["status"] == 400


# ---- rate limit, concurrency cap, deadline ------------------------------------------------------------------------------------

def test_rate_limit_returns_429_with_retry_after_and_can_be_disabled(client, monkeypatch):
    path = "/api/arena/feeds"                                       # cheap route inside the 30/minute arena bucket
    codes = [client.get(path).status_code for _ in range(32)]
    assert codes[:30].count(429) == 0 and codes[30] == 429
    r = client.get(path)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "hint" in r.json()
    assert client.get("/api/health").status_code == 200             # other routes keep their own budget
    monkeypatch.setenv("ORDERGUARD_RATE_LIMIT", "0")
    assert client.get(path).status_code == 200


def _slow_stack(monkeypatch, sleep_s, deadline, concurrent=1):
    from fastapi import FastAPI
    monkeypatch.setattr(guards, "LIMITS", (guards.Limit("/api/slow", 100, deadline, concurrent),))
    app = FastAPI()

    @app.get("/api/slow")
    def slow():
        time.sleep(sleep_s)
        return {"done": True}
    app.add_middleware(guards.Guards)
    return TestClient(app, raise_server_exceptions=False)


def test_a_heavy_route_past_its_deadline_gets_504_promptly(monkeypatch):
    c = _slow_stack(monkeypatch, sleep_s=1.0, deadline=0.2)
    t0 = time.monotonic()
    r = c.get("/api/slow")
    assert r.status_code == 504 and "abandoned" in r.json()["error"] and time.monotonic() - t0 < 0.9
    assert r.headers["x-content-type-options"] == "nosniff"


def test_a_fast_request_inside_the_deadline_passes_untouched(monkeypatch):
    c = _slow_stack(monkeypatch, sleep_s=0.0, deadline=2.0)
    r = c.get("/api/slow")
    assert r.status_code == 200 and r.json() == {"done": True} and r.headers["cache-control"] == "no-store"


def test_concurrency_cap_returns_503_then_recovers(monkeypatch):
    import threading
    c = _slow_stack(monkeypatch, sleep_s=0.6, deadline=5.0, concurrent=1)
    first: list = []
    t = threading.Thread(target=lambda: first.append(c.get("/api/slow")))
    t.start()
    time.sleep(0.2)
    r = c.get("/api/slow")
    assert r.status_code == 503 and r.headers["retry-after"] == "3"
    t.join()
    assert first[0].status_code == 200
    assert c.get("/api/slow").status_code == 200


# ---- headers and cross-origin stance -----------------------------------------------------------------------------------------

SECURITY = ("x-content-type-options", "referrer-policy", "x-frame-options", "content-security-policy", "permissions-policy", "cross-origin-opener-policy")


@pytest.mark.parametrize("method,path,status", [("GET", "/", 200), ("GET", "/static/app.js", 200), ("GET", "/api/health", 200), ("GET", "/api/nope", 404),
                                                ("POST", "/api/screen", 422), ("GET", "/static/missing.js", 404)])
def test_security_headers_on_every_kind_of_response(client, method, path, status):
    r = client.request(method, path, json={} if method == "POST" else None)
    assert r.status_code == status
    for h in SECURITY:
        assert h in r.headers, f"{h} missing on {method} {path}"
    csp = r.headers["content-security-policy"]
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "frame-ancestors 'none'" in csp and "default-src 'self'" in csp
    assert r.headers["x-frame-options"] == "DENY"


def test_security_headers_on_auth_failure_and_413(monkeypatch):
    monkeypatch.setenv("ORDERGUARD_APP_TOKEN", "t0k")
    c = TestClient(create_app(), raise_server_exceptions=False)
    for r in (c.get("/api/health"), c.post("/api/screen", content=b"x" * (guards.MAX_BODY + 1), headers=JSON)):
        assert r.status_code in (401, 413) and all(h in r.headers for h in SECURITY)


def test_there_is_no_cors(client):
    r = client.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert not any(k.lower().startswith("access-control-") for k in r.headers)
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
    assert r.headers["cross-origin-resource-policy"] == "same-origin"


def test_api_responses_are_never_cached_and_pages_revalidate(client):
    assert client.get("/api/health").headers["cache-control"] == "no-store"
    assert client.get("/").headers["cache-control"] == "no-cache"


# ---- speed ------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/api/health", "/api/overview", "/api/scenarios", "/api/mandate"])
def test_light_endpoints_are_fast(client, path):
    client.get(path)
    t0 = time.perf_counter()
    assert client.get(path).status_code == 200
    assert time.perf_counter() - t0 < 1.0, path


def test_limit_table_is_sane():
    for lim in (*guards.LIMITS, guards.DEFAULT):
        assert lim.per_minute > 0 and 0 < lim.timeout_s <= 300 and lim.concurrent >= 1
    assert guards.limit_for("/api/arena/run").prefix == "/api/arena/"
    assert guards.limit_for("/api/check-order").prefix == "/api/check-order"
    assert guards.limit_for("/api/unlisted").prefix == "/api/"
    assert guards.limit_for("/static/app.js") is None
