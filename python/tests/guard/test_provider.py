"""Provider wire translation and live budget enforcement against an offline transport."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from orderguard_guard import llm


def test_deepseek_wire_maps_model_and_reasoning(monkeypatch):
    monkeypatch.setenv("OG_PROVIDER", "deepseek")
    body = {"model": "deepseek/deepseek-v4.1-flash", "messages": [], "max_tokens": 10,
            "usage": {"include": True}, "reasoning": {"effort": "low"}}
    url, wire = llm.LLM(mode="replay")._wire(body)
    assert url == llm.DEEPSEEK_URL
    assert wire["model"] == "deepseek-flash" and wire["reasoning_effort"] == "low"
    assert "usage" not in wire and "reasoning" not in wire
    assert body["model"] == "deepseek/deepseek-v4.1-flash"      # the logical body (replay key) is untouched


def test_openrouter_wire_is_unchanged(monkeypatch):
    monkeypatch.setenv("OG_PROVIDER", "openrouter")
    body = {"model": "deepseek/deepseek-v4.1-flash", "messages": []}
    assert llm.LLM(mode="replay")._wire(body) == (llm.API_URL, body)


def test_headers_match_selected_provider(monkeypatch):
    monkeypatch.setattr(llm, "api_key", lambda: "test-only")
    client = llm.LLM(mode="replay")
    monkeypatch.setenv("OG_PROVIDER", "deepseek")
    assert client._headers() == {"Authorization": "Bearer test-only", "Content-Type": "application/json"}
    monkeypatch.setenv("OG_PROVIDER", "openrouter")
    assert client._headers()["HTTP-Referer"] == "https://github.com/orderguard"
    assert client._headers()["X-Title"] == "OrderGuard"


def test_cost_is_estimated_when_provider_reports_none(tmp_path):
    c = llm.LLM(mode="replay", spend_file=tmp_path / "s.jsonl", spend=llm.Spend(budget_usd=1.0))
    resp = {"usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}
    c._record_spend("m", resp)
    assert abs(resp["usage"]["cost"] - llm.PRICE_IN) < 1e-9 and resp["usage"]["cost_estimated"]


MSG = [{"role": "user", "content": "hello"}]


@pytest.fixture
def mock_live(monkeypatch, tmp_path):
    monkeypatch.setenv("OG_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "PRICE_IN", 0.30)
    monkeypatch.setattr(llm, "PRICE_OUT", 1.20)
    monkeypatch.setattr(llm, "api_key", lambda: "test-only")
    monkeypatch.setattr(llm.LLM, "_backoff", lambda self, attempt: None)

    def make(handler, *, budget=0.05, balance="0.308", retries=0, before_credits=lambda: None):
        spend = llm.Spend(budget_usd=budget)
        methods = []

        def transport(request):
            methods.append(request.method)
            if request.method == "GET":
                before_credits()
                return httpx.Response(200, json={"balance_infos": [{"currency": "USD", "total_balance": balance}]})
            return handler(request)

        with_http = httpx.Client(transport=httpx.MockTransport(transport))
        client = llm.LLM("deepseek/deepseek-v4.1-flash", mode="live", client=with_http, spend=spend, retries=retries,
                         replay_dir=tmp_path / "replay", spend_file=tmp_path / "spend.jsonl")
        return client, spend, methods

    return make


def completion(usage):
    return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}], "usage": usage})


def test_over_budget_requests_do_not_reach_http(mock_live):
    client, _, methods = mock_live(lambda req: pytest.fail("sent an unaffordable request"), budget=0.008)
    with pytest.raises(llm.BudgetExceeded):
        client.chat(MSG, max_tokens=2500, model="deepseek/deepseek-v4-pro")
    large_tool = {"type": "function", "function": {"name": "lookup", "description": "文" * 10_000}}
    with pytest.raises(llm.BudgetExceeded):
        client.chat(MSG, tools=[large_tool], max_tokens=1)
    with pytest.raises(llm.BudgetExceeded):
        client.chat(MSG, max_tokens=1, extra={"max_tokens": None})
    assert methods == []


def test_concurrent_reservations_respect_credit_headroom_and_reconcile(mock_live):
    started, release = threading.Event(), threading.Event()

    def handler(request):
        started.set()
        assert release.wait(5), "test did not release first completion"
        return completion({"cost": 0.001})

    client, spend, methods = mock_live(handler)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.chat, MSG)
        try:
            assert started.wait(5), "first completion never started"
            with pytest.raises(llm.BudgetExceeded):
                pool.submit(client.chat, MSG).result(timeout=5)
            assert methods == ["GET", "POST"]
        finally:
            release.set()
        assert first.result(timeout=5)["_meta"]["cost_usd"] == 0.001
    assert client.chat(MSG)["_meta"]["cost_usd"] == 0.001
    assert spend.spent_usd == 0.002 and methods == ["GET", "POST", "POST"]


def test_concurrent_first_calls_share_one_credit_check(mock_live):
    checked, release, duplicate = threading.Event(), threading.Event(), threading.Event()

    def before_credits():
        if checked.is_set():
            duplicate.set()
        checked.set()
        assert release.wait(5), "test did not release the balance check"

    client, spend, methods = mock_live(lambda req: completion({"prompt_tokens": 5, "completion_tokens": 2}),
                                       before_credits=before_credits)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.chat, MSG, max_tokens=100)
        try:
            assert checked.wait(5), "balance check never started"
            second = pool.submit(client.chat, [{"role": "user", "content": "another"}], max_tokens=100)
            assert not duplicate.wait(0.1)
        finally:
            release.set()
        assert first.result(timeout=5)["usage"]["cost_estimated"]
        assert second.result(timeout=5)["usage"]["cost_estimated"]
    assert spend.spent_usd == pytest.approx(0.0000078) and methods == ["GET", "POST", "POST"]


def test_definite_failures_release_budget_and_retry_holds_it(mock_live, monkeypatch):
    responses = iter([429, 400, 200])

    def handler(request):
        status = next(responses)
        return completion({"cost": 0.001}) if status == 200 else httpx.Response(status)

    client, spend, methods = mock_live(handler, retries=1)

    def during_retry(attempt):
        with pytest.raises(llm.BudgetExceeded):
            client.chat(MSG)

    monkeypatch.setattr(client, "_backoff", during_retry)
    with pytest.raises(llm.LLMError, match="HTTP 400"):
        client.chat(MSG)
    assert spend.spent_usd == 0.0 and methods == ["GET", "POST", "POST"]
    assert client.chat(MSG)["_meta"]["cost_usd"] == 0.001


def test_ambiguous_retry_cannot_double_charge_the_same_reservation(mock_live):
    def timeout(request):
        raise httpx.ReadTimeout("test response timeout", request=request)

    client, spend, methods = mock_live(timeout, retries=1)
    with pytest.raises(llm.BudgetExceeded):
        client.chat(MSG)
    assert spend.spent_usd == 0.0 and methods == ["GET", "POST"]
    with pytest.raises(llm.BudgetExceeded):
        client.chat(MSG)
    assert methods == ["GET", "POST"]
    [row] = map(json.loads, client.spend_file.read_text().splitlines())
    assert row["outcome"] == "unconfirmed" and row["reason"] == "ReadTimeout"
    assert 0.0048 < row["exposure_usd"] < 0.008
    assert "cost_usd" not in row and spend.calls == 0


def test_missing_usage_cannot_refund_the_reservation(mock_live):
    client, _, methods = mock_live(lambda req: completion(None))
    assert client.chat(MSG)["usage"]["cost_estimated"]
    with pytest.raises(llm.BudgetExceeded):
        client.chat(MSG)
    assert methods == ["GET", "POST"]


def test_first_reservation_can_be_rejected_by_credit_headroom(mock_live):
    client, _, methods = mock_live(lambda req: completion({"cost": 0.0001}), balance="0.301")
    with pytest.raises(llm.BudgetExceeded):
        client.chat(MSG)
    assert methods == ["GET"] and not client.spend_file.exists()
    assert client.chat(MSG, max_tokens=100)["_meta"]["cost_usd"] == 0.0001
    assert methods == ["GET", "POST"]


def test_rejected_credit_check_releases_reservation(mock_live):
    client, _, methods = mock_live(lambda req: pytest.fail("sent a completion below the floor"), balance="0.295")
    for _ in range(2):
        with pytest.raises(llm.CreditFloor):
            client.chat(MSG)
    assert methods == ["GET", "GET"] and not client.spend_file.exists()
