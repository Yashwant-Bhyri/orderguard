#!/usr/bin/env python3
"""A tiny generic MCP client: start the OrderGuard server over stdio, list its tools, and get an order refused with a reason.

    .venv/bin/python examples/mcp/list_tools.py

Offline: the client spawns `python -m orderguard_mcp` as a child process and talks JSON-RPC over its stdin and stdout, the same
way Claude Desktop or any MCP client does. No network, no model, no API key. It uses the server's labelled demo mandate unless
you pass your own config directory: `... list_tools.py --home var/orderguard`. Expected output (about two seconds):

    server: orderguard
    tools (10): screen_text, check_order, verify_figures, get_reported_figure, evaluate_rules, get_mandate, review_mandate, review_held_order, review_mandate_draft, submit_order

    check_order buy 440 AAPL @ 22.30 -> REFUSE
      The order is worth $97,988 at the trusted price of $222.70 (440 shares), above the per-order cap of $10,000.
      With $0 already placed today this order would bring the day's total to $97,988, above the daily cap of $20,000.
      The limit price $22.30 is 90.0% below the trusted price $222.70; the mandate allows at most 5%.
      The order is worth $97,988, above the $9,500 step-up threshold, so a human must approve it.
    mandate: demo, signature verified: True

Exit code 0 means the server started, listed its tools, and refused the order. This is also the pattern for any MCP client library:
spawn the command, `initialize`, `list_tools`, `call_tool`.
"""
import argparse
import asyncio
import json
import os
import sys

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    sys.exit("The `mcp` package is not installed in this Python. From the repository root run `sh scripts/quickstart.sh --no-serve --skip-tests`, "
             "then use `.venv/bin/python` to run this file.")


async def run(home: str | None) -> int:
    # Replay mode and the offline flag guarantee the server never calls a model or fetches filings.
    env = {**os.environ, "OG_LLM": "replay", "ORDERGUARD_OFFLINE": "1"}
    if home:
        env["ORDERGUARD_HOME"] = home
    else:
        env.pop("ORDERGUARD_HOME", None)      # a stray value would silently change which mandate this demo uses
    server = StdioServerParameters(command=sys.executable, args=["-m", "orderguard_mcp"], env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            info = await asyncio.wait_for(session.initialize(), timeout=30)
            tools = (await session.list_tools()).tools
            print(f"server: {info.serverInfo.name}")
            print(f"tools ({len(tools)}): {', '.join(t.name for t in tools)}\n")
            order = {"ticker": "AAPL", "side": "buy", "quantity": 440, "limit_price": 22.30}   # sized from a forged split notice
            result = await session.call_tool("check_order", order)
            body = result.structuredContent or json.loads(result.content[0].text)
            if result.isError or not body.get("ok"):
                print(f"check_order failed: {body.get('error', result.content[0].text if result.content else 'no detail')}")
                return 1
            print(f"check_order buy {order['quantity']} {order['ticker']} @ {order['limit_price']:.2f} -> {body['decision'].upper()}")
            for reason in body["reasons"]:
                print(f"  {reason}")
            mandate = body["mandate"]
            print(f"mandate: {mandate['source']}, signature verified: {mandate['signature_verified']}")
            if home and mandate["source"] == "demo":
                print(f"warning: {mandate.get('label', 'the demo mandate was used')}")
                return 1
            return 0 if body["decision"] == "refuse" and len(tools) > 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--home", help="an `orderguard init` directory whose signed mandate.json to use (default: the labelled demo mandate)")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args.home)))
