// Shared helpers for the receiver benchmarks. The workload file is written by `og-bench` (python/orderguard_bench/receiver.py):
//   line 1   {"type":"header","base_date":"2026-01-05","prices":[{SYM: price, ...} per step],"envelopes":{name:{mandateId,scope}}}
//   then     {"e":env,"t":step,"day":d,"k":clientOrderId,"s":symbol,"sd":side,"q":qty,"l":limit,"tp":trusted|null,"py":decision,"x":kind}
// Nothing here talks to a network. Ledgers are throw-away SQLite files in a temp directory.

import { readFileSync } from 'node:fs';
import { ReceiverCore, type Decision, type MandateScope, type ProposedOrder } from '../core/receiver-core.ts';

export interface Line { e: string; t: number; day: number; k: string; s: string; sd: string; q: number; l: number; tp: number | null; py: string; x: string }
export interface Header { base_date: string; prices: Array<Record<string, number>>; envelopes: Record<string, { mandateId: string; scope: MandateScope }> }

export function loadWorkload(path: string): { header: Header; lines: Line[] } {
  const text = readFileSync(path, 'utf8').split('\n');
  const header = JSON.parse(text[0]!) as Header;
  const lines: Line[] = [];
  for (let i = 1; i < text.length; i += 1) if (text[i]) lines.push(JSON.parse(text[i]!) as Line);
  return { header, lines };
}

export function arg(name: string, fallback?: string): string | undefined {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : fallback;
}

/** A clock and a trusted-price source the benchmark moves forward step by step (the receiver reads both through its options). */
export class Market {
  step = 0;
  day = 0;
  private readonly base: number;
  constructor(readonly header: Header) { this.base = Date.parse(header.base_date + 'T12:00:00Z'); }
  at(step: number, day: number): void { this.step = step; this.day = day; }
  now = (): number => this.base + this.day * 86_400_000;
  quote = (symbol: string): number | undefined => this.header.prices[this.step]?.[symbol];
}

export function openCore(path: string, name: string, header: Header, market: Market, opts: { fast?: boolean; mutations?: { idempotencyOff?: boolean; budgetLockOff?: boolean }; verifyOnOpen?: boolean } = {}): ReceiverCore {
  const env = header.envelopes[name]!;
  return new ReceiverCore({ ledgerPath: path, mandateId: env.mandateId, mandate: env.scope, quoteSource: market.quote, now: market.now,
    fast: opts.fast, mutations: opts.mutations, verifyOnOpen: opts.verifyOnOpen });
}

export const toOrder = (l: Line): ProposedOrder => ({ symbol: l.s, side: l.sd, quantity: l.q, limitPrice: l.l, clientOrderId: l.k });
export const asPy = (d: Decision): string => (d.decision === 'filled' ? 'allow' : d.decision === 'held' ? 'hold' : 'refuse');

export function pct(ns: number[]): Record<string, number> {
  if (!ns.length) return { n: 0 };
  const a = Float64Array.from(ns).sort();
  const q = (p: number) => {
    const r = (p / 100) * (a.length - 1);
    const lo = Math.floor(r), hi = Math.ceil(r);
    return (a[lo]! + (a[hi]! - a[lo]!) * (r - lo)) / 1000;
  };
  const mean = a.reduce((s, v) => s + v, 0) / a.length / 1000;
  const r2 = (v: number) => Math.round(v * 100) / 100;
  return { n: a.length, p50: r2(q(50)), p90: r2(q(90)), p99: r2(q(99)), p999: r2(q(99.9)), max: r2(a[a.length - 1]! / 1000), mean: r2(mean) };
}

export const hr = (): bigint => process.hrtime.bigint();
