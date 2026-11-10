import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const dir = mkdtempSync(join(tmpdir(), "og-bridge-test-"));
const base = { symbols: ["AAPL", "MSFT"], sides: ["buy"], maxOrderNotionalUsd: 10000, maxDailyNotionalUsd: 20000, priceBandPct: 5, expiresAt: new Date(Date.now() + 3_600_000).toISOString(), referencePrices: { AAPL: 222.7, MSFT: 420.18 } };

async function boot(name, mandate, extraArgs = []) {
  const file = join(dir, name + ".json");
  writeFileSync(file, JSON.stringify(mandate));
  const child = spawn(process.execPath, [join(root, "receiver/bridge/serve.mjs"), "--mandate", file, ...extraArgs], { stdio: ["ignore", "pipe", "pipe"] });
  let err = ""; child.stderr.on("data", (c) => { err += c; });
  const lines = createInterface({ input: child.stdout });
  const port = await new Promise((ok, bad) => {
    const t = setTimeout(() => bad(new Error("bridge boot timeout " + err)), 60_000);
    lines.on("line", (l) => { const m = l.match(/^READY (\d+)$/); if (m) { clearTimeout(t); ok(Number(m[1])); } });
    child.once("exit", () => bad(new Error("bridge exited " + err)));
  });
  const url = `http://127.0.0.1:${port}`;
  const post = async (p, body) => (await fetch(url + p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) })).json();
  const get = async (p) => (await fetch(url + p)).json();
  const stop = () => new Promise((ok) => { if (child.exitCode !== null) return ok(); child.once("exit", ok); child.kill("SIGTERM"); });
  return { post, get, stop, child };
}

const o = (id, over = {}) => ({ symbol: "AAPL", side: "buy", quantity: 44, limitPrice: 222.7, clientOrderId: id, ...over });
const running = [];
after(async () => { await Promise.all(running.map((b) => b.stop())); rmSync(dir, { recursive: true, force: true }); });

test("bridge: honest, fake split, unlisted, sell, duplicate, revoke, then propose again", async () => {
  const b = await boot("m1", base); running.push(b);
  const health = await b.get("/health");
  assert.equal(health.status, "ready");
  assert.equal(health.issuerMandateActive, true);

  const honest = await b.post("/propose", o("t-honest"));
  assert.equal(honest.decision, "filled"); assert.equal(honest.ledgerEffect, true); assert.ok(honest.orderId);

  const split = await b.post("/propose", o("t-split", { quantity: 440, limitPrice: 22.3 }));
  assert.equal(split.decision, "denied"); assert.equal(split.reason, "limit_outside_band"); assert.equal(split.ledgerEffect, false);

  const unlisted = await b.post("/propose", o("t-unlisted", { symbol: "TSLA", limitPrice: 300, quantity: 1 }));
  assert.equal(unlisted.decision, "denied"); assert.equal(unlisted.reason, "unlisted_symbol");

  const cyr = await b.post("/propose", o("t-cyr", { symbol: "АAAPL", quantity: 1 }));
  assert.equal(cyr.decision, "denied"); assert.equal(cyr.reason, "non_ascii_symbol");

  const sell = await b.post("/propose", o("t-sell", { side: "sell", quantity: 1 }));
  assert.equal(sell.decision, "denied"); assert.equal(sell.reason, "side_not_allowed");

  const dup = await b.post("/propose", o("t-honest"));
  assert.equal(dup.orderId, honest.orderId); assert.equal(dup.ledgerEffect, false); assert.equal(dup.replay, true);

  let snap = await b.get("/snapshot");
  assert.equal(snap.orders.length, 1);
  assert.equal(snap.orders[0].clientOrderId, "t-honest");
  assert.equal(snap.ledgerIntegrity, true);

  assert.deepEqual(await b.post("/revoke"), { revoked: true });
  assert.equal((await b.get("/health")).issuerMandateActive, false, "r5 must also show the mandate revoked");
  const after = await b.post("/propose", o("t-after", { quantity: 1 }));
  assert.equal(after.decision, "denied"); assert.equal(after.reason, "mandate_revoked"); assert.equal(after.ledgerEffect, false);
  snap = await b.get("/snapshot");
  assert.equal(snap.orders.length, 1);
  assert.equal(snap.ledgerIntegrity, true);
  await b.stop();
});

test("bridge: orders above the step-up threshold are held until the owner passkey approves via POST /approve", async () => {
  const b = await boot("m2", base, ["--step-up-usd", "5000"]); running.push(b);
  const small = await b.post("/propose", o("s-small", { quantity: 10 }));
  assert.equal(small.decision, "filled");
  const held = await b.post("/propose", o("s-big", { quantity: 30 }));
  assert.equal(held.decision, "held"); assert.equal(held.ledgerEffect, false); assert.ok(held.orderId);
  let snap = await b.get("/snapshot");
  assert.equal(snap.orders.find((x) => x.orderId === held.orderId).status, "held");

  const approved = await b.post("/approve", { orderId: held.orderId });
  assert.equal(approved.decision, "filled"); assert.equal(approved.ledgerEffect, true);
  const again = await b.post("/approve", { orderId: held.orderId });
  assert.equal(again.ledgerEffect, false);
  snap = await b.get("/snapshot");
  assert.equal(snap.orders.filter((x) => x.status === "filled").length, 2);

  const nothing = await b.post("/approve", { orderId: "og_unknown" });
  assert.equal(nothing.decision, "denied");

  const held2 = await b.post("/propose", o("s-big2", { quantity: 30 }));
  assert.equal(held2.decision, "held");
  await b.post("/revoke");
  const late = await b.post("/approve", { orderId: held2.orderId });
  assert.equal(late.decision, "denied");
  snap = await b.get("/snapshot");
  assert.equal(snap.orders.filter((x) => x.status === "filled").length, 2);
  assert.equal(snap.ledgerIntegrity, true);
  await b.stop();
});
