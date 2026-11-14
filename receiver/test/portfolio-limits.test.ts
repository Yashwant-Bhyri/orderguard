// Optional signed portfolio limits in the receiver: per-symbol daily cap, net position cap, orders per day.
// Computed from the SQLite ledger in integer cents inside the commit transaction; an absent field means no limit.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import { ReceiverCore, type MandateScope } from '../core/receiver-core.ts';
import { SignedPaperPolicy } from '../core/paper-policy.ts';

const DAY = Date.parse('2026-03-02T12:00:00Z');
const BASE: MandateScope = {
  symbols: ['AAPL', 'MSFT'], sides: ['buy', 'sell'], maxOrderNotionalUsd: 5000, maxDailyNotionalUsd: 100000, priceBandPct: 5,
  expiresAt: '2026-04-01T00:00:00Z', referencePrices: { AAPL: 100, MSFT: 200 },
};
const o = (id: string, quantity: number, over: Record<string, unknown> = {}) =>
  ({ symbol: 'AAPL', side: 'buy', quantity, limitPrice: 100, clientOrderId: id, ...over });

function make(scope: Partial<MandateScope> = {}, clock = { now: DAY }) {
  const core = new ReceiverCore({ ledgerPath: ':memory:', mandateId: 'm1', mandate: { ...BASE, ...scope }, fast: true, now: () => clock.now });
  return { core, clock };
}

test('maxSymbolDailyNotionalUsd allows exactly at the cap and refuses one cent over', async () => {
  const { core } = make({ maxSymbolDailyNotionalUsd: 1000 });
  assert.equal((await core.propose(o('a', 10))).decision, 'filled');                     // $1,000.00: at the cap
  const over = await core.propose(o('b', 1));
  assert.equal(over.reason, 'symbol_daily_cap');
  assert.equal((await core.propose(o('c', 1, { symbol: 'MSFT', limitPrice: 200 }))).decision, 'filled'); // another symbol is unaffected
  core.close();
  const cent = make({ maxSymbolDailyNotionalUsd: 1000, referencePrices: { AAPL: 100.001, MSFT: 200 } }).core;
  const r = await cent.propose(o('d', 10, { limitPrice: 100.001 }));                     // $1,000.01: one cent over
  assert.equal(r.reason, 'symbol_daily_cap');
  cent.close();
});

test('the symbol cap counts held orders and resets on the next UTC day', async () => {
  const { core, clock } = make({ maxSymbolDailyNotionalUsd: 1000, stepUpThresholdUsd: 500 });
  assert.equal((await core.propose(o('h', 6))).decision, 'held');                        // $600 held still counts
  assert.equal((await core.propose(o('x', 5))).reason, 'symbol_daily_cap');
  clock.now += 86_400_000;
  assert.equal((await core.propose(o('y', 5))).decision, 'filled');
  core.close();
});

test('maxPositionUsd allows exactly at the cap, refuses one cent over, and is net of sells', async () => {
  const { core } = make({ maxPositionUsd: 1000 });
  assert.equal((await core.propose(o('b1', 10))).decision, 'filled');                    // long $1,000.00
  assert.equal((await core.propose(o('b2', 1))).reason, 'position_cap');
  assert.equal((await core.propose(o('s1', 15, { side: 'sell' }))).decision, 'filled');  // net -5, reduces then flips within the cap
  assert.equal((await core.propose(o('s2', 5, { side: 'sell' }))).decision, 'filled');   // net -10: $1,000.00 short
  assert.equal((await core.propose(o('s3', 1, { side: 'sell' }))).reason, 'position_cap');
  assert.equal((await core.propose(o('b3', 20))).decision, 'filled');                    // back to +10
  core.close();
  const cent = make({ maxPositionUsd: 1000, referencePrices: { AAPL: 100.001, MSFT: 200 } }).core;
  assert.equal((await cent.propose(o('c', 10, { limitPrice: 100.001 }))).reason, 'position_cap'); // $1,000.01
  cent.close();
});

test('held orders count toward the position in the direction that grows exposure', async () => {
  const { core } = make({ maxPositionUsd: 1000, stepUpThresholdUsd: 500 });
  assert.equal((await core.propose(o('h1', 6))).decision, 'held');                       // +6 if approved
  assert.equal((await core.propose(o('b', 5))).reason, 'position_cap');                  // 6 + 5 = 11 shares, $1,100
  assert.equal((await core.propose(o('s', 4, { side: 'sell' }))).decision, 'filled');    // a held buy is never assumed to offset a sell: |0 - 4| and |6 - 4| both fit
  assert.equal((await core.propose(o('h2', 6, { side: 'sell' }))).decision, 'held');     // -4 - 6 = -10 shares: exactly $1,000
  assert.equal((await core.propose(o('s2', 1, { side: 'sell' }))).reason, 'position_cap');
  core.close();
});

test('maxOrdersPerDay counts filled and held orders, not denied ones, and resets daily', async () => {
  const { core, clock } = make({ maxOrdersPerDay: 3, stepUpThresholdUsd: 500 });
  assert.equal((await core.propose(o('1', 1))).decision, 'filled');
  assert.equal((await core.propose(o('2', 6))).decision, 'held');
  assert.equal((await core.propose(o('big', 100))).reason, 'per_order_cap');             // denied: consumes nothing
  assert.equal((await core.propose(o('3', 1))).decision, 'filled');                      // third counted order: at the cap
  assert.equal((await core.propose(o('4', 1))).reason, 'order_count_cap');
  assert.equal((await core.propose(o('1', 1))).replay, true);                            // a replay is answered from the ledger, not refused
  clock.now += 86_400_000;
  assert.equal((await core.propose(o('5', 1))).decision, 'filled');
  core.close();
});

