import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import type { IncomingHttpHeaders } from 'node:http';
import { existsSync, mkdirSync, chmodSync, lstatSync } from 'node:fs';
import { dirname, isAbsolute } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

const MAX_CLOCK_SKEW_MS = 30_000;
const NONCE_TTL_MS = 60_000;
const MAX_NONCES = 20_000;

export type DurableNonceAcceptor = (
  identity: string,
  nonce: string,
  now: number,
  expiresAt: number,
) => boolean;

/** A separate, host-local SQLite journal for replay state shared by replicas. */
export class InternalNonceReplayJournal {
  private readonly db: DatabaseSync;
  private admissions = 0;

  constructor(path: string) {
    if (!isAbsolute(path) || path.length > 4096 || path === '/') {
      throw new Error('The internal nonce journal requires an absolute file path.');
    }
    mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
    if (existsSync(path) && lstatSync(path).isSymbolicLink()) {
      throw new Error('The internal nonce journal may not be a symbolic link.');
    }
    this.db = new DatabaseSync(path);
    try {
      this.db.exec(`
        PRAGMA busy_timeout = 5000;
        PRAGMA synchronous = FULL;
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS internal_auth_nonces (
          receiver_identity TEXT NOT NULL,
          sender_identity TEXT NOT NULL,
          nonce TEXT NOT NULL,
          expires_at_ms INTEGER NOT NULL,
          PRIMARY KEY (receiver_identity, sender_identity, nonce)
        );
        CREATE INDEX IF NOT EXISTS internal_auth_nonces_expiry_idx
          ON internal_auth_nonces (expires_at_ms);
      `);
      chmodSync(path, 0o600);
    } catch (error) {
      this.db.close();
      throw error;
    }
  }

  accept(receiverIdentity: string, senderIdentity: string, nonce: string, now: number, expiresAt: number): boolean {
    if (!receiverIdentity || receiverIdentity.length > 128 || !senderIdentity || senderIdentity.length > 128
      || !/^[0-9a-f-]{36}$/i.test(nonce) || !Number.isSafeInteger(now)
      || !Number.isSafeInteger(expiresAt) || expiresAt <= now) {
      return false;
    }
    this.admissions += 1;
    if (this.admissions % 128 === 0) {
      this.db.prepare('DELETE FROM internal_auth_nonces WHERE expires_at_ms <= ?').run(now);
    }
    const result = this.db.prepare(`
      INSERT OR IGNORE INTO internal_auth_nonces
        (receiver_identity, sender_identity, nonce, expires_at_ms)
      VALUES (?, ?, ?, ?)
    `).run(receiverIdentity, senderIdentity, nonce, expiresAt) as { changes: number | bigint };
    return Number(result.changes) === 1;
  }

  close(): void {
    this.db.close();
  }
}

function requestDigest(secret: string, identity: string, method: string, pathname: string, timestamp: string, nonce: string, body: string): string {
  return createHmac('sha256', secret)
    .update([identity, method.toUpperCase(), pathname, timestamp, nonce, body].join('\n'))
    .digest('base64url');
}

export function signedInternalHeaders(secret: string, identity: string, method: string, pathname: string, body: string): Record<string, string> {
  const timestamp = String(Date.now());
  const nonce = randomUUID();
  return {
    'x-orderguard-identity': identity,
    'x-orderguard-timestamp': timestamp,
    'x-orderguard-nonce': nonce,
    'x-orderguard-signature': requestDigest(secret, identity, method, pathname, timestamp, nonce, body),
  };
}

export interface InternalAuthHeaders {
  identity?: string | string[] | undefined;
  timestamp?: string | string[] | undefined;
  nonce?: string | string[] | undefined;
  signature?: string | string[] | undefined;
}

export function readInternalAuthHeaders(headers: IncomingHttpHeaders): InternalAuthHeaders {
  return {
    identity: headers['x-orderguard-identity'],
    timestamp: headers['x-orderguard-timestamp'],
    nonce: headers['x-orderguard-nonce'],
    signature: headers['x-orderguard-signature'],
  };
}

export function verifyInternalHeaders(
  secret: string,
  expectedIdentity: string,
  method: string,
  pathname: string,
  body: string,
  headers: InternalAuthHeaders,
  now = Date.now(),
): { valid: boolean; nonce: string | null; timestamp: number | null } {
  const { identity, timestamp, nonce, signature } = headers;
  if (identity !== expectedIdentity || typeof timestamp !== 'string' || typeof nonce !== 'string' || typeof signature !== 'string') {
    return { valid: false, nonce: null, timestamp: null };
  }
  if (!/^\d{13}$/.test(timestamp) || !/^[0-9a-f-]{36}$/i.test(nonce) || !/^[A-Za-z0-9_-]{43}$/.test(signature)) {
    return { valid: false, nonce: null, timestamp: null };
  }
  const timestampNumber = Number(timestamp);
  if (!Number.isSafeInteger(timestampNumber) || Math.abs(now - timestampNumber) > MAX_CLOCK_SKEW_MS) {
    return { valid: false, nonce: null, timestamp: timestampNumber };
  }
  const expected = Buffer.from(requestDigest(secret, identity, method, pathname, timestamp, nonce, body));
  const supplied = Buffer.from(signature);
  return {
    valid: expected.length === supplied.length && timingSafeEqual(expected, supplied),
    nonce,
    timestamp: timestampNumber,
  };
}

export class InternalNonceReplayGuard {
  private readonly observed = new Map<string, number>();

  constructor(private readonly durableAcceptor?: DurableNonceAcceptor) {}

  accept(identity: string, nonce: string, now = Date.now()): boolean {
    if (this.durableAcceptor) {
      try {
        return this.durableAcceptor(identity, nonce, now, now + NONCE_TTL_MS);
      } catch {
        // An unavailable durable replay journal must reject the request.
        return false;
      }
    }
    for (const [key, expiresAt] of this.observed) {
      if (expiresAt <= now) this.observed.delete(key);
    }
    const key = identity + ':' + nonce;
    if (this.observed.has(key) || this.observed.size >= MAX_NONCES) return false;
    this.observed.set(key, now + NONCE_TTL_MS);
    return true;
  }
}
