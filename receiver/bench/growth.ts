// Receiver latency as its ledger grows: one envelope, one day, ample caps (with or without the portfolio limits), N fills in a row.
// Reports propose() latency per window of orders, so a cost that grows with the number of rows in the ledger is visible.
//
//   node --no-warnings --import tsx receiver/bench/growth.ts --dir DIR --orders N --window W --out OUT.json [--durable]

import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { ReceiverCore } from '../core/receiver-core.ts';
import { arg, hr, pct } from './common.ts';

const dir = arg('--dir')!;
const orders = Number(arg('--orders', '20000'));
const windowSize = Number(arg('--window', '2000'));
const durable = process.argv.includes('--durable');
mkdirSync(dir, { recursive: true });
const results: Record<string, unknown> = {};
for (const portfolio of [false, true]) {
  const path = join(dir, `growth-${portfolio ? 'portfolio' : 'plain'}.sqlite`);
  rmSync(path, { force: true });
  const scope = { symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'], sides: ['buy', 'sell'] as Array<'buy' | 'sell'>, maxOrderNotionalUsd: 1e6, maxDailyNotionalUsd: 1e12,
    priceBandPct: 1, expiresAt: '2099-01-01T00:00:00Z', referencePrices: { BTCUSDT: 73.77, ETHUSDT: 20.52, SOLUSDT: 83.39 },
    ...(portfolio ? { maxSymbolDailyNotionalUsd: 1e11, maxPositionUsd: 1e11, maxOrdersPerDay: 10_000_000 } : {}) };
  const core = new ReceiverCore({ ledgerPath: path, mandateId: 'growth', mandate: scope, fast: !durable, now: () => Date.parse('2026-01-05T12:00:00Z') });
  const windows: Array<Record<string, number>> = [];
  let lat: number[] = [];
  const syms = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'];
  const px: Record<string, number> = scope.referencePrices;
  for (let i = 0; i < orders; i += 1) {
    const s = syms[i % 3]!;
    const t0 = hr();
    const d = await core.propose({ symbol: s, side: i % 2 ? 'sell' : 'buy', quantity: 1 + (i % 7), limitPrice: px[s]!, clientOrderId: `g${i}` });
    lat.push(Number(hr() - t0));
    if (d.decision !== 'filled') throw new Error(`order ${i} was ${d.decision} (${d.reason})`);
    if (lat.length === windowSize) {
      windows.push({ rows_before: i + 1 - windowSize, ...pct(lat) });
      lat = [];
    }
  }
  core.close();
  rmSync(path, { force: true });
  rmSync(path + '-wal', { force: true });
  rmSync(path + '-shm', { force: true });
  results[portfolio ? 'with_portfolio_limits' : 'without_portfolio_limits'] = windows;
}
writeFileSync(arg('--out')!, JSON.stringify({ orders, window: windowSize, durable, ...results }));
