import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
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

const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));

test("bridge: the anchor is renewed before it expires, so an honest order still fills after the first anchor would have lapsed", async () => {
  const b = await boot("m3", base, ["--anchor-ttl-sec", "3"]); running.push(b);
  const h0 = await b.get("/health");
  assert.equal(h0.anchorRenewals, 0);
  const firstAnchor = h0.anchorId;
  assert.equal((await b.post("/propose", o("r-early", { quantity: 1 }))).decision, "filled");

  await sleep(4500); // past the first anchor's 3 s lifetime
  const h1 = await b.get("/health");
  assert.ok(h1.anchorRenewals >= 1, "proactive renewal should have happened");
  assert.notEqual(h1.anchorId, firstAnchor);
  assert.equal(h1.issuerMandateActive, true);
  assert.equal(h1.mandateId, h0.mandateId, "the core mandate identity does not change");

  const late = await b.post("/propose", o("r-late", { quantity: 2 }));
  assert.equal(late.decision, "filled"); assert.equal(late.ledgerEffect, true);
  const snap = await b.get("/snapshot");
  assert.equal(snap.orders.length, 2);
  assert.equal(snap.ledgerIntegrity, true);
  await b.stop();
});

test("bridge: with proactive renewal off, a lapsed anchor is renewed on demand; after /revoke nothing renews and proposals are denied", async () => {
  const b = await boot("m4", base, ["--anchor-ttl-sec", "2", "--anchor-renew-frac", "off"]); running.push(b);
  const firstAnchor = (await b.get("/health")).anchorId;
  await sleep(2800);
  const lapsed = await b.get("/health");
  assert.equal(lapsed.issuerMandateActive, false, "first anchor has expired and /health does not renew");
  assert.equal(lapsed.anchorRenewals, 0);

  const filled = await b.post("/propose", o("d-1", { quantity: 3 }));
  assert.equal(filled.decision, "filled");
  const renewed = await b.get("/health");
  assert.equal(renewed.anchorRenewals, 1);
  assert.notEqual(renewed.anchorId, firstAnchor);

  assert.deepEqual(await b.post("/revoke"), { revoked: true });
  await sleep(3000); // would be past the renewed anchor's lifetime too
  const dead = await b.get("/health");
  assert.equal(dead.anchorRenewals, 1, "revocation is final: no renewal after /revoke");
  assert.equal(dead.issuerMandateActive, false);
  const denied = await b.post("/propose", o("d-2", { quantity: 1 }));
  assert.equal(denied.decision, "denied"); assert.equal(denied.reason, "mandate_revoked"); assert.equal(denied.ledgerEffect, false);
  assert.equal((await b.get("/health")).anchorRenewals, 1);
  const snap = await b.get("/snapshot");
  assert.equal(snap.orders.length, 1);
  assert.equal(snap.ledgerIntegrity, true);
  await b.stop();
});

test("bridge: a failed renewal keeps failing closed with anchor_unavailable", async () => {
  const b = await boot("m5", base, ["--anchor-ttl-sec", "2", "--anchor-renew-frac", "off"]); running.push(b);
  assert.equal((await b.post("/propose", o("f-1", { quantity: 1 }))).decision, "filled");
  // Take r5 away so the ceremony cannot succeed.
  const kids = execFileSync("pgrep", ["-P", String(b.child.pid)]).toString().trim().split(/\s+/).filter(Boolean);
  assert.ok(kids.length >= 1, "r5 child process found");
  for (const k of kids) process.kill(Number(k), "SIGKILL");
  await sleep(2800);
  const d = await b.post("/propose", o("f-2", { quantity: 1 }));
  assert.equal(d.decision, "denied"); assert.equal(d.reason, "anchor_unavailable"); assert.equal(d.ledgerEffect, false);
  assert.match(d.detail, /anchor renewal failed/);
  const snap = await b.get("/snapshot");
  assert.equal(snap.orders.length, 1);
  assert.equal(snap.ledgerIntegrity, true);
  await b.stop();
});
