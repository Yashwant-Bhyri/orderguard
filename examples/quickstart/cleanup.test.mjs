import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { cleanupSequential, formatQuickstartFailure, runWithCleanup, trackChildSpawn } from "./cleanup.mjs";

test("all cleanup actions run before a stop error is rethrown", async () => {
  const calls = [];
  const stopError = new Error("MCP stop failed");
  await assert.rejects(
    cleanupSequential([
      async () => { calls.push("mcp"); throw stopError; },
      async () => { calls.push("receiver"); },
      async () => { calls.push("scratch"); },
    ]),
    (error) => error === stopError,
  );
  assert.deepEqual(calls, ["mcp", "receiver", "scratch"]);
});

test("the original run error and cleanup errors survive after every cleanup", async () => {
  const calls = [];
  const runError = new Error("receiver attack check failed");
  const mcpError = new Error("MCP stop failed");
  const receiverError = new Error("receiver stop failed");
  const error = await runWithCleanup(
    async () => { calls.push("run"); throw runError; },
    [
      async () => { calls.push("mcp"); throw mcpError; },
      async () => { calls.push("receiver"); throw receiverError; },
      async () => { calls.push("scratch"); },
    ],
  ).then(() => null, (failure) => failure);
  assert.ok(error instanceof AggregateError);
  assert.equal(error.cause, runError);
  assert.deepEqual(error.errors, [runError, mcpError, receiverError]);
  assert.deepEqual(calls, ["run", "mcp", "receiver", "scratch"]);
  assert.equal(formatQuickstartFailure(error), "receiver attack check failed; MCP stop failed; receiver stop failed");
});

test("the original run error is retained when cleanup succeeds", async () => {
  const runError = new Error("pairing code: ABCD1234 failed");
  await assert.rejects(
    runWithCleanup(async () => { throw runError; }, [async () => {}]),
    (error) => error === runError,
  );
  assert.equal(formatQuickstartFailure(runError), "pairing code: [redacted] failed");
});

test("a non-Error thrown value is retained when cleanup succeeds", async () => {
  const outcome = await runWithCleanup(async () => { throw null; }, [async () => {}]).then(
    () => ({ rejected: false }),
    (error) => ({ rejected: true, error }),
  );
  assert.equal(outcome.rejected, true);
  assert.equal(outcome.error, null);
});


test("an asynchronous child spawn error runs every cleanup and stays primary", async () => {
  const scratch = await mkdtemp(join(tmpdir(), "orderguard-spawn-error-"));
  const missingCwd = join(scratch, "missing-cwd");
  await mkdir(missingCwd);
  await rm(missingCwd, { recursive: true, force: true });
  const child = spawn(process.execPath, ["-e", ""], { cwd: missingCwd, stdio: "ignore" });
  const spawnState = trackChildSpawn(child);
  const calls = [];
  try {
    const error = await runWithCleanup(
      async () => spawnState.race(new Promise((resolve) => child.once("spawn", resolve))),
      [
        async () => { calls.push("mcp"); },
        async () => { calls.push("receiver"); },
        async () => { calls.push("scratch"); await rm(scratch, { recursive: true, force: true }); },
      ],
    ).then(() => null, (failure) => failure);
    assert.equal(error?.code, "ENOENT");
    assert.match(error?.syscall ?? "", /^spawn\b/);
    assert.deepEqual(calls, ["mcp", "receiver", "scratch"]);
    assert.equal(formatQuickstartFailure(error), "child process spawn failed (ENOENT)");
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});
