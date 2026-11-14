// In-process receiver benchmark: the real ReceiverCore (receiver/core/receiver-core.ts), one SQLite ledger per envelope, fed the
// envelope's order stream from the bench workload in order. Measures end-to-end propose() latency and throughput in two storage
// modes, a per-stage profile (private methods wrapped by a timer on a separate pass), the cost of verify-on-open, and agreement with
// the Python authority's decisions. The ledgers are left on disk for the Python auditor.
//
//   node --no-warnings --import tsx receiver/bench/inprocess.ts --workload W.jsonl --dir LEDGER_DIR --out OUT.json [--durable-max N]

import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { Market, arg, asPy, hr, loadWorkload, openCore, pct, toOrder, type Line } from './common.ts';
import type { ReceiverCore } from '../core/receiver-core.ts';

const workload = arg('--workload')!;
const dir = arg('--dir')!;
const out = arg('--out')!;
const durableMax = Number(arg('--durable-max', '20000'));
const { header, lines } = loadWorkload(workload);
const byEnv = new Map<string, Line[]>();
for (const l of lines) { if (!byEnv.has(l.e)) byEnv.set(l.e, []); byEnv.get(l.e)!.push(l); }
const envNames = [...byEnv.keys()].sort();

interface StageAcc { [k: string]: number }

function wrapStages(core: ReceiverCore, acc: StageAcc): void {
  const c = core as unknown as Record<string, (...a: unknown[]) => unknown>;
  let inCommit = false;
  const timed = (name: string, key: (inside: boolean) => string, flag?: boolean) => {
    const orig = c[name]!.bind(core);
    c[name] = (...a: unknown[]) => {
      const k = key(inCommit);
      if (flag) inCommit = true;
      const t = hr();
      try { return orig(...a); } finally {
        acc[k] = (acc[k] ?? 0) + Number(hr() - t);
        if (flag) inCommit = false;
      }
    };
  };
  timed('check', () => 'shape');
  timed('findByClientId', (inside) => (inside ? 'idem_in_commit' : 'idempotency_lookup'));
  timed('dayBudgetUsedCents', () => 'budget');
  timed('portfolioDenial', () => 'portfolio');
  timed('insertRow', () => 'insert_and_chain');
  timed('commit', () => 'commit', true);
}

async function pass(mode: 'fast' | 'durable', max: number, profile: boolean) {
  const sub = join(dir, mode + (profile ? '-profile' : ''));
  mkdirSync(sub, { recursive: true });
  const lat: number[] = [];
  const stageRows: Record<string, number[]> = {};
  const decisions: Array<[string, string, string]> = [];
  const agree = { first: { agree: 0, disagree: 0 }, repeat: { agree: 0, disagree: 0 }, examples: [] as unknown[] };
  const counts: Record<string, number> = { filled: 0, held: 0, denied: 0 };
  const ledgers: Record<string, string> = {};
  const market = new Market(header);
  let n = 0;
  let busy = 0n;
  for (const name of envNames) {
    if (n >= max) break;
    const path = join(sub, name + '.sqlite');
    ledgers[name] = path;
    const core = openCore(path, name, header, market, { fast: mode === 'fast' });
    const acc: StageAcc = {};
    if (profile) wrapStages(core, acc);
    const seenKeys = new Set<string>();
    for (const l of byEnv.get(name)!) {
      if (n >= max) break;
      market.at(l.t, l.day);
      if (l.x === 'revoke') { core.revoke(); continue; }       // the owner revokes the envelope: durable, nothing may commit after it
      for (const k of Object.keys(acc)) delete acc[k];
      const t0 = hr();
      const d = await core.propose(toOrder(l));
      const dt = Number(hr() - t0);
      busy += BigInt(dt);
      lat.push(dt);
      n += 1;
      counts[d.decision] = (counts[d.decision] ?? 0) + 1;
      decisions.push([l.k, d.decision, name]);
      if (profile) {
        const inner = (acc.shape ?? 0) + (acc.idempotency_lookup ?? 0) + (acc.commit ?? 0);
        const row: Record<string, number> = { ...acc, scope_at_trusted_price: dt - inner, total: dt };
        if (acc.commit !== undefined) row.tx_begin_commit_fsync = acc.commit - (acc.budget ?? 0) - (acc.portfolio ?? 0) - (acc.insert_and_chain ?? 0) - (acc.idem_in_commit ?? 0);
        for (const [k, v] of Object.entries(row)) (stageRows[k] ??= []).push(v);
      }
      const first = !seenKeys.has(l.k) && l.x !== 'retry' && l.x !== 'dup_now' && l.x !== 'conflict';
      seenKeys.add(l.k);
      const slot = first ? agree.first : agree.repeat;
      if (asPy(d) === l.py) slot.agree += 1;
      else {
        slot.disagree += 1;
        if (agree.examples.length < 12) agree.examples.push({ key: l.k, kind: l.x, python: l.py, receiver: d.decision, reason: d.reason });
      }
    }
    core.close();
  }
  const res: Record<string, unknown> = { mode, orders: n, envelopes: Object.keys(ledgers).length, busy_s: Number(busy) / 1e9,
    decisions_per_s: Math.round(n / (Number(busy) / 1e9)), latency_us: pct(lat), counts, agreement: agree, ledgers };
  if (profile) res.stages_us = Object.fromEntries(Object.entries(stageRows).map(([k, v]) => [k, pct(v)]));
  else res.decisions = decisions;
  return res;
}

function verifyOnOpen(ledgers: Record<string, string>): Record<string, unknown> {
  const market = new Market(header);
  const per: number[] = [];
  let events = 0;
  let total = 0;
  for (const [name, path] of Object.entries(ledgers)) {
    const t0 = hr();
    const core = openCore(path, name, header, market, { verifyOnOpen: true });
    const dt = Number(hr() - t0);
    const check = core.verifyLedger();
    core.close();
    if (!check.ok) throw new Error(`ledger ${name} failed its own verification: ${check.problems[0]}`);
    events += check.events;
    total += dt;
    per.push(dt / Math.max(check.events, 1));
  }
  return { ledgers: Object.keys(ledgers).length, events, open_and_verify_ms: Math.round(total / 1e4) / 100, us_per_event: pct(per) };
}

const only = arg('--passes', 'all');
const fast = await pass('fast', Number.MAX_SAFE_INTEGER, false);
if (only === 'fast') {
  writeFileSync(out, JSON.stringify({ node: process.version, workload_orders: lines.length, envelopes: envNames.length, fast }));
} else {
  const fastProfile = await pass('fast', Math.min(lines.length, 50_000), true);
  const durable = await pass('durable', durableMax, false);
  const durableProfile = await pass('durable', Math.min(durableMax, 5_000), true);
  const verify = verifyOnOpen(fast.ledgers as Record<string, string>);
  writeFileSync(out, JSON.stringify({ node: process.version, workload_orders: lines.length, envelopes: envNames.length, fast, fast_profile: fastProfile,
    durable, durable_profile: durableProfile, verify_on_open: verify }));
  console.log(`receiver in-process: fast ${fast.decisions_per_s}/s, durable ${durable.decisions_per_s}/s over ${fast.orders} / ${durable.orders} orders`);
}
