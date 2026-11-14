#!/usr/bin/env node
// Offline ledger tool for the receiver bridge.
//   node receiver/bridge/ledger-tool.mjs verify --ledger FILE [--expect-head SEQ:HASH]
//   node receiver/bridge/ledger-tool.mjs export --ledger FILE --out FILE|-
//   node receiver/bridge/ledger-tool.mjs backup --ledger FILE --out FILE [--allow-tampered]
// Exit status: 0 verified, 1 the ledger failed verification, 2 usage or file problem. Works while the receiver runs.
import { writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { register } from "tsx/esm/api";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const argv = process.argv.slice(2);
const command = argv[0];
const arg = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };
const say = (value) => process.stdout.write(JSON.stringify(value, null, 2) + "\n");
const usage = "usage: ledger-tool.mjs verify|export|backup --ledger FILE [--out FILE] [--expect-head SEQ:HASH] [--allow-tampered]";

function parseHead(text) {
  if (text === undefined) return undefined;
  const m = /^(\d+):([0-9a-f]{64})$/.exec(text);
  if (!m) throw new Error("--expect-head must look like SEQ:HASH (64 hex characters), as printed by verify");
  return { seq: Number(m[1]), hash: m[2] };
}

try {
  const ledger = arg("--ledger");
  if (!["verify", "export", "backup"].includes(command) || !ledger) { process.stderr.write(usage + "\n"); process.exit(2); }
  register();
  const files = await import(pathToFileURL(join(root, "receiver/core/ledger-files.ts")).href);
  const name = basename(ledger);
  if (command === "verify") {
    const check = files.verifyLedgerFile(ledger, parseHead(arg("--expect-head")));
    say({ ledger: name, ok: check.ok, events: check.events, orders: check.orders, revoked: check.revoked,
      head: `${check.head.seq}:${check.head.hash}`, problems: check.problems });
    process.exit(check.ok ? 0 : 1);
  }
  const out = arg("--out");
  if (!out) { process.stderr.write("--out is required\n" + usage + "\n"); process.exit(2); }
  if (command === "export") {
    const data = files.exportLedger(ledger);
    const text = JSON.stringify(data, null, 1) + "\n";
    if (out === "-") process.stdout.write(text); else writeFileSync(resolve(out), text, { mode: 0o600, flag: "wx" });
    say({ ledger: name, exported: out === "-" ? "stdout" : basename(out), ok: data.verification.ok, events: data.verification.events,
      orders: data.verification.orders, head: `${data.verification.head.seq}:${data.verification.head.hash}`, problems: data.verification.problems });
    process.exit(data.verification.ok ? 0 : 1);
  }
  const check = files.backupLedger(ledger, out, { allowTampered: argv.includes("--allow-tampered") });
  say({ ledger: name, backup: basename(out), ok: check.ok, events: check.events, orders: check.orders, head: `${check.head.seq}:${check.head.hash}`, problems: check.problems });
  process.exit(check.ok ? 0 : 1);
} catch (error) {
  const text = String(error?.message ?? error);
  const code = error?.code === "EEXIST" ? "that output file already exists; choose a new name" : text;
  process.stderr.write(`ledger-tool: ${code}\n`);
  process.exit(error?.code === "tampered" ? 1 : 2);
}
