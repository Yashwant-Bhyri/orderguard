// First-run checks shared by the receiver bridge and the Node examples. Imports only Node built-ins, so it still runs on a Node that is too
// old for the rest of the repository, and before `npm ci` has installed anything. Each problem is one sentence that says what to do.
import { existsSync } from "node:fs";
import { join } from "node:path";

export const MIN_NODE = [22, 13];

/** A sentence if `version` (default: this Node) is older than 22.13, else null. */
export function nodeProblem(version = process.versions.node) {
  const [major = 0, minor = 0] = String(version).split(".").map(Number);
  if (major > MIN_NODE[0] || (major === MIN_NODE[0] && minor >= MIN_NODE[1])) return null;
  return `Node ${version} is too old: the receiver needs Node ${MIN_NODE.join(".")} or newer (it uses the built-in SQLite). `
    + "Upgrade with `nvm install 22 && nvm use 22` (or https://nodejs.org/), then run this again. The Python parts of OrderGuard do not need Node.";
}

/** A sentence if the repository's npm dependencies are not installed (tsx runs the TypeScript receiver), else null. */
export function installProblem(root, exists = existsSync) {
  if (exists(join(root, "node_modules", "tsx"))) return null;
  return `The Node dependencies are not installed in ${root}. Run \`npm ci\` there once, then run this again.`;
}

/** Print every problem and exit 1; returns normally when the environment is fine. */
export function requireEnvironment(root, { needsInstall = true } = {}) {
  const problems = [nodeProblem(), needsInstall ? installProblem(root) : null].filter(Boolean);
  if (problems.length === 0) return;
  for (const problem of problems) process.stderr.write(`error: ${problem}\n`);
  process.exit(1);
}
