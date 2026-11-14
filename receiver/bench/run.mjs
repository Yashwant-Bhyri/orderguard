#!/usr/bin/env node
// `npm run bench -- [run --profile quick|full | http | report]`: runs og-bench from the repository's virtualenv (or python3 -m orderguard_bench).
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const venv = join(root, ".venv", "bin", "python");
const python = existsSync(venv) ? venv : "python3";
const args = process.argv.slice(2);
const r = spawnSync(python, ["-m", "orderguard_bench", ...(args.length ? args : ["run", "--profile", "quick"])], {
  cwd: root, stdio: "inherit", env: { ...process.env, PYTHONPATH: [join(root, "python"), process.env.PYTHONPATH].filter(Boolean).join(":") },
});
process.exit(r.status ?? 1);
