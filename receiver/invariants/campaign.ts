// Seeded fault campaign and invariant checker for the receiver core.
// Reuses the r5 fault scheduler: every five consecutive seeds cover drop, duplicate, delay, crash and revoke.

import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { B4FaultScheduler, createSeededB4FaultSchedule } from '../r5/fault-scheduler.ts';
import { FaultCrash, FaultDropped, ReceiverCore, type MandateScope, type ProposedOrder } from '../core/receiver-core.ts';

export const MANDATE: Omit<MandateScope, 'expiresAt'> = {
  symbols: ['AAPL', 'MSFT'], sides: ['buy'], maxOrderNotionalUsd: 10000, maxDailyNotionalUsd: 20000, priceBandPct: 5,
  referencePrices: { AAPL: 222.7, MSFT: 420.18 },
};
const TRUSTED = 222.7;
const HONEST_QTY = 44; // 9,798.80 each: two fit under the 20,000 daily cap, three do not
const CAP_CENTS = MANDATE.maxDailyNotionalUsd * 100;
const ORDER_CAP_CENTS = MANDATE.maxOrderNotionalUsd * 100;

export interface Mutations { idempotencyOff?: boolean; budgetLockOff?: boolean }
export type Violation = { invariant: 'I1' | 'I2' | 'I3' | 'I4' | 'I5'; seed: number; detail: string };

export interface SeedResult {
  seed: number;
  action: string;
  faultApplied: boolean;
  violations: Violation[];
  honestSubmitted: number;
  honestFilled: number;
  honestEntitled: number | null; // null when a revoke made entitlement undefined
}

const honest = (id: string): ProposedOrder => ({ symbol: 'AAPL', side: 'buy', quantity: HONEST_QTY, limitPrice: TRUSTED, clientOrderId: id });
const attacks: ProposedOrder[] = [
  { symbol: 'AAPL', side: 'buy', quantity: 440, limitPrice: 22.3, clientOrderId: 'atk-split' },
  { symbol: 'AAPL', side: 'sell', quantity: 10, limitPrice: TRUSTED, clientOrderId: 'atk-sell' },
  { symbol: 'АAAPL', side: 'buy', quantity: 10, limitPrice: TRUSTED, clientOrderId: 'atk-cyrillic' },
  { symbol: 'TSLA', side: 'buy', quantity: 10, limitPrice: 300, clientOrderId: 'atk-unlisted' },
];

async function deliver(core: ReceiverCore, order: ProposedOrder): Promise<void> {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try { await core.propose(order); return; } catch (e) { if (!(e instanceof FaultDropped || e instanceof FaultCrash)) throw e; }
  }
}

