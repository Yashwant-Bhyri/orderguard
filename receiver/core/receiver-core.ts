// OrderGuard receiver core (layer L8): the final authority over the paper ledger.
//
// One class, one job: decide whether the EXACT canonical order may take effect under the
// current human-signed mandate, and if so commit it atomically. Everything that can take
// effect goes through propose() or approve(); there is no other write path to the ledger.
//
// Atomicity: node:sqlite is synchronous, so the commit body (revocation re-check,
// idempotency lookup, budget check, insert) runs inside one BEGIN IMMEDIATE transaction with
// no await in it. Concurrent proposals interleave only at the awaits before the commit.

import { DatabaseSync } from 'node:sqlite';
import { createHash, randomBytes } from 'node:crypto';
import { verifyAuthenticationResponse, verifyRegistrationResponse, type AuthenticationResponseJSON, type RegistrationResponseJSON } from '@simplewebauthn/server';
import { B4FaultScheduler, applyLogicalDelay } from '../r5/fault-scheduler.js';
import { buildTrustedPrices, normaliseSymbol, notionalCents, withinBand, type DenyCode, type QuoteSource } from './valuation.js';
import type { PaperPolicyState, SignedPaperPolicy } from './paper-policy.js';

export interface MandateScope {
  symbols: string[];
  sides: Array<'buy' | 'sell'>;
  maxOrderNotionalUsd: number;
  maxDailyNotionalUsd: number;
  priceBandPct: number;
  expiresAt: string;
  referencePrices?: Record<string, number>;
  /** Orders whose trusted notional is above this are held for owner passkey approval. */
  stepUpThresholdUsd?: number;
}

export interface ProposedOrder {
  symbol: string;
  side: string;
  quantity: number;
  limitPrice: number;
  clientOrderId: string;
}

export type DecisionKind = 'filled' | 'denied' | 'held';

export interface Decision {
  decision: DecisionKind;
  reason: string;
  reasons: string[];
  orderId?: string;
  /** True only if THIS call created a ledger effect. A replayed delivery returns false. */
  ledgerEffect: boolean;
  replay?: boolean;
  trustedPrice?: number;
  notionalUsd?: number;
}

export interface Authority {
  /** Liveness of the human-signed mandate at its issuer. Must fail closed (return false) on error. */
  isActive(): Promise<boolean>;
}

export interface CoreOptions {
  ledgerPath: string;
  mandateId: string;
  mandate: MandateScope;
  authority?: Authority;
  signedPolicy?: SignedPaperPolicy;
  quoteSource?: QuoteSource;
  faults?: B4FaultScheduler;
  /** Deliberately broken variants used only by the mutation tests. */
  mutations?: { idempotencyOff?: boolean; budgetLockOff?: boolean };
  webauthn?: { origin: string; rpId: string };
  now?: () => number;
  /** Skip fsync for throw-away campaign ledgers. */
  fast?: boolean;
}

export class FaultDropped extends Error { constructor() { super('request dropped before the receiver saw it'); } }
export class FaultCrash extends Error { constructor() { super('receiver crashed after commit, before reply'); } }

export interface LedgerOrder {
  orderId: string;
  clientOrderId: string;
  symbol: string;
  side: string;
  quantity: number;
  limitPrice: number;
  trustedPrice: number;
  notionalUsd: number;
  status: 'filled' | 'held' | 'cancelled';
  fillPrice: number | null;
  seq: number;
}

export interface LedgerEvent { seq: number; type: string; orderId: string | null; payload: string; prevHash: string; hash: string }

const GENESIS = '0'.repeat(64);
const sha = (text: string) => createHash('sha256').update(text).digest('hex');

export function canonicalAction(mandateId: string, o: { symbol: string; side: string; quantity: number; limitPrice: number }): string {
  return JSON.stringify({ m: mandateId, symbol: o.symbol, side: o.side, quantity: o.quantity, limitPrice: o.limitPrice });
}

interface Passkey { id: string; publicKey: string; counter: number }
interface PendingApproval { challenge: string; actionHash: string; expiresAt: number }

