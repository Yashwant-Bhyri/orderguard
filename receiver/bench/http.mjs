#!/usr/bin/env node
// HTTP benchmark of the real receiver bridge (receiver/bridge/serve.mjs) on loopback: boots the bridge with a demo mandate and an
// ephemeral ledger (it also boots r5, the owner-passkey authority, which the bridge asks whether the mandate is still active on every
// proposal), then sends N proposals with C in flight, re-sends some keys as retries, and reads /snapshot for the ledger's own integrity
// check. Writes a JSON result. If this machine (or a sandbox) does not allow binding a loopback port, it writes a skip record with
// the reason instead of failing.
//
//   node receiver/bench/http.mjs --spec SPEC.json --out OUT.json --requests N --concurrency C
// SPEC: {"mandate": {...bridge mandate JSON with referencePrices...}, "orders": [{symbol, side, quantity, limitPrice, clientOrderId}...]}

import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const arg = (n, d) => { const i = process.argv.indexOf(n); return i >= 0 ? process.argv[i + 1] : d; };
const out = arg("--out");
const requests = Number(arg("--requests", "2000"));
const concurrency = Number(arg("--concurrency", "32"));
const COMMAND = "npm run bench -- http   (or: .venv/bin/og-bench http --profile quick)";

async function canBind() {
  const s = createServer();
  try {
    await new Promise((ok, bad) => { s.once("error", bad); s.listen(0, "127.0.0.1", ok); });
    await new Promise((ok) => s.close(ok));
    return null;
  } catch (e) {
    return `${e.code || "error"}: binding a loopback port is not permitted here (${String(e.message).slice(0, 80)})`;
  }
}

function pct(ns) {
  if (!ns.length) return { n: 0 };
  const a = Float64Array.from(ns).sort();
  const q = (p) => { const r = (p / 100) * (a.length - 1); const lo = Math.floor(r), hi = Math.ceil(r); return (a[lo] + (a[hi] - a[lo]) * (r - lo)) / 1000; };
  const r2 = (v) => Math.round(v * 100) / 100;
  return { n: a.length, p50: r2(q(50)), p90: r2(q(90)), p99: r2(q(99)), p999: r2(q(99.9)), max: r2(a[a.length - 1] / 1000), mean: r2(a.reduce((s, v) => s + v, 0) / a.length / 1000) };
}

async function main() {
  const reason = await canBind();
  if (reason) {
    await writeFile(out, JSON.stringify({ skipped: true, reason, command: COMMAND, node: process.version }));
    console.log(`http bench skipped: ${reason}`);
    return;
  }
  const spec = JSON.parse(await readFile(arg("--spec"), "utf8"));
  const scratch = await mkdtemp(join(tmpdir(), "og-bench-http-"));
  const mandatePath = join(scratch, "mandate.json");
  await writeFile(mandatePath, JSON.stringify(spec.mandate));
  const child = spawn(process.execPath, [join(root, "receiver/bridge/serve.mjs"), "--mandate", mandatePath, "--ledger", ":ephemeral"], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
  let stderr = "";
  child.stderr.on("data", (b) => { stderr += b.toString(); });
  const port = await new Promise((ok, bad) => {
    const t = setTimeout(() => bad(new Error("bridge did not become ready in 60 s: " + stderr.slice(-300))), 60_000);
    createInterface({ input: child.stdout }).on("line", (line) => { const m = line.match(/^READY (\d+)/); if (m) { clearTimeout(t); ok(Number(m[1])); } });
    child.once("exit", (code) => { clearTimeout(t); bad(new Error(`bridge exited (${code}): ${stderr.slice(-300)}`)); });
  });
  const base = `http://127.0.0.1:${port}`;
  const post = async (path, body) => {
    const t0 = process.hrtime.bigint();
    const res = await fetch(base + path, { method: "POST", headers: { "content-type": "application/json", origin: base }, body: JSON.stringify(body) });
    const json = await res.json();
    return [Number(process.hrtime.bigint() - t0), res.status, json];
  };
  const orders = [];
  for (let i = 0; i < requests; i += 1) {
    if (i % 10 === 9) { orders.push({ ...orders[i - 5], retry: true }); continue; }      // one in ten is a retry of an earlier key
    const o = spec.orders[i % spec.orders.length];
    orders.push({ ...o, clientOrderId: `${o.clientOrderId}-h${i}` });
  }
  const lat = [], latRetry = [];
  const counts = {};
  let next = 0, errors = 0;
  const t0 = process.hrtime.bigint();
  await Promise.all(Array.from({ length: concurrency }, async () => {
    while (next < orders.length) {
      const o = orders[next++];
      try {
        const [ns, status, body] = await post("/propose", { symbol: o.symbol, side: o.side, quantity: o.quantity, limitPrice: o.limitPrice, clientOrderId: o.clientOrderId });
        (o.retry ? latRetry : lat).push(ns);
        const k = status === 200 ? body.decision + (body.replay ? "+replay" : "") : `http_${status}`;
        counts[k] = (counts[k] || 0) + 1;
      } catch { errors += 1; }
    }
  }));
  const wall = Number(process.hrtime.bigint() - t0) / 1e9;
  const snap = await (await fetch(base + "/snapshot", { headers: { origin: base } })).json();
  child.kill("SIGTERM");
  await new Promise((ok) => { const t = setTimeout(ok, 5000); child.once("exit", () => { clearTimeout(t); ok(); }); });
  await rm(scratch, { recursive: true, force: true });
  const perKey = new Map();
  for (const o of snap.orders) perKey.set(o.clientOrderId, (perKey.get(o.clientOrderId) || 0) + 1);
  const doubles = [...perKey.values()].filter((n) => n > 1).length;
  const result = { skipped: false, node: process.version, requests, concurrency, wall_s: Math.round(wall * 1000) / 1000, requests_per_s: Math.round(requests / wall),
    latency_us: pct(lat), retry_latency_us: pct(latRetry), counts, errors, ledger_integrity: snap.ledgerIntegrity, ledger_orders: snap.orders.length,
    double_executions: doubles, used_notional_usd: snap.usedNotionalUsd, daily_cap_usd: spec.mandate.maxDailyNotionalUsd,
    within_daily_cap: snap.usedNotionalUsd <= spec.mandate.maxDailyNotionalUsd + 1e-9,
    note: "every proposal crosses loopback HTTP to the bridge, which asks r5 (another loopback hop) whether the mandate is active, then commits in SQLite (WAL, synchronous=FULL)" };
  await writeFile(out, JSON.stringify(result));
  console.log(`http bench: ${result.requests_per_s} req/s, p50 ${result.latency_us.p50} us, p99 ${result.latency_us.p99} us, integrity ${result.ledger_integrity}`);
}

main().catch(async (e) => {
  if (out) await writeFile(out, JSON.stringify({ skipped: true, reason: "bridge benchmark failed: " + String(e.message || e).slice(0, 300), command: COMMAND }));
  console.error(e.message || e);
  process.exit(1);
});
