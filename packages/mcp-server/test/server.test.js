import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createInterface } from "node:readline";

test("stdio server lists the four bounded OrderGuard tools", async () => {
  const child = spawn(process.execPath, ["bin/orderguard-mcp.js"], { stdio: ["pipe", "pipe", "ignore"] });
  const lines = createInterface({ input: child.stdout });
  const iterator = lines[Symbol.asyncIterator]();
  try {
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-11-25" } }) + "\n");
    const init = JSON.parse((await iterator.next()).value);
    assert.equal(init.result.protocolVersion, "2025-11-25");
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }) + "\n");
    const list = JSON.parse((await iterator.next()).value);
    assert.deepEqual(list.result.tools.map((tool) => tool.name), ["get_mandate", "propose_order", "order_status", "cancel"]);
    assert.equal(list.result.tools[1].inputSchema.additionalProperties, false);
  } finally {
    child.kill("SIGTERM");
    await once(child, "exit");
    lines.close();
  }
});

test("malformed lines get a JSON-RPC error instead of silence, and an unreachable receiver is reported actionably", async () => {
  const child = spawn(process.execPath, ["bin/orderguard-mcp.js"], { stdio: ["pipe", "pipe", "ignore"], env: { ...process.env, ORDERGUARD_URL: "http://127.0.0.1:1" } });
  const lines = createInterface({ input: child.stdout });
  const iterator = lines[Symbol.asyncIterator]();
  try {
    child.stdin.write("{not json\n");
    assert.equal(JSON.parse((await iterator.next()).value).error.code, -32700);
    child.stdin.write("[1]\n");
    assert.equal(JSON.parse((await iterator.next()).value).error.code, -32600);
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 7, method: "tools/call", params: { name: "get_mandate", arguments: {} } }) + "\n");
    const reply = JSON.parse((await iterator.next()).value);
    assert.equal(reply.id, 7);
    const body = JSON.parse(reply.result.content[0].text);
    assert.equal(reply.result.isError, true);
    assert.equal(body.reason, "receiver_unavailable");
    assert.match(body.detail, /Check that the receiver is running/);
  } finally {
    child.kill("SIGTERM");
    await once(child, "exit");
    lines.close();
  }
});
