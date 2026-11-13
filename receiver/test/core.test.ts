import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ReceiverCore, type MandateScope } from '../core/receiver-core.ts';
import { normaliseSymbol } from '../core/valuation.ts';
import { SignedPaperPolicy } from '../core/paper-policy.ts';
// @ts-expect-error plain .mjs helper
import { virtualPasskey, registrationResponse, authenticationResponse } from '../bridge/synthetic-passkey.mjs';

const MANDATE: MandateScope = {
  symbols: ['AAPL', 'MSFT'], sides: ['buy'], maxOrderNotionalUsd: 10000, maxDailyNotionalUsd: 20000, priceBandPct: 5,
  expiresAt: new Date(Date.now() + 3_600_000).toISOString(), referencePrices: { AAPL: 222.7, MSFT: 420.18 },
};

function make(overrides: Partial<MandateScope> = {}, extra: Record<string, unknown> = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'og-core-'));
  const core = new ReceiverCore({ ledgerPath: join(dir, 'l.sqlite'), mandateId: 'm1', mandate: { ...MANDATE, ...overrides }, fast: true, ...extra });
  return { core, done: () => { core.close(); rmSync(dir, { recursive: true, force: true }); } };
}

test('symbol normalisation: trim, NFKC, uppercase, ASCII only', () => {
  assert.deepEqual(normaliseSymbol('  aapl '), { ok: true, symbol: 'AAPL' });
  assert.deepEqual(normaliseSymbol('ＡＡＰＬ'), { ok: true, symbol: 'AAPL' }); // fullwidth folds to ASCII under NFKC
  assert.equal(normaliseSymbol('АAAPL').ok, false); // Cyrillic A + Latin AAPL
  assert.equal(normaliseSymbol('AAP​L').ok, false); // zero-width space
  assert.equal(normaliseSymbol('ßX').ok, false); // sharp s would uppercase to ASCII SS
  assert.equal(normaliseSymbol('AA PL').ok, false);
});

test('honest 44-share order fills at the trusted price; lowercase symbol maps to AAPL', () => {
  const { core, done } = make();
  return core.propose({ symbol: 'aapl', side: 'buy', quantity: 44, limitPrice: 222.7, clientOrderId: 'c1' }).then((d) => {
    assert.equal(d.decision, 'filled');
    assert.equal(d.ledgerEffect, true);
    assert.equal(d.notionalUsd, 9798.8);
    assert.equal(core.orders()[0]!.symbol, 'AAPL');
    done();
  });
});

test('fake split (440 shares at $22.30 vs trusted $222.70) is denied and leaves no effect', async () => {
  const { core, done } = make();
  const d = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 440, limitPrice: 22.3, clientOrderId: 'split' });
  assert.equal(d.decision, 'denied');
  assert.equal(d.reason, 'limit_outside_band');
  assert.equal(d.ledgerEffect, false);
  assert.equal(core.orders().length, 0);
  done();
});

test('cap is valued at the trusted price, not the order limit price', async () => {
  // 440 x 22.30 = 9,812 would slip under the 10,000 cap if valued at the limit price; 440 x 222.70 = 97,988 must not.
  const { core, done } = make({ priceBandPct: 100 }); // band wide open on purpose, so only the cap can stop it
  const d = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 440, limitPrice: 22.3, clientOrderId: 'cap' });
  assert.equal(d.decision, 'denied');
  assert.equal(d.reason, 'per_order_cap');
  done();
});

test('Cyrillic look-alike, unlisted ticker and sell are denied', async () => {
  const { core, done } = make();
  const cyr = await core.propose({ symbol: 'АAAPL', side: 'buy', quantity: 1, limitPrice: 222.7, clientOrderId: 'a' });
  assert.equal(cyr.reason, 'non_ascii_symbol');
  const unl = await core.propose({ symbol: 'TSLA', side: 'buy', quantity: 1, limitPrice: 300, clientOrderId: 'b' });
  assert.equal(unl.reason, 'unlisted_symbol');
  const sell = await core.propose({ symbol: 'AAPL', side: 'sell', quantity: 1, limitPrice: 222.7, clientOrderId: 'c' });
  assert.equal(sell.reason, 'side_not_allowed');
  assert.equal(core.orders().length, 0);
  done();
});

