"""Verify's cache compatibility and shared LLM behavior with a fake HTTP transport."""

import hashlib
import json

import httpx
import pytest

from orderguard_guard import llm as shared_llm
from orderguard_verify.core import llm

MODEL = "deepseek/deepseek-v4.1-flash-1017"
SYSTEM, USER = "You extract claims.", "ACME had revenue of $5.0 billion."
MESSAGES = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]
ANSWER = {"claims": []}
REPLY = {"choices": [{"message": {"content": json.dumps(ANSWER)}}],
         "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
LEGACY_CALL = llm.LLMCall(MODEL, 42, 17, 0.0005, 2.5, False)


@pytest.fixture
def mock_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("OG_PROVIDER", raising=False)
    monkeypatch.delenv("OG_MODEL", raising=False)
    monkeypatch.setenv("OG_LLM", "live")
    monkeypatch.setenv("OG_MAX_TOKENS", "77")
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "verify-cache")
    monkeypatch.setattr(shared_llm, "REPLAY_DIR", tmp_path / "shared-replay")
    monkeypatch.setattr(shared_llm, "SPEND", shared_llm.Spend(budget_usd=0.05))
    monkeypatch.setattr(shared_llm, "PRICE_IN", 0.30)
    monkeypatch.setattr(shared_llm, "PRICE_OUT", 1.20)
    spend_file = tmp_path / "spend.jsonl"
    monkeypatch.setenv("OG_SPEND_FILE", str(spend_file))

    requests = []
    provider = {"balance": 1.0, "reply": REPLY, "status": 200}

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            assert str(request.url) in (shared_llm.DEEPSEEK_BALANCE_URL, shared_llm.CREDITS_URL)
            return httpx.Response(200, json={
                "balance_infos": [{"currency": "USD", "total_balance": provider["balance"]}],
                "data": {"total_credits": provider["balance"], "total_usage": 0},
            })
        assert request.method == "POST"
        return httpx.Response(provider["status"], json=provider["reply"])

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(shared_llm.LLM, "_http", lambda self: client)
        monkeypatch.setattr(shared_llm.LLM, "_headers", lambda self: {})
        yield requests, provider, spend_file


def record_legacy_answer():
    digest = hashlib.sha256(json.dumps([MODEL, SYSTEM, USER]).encode()).hexdigest()[:32]
    path = llm.CACHE_DIR / f"{digest}.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"text": json.dumps(ANSWER), "call": LEGACY_CALL.__dict__}))


def test_live_verify_delegates_to_shared_deepseek_client(mock_provider, monkeypatch):
    requests, _, spend_file = mock_provider
    record_legacy_answer()

    parsed, call = llm.ask_json(SYSTEM, USER)

    assert parsed == ANSWER
    balance, completion = requests
    assert str(balance.url) == shared_llm.DEEPSEEK_BALANCE_URL
    assert str(completion.url) == shared_llm.DEEPSEEK_URL
    assert json.loads(completion.content) == {
        "model": "deepseek-flash", "messages": MESSAGES, "max_tokens": 77, "temperature": 0,
    }
    assert call.model == MODEL
    assert (call.prompt_tokens, call.completion_tokens) == (100, 50)
    assert call.cost_usd == pytest.approx(0.00009)
    assert call.cached is False
    assert shared_llm.SPEND.calls == 1
    assert shared_llm.SPEND.spent_usd == pytest.approx(call.cost_usd)
    [logged] = spend_file.read_text().splitlines()
    spend_entry = json.loads(logged)
    assert spend_entry["model"] == MODEL
    assert spend_entry["provider"] == "deepseek"
    assert spend_entry["cost_usd"] == pytest.approx(call.cost_usd)

    monkeypatch.setenv("OG_LLM", "replay")
    _, replayed = llm.ask_json(SYSTEM, USER)
    assert replayed == llm.LLMCall(MODEL, 100, 50, call.cost_usd, 0.0, True)
    assert [request.method for request in requests] == ["GET", "POST"]


