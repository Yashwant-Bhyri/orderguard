import json

import httpx
import pytest

from orderguard_guard import llm as L
from orderguard_guard.receiver_client import LocalLedger, Receiver, ReceiverError, bridge_available

BODY_OK = {"choices": [{"message": {"role": "assistant", "content": "hi"}}], "usage": {"cost": 0.001, "prompt_tokens": 5, "completion_tokens": 2}}


def make(tmp_path, handler, mode="record", budget=0.05):
    spend = L.Spend(budget_usd=budget)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return L.LLM("deepseek/deepseek-v4.1-flash", mode=mode, replay_dir=tmp_path / "replay", spend_file=tmp_path / "spend.jsonl", client=client, retries=2, spend=spend), spend


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("OG_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setattr(L.LLM, "_backoff", lambda self, a: None)


def handler_factory(calls, credits=2.0):
    def h(req):
        calls.append(str(req.url))
        if req.url.path.endswith("/credits"):
            return httpx.Response(200, json={"data": {"total_credits": credits, "total_usage": 0.0}})
        return httpx.Response(200, json=BODY_OK)
    return h


MSG = [{"role": "user", "content": "hello"}]


def test_replay_miss_is_an_error(tmp_path):
    llm, _ = make(tmp_path, handler_factory([]), mode="replay")
    with pytest.raises(L.ReplayMiss):
        llm.chat(MSG)


def test_record_then_replay_is_content_addressed(tmp_path):
    calls = []
    llm, _ = make(tmp_path, handler_factory(calls))
    r1 = llm.chat(MSG)
    assert r1["_meta"]["cached"] is False
    files = list((tmp_path / "replay").glob("*.json"))
    assert len(files) == 1 and files[0].stem == r1["_meta"]["hash"]
    r2 = llm.chat(MSG)
    assert r2["_meta"]["cached"] is True and len([c for c in calls if "chat" in c]) == 1
    llm.mode = "replay"
    assert llm.chat(MSG)["choices"][0]["message"]["content"] == "hi"
    with pytest.raises(L.ReplayMiss):
        llm.chat([{"role": "user", "content": "different"}])
    assert "test-key-not-real" not in files[0].read_text()


def test_writable_recording_directory_keeps_bundled_replay_available(tmp_path, monkeypatch):
    bundled, _ = make(tmp_path, handler_factory([]))
    bundled.chat(MSG)
    monkeypatch.setattr(L, "REPLAY_DIR", bundled.replay_dir)
    records = tmp_path / "records"
    monkeypatch.setenv("OG_RECORD_DIR", str(records))
    calls = []
    with httpx.Client(transport=httpx.MockTransport(handler_factory(calls))) as client:
        llm = L.LLM(bundled.model, mode="record", spend_file=tmp_path / "other-spend.jsonl", client=client, spend=L.Spend())
        assert llm.chat(MSG)["_meta"]["cached"] is True and not calls
        new = [{"role": "user", "content": "an uncached request"}]
        response = llm.chat(new)
        assert list(records.iterdir()) == [records / f"{response['_meta']['hash']}.json"]
        assert len(list(bundled.replay_dir.iterdir())) == 1
        replay = L.LLM(bundled.model, mode="replay")
        assert replay.chat(MSG)["_meta"]["cached"] and replay.chat(new)["_meta"]["cached"]
        isolated, _ = make(tmp_path / "isolated", handler_factory([]), mode="replay")
        with pytest.raises(L.ReplayMiss):
            isolated.chat(new)


def test_budget_guard_and_spend_log(tmp_path):
    calls = []
    llm, spend = make(tmp_path, handler_factory(calls), budget=0.0023)
    llm.chat(MSG, max_tokens=800)
    llm.chat([{"role": "user", "content": "b"}], max_tokens=800)
    with pytest.raises(L.BudgetExceeded):
        llm.chat([{"role": "user", "content": "c"}], max_tokens=800)
    lines = (tmp_path / "spend.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["cost_usd"] == 0.001
    assert spend.spent_usd == 0.002 and len([c for c in calls if "chat" in c]) == 2


def test_credit_floor_checked_once_before_first_live_call(tmp_path):
    calls = []
    llm, _ = make(tmp_path, handler_factory(calls, credits=0.20))
    with pytest.raises(L.CreditFloor):
        llm.chat(MSG)
    assert not any("chat" in c for c in calls)
    calls2 = []
    llm2, _ = make(tmp_path / "b", handler_factory(calls2))
    llm2.chat(MSG)
    llm2.chat([{"role": "user", "content": "x"}])
    assert len([c for c in calls2 if c.endswith("/credits")]) == 1


def test_retries_on_429_and_incomplete_read(tmp_path):
    n = {"i": 0}

    def h(req):
        if req.url.path.endswith("/credits"):
            return httpx.Response(200, json={"data": {"total_credits": 2, "total_usage": 0}})
        n["i"] += 1
        if n["i"] == 1:
            return httpx.Response(429, json={})
        if n["i"] == 2:
            raise httpx.RemoteProtocolError("peer closed connection: IncompleteRead")
        return httpx.Response(200, json=BODY_OK)
    llm, _ = make(tmp_path, h)
    assert llm.chat(MSG)["choices"][0]["message"]["content"] == "hi" and n["i"] == 3


def test_key_from_env_file_by_name(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    f = tmp_path / "x.env"
    f.write_text("OTHER=1\nOPENROUTER_API_KEY='abc123'\n")
    monkeypatch.setenv("OG_ENV_FILE", str(f))
    assert L.api_key() == "abc123"


def test_parse_json_tolerates_fences():
    assert L.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        L.parse_json("no object")


def test_local_ledger_idempotency_and_revocation():
    led = LocalLedger()
    a = led.propose("AAPL", "buy", 10, 222.7, "c1")
    b = led.propose("AAPL", "buy", 10, 222.7, "c1")
    assert a["decision"] == "filled" and b["ledgerEffect"] is False and len(led.snapshot()["orders"]) == 1
    led.revoke()
    assert led.propose("AAPL", "buy", 1, 1, "c2")["decision"] == "denied"


def test_receiver_http_client_against_a_mock_bridge():
    seen = []

    def h(req):
        seen.append((req.method, req.url.path, req.content))
        if req.url.path == "/propose":
            return httpx.Response(200, json={"decision": "filled", "reason": "ok", "orderId": "o1", "ledgerEffect": True})
        if req.url.path == "/snapshot":
            return httpx.Response(200, json={"orders": [], "ledgerIntegrity": True})
        return httpx.Response(500)
    r = Receiver("http://127.0.0.1:1", client=httpx.Client(transport=httpx.MockTransport(h)))
    assert r.propose("AAPL", "buy", 5, 222.7, "k")["decision"] == "filled"
    assert json.loads(seen[0][2])["clientOrderId"] == "k" and r.snapshot()["ledgerIntegrity"] is True
    with pytest.raises(ReceiverError):
        r.health()


def test_bridge_available_reports_a_reason():
    ok, why = bridge_available()
    assert ok or why
