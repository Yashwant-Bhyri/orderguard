#!/usr/bin/env node
// An agent's order is refused with a reason, through the OrderGuard Node SDK (packages/sdk).
//
//   node examples/node/check-order.mjs                         # self-contained: starts a throwaway paper receiver
//   ORDERGUARD_URL=http://127.0.0.1:4173 node examples/node/check-order.mjs   # your own receiver (the SDK's routes, not the :8700 bridge)
//
// Needs Node 22.13+ and `npm ci` once (the throwaway receiver is TypeScript). No API key, no model, no network beyond loopback.
// The first run starts a receiver on a free 127.0.0.1 port, has a synthetic owner sign a mandate (buy AAPL, up to 10 shares per
// order), and removes everything on exit. Expected output (about two seconds), exit code 0:
//
//   OrderGuard Node SDK example: throwaway paper receiver on http://127.0.0.1:<port>, synthetic owner, no model
//   Mandate: buy AAPL, market/limit orders, regular session, day, up to 10 shares per order
//
//   allowed  buy 1 AAPL -> filled (paper:run-<id>)
//   refused  sell 1 AAPL -> HTTP 409: The distributed risk engine did not approve this paper proposal: mandate_action_out_of_scope
//   refused  buy 500 AAPL -> order-notional: Estimated notional is $109210.00 USD equivalent, above the $12,500 illustrative limit.
//   Neither refused order was dispatched (venueDispatchAttempted: false). To retry, stay inside: buy AAPL, market/limit orders, regular session, day, up to 10 shares per order.
//
// With your own receiver (ORDERGUARD_URL) the same code runs against its active mandate; set ORDERGUARD_BEARER_TOKEN if it needs one.
import { OrderGuardClient, OrderGuardError, OrderGuardUnavailable } from "@orderguard/sdk";   // the npm workspace link to packages/sdk made by `npm ci`
import { startLocalSim } from "./localsim.mjs";

const own = process.env.ORDERGUARD_URL;
let sim = null;
let exitCode = 0;
try {
  sim = own ? null : await startLocalSim();
  const baseUrl = own ?? sim.base;
  console.log(`OrderGuard Node SDK example: ${own ? `your receiver at ${baseUrl}` : `throwaway paper receiver on ${baseUrl}, synthetic owner, no model`}`);

  // The SDK carries no signing key. It asks the receiver which mandate is active and proposes typed orders under it.
  const orderguard = new OrderGuardClient({ baseUrl });
  const status = await orderguard.getMandate();
  const active = status.mandates?.find((row) => row.active === true && (!sim || row.mandateId === sim.mandateId));
  if (!active) {
    throw new Error("The receiver has no active mandate. The owner must sign one first (in the receiver's UI); an agent cannot create its own authority.");
  }
  const shape = (m) => `${m.side} ${m.symbol}, ${m.allowedOrderTypes?.join("/") ?? "market"} orders, ${m.session} session, ${m.timeInForce}, up to ${m.maxQuantityPerOrder} shares per order`;
  console.log(`Mandate: ${shape(active)}\n`);

  // What a fooled agent might send: an honest order, an order on the wrong side, and an order far above the mandate's size.
  const proposals = [
    { side: "buy", quantity: 1 },
    { side: "sell", quantity: 1 },
    { side: "buy", quantity: 500 },
  ];
  let refused = 0;
  let dispatched = false;
  for (const { side, quantity } of proposals) {
    const label = `${side} ${quantity} AAPL`;
    const result = await orderguard.proposeOrder({ mandateId: active.mandateId, symbol: "AAPL", side, quantity, orderType: "market", session: "regular", timeInForce: "day" });
    if (result.state === "denied" || result.state === "proposal_denied") {
      refused += 1;
      dispatched ||= result.venueDispatchAttempted !== false;
      console.log(`refused  ${label} -> ${result.statusCode ? `HTTP ${result.statusCode}: ` : ""}${result.reason}`);
    } else if (result.state === "filled") {
      console.log(`allowed  ${label} -> filled (${result.orderId})`);
    } else {
      console.log(`${String(result.state).padEnd(8)} ${label} -> ${result.reason ?? result.guidance ?? "see the receiver"}`);
    }
  }
  const retry = (await orderguard.getMandate()).mandates?.find((row) => row.mandateId === active.mandateId);
  console.log(`${dispatched ? "A refused order may have been dispatched: check the receiver." : "Neither refused order was dispatched (venueDispatchAttempted: false)."}${retry ? ` To retry, stay inside: ${shape(retry)}.` : ""}`);
  if (refused === 0) { console.error("No order was refused: the mandate is wider than this example's orders. Try a smaller mandate."); exitCode = 1; }
} catch (error) {
  if (error instanceof OrderGuardUnavailable) {
    console.error(`error: ${error.message}\nStart the receiver this SDK talks to (docs/QUICKSTART.md, Node tab), or unset ORDERGUARD_URL to use the throwaway one.`);
  } else if (error instanceof OrderGuardError && (error.status === 401 || error.status === 403)) {
    console.error(`error: the receiver refused this client (HTTP ${error.status}). Set ORDERGUARD_BEARER_TOKEN to a token the receiver accepts.`);
  } else {
    console.error(`error: ${error?.message ?? error}`);
  }
  exitCode = 1;
} finally {
  await sim?.stop();
}
process.exitCode = exitCode;
