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
