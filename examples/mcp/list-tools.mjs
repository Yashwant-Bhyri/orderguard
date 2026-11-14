#!/usr/bin/env node
// A tiny MCP client for the Node receiver server (packages/mcp-server): start it over stdio and list its tools. No network.
//
//   node examples/mcp/list-tools.mjs
//
// The server speaks newline-delimited JSON-RPC on stdin/stdout, so this needs nothing but Node 20+ (no `npm ci`, no SDK). It asks for
// the tool list, then calls get_mandate with no receiver running to show the error an agent gets in that case.
// Expected output (about a quarter of a second), exit code 0:
//
//   server: orderguard 0.1.0 (protocol 2025-11-25)
//   tools (4): get_mandate, propose_order, order_status, cancel
//
//   get_mandate with no receiver -> error: receiver_unavailable
//     OrderGuard receiver could not be reached. Nothing was sent. Check that the receiver is running and ORDERGUARD_URL is correct, then try again.
//
// Point it at a real receiver by setting ORDERGUARD_URL (and ORDERGUARD_BEARER_TOKEN if it needs one) before running.
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const [major] = process.versions.node.split(".").map(Number);
if (major < 20) {
  console.error(`error: Node ${process.versions.node} is too old; the OrderGuard MCP server needs Node 20 or newer (nvm install 22).`);
  process.exit(1);
}
const script = join(dirname(fileURLToPath(import.meta.url)), "../../packages/mcp-server/bin/orderguard-mcp.js");
const server = spawn(process.execPath, [script], {
  // An unreachable address on purpose when none is configured: loopback port 9 is closed, so the failure is immediate and offline.
  env: { PATH: process.env.PATH ?? "", ORDERGUARD_URL: process.env.ORDERGUARD_URL ?? "http://127.0.0.1:9", ORDERGUARD_BEARER_TOKEN: process.env.ORDERGUARD_BEARER_TOKEN ?? "" },
  stdio: ["pipe", "pipe", "inherit"],
});
server.on("error", (error) => { console.error(`error: could not start the MCP server: ${error.message}`); process.exit(1); });
const lines = createInterface({ input: server.stdout })[Symbol.asyncIterator]();
let nextId = 0;
async function rpc(method, params = {}) {
  const id = ++nextId;
  server.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
  const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error(`no answer to ${method} within 10 s`)), 10_000).unref());
  const { value, done } = await Promise.race([lines.next(), timeout]);
  if (done) throw new Error("the server closed its output before answering");
  const frame = JSON.parse(value);
  if (frame.error) throw new Error(`${method}: ${frame.error.message}`);
  return frame.result;
}

let code = 0;
try {
  const init = await rpc("initialize", { protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "orderguard-example", version: "0.1.0" } });
  server.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })}\n`);
  console.log(`server: ${init.serverInfo.name} ${init.serverInfo.version} (protocol ${init.protocolVersion})`);
  const { tools } = await rpc("tools/list");
  console.log(`tools (${tools.length}): ${tools.map((t) => t.name).join(", ")}\n`);
  const reply = await rpc("tools/call", { name: "get_mandate", arguments: {} });
  const body = JSON.parse(reply.content[0].text);
  console.log(`get_mandate with ${process.env.ORDERGUARD_URL ? "your receiver" : "no receiver"} -> ${reply.isError ? `error: ${body.reason}` : "ok"}`);
  if (body.detail) console.log(`  ${body.detail}`);
  if (tools.length === 0) code = 1;
} catch (error) {
  console.error(`error: ${error.message}`);
  code = 1;
} finally {
  server.stdin.end();
  server.kill();
}
process.exitCode = code;
