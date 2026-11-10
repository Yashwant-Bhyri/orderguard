"""A small outside research agent, run as its own process. It knows nothing about OrderGuard's internals.

It reads a packet of source notes, asks a model to write a memo and an order, then submits both to the gateway
over MCP with the `propose_order` tool, exactly as any other MCP client (Claude Desktop, Claude Code) could.

    python -m orderguard_verify.agent data/verify/demo/packets/poisoned.txt
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from ..core.llm import ask_json

SYSTEM = ("You are a research agent for a trading desk. You cannot check facts yourself. Using only the source packet, write a short "
          "research memo (80 to 140 words, plain prose, quote the figures as given) and the order it recommends. "
          'Reply with JSON only: {"memo": "...", "order": {"ticker": "...", "side": "buy" or "sell", "quantity": <integer>}}')


async def run(packet: str, url: str) -> dict:
    data, call = ask_json(SYSTEM, packet, model=os.getenv("OG_AGENT_MODEL") or None)
    memo, order = data["memo"], data["order"]
    print(f"agent> memo ({len(memo.split())} words) for {order['ticker']}: proposing to {order['side']} {order['quantity']} shares\n")
    print("  " + memo.replace("\n", "\n  ") + "\n")
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            print(f"agent> connected over MCP, gateway offers tools: {tools}")
            result = await session.call_tool("propose_order", {"research": memo, "order": order})
            reply = result.structuredContent or json.loads(result.content[0].text)
            reply = reply.get("result", reply)
    print(f"agent> gateway says: order {reply['status'].upper()} (memo check: {reply['action']}; {reply['coverage']})")
    for reason in reply.get("reasons", []):
        print(f"       - {reason}")
    for f in reply.get("fix", []):
        print(f"       fix: {f['claim']}")
    return reply


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("packet")
    p.add_argument("--url", default=f"http://127.0.0.1:{os.getenv('OG_GATEWAY_PORT', '8765')}/mcp")
    a = p.parse_args()
    asyncio.run(run(Path(a.packet).read_text(), a.url))


if __name__ == "__main__":
    main()
