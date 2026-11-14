// Bridge start-up and ledger-tool tests that need no network port: every refusal happens before the bridge binds anything.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Readable } from "node:stream";
import { register } from "tsx/esm/api";
import { DatabaseSync } from "node:sqlite";
import { HttpError, failure, readJsonBody, scrub } from "../bridge/http-util.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const dir = mkdtempSync(join(tmpdir(), "og-bridge-ledger-"));
after(() => rmSync(dir, { recursive: true, force: true }));
register();
const { ReceiverCore } = await import(pathToFileURL(join(root, "receiver/core/receiver-core.ts")).href);
const files = await import(pathToFileURL(join(root, "receiver/core/ledger-files.ts")).href);

const mandate = { symbols: ["AAPL"], sides: ["buy"], maxOrderNotionalUsd: 10000, maxDailyNotionalUsd: 20000, priceBandPct: 5,
  expiresAt: new Date(Date.now() + 3_600_000).toISOString(), referencePrices: { AAPL: 222.7 } };
const mandateFile = join(dir, "mandate.json");
writeFileSync(mandateFile, JSON.stringify(mandate));

async function seededLedger(name) {
  const path = join(dir, name);
  const core = new ReceiverCore({ ledgerPath: path, mandateId: files.demoMandateId(mandate), mandate });
  await core.propose({ symbol: "AAPL", side: "buy", quantity: 5, limitPrice: 222.7, clientOrderId: "seed-1" });
  core.close();
  return path;
}
const bridge = (...args) => spawnSync(process.execPath, [join(root, "receiver/bridge/serve.mjs"), "--mandate", mandateFile, ...args], { encoding: "utf8", timeout: 60_000 });
const tool = (...args) => spawnSync(process.execPath, [join(root, "receiver/bridge/ledger-tool.mjs"), ...args], { encoding: "utf8", timeout: 60_000 });

test("bridge refuses to serve a tampered ledger, says why and what to do, and leaves the file alone", async () => {
  const path = await seededLedger("tampered.sqlite");
  const db = new DatabaseSync(path); db.exec("UPDATE orders SET notional_cents = 1"); db.close();
  const before = readFileSync(path);
  const run = bridge("--ledger", path);
  assert.equal(run.status, 1);
  assert.match(run.stderr, /integrity check/);
  assert.match(run.stderr, /Restore the last backup/);
  assert.doesNotMatch(run.stdout, /READY/);
  assert.equal(run.stderr.includes(dir), false, "no absolute path in the message");
  assert.equal(readFileSync(path).equals(before), true);
  assert.equal(existsSync(path + ".lock"), false, "the lock is released on refusal");
});

test("bridge refuses a ledger from another mandate, a garbage file and a live holder", async () => {
  const path = await seededLedger("other.sqlite");
  const other = join(dir, "other-mandate.json");
  writeFileSync(other, JSON.stringify({ ...mandate, maxDailyNotionalUsd: 30000 }));
  const run = spawnSync(process.execPath, [join(root, "receiver/bridge/serve.mjs"), "--mandate", other, "--ledger", path], { encoding: "utf8", timeout: 60_000 });
  assert.equal(run.status, 1);
  assert.match(run.stderr, /different mandate/);

  const junk = join(dir, "junk.sqlite");
  writeFileSync(junk, "not a database ".repeat(100));
  const bad = bridge("--ledger", junk);
  assert.equal(bad.status, 1);
  assert.match(bad.stderr, /could not be opened/);

  const held = join(dir, "held.sqlite");
  writeFileSync(held + ".lock", String(process.ppid));
  const locked = bridge("--ledger", held);
  assert.equal(locked.status, 1);
  assert.match(locked.stderr, /Another receiver/);
});