def test_live_verify_can_use_openrouter(mock_provider, monkeypatch):
    requests, provider, _ = mock_provider
    monkeypatch.setenv("OG_PROVIDER", "openrouter")
    provider["reply"] = {**REPLY, "usage": {**REPLY["usage"], "cost": 0.0001}}
    model = "nvidia/nemotron-3.5-super-vl:free"

    _, call = llm.ask_json(SYSTEM, USER, model=model, max_tokens=321)

    balance, completion = requests
    assert str(balance.url) == shared_llm.CREDITS_URL
    assert str(completion.url) == shared_llm.API_URL
    assert json.loads(completion.content) == {
        "model": model, "messages": MESSAGES, "max_tokens": 321, "temperature": 0, "usage": {"include": True},
        "provider": {"max_price": {"prompt": 0.30, "completion": 1.20, "request": 0, "image": 0},
                     "require_parameters": True},
    }
    assert call.cost_usd == pytest.approx(0.0001)


def test_live_verify_rejects_calls_that_cannot_fit_shared_budget(mock_provider):
    requests, _, spend_file = mock_provider
    shared_llm.SPEND.budget_usd = 0.001

    with pytest.raises(llm.LLMUnavailable, match="live call needs .* live cap"):
        llm.ask_json(SYSTEM, USER, max_tokens=1000)

    assert all(request.method == "GET" for request in requests)
    assert shared_llm.SPEND.calls == 0
    assert not spend_file.exists()


def test_live_verify_translates_shared_credit_refusal(mock_provider):
    requests, provider, spend_file = mock_provider
    provider["balance"] = 0.10

    with pytest.raises(llm.LLMUnavailable, match=r"balance.*0\.10.*0\.30"):
        llm.ask_json(SYSTEM, USER)

    assert [request.method for request in requests] == ["GET"]
    assert not spend_file.exists()


def test_provider_error_details_stay_out_of_verify_exception(mock_provider):
    _, provider, _ = mock_provider
    provider.update(status=401, reply={"error": "private provider diagnostic"})

    with pytest.raises(llm.LLMUnavailable, match="request failed") as exc:
        llm.ask_json(SYSTEM, USER)

    assert "private provider diagnostic" not in str(exc.value)
    assert exc.value.__suppress_context__


@pytest.mark.parametrize("provider", ["deepseek", "openrouter"])
@pytest.mark.parametrize("mode", ["replay", "record", "auto"])
def test_legacy_cache_preserves_original_answer_and_measurements(mock_provider, monkeypatch, provider, mode):
    requests, _, _ = mock_provider
    record_legacy_answer()
    monkeypatch.setenv("OG_PROVIDER", provider)
    monkeypatch.setenv("OG_LLM", mode)

    parsed, call = llm.ask_json(SYSTEM, USER)

    assert parsed == ANSWER
    assert call == llm.LLMCall(MODEL, 42, 17, 0.0005, 2.5, True)
    assert requests == []


def test_new_recording_is_replayed_from_shared_cache(mock_provider, monkeypatch):
    requests, _, _ = mock_provider
    monkeypatch.setenv("OG_LLM", "record")
    _, live = llm.ask_json(SYSTEM, USER)
    assert len(list(shared_llm.REPLAY_DIR.glob("*.json"))) == 1
    assert not llm.CACHE_DIR.exists()

    monkeypatch.setenv("OG_LLM", "replay")
    monkeypatch.setenv("OG_PROVIDER", "openrouter")
    parsed, replayed = llm.ask_json(SYSTEM, USER)

    assert parsed == ANSWER
    assert replayed == llm.LLMCall(MODEL, 100, 50, live.cost_usd, 0.0, True)
    assert [request.method for request in requests] == ["GET", "POST"]


def test_replay_miss_reports_both_recording_stores(mock_provider, monkeypatch):
    requests, _, _ = mock_provider
    monkeypatch.setenv("OG_LLM", "replay")

    with pytest.raises(llm.LLMUnavailable, match="OG_LLM=replay.*No legacy Verify recording"):
        llm.ask_json(SYSTEM, USER)

    assert requests == []
