#!/usr/bin/env node
// OrderGuard receiver bridge (CONTRACT 5.1).
//   node receiver/bridge/serve.mjs [--port P] --mandate mandate.json [--step-up-usd N]
//                                [--anchor-ttl-sec S] [--anchor-renew-frac F|off]
//
// Boots the r5 receiver on a free loopback port with an isolated temp ledger, registers a synthetic
// owner passkey, authorises ONE human mandate through the same synthetic WebAuthn flow as the
// quickstart, then serves a small loopback HTTP API backed by the receiver core.
//
// Who owns what: r5 holds the owner passkey and the passkey-signed mandate, and is the source of
// truth for whether that mandate is still active (revocation goes through the passkey ceremony).
// The receiver core (receiver/core) values every order at the trusted price, enforces the JSON
// mandate's scope and budget, and owns the effect ledger. A proposal commits only if BOTH agree.
import { spawn } from "node:child_process";
import { createServer as createHttpServer } from "node:http";
import { createServer as createNetServer } from "node:net";
import { mkdtemp, readFile, realpath, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createInterface } from "node:readline";
import { register } from "tsx/esm/api";
import { virtualPasskey, registrationResponse, authenticationResponse } from "./synthetic-passkey.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");

function arg(name) { const i = process.argv.indexOf(name); return i >= 0 ? process.argv[i + 1] : undefined; }

async function freePort() {
  const s = createNetServer();
  await new Promise((ok, bad) => { s.once("error", bad); s.listen(0, "127.0.0.1", ok); });
  const { port } = s.address();
  await new Promise((ok) => s.close(ok));
  return port;
}