test("ledger-tool verifies, exports and backs up, with exit status 1 for a tampered ledger and no absolute paths printed", async () => {
  const path = await seededLedger("tool.sqlite");
  const ok = tool("verify", "--ledger", path);
  assert.equal(ok.status, 0);
  const report = JSON.parse(ok.stdout);
  assert.equal(report.ok, true); assert.equal(report.orders, 1); assert.match(report.head, /^\d+:[0-9a-f]{64}$/);
  assert.equal(tool("verify", "--ledger", path, "--expect-head", report.head).status, 0);
  assert.equal(tool("verify", "--ledger", path, "--expect-head", "9:" + "0".repeat(64)).status, 1);
  assert.equal(tool("verify", "--ledger", path, "--expect-head", "nonsense").status, 2);

  const out = join(dir, "export.json");
  assert.equal(tool("export", "--ledger", path, "--out", out).status, 0);
  assert.equal(JSON.parse(readFileSync(out, "utf8")).orders.length, 1);
  assert.equal(tool("export", "--ledger", path, "--out", out).status, 2, "never overwrites an export");

  const backup = join(dir, "backup.sqlite");
  const made = tool("backup", "--ledger", path, "--out", backup);
  assert.equal(made.status, 0);
  assert.equal(made.stdout.includes(dir), false);
  assert.equal(tool("verify", "--ledger", backup).status, 0);
  assert.equal(tool("backup", "--ledger", path, "--out", backup).status, 2);

  const db = new DatabaseSync(path); db.exec("UPDATE orders SET quantity = 3"); db.close();
  assert.equal(tool("verify", "--ledger", path).status, 1);
  assert.equal(tool("backup", "--ledger", path, "--out", join(dir, "bad-backup.sqlite")).status, 1);
  assert.equal(tool("verify", "--ledger", join(dir, "nope.sqlite")).status, 2);
  assert.equal(tool("verify").status, 2);
});

const req = (chunks, headers = {}) => Object.assign(Readable.from(chunks.map((c) => Buffer.from(c))), { headers });

test("request bodies: oversized, malformed, non-object and stalled requests are refused with a clear status", async () => {
  assert.deepEqual(await readJsonBody(req(['{"a":1}'])), { a: 1 });
  assert.deepEqual(await readJsonBody(req([])), {});
  await assert.rejects(readJsonBody(req(["x".repeat(100)], { "content-length": "100" }), { limit: 50 }), (e) => e instanceof HttpError && e.status === 413);
  await assert.rejects(readJsonBody(req(["x".repeat(30), "y".repeat(30)]), { limit: 50 }), (e) => e.status === 413, "chunked body with no content-length");
  await assert.rejects(readJsonBody(req(["{not json"])), (e) => e.status === 400 && e.code === "invalid_json");
  for (const body of ["[]", "null", "5", '"s"']) await assert.rejects(readJsonBody(req([body])), (e) => e.status === 400 && e.code === "invalid_body", body);
  const stalled = new Readable({ read() {} });
  stalled.headers = {};
  await assert.rejects(readJsonBody(stalled, { timeoutMs: 30 }), (e) => e.status === 408);
  const dropped = new Readable({ read() {} });
  dropped.headers = {};
  const pending = readJsonBody(dropped);
  dropped.destroy(new Error("socket hang up"));
  await assert.rejects(pending, (e) => e.status === 400 && e.code === "request_aborted");
});

test("error mapping: internal and database errors are 500 with no detail; domain errors keep their message; paths and tokens are scrubbed", () => {
  const fakeHome = ["", "Users", "someone"].join("/"); // built from parts so no literal home path sits in the repository
  const [s1, b1] = failure(Object.assign(new Error(`SQLITE_BUSY at ${fakeHome}/x.sqlite`), { code: "ERR_SQLITE_ERROR" }));
  assert.equal(s1, 500); assert.equal(b1.error, "internal_error"); assert.doesNotMatch(JSON.stringify(b1), /someone|sqlite/i);
  assert.equal(failure(new TypeError("bug"))[0], 500);
  assert.deepEqual(failure(new Error("The active policy changed. Sign again"), { domainStatus: 400 }), [400, { error: "The active policy changed. Sign again" }]);
  assert.equal(failure("a string", { domainStatus: 400 })[0], 500);
  assert.equal(failure(new HttpError(413, "body_too_large", "big"))[0], 413);
  const text = scrub(`failed in ${fakeHome}/project/file.js with Bearer abc.def-123 and api_key=zz-123456`);
  assert.doesNotMatch(text, /someone|abc\.def|zz-123456/);
});
