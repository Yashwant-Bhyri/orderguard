/**
 * Bounded W2 seam proof: the actual second-lock reviewer fails closed when its
 * loopback decision sidecar is down; no ledger commit or W2 dispatch follows.
 * Paired clean requests use the cheap allow path, then W2 dispatches/reconciles
 * against the synthetic LocalSim venue. No OpenD, Futu, provider or WAN calls.
 */

import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { reviewSecondLock } from '../intel/second-lock.ts';

const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
const PYTHON_BRIDGE = join(ROOT, 'futu-adapter/offline_lock2_gate_bridge.py');
const OUTPUT = join(ROOT, 'futu-adapter/results/lock2-outage-localsim-proof-2026-11-03.json');
const SECRET_NAMES = ['OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'LIQUID_API_KEY', 'TYPESAFE_API_KEY'];
for (const name of SECRET_NAMES) delete process.env[name];

const order = {
  market: 'HK', symbol: '0700.HK', side: 'buy', quantity: 2,
  orderType: 'limit', limitPrice: 388, currency: 'HKD', session: 'hk_regular', timeInForce: 'day',
};
const cleanTrigger = 'Routine market update. No order instructions are included.';
const syntheticTools = {
  readAccountState: async () => ({ cashAvailableUsd: 100_000, netAssetValueUsd: 100_000, syntheticOnly: true }),
  readSignedQuote: async () => ({ quote: { symbol: '0700.HK', last: 388, currency: 'HKD', freshness: 'current' }, trustedByReceiver: true }),
  readMandateState: async () => ({
    policyVersion: 'w2-offline-gate-v1', market: 'HK', currency: 'HKD',
    allowedSymbols: ['0700.HK'], maxQuantityPerOrder: 1_000, maxOrderNotionalHkd: 10_000,
  }),
};

function closedLoopbackPort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') return reject(new Error('loopback_port_unavailable'));
      const port = address.port;
      server.close((error) => error ? reject(error) : resolvePort(port));
    });
  });
}

function runPython(mode: 'control' | 'blocked', index: number, scratch: string): Record<string, unknown> {
  const caseDir = join(scratch, `${mode}-${String(index).padStart(2, '0')}`);
  const env = {
    ...process.env,
    ORDERGUARD_DISABLE_LOCAL_ENV: '1',
    ORDERGUARD_FUTU_SIMULATE_ENABLED: '1',
    ORDERGUARD_B3_DISPATCH_STARTED: '1',
    ORDERGUARD_SPEND_FILE: join(scratch, 'spend.csv'),
  };
  for (const name of SECRET_NAMES) delete (env as Record<string, string | undefined>)[name];
  const child = spawnSync('python3', [PYTHON_BRIDGE, mode, caseDir], {
    cwd: ROOT, env, encoding: 'utf8', timeout: 15_000,
  });
  if (child.status !== 0) throw new Error(`python_bridge_failed:${mode}:${index}:${child.stderr || child.stdout}`);
  return JSON.parse(child.stdout.trim()) as Record<string, unknown>;
}

