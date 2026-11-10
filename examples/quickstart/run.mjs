#!/usr/bin/env node
import { createHash, generateKeyPairSync, randomBytes, sign } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdtemp, rm, access, realpath } from "node:fs/promises";
import { tmpdir } from "node:os";
import { constants } from "node:fs";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";
import { performance } from "node:perf_hooks";
import { formatQuickstartFailure, runWithCleanup, trackChildSpawn } from "./cleanup.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const b64url = (value) => Buffer.from(value).toString("base64url");

function cborHead(major, value) {
  if (value < 24) return Buffer.from([(major << 5) | value]);
  if (value <= 0xff) return Buffer.from([(major << 5) | 24, value]);
  if (value <= 0xffff) return Buffer.from([(major << 5) | 25, value >> 8, value & 0xff]);
  return Buffer.from([(major << 5) | 26, value >>> 24, (value >>> 16) & 0xff, (value >>> 8) & 0xff, value & 0xff]);
}

function cbor(value) {
  if (typeof value === "number") return cborHead(value >= 0 ? 0 : 1, value >= 0 ? value : -1 - value);
  if (typeof value === "string") { const bytes = Buffer.from(value); return Buffer.concat([cborHead(3, bytes.length), bytes]); }
  if (Buffer.isBuffer(value)) return Buffer.concat([cborHead(2, value.length), value]);
  if (Array.isArray(value)) return Buffer.concat([cborHead(4, value.length), ...value.map(cbor)]);
  if (value instanceof Map) {
    return Buffer.concat([cborHead(5, value.size), ...[...value].flatMap(([key, item]) => [cbor(key), cbor(item)])]);
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value);
    return Buffer.concat([cborHead(5, entries.length), ...entries.flatMap(([key, item]) => [cbor(key), cbor(item)])]);
  }
  throw new TypeError("unsupported synthetic WebAuthn value");
}

function virtualPasskey() {
  const pair = generateKeyPairSync("ec", { namedCurve: "prime256v1" });
  return { credentialId: randomBytes(32).toString("base64url"), publicKey: pair.publicKey, signingHandle: pair.privateKey, counter: 0 };
}

function registrationResponse(passkey, challenge, origin) {
  const jwk = passkey.publicKey.export({ format: "jwk" });
  const credentialId = Buffer.from(passkey.credentialId, "base64url");
  const coseKey = cbor(new Map([[1, 2], [3, -7], [-1, 1], [-2, Buffer.from(jwk.x, "base64url")], [-3, Buffer.from(jwk.y, "base64url")]]));
  const rpIdHash = createHash("sha256").update(new URL(origin).hostname).digest();
  const idLength = Buffer.alloc(2); idLength.writeUInt16BE(credentialId.length);
  const authData = Buffer.concat([rpIdHash, Buffer.from([0x45]), Buffer.alloc(4), Buffer.alloc(16), idLength, credentialId, coseKey]);
  return {
    id: passkey.credentialId, rawId: passkey.credentialId, type: "public-key", clientExtensionResults: {},
    response: {
      clientDataJSON: b64url(JSON.stringify({ type: "webauthn.create", challenge, origin, crossOrigin: false })),
      attestationObject: b64url(cbor({ fmt: "none", attStmt: {}, authData })), transports: ["internal"],
    },
  };
}

function authenticationResponse(passkey, challenge, origin) {
  passkey.counter += 1;
  const authData = Buffer.concat([
    createHash("sha256").update(new URL(origin).hostname).digest(),
    Buffer.from([0x05, 0, 0, 0, passkey.counter & 0xff]),
  ]);
  const clientDataJSON = Buffer.from(JSON.stringify({ type: "webauthn.get", challenge, origin, crossOrigin: false }));
  const signedData = Buffer.concat([authData, createHash("sha256").update(clientDataJSON).digest()]);
  return {
    id: passkey.credentialId, rawId: passkey.credentialId, type: "public-key", clientExtensionResults: {},
    response: { clientDataJSON: b64url(clientDataJSON), authenticatorData: b64url(authData), signature: b64url(sign("sha256", signedData, passkey.signingHandle)) },
  };
}