export class ReceiverCore {
  private db!: DatabaseSync;
  private readonly prices: QuoteSource;
  private readonly now: () => number;
  private readonly expiresAtMs: number;
  private passkey: Passkey | null = null;
  private registrationChallengeValue: string | null = null;
  private readonly pending = new Map<string, PendingApproval>();

  constructor(private readonly opts: CoreOptions) {
    this.now = opts.now ?? Date.now;
    const parent = opts.signedPolicy?.parent ?? opts.mandate;
    this.prices = buildTrustedPrices({ referencePrices: parent.referencePrices, quoteSource: opts.quoteSource });
    this.expiresAtMs = Date.parse(parent.expiresAt);
    if (!Number.isFinite(this.expiresAtMs)) throw new Error('mandate.expiresAt must be an ISO timestamp');
    for (const symbol of parent.symbols) if (!normaliseSymbol(symbol).ok) throw new Error('mandate lists an invalid symbol');
    this.open();
  }

  // ---------- storage ----------

  private open(): void {
    this.db = new DatabaseSync(this.opts.ledgerPath);
    if (this.opts.fast) this.db.exec('PRAGMA synchronous=OFF; PRAGMA journal_mode=MEMORY;');
    const idem = this.opts.mutations?.idempotencyOff ? '' : 'UNIQUE';
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS orders (
        seq INTEGER PRIMARY KEY, order_id TEXT NOT NULL, client_order_id TEXT NOT NULL ${idem},
        action_hash TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, quantity INTEGER NOT NULL,
        limit_price REAL NOT NULL, trusted_price REAL NOT NULL, notional_cents INTEGER NOT NULL,
        status TEXT NOT NULL, fill_price REAL, day TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS events (
        seq INTEGER PRIMARY KEY, type TEXT NOT NULL, order_id TEXT, payload TEXT NOT NULL,
        prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
    `);
    const stored = this.meta('passkey');
    if (stored) this.passkey = JSON.parse(stored) as Passkey;
    this.tx(() => {
      const policy = this.policy();
      const signed = this.opts.signedPolicy;
      if (policy && policy.parentId !== signed?.parentId) throw new Error('The ledger is bound to a different signed parent');
      if (signed && !policy) {
        if (this.db.prepare('SELECT seq FROM events LIMIT 1').get()) throw new Error('Cannot attach a signed parent to an existing ledger');
        const initial = { ledgerId: randomBytes(16).toString('hex'), parentId: signed.parentId, revision: 0,
          activeId: signed.parentId, scope: signed.parent };
        this.setMeta('paper_policy', JSON.stringify(initial));
      }
    });
  }

  /** Simulates a process crash and restart: all in-memory state is dropped, the ledger file survives. */
  restart(): void {
    if (this.opts.ledgerPath === ':memory:') throw new Error('restart needs a file-backed ledger');
    this.db.close();
    this.pending.clear();
    this.passkey = null;
    this.open();
  }

  close(): void { this.db.close(); }

  private meta(key: string): string | null {
    const row = this.db.prepare('SELECT v FROM meta WHERE k = ?').get(key) as { v: string } | undefined;
    return row ? row.v : null;
  }
  private setMeta(key: string, value: string): void {
    this.db.prepare('INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v').run(key, value);
  }

  /** Append one hash-chained event. Must run inside a transaction. */
  private appendEvent(type: string, orderId: string | null, payload: object): number {
    const head = this.db.prepare('SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1').get() as { seq: number; hash: string } | undefined;
    const seq = (head?.seq ?? 0) + 1;
    const prev = head?.hash ?? GENESIS;
    const body = JSON.stringify(payload);
    const hash = sha([prev, seq, type, orderId ?? '', body].join('|'));
    this.db.prepare('INSERT INTO events (seq, type, order_id, payload, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?)').run(seq, type, orderId, body, prev, hash);
    return seq;
  }

  private tx<T>(body: () => T): T {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const result = body();
      this.db.exec('COMMIT');
      return result;
    } catch (error) {
      try { this.db.exec('ROLLBACK'); } catch { /* already rolled back */ }
      throw error;
    }
  }

  // ---------- revocation ----------

  get revoked(): boolean { return this.meta('revoked_seq') !== null; }

  /** Durable and synchronous: once this returns, no later commit can succeed. Idempotent. */
  revoke(): { revoked: true; seq: number } {
    return this.tx(() => {
      const existing = this.meta('revoked_seq');
      if (existing !== null) return { revoked: true as const, seq: Number(existing) };
      const seq = this.appendEvent('revoked', null, { mandateId: this.opts.mandateId });
      this.setMeta('revoked_seq', String(seq));
      this.db.prepare("UPDATE orders SET status = 'cancelled' WHERE status = 'held'").run();
      return { revoked: true as const, seq };
    });
  }

  // ---------- signed paper policy ----------

  policy(): PaperPolicyState | null {
    const value = this.meta('paper_policy');
    return value === null ? null : JSON.parse(value) as PaperPolicyState;
  }

  async activatePolicy(proof: unknown): Promise<{ policy: PaperPolicyState; cancelled: number; replay: boolean }> {
    const signed = this.opts.signedPolicy;
    if (!signed) throw new Error('Signed paper activation is unavailable');
    if (this.opts.authority && !await this.opts.authority.isActive()) throw new Error('The issuer reports that the parent is inactive');
    return this.tx(() => {
      const state = this.policy()!;
      if (this.revoked || this.now() >= this.expiresAtMs) throw new Error('The parent policy is inactive');
      const action = signed.authorization(proof, state, 'orderguard.paper-draft-activation.v1', this.meta('last_paper_activation') ?? undefined);
      if (action.replay) return { policy: state, cancelled: 0, replay: true };
      const scope = signed.containedDraft(action.body.draft, this.now());
      if (JSON.stringify(scope) === JSON.stringify(state.scope)) return { policy: state, cancelled: 0, replay: false };
      const policy = { ...state, scope, activeId: action.digest.slice(0, 16), revision: state.revision + 1 };
      const held = this.db.prepare("SELECT order_id FROM orders WHERE status = 'held' ORDER BY seq").all() as { order_id: string }[];
      for (const order of held) this.appendEvent('cancelled', order.order_id, { reason: 'policy_changed', revision: state.revision });
      this.db.prepare("UPDATE orders SET status = 'cancelled' WHERE status = 'held'").run();
      this.appendEvent('policy_activated', null, { parentId: policy.parentId, activeId: policy.activeId,
        revision: policy.revision, authorizationDigest: action.digest, cancelled: held.length });
      this.setMeta('paper_policy', JSON.stringify(policy));
      this.setMeta('last_paper_activation', action.digest);
      return { policy, cancelled: held.length, replay: false };
    });
  }

  private verifyPaperApproval(orderId: string, proof: unknown): void {
    const signed = this.opts.signedPolicy;
    if (!signed) return;
    const state = this.policy()!;
    const action = signed.authorization(proof, state, 'orderguard.paper-order-approval.v1');
    if (action.body.orderId !== orderId) throw new Error('Signature was issued for a different held order');
  }

  // ---------- decisions ----------

  private deny(code: DenyCode, ...more: string[]): Decision {
    return { decision: 'denied', reason: code, reasons: [code, ...more], ledgerEffect: false };
  }

  private findByClientId(clientOrderId: string): (LedgerRow | undefined) {
    return this.db.prepare('SELECT * FROM orders WHERE client_order_id = ? ORDER BY seq LIMIT 1').get(clientOrderId) as LedgerRow | undefined;
  }

  private replayOf(row: LedgerRow): Decision {
    if (row.status === 'cancelled') {
      return { decision: 'denied', reason: 'mandate_revoked', reasons: ['mandate_revoked'], orderId: row.order_id, ledgerEffect: false, replay: true };
    }
    return {
      decision: row.status === 'held' ? 'held' : 'filled', reason: row.status === 'held' ? 'step_up_required' : 'replay_of_committed_order',
      reasons: [], orderId: row.order_id, ledgerEffect: false, replay: true,
      trustedPrice: row.trusted_price, notionalUsd: row.notional_cents / 100,
    };
  }

  async propose(input: ProposedOrder): Promise<Decision> {
    const faults = this.opts.faults;
    const first = faults?.visit('worker.request.before');
    if (first?.action === 'drop') {
      faults!.markApplied(first, 'request dropped before receiver');
      throw new FaultDropped();
    }
    if (first?.action === 'delay') {
      faults!.markApplied(first, 'logical delay before receiver', { ticks: first.delayTicks ?? 0 });
      await applyLogicalDelay(first.delayTicks!);
    }

    // 1. Shape. Nothing here trusts the order's own claims.
    if (!input || typeof input !== 'object' || typeof input.clientOrderId !== 'string' || !/^[A-Za-z0-9._:-]{1,96}$/.test(input.clientOrderId)
      || !Number.isSafeInteger(input.quantity) || input.quantity <= 0
      || typeof input.limitPrice !== 'number' || !Number.isFinite(input.limitPrice) || input.limitPrice <= 0
      || typeof input.side !== 'string') {
      return this.deny('invalid_order');
    }
    const sym = normaliseSymbol(input.symbol);
    if (!sym.ok) return this.deny(sym.code, sym.detail);
    const side = input.side.trim().toLowerCase();
    const canonical = { symbol: sym.symbol, side, quantity: input.quantity, limitPrice: input.limitPrice };
    const actionHash = sha(canonicalAction(this.opts.mandateId, canonical));

    // 2. Idempotency: a delivery of an order we already committed is answered from the ledger.
    if (!this.opts.mutations?.idempotencyOff) {
      const prior = this.findByClientId(input.clientOrderId);
      if (prior) return prior.action_hash === actionHash ? this.replayOf(prior) : this.deny('idempotency_conflict');
    }

    // 3. Authority: revocation, expiry, then the issuer's view of the mandate. Fails closed.
    if (this.revoked) return this.deny('mandate_revoked');
    if (this.now() >= this.expiresAtMs) return this.deny('mandate_expired');
    let active = false;
    try { active = this.opts.authority ? await this.opts.authority.isActive() : true; } catch { active = false; }
    if (!active) return this.deny('mandate_revoked', 'issuer reports the mandate is not active');

    // 4. Scope, valued at the TRUSTED price.
    const policy = this.opts.signedPolicy ? this.policy() : null;
    const scope = policy?.scope ?? this.opts.mandate;
    if (policy && this.now() >= Date.parse(scope.expiresAt)) return this.deny('mandate_expired');
    const allowed = new Set(scope.symbols.map((s) => (normaliseSymbol(s) as { symbol: string }).symbol));
    if (!allowed.has(sym.symbol)) return this.deny('unlisted_symbol');
    if (!(scope.sides as string[]).includes(side)) return this.deny('side_not_allowed');
    const trusted = this.prices(sym.symbol);
    if (trusted === undefined) return this.deny('no_trusted_price');
    if (!withinBand(input.limitPrice, trusted, scope.priceBandPct)) return this.deny('limit_outside_band', `trusted ${trusted}`);
    const cents = notionalCents(input.quantity, trusted);
    if (cents > Math.round(scope.maxOrderNotionalUsd * 100)) return this.deny('per_order_cap');
    const needsStepUp = scope.stepUpThresholdUsd !== undefined && cents > Math.round(scope.stepUpThresholdUsd * 100);

    // 5. Approval is done. A revocation landing here, before the commit, must still win.
    const approval = faults?.visit('mandate.approval.before_commit');
    if (approval?.action === 'revoke') {
      faults!.markApplied(approval, 'mandate revoked between approval and commit');
      this.revoke();
    }

    // 6. Commit.
    const row = { actionHash, clientOrderId: input.clientOrderId, ...canonical, trusted, cents,
      status: needsStepUp ? 'held' as const : 'filled' as const, revision: policy?.revision };
    let result: Decision;
    if (this.opts.mutations?.budgetLockOff) {
      result = await this.commitWithoutLock(row);
    } else {
      const dup = faults?.visit('ledger.before_commit');
      result = this.commit(row);
      if (dup?.action === 'duplicate') {
        faults!.markApplied(dup, 'commit delivered twice');
        this.commit(row);
      }
    }
    const crash = faults?.visit('ledger.after_commit_before_reply');
    if (crash?.action === 'crash') {
      faults!.markApplied(crash, 'receiver restarted after commit, before reply');
      this.restart();
      throw new FaultCrash();
    }
    return result;
  }

  private today(): string { return new Date(this.now()).toISOString().slice(0, 10); }

  private dayBudgetUsedCents(): number {
    const r = this.db.prepare("SELECT COALESCE(SUM(notional_cents), 0) AS s FROM orders WHERE status IN ('filled','held') AND day = ?").get(this.today()) as { s: number };
    return r.s;
  }

  private insertRow(r: CommitRow): Decision {
    const seq = (this.db.prepare('SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM events').get() as { n: number }).n;
    const orderId = this.opts.mutations?.idempotencyOff
      ? 'og_' + sha(this.opts.mandateId + '|' + r.clientOrderId + '|' + seq).slice(0, 16)
      : 'og_' + sha(this.opts.mandateId + '|' + r.clientOrderId).slice(0, 16);
    const eventSeq = this.appendEvent(r.status, orderId, { clientOrderId: r.clientOrderId, symbol: r.symbol, side: r.side, quantity: r.quantity, limitPrice: r.limitPrice, trustedPrice: r.trusted, notionalCents: r.cents, revision: r.revision });
    this.db.prepare(`INSERT INTO orders (seq, order_id, client_order_id, action_hash, symbol, side, quantity, limit_price, trusted_price, notional_cents, status, fill_price, day)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(eventSeq, orderId, r.clientOrderId, r.actionHash, r.symbol, r.side, r.quantity, r.limitPrice, r.trusted, r.cents, r.status, r.status === 'filled' ? r.trusted : null, this.today());
    return {
      decision: r.status, reason: r.status === 'held' ? 'step_up_required' : 'within_mandate', reasons: [], orderId,
      ledgerEffect: r.status === 'filled', trustedPrice: r.trusted, notionalUsd: r.cents / 100,
    };
  }

  /** Atomic: revocation, idempotency and budget are all checked and written in one transaction. */
  private commit(r: CommitRow): Decision {
    return this.tx(() => {
      if (this.meta('revoked_seq') !== null) return this.deny('mandate_revoked');
      if (!this.opts.mutations?.idempotencyOff) {
        const prior = this.findByClientId(r.clientOrderId);
        if (prior) return prior.action_hash === r.actionHash ? this.replayOf(prior) : this.deny('idempotency_conflict');
      }
      const policy = this.opts.signedPolicy ? this.policy() : null;
      if (policy && policy.revision !== r.revision) return this.deny('mandate_changed');
      const scope = policy?.scope ?? this.opts.mandate;
      if (this.now() >= Date.parse(scope.expiresAt)) return this.deny('mandate_expired');
      if (this.dayBudgetUsedCents() + r.cents > Math.round(scope.maxDailyNotionalUsd * 100)) return this.deny('daily_cap');
      return this.insertRow(r);
    });
  }

  /** MUTATION ONLY: check-then-act with a yield in between and no lock. Exists so the checker can prove it catches this. */
  private async commitWithoutLock(r: CommitRow): Promise<Decision> {
    const used = this.dayBudgetUsedCents();
    if (this.meta('revoked_seq') !== null) return this.deny('mandate_revoked');
    if (!this.opts.mutations?.idempotencyOff) {
      const prior = this.findByClientId(r.clientOrderId);
      if (prior) return prior.action_hash === r.actionHash ? this.replayOf(prior) : this.deny('idempotency_conflict');
    }
    if (used + r.cents > Math.round(this.opts.mandate.maxDailyNotionalUsd * 100)) return this.deny('daily_cap');
    await new Promise<void>((resolve) => setImmediate(resolve));
    try { return this.tx(() => this.insertRow(r)); } catch {
      return this.deny('idempotency_conflict', 'unique constraint refused a duplicate delivery');
    }
  }

  // ---------- owner passkey: registration and step-up approval ----------

  private requireWebauthn(): { origin: string; rpId: string } {
    if (!this.opts.webauthn) throw new Error('webauthn origin and rpId were not configured');
    return this.opts.webauthn;
  }

  passkeyRegistrationChallenge(): string {
    this.registrationChallengeValue = randomBytes(32).toString('base64url');
    return this.registrationChallengeValue;
  }

  async registerOwnerPasskey(response: RegistrationResponseJSON): Promise<void> {
    const { origin, rpId } = this.requireWebauthn();
    if (!this.registrationChallengeValue) throw new Error('no registration challenge outstanding');
    const challenge = this.registrationChallengeValue;
    this.registrationChallengeValue = null;
    const v = await verifyRegistrationResponse({ response, expectedChallenge: challenge, expectedOrigin: origin, expectedRPID: rpId, requireUserVerification: true });
    if (!v.verified) throw new Error('passkey registration did not verify');
    const c = v.registrationInfo.credential;
    this.passkey = { id: c.id, publicKey: Buffer.from(c.publicKey).toString('base64url'), counter: c.counter };
    this.setMeta('passkey', JSON.stringify(this.passkey));
  }

  /** Issue a single-use challenge bound to one held order. */
  beginApproval(orderId: string, ownerProof?: unknown): { orderId: string; challenge: string; credentialId: string } {
    try { this.verifyPaperApproval(orderId, ownerProof); } catch { throw new ApprovalError('approval_invalid'); }
    const row = this.db.prepare('SELECT * FROM orders WHERE order_id = ?').get(orderId) as LedgerRow | undefined;
    if (!row || row.status !== 'held') throw new ApprovalError('not_held');
    if (!this.passkey) throw new ApprovalError('approval_invalid', 'no owner passkey registered');
    const challenge = randomBytes(32).toString('base64url');
    this.pending.set(orderId, { challenge, actionHash: row.action_hash, expiresAt: this.now() + 60_000 });
    return { orderId, challenge, credentialId: this.passkey.id };
  }

  async approve(orderId: string, assertion: AuthenticationResponseJSON, ownerProof?: unknown): Promise<Decision> {
    try { this.verifyPaperApproval(orderId, ownerProof); } catch { return this.deny('approval_invalid'); }
    const row = this.db.prepare('SELECT * FROM orders WHERE order_id = ?').get(orderId) as LedgerRow | undefined;
    if (!row) return this.deny('not_held');
    if (row.status === 'filled') return this.replayOf(row);
    if (row.status === 'cancelled') return this.deny('mandate_revoked');
    const pend = this.pending.get(orderId);
    this.pending.delete(orderId); // single use, whatever the outcome
    if (!pend || pend.expiresAt <= this.now() || pend.actionHash !== row.action_hash || !this.passkey) return this.deny('approval_invalid', 'no outstanding challenge for this exact order');
    const { origin, rpId } = this.requireWebauthn();
    let verified;
    try {
      verified = await verifyAuthenticationResponse({
        response: assertion, expectedChallenge: pend.challenge, expectedOrigin: origin, expectedRPID: rpId, requireUserVerification: true,
        credential: { id: this.passkey.id, publicKey: Buffer.from(this.passkey.publicKey, 'base64url'), counter: this.passkey.counter },
      });
    } catch {
      return this.deny('approval_invalid', 'assertion did not verify');
    }
    if (!verified.verified) return this.deny('approval_invalid');
    if (this.opts.signedPolicy && this.opts.authority) {
      try { if (!await this.opts.authority.isActive()) return this.deny('mandate_revoked'); }
      catch { return this.deny('mandate_revoked'); }
    }
    return this.tx(() => {
      this.passkey!.counter = Math.max(this.passkey!.counter, verified.authenticationInfo.newCounter);
      this.setMeta('passkey', JSON.stringify(this.passkey));
      if (this.meta('revoked_seq') !== null) return this.deny('mandate_revoked');
      const policy = this.opts.signedPolicy ? this.policy() : null;
      if (this.now() >= Date.parse((policy?.scope ?? this.opts.mandate).expiresAt)) return this.deny('mandate_expired');
      const fresh = this.db.prepare('SELECT * FROM orders WHERE order_id = ?').get(orderId) as LedgerRow;
      if (fresh.status !== 'held') return this.replayOf(fresh);
      this.appendEvent('approved', orderId, { actionHash: fresh.action_hash });
      this.db.prepare("UPDATE orders SET status = 'filled', fill_price = trusted_price WHERE order_id = ?").run(orderId);
      return {
        decision: 'filled' as const, reason: 'owner_passkey_approved', reasons: [], orderId, ledgerEffect: true,
        trustedPrice: fresh.trusted_price, notionalUsd: fresh.notional_cents / 100,
      };
    });
  }

  // ---------- read side ----------

  orders(): LedgerOrder[] {
    const rows = this.db.prepare('SELECT * FROM orders ORDER BY seq').all() as unknown as LedgerRow[];
    return rows.map((r) => ({
      orderId: r.order_id, clientOrderId: r.client_order_id, symbol: r.symbol, side: r.side, quantity: r.quantity,
      limitPrice: r.limit_price, trustedPrice: r.trusted_price, notionalUsd: r.notional_cents / 100,
      status: r.status as LedgerOrder['status'], fillPrice: r.fill_price, seq: r.seq,
    }));
  }

  events(): LedgerEvent[] {
    const rows = this.db.prepare('SELECT * FROM events ORDER BY seq').all() as unknown as Array<{ seq: number; type: string; order_id: string | null; payload: string; prev_hash: string; hash: string }>;
    return rows.map((r) => ({ seq: r.seq, type: r.type, orderId: r.order_id, payload: r.payload, prevHash: r.prev_hash, hash: r.hash }));
  }

  revokedSeq(): number | null { const v = this.meta('revoked_seq'); return v === null ? null : Number(v); }

  /** Hash chain intact, every order row agrees with its last event, and the budget is not exceeded. */
  ledgerIntegrity(): boolean {
    let prev = GENESIS;
    const last = new Map<string, string>();
    for (const e of this.events()) {
      if (e.prevHash !== prev || e.hash !== sha([prev, e.seq, e.type, e.orderId ?? '', e.payload].join('|'))) return false;
      prev = e.hash;
      if (e.orderId) last.set(e.orderId, e.type);
    }
    const revoked = this.revokedSeq() !== null;
    for (const o of this.orders()) {
      const lastType = last.get(o.orderId);
      const expected = o.status === 'filled' ? ['filled', 'approved'] : o.status === 'held' ? ['held'] : revoked ? ['held', 'cancelled'] : ['cancelled'];
      if (!lastType || !expected.includes(lastType)) return false;
    }
    const maxDaily = this.db.prepare("SELECT COALESCE(MAX(total), 0) AS cents FROM (SELECT SUM(notional_cents) AS total FROM orders WHERE status IN ('filled','held') GROUP BY day)").get() as { cents: number };
    return maxDaily.cents <= Math.round((this.opts.signedPolicy?.parent ?? this.opts.mandate).maxDailyNotionalUsd * 100);
  }

  snapshot(): { orders: LedgerOrder[]; ledgerIntegrity: boolean; revoked: boolean; usedNotionalUsd: number } {
    const orders = this.orders();
    const used = orders.filter((o) => o.status !== 'cancelled').reduce((s, o) => s + Math.round(o.notionalUsd * 100), 0) / 100;
    return { orders, ledgerIntegrity: this.ledgerIntegrity(), revoked: this.revoked, usedNotionalUsd: used };
  }
}

export class ApprovalError extends Error {
  constructor(readonly code: DenyCode, message?: string) { super(message ?? code); }
}

interface LedgerRow {
  seq: number; order_id: string; client_order_id: string; action_hash: string; symbol: string; side: string; quantity: number;
  limit_price: number; trusted_price: number; notional_cents: number; status: string; fill_price: number | null;
}
interface CommitRow {
  actionHash: string; clientOrderId: string; symbol: string; side: string; quantity: number; limitPrice: number;
  trusted: number; cents: number; status: 'filled' | 'held';
  revision?: number;
}