test('a mandate without the fields behaves exactly as before', async () => {
  const { core } = make();
  for (let i = 0; i < 25; i++) assert.equal((await core.propose(o(`n${i}`, 40))).decision, 'filled'); // 25 orders, $4,000 each, one symbol, net +1000 shares
  assert.equal((await core.propose(o('over', 40))).reason, 'daily_cap');                  // only the existing daily cap bites ($104,000 > $100,000)
  core.close();
});

test('concurrent orders can never together pass the symbol cap, the position cap or the order count', async () => {
  const sym = make({ maxSymbolDailyNotionalUsd: 1000, maxDailyNotionalUsd: 100000 }).core;
  const rs = await Promise.all(Array.from({ length: 60 }, (_, i) => sym.propose(o(`s${i}`, 1))));
  assert.equal(rs.filter((r) => r.decision === 'filled').length, 10);                    // exactly $1,000 / $100
  assert.ok(sym.orders().filter((x) => x.status === 'filled').reduce((a, x) => a + x.notionalUsd, 0) <= 1000);
  assert.equal(sym.verifyLedger().ok, true);
  sym.close();
  const pos = make({ maxPositionUsd: 700 }).core;
  const ps = await Promise.all(Array.from({ length: 40 }, (_, i) => pos.propose(o(`p${i}`, 1))));
  assert.equal(ps.filter((r) => r.decision === 'filled').length, 7);
  pos.close();
  const cnt = make({ maxOrdersPerDay: 5 }).core;
  const cs = await Promise.all(Array.from({ length: 40 }, (_, i) => cnt.propose(o(`c${i}`, 1, { symbol: i % 2 ? 'AAPL' : 'MSFT', limitPrice: i % 2 ? 100 : 200 }))));
  assert.equal(cs.filter((r) => r.decision === 'filled').length, 5);
  assert.equal(cs.filter((r) => r.reason === 'order_count_cap').length, 35);
  cnt.close();
});

test('an invalid portfolio limit in the mandate refuses to start rather than silently not limiting', () => {
  for (const bad of [{ maxOrdersPerDay: 0 }, { maxOrdersPerDay: 2.5 }, { maxPositionUsd: -1 }, { maxSymbolDailyNotionalUsd: Number.NaN }]) {
    assert.throws(() => make(bad as Partial<MandateScope>));
  }
});

// ---- signed policy: parsing and sub-mandate containment ----

function policy(parent: Record<string, unknown>) {
  const keys = generateKeyPairSync('ed25519');
  const owner = Buffer.from(keys.publicKey.export({ format: 'jwk' }).x!, 'base64url').toString('base64');
  const bytes = Buffer.from(JSON.stringify(parent));
  const proof = { payload: bytes.toString('base64'), signature: sign(null, bytes, keys.privateKey).toString('base64') };
  return new SignedPaperPolicy(proof, owner);
}
const PARENT = { ...BASE, stepUpAboveUsd: 4000, maxSymbolDailyNotionalUsd: 20000, maxPositionUsd: 30000, maxOrdersPerDay: 50 };
const draft = (over: Record<string, unknown>) => ({ ...PARENT, ...over });
const fits = (p: SignedPaperPolicy, d: Record<string, unknown>) => { try { p.containedDraft(d, DAY); return true; } catch { return false; } };

test('the signed parent parses the three fields and a child may be equal or tighter', () => {
  const p = policy(PARENT);
  assert.equal(p.parent.maxSymbolDailyNotionalUsd, 20000);
  assert.equal(p.parent.maxPositionUsd, 30000);
  assert.equal(p.parent.maxOrdersPerDay, 50);
  assert.ok(fits(p, draft({})));
  assert.ok(fits(p, draft({ maxSymbolDailyNotionalUsd: 19999.99, maxPositionUsd: 100, maxOrdersPerDay: 1 })));
});

test('a child can never be looser than its parent, and cannot drop a limit the parent has', () => {
  const p = policy(PARENT);
  assert.ok(!fits(p, draft({ maxSymbolDailyNotionalUsd: 20000.01 })));
  assert.ok(!fits(p, draft({ maxPositionUsd: 30000.01 })));
  assert.ok(!fits(p, draft({ maxOrdersPerDay: 51 })));
  for (const field of ['maxSymbolDailyNotionalUsd', 'maxPositionUsd', 'maxOrdersPerDay']) {
    const dropped: Record<string, unknown> = { ...PARENT };
    delete dropped[field];
    assert.ok(!fits(p, dropped), `dropping ${field} must be refused`);
  }
});

test('a parent without the fields lets a child add them; malformed values are refused', () => {
  const p = policy(BASE);
  assert.ok(fits(p, { ...BASE, maxPositionUsd: 500, maxOrdersPerDay: 3, maxSymbolDailyNotionalUsd: 900 }));
  assert.ok(fits(p, BASE));
  for (const bad of [{ maxOrdersPerDay: 0 }, { maxOrdersPerDay: 1.5 }, { maxOrdersPerDay: '5' }, { maxPositionUsd: 0 }, { maxPositionUsd: null },
    { maxSymbolDailyNotionalUsd: -5 }, { maxSymbolDailyNotionalUsd: 10.001 }]) {
    assert.ok(!fits(p, { ...BASE, ...bad }), JSON.stringify(bad));
  }
  assert.throws(() => policy({ ...BASE, maxOrdersPerDay: 0 }));
});
