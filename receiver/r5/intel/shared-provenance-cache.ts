import { DatabaseSync } from 'node:sqlite';
import { chmodSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

export interface SharedProvenanceScoreV1 {
  probability: number;
  provider: string;
  model: string;
  responseId: string | null;
  usageInputTokens: number | null;
  usageOutputTokens: number;
  usageCostUsd: number | null;
  createdAt: number;
  precomputeLatencyMs: number;
  spendUsd: number;
  costBasis: string;
}

export type SharedProvenanceCacheStateV1 =
  | { kind: 'scored'; score: SharedProvenanceScoreV1 }
  | { kind: 'unavailable'; cause: string; createdAt: number }
  | { kind: 'pending'; owner: string; leaseUntil: number }
  | null;

export type SharedProvenanceClaimV1 =
  | { kind: 'claimed' }
  | { kind: 'scored'; score: SharedProvenanceScoreV1 }
  | { kind: 'unavailable'; cause: string; createdAt: number }
  | { kind: 'pending'; owner: string; leaseUntil: number };

const CACHE_SCHEMA = `
  CREATE TABLE IF NOT EXISTS provenance_content_score_cache (
    content_hash TEXT PRIMARY KEY CHECK (length(content_hash) = 64),
    status TEXT NOT NULL CHECK (status IN ('pending', 'scored', 'unavailable')),
    created_at_ms INTEGER NOT NULL,
    lease_owner TEXT,
    lease_until_ms INTEGER,
    provider TEXT,
    model TEXT,
    response_id TEXT,
    probability REAL,
    usage_input_tokens INTEGER,
    usage_output_tokens INTEGER,
    usage_cost_usd REAL,
    precompute_latency_ms REAL NOT NULL DEFAULT 0,
    spend_usd REAL NOT NULL DEFAULT 0,
    cost_basis TEXT NOT NULL DEFAULT 'none',
    cause TEXT
  );
  CREATE INDEX IF NOT EXISTS provenance_content_score_cache_created
    ON provenance_content_score_cache(created_at_ms);
`;

/**
 * Optional same-host, process-shared cache for content-only provenance scores.
 * SQLite's immediate transaction provides one provider-call lease per hash;
 * the database stores hashes and typed score metadata, never source text.
 */
export class SharedProvenanceCacheV1 {
  private readonly db: DatabaseSync;

  constructor(path: string) {
    const absolutePath = resolve(path);
    mkdirSync(dirname(absolutePath), { recursive: true, mode: 0o700 });
    this.db = new DatabaseSync(absolutePath);
    this.db.exec('PRAGMA busy_timeout = 5000; PRAGMA synchronous = FULL;');
    this.enableWalMode();
    this.db.exec(CACHE_SCHEMA);
    chmodSync(absolutePath, 0o600);
  }

  read(contentHash: string): SharedProvenanceCacheStateV1 {
    const row = this.db.prepare(`
      SELECT status, created_at_ms, lease_owner, lease_until_ms, provider, model, response_id,
        probability, usage_input_tokens, usage_output_tokens, usage_cost_usd,
        precompute_latency_ms, spend_usd, cost_basis, cause
      FROM provenance_content_score_cache WHERE content_hash = ?
    `).get(contentHash) as Record<string, unknown> | undefined;
    if (!row) return null;
    if (row.status === 'pending' && typeof row.lease_owner === 'string'
      && Number.isSafeInteger(row.lease_until_ms)) {
      return { kind: 'pending', owner: row.lease_owner, leaseUntil: Number(row.lease_until_ms) };
    }
    if (row.status === 'unavailable' && typeof row.cause === 'string'
      && Number.isSafeInteger(row.created_at_ms)) {
      return { kind: 'unavailable', cause: row.cause, createdAt: Number(row.created_at_ms) };
    }
    if (row.status !== 'scored' || !['liquid', 'openrouter', 'openai', 'typesafe'].includes(String(row.provider))
      || typeof row.model !== 'string' || !row.model
      || !(row.response_id === null || typeof row.response_id === 'string')
      || typeof row.probability !== 'number' || !Number.isFinite(row.probability) || row.probability < 0 || row.probability > 1
      || !Number.isSafeInteger(row.created_at_ms) || !Number.isFinite(row.precompute_latency_ms)
      || !Number.isFinite(row.spend_usd) || !['provider-usage', 'token-rate-estimate', 'mixed', 'none'].includes(String(row.cost_basis))) return null;
    return {
      kind: 'scored',
      score: {
        probability: row.probability,
        provider: String(row.provider),
        model: row.model,
        responseId: row.response_id as string | null,
        usageInputTokens: Number.isSafeInteger(row.usage_input_tokens) ? Number(row.usage_input_tokens) : null,
        usageOutputTokens: Number.isSafeInteger(row.usage_output_tokens) ? Number(row.usage_output_tokens) : 0,
        usageCostUsd: typeof row.usage_cost_usd === 'number' && Number.isFinite(row.usage_cost_usd)
          ? row.usage_cost_usd : null,
        createdAt: Number(row.created_at_ms),
        precomputeLatencyMs: Number(row.precompute_latency_ms),
        spendUsd: Number(row.spend_usd),
        costBasis: String(row.cost_basis),
      },
    };
  }

  claim(contentHash: string, owner: string, nowMs: number, ttlMs: number, leaseMs: number): SharedProvenanceClaimV1 {
    this.db.exec('BEGIN IMMEDIATE;');
    try {
      const state = this.read(contentHash);
      if (state?.kind === 'scored' && nowMs - state.score.createdAt <= ttlMs) {
        this.db.exec('COMMIT;');
        return state;
      }
      if (state?.kind === 'unavailable' && nowMs - state.createdAt <= ttlMs) {
        this.db.exec('COMMIT;');
        return state;
      }
      if (state?.kind === 'pending' && state.leaseUntil > nowMs) {
        this.db.exec('COMMIT;');
        return state;
      }
      this.db.prepare(`
        INSERT INTO provenance_content_score_cache (
          content_hash, status, created_at_ms, lease_owner, lease_until_ms,
          precompute_latency_ms, spend_usd, cost_basis
        ) VALUES (?, 'pending', ?, ?, ?, 0, 0, 'none')
        ON CONFLICT(content_hash) DO UPDATE SET
          status = 'pending', created_at_ms = excluded.created_at_ms,
          lease_owner = excluded.lease_owner, lease_until_ms = excluded.lease_until_ms,
          provider = NULL, model = NULL, response_id = NULL, probability = NULL,
          usage_input_tokens = NULL, usage_output_tokens = NULL, usage_cost_usd = NULL,
          precompute_latency_ms = 0, spend_usd = 0, cost_basis = 'none', cause = NULL
      `).run(contentHash, nowMs, owner, nowMs + leaseMs);
      this.db.exec('COMMIT;');
      return { kind: 'claimed' };
    } catch (error) {
      try { this.db.exec('ROLLBACK;'); } catch { /* Preserve the original SQLite error. */ }
      throw error;
    }
  }

  completeScore(contentHash: string, owner: string, score: SharedProvenanceScoreV1): boolean {
    const result = this.db.prepare(`
      UPDATE provenance_content_score_cache SET
        status = 'scored', created_at_ms = ?, lease_owner = NULL, lease_until_ms = NULL,
        provider = ?, model = ?, response_id = ?, probability = ?, usage_input_tokens = ?,
        usage_output_tokens = ?, usage_cost_usd = ?, precompute_latency_ms = ?,
        spend_usd = ?, cost_basis = ?, cause = NULL
      WHERE content_hash = ? AND status = 'pending' AND lease_owner = ? AND lease_until_ms > ?
    `).run(score.createdAt, score.provider, score.model, score.responseId, score.probability,
      score.usageInputTokens, score.usageOutputTokens, score.usageCostUsd,
      score.precomputeLatencyMs, score.spendUsd, score.costBasis, contentHash, owner, Date.now());
    chmodSync(this.databasePath(), 0o600);
    const completed = Number(result.changes) === 1;
    if (completed) this.trim(2_000);
    return completed;
  }

  completeFailure(contentHash: string, owner: string, cause: string, createdAt: number): boolean {
    const result = this.db.prepare(`
      UPDATE provenance_content_score_cache SET
        status = 'unavailable', created_at_ms = ?, lease_owner = NULL, lease_until_ms = NULL,
        provider = NULL, model = NULL, response_id = NULL, probability = NULL,
        usage_input_tokens = NULL, usage_output_tokens = NULL, usage_cost_usd = NULL,
        precompute_latency_ms = 0, spend_usd = 0, cost_basis = 'none', cause = ?
      WHERE content_hash = ? AND status = 'pending' AND lease_owner = ? AND lease_until_ms > ?
    `).run(createdAt, cause, contentHash, owner, Date.now());
    const completed = Number(result.changes) === 1;
    if (completed) this.trim(2_000);
    return completed;
  }

  recordFailure(contentHash: string, cause: string, createdAt: number): void {
    this.db.prepare(`
      INSERT INTO provenance_content_score_cache (
        content_hash, status, created_at_ms, lease_owner, lease_until_ms,
        precompute_latency_ms, spend_usd, cost_basis, cause
      ) VALUES (?, 'unavailable', ?, NULL, NULL, 0, 0, 'none', ?)
      ON CONFLICT(content_hash) DO UPDATE SET
        status = 'unavailable', created_at_ms = excluded.created_at_ms,
        lease_owner = NULL, lease_until_ms = NULL, provider = NULL, model = NULL,
        response_id = NULL, probability = NULL, usage_input_tokens = NULL,
        usage_output_tokens = NULL, usage_cost_usd = NULL, precompute_latency_ms = 0,
        spend_usd = 0, cost_basis = 'none', cause = excluded.cause
    `).run(contentHash, createdAt, cause);
    this.trim(2_000);
  }

  hasPending(contentHash: string): boolean {
    const state = this.read(contentHash);
    return state?.kind === 'pending';
  }

  private enableWalMode(): void {
    const deadline = Date.now() + 5_000;
    let delayMs = 5;
    while (true) {
      try {
        this.db.exec('PRAGMA journal_mode = WAL;');
        return;
      } catch (error) {
        const sqliteError = error as { errcode?: unknown };
        if ((sqliteError.errcode !== 5 && sqliteError.errcode !== 6) || Date.now() >= deadline) throw error;
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, delayMs);
        delayMs = Math.min(delayMs * 2, 100);
      }
    }
  }

  private databasePath(): string {
    const row = this.db.prepare('PRAGMA database_list;').all() as Array<Record<string, unknown>>;
    const main = row.find((entry) => entry.name === 'main');
    return typeof main?.file === 'string' ? main.file : '';
  }

  private trim(limit: number): void {
    this.db.prepare(`
      DELETE FROM provenance_content_score_cache
      WHERE content_hash IN (
        SELECT content_hash FROM provenance_content_score_cache
        WHERE status != 'pending' ORDER BY created_at_ms DESC LIMIT -1 OFFSET ?
      )
    `).run(limit);
  }
}
