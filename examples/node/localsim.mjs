// Starts a throwaway LocalSim paper receiver on a loopback port and authorizes one mandate with a SYNTHETIC passkey, so
// examples can talk to a receiver without a real owner ceremony. Not for production: the "owner" is a script.
import { spawn } from "node:child_process";
import { mkdtemp, realpath, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { virtualPasskey, registrationResponse, authenticationResponse } from "../../receiver/bridge/synthetic-passkey.mjs";
import { requireEnvironment } from "../../receiver/bridge/preflight.mjs";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

async function freePort() {
  const server = createServer();
  await new Promise((ok, bad) => { server.once("error", bad); server.listen(0, "127.0.0.1", ok); });
  const { port } = server.address();
  await new Promise((ok) => server.close(ok));
  return port;
}

async function post(base, path, body) {
  const response = await fetch(base + path, {
    method: "POST",
    headers: { origin: new URL(base).origin, "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${path} answered HTTP ${response.status}: ${payload.error ?? "receiver error"}`);
  return payload;
}

/** Resolves to { base, mandateId, stop() }. Call stop() when done (it also removes the temporary ledger). */
export async function startLocalSim() {
  requireEnvironment(ROOT);
  const scratch = await mkdtemp(join(await realpath(tmpdir()), "orderguard-example-"));
  let port;
  try {
    port = await freePort();
  } catch (error) {
    await rm(scratch, { recursive: true, force: true });
    throw new Error(error?.code === "EPERM" || error?.code === "EACCES"
      ? "This environment does not allow listening on a local port (EPERM). Run outside the sandbox, or allow local binding."
      : `Could not find a free local port (${error?.code ?? error}).`);
  }
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, ["--no-warnings", "--import", join(ROOT, "node_modules/tsx/dist/loader.mjs"), join(ROOT, "receiver/r5/server.ts")], {
    cwd: scratch,
    env: {
      PATH: process.env.PATH || "/usr/bin:/bin", TMPDIR: process.env.TMPDIR || "/tmp",
      ORDERGUARD_DISABLE_LOCAL_ENV: "1", ORDERGUARD_HOST: "127.0.0.1", ORDERGUARD_PORT: String(port),
      ORDERGUARD_LEDGER_DB: join(scratch, "paper-ledger.sqlite"), ORDERGUARD_SCENARIO_CARDS_DIR: join(ROOT, "receiver/r5/scenario_cards"),
      ORDERGUARD_FUTU_SIMULATE_ENABLED: "0", ORDERGUARD_SECOND_LOCK_ENABLED: "0",
    },
    stdio: ["ignore", "pipe", "ignore"],
  });
  let spawnError = null;
  child.once("error", (error) => { spawnError = error; });
  let pairing = null;
  createInterface({ input: child.stdout }).on("line", (line) => { pairing ??= line.match(/pairing code: ([A-Za-z0-9_-]+)/i)?.[1] ?? null; });
  const stop = async () => {
    if (child.exitCode === null && child.signalCode === null) {
      await new Promise((ok) => {
        const timer = setTimeout(() => { child.kill("SIGKILL"); ok(); }, 2_000);
        child.once("exit", () => { clearTimeout(timer); ok(); });
        child.kill("SIGTERM");
      });
    }
    await rm(scratch, { recursive: true, force: true });
  };
  try {
    for (let i = 0; ; i += 1) {
      if (spawnError || child.exitCode !== null) throw new Error("The receiver process exited while starting. Run `npm ci` and try again; if it persists, run `npm run quickstart` and read its error.");
      if (i > 300) throw new Error("The receiver did not become healthy within 30 s.");
      try {
        const health = await fetch(base + "/api/health", { signal: AbortSignal.timeout(1_000) });
        if ((await health.json()).status === "ready") break;
      } catch { /* not listening yet */ }
      await new Promise((ok) => setTimeout(ok, 100));
    }
    for (let i = 0; !pairing && i < 100; i += 1) await new Promise((ok) => setTimeout(ok, 100));
    if (!pairing) throw new Error("The receiver printed no pairing code.");
    const passkey = virtualPasskey();
    const setup = await post(base, "/api/owner-passkey/setup/options", { bootstrapCode: pairing });
    await post(base, "/api/owner-passkey/setup/verify", {
      bootstrapCode: pairing, challengeId: setup.challengeId, response: registrationResponse(passkey, setup.options.challenge, base),
    });
    // The owner's mandate covers exactly what this preview says: buy AAPL, market order, regular hours, day.
    const preview = await post(base, "/api/chat", { prompt: "Buy 1 AAPL share as a market order during regular hours for day.", provider: "local", verifier: "none" });
    if (preview.run?.outcome !== "ready") throw new Error("The receiver did not prepare the mandate preview.");
    const options = await post(base, "/api/human-mandate/authorize/options", { runId: preview.run.id });
    const authorized = await post(base, "/api/human-mandate/authorize/verify", {
      challengeId: options.challengeId, response: authenticationResponse(passkey, options.options.challenge, base),
    });
    const mandateId = authorized.mandate?.mandateId;
    if (typeof mandateId !== "string") throw new Error("The receiver did not issue a mandate.");
    return { base, mandateId, stop };
  } catch (error) {
    await stop();
    throw error;
  }
}