async function findRoot() {
  let dir = resolve(here);
  for (let i = 0; i < 7; i += 1) {
    const serverTypeScript = join(dir, "server.ts");
    const receiverTypeScript = join(dir, "receiver", "server.ts");
    const receiverR5TypeScript = join(dir, "receiver", "r5", "server.ts");
    const serverJavaScript = join(dir, "server.js");
    const receiverJavaScript = join(dir, "receiver", "server.js");
    const receiverDistJavaScript = join(dir, "receiver", "dist", "server.js");
    const receiverR5DistJavaScript = join(dir, "receiver", "r5", "dist", "server.js");
    const sdkCandidates = [join(dir, "packages/sdk", "src/index.js"), join(dir, "integrate/packages/sdk", "src/index.js")];
    const mcpCandidates = [join(dir, "packages/mcp-server", "bin/orderguard-mcp.js"), join(dir, "integrate/packages/mcp-server", "bin/orderguard-mcp.js")];
    for (const entry of [serverTypeScript, receiverTypeScript, receiverR5TypeScript, serverJavaScript, receiverJavaScript, receiverDistJavaScript, receiverR5DistJavaScript]) {
      try {
        await access(entry, constants.R_OK);
        const sdk = await firstReadable(sdkCandidates);
        const mcp = await firstReadable(mcpCandidates);
        if (sdk && mcp) return { root: dir, entry, sdk, mcp };
      } catch {}
    }
    dir = dirname(dir);
  }
  throw new Error("Quickstart files were not found. Run from the OrderGuard source or release root after installing dependencies.");
}

async function firstReadable(paths) {
  for (const path of paths) { try { await access(path, constants.R_OK); return path; } catch {} }
  return null;
}

async function unusedPort() {
  const server = createServer();
  await new Promise((resolvePromise, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolvePromise); });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("could not allocate a loopback port");
  const port = address.port;
  await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()));
  return port;
}

