import test from "node:test";
import assert from "node:assert/strict";
import { OrderGuardClient } from "../src/index.js";

test("constructor rejects credential URLs and cleartext remote receivers", () => {
  assert.throws(() => new OrderGuardClient({ baseUrl: "https://synthetic-user:synthetic-pass@receiver" }), /without credentials/);
  assert.throws(() => new OrderGuardClient({ baseUrl: "http://example.test" }), /HTTPS/);
});

test("typed proposal uses only public preview and receiver routes", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    const path = new URL(url).pathname;
    calls.push([init.method, path, init.body ? JSON.parse(init.body) : undefined]);
    if (path === "/api/chat") return Response.json({
      run: { id: "run-1", outcome: "ready", intent: { symbol: "AAPL", side: "buy", quantity: 1, market: "US", orderType: "market", session: "regular", timeInForce: "day", limitPrice: null } },
      paperConfirmation: { token: "preview-token", intentHash: "intent-hash" },
    });
    if (path === "/api/paper-orders") return Response.json({ order: { id: "paper-1", status: "filled" }, executionMesh: "LocalSim" });
    throw new Error(`unexpected route: ${path}`);
  };
  const client = new OrderGuardClient({ fetchImpl });
  const result = await client.proposeOrder({ mandateId: "mandate-1", symbol: "aapl", side: "buy", quantity: 1 });
  assert.equal(result.state, "filled");
  assert.deepEqual(calls.map(([method, path]) => [method, path]), [
    ["POST", "/api/chat"],
    ["POST", "/api/paper-orders"],
  ]);
  assert.equal(calls[1][2].previewToken, "preview-token");
});

test("typed preview mismatch is denied before an order submission", async () => {
  const paths = [];
  const client = new OrderGuardClient({ fetchImpl: async (url) => {
    const path = new URL(url).pathname;
    paths.push(path);
    return Response.json({ run: { id: "run-1", outcome: "ready", intent: { symbol: "NVDA", side: "buy", quantity: 1, market: "US", orderType: "market", session: "regular", timeInForce: "day", limitPrice: null } }, paperConfirmation: { token: "x", intentHash: "y" } });
  } });
  const result = await client.proposeOrder({ mandateId: "m", symbol: "AAPL", side: "buy", quantity: 1 });
  assert.equal(result.state, "proposal_denied");
  assert.deepEqual(paths, ["/api/chat"]);
});
