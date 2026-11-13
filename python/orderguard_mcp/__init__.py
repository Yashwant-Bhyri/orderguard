"""OrderGuard as an MCP server: the pre-trade guard itself, callable by any MCP client.

`python -m orderguard_mcp` starts a stdio server. The tool implementations live in `core`; `server` registers them.
(The TypeScript server in packages/mcp-server is a different thing: it fronts the L8 receiver. See docs/MCP.md.)
"""
__all__ = ["core", "server"]
