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
import { randomBytes } from 'node:crypto';
import { verifyAuthenticationResponse, verifyRegistrationResponse, type AuthenticationResponseJSON, type RegistrationResponseJSON } from '@simplewebauthn/server';
import { B4FaultScheduler, applyLogicalDelay } from '../r5/fault-scheduler.js';
import { buildTrustedPrices, normaliseSymbol, notionalCents, withinBand, type DenyCode, type QuoteSource } from './valuation.js';
import type { PaperPolicyState, SignedPaperPolicy } from './paper-policy.js';
import { GENESIS, SCHEMA_VERSION, actionHashOf, orderIdOf, sha256 as sha, verifyLedgerDb, type LedgerCheck, type LedgerHead } from './ledger-verify.js';

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
  /** Optional portfolio limits. Absent means no limit. */
  /** Cap on one symbol's notional per UTC day, counting filled and held orders (the concentration control). */
  maxSymbolDailyNotionalUsd?: number;
  /** Cap on the absolute net position in one symbol after the order, at the trusted price. Held orders count in the direction that grows exposure. */
  maxPositionUsd?: number;
  /** Cap on non-denied (filled or held) orders per UTC day. */
  maxOrdersPerDay?: number;
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
  /** Verify the whole ledger when a file is opened (default true). A ledger that fails is never served. */
  verifyOnOpen?: boolean;
  /** Longest the issuer may take to answer isActive() before the call counts as inactive. Default 10 s. */
  authorityTimeoutMs?: number;
  /** A head (seq, hash) recorded outside the ledger; opening fails if the ledger no longer contains it. */
  expectHead?: LedgerHead;
}

