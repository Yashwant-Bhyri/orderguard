import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { generateKeyPairSync, sign } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const dir = mkdtempSync(join(tmpdir(), "og-bridge-test-"));
const base = { symbols: ["AAPL", "MSFT"], sides: ["buy"], maxOrderNotionalUsd: 10000, maxDailyNotionalUsd: 20000, priceBandPct: 5, expiresAt: new Date(Date.now() + 3_600_000).toISOString(), referencePrices: { AAPL: 222.7, MSFT: 420.18 } };

// The owner's Ed25519 key. The bridge enforces only a mandate this key signed, verified against the pinned signing.pub.
const owner = generateKeyPairSync("ed25519");
const ownerPub = owner.publicKey.export({ format: "jwk" }).x;
const pubB64 = Buffer.from(ownerPub, "base64url").toString("base64");
const proofOf = (body, key = owner.privateKey) => {
  const bytes = Buffer.from(JSON.stringify(body), "utf8");
  return { payload: bytes.toString("base64"), signature: sign(null, bytes, key).toString("base64") };
};
writeFileSync(join(dir, "signing.pub"), pubB64 + "\n");

// Owner approval of one held order (signed paper mode): purpose, parent, ledger and revision come from GET /policy.
const approval = (policy, orderId) => proofOf({ purpose: "orderguard.paper-order-approval.v1", parentId: policy.parentId,
  ledgerId: policy.ledgerId, revision: policy.revision, orderId });

