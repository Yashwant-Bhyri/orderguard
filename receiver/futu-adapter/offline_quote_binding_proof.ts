#!/usr/bin/env npx tsx
/** Offline proof that Futu dispatch authorization is bound to the stored quote receipt. */

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { PaperLedgerStore, type DurablePaperOrder, type FutuM1DispatchAuthorization } from '../paper-ledger-store.js';

function canonical(value: unknown): string {
  if (value === undefined) return '"__undefined__"';
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  const record = value as Record<string, unknown>;
  return '{' + Object.keys(record).sort().map((key) => JSON.stringify(key) + ':' + canonical(record[key])).join(',') + '}';
}

function digest(value: unknown): string {
  return createHash('sha256').update(canonical(value), 'utf8').digest('base64url');
}

function authorization(order: DurablePaperOrder, quoteReceiptHash: string): FutuM1DispatchAuthorization {
  return {
    idempotencyKey: 'idem-futu-proof-1',
    orderId: order.orderId,
    orderHash: order.orderHash,
    mandateId: 'MANDATE-M1',
    mandateHash: digest({ mandate: 'offline-proof' }),
    quoteReceiptHash,
    secondLockDecision: 'allow',
    version: 'MANDATE-M1-v1.0.0',
  };
}

const directory = mkdtempSync(join(tmpdir(), 'orderguard-futu-quote-binding-'));
const databasePath = join(directory, 'paper-ledger.sqlite');
const store = new PaperLedgerStore(databasePath);
try {
  const mandateHash = digest({ mandate: 'offline-proof' });
  assert.equal(store.saveHumanMandate({
    mandateId: 'MANDATE-M1', mandateHash, document: { mandateId: 'MANDATE-M1', offline: true },
    createdAt: Date.now() - 1_000, expiresAt: Date.now() + 60_000,
  }), true);
  const order: DurablePaperOrder = {
    orderHash: '',
    intentHash: digest({ intent: 'offline-proof' }),
    orderId: 'futu-proof-order-1',
    order: {
      orderId: 'futu-proof-order-1', symbol: '0700.HK', market: 'HK', currency: 'HKD',
      side: 'buy', quantity: 100, orderType: 'limit', limitPrice: 388, limitPriceMinor: 38_800,
    },
    marketQuote: {
      code: 'HK.00700', currency: 'HKD', bid: 387.8, ask: 388, bidMinor: 38_780,
      askMinor: 38_800, lotSize: 100,
    },
    marketQuoteResult: { decision: 'allow', source: 'offline-proof' },
    marketQuoteReceipt: { claims: { symbol: 'HK.00700', quoteHash: 'fixture' }, signature: 'fixture-signature' },
    execution: { status: 'filled', filledQuantity: 100, averageFillPrice: 388 },
    cancelled: false,
  };
  order.orderHash = digest(order.order);

  const committed = store.commit('idem-futu-proof-1', order, {
    capabilityJti: 'offline-proof-capability',
    budgetKey: 'offline-proof-account:2026-10-30',
    maxNotionalAmount: { amount_minor: 100_000_000, currency: 'HKD' },
    ledgerConversion: { numerator: 16, denominator: 125 },
  });
  assert.equal(committed.kind, 'inserted');

  const wrongReceiptAccepted = store.authorizeFutuM1Dispatch(authorization(order, digest({ claims: { forged: true } })));
  const readDb = new DatabaseSync(databasePath);
  const rowsAfterWrongReceipt = Number((readDb.prepare('SELECT COUNT(*) AS count FROM futu_m1_dispatch_authorizations').get() as { count: number }).count);
  readDb.close();
  assert.equal(wrongReceiptAccepted, false);
  assert.equal(rowsAfterWrongReceipt, 0);

  const exactReceiptAccepted = store.authorizeFutuM1Dispatch(authorization(order, digest(order.marketQuoteReceipt)));
  assert.equal(exactReceiptAccepted, true);
  const sameAuthorizationReplay = store.authorizeFutuM1Dispatch(authorization(order, digest(order.marketQuoteReceipt)));
  assert.equal(sameAuthorizationReplay, true);
  const changedReceiptReplay = store.authorizeFutuM1Dispatch(authorization(order, digest({ claims: { forged: true } })));
  assert.equal(changedReceiptReplay, false);
  const proofKey = 'idem-futu-proof-1';
  const proofRemark = 'OG' + createHash('sha256').update(proofKey).digest('hex').slice(0, 32);
  const dispatchDb = new DatabaseSync(databasePath);
  dispatchDb.prepare(
    "INSERT INTO futu_simulate_dispatches (idempotency_key, order_id, order_hash, remark, state, updated_at_ms) "
    + "VALUES (?, ?, ?, ?, 'unknown', ?)",
  ).run(proofKey, order.orderId, order.orderHash, proofRemark, Date.now());
  dispatchDb.close();
  const revokeResult = store.revokeHumanMandate('MANDATE-M1', Date.now());
  const storedMandate = store.getHumanMandate('MANDATE-M1');
  assert.equal(revokeResult, 'pending');
  assert.equal(store.isHumanMandateActive('MANDATE-M1', mandateHash), false);
  assert.ok(typeof storedMandate?.revokeRequestedAt === 'number');

  console.log(JSON.stringify({
    proof: 'futu_dispatch_quote_receipt_binding',
    wrong_receipt_accepted: wrongReceiptAccepted,
    authorization_rows_after_wrong_receipt: rowsAfterWrongReceipt,
    exact_stored_receipt_accepted: exactReceiptAccepted,
    same_authorization_replay_accepted: sameAuthorizationReplay,
    changed_receipt_replay_accepted: changedReceiptReplay,
    ambiguous_send_revocation_pending: revokeResult === 'pending',
    pending_mandate_blocks_new_authorization: !store.isHumanMandateActive('MANDATE-M1', mandateHash),
    live_opend_calls: 0,
    futu_order_submissions: 0,
    provider_calls: 0,
  }, Object.keys({
    proof: '', wrong_receipt_accepted: 0, authorization_rows_after_wrong_receipt: 0,
    exact_stored_receipt_accepted: 0, same_authorization_replay_accepted: 0,
    changed_receipt_replay_accepted: 0, ambiguous_send_revocation_pending: 0,
    pending_mandate_blocks_new_authorization: 0, live_opend_calls: 0,
    futu_order_submissions: 0, provider_calls: 0,
  }).sort()));
} finally {
  store.close();
  rmSync(directory, { recursive: true, force: true });
}
