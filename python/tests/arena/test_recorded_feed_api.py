import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orderguard_arena import api


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ORDERGUARD_RECEIVER_URL", raising=False)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        yield client


def test_bundled_recording_drives_replay_and_envelope_frontier(client):
    feed = "binance-public-20261111T000117Z.jsonl"
    listed = {item["name"]: item for item in client.get("/api/arena/feeds").json()["feeds"]}
    assert listed[feed]["ticks"] == 144
    assert "data-api.binance.vision" in listed[feed]["source"]

    params = {"agents": 15, "steps": 50, "seed": 7}
    replay = client.get("/api/arena/run", params=params | {"feed": feed})
    frontier = client.get("/api/arena/frontier", params=params | {"feed": feed, "samples": 8})
    synthetic = client.get("/api/arena/frontier", params=params | {"feed": "synthetic", "samples": 8})
    assert replay.status_code == frontier.status_code == synthetic.status_code == 200
    replay, frontier, synthetic = replay.json(), frontier.json(), synthetic.json()
    assert replay["ran"] == {"feed": feed, "agents": 15, "steps": listed[feed]["ticks"]}
    assert frontier["ran"] == replay["ran"] | {"steps_per_day": 60}
    assert frontier["profile"]["ndays"] == replay["summary"]["config"]["days"] == 3
    assert set(frontier["profile"]["symbols"]) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert set(frontier["recommendation"]["proposed_mandate"]["symbols"]) <= set(frontier["profile"]["symbols"])
    assert frontier["baseline"]["utility_per_day_usd"] == round(replay["summary"]["legit"]["allowed_usd"] / 3, 2)
    assert synthetic["ran"] == {"feed": "synthetic", "agents": 15, "steps": 50, "steps_per_day": 12}
    assert set(synthetic["profile"]["symbols"]).isdisjoint(frontier["profile"]["symbols"])


def test_arena_browser_runs_never_attach_the_configured_receiver(client, monkeypatch):
    from orderguard_arena.authority import Authority

    def unexpected(*args, **kwargs):
        raise AssertionError("The browser's simulated runs must never attach a receiver.")

    monkeypatch.setenv("ORDERGUARD_RECEIVER_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(Authority, "from_env", unexpected)
    result = client.get("/api/arena/run", params={"steps": 50, "agents": 15})
    assert result.status_code == 200 and result.json()["summary"]["l8"] is None
    result = client.get("/api/arena/frontier", params={"steps": 50, "agents": 15, "samples": 8})
    assert result.status_code == 200


@pytest.mark.parametrize("replacement", ["{broken\n", '{"type":"meta"}\n', '{"type":"tick","ts":"2026-01-01","quotes":{"BTCUSDT":{}}}\n'])
def test_unusable_recordings_are_not_listed_or_silently_replaced(client, monkeypatch, tmp_path, replacement):
    monkeypatch.setattr(api, "FEEDS", tmp_path)
    p = tmp_path / "test.jsonl"
    header = {"type": "meta", "steps_per_day": 2}
    tick = {"type": "tick", "ts": "2026-01-01T00:00:00Z", "quotes": {"BTCUSDT": {"bid": 50}}}
    p.write_text(f"{json.dumps(header)}\n\n{json.dumps(tick)}\n", encoding="utf-8")
    assert client.get("/api/arena/feeds").json()["feeds"] == [{"name": p.name, "ticks": 1, "source": "recorded"}]
    p.write_text(replacement, encoding="utf-8")
    assert client.get("/api/arena/feeds").json()["feeds"] == []
    for endpoint in ("run", "frontier"):
        response = client.get(f"/api/arena/{endpoint}", params={"feed": p.name})
        assert response.status_code == 422 and "invalid recorded feed" in response.json()["detail"]
        for name in ("missing.jsonl", f"subdir/../{p.name}"):
            response = client.get(f"/api/arena/{endpoint}", params={"feed": name})
            assert response.status_code == 404


@pytest.mark.parametrize("endpoint", ["run", "frontier", "envelopes"])
@pytest.mark.parametrize("field,value,limit_text", [
    ("agents", "-1", "agents must be from 1 to 5,000"), ("agents", "0", "agents must be from 1 to 5,000"), ("agents", "999999", "agents must be from 1 to 5,000"),
    ("agents", "abc", "agents must be a whole number"), ("agents", "1.5", "agents must be a whole number"), ("agents", "", "agents must be a whole number"),
    ("steps", "-1", "steps must be from 1 to 2,000"), ("steps", "0", "steps must be from 1 to 2,000"), ("steps", "2001", "steps must be from 1 to 2,000"),
    ("steps", "1e3", "steps must be a whole number"), ("seed", "-5", "seed must be from 0"), ("seed", "x", "seed must be a whole number"),
])
def test_nonsense_sizes_are_422_naming_the_field_not_clamped(client, endpoint, field, value, limit_text):
    if endpoint == "envelopes" and field != "agents":
        pytest.skip("envelopes takes only agents")
    r = client.get(f"/api/arena/{endpoint}", params={field: value})
    assert r.status_code == 422 and limit_text in r.json()["detail"], r.text


def test_only_the_documented_work_bound_still_adjusts_the_request(client):
    r = client.get("/api/arena/run", params={"agents": 5000, "steps": 2000})
    assert r.status_code == 200
    body = r.json()
    assert body["requested"] == {"agents": 5000, "steps": 2000} and body["ran"]["steps"] == 500          # 2.5M agent-steps / 5,000 agents
    small = client.get("/api/arena/run", params={"agents": 1, "steps": 1})
    assert small.status_code == 200 and small.json()["ran"]["steps"] == 1
