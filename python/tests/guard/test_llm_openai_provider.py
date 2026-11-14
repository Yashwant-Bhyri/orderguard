"""OG_PROVIDER=openai translates the logical request for OpenAI's own API and prices it from list rates. Offline."""
import pytest

from orderguard_guard import llm as L


def test_openai_wire_and_pricing(monkeypatch):
    monkeypatch.setenv("OG_PROVIDER", "openai")
    assert L.key_var() == "OPENAI_API_KEY"
    c = L.LLM("openai/gpt-6-luna", mode="replay")
    body = {"model": "openai/gpt-6-luna", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 100, "temperature": 0.0,
            "usage": {"include": True}, "reasoning": {"effort": "low"}}
    url, wire = c._wire(body)
    assert url == L.OPENAI_URL and wire["model"] == "gpt-6-luna" and wire["max_completion_tokens"] == 100
    assert "max_tokens" not in wire and "usage" not in wire and "temperature" not in wire and wire["reasoning_effort"] == "low"


def test_openai_unknown_model_is_refused_before_spending(monkeypatch):
    monkeypatch.setenv("OG_PROVIDER", "openai")
    c = L.LLM("openai/some-unpriced-model", mode="replay")
    body = {"model": "openai/some-unpriced-model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}
    url, wire = c._wire(body)
    with pytest.raises(L.BudgetExceeded):
        c._budgeted_payload(wire)
