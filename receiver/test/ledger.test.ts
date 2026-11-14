// Persistence, tamper detection, concurrency, clock and malformed-input tests for the receiver core and its ledger files.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { LedgerError, ReceiverCore, type MandateScope } from '../core/receiver-core.ts';
import { acquireLedgerLock, backupLedger, exportLedger, verifyLedgerFile, LedgerFileError } from '../core/ledger-files.ts';

const SCOPE: MandateScope = {
  symbols: ['AAPL', 'MSFT'], sides: ['buy'], maxOrderNotionalUsd: 10000, maxDailyNotionalUsd: 20000, priceBandPct: 5,
  expiresAt: new Date(Date.now() + 3_600_000).toISOString(), referencePrices: { AAPL: 222.7, MSFT: 420.18 },
};
const order = (id: string, over: Record<string, unknown> = {}) => ({ symbol: 'AAPL', side: 'buy', quantity: 10, limitPrice: 222.7, clientOrderId: id, ...over });

function sandbox() {
  const dir = mkdtempSync(join(tmpdir(), 'og-ledger-'));
  const path = join(dir, 'ledger.sqlite');
  const open = (extra: Record<string, unknown> = {}, scope: Partial<MandateScope> = {}) =>
    new ReceiverCore({ ledgerPath: path, mandateId: 'm1', mandate: { ...SCOPE, ...scope }, ...extra });
  const side = (sql: string) => { const db = new DatabaseSync(path); try { db.exec(sql); } finally { db.close(); } };
  return { dir, path, open, side, done: () => rmSync(dir, { recursive: true, force: true }) };
}

test('idempotency and the daily budget survive a process restart', async () => {
  const s = sandbox();
  try {
    const first = s.open();
    const a = await first.propose(order('p1', { quantity: 44 }));
    assert.equal(a.decision, 'filled');
    first.close();
    const second = s.open(); // a brand new process: nothing in memory
    const replay = await second.propose(order('p1', { quantity: 44 }));
    assert.equal(replay.orderId, a.orderId);
    assert.equal(replay.ledgerEffect, false);
    assert.equal(replay.replay, true);
    assert.equal((await second.propose(order('p1', { quantity: 45 }))).reason, 'idempotency_conflict');
    assert.equal((await second.propose(order('p2', { quantity: 44 }))).decision, 'filled');
    assert.equal((await second.propose(order('p3', { quantity: 44 }))).reason, 'daily_cap'); // 3 x 9,798.80 > 20,000 across the restart
    assert.equal(second.orders().length, 2);
    assert.equal(second.verifyLedger().ok, true);
    second.close();
  } finally { s.done(); }
});

test('revocation is durable across restart and cannot be undone by deleting the flag', async () => {
  const s = sandbox();
  try {
    const core = s.open();
    await core.propose(order('r1'));
    core.revoke();
    core.close();
    const again = s.open();
    assert.equal(again.revoked, true);
    assert.equal((await again.propose(order('r2'))).reason, 'mandate_revoked');
    again.close();
    s.side("DELETE FROM meta WHERE k = 'revoked_seq'");
    assert.throws(() => s.open(), (e: unknown) => e instanceof LedgerError && e.code === 'tampered' && /revoked flag/.test(e.message));
  } finally { s.done(); }
});