async function request(base, path, body) {
  const response = await fetch(base + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { origin: new URL(base).origin, ...(body === undefined ? {} : { "content-type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${path} HTTP ${response.status}: ${payload.error ?? "receiver error"}`);
  return payload;
}

async function requestStatus(base, path, body) {
  const response = await fetch(base + path, { method: "POST", headers: { origin: new URL(base).origin, "content-type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(15_000) });
  return { status: response.status, body: await response.json() };
}

async function boundedNext(iterator, timeoutMs, label) {
  let timer;
  try {
    return await Promise.race([
      iterator.next(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(label)), timeoutMs); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function waitForHealth(base, child, timeoutMs = 30_000) {
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error("receiver exited before health check passed");
    try {
      const response = await fetch(base + "/api/health", { signal: AbortSignal.timeout(1_000) });
      const payload = await response.json();
      if (response.ok && payload.status === "ready") return;
    } catch {}
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100));
  }
  throw new Error("receiver health check timed out");
}

async function startMesh(root, entry, ledgerPath, runDir) {
  const port = await unusedPort();
  const base = `http://127.0.0.1:${port}`;
  const env = {
    PATH: process.env.PATH || "/usr/bin:/bin",
    TMPDIR: process.env.TMPDIR || "/tmp",
    ORDERGUARD_DISABLE_LOCAL_ENV: "1",
    ORDERGUARD_HOST: "127.0.0.1",
    ORDERGUARD_PORT: String(port),
    ORDERGUARD_LEDGER_DB: ledgerPath,
    ORDERGUARD_SCENARIO_CARDS_DIR: join(root, "receiver/r5/scenario_cards"),
    [["ORDERGUARD_", "FUTU_SIMULATE_ENABLED"].join("")]: "0",
    [["ORDERGUARD_", "SECOND_LOCK_ENABLED"].join("")]: "0",
  };
  const tsLoader = join(root, "node_modules/tsx/dist/loader.mjs");
  const args = entry.endsWith(".ts") ? ["--import", tsLoader, entry] : [entry];
  const child = spawn(process.execPath, args, { cwd: runDir, env, stdio: ["ignore", "pipe", "ignore"] });
  const spawnState = trackChildSpawn(child);
  const lines = createInterface({ input: child.stdout });
  const iterator = lines[Symbol.asyncIterator]();
  return {
    child, base, spawnState,
    async waitUntilHealthy() { await spawnState.race(waitForHealth(base, child)); },
    async lineMatching(pattern, timeoutMs = 10_000) {
      const deadline = performance.now() + timeoutMs;
      while (performance.now() < deadline) {
        const remaining = Math.max(1, Math.ceil(deadline - performance.now()));
        const result = await spawnState.race(boundedNext(iterator, remaining, "receiver output timeout"));
        if (result.done) throw new Error("receiver exited before expected output");
        const match = result.value.match(pattern);
        if (match) return match[1] ?? result.value;
      }
      throw new Error("receiver output timeout");
    },
  };
}

function signalAndWait(child, signal, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true);
  return new Promise((resolvePromise) => {
    let timer;
    const finish = (exited) => {
      clearTimeout(timer);
      child.removeListener("exit", onExit);
      resolvePromise(exited);
    };
    const onExit = () => finish(true);
    child.once("exit", onExit);
    timer = setTimeout(() => finish(child.exitCode !== null || child.signalCode !== null), timeoutMs);
    if (child.exitCode === null && child.signalCode === null) child.kill(signal);
  });
}

async function stop(child, spawnState) {
  if (!child || spawnState?.error || child.exitCode !== null || child.signalCode !== null) return;
  if (await signalAndWait(child, "SIGTERM", 2_000)) return;
  if (!(await signalAndWait(child, "SIGKILL", 1_000))) {
    throw new Error("receiver process did not exit after SIGKILL");
  }
}

class McpProcess {
  constructor(script, base, cwd) {
    this.child = spawn(process.execPath, [script], { cwd, env: { PATH: process.env.PATH || "/usr/bin:/bin", ORDERGUARD_URL: base }, stdio: ["pipe", "pipe", "ignore"] });
    this.spawnState = trackChildSpawn(this.child);
    this.lines = createInterface({ input: this.child.stdout });
    this.iterator = this.lines[Symbol.asyncIterator]();
    this.id = 0;
  }
  async call(method, params = {}) {
    const id = ++this.id;
    this.child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    const next = await this.spawnState.race(boundedNext(this.iterator, 10_000, "MCP response timeout"));
    if (next.done) throw new Error("MCP server ended its output");
    const frame = JSON.parse(next.value);
    if (frame.id !== id || frame.error) throw new Error("MCP JSON-RPC call failed");
    return frame.result;
  }
  async tool(name, args = {}) {
    const result = await this.call("tools/call", { name, arguments: args });
    return JSON.parse(result.content[0].text);
  }
}

async function main() {
  const { root, entry, sdk, mcp: mcpScript } = await findRoot();
  const { OrderGuardClient } = await import(sdk);
  const scratch = await mkdtemp(join(await realpath(tmpdir()), "orderguard-quickstart-"));
  let mesh = null;
  let mcp = null;
  const output = await runWithCleanup(async () => {
    mesh = await startMesh(root, entry, join(scratch, "paper-ledger.sqlite"), scratch);
    await mesh.waitUntilHealthy();
    const pairingCode = await mesh.lineMatching(/pairing code: ([A-Za-z0-9_-]+)/i);
    const passkey = virtualPasskey();
    const setup = await request(mesh.base, "/api/owner-passkey/" + "setup/options", { bootstrapCode: pairingCode });
    const origin = new URL(mesh.base).origin;
    await request(mesh.base, "/api/owner-passkey/" + "setup/verify", {
      bootstrapCode: pairingCode, challengeId: setup.challengeId,
      response: registrationResponse(passkey, setup.options.challenge, origin),
    });
    const preview = await request(mesh.base, "/api/chat", { prompt: "Buy 1 AAPL share as a market order during regular hours for day.", provider: "local", verifier: "none" });
    if (preview.run?.outcome !== "ready" || preview.run?.intent?.symbol !== "AAPL") throw new Error("synthetic AAPL preview was not ready");
    const options = await request(mesh.base, "/api/human-mandate/" + "authorize/options", { runId: preview.run.id });
    const authorized = await request(mesh.base, "/api/human-mandate/" + "authorize/verify", {
      challengeId: options.challengeId,
      response: authenticationResponse(passkey, options.options.challenge, origin),
    });
    const mandateId = authorized.mandate?.mandateId;
    if (typeof mandateId !== "string") throw new Error("synthetic signer did not produce a mandate");

    const sdk = new OrderGuardClient({ baseUrl: mesh.base });
    const benign = await sdk.proposeOrder({ mandateId, symbol: "AAPL", side: "buy", quantity: 1, orderType: "market", session: "regular", timeInForce: "day" });
    if (benign.state !== "filled") throw new Error("benign paper order did not fill");
    mcp = new McpProcess(mcpScript, mesh.base, root);
    const initialized = await mcp.call("initialize", { protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "orderguard-quickstart", version: "0.1.0" } });
    const tools = await mcp.call("tools/list");
    const expectedTools = ["get_mandate", "propose_order", "order_status", "cancel"];
    if (initialized.protocolVersion !== "2025-11-25" || JSON.stringify(tools.tools.map((tool) => tool.name)) !== JSON.stringify(expectedTools)) throw new Error("MCP startup or tool list failed");
    const active = await mcp.tool("get_mandate");
    if (!active.mandates?.some((row) => row.mandateId === mandateId && row.active === true)) throw new Error("MCP did not observe the active mandate");
    const beforeAttack = await request(mesh.base, "/api/snapshot");
    const attack = await mcp.tool("propose_order", {
      mandate_id: mandateId, symbol: "AAPL", side: "sell", quantity: 1,
      order_type: "market", session: "regular", time_in_force: "day",
    });
    const afterAttack = await request(mesh.base, "/api/snapshot");
    const noAttackEffect = afterAttack.orders?.length === beforeAttack.orders?.length;
    const exactDenial = attack.state === "denied" && attack.statusCode === 409 && String(attack.reason).includes("mandate_action_out_of_scope");
    const integrity = afterAttack.paperAuditIntegrity?.verified === true;
    if (!exactDenial || !noAttackEffect || !integrity) throw new Error("receiver attack denial or final ledger check failed");
    const status = await sdk.orderStatus(benign.orderId);
    return {
      state: "pass", signer: "synthetic signer, passkey step-up pending", model: "none",
      benign: { orderId: benign.orderId, state: benign.state, receiverStatus: status.status },
      attack: { state: attack.state, receiverHttpStatus: attack.statusCode, reason: attack.reason, noLedgerEffect: noAttackEffect },
      mcpTools: expectedTools, ledgerIntegrityVerified: integrity,
      boundary: "loopback LocalSim paper ledger only; no API key, brokerage account, Futu, or Binance connection",
    };
  }, [
    () => stop(mcp?.child ?? null, mcp?.spawnState),
    () => stop(mesh?.child ?? null, mesh?.spawnState),
    () => rm(scratch, { recursive: true, force: true }),
  ]);
  console.log(JSON.stringify(output));
}

main().catch((error) => {
  console.error(formatQuickstartFailure(error));
  process.exitCode = 1;
});
