// Offline verification of an OrderGuard receiver ledger (SQLite file written by ReceiverCore).
//
// A hash chain alone proves the event log was not edited in the middle. It does not prove that the
// mutable tables agree with the log, so this verifier also replays the log and compares it with every
// order row, the revocation flag, the policy revision and the daily budget. The same function runs
// when the receiver opens a file (so a tampered or half-written ledger is never served) and from the
// ledger tool (verify / export / backup).
//
// Known limit, stated plainly: deleting the newest events and their order rows leaves a valid shorter
// chain. Record `head` (seq and hash, printed by export and verify) somewhere the ledger's writer
// cannot reach, and pass it back as `expectHead` to detect that.

import { createHash } from 'node:crypto';
import type { DatabaseSync } from 'node:sqlite';

export const GENESIS = '0'.repeat(64);
export const SCHEMA_VERSION = 1;
export const sha256 = (text: string) => createHash('sha256').update(text).digest('hex');

export interface LedgerHead { seq: number; hash: string }
export interface LedgerCheck {
  ok: boolean;
  problems: string[];
  events: number;
  orders: number;
  head: LedgerHead;
  revoked: boolean;
}
export interface VerifyExpectations {
  /** The mandate identity the ledger must be bound to. Omit to trust the ledger's own `mandate_id`. */
  mandateId?: string;
  /** Daily budget ceiling in cents. Omit to use the cap stored when the ledger was created. */
  maxDailyCents?: number;
  /** Seq and hash recorded outside the ledger. The ledger must contain this exact event. */
  expectHead?: LedgerHead;
  /** Skip the order-id derivation check (mutation tests build deliberately different ids). */
  skipOrderIdCheck?: boolean;
}

interface EventRow { seq: number; type: string; order_id: string | null; payload: string; prev_hash: string; hash: string }
interface OrderRow {
  seq: number; order_id: string; client_order_id: string; action_hash: string; symbol: string; side: string; quantity: number;
  limit_price: number; trusted_price: number; notional_cents: number; status: string; fill_price: number | null; day: string;
}

const MAX_PROBLEMS = 20;

function metaValue(db: DatabaseSync, key: string): string | null {
  const row = db.prepare('SELECT v FROM meta WHERE k = ?').get(key) as { v: string } | undefined;
  return row ? row.v : null;
}

/** The action hash the core stores for an order. Kept here so the verifier and the core cannot drift apart. */
export function actionHashOf(mandateId: string, o: { symbol: string; side: string; quantity: number; limitPrice: number }): string {
  return sha256(JSON.stringify({ m: mandateId, symbol: o.symbol, side: o.side, quantity: o.quantity, limitPrice: o.limitPrice }));
}

export function orderIdOf(mandateId: string, clientOrderId: string): string {
  return 'og_' + sha256(mandateId + '|' + clientOrderId).slice(0, 16);
}