test('a ledger that was edited is refused at open, and left exactly as found', async () => {
  const tamper: Array<[string, string, RegExp]> = [
    ['order amount', "UPDATE orders SET notional_cents = 1 WHERE seq = (SELECT MIN(seq) FROM orders)", /changed after it was recorded|notional/],
    ['order quantity', "UPDATE orders SET quantity = 1 WHERE seq = (SELECT MIN(seq) FROM orders)", /changed after it was recorded|notional/],
    ['event payload', "UPDATE events SET payload = replace(payload, 'AAPL', 'MSFT') WHERE seq = 1", /contents do not match their hash/],
    ['order row deleted', "DELETE FROM orders WHERE seq = (SELECT MIN(seq) FROM orders)", /row is missing/],
    ['middle event deleted', "DELETE FROM events WHERE seq = 2", /sequence number|does not follow|has no creating event/],
    ['status flipped', "UPDATE orders SET status = 'cancelled', fill_price = NULL WHERE seq = (SELECT MIN(seq) FROM orders)", /status is cancelled but the log says filled/],
    ['order id forged', "UPDATE orders SET order_id = 'og_forged' WHERE seq = (SELECT MIN(seq) FROM orders)", /no creating event|missing/],
    ['action hash forged', "UPDATE orders SET action_hash = 'x' WHERE seq = (SELECT MIN(seq) FROM orders)", /action hash/],
  ];
  for (const [name, sql, pattern] of tamper) {
    const s = sandbox();
    try {
      const core = s.open();
      await core.propose(order('t1'));
      await core.propose(order('t2'));
      core.close();
      s.side(sql);
      const before = readFileSync(s.path);
      assert.throws(() => s.open(), (e: unknown) => e instanceof LedgerError && e.code === 'tampered' && pattern.test(e.message + e.problems.join(' ')), name);
      assert.equal(verifyLedgerFile(s.path).ok, false, name);
      assert.equal(readFileSync(s.path).equals(before), true, `${name}: a refused ledger must not be modified`);
    } finally { s.done(); }
  }
});

test('truncating the newest events is caught when the head was recorded elsewhere', async () => {
  const s = sandbox();
  try {
    const core = s.open();
    await core.propose(order('h1'));
    await core.propose(order('h2'));
    const head = core.verifyLedger().head;
    core.close();
    assert.equal(verifyLedgerFile(s.path, head).ok, true);
    s.side('DELETE FROM orders WHERE seq = (SELECT MAX(seq) FROM orders); DELETE FROM events WHERE seq = (SELECT MAX(seq) FROM events)');
    assert.equal(verifyLedgerFile(s.path).ok, true, 'a shorter chain is still internally consistent');
    assert.equal(verifyLedgerFile(s.path, head).ok, false);
    assert.throws(() => s.open({ expectHead: head }), (e: unknown) => e instanceof LedgerError && /truncated or replaced/.test(e.message));
  } finally { s.done(); }
});

