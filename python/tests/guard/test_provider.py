"""DeepSeek-direct provider: wire translation and cost estimate, offline."""
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
    monkeypatch.delenv("OG_PROVIDER", raising=False)
    body = {"model": "deepseek/deepseek-v4.1-flash", "messages": []}
    assert llm.LLM(mode="replay")._wire(body) == (llm.API_URL, body)


def test_cost_is_estimated_when_provider_reports_none(tmp_path):
    c = llm.LLM(mode="replay", spend_file=tmp_path / "s.jsonl", spend=llm.Spend(budget_usd=1.0))
    resp = {"usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}}
    c._record_spend("m", resp)
    assert abs(resp["usage"]["cost"] - llm.PRICE_IN) < 1e-9 and resp["usage"]["cost_estimated"]