async function boot(name, mandate, extraArgs = [], { raw } = {}) {
  const file = join(dir, name + ".json");
  writeFileSync(file, raw ?? JSON.stringify(proofOf(mandate)));
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
  return { post, get, stop, child, stderr: () => err };
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

test("bridge: orders above the signed step-up threshold are held until the owner signs the approval", async () => {
  const b = await boot("m2", { ...base, stepUpAboveUsd: 5000 }); running.push(b);
  const small = await b.post("/propose", o("s-small", { quantity: 10 }));
  assert.equal(small.decision, "filled");
  const held = await b.post("/propose", o("s-big", { quantity: 30 }));
  assert.equal(held.decision, "held"); assert.equal(held.ledgerEffect, false); assert.ok(held.orderId);
  let snap = await b.get("/snapshot");
  assert.equal(snap.orders.find((x) => x.orderId === held.orderId).status, "held");

  // A loopback caller (the agent) cannot release a hold: approval needs the owner's signature.
  const unsigned = await b.post("/approve", { orderId: held.orderId });
  assert.equal(unsigned.decision, "denied"); assert.equal(unsigned.reason, "approval_invalid");
  const stranger = generateKeyPairSync("ed25519");
  const forged = await b.post("/approve", { orderId: held.orderId, authorization: proofOf({ purpose: "orderguard.paper-order-approval.v1", ...(await b.get("/policy")), orderId: held.orderId }, stranger.privateKey) });
  assert.equal(forged.decision, "denied");

  const policy = await b.get("/policy");
  const approved = await b.post("/approve", { orderId: held.orderId, authorization: approval(policy, held.orderId) });
  assert.equal(approved.decision, "filled"); assert.equal(approved.ledgerEffect, true);
  const again = await b.post("/approve", { orderId: held.orderId, authorization: approval(policy, held.orderId) });
  assert.equal(again.ledgerEffect, false);
  snap = await b.get("/snapshot");
  assert.equal(snap.orders.filter((x) => x.status === "filled").length, 2);

  const nothing = await b.post("/approve", { orderId: "og_unknown" });
  assert.equal(nothing.decision, "denied");

  const held2 = await b.post("/propose", o("s-big2", { quantity: 30 }));
  assert.equal(held2.decision, "held");
  await b.post("/revoke");
  const late = await b.post("/approve", { orderId: held2.orderId, authorization: approval(policy, held2.orderId) });
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

// ---- review finding: the --mandate path must verify the owner's signature and keep the signed step-up ----

test("bridge: a Python-signed mandate (orderguard init's file) keeps its step-up: $9,576 under a $9,500 threshold is HELD, not filled", async () => {
  // The bytes Python's gate.sign_mandate signs: canonical JSON with Python float reprs (10000.0) and sorted keys.
  const expiresAt = new Date(Date.now() + 3_600_000).toISOString();
  const canonical = `{"expiresAt":${JSON.stringify(expiresAt)},"maxDailyNotionalUsd":20000.0,"maxOrderNotionalUsd":10000.0,"priceBandPct":5.0,`
    + `"referencePrices":{"AAPL":222.7},"sides":["buy"],"stepUpAboveUsd":9500.0,"symbols":["AAPL"]}`;
  const signature = sign(null, Buffer.from(canonical, "utf8"), owner.privateKey).toString("base64");
  // As `orderguard init` writes it: indented, Python lexemes, the signer's key alongside (never trusted; the pinned one is).
  const file = `{\n  "symbols": ["AAPL"],\n  "sides": ["buy"],\n  "maxOrderNotionalUsd": 10000.0,\n  "maxDailyNotionalUsd": 20000.0,\n`
    + `  "priceBandPct": 5.0,\n  "expiresAt": ${JSON.stringify(expiresAt)},\n  "referencePrices": {"AAPL": 222.7},\n  "stepUpAboveUsd": 9500.0,\n`
    + `  "signature": "${signature}",\n  "signerPublicKey": "${pubB64}"\n}\n`;
  const b = await boot("py-signed", null, [], { raw: file }); running.push(b);
  const big = await b.post("/propose", o("py-9576", { quantity: 43 }));   // 43 x 222.70 = 9,576.10
  assert.equal(big.decision, "held", JSON.stringify(big)); assert.equal(big.ledgerEffect, false);
  assert.equal(big.notionalUsd, 9576.1);
  const small = await b.post("/propose", o("py-small", { quantity: 1 }));
  assert.equal(small.decision, "filled");
  await b.stop();
});

const refuse = (file, ...args) => spawnSync(process.execPath, [join(root, "receiver/bridge/serve.mjs"), "--mandate", file, ...args], { encoding: "utf8", timeout: 60_000 });

test("bridge: refuses to start on an unsigned, tampered or foreign-signed mandate, a step-up flag, or a missing owner key", () => {
  const unsigned = join(dir, "unsigned.json");
  writeFileSync(unsigned, JSON.stringify({ ...base, stepUpAboveUsd: 9500 }));
  let r = refuse(unsigned);
  assert.notEqual(r.status, 0); assert.match(r.stderr, /not signed/); assert.doesNotMatch(r.stdout, /READY/);

  const good = proofOf(base);
  const tampered = join(dir, "tampered.json");
  const body = JSON.parse(Buffer.from(good.payload, "base64").toString("utf8"));
  writeFileSync(tampered, JSON.stringify({ payload: Buffer.from(JSON.stringify({ ...body, maxOrderNotionalUsd: 1e9 })).toString("base64"), signature: good.signature }));
  r = refuse(tampered);
  assert.notEqual(r.status, 0); assert.match(r.stderr, /signature did not verify/);

  const foreign = join(dir, "foreign.json");
  writeFileSync(foreign, JSON.stringify(proofOf(base, generateKeyPairSync("ed25519").privateKey)));
  r = refuse(foreign);
  assert.notEqual(r.status, 0); assert.match(r.stderr, /signature did not verify/);

  const ok = join(dir, "ok.json");
  writeFileSync(ok, JSON.stringify(good));
  r = refuse(ok, "--step-up-usd", "1000000");
  assert.notEqual(r.status, 0); assert.match(r.stderr, /--step-up-usd was removed/);

  const lonely = mkdtempSync(join(dir, "nokey-"));
  writeFileSync(join(lonely, "mandate.json"), JSON.stringify(good));
  r = refuse(join(lonely, "mandate.json"));
  assert.notEqual(r.status, 0); assert.match(r.stderr, /no owner public key/);
});

test("bridge: a configured revocation list that is missing or invalid fails closed (the bridge does not start)", () => {
  const ok = join(dir, "rev-ok.json");
  writeFileSync(ok, JSON.stringify(proofOf(base)));
  let r = refuse(ok, "--revocations", join(dir, "no-such-revocations.json"));
  assert.notEqual(r.status, 0); assert.match(r.stderr, /revocation list is missing or invalid/); assert.doesNotMatch(r.stdout, /READY/);
  const junk = join(dir, "junk-revocations.json");
  writeFileSync(junk, "{not json");
  r = refuse(ok, "--revocations", junk);
  assert.notEqual(r.status, 0); assert.match(r.stderr, /revocation list is missing or invalid/);
});

test("bridge: a revocation file deleted while serving fails closed: every later proposal is denied", async () => {
  const rev = join(dir, "live-revocations.json");
  writeFileSync(rev, "[]");
  const b = await boot("rev-live", base, ["--revocations", rev]); running.push(b);
  assert.equal((await b.post("/propose", o("rv-1", { quantity: 1 }))).decision, "filled");
  rmSync(rev);
  const after = await b.post("/propose", o("rv-2", { quantity: 1 }));
  assert.equal(after.decision, "denied"); assert.equal(after.ledgerEffect, false);
  assert.equal((await b.get("/snapshot")).orders.length, 1);
  await b.stop();
});

test("bridge: --demo-unsigned is explicit and loud", async () => {
  const b = await boot("demo", null, ["--demo-unsigned"], { raw: JSON.stringify({ ...base, stepUpAboveUsd: 5000 }) }); running.push(b);
  const held = await b.post("/propose", o("d-big", { quantity: 30 }));
  assert.equal(held.decision, "held", "the demo path maps stepUpAboveUsd through the same parser");
  assert.match(b.stderr(), /WARNING: --demo-unsigned\. The mandate's owner signature is NOT checked/);
  await b.stop();
  const r = refuse(join(dir, "demo.json"), "--demo-unsigned", "--pub", join(dir, "signing.pub"));
  assert.notEqual(r.status, 0); assert.match(r.stderr, /--demo-unsigned takes no owner key/);
});