export function verifyLedgerDb(db: DatabaseSync, expect: VerifyExpectations = {}): LedgerCheck {
  const problems: string[] = [];
  const bad = (text: string) => { if (problems.length < MAX_PROBLEMS) problems.push(text); };

  let events: EventRow[] = [];
  let orders: OrderRow[] = [];
  try {
    events = db.prepare('SELECT * FROM events ORDER BY seq').all() as unknown as EventRow[];
    orders = db.prepare('SELECT * FROM orders ORDER BY seq').all() as unknown as OrderRow[];
  } catch {
    bad('the ledger tables are missing or unreadable');
    return { ok: false, problems, events: 0, orders: 0, head: { seq: 0, hash: GENESIS }, revoked: false };
  }

  // 1. The hash chain: contiguous seq from 1, each link points at the previous hash, each hash recomputes.
  let prev = GENESIS;
  const parsed = new Map<number, Record<string, unknown>>();
  events.forEach((e, index) => {
    if (e.seq !== index + 1) bad(`event ${index + 1}: sequence number is ${e.seq}; an event is missing or reordered`);
    if (e.prev_hash !== prev) bad(`event ${e.seq}: does not follow the previous event`);
    if (e.hash !== sha256([e.prev_hash, e.seq, e.type, e.order_id ?? '', e.payload].join('|'))) bad(`event ${e.seq}: contents do not match their hash`);
    prev = e.hash;
    try {
      const body = JSON.parse(e.payload);
      if (body && typeof body === 'object' && !Array.isArray(body)) parsed.set(e.seq, body as Record<string, unknown>);
      else bad(`event ${e.seq}: payload is not an object`);
    } catch { bad(`event ${e.seq}: payload is not valid JSON`); }
  });
  const head: LedgerHead = { seq: events.length ? events[events.length - 1]!.seq : 0, hash: prev };

  if (expect.expectHead) {
    const at = events.find((e) => e.seq === expect.expectHead!.seq);
    if (!at || at.hash !== expect.expectHead.hash) bad(`the recorded head (event ${expect.expectHead.seq}) is not in this ledger; it was truncated or replaced`);
  }

  // 2. Replay the log: what status should every order have, and was the ledger revoked?
  const mandateId = expect.mandateId ?? metaValue(db, 'mandate_id') ?? undefined;
  const status = new Map<string, 'filled' | 'held' | 'cancelled'>();
  const created = new Map<string, EventRow>();
  let revokedEvents = 0;
  let revokedSeq: number | null = null;
  for (const e of events) {
    if (e.type === 'filled' || e.type === 'held') {
      if (!e.order_id) { bad(`event ${e.seq}: ${e.type} without an order`); continue; }
      if (status.has(e.order_id)) bad(`event ${e.seq}: order ${e.order_id} was created twice`);
      status.set(e.order_id, e.type);
      created.set(e.order_id, e);
    } else if (e.type === 'approved') {
      if (!e.order_id || status.get(e.order_id) !== 'held') bad(`event ${e.seq}: approval of an order that was not held`);
      else status.set(e.order_id, 'filled');
    } else if (e.type === 'cancelled') {
      if (!e.order_id || status.get(e.order_id) !== 'held') bad(`event ${e.seq}: cancellation of an order that was not held`);
      else status.set(e.order_id, 'cancelled');
    } else if (e.type === 'revoked') {
      revokedEvents += 1;
      if (revokedSeq === null) revokedSeq = e.seq;
      for (const [id, s] of status) if (s === 'held') status.set(id, 'cancelled');
    } else if (e.type !== 'policy_activated') {
      bad(`event ${e.seq}: unknown event type`);
    }
  }
  if (revokedEvents > 1) bad('the ledger records more than one revocation');

  // 3. Revocation flag. Deleting the flag would silently un-revoke the mandate.
  const flag = metaValue(db, 'revoked_seq');
  if (revokedSeq === null && flag !== null) bad('the revoked flag is set but the log has no revocation');
  if (revokedSeq !== null && flag !== String(revokedSeq)) bad('the log records a revocation but the revoked flag does not match it');

  // 4. Every order row must be exactly what its creating event says, in the status the log implies.
  const seen = new Set<string>();
  for (const o of orders) {
    if (seen.has(o.order_id)) { bad(`order ${o.order_id}: appears twice`); continue; }
    seen.add(o.order_id);
    const ev = created.get(o.order_id);
    if (!ev) { bad(`order ${o.order_id}: has no creating event`); continue; }
    if (ev.seq !== o.seq) bad(`order ${o.order_id}: row position does not match its event`);
    const body = parsed.get(ev.seq) ?? {};
    const same = body.clientOrderId === o.client_order_id && body.symbol === o.symbol && body.side === o.side && body.quantity === o.quantity
      && body.limitPrice === o.limit_price && body.trustedPrice === o.trusted_price && body.notionalCents === o.notional_cents;
    if (!same) bad(`order ${o.order_id}: row was changed after it was recorded`);
    if (!Number.isSafeInteger(o.notional_cents) || o.notional_cents <= 0 || o.notional_cents !== Math.round(o.quantity * o.trusted_price * 100)) {
      bad(`order ${o.order_id}: notional does not equal quantity times trusted price`);
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(o.day)) bad(`order ${o.order_id}: invalid trading day`);
    const want = status.get(o.order_id);
    if (o.status !== want) bad(`order ${o.order_id}: status is ${o.status} but the log says ${want}`);
    if (o.status === 'filled' && o.fill_price !== o.trusted_price) bad(`order ${o.order_id}: fill price is not the trusted price`);
    if (o.status !== 'filled' && o.fill_price !== null) bad(`order ${o.order_id}: has a fill price but is not filled`);
    if (mandateId !== undefined) {
      if (!expect.skipOrderIdCheck && o.order_id !== orderIdOf(mandateId, o.client_order_id)) bad(`order ${o.order_id}: id does not belong to this mandate`);
      if (o.action_hash !== actionHashOf(mandateId, { symbol: o.symbol, side: o.side, quantity: o.quantity, limitPrice: o.limit_price })) {
        bad(`order ${o.order_id}: stored action hash does not match its terms`);
      }
    }
  }
  for (const id of created.keys()) if (!seen.has(id)) bad(`order ${id}: the log records it but its row is missing`);

  // 5. Policy revision must equal the number of recorded activations.
  const rawPolicy = metaValue(db, 'paper_policy');
  if (rawPolicy !== null) {
    try {
      const policy = JSON.parse(rawPolicy) as { revision?: unknown; activeId?: unknown; parentId?: unknown };
      const activations = events.filter((e) => e.type === 'policy_activated');
      if (policy.revision !== activations.length) bad('the policy revision does not match the recorded activations');
      const last = activations.length ? parsed.get(activations[activations.length - 1]!.seq) : undefined;
      if (last && (last.activeId !== policy.activeId || last.parentId !== policy.parentId)) bad('the active policy does not match its last activation');
    } catch { bad('the stored policy is not valid JSON'); }
  } else if (events.some((e) => e.type === 'policy_activated')) {
    bad('policy activations are recorded but the policy is missing');
  }

  // 6. Budget: no UTC day may exceed the daily ceiling the ledger was created under.
  let ceiling = expect.maxDailyCents;
  if (ceiling === undefined) {
    const stored = metaValue(db, 'max_daily_cents');
    if (stored !== null && Number.isSafeInteger(Number(stored))) ceiling = Number(stored);
  }
  if (ceiling !== undefined) {
    const totals = new Map<string, number>();
    for (const o of orders) if (o.status !== 'cancelled') totals.set(o.day, (totals.get(o.day) ?? 0) + o.notional_cents);
    for (const [day, cents] of totals) if (cents > ceiling) bad(`${day}: spending is above the daily limit`);
  }

  return { ok: problems.length === 0, problems, events: events.length, orders: orders.length, head, revoked: revokedSeq !== null };
}
