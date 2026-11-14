// File-level operations on a receiver ledger: single-writer lock, offline verify, export and backup.
// Everything here works on the SQLite file directly, so it runs with the receiver stopped (or running:
// reads are safe under WAL) and never needs the mandate or any key.

import { closeSync, existsSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync, chmodSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { sha256, verifyLedgerDb, type LedgerCheck, type LedgerHead } from './ledger-verify.js';

export class LedgerFileError extends Error {
  constructor(readonly code: 'missing' | 'locked' | 'exists' | 'tampered' | 'unreadable', message: string) {
    super(message);
    this.name = 'LedgerFileError';
  }
}

const alive = (pid: number): boolean => {
  try { process.kill(pid, 0); return true; } catch (error) { return (error as NodeJS.ErrnoException).code === 'EPERM'; }
};

/** Make the directory for a persistent ledger (owner only) and return the resolved path. */
export function prepareLedgerPath(path: string): string {
  const full = resolve(path);
  mkdirSync(dirname(full), { recursive: true, mode: 0o700 });
  return full;
}

/**
 * One receiver per ledger file. A second process opening the same ledger would keep its own in-memory approval
 * challenges and revocation view, so it is refused instead. The lock is a pid file; a lock whose process has
 * died is taken over. Returns a release function.
 */
export function acquireLedgerLock(ledgerPath: string): () => void {
  const lock = ledgerPath + '.lock';
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const fd = openSync(lock, 'wx', 0o600);
      writeFileSync(fd, String(process.pid));
      closeSync(fd);
      let released = false;
      return () => {
        if (released) return;
        released = true;
        try { if (readFileSync(lock, 'utf8').trim() === String(process.pid)) unlinkSync(lock); } catch { /* already gone */ }
      };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
        throw new LedgerFileError('unreadable', `Cannot create the ledger lock next to ${basename(ledgerPath)} (${(error as NodeJS.ErrnoException).code ?? 'error'}). Check that the ledger directory is writable.`);
      }
      let holder = NaN;
      try { holder = Number(readFileSync(lock, 'utf8').trim()); } catch { /* removed meanwhile: retry */ }
      if (Number.isInteger(holder) && holder > 0 && holder !== process.pid && alive(holder)) {
        throw new LedgerFileError('locked', `Another receiver (process ${holder}) is already using ${basename(ledgerPath)}. Stop it first, or use a different ledger path.`);
      }
      try { unlinkSync(lock); } catch { /* lost the race: retry */ }
    }
  }
  throw new LedgerFileError('locked', `Could not take the lock for ${basename(ledgerPath)}. Remove ${basename(ledgerPath)}.lock if no receiver is running.`);
}

function openReadOnly(path: string): DatabaseSync {
  if (!existsSync(path)) throw new LedgerFileError('missing', `No ledger at ${basename(path)}. Check the --ledger path.`);
  try {
    const db = new DatabaseSync(path, { readOnly: true });
    db.exec('PRAGMA busy_timeout=5000');
    db.prepare('SELECT 1 FROM events LIMIT 1').get();
    return db;
  } catch (error) {
    throw new LedgerFileError('unreadable', `${basename(path)} is not a readable OrderGuard ledger (${String((error as Error)?.message ?? error).slice(0, 80)}).`);
  }
}

export function verifyLedgerFile(path: string, expectHead?: LedgerHead): LedgerCheck {
  const db = openReadOnly(resolve(path));
  try { return verifyLedgerDb(db, { expectHead }); } finally { db.close(); }
}

const METAKEYS = ['schema', 'mandate_id', 'max_daily_cents', 'revoked_seq', 'paper_policy'];

export interface LedgerExport {
  format: 'orderguard-ledger-export/1';
  exportedAt: string;
  verification: { ok: boolean; problems: string[]; head: LedgerHead; events: number; orders: number; revoked: boolean };
  meta: Record<string, string>;
  orders: unknown[];
  events: unknown[];
}

/** A self-contained JSON copy of the ledger with its verification result. Contains no keys (the passkey record is excluded). */
export function exportLedger(path: string, now: () => Date = () => new Date()): LedgerExport {
  const db = openReadOnly(resolve(path));
  try {
    const check = verifyLedgerDb(db);
    const meta: Record<string, string> = {};
    for (const key of METAKEYS) {
      const row = db.prepare('SELECT v FROM meta WHERE k = ?').get(key) as { v: string } | undefined;
      if (row) meta[key] = row.v;
    }
    return {
      format: 'orderguard-ledger-export/1', exportedAt: now().toISOString(),
      verification: { ok: check.ok, problems: check.problems, head: check.head, events: check.events, orders: check.orders, revoked: check.revoked },
      meta, orders: db.prepare('SELECT * FROM orders ORDER BY seq').all(), events: db.prepare('SELECT * FROM events ORDER BY seq').all(),
    };
  } finally { db.close(); }
}

/**
 * A consistent SQLite copy (VACUUM INTO) that is itself verified. Refuses to overwrite and refuses to back up a ledger
 * that fails verification, so a good backup is never replaced by a damaged one.
 */
export function backupLedger(path: string, dest: string, opts: { allowTampered?: boolean } = {}): LedgerCheck {
  const source = resolve(path);
  const target = resolve(dest);
  if (existsSync(target)) throw new LedgerFileError('exists', `${basename(target)} already exists. Choose a new backup file name.`);
  const db = openReadOnly(source);
  const tmp = target + '.partial';
  try {
    const check = verifyLedgerDb(db);
    if (!check.ok && !opts.allowTampered) {
      throw new LedgerFileError('tampered', `The ledger failed verification (${check.problems[0]}); no backup was written. Run verify for details.`);
    }
    mkdirSync(dirname(target), { recursive: true, mode: 0o700 });
    if (existsSync(tmp)) unlinkSync(tmp);
    db.exec(`VACUUM INTO '${tmp.replace(/'/g, "''")}'`);
    chmodSync(tmp, 0o600);
    const copy = verifyLedgerFile(tmp);
    if (copy.ok !== check.ok || copy.head.hash !== check.head.hash) {
      unlinkSync(tmp);
      throw new LedgerFileError('unreadable', 'The backup copy did not verify identically to the source and was discarded. Try again.');
    }
    renameSync(tmp, target);
    return check;
  } finally {
    db.close();
    try { if (existsSync(tmp)) unlinkSync(tmp); } catch { /* best effort */ }
  }
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') {
    const o = value as Record<string, unknown>;
    return `{${Object.keys(o).sort().map((k) => `${JSON.stringify(k)}:${stable(o[k])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

/** Stable identity of a demo mandate (key order does not matter). Orders and idempotency keys in a ledger are bound to it. */
export const demoMandateId = (mandate: unknown): string => 'demo-' + sha256(stable(mandate)).slice(0, 16);
