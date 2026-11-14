// One of K processes racing the same receiver ledger file. Each process opens its own ReceiverCore on the shared SQLite file
// (durable: WAL, synchronous=FULL, busy_timeout) and, at an agreed wall-clock instant, fires all of its orders at once. SQLite's
// BEGIN IMMEDIATE is the only thing serialising the processes, so this tests the shared budget and idempotency across processes.
// (The production bridge refuses a second writer with a lock file; this bypasses that lock on purpose, to test the core itself.)
//
//   node --no-warnings --import tsx receiver/bench/race-worker.ts --ledger L --spec SPEC.json --worker i --start-at MS [--mutation m]
// SPEC: {"mandateId","scope","price","orders":[{"symbol","side","quantity","limitPrice","clientOrderId"}...] per worker or shared}

import { readFileSync } from 'node:fs';
import { ReceiverCore, type Decision } from '../core/receiver-core.ts';
import { arg } from './common.ts';

const spec = JSON.parse(readFileSync(arg('--spec')!, 'utf8')) as {
  mandateId: string; scope: never; price: number; orders: Array<Array<{ symbol: string; side: string; quantity: number; limitPrice: number; clientOrderId: string }>>;
};
const worker = Number(arg('--worker'));
const startAt = Number(arg('--start-at'));
const mutation = arg('--mutation', 'none');
const mutations = mutation === 'budgetLockOff' ? { budgetLockOff: true } : mutation === 'idempotencyOff' ? { idempotencyOff: true } : undefined;

let core: ReceiverCore | null = null;
for (let attempt = 0; attempt < 50 && !core; attempt += 1) {
  try {
    core = new ReceiverCore({ ledgerPath: arg('--ledger')!, mandateId: spec.mandateId, mandate: spec.scope, quoteSource: () => spec.price,
      now: () => Date.parse('2026-01-05T12:00:00Z'), mutations });
  } catch (e) {
    if (!/locked|busy/i.test(String((e as Error).message))) throw e;
    await new Promise((ok) => setTimeout(ok, 20));
  }
}
if (!core) throw new Error('could not open the shared ledger');
const orders = spec.orders[worker % spec.orders.length]!;
const wait = startAt - Date.now();
if (wait > 0) await new Promise((ok) => setTimeout(ok, wait));
const results: Array<[string, string]> = [];
let errors = 0;
await Promise.all(orders.map(async (o) => {
  try {
    const d: Decision = await core!.propose(o);
    results.push([o.clientOrderId, d.decision]);
  } catch (e) {
    errors += 1;
    results.push([o.clientOrderId, 'error:' + String((e as Error).message).slice(0, 40)]);
  }
}));
core.close();
process.stdout.write(JSON.stringify({ worker, results, errors }) + '\n');