/** The ledger file cannot be trusted or used. `code` says why; the message says what to do. */
export class LedgerError extends Error {
  constructor(readonly code: 'tampered' | 'unreadable' | 'bound_elsewhere' | 'too_new', message: string, readonly problems: string[] = []) {
    super(message);
    this.name = 'LedgerError';
  }
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
    for (const k of ['maxSymbolDailyNotionalUsd', 'maxPositionUsd'] as const) {
      const v = parent[k];
      if (v !== undefined && (typeof v !== 'number' || !Number.isFinite(v) || v <= 0)) throw new Error(`mandate.${k} must be a positive number`);
    }
    if (parent.maxOrdersPerDay !== undefined && (!Number.isSafeInteger(parent.maxOrdersPerDay) || parent.maxOrdersPerDay < 1)) {
      throw new Error('mandate.maxOrdersPerDay must be a positive whole number');
    }
    for (const symbol of parent.symbols) if (!normaliseSymbol(symbol).ok) throw new Error('mandate lists an invalid symbol');
    this.open();
  }

  // ---------- storage ----------

  private open(): void {
    const file = this.opts.ledgerPath !== ':memory:';
    try {
      this.db = new DatabaseSync(this.opts.ledgerPath);
      if (this.opts.fast) this.db.exec('PRAGMA synchronous=OFF; PRAGMA journal_mode=MEMORY;');
      else if (file) this.db.exec('PRAGMA busy_timeout=5000; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;');
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
    } catch (error) {
      try { this.db?.close(); } catch { /* never opened */ }
      throw new LedgerError('unreadable', 'The ledger file could not be opened (' + String((error as Error)?.message ?? error).slice(0, 80)
        + '). It may be corrupt or not an OrderGuard ledger. Restore it from a backup, or start with a new ledger path.');
    }
    const scope = this.opts.signedPolicy?.parent ?? this.opts.mandate;
    try {
      const schema = this.meta('schema');
      if (schema !== null && Number(schema) > SCHEMA_VERSION) {
        throw new LedgerError('too_new', 'This ledger was written by a newer OrderGuard release. Upgrade OrderGuard, or use a different ledger path.');
      }
      const bound = this.meta('mandate_id');
      if (bound !== null && bound !== this.opts.mandateId) {
        throw new LedgerError('bound_elsewhere', 'This ledger belongs to a different mandate. Start the receiver with a new ledger path, or restore the mandate it was created under.');
      }
      const verifyNow = file && this.opts.verifyOnOpen !== false && !this.opts.mutations;
      if (verifyNow) {
        // Verify before anything is written, so a damaged ledger is left exactly as found for inspection.
        const check = verifyLedgerDb(this.db, { mandateId: this.opts.mandateId, maxDailyCents: Math.round(scope.maxDailyNotionalUsd * 100),
          expectHead: this.opts.expectHead, skipOrderIdCheck: Boolean(this.opts.mutations?.idempotencyOff) });
        if (!check.ok) {
          throw new LedgerError('tampered', 'The ledger failed its integrity check, so the receiver will not serve it: ' + check.problems[0]
            + '. Restore the last backup (or move this file aside and start a new ledger).', check.problems);
        }
      }
      this.tx(() => {
        const policy = this.policy();
        const signed = this.opts.signedPolicy;
        if (policy && policy.parentId !== signed?.parentId) {
          throw new LedgerError('bound_elsewhere', 'This ledger is bound to a different signed parent policy (the owner re-signed or changed the mandate). Start with a new ledger path.');
        }
        if (signed && !policy) {
          if (this.db.prepare('SELECT seq FROM events LIMIT 1').get()) throw new LedgerError('bound_elsewhere', 'This ledger already holds orders from a demo mandate and cannot be attached to a signed parent. Use a new ledger path.');
          const initial = { ledgerId: randomBytes(16).toString('hex'), parentId: signed.parentId, revision: 0,
            activeId: signed.parentId, scope: signed.parent };
          this.setMeta('paper_policy', JSON.stringify(initial));
        }
        if (this.meta('mandate_id') === null) this.setMeta('mandate_id', this.opts.mandateId);
        if (this.meta('max_daily_cents') === null) this.setMeta('max_daily_cents', String(Math.round(scope.maxDailyNotionalUsd * 100)));
        if (schema === null) this.setMeta('schema', String(SCHEMA_VERSION));
      });
    } catch (error) {
      try { this.db.close(); } catch { /* already closed */ }
      if (error instanceof LedgerError) throw error;
      throw new LedgerError('unreadable', 'The ledger could not be initialised (' + String((error as Error)?.message ?? error).slice(0, 80) + '). Check free disk space and permissions on the ledger directory.');
    }
    const stored = this.meta('passkey');
    if (stored) this.passkey = JSON.parse(stored) as Passkey;
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

  /** The issuer's view of the mandate. Any error, a falsy answer or no answer within the timeout counts as inactive. */
  private async issuerActive(): Promise<boolean> {
    const authority = this.opts.authority;
    if (!authority) return true;
    const limit = this.opts.authorityTimeoutMs ?? 10_000;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const answer = await Promise.race([
        authority.isActive(),
        new Promise<boolean>((resolve) => { timer = setTimeout(() => resolve(false), limit); }),
      ]);
      return answer === true;
    } catch { return false; } finally { clearTimeout(timer); }
  }

  /** Set once the HTTP port is known; the owner passkey ceremony checks this origin. */
  setWebauthn(webauthn: { origin: string; rpId: string }): void { this.opts.webauthn = webauthn; }

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
    if (!await this.issuerActive()) throw new Error('The issuer reports that the parent is inactive');
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
      const reason = this.revoked ? 'mandate_revoked' : 'mandate_changed'; // a held order is cancelled by revocation or by a policy change
      return { decision: 'denied', reason, reasons: [reason], orderId: row.order_id, ledgerEffect: false, replay: true };
    }
    return {
      decision: row.status === 'held' ? 'held' : 'filled', reason: row.status === 'held' ? 'step_up_required' : 'replay_of_committed_order',
      reasons: [], orderId: row.order_id, ledgerEffect: false, replay: true,
      trustedPrice: row.trusted_price, notionalUsd: row.notional_cents / 100,
    };
  }

  /** Shape check. Nothing here trusts the order's own claims. Returns the canonical order or a denial. */
  private check(input: ProposedOrder): Decision | { canonical: { symbol: string; side: string; quantity: number; limitPrice: number }; actionHash: string; sym: { symbol: string } } {
    if (!input || typeof input !== 'object' || typeof input.clientOrderId !== 'string' || !/^[A-Za-z0-9._:-]{1,96}$/.test(input.clientOrderId)
      || !Number.isSafeInteger(input.quantity) || input.quantity <= 0
      || typeof input.limitPrice !== 'number' || !Number.isFinite(input.limitPrice) || input.limitPrice <= 0 || input.limitPrice > 1e12
      || typeof input.side !== 'string' || input.side.length > 16) {
      return this.deny('invalid_order');
    }
    const sym = normaliseSymbol(input.symbol);
    if (!sym.ok) return this.deny(sym.code, sym.detail);
    const side = input.side.trim().toLowerCase();
    const canonical = { symbol: sym.symbol, side, quantity: input.quantity, limitPrice: input.limitPrice };
    return { canonical, actionHash: actionHashOf(this.opts.mandateId, canonical), sym };
  }

  /**
   * What the ledger already says about this clientOrderId, or null if it is new. Read-only. The bridge asks this
   * before it consults the anchor so that a retry after a crash or a timeout always sees the original outcome,
   * even while the issuer is unreachable.
   */
  priorDecision(input: ProposedOrder): Decision | null {
    if (this.opts.mutations?.idempotencyOff) return null;
    const checked = this.check(input);
    if ('decision' in checked) return null;
    const prior = this.findByClientId(input.clientOrderId);
    if (!prior) return null;
    return prior.action_hash === checked.actionHash ? this.replayOf(prior) : this.deny('idempotency_conflict');
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

    // 1-2. Shape, then idempotency: a delivery of an order we already committed is answered from the ledger.
    const checked = this.check(input);
    if ('decision' in checked) return checked;
    const { canonical, actionHash } = checked;
    const sym = { symbol: canonical.symbol };
    const side = canonical.side;
    if (!this.opts.mutations?.idempotencyOff) {
      const prior = this.findByClientId(input.clientOrderId);
      if (prior) return prior.action_hash === actionHash ? this.replayOf(prior) : this.deny('idempotency_conflict');
    }

    // 3. Authority: revocation, expiry, then the issuer's view of the mandate. Fails closed.
    if (this.revoked) return this.deny('mandate_revoked');
    if (this.now() >= this.expiresAtMs) return this.deny('mandate_expired');
    if (!await this.issuerActive()) return this.deny('mandate_revoked', 'issuer reports the mandate is not active');

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

  /**
   * The UTC day budgets are charged to. A clock that steps backwards (NTP correction, VM restore, tampering) must
   * not reopen yesterday's or reset today's budget, so the day never moves behind the newest day in the ledger.
   */
  private today(): string {
    const clock = new Date(this.now()).toISOString().slice(0, 10);
    const newest = this.db.prepare('SELECT MAX(day) AS d FROM orders').get() as { d: string | null };
    return newest.d && newest.d > clock ? newest.d : clock;
  }

  private dayBudgetUsedCents(): number {
    const r = this.db.prepare("SELECT COALESCE(SUM(notional_cents), 0) AS s FROM orders WHERE status IN ('filled','held') AND day = ?").get(this.today()) as { s: number };
    return r.s;
  }

  /**
   * The optional portfolio limits, computed from the ledger in integer cents. Must run inside the commit transaction, next to the daily
   * budget check, so concurrent proposals can never together pass them. Returns a denial, or null when the order fits (or no limit is set).
   */
  private portfolioDenial(scope: MandateScope, r: CommitRow): Decision | null {
    const day = this.today();
    if (scope.maxOrdersPerDay !== undefined) {
      const n = (this.db.prepare("SELECT COUNT(*) AS n FROM orders WHERE status IN ('filled','held') AND day = ?").get(day) as { n: number }).n;
      if (n + 1 > scope.maxOrdersPerDay) return this.deny('order_count_cap');
    }
    if (scope.maxSymbolDailyNotionalUsd !== undefined) {
      const used = (this.db.prepare("SELECT COALESCE(SUM(notional_cents), 0) AS s FROM orders WHERE status IN ('filled','held') AND day = ? AND symbol = ?")
        .get(day, r.symbol) as { s: number }).s;
      if (used + r.cents > Math.round(scope.maxSymbolDailyNotionalUsd * 100)) return this.deny('symbol_daily_cap');
    }
    if (scope.maxPositionUsd !== undefined) {
      const q = this.db.prepare(`SELECT
          COALESCE(SUM(CASE WHEN status = 'filled' THEN (CASE side WHEN 'buy' THEN quantity ELSE -quantity END) END), 0) AS net,
          COALESCE(SUM(CASE WHEN status = 'held' AND side = 'buy' THEN quantity END), 0) AS hb,
          COALESCE(SUM(CASE WHEN status = 'held' AND side = 'sell' THEN quantity END), 0) AS hs
        FROM orders WHERE symbol = ?`).get(r.symbol) as { net: number; hb: number; hs: number };
      const s = r.side === 'buy' ? r.quantity : -r.quantity;
      const exposure = Math.max(Math.abs(q.net + q.hb + s), Math.abs(q.net - q.hs + s)); // held orders counted whichever way grows the exposure
      if (Math.round(exposure * r.trusted * 100) > Math.round(scope.maxPositionUsd * 100)) return this.deny('position_cap');
    }
    return null;
  }

  private insertRow(r: CommitRow): Decision {
    const seq = (this.db.prepare('SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM events').get() as { n: number }).n;
    const orderId = this.opts.mutations?.idempotencyOff
      ? 'og_' + sha(this.opts.mandateId + '|' + r.clientOrderId + '|' + seq).slice(0, 16)
      : orderIdOf(this.opts.mandateId, r.clientOrderId);
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
      const portfolio = this.portfolioDenial(scope, r);
      if (portfolio) return portfolio;
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

  /** An approval the ledger already holds (the order is filled), answered as a replay with no new effect. Read-only. */
  priorApproval(orderId: string, ownerProof?: unknown): Decision | null {
    try { this.verifyPaperApproval(orderId, ownerProof); } catch { return null; }
    const row = this.db.prepare('SELECT * FROM orders WHERE order_id = ?').get(orderId) as LedgerRow | undefined;
    return row && row.status === 'filled' ? this.replayOf(row) : null;
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
    if (row.status === 'cancelled') return this.deny(this.revoked ? 'mandate_revoked' : 'mandate_changed');
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
    if (this.opts.signedPolicy && this.opts.authority && !await this.issuerActive()) return this.deny('mandate_revoked');
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

  /** Full verification (see ledger-verify.ts): hash chain, log replay against every row, revocation flag, policy revision, budget. */
  verifyLedger(expectHead?: LedgerHead): LedgerCheck {
    return verifyLedgerDb(this.db, { mandateId: this.opts.mandateId,
      maxDailyCents: Math.round((this.opts.signedPolicy?.parent ?? this.opts.mandate).maxDailyNotionalUsd * 100),
      skipOrderIdCheck: Boolean(this.opts.mutations?.idempotencyOff), expectHead });
  }

  ledgerIntegrity(): boolean { return this.verifyLedger().ok; }

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