test('trusted quote source is used when the mandate has no price; an unpriced symbol is denied', async () => {
  const { core, done } = make({ symbols: ['AAPL', 'NVDA', 'IBM'] }, { quoteSource: (s: string) => (s === 'NVDA' ? 100 : undefined) });
  const ok = await core.propose({ symbol: 'NVDA', side: 'buy', quantity: 10, limitPrice: 101, clientOrderId: 'n1' });
  assert.equal(ok.decision, 'filled');
  const none = await core.propose({ symbol: 'IBM', side: 'buy', quantity: 1, limitPrice: 100, clientOrderId: 'n2' });
  assert.equal(none.reason, 'no_trusted_price');
  done();
});

test('daily cap is a running total in trusted dollars', async () => {
  const { core, done } = make();
  const a = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 44, limitPrice: 222.7, clientOrderId: 'd1' });
  const b = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 44, limitPrice: 222.7, clientOrderId: 'd2' });
  const c = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 44, limitPrice: 222.7, clientOrderId: 'd3' });
  assert.deepEqual([a.decision, b.decision, c.decision], ['filled', 'filled', 'denied']);
  assert.equal(c.reason, 'daily_cap');
  done();
});

test('retried clientOrderId returns the same order and never a second effect; a changed body conflicts', async () => {
  const { core, done } = make();
  const first = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 5, limitPrice: 222.7, clientOrderId: 'r1' });
  const again = await core.propose({ symbol: 'aapl', side: 'buy', quantity: 5, limitPrice: 222.7, clientOrderId: 'r1' });
  assert.equal(again.orderId, first.orderId);
  assert.equal(again.ledgerEffect, false);
  assert.equal(again.replay, true);
  const changed = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 6, limitPrice: 222.7, clientOrderId: 'r1' });
  assert.equal(changed.reason, 'idempotency_conflict');
  assert.equal(core.orders().length, 1);
  done();
});

test('after revoke nothing commits; ledger integrity holds', async () => {
  const { core, done } = make();
  await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 1, limitPrice: 222.7, clientOrderId: 'v1' });
  core.revoke();
  const d = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 1, limitPrice: 222.7, clientOrderId: 'v2' });
  assert.equal(d.reason, 'mandate_revoked');
  assert.equal(core.orders().length, 1);
  assert.equal(core.ledgerIntegrity(), true);
  done();
});

test('an issuer that reports the mandate inactive, or throws, fails closed', async () => {
  const off = make({}, { authority: { isActive: async () => false } });
  assert.equal((await off.core.propose({ symbol: 'AAPL', side: 'buy', quantity: 1, limitPrice: 222.7, clientOrderId: 'x' })).decision, 'denied');
  off.done();
  const boom = make({}, { authority: { isActive: async () => { throw new Error('down'); } } });
  assert.equal((await boom.core.propose({ symbol: 'AAPL', side: 'buy', quantity: 1, limitPrice: 222.7, clientOrderId: 'x' })).decision, 'denied');
  boom.done();
});

test('expired mandate is denied', async () => {
  const { core, done } = make({ expiresAt: new Date(Date.now() - 1000).toISOString() });
  assert.equal((await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 1, limitPrice: 222.7, clientOrderId: 'e' })).reason, 'mandate_expired');
  done();
});

// ---- human step-up ----

async function withPasskey(core: ReceiverCore) {
  const origin = 'http://127.0.0.1:8123';
  const passkey = virtualPasskey();
  await core.registerOwnerPasskey(registrationResponse(passkey, core.passkeyRegistrationChallenge(), origin));
  return { passkey, origin };
}