async function jsonFetch(base, path, body) {
  const res = await fetch(base + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { origin: new URL(base).origin, ...(body === undefined ? {} : { "content-type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await res.json();
  if (!res.ok) throw new Error(`${path} HTTP ${res.status}`);
  return payload;
}

async function main() {
  const mandatePath = arg("--mandate");
  const proofPath = arg("--parent-proof");
  const ownerPath = arg("--owner-public-key");
  const revocations = arg("--revocations");
  const stepUp = arg("--step-up-usd");
  if (Boolean(mandatePath) === Boolean(proofPath) || Boolean(proofPath) !== Boolean(ownerPath) || (proofPath && stepUp !== undefined)
      || (revocations && !proofPath)) {
    throw new Error("Choose --mandate FILE for a demo, or --parent-proof FILE --owner-public-key FILE for signed paper policy");
  }
  register();
  const { ReceiverCore } = await import(pathToFileURL(join(root, "receiver/core/receiver-core.ts")).href);
  const { SignedPaperPolicy } = await import(pathToFileURL(join(root, "receiver/core/paper-policy.ts")).href);
  const signedPolicy = proofPath ? new SignedPaperPolicy(JSON.parse(await readFile(resolve(proofPath), "utf8")),
    (await readFile(resolve(ownerPath), "utf8")).trim()) : undefined;
  const mandate = signedPolicy?.parent ?? JSON.parse(await readFile(resolve(mandatePath), "utf8"));
  if (stepUp !== undefined) mandate.stepUpThresholdUsd = Number(stepUp);
  // Anchor lifetime and renewal point. r5 caps a mandate at 1 h and floors it at 2 s (see receiver/r5/PATCHES.md).
  const ttlRaw = arg("--anchor-ttl-sec") ?? process.env.ORDERGUARD_ANCHOR_TTL_SEC;
  const ttlSec = ttlRaw === undefined || ttlRaw === "" ? 3600 : Number(ttlRaw);
  if (!Number.isFinite(ttlSec) || ttlSec < 2 || ttlSec > 3600) throw new Error("--anchor-ttl-sec must be between 2 and 3600");
  const anchorTtlMs = Math.round(ttlSec * 1000);
  const fracRaw = arg("--anchor-renew-frac") ?? process.env.ORDERGUARD_ANCHOR_RENEW_FRAC ?? "0.8";
  const renewFrac = fracRaw === "off" ? null : Number(fracRaw);
  if (renewFrac !== null && !(renewFrac >= 0.1 && renewFrac <= 0.95)) throw new Error("--anchor-renew-frac must be 0.1..0.95 or off");
  const mandateExpiresMs = Date.parse(mandate.expiresAt);
  if (signedPolicy && Date.now() >= mandateExpiresMs) throw new Error("The signed parent policy is expired");
  let core = null;
  const parentUnrevoked = async () => {
    if (!revocations) return true;
    try {
      const ids = JSON.parse(await readFile(resolve(revocations), "utf8"));
      if (!Array.isArray(ids) || ids.some((id) => typeof id !== "string")) return false;
      if (!ids.includes(signedPolicy.parentId)) return true;
      if (core && !core.revoked) core.revoke();
      return false;
    } catch (error) { return error?.code === "ENOENT"; }
  };
  if (!await parentUnrevoked()) throw new Error("The signed parent is revoked or its revocation list is invalid");
  const wanted = arg("--port");
  const port = wanted && wanted !== "0" ? Number(wanted) : await freePort();

  const scratch = await mkdtemp(join(await realpath(tmpdir()), "orderguard-bridge-"));
  let r5 = null;
  let http = null;
  let closing = false;
  const shutdown = async (code) => {
    if (closing) return; closing = true;
    try { http?.close(); } catch {}
    try { core?.close(); } catch {}
    if (r5 && r5.exitCode === null) {
      r5.kill("SIGTERM");
      await new Promise((ok) => { const t = setTimeout(() => { r5.kill("SIGKILL"); ok(); }, 2000); r5.once("exit", () => { clearTimeout(t); ok(); }); });
    }
    await rm(scratch, { recursive: true, force: true });
    process.exit(code);
  };
  process.on("SIGTERM", () => shutdown(0));
  process.on("SIGINT", () => shutdown(0));

  try {
    // ---- boot r5 on a free loopback port, isolated ledger ----
    const r5Port = await freePort();
    const r5Base = `http://127.0.0.1:${r5Port}`;
    const env = {
      PATH: process.env.PATH || "/usr/bin:/bin", TMPDIR: process.env.TMPDIR || "/tmp",
      ORDERGUARD_DISABLE_LOCAL_ENV: "1", ORDERGUARD_HOST: "127.0.0.1", ORDERGUARD_PORT: String(r5Port),
      ORDERGUARD_LEDGER_DB: join(scratch, "r5-paper-ledger.sqlite"),
      ORDERGUARD_FUTU_SIMULATE_ENABLED: "0", ORDERGUARD_SECOND_LOCK_ENABLED: "0",
      ORDERGUARD_HUMAN_MANDATE_TTL_MS: String(anchorTtlMs),
    };
    r5 = spawn(process.execPath, ["--import", join(root, "node_modules/tsx/dist/loader.mjs"), join(root, "receiver/r5/server.ts")], { cwd: scratch, env, stdio: ["ignore", "pipe", "ignore"] });
    const lines = createInterface({ input: r5.stdout })[Symbol.asyncIterator]();
    let pairing = null;
    const reader = (async () => { for await (const line of { [Symbol.asyncIterator]: () => lines }) { const m = line.match(/pairing code: ([A-Za-z0-9_-]+)/i); if (m && !pairing) pairing = m[1]; } })();
    void reader;
    for (let i = 0; ; i += 1) {
      if (r5.exitCode !== null) throw new Error("r5 exited during boot");
      if (i > 300) throw new Error("r5 health timeout");
      try { const h = await fetch(r5Base + "/api/health", { signal: AbortSignal.timeout(1000) }); if ((await h.json()).status === "ready") break; } catch {}
      await new Promise((ok) => setTimeout(ok, 100));
    }
    for (let i = 0; !pairing && i < 100; i += 1) await new Promise((ok) => setTimeout(ok, 100));
    if (!pairing) throw new Error("r5 pairing code not seen");

    // ---- synthetic owner passkey, registered with r5 (and later with the core) ----
    const passkey = virtualPasskey();
    const r5Origin = new URL(r5Base).origin;
    const setup = await jsonFetch(r5Base, "/api/owner-passkey/setup/options", { bootstrapCode: pairing });
    await jsonFetch(r5Base, "/api/owner-passkey/setup/verify", { bootstrapCode: pairing, challengeId: setup.challengeId, response: registrationResponse(passkey, setup.options.challenge, r5Origin) });

    // ---- authorise a human mandate in r5 (anchor symbol AAPL, 1 share: r5 mandates are single-symbol) ----
    // The same ceremony runs at boot and for every renewal.
    const authorizeAnchor = async () => {
      const preview = await jsonFetch(r5Base, "/api/chat", { prompt: "Buy 1 AAPL share as a market order during regular hours for day.", provider: "local", verifier: "none" });
      if (preview.run?.outcome !== "ready") throw new Error("r5 did not prepare the mandate preview");
      const opts = await jsonFetch(r5Base, "/api/human-mandate/authorize/options", { runId: preview.run.id });
      const authorized = await jsonFetch(r5Base, "/api/human-mandate/authorize/verify", { challengeId: opts.challengeId, response: authenticationResponse(passkey, opts.options.challenge, r5Origin) });
      const id = authorized.mandate?.mandateId;
      if (typeof id !== "string") throw new Error("r5 produced no mandate");
      return { id, expiresAt: Number(authorized.mandate.expiresAt), createdAt: Number(authorized.mandate.createdAt) };
    };
    const first = await authorizeAnchor();
    const mandateId = first.id;
    const anchors = [first]; // every anchor ever authorised; /revoke revokes them all
    let current = first;
    let renewals = 0;
    let renewalError = null;
    let renewing = null;
    let timer = null;

    const anchorActiveAt = async (id) => {
      const status = await jsonFetch(r5Base, "/api/human-mandate/status");
      return status.mandates?.some((m) => m.mandateId === id && m.active === true && m.revocationPending !== true) === true;
    };
    const r5MandateActive = () => anchorActiveAt(current.id);
    const parentAuthorityActive = async () => await parentUnrevoked() && await r5MandateActive();

    const schedule = () => {
      clearTimeout(timer);
      if (renewFrac === null || closing || core?.revoked || Date.now() >= mandateExpiresMs) return;
      const at = current.createdAt + Math.round((current.expiresAt - current.createdAt) * renewFrac);
      timer = setTimeout(async () => {
        if (await parentUnrevoked()) renew().catch(() => { schedule(); });
      }, Math.max(250, at - Date.now()));
      timer.unref?.();
    };
    // Single-flight renewal. Never starts after revocation; never starts once the core mandate itself has expired.
    const renew = () => {
      if (core.revoked) return Promise.reject(new Error("revoked"));
      if (Date.now() >= mandateExpiresMs) return Promise.reject(new Error("core mandate expired"));
      renewing ??= (async () => {
        try {
          const next = await authorizeAnchor();
          anchors.push(next);
          current = next; renewals += 1; renewalError = null;
        } catch (e) {
          renewalError = String(e?.message || e).slice(0, 120);
          throw e;
        } finally { renewing = null; schedule(); }
      })();
      return renewing;
    };
    // Gate for /propose and /approve: renew on demand if the anchor lapsed. Returns null when fine or a denial reason.
    const ensureAnchor = async () => {
      if (core.revoked || Date.now() >= mandateExpiresMs || !await parentUnrevoked()) return null; // the core denies these with its own reason
      if (await r5MandateActive().catch(() => false)) return null;
      try { await renew(); } catch { /* fall through to the check below */ }
      if (core.revoked) return null;
      return (await r5MandateActive().catch(() => false)) ? null : `anchor renewal failed${renewalError ? ": " + renewalError : ""}`;
    };
    const denyAnchor = (detail) => ({ decision: "denied", reason: "anchor_unavailable", reasons: ["anchor_unavailable"], detail, ledgerEffect: false });

    // ---- the receiver core, with the same owner passkey registered for step-up approval ----
    const coreOrigin = `http://127.0.0.1:${port}`;
    core = new ReceiverCore({
      ledgerPath: join(scratch, "receiver-core.sqlite"), mandateId, mandate, signedPolicy,
      authority: { isActive: parentAuthorityActive }, webauthn: { origin: coreOrigin, rpId: "127.0.0.1" },
    });
    await core.registerOwnerPasskey(registrationResponse(passkey, core.passkeyRegistrationChallenge(), coreOrigin));

    schedule();

    // ---- HTTP API (loopback only) ----
    const send = (res, code, body) => { const text = JSON.stringify(body); res.writeHead(code, { "content-type": "application/json", "content-length": Buffer.byteLength(text) }); res.end(text); };
    const readBody = (req) => new Promise((ok, bad) => {
      const chunks = []; let n = 0;
      req.on("data", (c) => { n += c.length; if (n > 65536) { bad(new Error("body too large")); req.destroy(); } else chunks.push(c); });
      req.on("end", () => { try { ok(chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {}); } catch { bad(new Error("invalid JSON")); } });
      req.on("error", bad);
    });
    let revokeInFlight = null;
    http = createHttpServer(async (req, res) => {
      const host = (req.headers.host || "").toLowerCase();
      if (host !== `127.0.0.1:${port}` && host !== `localhost:${port}`) return send(res, 403, { error: "loopback only" });
      const path = new URL(req.url || "/", "http://x").pathname;
      try {
        if (req.method === "GET" && path === "/health") return send(res, 200, { status: "ready", mandateId, revoked: core.revoked, issuerMandateActive: await parentAuthorityActive().catch(() => false), anchorId: current.id, anchorExpiresAt: new Date(current.expiresAt).toISOString(), anchorRenewals: renewals, anchorRenewalError: renewalError });
        if (req.method === "GET" && path === "/snapshot") { const s = core.snapshot(); return send(res, 200, { orders: s.orders, ledgerIntegrity: s.ledgerIntegrity, revoked: s.revoked, usedNotionalUsd: s.usedNotionalUsd }); }
        if (signedPolicy && req.method === "GET" && path === "/policy") return send(res, 200, core.policy());
        if (signedPolicy && req.method === "POST" && path === "/policy/activate") {
          const proof = await readBody(req);
          const lapsed = await ensureAnchor();
          if (lapsed) return send(res, 409, { error: lapsed });
          return send(res, 200, await core.activatePolicy(proof));
        }
        if (req.method === "POST" && path === "/propose") {
          const b = await readBody(req);
          const lapsed = await ensureAnchor();
          if (lapsed) return send(res, 200, denyAnchor(lapsed));
          const d = await core.propose({ symbol: b.symbol, side: b.side, quantity: b.quantity, limitPrice: b.limitPrice, clientOrderId: b.clientOrderId });
          return send(res, 200, d);
        }
        if (req.method === "POST" && path === "/revoke") {
          // Local, durable and synchronous first: nothing can commit after this line. Then the owner-passkey revocation at r5.
          core.revoke();
          clearTimeout(timer);
          revokeInFlight ??= (async () => {
            // Revocation is final: let any renewal already in flight land, then revoke every anchor ever issued.
            await renewing?.catch(() => {});
            for (const a of anchors) {
              try {
                const o = await jsonFetch(r5Base, "/api/human-mandate/revoke/options", { mandateId: a.id });
                await jsonFetch(r5Base, "/api/human-mandate/revoke/verify", { mandateId: a.id, challengeId: o.challengeId, response: authenticationResponse(passkey, o.options.challenge, r5Origin) });
              } catch { /* an anchor that already expired cannot be revoked; it is inactive anyway */ }
            }
          })();
          await revokeInFlight;
          return send(res, 200, { revoked: true });
        }
        if (req.method === "POST" && path === "/approve") {
          const b = await readBody(req);
          if (typeof b.orderId !== "string") return send(res, 400, { error: "orderId required" });
          const lapsed = await ensureAnchor();
          if (lapsed) return send(res, 200, denyAnchor(lapsed));
          let ch;
          try { ch = core.beginApproval(b.orderId, b.authorization); } catch (e) { return send(res, 200, { decision: "denied", reason: e.code || "not_held", reasons: [e.code || "not_held"], ledgerEffect: false }); }
          return send(res, 200, await core.approve(b.orderId, authenticationResponse(passkey, ch.challenge, coreOrigin), b.authorization));
        }
        return send(res, 404, { error: "not found" });
      } catch (e) {
        return send(res, 400, { error: String(e?.message || e).slice(0, 200) });
      }
    });
    await new Promise((ok, bad) => { http.once("error", bad); http.listen(port, "127.0.0.1", ok); });
    process.stdout.write(`READY ${port}\n`);
  } catch (error) {
    process.stderr.write(`bridge failed: ${error?.message || error}\n`);
    await shutdown(1);
  }
}

main().catch((e) => { process.stderr.write(`bridge failed: ${e?.message || e}\n`); process.exit(1); });
