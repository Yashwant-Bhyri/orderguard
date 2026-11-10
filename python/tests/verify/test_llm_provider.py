"""The verify LLM client's provider switch: wire translation, unchanged cache keys, untouched default path.

Offline: httpx.post is monkeypatched, and the cache directory is a tmp_path, so nothing is sent or written
under data/.
"""
import json

import httpx
import pytest

from orderguard_verify.core import llm

MODEL = "deepseek/deepseek-v4.1-flash"
SYSTEM, USER = "You extract claims.", "ACME had revenue of $5.0 billion."
ANSWER = {"claims": []}
REPLY = {"choices": [{"message": {"role": "assistant", "content": json.dumps(ANSWER)}}],
         "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.delenv("OG_PROVIDER", raising=False)
    monkeypatch.delenv("OG_ENV_FILE", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("OG_LLM", "live")
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "cache")
    return monkeypatch


def capture(monkeypatch, reply=REPLY):
    sent = []

    def fake_post(url, **kw):
        sent.append({"url": url, **kw})
        return httpx.Response(200, json=reply, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return sent


def test_default_path_sends_the_logical_request_unchanged(env):
    sent = capture(env)
    parsed, call = llm.ask_json(SYSTEM, USER, model="nvidia/nemotron-3.5-super-vl:free", max_tokens=321)
    assert parsed == ANSWER
    assert sent[0]["url"] == llm.API_URL
    assert sent[0]["json"] == {"model": "nvidia/nemotron-3.5-super-vl:free", "temperature": 0, "max_tokens": 321,
                               "usage": {"include": True},
                               "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]}
    assert sent[0]["headers"]["Authorization"] == "Bearer or-test-key"
    assert call.cost_usd == 0.0   # default path keeps the old behaviour: no cost reported, none estimated


def test_default_wire_is_the_request_object_itself():
    req = {"model": "m", "usage": {"include": True}}
    assert llm._wire(req) == (llm.API_URL, req)


def test_deepseek_wire_translation(env):
    env.setenv("OG_PROVIDER", "deepseek")
    env.setenv("DEEPSEEK_API_KEY", "ds-test-key")
    sent = capture(env)
    llm.ask_json(SYSTEM, USER, model=MODEL, max_tokens=77)
    assert sent[0]["url"] == "https://api.deepseek.com/chat/completions"
    body = sent[0]["json"]
    assert body == {"model": "deepseek-flash", "temperature": 0, "max_tokens": 77,
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]}
    assert "usage" not in body
    assert sent[0]["headers"]["Authorization"] == "Bearer ds-test-key"


def test_deepseek_other_model_ids_drop_the_vendor_prefix(env):
    env.setenv("OG_PROVIDER", "deepseek")
    req = {"model": "deepseek/deepseek-v4-pro", "usage": {"include": True}, "messages": []}
    assert llm._wire(req)[1]["model"] == "deepseek-v4-pro"
    assert llm._wire({"model": "vendor/some-model", "messages": []})[1]["model"] == "some-model"


def test_deepseek_key_read_by_name_from_env_file(env, tmp_path):
    env.setenv("OG_PROVIDER", "deepseek")
    envfile = tmp_path / "keys.env"
    envfile.write_text("OPENROUTER_API_KEY=or-only\nexport DEEPSEEK_API_KEY='file-key'\n")
    env.setenv("OG_ENV_FILE", str(envfile))
    assert llm._api_key() == "file-key"


def test_deepseek_missing_key_is_reported_by_the_deepseek_name(env):
    env.setenv("OG_PROVIDER", "deepseek")
    with pytest.raises(llm.LLMUnavailable, match="DEEPSEEK_API_KEY"):
        llm.ask_json(SYSTEM, USER, model=MODEL)


def test_deepseek_cost_is_estimated_from_tokens_when_not_reported(env):
    env.setenv("OG_PROVIDER", "deepseek")
    env.setenv("DEEPSEEK_API_KEY", "ds-test-key")
    capture(env)
    _, call = llm.ask_json(SYSTEM, USER, model=MODEL)
    assert call.cost_usd == pytest.approx((1000 * llm.PRICE_IN + 500 * llm.PRICE_OUT) / 1e6)
    assert call.prompt_tokens == 1000 and call.completion_tokens == 500


def test_cache_key_is_computed_from_the_logical_request(env, tmp_path):
    """A recording made under OpenRouter is found again under deepseek, and a live deepseek call writes the same file."""
    key = llm._cache_path(MODEL, SYSTEM, USER)
    assert key.name == llm._cache_path(MODEL, SYSTEM, USER).name
    assert key.name.endswith(".json") and len(key.stem) == 32

    # live under deepseek writes to the path the OpenRouter-shaped request would produce
    env.setenv("OG_PROVIDER", "deepseek")
    env.setenv("DEEPSEEK_API_KEY", "ds-test-key")
    capture(env)
    llm.ask_json(SYSTEM, USER, model=MODEL)
    assert (llm.CACHE_DIR / key.name).exists()

    # and a replay under deepseek hits that recording without any network call
    env.setenv("OG_LLM", "replay")
    env.setattr(llm.httpx, "post", lambda *a, **k: pytest.fail("replay must not call the network"))
    parsed, call = llm.ask_json(SYSTEM, USER, model=MODEL)
    assert parsed == ANSWER and call.cached is True


def test_cache_key_does_not_depend_on_provider(env):
    env.setenv("OG_LLM", "replay")
    llm.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = llm._cache_path(MODEL, SYSTEM, USER)
    path.write_text(json.dumps({"text": json.dumps(ANSWER),
                                "call": {"model": MODEL, "prompt_tokens": 0, "completion_tokens": 0,
                                         "cost_usd": 0.0, "latency_s": 0.0, "cached": False}}))
    for prov in (None, "openrouter", "deepseek"):
        if prov is None:
            env.delenv("OG_PROVIDER", raising=False)
        else:
            env.setenv("OG_PROVIDER", prov)
        assert llm.ask_json(SYSTEM, USER, model=MODEL)[0] == ANSWER


def test_deepseek_provider_defaults_to_a_deepseek_model(monkeypatch, tmp_path):
    """The default model (a free OpenRouter model) does not exist on DeepSeek's API; the provider picks V4.1 Flash."""
    import orderguard_verify.core.llm as L
    sent = {}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    def fake_post(url, **kw):
        sent.update(kw["json"])
        return R()

    monkeypatch.setenv("OG_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-not-a-key")
    monkeypatch.setenv("OG_LLM", "live")
    monkeypatch.delenv("OG_MODEL", raising=False)
    monkeypatch.setattr(L, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(L.httpx, "post", fake_post)
    L.ask_json("s", "u")
    assert sent["model"] == "deepseek-flash"