test('orders above the step-up threshold are held, reserve budget, and fill only on the owner passkey', async () => {
  const origin = 'http://127.0.0.1:8123';
  const { core, done } = make({ stepUpThresholdUsd: 5000 }, { webauthn: { origin, rpId: '127.0.0.1' } });
  const { passkey } = await withPasskey(core);
  const small = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 10, limitPrice: 222.7, clientOrderId: 's1' });
  assert.equal(small.decision, 'filled');
  const big = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 30, limitPrice: 222.7, clientOrderId: 's2' });
  assert.equal(big.decision, 'held');
  assert.equal(big.ledgerEffect, false);
  assert.equal(core.orders().find((o) => o.orderId === big.orderId)!.status, 'held');
  // a signature for a different challenge, or no challenge, is refused
  const stale = authenticationResponse(passkey, 'AAAA', origin);
  assert.equal((await core.approve(big.orderId!, stale)).reason, 'approval_invalid');
  // approval consumed its challenge; a fresh one is needed
  const ch = core.beginApproval(big.orderId!);
  const approved = await core.approve(big.orderId!, authenticationResponse(passkey, ch.challenge, origin));
  assert.equal(approved.decision, 'filled');
  assert.equal(approved.ledgerEffect, true);
  // replaying the approval does not create a second effect
  const again = await core.approve(big.orderId!, authenticationResponse(passkey, ch.challenge, origin));
  assert.equal(again.ledgerEffect, false);
  assert.equal(core.orders().filter((o) => o.status === 'filled').length, 2);
  assert.equal(core.ledgerIntegrity(), true);
  done();
});

test('a held order cannot be approved after revocation, and a forged assertion is refused', async () => {
  const origin = 'http://127.0.0.1:8123';
  const { core, done } = make({ stepUpThresholdUsd: 5000 }, { webauthn: { origin, rpId: '127.0.0.1' } });
  const { passkey } = await withPasskey(core);
  const held = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 30, limitPrice: 222.7, clientOrderId: 'h1' });
  const stranger = virtualPasskey(); // a different device, not the enrolled owner
  const ch = core.beginApproval(held.orderId!);
  assert.equal((await core.approve(held.orderId!, authenticationResponse(stranger, ch.challenge, origin))).reason, 'approval_invalid');
  const held2 = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: 30, limitPrice: 222.7, clientOrderId: 'h2' });
  const ch2 = core.beginApproval(held2.orderId!);
  core.revoke();
  const late = await core.approve(held2.orderId!, authenticationResponse(passkey, ch2.challenge, origin));
  assert.equal(late.decision, 'denied');
  assert.equal(core.orders().filter((o) => o.status === 'filled').length, 0);
  done();
});

test('a delayed order uses the new signed revision and the revision survives core restart', async () => {
  const keys = generateKeyPairSync('ed25519');
  const owner = Buffer.from(keys.publicKey.export({ format: 'jwk' }).x!, 'base64url').toString('base64');
  const proof = (body: object) => {
    const bytes = Buffer.from(JSON.stringify(body));
    return { payload: bytes.toString('base64'), signature: sign(null, bytes, keys.privateKey).toString('base64') };
  };
  const signedPolicy = new SignedPaperPolicy(proof(MANDATE), owner);
  let resume!: (active: boolean) => void;
  const delayed = new Promise<boolean>((resolve) => { resume = resolve; });
  let calls = 0;
  let now = Date.now();
  const expiresAt = new Date(now + 60_000).toISOString();
  const { core, done } = make({}, { signedPolicy, now: () => now,
    authority: { isActive: () => ++calls === 1 ? delayed : Promise.resolve(true) } });
  try {
    const original = core.policy()!;
    const pending = core.propose({ symbol: 'AAPL', side: 'buy', quantity: 4, limitPrice: 222.7, clientOrderId: 'delayed' });
    const activation = await core.activatePolicy(proof({ purpose: 'orderguard.paper-draft-activation.v1',
      parentId: original.parentId, ledgerId: original.ledgerId, revision: original.revision,
      draft: { ...MANDATE, maxOrderNotionalUsd: 500, expiresAt } }));
    resume(true);
    assert.equal((await pending).reason, 'per_order_cap');
    assert.equal(core.orders().length, 0);
    core.restart();
    assert.deepEqual(core.policy(), activation.policy);
    assert.equal(core.events().filter((event) => event.type === 'policy_activated').length, 1);
    const valid = { symbol: 'AAPL', side: 'buy', quantity: 1, limitPrice: 222.7, clientOrderId: 'within-draft' };
    assert.equal((await core.propose(valid)).ledgerEffect, true);
    now = Date.parse(expiresAt);
    assert.equal((await core.propose({ ...valid, clientOrderId: 'after-expiry' })).reason, 'mandate_expired');
    assert.equal(core.ledgerIntegrity(), true);
  } finally {
    done();
  }
});