test('a ledger belongs to one mandate, and a damaged or foreign file is unreadable not served', async () => {
  const s = sandbox();
  try {
    const core = s.open();
    await core.propose(order('b1'));
    core.close();
    assert.throws(() => new ReceiverCore({ ledgerPath: s.path, mandateId: 'other', mandate: SCOPE }), (e: unknown) => e instanceof LedgerError && e.code === 'bound_elsewhere' && /new ledger path/.test(e.message));
    writeFileSync(s.path, 'this is not a database'.repeat(50));
    assert.throws(() => s.open(), (e: unknown) => e instanceof LedgerError && e.code === 'unreadable' && !/\/(Users|home)\//.test(e.message));
  } finally { s.done(); }
});

test('a transaction that fails halfway leaves no partial write, and the retry is applied exactly once', async () => {
  const s = sandbox();
  try {
    const core = s.open();
    await core.propose(order('w0'));
    // The orders INSERT fails after the event was appended inside the same transaction.
    s.side("CREATE TRIGGER boom BEFORE INSERT ON orders WHEN NEW.client_order_id = 'w1' BEGIN SELECT RAISE(ABORT, 'disk full'); END");
    await assert.rejects(core.propose(order('w1')));
    assert.equal(core.orders().length, 1);
    assert.equal(core.events().length, 1, 'the event rolled back with the row');
    assert.equal(core.verifyLedger().ok, true);
    s.side('DROP TRIGGER boom');
    const retry = await core.propose(order('w1'));
    assert.equal(retry.decision, 'filled');
    assert.equal((await core.propose(order('w1'))).ledgerEffect, false);
    assert.equal(core.orders().length, 2);
    core.restart(); // crash right after: the reopened ledger verifies and the retry still replays
    assert.equal((await core.propose(order('w1'))).replay, true);
    core.close();
  } finally { s.done(); }
});

test('concurrent proposals racing the daily budget never overspend, and a duplicate storm is one effect', async () => {
  const s = sandbox();
  try {
    const core = s.open();
    // 25 distinct orders of 9,798.80 each against a 20,000 cap, plus 25 deliveries of one more id.
    const work = Array.from({ length: 25 }, (_, i) => core.propose(order(`c${i}`, { quantity: 44 })));
    const storm = Array.from({ length: 25 }, () => core.propose(order('storm', { quantity: 1 })));
    const results = await Promise.all([...work, ...storm]);
    const filled = results.filter((r) => r.ledgerEffect);
    assert.ok(filled.length <= 3, 'at most two big orders plus the single storm order take effect');
    assert.equal(core.orders().filter((o) => o.clientOrderId === 'storm').length, 1);
    assert.ok(core.snapshot().usedNotionalUsd <= 20000);
    assert.equal(core.verifyLedger().ok, true);
    core.close();
  } finally { s.done(); }
});

test('a revocation that lands while the issuer check is in flight wins', async () => {
  const s = sandbox();
  try {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let core!: ReceiverCore;
    core = s.open({ authority: { isActive: async () => { await gate; return true; } } });
    const pending = core.propose(order('v1'));
    core.revoke();
    release();
    const d = await pending;
    assert.equal(d.decision, 'denied');
    assert.equal(d.reason, 'mandate_revoked');
    assert.equal(core.orders().length, 0);
    core.close();
  } finally { s.done(); }
});

test('an issuer that never answers fails closed after the timeout', async () => {
  const s = sandbox();
  try {
    const core = s.open({ authority: { isActive: () => new Promise<boolean>(() => {}) }, authorityTimeoutMs: 40 });
    const started = Date.now();
    const d = await core.propose(order('slow'));
    assert.equal(d.decision, 'denied');
    assert.ok(Date.now() - started < 2000);
    assert.equal(core.orders().length, 0);
    core.close();
  } finally { s.done(); }
});

test('expiry is exclusive at the boundary, to the millisecond', async () => {
  const s = sandbox();
  try {
    const t0 = Date.parse('2030-01-01T12:00:00.000Z');
    let now = t0 - 1;
    const core = s.open({ now: () => now }, { expiresAt: new Date(t0).toISOString() });
    assert.equal((await core.propose(order('e1'))).decision, 'filled');
    now = t0;
    assert.equal((await core.propose(order('e2'))).reason, 'mandate_expired');
    now = t0 + 1;
    assert.equal((await core.propose(order('e3'))).reason, 'mandate_expired');
    assert.equal((await core.propose(order('e1'))).replay, true, 'a replay is not a new effect, even after expiry');
    core.close();
  } finally { s.done(); }
});

test('the budget resets at UTC midnight but a clock that steps backwards cannot reset it', async () => {
  const s = sandbox();
  try {
    let now = Date.parse('2030-01-01T23:59:59.000Z');
    const core = s.open({ now: () => now }, { expiresAt: '2031-01-01T00:00:00.000Z' });
    assert.equal((await core.propose(order('d1', { quantity: 44 }))).decision, 'filled');
    assert.equal((await core.propose(order('d2', { quantity: 44 }))).decision, 'filled');
    assert.equal((await core.propose(order('d3', { quantity: 44 }))).reason, 'daily_cap');
    now = Date.parse('2030-01-02T00:00:00.000Z');
    assert.equal((await core.propose(order('d4', { quantity: 44 }))).decision, 'filled', 'a new UTC day has a new budget');
    now = Date.parse('2030-01-01T10:00:00.000Z'); // clock stepped back a day
    assert.equal((await core.propose(order('d5', { quantity: 44 }))).decision, 'filled');
    assert.equal((await core.propose(order('d6', { quantity: 44 }))).reason, 'daily_cap', 'still charged to the newest day, not reset');
    assert.equal(core.verifyLedger().ok, true);
    core.close();
  } finally { s.done(); }
});

test('malformed, oversized and hostile requests are denied with no effect and never throw', async () => {
  const s = sandbox();
  try {
    const core = s.open();
    const bad: unknown[] = [
      null, undefined, 5, 'x', [], {}, order('x', { quantity: Number.NaN }), order('x', { quantity: Infinity }), order('x', { quantity: 2 ** 60 }),
      order('x', { quantity: 1.5 }), order('x', { quantity: -1 }), order('x', { quantity: '3' }), order('x', { limitPrice: Number.NaN }),
      order('x', { limitPrice: 1e13 }), order('x', { limitPrice: -1 }), order('x', { limitPrice: '222.7' }), order('x', { clientOrderId: '' }),
      order('x', { clientOrderId: 'a'.repeat(97) }), order('x', { clientOrderId: 'has space' }), order('x', { clientOrderId: { toString: () => 'x' } }),
      order('x', { side: { a: 1 } }), order('x', { side: 'b'.repeat(10_000) }), order('x', { symbol: 'A'.repeat(100_000) }), order('x', { symbol: { toString: () => 'AAPL' } }),
      JSON.parse('{"__proto__": {"symbol": "AAPL"}, "symbol": "AAPL"}'),
    ];
    for (const input of bad) {
      const d = await core.propose(input as never);
      assert.equal(d.ledgerEffect, false, JSON.stringify(input)?.slice(0, 80));
      assert.notEqual(d.decision, 'filled');
    }
    assert.equal(core.orders().length, 0);
    assert.equal((await core.propose(order('ok-after-garbage'))).decision, 'filled');
    core.close();
  } finally { s.done(); }
});

test('priorDecision answers a retry from the ledger without consulting anyone', async () => {
  const s = sandbox();
  try {
    let asked = 0;
    const core = s.open({ authority: { isActive: async () => { asked += 1; return true; } } });
    assert.equal(core.priorDecision(order('n1')), null);
    const first = await core.propose(order('n1'));
    asked = 0;
    const prior = core.priorDecision(order('n1'))!;
    assert.equal(prior.orderId, first.orderId);
    assert.equal(prior.ledgerEffect, false);
    assert.equal(core.priorDecision(order('n1', { quantity: 11 }))!.reason, 'idempotency_conflict');
    assert.equal(asked, 0);
    core.close();
  } finally { s.done(); }
});

test('export and backup produce verified copies, never overwrite, and refuse a tampered ledger', async () => {
  const s = sandbox();
  try {
    const core = s.open();
    await core.propose(order('x1'));
    core.revoke();
    core.close();
    const data = exportLedger(s.path);
    assert.equal(data.verification.ok, true);
    assert.equal(data.orders.length, 1);
    assert.equal(data.events.length, 2);
    assert.equal('passkey' in data.meta, false, 'no key material in an export');
    const copy = join(s.dir, 'backup.sqlite');
    const check = backupLedger(s.path, copy);
    assert.equal(check.ok, true);
    assert.equal(verifyLedgerFile(copy).head.hash, check.head.hash);
    assert.throws(() => backupLedger(s.path, copy), (e: unknown) => e instanceof LedgerFileError && e.code === 'exists');
    assert.equal(existsSync(copy + '.partial'), false);
    const restored = new ReceiverCore({ ledgerPath: copy, mandateId: 'm1', mandate: SCOPE });
    assert.equal(restored.revoked, true);
    assert.equal(restored.orders().length, 1);
    restored.close();
    s.side("UPDATE orders SET quantity = 2");
    assert.throws(() => backupLedger(s.path, join(s.dir, 'second.sqlite')), (e: unknown) => e instanceof LedgerFileError && e.code === 'tampered');
    assert.equal(existsSync(join(s.dir, 'second.sqlite')), false);
    assert.equal(exportLedger(s.path).verification.ok, false);
    assert.throws(() => verifyLedgerFile(join(s.dir, 'missing.sqlite')), (e: unknown) => e instanceof LedgerFileError && e.code === 'missing');
  } finally { s.done(); }
});

test('only one receiver may hold a ledger; a dead holder is taken over', () => {
  const dir = mkdtempSync(join(tmpdir(), 'og-lock-'));
  try {
    const path = join(dir, 'ledger.sqlite');
    writeFileSync(path + '.lock', String(process.ppid)); // a live process other than us
    assert.throws(() => acquireLedgerLock(path), (e: unknown) => e instanceof LedgerFileError && e.code === 'locked' && /different ledger path/.test(e.message));
    writeFileSync(path + '.lock', '2147483646'); // not a running process
    const release = acquireLedgerLock(path);
    assert.equal(readFileSync(path + '.lock', 'utf8'), String(process.pid));
    release();
    assert.equal(existsSync(path + '.lock'), false);
    release(); // idempotent
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
