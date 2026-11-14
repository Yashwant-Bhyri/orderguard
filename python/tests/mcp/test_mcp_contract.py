"""MCP contract: every registered tool is listed with a usable schema and called with valid and invalid input over a real client
session; one test also spawns the server as a subprocess over stdio, the way an MCP client does. Offline."""
import asyncio
import json
import os
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from orderguard_mcp.server import build_server

FIG = {"metric": "revenue", "fiscal_year": 2024, "value": 391035, "unit": "USD millions"}
ORDER = {"ticker": "AAPL", "side": "buy", "quantity": 40, "limit_price": 222.9, "as_of": "2024-11-06"}
EVENTS = [{"type": "quote_change", "ticker": t, "pct": -1.0, "source": s} for t in ("ISRG",) for s in ("VenueA", "VenueB")]
RULE = {"id": "R1", "kind": "pct_change", "inputs": ["ISRG"], "threshold": -10, "notional": 1000, "side": "sell"}

# tool -> (valid arguments, invalid arguments, text the protocol error must contain)
CASES = {
    "screen_text": ({"text": "Apple shares were steady."}, {"text": "x", "kind": "bogus"}, "kind"),
    "check_order": (ORDER, {**ORDER, "quantity": 0}, "quantity"),
    "verify_figures": ({"ticker": "AAPL", "as_of": "2024-11-06", "figures": [FIG]}, {"ticker": "AAPL", "as_of": "yesterday", "figures": [FIG]}, "as_of"),
    "get_reported_figure": ({"ticker": "AAPL", "metric": "revenue", "fiscal_year": 2024}, {"ticker": "AAPL", "metric": "vibes", "fiscal_year": 2024}, "metric"),
    "evaluate_rules": ({"rules": [RULE], "events": EVENTS}, {"rules": [], "events": EVENTS}, "rules"),
    "get_mandate": ({}, {"surprise": 1}, "surprise"),
    "submit_order": ({"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 222.7, "idempotency_key": "contract-key-0001"},
                     {"ticker": "AAPL", "side": "buy", "quantity": 1, "limit_price": 222.7, "idempotency_key": "x"}, "idempotency_key"),
    "review_mandate": ({"source": "demo"}, {"source": "demo", "agents": 10**9}, "agents"),
}


async def _with_session(fn):
    async with create_connected_server_and_client_session(build_server()._mcp_server) as client:
        return await fn(client)


def test_every_tool_is_covered_and_described_for_a_model():
    async def go(c):
        tools = (await c.list_tools()).tools
        assert {t.name for t in tools} == set(CASES), "a tool was added or removed: add it to CASES"
        for t in tools:
            assert len(t.description) > 80, f"{t.name}: the description must tell a model when to call it"
            assert t.inputSchema["type"] == "object" and t.annotations is not None
            for name, prop in t.inputSchema["properties"].items():
                assert prop.get("description") or "$ref" in prop or "anyOf" in prop, f"{t.name}.{name} has no description"
            if t.name != "get_mandate":
                assert all(p.get("description") for p in t.inputSchema["properties"].values()), f"{t.name}: every argument needs a description"
    asyncio.run(_with_session(go))


@pytest.mark.parametrize("name", sorted(CASES))
def test_valid_input_returns_an_ok_envelope_and_invalid_input_a_clear_error(name):
    valid, invalid, field = CASES[name]

    async def go(c):
        ok = await c.call_tool(name, valid)
        assert not ok.isError, ok.content[0].text
        body = ok.structuredContent
        assert body is not None and body.get("ok") is True
        bad = await c.call_tool(name, invalid)
        assert bad.isError
        text = bad.content[0].text
        assert text.startswith("invalid_input:") and field in text
        assert "Traceback" not in text and "errors.pydantic.dev" not in text and "input_value" not in text
    asyncio.run(_with_session(go))


def test_unknown_tool_and_unknown_argument_are_errors_not_crashes():
    async def go(c):
        r = await c.call_tool("transfer_funds", {"amount": 1})
        assert r.isError and "Traceback" not in r.content[0].text
        r = await c.call_tool("check_order", {**ORDER, "daily_total": 5})        # a typo of daily_total_usd must not be silently dropped
        assert r.isError and "daily_total" in r.content[0].text and "daily_total_usd" in r.content[0].text
    asyncio.run(_with_session(go))


def test_oversize_inputs_are_rejected_by_the_schema():
    async def go(c):
        assert (await c.call_tool("screen_text", {"text": "x" * 100_001})).isError
        assert (await c.call_tool("evaluate_rules", {"rules": [RULE] * 51, "events": EVENTS})).isError
        assert (await c.call_tool("evaluate_rules", {"rules": [RULE], "events": EVENTS, "lies": [1e9]})).isError
        assert (await c.call_tool("review_mandate", {"source": "demo", "steps": 0})).isError
    asyncio.run(_with_session(go))


def test_review_mandate_bad_draft_is_a_structured_report_not_a_crash():
    async def go(c):
        r = await c.call_tool("review_mandate", {"source": "demo", "draft": {"nonsense": True}})
        assert not r.isError and r.structuredContent["ok"] is True and r.structuredContent["fit"]["fits"] is False
        r = await c.call_tool("review_mandate", {"source": "demo", "mode": "rank", "draft": {"symbols": ["AAPL"]}})
        assert r.structuredContent["ok"] is False and r.structuredContent["error"]["type"] == "invalid_input"
    asyncio.run(_with_session(go))


def test_stdio_subprocess_session(tmp_path):
    """The real client path: spawn `python -m orderguard_mcp`, talk JSON-RPC over stdio, nothing but protocol on stdout."""
    env = {**os.environ, "OG_LLM": "replay", "ORDERGUARD_HOME": str(tmp_path / "no-config"), "OG_SPEND_FILE": str(tmp_path / "spend.jsonl")}

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "orderguard_mcp"], env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                info = await asyncio.wait_for(s.initialize(), 30)
                assert info.serverInfo.name == "orderguard" and "check_order" in (info.instructions or "")
                assert {t.name for t in (await s.list_tools()).tools} == set(CASES)
                res = await s.call_tool("check_order", ORDER)
                assert res.structuredContent["decision"] == "allow"
                assert json.loads(res.content[0].text)["ok"] is True
    asyncio.run(go())