async function main(): Promise<number> {
  const scratch = mkdtempSync(join(tmpdir(), 'og-w2-lock2-localsim-'));
  const denied: Record<string, unknown>[] = [];
  const controls: Record<string, unknown>[] = [];
  const originalInfo = console.info;
  const originalWarn = console.warn;
  console.info = () => {};
  console.warn = () => {};
  try {
    process.env.ORDERGUARD_DISABLE_LOCAL_ENV = '1';
    process.env.ORDERGUARD_SECOND_LOCK_DEADLINE_MS = '1000';
    process.env.ORDERGUARD_DECISIONS_SIDECAR_URL = 'http://127.0.0.1:9/v1/provider-decision';
    process.env.ORDERGUARD_SPEND_FILE = join(scratch, 'spend.csv');

    for (let i = 1; i <= 10; i += 1) {
      // Reserve an ephemeral local port, close it, then point the real second
      // lock at it. Refused loopback requests model a crashed/unavailable host.
      const port = await closedLoopbackPort();
      process.env.ORDERGUARD_DECISIONS_SIDECAR_URL = `http://127.0.0.1:${port}/v1/provider-decision`;
      const riskyOrder = { ...order, limitPrice: 430 + i };
      const audit = await reviewSecondLock({
        order: riskyOrder,
        trigger: cleanTrigger,
        tools: syntheticTools,
        mandateDecision: 'allow',
      });
      let adapterResult: Record<string, unknown> = { adapter_invoked: false, venue_place_calls: 0 };
      if (audit.decision !== 'allow') adapterResult = runPython('blocked', i, scratch);
      denied.push({
        case: i,
        decision: audit.decision,
        source: audit.source,
        fallback_reason: audit.fallbackReason,
        cheap_flags: audit.cheapFlags,
        provider_attempts: audit.providerAttempts.length,
        adapter_gate: adapterResult,
      });
    }

    for (let i = 1; i <= 10; i += 1) {
      // Clean in-scope orders should stay on the cheap lock path while the
      // sidecar remains unavailable, then complete through W2 LocalSim.
      const audit = await reviewSecondLock({ order, trigger: cleanTrigger, tools: syntheticTools, mandateDecision: 'allow' });
      const adapterResult = audit.decision === 'allow' ? runPython('control', i, scratch) : { state: 'not_dispatched' };
      controls.push({ case: i, decision: audit.decision, source: audit.source, adapter: adapterResult });
    }

    const failedClosed = denied.filter((row) => row.decision === 'step_up'
      && row.source === 'flagged-fallback' && row.fallback_reason === 'sidecar_unavailable'
      && Array.isArray(row.cheap_flags) && (row.cheap_flags as string[]).includes('price_distance_from_quote')
      && row.adapter_gate && (row.adapter_gate as Record<string, unknown>).observed === 'ledger_commit_missing'
      && (row.adapter_gate as Record<string, unknown>).venue_place_calls === 0).length;
    const benignCompleted = controls.filter((row) => {
      const result = row.adapter as Record<string, unknown>;
      return row.decision === 'allow' && row.source === 'cheap-features'
        && result.state === 'accepted' && result.reconciled === true
        && result.venue_place_calls === 1 && result.reconcile_mismatches === 0;
    }).length;
    const spendFile = join(scratch, 'spend.csv');
    const result = {
      schema_version: 1,
      mode: 'offline_lock2_outage_w2_localsim_gate',
      date_hkt: new Date().toISOString().slice(0, 10),
      n: denied.length + controls.length,
      k: failedClosed + benignCompleted,
      model: 'N/A; deterministic second-lock features and synthetic LocalSim',
      lock2_sidecar_unavailable_step_up: `${failedClosed}/10`,
      adapter_refused_without_commit: `${failedClosed}/10`,
      benign_local_sim_reconciled: `${benignCompleted}/10`,
      benign_local_sim_placements: controls.reduce((n, row) => n + Number((row.adapter as Record<string, unknown>).venue_place_calls ?? 0), 0),
      reconcile_mismatches: controls.reduce((n, row) => n + Number((row.adapter as Record<string, unknown>).reconcile_mismatches ?? 0), 0),
      loopback_connection_refusals: denied.reduce((n, row) => n + Number(row.provider_attempts ?? 0), 0),
      external_network_calls: 0,
      provider_calls: 0,
      opend_calls: 0,
      futu_submissions: 0,
      spend_file_rows: process.env.ORDERGUARD_SPEND_FILE && requireSpendRows(spendFile),
      denied_cases: denied,
      benign_cases: controls,
    };
    await (await import('node:fs/promises')).mkdir(join(ROOT, 'futu-adapter/results'), { recursive: true });
    await (await import('node:fs/promises')).writeFile(OUTPUT, JSON.stringify(result, null, 2) + '\n', 'utf8');
    process.stdout.write(JSON.stringify({
      artifact: OUTPUT.slice(ROOT.length + 1), mode: result.mode, n: result.n, k: result.k,
      lock2_sidecar_unavailable_step_up: result.lock2_sidecar_unavailable_step_up,
      adapter_refused_without_commit: result.adapter_refused_without_commit,
      benign_local_sim_reconciled: result.benign_local_sim_reconciled,
      benign_local_sim_placements: result.benign_local_sim_placements,
      reconcile_mismatches: result.reconcile_mismatches,
      loopback_connection_refusals: result.loopback_connection_refusals,
      external_network_calls: 0, provider_calls: 0, opend_calls: 0, futu_submissions: 0,
      spend_file_rows: result.spend_file_rows,
    }, null, 0) + '\n');
    return result.k === result.n ? 0 : 1;
  } finally {
    console.info = originalInfo;
    console.warn = originalWarn;
    rmSync(scratch, { recursive: true, force: true });
  }
}

function requireSpendRows(path: string): number {
  try {
    return readFileSync(path, 'utf8').trim().split(/\r?\n/).filter(Boolean).length;
  } catch {
    return 0;
  }
}

main().then((code) => { process.exitCode = code; }).catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
