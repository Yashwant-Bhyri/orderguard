#!/usr/bin/env node
import { createInterface } from "node:readline";
import { OrderGuardClient, OrderGuardError } from "../src/client.js";

const PROTOCOL_VERSION = "2025-11-25";
if (process.argv.includes("--version")) {
  process.stdout.write("0.1.0\n");
  process.exit(0);
}
const TOOLS = [
  { name: "get_mandate", description: "Read active mandate metadata. Does not create or broaden authority.", inputSchema: { type: "object", properties: {}, additionalProperties: false } },
  {
    name: "propose_order",
    description: "Submit one typed proposal to the OrderGuard receiver; receiver scope, budget, expiry, revocation and idempotency checks remain authoritative.",
    inputSchema: {
      type: "object",
      properties: {
        mandate_id: { type: "string" }, symbol: { type: "string" }, side: { type: "string", enum: ["buy", "sell"] },
        quantity: { type: "integer", minimum: 1 }, order_type: { type: "string", enum: ["market", "limit"] },
        limit_price: { type: ["string", "number"] }, session: { type: "string", enum: ["regular", "premarket", "afterhours", "overnight", "hk_regular"] },
        time_in_force: { type: "string", enum: ["day", "gtc"] },
      },
      required: ["mandate_id", "symbol", "side", "quantity", "order_type"],
      additionalProperties: false,
    },
  },
  { name: "order_status", description: "Read final paper order state from the receiver snapshot.", inputSchema: { type: "object", properties: { order_id: { type: "string" } }, required: ["order_id"], additionalProperties: false } },
  { name: "cancel", description: "Start cancellation step-up. The agent cannot approve it; the owner must use the trusted device.", inputSchema: { type: "object", properties: { order_id: { type: "string" } }, required: ["order_id"], additionalProperties: false } },
];

const client = new OrderGuardClient();
const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });

function frame(id, result, isError = false) {
  const content = { content: [{ type: "text", text: JSON.stringify(result) }] };
  if (isError) content.isError = true;
  return { jsonrpc: "2.0", id, result: content };
}

async function callTool(name, args) {
  switch (name) {
    case "get_mandate": return client.getMandate();
    case "propose_order": return client.proposeOrder({
      mandateId: String(args.mandate_id ?? ""),
      symbol: String(args.symbol ?? ""),
      side: args.side,
      quantity: args.quantity,
      orderType: args.order_type,
      limitPrice: args.limit_price,
      session: args.session ?? "regular",
      timeInForce: args.time_in_force ?? "day",
    });
    case "order_status": return client.orderStatus(String(args.order_id ?? ""));
    case "cancel": return client.cancel(String(args.order_id ?? ""));
    default: throw new TypeError("unknown_orderguard_tool");
  }
}

async function dispatch(message) {
  const { id, method, params = {} } = message;
  if (method === "notifications/initialized" || id === undefined) return undefined;
  if (method === "ping") return { jsonrpc: "2.0", id, result: {} };
  if (method === "initialize") {
    const requested = params.protocolVersion;
    return { jsonrpc: "2.0", id, result: {
      protocolVersion: [PROTOCOL_VERSION, "2025-06-18"].includes(requested) ? requested : PROTOCOL_VERSION,
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "orderguard", version: "0.1.0" },
    } };
  }
  if (method === "tools/list") return { jsonrpc: "2.0", id, result: { tools: TOOLS } };
  if (method === "tools/call") {
    try {
      if (!params.arguments || typeof params.arguments !== "object" || Array.isArray(params.arguments)) throw new TypeError("tool_arguments_must_be_object");
      return frame(id, await callTool(String(params.name ?? ""), params.arguments));
    } catch (error) {
      const payload = error instanceof OrderGuardError
        ? { state: "denied", status_code: error.status, reason: error.payload?.error ?? "receiver_denied" }
        : { state: "error", reason: error instanceof TypeError ? error.message : "receiver_request_failed" };
      return frame(id, payload, true);
    }
  }
  return { jsonrpc: "2.0", id, error: { code: -32601, message: "Method not found" } };
}

for await (const line of rl) {
  try {
    const message = JSON.parse(line);
    if (!message || typeof message !== "object" || Array.isArray(message)) continue;
    const response = await dispatch(message);
    if (response !== undefined) process.stdout.write(`${JSON.stringify(response)}\n`);
  } catch (error) {
    // MCP stdout is reserved for JSON-RPC. Never echo request headers or tokens.
    process.stderr.write(`OrderGuard MCP input rejected (${error?.name ?? "Error"}).\n`);
  }
}
