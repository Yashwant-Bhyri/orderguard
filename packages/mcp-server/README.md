# OrderGuard MCP server

An MCP stdio server exposing `get_mandate`, `propose_order`, `order_status`, and `cancel`. The server is a thin adapter: every preview, order, status read, and cancellation challenge goes through OrderGuard's public HTTP routes. It does not contain signing authority or connect directly to a venue.

## Run from a source checkout

```sh
ORDERGUARD_URL=http://127.0.0.1:4173 node bin/orderguard-mcp.js
```

MCP frames use newline-delimited JSON-RPC on stdin/stdout. Logs and rejected-frame notices go to stderr. For remote receivers, use HTTPS. Provide `ORDERGUARD_BEARER_TOKEN` only through the host's secret environment mechanism; never put it in the URL or agent prompt.

## Install and verify

```sh
npm pack
npm install ./orderguard-mcp-server-0.1.0.tgz
npm test
```

In the assembled GitHub release, `npx --yes github:Yashwant-Bhyri/orderguard` is supported by the repository-root `bin` shim that forwards to this package. npm's GitHub spec installs the repository root; it does not address this nested package by path. The packager must include that root shim.

## Security boundary and status

The MCP server carries only the receiver URL and optional bearer capability. The mesh receiver checks the exact typed proposal and owns budget, idempotency, revocation, and paper-ledger effects. `cancel` starts a human step-up and cannot approve it. Release status: **owner packaged; receiver review pending**. No remote OAuth resource-server deployment or production broker integration is claimed.
