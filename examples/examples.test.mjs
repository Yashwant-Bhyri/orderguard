// Smoke tests for the Node examples and the first-run error messages. Everything here is offline. The tests that need a loopback port
// (the throwaway receiver) skip themselves where binding is not allowed, such as a sandbox.
import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createServer } from "node:net";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { MIN_NODE, installProblem, nodeProblem } from "../receiver/bridge/preflight.mjs";

const run = promisify(execFile);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const node = (args, options = {}) => run(process.execPath, args, { cwd: root, timeout: 120_000, ...options }).catch((error) => error);

const loopback = await new Promise((resolve) => {
  const server = createServer();
  server.once("error", () => resolve(false));
  server.listen(0, "127.0.0.1", () => server.close(() => resolve(true)));
});

test("a Node that is too old gets one sentence that says what to install", () => {
  assert.equal(nodeProblem(`${MIN_NODE.join(".")}.0`), null);
  assert.equal(nodeProblem("23.0.0"), null);
  for (const old of ["20.11.1", "22.12.9", "18.0.0"]) {
    const message = nodeProblem(old);
    assert.match(message, new RegExp(`Node ${old.replace(/\./g, "\\.")} is too old`));
    assert.match(message, /22\.13/);
    assert.match(message, /nvm install 22/);
  }
});

test("missing node_modules says to run npm ci", () => {
  assert.equal(installProblem("/repo", () => true), null);
  assert.match(installProblem("/repo", () => false), /npm ci/);
});

test("the receiver bridge explains a missing or unreadable mandate before it binds anything", async () => {
  const none = await node(["receiver/bridge/serve.mjs"]);
  assert.match(none.stderr, /--mandate FILE is required.*orderguard init/);
  const missing = await node(["receiver/bridge/serve.mjs", "--mandate", "no/such/mandate.json"]);
  assert.match(missing.stderr, /no mandate file at no\/such\/mandate\.json: create one with `orderguard init`/);
  assert.notEqual(missing.code, 0);
});

test("the MCP tool-listing example starts the server over stdio with no network and lists its tools", async () => {
  const out = await node(["examples/mcp/list-tools.mjs"]);
  assert.equal(out.code, undefined, out.stderr);
  assert.match(out.stdout, /tools \(4\): get_mandate, propose_order, order_status, cancel/);
  assert.match(out.stdout, /receiver_unavailable/);
  assert.match(out.stdout, /Check that the receiver is running and ORDERGUARD_URL is correct/);
});

test("examples/node/check-order.mjs: the agent's order is refused with a reason", { skip: !loopback && "binding a loopback port is not allowed here" }, async () => {
  const out = await node(["examples/node/check-order.mjs"], { env: { PATH: process.env.PATH, TMPDIR: process.env.TMPDIR } });
  assert.equal(out.code, undefined, out.stderr);
  assert.match(out.stdout, /allowed {2}buy 1 AAPL -> filled/);
  assert.match(out.stdout, /refused {2}sell 1 AAPL -> HTTP 409: .*mandate_action_out_of_scope/);
  assert.match(out.stdout, /refused {2}buy 500 AAPL -> order-notional: Estimated notional is .* above the .* limit/);
  assert.match(out.stdout, /venueDispatchAttempted: false/);
  // the header of the example shows the same lines
  const header = readFileSync(join(root, "examples/node/check-order.mjs"), "utf8");
  assert.match(header, /mandate_action_out_of_scope/);
  assert.match(header, /order-notional: Estimated notional/);
});

test("the MCP config files are valid JSON that point at real entry points", () => {
  const desktop = JSON.parse(readFileSync(join(root, "examples/mcp/claude_desktop_config.json"), "utf8"));
  assert.deepEqual(desktop.mcpServers.orderguard.args, ["-m", "orderguard_mcp"]);
  const receiver = JSON.parse(readFileSync(join(root, "examples/mcp/receiver-server.json"), "utf8"));
  assert.ok(readFileSync(join(root, receiver.mcpServers["orderguard-receiver"].args[0].replace("/path/to/orderguard/", "")), "utf8").includes("orderguard-mcp"));
});