export async function runSeed(seed: number, mutations: Mutations = {}): Promise<SeedResult> {
  const dir = mkdtempSync(join(tmpdir(), 'og-seed-'));
  const schedule = createSeededB4FaultSchedule(seed);
  const faults = new B4FaultScheduler(schedule);
  const core = new ReceiverCore({
    ledgerPath: join(dir, 'ledger.sqlite'), mandateId: 'campaign', fast: true, faults, mutations,
    mandate: { ...MANDATE, expiresAt: new Date(Date.now() + 3_600_000).toISOString() },
  });
  try {
    // Five honest agents race for one budget; agent 0 also delivers its order twice at once.
    const ids = ['h0', 'h1', 'h2', 'h3', 'h4'];
    const work: Array<Promise<void>> = ids.map((id) => deliver(core, honest(id)));
    work.push(deliver(core, honest('h0')));
    for (const a of attacks) work.push(deliver(core, a));
    await Promise.all(work);

    const action = schedule.events[0]!.action;
    const faultApplied = faults.report().unappliedEventIds.length === 0;
    const orders = core.orders();
    const events = core.events();
    const revokedSeq = core.revokedSeq();
    const v: Violation[] = [];

    // I1: every ledger effect is the exact canonical action under scope, valued at the trusted price.
    for (const o of orders) {
      const cents = Math.round(o.quantity * TRUSTED * 100);
      const inBand = Math.abs(o.limitPrice - TRUSTED) <= TRUSTED * MANDATE.priceBandPct / 100 + 1e-9;
      if (o.symbol !== 'AAPL' || o.side !== 'buy' || cents > ORDER_CAP_CENTS || !inBand || o.clientOrderId.startsWith('atk')) {
        v.push({ invariant: 'I1', seed, detail: `out-of-scope effect ${o.clientOrderId}` });
      }
    }
    // I2: shared limit holds, counted in trusted cents.
    const used = orders.filter((o) => o.status !== 'cancelled').reduce((s, o) => s + Math.round(o.notionalUsd * 100), 0);
    if (used > CAP_CENTS) v.push({ invariant: 'I2', seed, detail: `spent ${used / 100} of ${CAP_CENTS / 100}` });
    // I3: one effect per clientOrderId, however many deliveries.
    const perId = new Map<string, number>();
    for (const o of orders) perId.set(o.clientOrderId, (perId.get(o.clientOrderId) ?? 0) + 1);
    for (const [id, n] of perId) if (n > 1) v.push({ invariant: 'I3', seed, detail: `${id} has ${n} ledger effects` });
    // I4: no fill or approval is sequenced after the revocation.
    if (revokedSeq !== null) {
      for (const e of events) if (e.seq > revokedSeq && (e.type === 'filled' || e.type === 'approved')) v.push({ invariant: 'I4', seed, detail: `${e.type} at seq ${e.seq} after revoke at ${revokedSeq}` });
    }
    if (!core.ledgerIntegrity() && !mutations.idempotencyOff && !mutations.budgetLockOff) v.push({ invariant: 'I2', seed, detail: 'ledger integrity check failed' });

    // I5: permitted work completes. Five honest orders race; exactly floor(cap/order) may fill. Undefined if a revoke fired.
    const honestFilled = orders.filter((o) => o.clientOrderId.startsWith('h') && o.status === 'filled').length;
    const entitled = revokedSeq === null ? Math.min(ids.length, Math.floor(CAP_CENTS / Math.round(HONEST_QTY * TRUSTED * 100))) : null;
    if (entitled !== null && honestFilled < entitled) v.push({ invariant: 'I5', seed, detail: `${honestFilled} of ${entitled} entitled honest orders filled` });
    return { seed, action, faultApplied, violations: v, honestSubmitted: ids.length, honestFilled, honestEntitled: entitled };
  } finally {
    core.close();
    rmSync(dir, { recursive: true, force: true });
  }
}

export interface CampaignSummary {
  seeds: number;
  byAction: Record<string, { seeds: number; applied: number }>;
  violations: Violation[];
  benignFilled: number;
  benignEntitled: number;
}

export async function runCampaign(seeds: number, mutations: Mutations = {}, start = 1): Promise<CampaignSummary> {
  const sum: CampaignSummary = { seeds, byAction: {}, violations: [], benignFilled: 0, benignEntitled: 0 };
  for (let i = 0; i < seeds; i += 1) {
    const r = await runSeed(start + i, mutations);
    const slot = (sum.byAction[r.action] ??= { seeds: 0, applied: 0 });
    slot.seeds += 1;
    if (r.faultApplied) slot.applied += 1;
    sum.violations.push(...r.violations);
    if (r.honestEntitled !== null) { sum.benignFilled += Math.min(r.honestFilled, r.honestEntitled); sum.benignEntitled += r.honestEntitled; }
  }
  return sum;
}

/** Fault-free benign suite: ample budget, distinct honest orders across both symbols. Every one must complete. */
export async function runBenignSuite(n = 20): Promise<{ filled: number; total: number }> {
  const dir = mkdtempSync(join(tmpdir(), 'og-benign-'));
  const core = new ReceiverCore({ ledgerPath: join(dir, 'l.sqlite'), mandateId: 'benign', fast: true, mandate: { ...MANDATE, maxDailyNotionalUsd: 1_000_000, expiresAt: new Date(Date.now() + 3_600_000).toISOString() } });
  try {
    let filled = 0;
    const out = await Promise.all(Array.from({ length: n }, (_, i) => core.propose(i % 2 ? { symbol: 'msft', side: 'buy', quantity: 5, limitPrice: 420.18, clientOrderId: `b${i}` } : { symbol: 'AAPL', side: 'buy', quantity: 10, limitPrice: 222.7, clientOrderId: `b${i}` })));
    for (const d of out) if (d.decision === 'filled') filled += 1;
    return { filled, total: n };
  } finally { core.close(); rmSync(dir, { recursive: true, force: true }); }
}
