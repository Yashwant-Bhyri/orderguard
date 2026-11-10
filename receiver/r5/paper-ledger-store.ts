import { DatabaseSync } from 'node:sqlite';
import { constants, mkdirSync, chmodSync, existsSync, readFileSync, readdirSync, openSync, writeSync, fsyncSync, closeSync, renameSync, unlinkSync, fchmodSync, fstatSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash, createHmac, createPublicKey, randomBytes, timingSafeEqual, verify as verifySignature } from 'node:crypto';
import { isHkexEquityPrice } from './hkex-equity-price-rules.js';
import { createPendingStepUpHold, matchPendingStepUpHold } from './intel/pending-step-up-hold.js';
import { paperAuditWitnessAnchorHash, readPaperAuditWitnessConfig, requestPaperAuditWitness, type PaperAuditWitnessConfig, type PaperAuditWitnessStateV1 } from './paper-audit-witness.js';
import type { MeshToolAudit } from './execution-mesh.js';
import { causalTriggerContextError, triggerScopeError, type CausalTriggerContextV1, type PaperTriggerEffectAuditV1, type TriggerScopeV1 } from './trigger-scope.js';

export interface DurablePaperOrder {
  orderHash: string;
  intentHash: string;
  orderId: string;
  order: unknown;
  marketQuote: unknown;
  marketQuoteResult: unknown;
  marketQuoteReceipt: unknown;
  execution: unknown;
  cancelled: boolean;
  createdAt?: number;
  ledgerBinding?: PaperOrderLedgerBindingV1;
}

export interface PaperOrderLedgerBindingV1 {
  idempotencyKey: string;
  budgetKey: string;
  budgetNotionalUsd: number;
  budgetNotionalMinor: number;
  budgetCurrency: 'USD' | 'HKD';
  createdAt: number;
}

export interface PaperExecutionAuditRecordV1 {
  schemaVersion: 1;
  kind: 'commit' | 'cancel';
  outcome: 'accepted' | 'recovered' | 'applied' | 'blocked' | 'unknown' | 'held' | 'rejected' | 'committing';
  recordedAt: string;
  ownerApproval?: {
    method: 'webauthn-passkey-v1';
    evidenceHash: string;
    authorizedOrderHash: string;
  };
  /** Present only for a commit authorized by a versioned trigger scope. */
  triggerEffect?: PaperTriggerEffectAuditV1;
  proposal: {
    runId: string;
    market: 'US' | 'HK';
    symbol: string;
    side: 'buy' | 'sell';
    quantity: number;
    orderType: 'market' | 'limit';
    limitPrice: number | null;
    session: string;
    timeInForce: 'day' | 'gtc';
  };
  audit: MeshToolAudit;
}

export interface PaperDecisionAttemptV1 {
  orderId: string;
  record: PaperExecutionAuditRecordV1;
}

export interface PaperAuditIntegritySummaryV1 {
  verified: true;
  auditRecords: number;
  orderChains: number;
  anchoredOrderHeads: number;
  killSwitchEvents: number;
  killSwitchVersion: number;
  causalTriggerBreakerEvents: number;
  keySource: 'environment' | 'local-sidecar' | 'process-memory';
  checkpoint: 'host-local-file' | 'remote-witness-configured' | 'process-memory';
  verifiedAt: string;
}

export interface PaperDecisionJournalV1 {
  attempts: PaperDecisionAttemptV1[];
  integrity: PaperAuditIntegritySummaryV1;
}

export type PaperCommitResult =
  | { kind: 'inserted'; order: DurablePaperOrder; insertionAudit?: PaperExecutionAuditRecordV1 }
  | { kind: 'replay'; order: DurablePaperOrder }
  | { kind: 'conflict'; order?: DurablePaperOrder }
  | { kind: 'revoked' }
  | { kind: 'kill-switch-active' }
  | { kind: 'mandate-revoked' }
  | { kind: 'mandate-order-limit' }
  | { kind: 'second-lock-held' }
  | { kind: 'mandate-budget-exceeded'; usedNotionalMinor: number; requestedNotionalMinor: number; maxNotionalMinor: number }
  | { kind: 'trigger-scope-denied'; reason: string }
  | { kind: 'trigger-breaker-open'; scope: 'trigger' | 'window'; reason: string }
  | { kind: 'trigger-breaker-opened'; scope: 'trigger' | 'window'; reason: string }
  | { kind: 'budget-exceeded'; usedNotionalUsd: number; requestedNotionalUsd: number; maxNotionalUsd: number; usedNotionalMinor?: number; requestedNotionalMinor?: number; maxNotionalMinor?: number };

export type FutuProposalConfirmationPhaseV1 = 'prepared' | 'processing' | 'dispatching' | 'complete';
export interface FutuProposalConfirmationBindingV1 {
  runId: string;
  mandateId: string;
  originalRequest: string;
  model: string;
  attackCardId: string;
  condition: 'attack' | 'control';
}
export interface FutuProposalConfirmationRecordV1 {
  payload: Record<string, unknown>;
  phase: FutuProposalConfirmationPhaseV1;
  leaseOwner: string | null;
  leaseUntilMs: number | null;
  dispatchLeaseUntilMs: number | null;
  expiresAtMs: number;
}
export type FutuProposalConfirmationClaimV1 =
  | { kind: 'claimed'; record: FutuProposalConfirmationRecordV1 }
  | { kind: 'complete'; record: FutuProposalConfirmationRecordV1 }
  | { kind: 'processing' | 'dispatching'; record: FutuProposalConfirmationRecordV1 }
  | { kind: 'dispatching-claimed'; record: FutuProposalConfirmationRecordV1 }
  | { kind: 'missing' | 'expired' | 'binding_mismatch' };

export interface PaperCommitControls {
  capabilityJti: string;
  budgetKey: string;
  maxNotionalUsd?: number;
  maxNotionalAmount?: { amount_minor: number; currency: 'HKD' };
  ledgerConversion?: { numerator: number; denominator: number };
  mandate?: { id: string; hash: string; maxOrders: number; maxSessionNotionalUsd: number; triggerScopeV1?: TriggerScopeV1 };
  triggerGuard?: {
    scope: TriggerScopeV1;
    context: CausalTriggerContextV1;
    mandateId: string;
    mandateHash: string;
    authorityKind: 'user-signed' | 'synthetic-policy';
  };
  /** Stable hash of the exact proposed action; a prior Lock-2 hold blocks this at commit. */
  secondLockActionHash?: string;
  /** Human-passkey mandate claim binding an explicit approval to a held action. */
  secondLockHoldApprovalHash?: string;
  /** Require the receiver's signed applied receipt to be anchored in this insert transaction. */
  requireReceiptBackedCommitAudit?: boolean;
  nowMs?: number;
}

export interface PaperSecondLockHoldScope {
  accountKey: string;
  sessionKey: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
}

/** Derive hold scope from the signed paper-budget scope and typed order. */
export function derivePaperSecondLockHoldScope(budgetKey: string, value: unknown): PaperSecondLockHoldScope {
  const order = value && typeof value === 'object' ? value as Record<string, unknown> : null;
  const market = order?.market;
  const session = order?.session;
  const symbol = order?.symbol;
  const side = order?.side;
  const quantity = order?.quantity;
  if (typeof budgetKey !== 'string' || !budgetKey.trim() || budgetKey.length > 180
    || (market !== 'US' && market !== 'HK') || typeof session !== 'string' || !/^[a-z][a-z0-9_-]{0,31}$/.test(session)
    || typeof symbol !== 'string' || !/^[A-Z0-9][A-Z0-9._-]{0,19}$/.test(symbol)
    || (side !== 'buy' && side !== 'sell') || !Number.isSafeInteger(quantity) || Number(quantity) <= 0) {
    throw new Error('A typed paper order and bounded budget key are required for the second-lock hold scope.');
  }
  return {
    // Budget limits roll over by date; unresolved human holds do not.
    accountKey: budgetKey.replace(/:\d{4}-\d{2}-\d{2}(?=:|$)/, ''),
    sessionKey: `${market}:${session}`,
    symbol,
    side,
    quantity: Number(quantity),
  };
}

export interface StoredOwnerCredential {
  credentialId: string;
  publicKey: string;
  counter: number;
  transports: string[];
  origin: string;
  rpId: string;
}

export interface StoredHumanMandate {
  mandateId: string;
  mandateHash: string;
  document: unknown;
  createdAt: number;
  expiresAt: number;
  revokedAt: number | null;
  revokeRequestedAt: number | null;
}

export interface StoredOwnerPreference {
  preferenceId: string;
  preferenceKey: string;
  preferenceHash: string;
  document: unknown;
  createdAt: number;
  expiresAt: number;
  revokedAt: number | null;
  revokedByCredentialId: string | null;
  revocationEvidenceHash: string | null;
}

export interface StoredKillSwitchState {
  active: boolean;
  version: number;
  changedAt: number | null;
  credentialId: string | null;
  evidenceHash: string | null;
}

export interface KillSwitchTransition {
  active: boolean;
  expectedVersion: number;
  credentialId: string;
  evidenceHash: string;
  nowMs?: number;
}

export interface FutuM1DispatchAuthorization {
  idempotencyKey: string;
  orderId: string;
  orderHash: string;
  mandateId: string;
  mandateHash: string;
  quoteReceiptHash: string;
  secondLockDecision: 'allow';
  version: 'MANDATE-M1-v1.0.0';
}

export type PaperCancelResult =
  | { kind: 'cancelled'; order: DurablePaperOrder; appliedAudit?: PaperExecutionAuditRecordV1 }
  | { kind: 'replay'; order: DurablePaperOrder }
  | { kind: 'dispatch-blocked'; state: 'dispatching' | 'unknown' | 'conflict' | 'accepted' }
  | { kind: 'missing' }
  | { kind: 'conflict' };

export interface MandateCancellationOutboxItemV1 {
  outboxId: string;
  venue: string;
  mandateId: string;
  mandateHash: string;
  idempotencyKey: string;
  orderId: string;
  orderHash: string;
  orderQuantityAtoms: number;
  clientOrderId: string;
  venueOrderId: string | null;
  orderJson: string;
  reason: 'revoked' | 'expired';
  state: 'pending' | 'dispatching' | 'retry' | 'cancelled' | 'filled' | 'expired' | 'blocked';
  attemptCount: number;
  leaseUntilMs: number | null;
  nextAttemptAtMs: number;
}

export interface MandateCancellationObservationV1 {
  venue: string;
  mandateId: string;
  mandateHash: string;
  idempotencyKey: string;
  orderId: string;
  orderHash: string;
  clientOrderId: string;
  venueOrderId: string;
  orderStatus: 'OPEN' | 'PARTIALLY_FILLED' | 'FILLED' | 'CANCELED' | 'EXPIRED' | 'UNKNOWN' | 'MISMATCH';
  orderHistoryMatched: boolean;
  tradeHistoryMatched: boolean;
  cancelConfirmed: boolean;
  matchedTradeAtoms: number;
  orderQuantityAtoms: number;
}

type SqlRow = Record<string, unknown>;

interface TriggerGuardPlanV1 {
  eventJson: string;
  eventSha256: string;
  scopeSha256: string;
  triggerId: string;
  rootTriggerId: string;
  parentEffectOrderId: string | null;
  standingRuleRef: string;
  policyEpoch: number;
  mandateId: string;
  mandateHash: string;
  triggerType: string;
  sourceProvenance: string;
  sourceSha256: string;
  receivedAtMs: number;
  expiresAtMs: number;
  symbol: string;
  side: 'buy' | 'sell';
  notionalUsdMinor: number;
}

type TriggerGuardDecisionV1 =
  | { kind: 'allow'; plan: TriggerGuardPlanV1 }
  | { kind: 'deny'; reason: string }
  | { kind: 'breaker-open'; scope: 'trigger' | 'window'; reason: string }
  | { kind: 'breaker-opened'; scope: 'trigger' | 'window'; reason: string };

interface PaperAuditAnchor {
  schemaVersion: 2;
  orders: Record<string, { sequence: number; headMac: string }>;
  killSwitch: { version: number; headMac: string };
  /** Optional v1 causal-breaker chains preserve byte-for-byte compatibility with older v2 anchors. */
  causalTriggerBreakerHeadsV1?: Record<string, { sequence: number; headMac: string }>;
}

interface LegacyPaperAuditAnchorV1 {
  schemaVersion: 1;
  orders: Record<string, { sequence: number; headMac: string }>;
}

interface KillSwitchAuditEventV1 {
  version: number;
  active: boolean;
  changedAt: number;
  credentialId: string;
  evidenceHash: string;
}

interface CausalTriggerBreakerAuditV1 {
  version: 1;
  breakerKey: string;
  budgetKey: string;
  breakerScope: 'trigger' | 'window';
  scopeRef: string;
  policyEpoch: number;
  openedAtMs: number;
  mandateId: string;
  reason: string;
  scopeSha256: string;
}

interface SignedPaperAuditAnchor {
  payload: PaperAuditAnchor;
  mac: string;
}

interface PaperAuditCheckpointTransitionV1 {
  schemaVersion: 1;
  transactionId: string;
  previous: PaperAuditAnchor;
  next: PaperAuditAnchor;
}

interface SignedPaperAuditCheckpointTransitionV1 {
  payload: PaperAuditCheckpointTransitionV1;
  mac: string;
}

interface PaperLedgerReceiptEvidence {
  signerPublicKey: string;
  document: { claims: Record<string, unknown>; signature: string };
  result: unknown;
}

const PAPER_AUDIT_GENESIS = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const KILL_SWITCH_AUDIT_GENESIS = PAPER_AUDIT_GENESIS;

/**
 * A single authoritative SQLite journal for synthetic paper effects.
 * BEGIN IMMEDIATE serializes commits across independent processes sharing this file.
 */
export class PaperLedgerStore {
  private readonly db: DatabaseSync;
  private readonly auditKey: Buffer;
  private readonly policyPublicKeyPem: string | null;
  private readonly auditKeySource: PaperAuditIntegritySummaryV1['keySource'];
  private readonly auditAnchorPath: string | null;
  private readonly auditAnchorDirectory: string | null;
  private readonly auditAnchorFilename: string | null;
  private readonly auditWitness: PaperAuditWitnessConfig | null;
  private verifiedPaperAuditCheckpoint: { dataVersion: number; anchorJson: string } | null = null;
  private memoryAuditAnchor: PaperAuditAnchor = {
    schemaVersion: 2, orders: {}, killSwitch: { version: 0, headMac: KILL_SWITCH_AUDIT_GENESIS },
  };

  constructor(path: string, policyPublicKeyPem?: string) {
    if (path !== ':memory:' && !path.startsWith('file:')) {
      mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
    }
    this.db = new DatabaseSync(path);
    this.policyPublicKeyPem = policyPublicKeyPem ?? null;
    const auditBasePath = paperLedgerSidecarBase(path);
    this.auditAnchorPath = auditBasePath ? auditBasePath + '.audit-head.json' : null;
    this.auditAnchorDirectory = this.auditAnchorPath ? dirname(this.auditAnchorPath) : null;
    this.auditAnchorFilename = this.auditAnchorPath ? this.auditAnchorPath.slice(this.auditAnchorDirectory!.length + 1) : null;
    this.auditWitness = readPaperAuditWitnessConfig();
    if (this.auditWitness && !this.auditAnchorPath) {
      throw new Error('An independent paper-audit witness requires a persistent SQLite ledger path.');
    }
    this.auditKeySource = process.env.ORDERGUARD_AUDIT_KEY !== undefined ? 'environment' : auditBasePath ? 'local-sidecar' : 'process-memory';
    this.auditKey = loadOrCreatePaperAuditKey(auditBasePath ? auditBasePath + '.audit-key' : null);
    this.db.exec('PRAGMA busy_timeout = 5000; PRAGMA synchronous = FULL;');
    if (path !== ':memory:') enableWalMode(this.db);
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS paper_orders (
        idempotency_key TEXT PRIMARY KEY,
        order_id TEXT NOT NULL UNIQUE,
        order_hash TEXT NOT NULL,
        intent_hash TEXT NOT NULL,
        order_json TEXT NOT NULL,
        market_quote_json TEXT NOT NULL,
        market_quote_result_json TEXT NOT NULL,
        market_quote_receipt_json TEXT NOT NULL,
        execution_json TEXT NOT NULL,
        cancelled INTEGER NOT NULL DEFAULT 0 CHECK (cancelled IN (0, 1)),
        created_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS paper_cancellations (
        idempotency_key TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        order_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS paper_execution_audits (
        order_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        record_json TEXT NOT NULL,
        record_hash TEXT NOT NULL CHECK (length(record_hash) = 43),
        previous_mac TEXT NOT NULL CHECK (length(previous_mac) = 43),
        record_mac TEXT NOT NULL CHECK (length(record_mac) = 43),
        recorded_at_ms INTEGER NOT NULL,
        PRIMARY KEY (order_id, sequence),
        UNIQUE (order_id, record_hash)
      );
      CREATE TABLE IF NOT EXISTS revoked_capabilities (
        jti TEXT PRIMARY KEY,
        revoked_until INTEGER NOT NULL,
        revoked_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS b3_cell_request_bindings (
        cell_id TEXT PRIMARY KEY,
        request_sha256 TEXT NOT NULL,
        bound_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS futu_m1_dispatch_authorizations (
        idempotency_key TEXT PRIMARY KEY,
        order_id TEXT NOT NULL UNIQUE,
        order_hash TEXT NOT NULL,
        mandate_id TEXT NOT NULL,
        mandate_hash TEXT NOT NULL,
        quote_receipt_hash TEXT NOT NULL,
        second_lock_decision TEXT NOT NULL CHECK (second_lock_decision = 'allow'),
        version TEXT NOT NULL CHECK (version = 'MANDATE-M1-v1.0.0'),
        created_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS arena_c1_dispatch_authorizations (
        authorization_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL UNIQUE,
        order_id TEXT NOT NULL UNIQUE,
        order_hash TEXT NOT NULL,
        quote_receipt_hash TEXT NOT NULL,
        notional_minor INTEGER NOT NULL CHECK (notional_minor > 0 AND notional_minor <= 50000),
        budget_key TEXT NOT NULL,
        expires_at_ms INTEGER NOT NULL,
        authorization_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('authorized','dispatching','accepted','unknown','rejected')),
        result_json TEXT,
        created_at_ms INTEGER NOT NULL,
        updated_at_ms INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS arena_c1_mandate_control (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        mandate_id TEXT NOT NULL CHECK (mandate_id = 'MANDATE-C1'),
        policy_digest TEXT NOT NULL CHECK (length(policy_digest) = 64),
        state TEXT NOT NULL CHECK (state IN ('active','revoking','revoked')),
        revoke_requested_at_ms INTEGER,
        revoked_at_ms INTEGER,
        revoked_by_credential_id TEXT,
        revocation_evidence_hash TEXT CHECK (revocation_evidence_hash IS NULL OR length(revocation_evidence_hash) = 43),
        updated_at_ms INTEGER NOT NULL,
        CHECK ((state = 'active' AND revoke_requested_at_ms IS NULL AND revoked_at_ms IS NULL
          AND revoked_by_credential_id IS NULL AND revocation_evidence_hash IS NULL)
          OR (state = 'revoking' AND revoke_requested_at_ms IS NOT NULL AND revoked_at_ms IS NULL
          AND revoked_by_credential_id IS NOT NULL AND revocation_evidence_hash IS NOT NULL)
          OR (state = 'revoked' AND revoke_requested_at_ms IS NOT NULL AND revoked_at_ms IS NOT NULL
          AND revoked_by_credential_id IS NOT NULL AND revocation_evidence_hash IS NOT NULL))
      );
      CREATE TABLE IF NOT EXISTS futu_simulate_dispatches (
        idempotency_key TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        order_hash TEXT NOT NULL,
        remark TEXT NOT NULL UNIQUE,
        state TEXT NOT NULL CHECK (state IN ('prepared','dispatching','accepted','unknown','rejected','conflict')),
        broker_order_id TEXT,
        account_id TEXT,
        account_masked TEXT,
        reconciliation_json TEXT,
        updated_at_ms INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS futu_proposal_confirmations (
        token_hash TEXT PRIMARY KEY CHECK (length(token_hash) = 64),
        phase TEXT NOT NULL CHECK (phase IN ('prepared','processing','dispatching','complete')),
        payload_json TEXT NOT NULL,
        lease_owner TEXT,
        lease_until_ms INTEGER,
        dispatch_lease_until_ms INTEGER,
        expires_at_ms INTEGER NOT NULL,
        created_at_ms INTEGER NOT NULL,
        updated_at_ms INTEGER NOT NULL,
        CHECK ((phase = 'processing' AND lease_owner IS NOT NULL AND lease_until_ms IS NOT NULL)
          OR (phase = 'dispatching' AND lease_owner IS NOT NULL AND lease_until_ms IS NULL)
          OR (phase IN ('prepared','complete') AND lease_owner IS NULL AND lease_until_ms IS NULL))
      );
      CREATE INDEX IF NOT EXISTS futu_proposal_confirmations_active_idx
        ON futu_proposal_confirmations(phase, expires_at_ms, updated_at_ms);
      CREATE TABLE IF NOT EXISTS venue_mandate_orders (
        venue TEXT NOT NULL,
        mandate_id TEXT NOT NULL,
        mandate_hash TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        order_id TEXT NOT NULL,
        order_hash TEXT NOT NULL,
        order_quantity_atoms INTEGER NOT NULL CHECK (order_quantity_atoms > 0),
        client_order_id TEXT NOT NULL,
        venue_order_id TEXT,
        order_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('resident','unknown','cancelled','filled','expired','blocked')),
        created_at_ms INTEGER NOT NULL,
        updated_at_ms INTEGER NOT NULL,
        PRIMARY KEY (venue, mandate_id, order_id),
        UNIQUE (venue, client_order_id)
      );
      CREATE TABLE IF NOT EXISTS mandate_cancellation_outbox (
        outbox_id TEXT PRIMARY KEY,
        venue TEXT NOT NULL,
        mandate_id TEXT NOT NULL,
        mandate_hash TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        order_id TEXT NOT NULL,
        order_hash TEXT NOT NULL,
        order_quantity_atoms INTEGER NOT NULL CHECK (order_quantity_atoms > 0),
        client_order_id TEXT NOT NULL,
        venue_order_id TEXT,
        order_json TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (reason IN ('revoked','expired')),
        state TEXT NOT NULL CHECK (state IN ('pending','dispatching','retry','cancelled','filled','expired','blocked')),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        lease_until_ms INTEGER,
        next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
        last_observation_json TEXT,
        created_at_ms INTEGER NOT NULL,
        updated_at_ms INTEGER NOT NULL,
        UNIQUE (venue, mandate_id, order_id)
      );
      CREATE TABLE IF NOT EXISTS owner_credentials (
        credential_id TEXT PRIMARY KEY,
        public_key TEXT NOT NULL,
        counter INTEGER NOT NULL,
        transports_json TEXT NOT NULL,
        origin TEXT NOT NULL,
        rp_id TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        revoked_at INTEGER
      );
      CREATE TABLE IF NOT EXISTS human_mandates (
        mandate_id TEXT PRIMARY KEY,
        mandate_hash TEXT NOT NULL,
        document_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        revoked_at INTEGER,
        revoke_requested_at INTEGER
      );
      CREATE TABLE IF NOT EXISTS owner_authorized_preferences (
        preference_id TEXT PRIMARY KEY,
        preference_key TEXT NOT NULL,
        preference_hash TEXT NOT NULL,
        document_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        revoked_at INTEGER,
        revoked_by_credential_id TEXT,
        revocation_evidence_hash TEXT
      );
      CREATE INDEX IF NOT EXISTS owner_authorized_preferences_key_idx
        ON owner_authorized_preferences (preference_key, created_at DESC);
      CREATE TABLE IF NOT EXISTS human_mandate_orders (
        idempotency_key TEXT PRIMARY KEY,
        mandate_id TEXT NOT NULL,
        order_id TEXT NOT NULL UNIQUE,
        notional_usd_minor INTEGER NOT NULL,
        created_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS causal_trigger_events (
        trigger_id TEXT PRIMARY KEY,
        root_trigger_id TEXT NOT NULL,
        mandate_id TEXT NOT NULL,
        policy_epoch INTEGER NOT NULL CHECK (policy_epoch > 0),
        trigger_type TEXT NOT NULL,
        source_provenance TEXT NOT NULL,
        source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
        event_json TEXT NOT NULL,
        event_sha256 TEXT NOT NULL CHECK (length(event_sha256) = 43),
        received_at_ms INTEGER NOT NULL,
        expires_at_ms INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS causal_trigger_effects (
        order_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL UNIQUE,
        budget_key TEXT NOT NULL,
        mandate_id TEXT NOT NULL,
        policy_epoch INTEGER NOT NULL CHECK (policy_epoch > 0),
        trigger_id TEXT NOT NULL,
        root_trigger_id TEXT NOT NULL,
        parent_effect_order_id TEXT,
        standing_rule_ref TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL CHECK (side IN ('buy','sell')),
        notional_usd_minor INTEGER NOT NULL CHECK (notional_usd_minor > 0),
        created_at_ms INTEGER NOT NULL,
        event_sha256 TEXT NOT NULL CHECK (length(event_sha256) = 43),
        scope_sha256 TEXT NOT NULL CHECK (length(scope_sha256) = 43),
        audit_record_hash TEXT NOT NULL CHECK (length(audit_record_hash) = 43)
      );
      CREATE INDEX IF NOT EXISTS causal_trigger_effects_root_idx
        ON causal_trigger_effects (budget_key, mandate_id, policy_epoch, root_trigger_id, created_at_ms);
      CREATE INDEX IF NOT EXISTS causal_trigger_effects_window_idx
        ON causal_trigger_effects (budget_key, created_at_ms);
      CREATE TABLE IF NOT EXISTS causal_trigger_breakers (
        budget_key TEXT NOT NULL,
        breaker_scope TEXT NOT NULL CHECK (breaker_scope IN ('trigger','window')),
        scope_ref TEXT NOT NULL,
        policy_epoch INTEGER NOT NULL CHECK (policy_epoch > 0),
        opened_at_ms INTEGER NOT NULL,
        mandate_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        scope_sha256 TEXT NOT NULL CHECK (length(scope_sha256) = 43),
        PRIMARY KEY (budget_key, breaker_scope, scope_ref, policy_epoch)
      );
      CREATE TABLE IF NOT EXISTS causal_trigger_breaker_audits (
        breaker_key TEXT NOT NULL CHECK (length(breaker_key) = 43),
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        event_json TEXT NOT NULL,
        event_hash TEXT NOT NULL CHECK (length(event_hash) = 43),
        previous_mac TEXT NOT NULL CHECK (length(previous_mac) = 43),
        event_mac TEXT NOT NULL CHECK (length(event_mac) = 43),
        recorded_at_ms INTEGER NOT NULL,
        PRIMARY KEY (breaker_key, sequence),
        UNIQUE (breaker_key, event_hash)
      );
      CREATE TRIGGER IF NOT EXISTS causal_trigger_events_immutable_update
        BEFORE UPDATE ON causal_trigger_events BEGIN SELECT RAISE(ABORT,'causal trigger events are append-only'); END;
      CREATE TRIGGER IF NOT EXISTS causal_trigger_events_immutable_delete
        BEFORE DELETE ON causal_trigger_events BEGIN SELECT RAISE(ABORT,'causal trigger events are append-only'); END;
      CREATE TRIGGER IF NOT EXISTS causal_trigger_effects_immutable_update
        BEFORE UPDATE ON causal_trigger_effects BEGIN SELECT RAISE(ABORT,'causal trigger effects are append-only'); END;
      CREATE TRIGGER IF NOT EXISTS causal_trigger_effects_immutable_delete
        BEFORE DELETE ON causal_trigger_effects BEGIN SELECT RAISE(ABORT,'causal trigger effects are append-only'); END;
      CREATE TRIGGER IF NOT EXISTS causal_trigger_breakers_immutable_update
        BEFORE UPDATE ON causal_trigger_breakers BEGIN SELECT RAISE(ABORT,'causal trigger breakers are latched'); END;
      CREATE TRIGGER IF NOT EXISTS causal_trigger_breakers_immutable_delete
        BEFORE DELETE ON causal_trigger_breakers BEGIN SELECT RAISE(ABORT,'causal trigger breakers are latched'); END;
      CREATE TRIGGER IF NOT EXISTS causal_trigger_breaker_audits_immutable_update
        BEFORE UPDATE ON causal_trigger_breaker_audits BEGIN SELECT RAISE(ABORT,'causal trigger breaker audits are append-only'); END;
      CREATE TRIGGER IF NOT EXISTS causal_trigger_breaker_audits_immutable_delete
        BEFORE DELETE ON causal_trigger_breaker_audits BEGIN SELECT RAISE(ABORT,'causal trigger breaker audits are append-only'); END;
      CREATE TABLE IF NOT EXISTS second_lock_holds (
        action_hash TEXT PRIMARY KEY,
        reason_code TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        approval_mandate_id TEXT,
        approved_at INTEGER,
        account_key TEXT,
        session_key TEXT,
        symbol TEXT,
        side TEXT,
        quantity INTEGER
      );
      CREATE TABLE IF NOT EXISTS kill_switch_state (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        active INTEGER NOT NULL CHECK (active IN (0, 1)),
        version INTEGER NOT NULL CHECK (version > 0),
        changed_at INTEGER NOT NULL,
        credential_id TEXT NOT NULL,
        evidence_hash TEXT NOT NULL CHECK (length(evidence_hash) = 43)
      );
      CREATE TABLE IF NOT EXISTS kill_switch_events (
        version INTEGER PRIMARY KEY CHECK (version > 0),
        active INTEGER NOT NULL CHECK (active IN (0, 1)),
        changed_at INTEGER NOT NULL,
        credential_id TEXT NOT NULL,
        evidence_hash TEXT NOT NULL CHECK (length(evidence_hash) = 43),
        previous_mac TEXT NOT NULL CHECK (length(previous_mac) = 43),
        event_mac TEXT NOT NULL CHECK (length(event_mac) = 43)
      );
    `);
    this.ensurePaperAuditIntegrityColumns();
    const mandateColumns = new Set((this.db.prepare('PRAGMA table_info(human_mandates)').all() as SqlRow[])
      .map((row) => row.name).filter((name): name is string => typeof name === 'string'));
    if (!mandateColumns.has('revoke_requested_at')) {
      this.db.exec('ALTER TABLE human_mandates ADD COLUMN revoke_requested_at INTEGER');
    }
    const dispatchColumns = new Set((this.db.prepare('PRAGMA table_info(futu_simulate_dispatches)').all() as SqlRow[])
      .map((row) => row.name).filter((name): name is string => typeof name === 'string'));
    if (!dispatchColumns.has('reconciliation_json')) {
      this.db.exec('ALTER TABLE futu_simulate_dispatches ADD COLUMN reconciliation_json TEXT');
    }
    const proposalConfirmationColumns = new Set((this.db.prepare('PRAGMA table_info(futu_proposal_confirmations)').all() as SqlRow[])
      .map((row) => row.name).filter((name): name is string => typeof name === 'string'));
    if (!proposalConfirmationColumns.has('dispatch_lease_until_ms')) {
      this.db.exec('ALTER TABLE futu_proposal_confirmations ADD COLUMN dispatch_lease_until_ms INTEGER');
    }
    this.ensureColumn('second_lock_holds', 'approval_mandate_id', 'TEXT');
    this.ensureColumn('second_lock_holds', 'approved_at', 'INTEGER');
    this.ensureColumn('second_lock_holds', 'account_key', 'TEXT');
    this.ensureColumn('second_lock_holds', 'session_key', 'TEXT');
    this.ensureColumn('second_lock_holds', 'symbol', 'TEXT');
    this.ensureColumn('second_lock_holds', 'side', 'TEXT');
    this.ensureColumn('second_lock_holds', 'quantity', 'INTEGER');
    this.ensureColumn('kill_switch_events', 'previous_mac', 'TEXT CHECK (length(previous_mac) = 43)');
    this.ensureColumn('kill_switch_events', 'event_mac', 'TEXT CHECK (length(event_mac) = 43)');
    this.db.exec('CREATE INDEX IF NOT EXISTS second_lock_holds_scope_idx ON second_lock_holds (account_key, session_key, symbol, side, approved_at);');
    this.ensureColumn('paper_orders', 'budget_key', "TEXT NOT NULL DEFAULT 'legacy'");
    this.ensureColumn('paper_orders', 'budget_notional_usd', 'REAL NOT NULL DEFAULT 0');
    this.ensureColumn('paper_orders', 'budget_notional_minor', 'INTEGER NOT NULL DEFAULT 0');
    this.ensureColumn('paper_orders', 'budget_currency', "TEXT NOT NULL DEFAULT 'USD'");
    this.ensureColumn('causal_trigger_events', 'source_provenance', "TEXT NOT NULL DEFAULT 'synthetic.unknown'");
    this.ensureArenaCancellationTerminalStates();
    this.db.prepare(`
      UPDATE paper_orders SET budget_key = 'synthetic-evaluation:legacy'
      WHERE substr(order_id, 1, 6) = 'paper-'
        AND (budget_key = 'legacy' OR budget_key LIKE 'synthetic-demo-account:%')
    `).run();
    this.db.prepare(`
      UPDATE paper_orders SET budget_key = 'synthetic-demo-account:' || strftime('%Y-%m-%d', created_at / 1000, 'unixepoch')
      WHERE substr(order_id, 1, 6) = 'paper:' AND budget_key = 'legacy'
    `).run();
    this.backfillUsdBudgetMinorUnits();
    this.db.exec('CREATE INDEX IF NOT EXISTS paper_orders_budget_idx ON paper_orders (budget_key, cancelled);');
    this.db.exec('CREATE INDEX IF NOT EXISTS venue_mandate_orders_mandate_idx ON venue_mandate_orders (mandate_id, state);');
    this.db.exec('CREATE INDEX IF NOT EXISTS mandate_cancellation_outbox_due_idx ON mandate_cancellation_outbox (state, next_attempt_at_ms, lease_until_ms);');
    if (path !== ':memory:') {
      try { chmodSync(path, 0o600); } catch { /* The database may not be materialized until the first write. */ }
    }
  }

  private ensureArenaCancellationTerminalStates(): void {
    const tableSql = (name: string): string | null => {
      const row = this.db.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name=?").get(name) as SqlRow | undefined;
      return typeof row?.sql === 'string' ? row.sql : null;
    };
    const stateCheckAllowsExpired = (sql: string | null): boolean => {
      const stateValues = sql?.match(/state\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(\s*state\s+IN\s*\(([^)]*)\)/i)?.[1];
      return typeof stateValues === 'string'
        && stateValues.split(',').some((value) => value.trim().replaceAll("'", '') === 'expired');
    };
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const venueSql = tableSql('venue_mandate_orders');
      if (venueSql && !stateCheckAllowsExpired(venueSql)) {
        this.db.exec('ALTER TABLE venue_mandate_orders RENAME TO venue_mandate_orders_pre_expired_state');
        this.db.exec(`CREATE TABLE venue_mandate_orders (
          venue TEXT NOT NULL, mandate_id TEXT NOT NULL, mandate_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL,
          order_id TEXT NOT NULL, order_hash TEXT NOT NULL, order_quantity_atoms INTEGER NOT NULL CHECK (order_quantity_atoms > 0),
          client_order_id TEXT NOT NULL, venue_order_id TEXT, order_json TEXT NOT NULL,
          state TEXT NOT NULL CHECK (state IN ('resident','unknown','cancelled','filled','expired','blocked')),
          created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
          PRIMARY KEY (venue, mandate_id, order_id), UNIQUE (venue, client_order_id)
        )`);
        this.db.exec('INSERT INTO venue_mandate_orders SELECT * FROM venue_mandate_orders_pre_expired_state');
        this.db.exec('DROP TABLE venue_mandate_orders_pre_expired_state');
      }
      const outboxSql = tableSql('mandate_cancellation_outbox');
      if (outboxSql && !stateCheckAllowsExpired(outboxSql)) {
        this.db.exec('ALTER TABLE mandate_cancellation_outbox RENAME TO mandate_cancellation_outbox_pre_expired_state');
        this.db.exec(`CREATE TABLE mandate_cancellation_outbox (
          outbox_id TEXT PRIMARY KEY, venue TEXT NOT NULL, mandate_id TEXT NOT NULL, mandate_hash TEXT NOT NULL,
          idempotency_key TEXT NOT NULL, order_id TEXT NOT NULL, order_hash TEXT NOT NULL,
          order_quantity_atoms INTEGER NOT NULL CHECK (order_quantity_atoms > 0), client_order_id TEXT NOT NULL,
          venue_order_id TEXT, order_json TEXT NOT NULL, reason TEXT NOT NULL CHECK (reason IN ('revoked','expired')),
          state TEXT NOT NULL CHECK (state IN ('pending','dispatching','retry','cancelled','filled','expired','blocked')),
          attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0), lease_until_ms INTEGER,
          next_attempt_at_ms INTEGER NOT NULL DEFAULT 0, last_observation_json TEXT,
          created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
          UNIQUE (venue, mandate_id, order_id)
        )`);
        this.db.exec('INSERT INTO mandate_cancellation_outbox SELECT * FROM mandate_cancellation_outbox_pre_expired_state');
        this.db.exec('DROP TABLE mandate_cancellation_outbox_pre_expired_state');
      }
      this.db.exec('COMMIT');
    } catch (error) {
      try { this.db.exec('ROLLBACK'); } catch { /* Keep the original migration failure. */ }
      throw error;
    }
  }

  getOwnerCredential(): StoredOwnerCredential | null {
    const row = this.db.prepare(
      'SELECT credential_id, public_key, counter, transports_json, origin, rp_id FROM owner_credentials WHERE revoked_at IS NULL ORDER BY created_at LIMIT 1',
    ).get() as SqlRow | undefined;
    if (!row || typeof row.credential_id !== 'string' || typeof row.public_key !== 'string'
      || typeof row.counter !== 'number' || typeof row.transports_json !== 'string'
      || typeof row.origin !== 'string' || typeof row.rp_id !== 'string') return null;
    let transports: unknown;
    try { transports = JSON.parse(row.transports_json) as unknown; } catch { return null; }
    if (!Array.isArray(transports) || !transports.every((item) => typeof item === 'string')) return null;
    return { credentialId: row.credential_id, publicKey: row.public_key, counter: row.counter, transports, origin: row.origin, rpId: row.rp_id };
  }

  getKillSwitchState(): StoredKillSwitchState {
    return this.withPaperAuditRead(() => {
      const anchor = this.loadPaperAuditAnchor();
      this.verifyAllPaperExecutionAudits(anchor);
      return this.readKillSwitchStateFromAnchor(anchor);
    });
  }

  private readKillSwitchStateFromAnchor(anchor: PaperAuditAnchor): StoredKillSwitchState {
    const events = this.readVerifiedKillSwitchEvents(anchor);
    const row = this.db.prepare(
      'SELECT active, version, changed_at, credential_id, evidence_hash FROM kill_switch_state WHERE singleton = 1',
    ).get() as SqlRow | undefined;
    const latestEvent = events[events.length - 1];
    if (!row) {
      if (events.length > 0) throw new Error('The durable kill-switch event journal has no matching current state.');
      return { active: false, version: 0, changedAt: null, credentialId: null, evidenceHash: null };
    }
    if ((row.active !== 0 && row.active !== 1) || typeof row.version !== 'number' || row.version < 1
      || typeof row.changed_at !== 'number' || typeof row.credential_id !== 'string'
      || typeof row.evidence_hash !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(row.evidence_hash)
      || !latestEvent || latestEvent.version !== row.version || latestEvent.active !== row.active
      || latestEvent.changed_at !== row.changed_at || latestEvent.credential_id !== row.credential_id
      || latestEvent.evidence_hash !== row.evidence_hash) {
      throw new Error('The durable kill-switch state does not match its latest audit event; refusing to trust it.');
    }
    return {
      active: row.active === 1,
      version: row.version,
      changedAt: row.changed_at,
      credentialId: row.credential_id,
      evidenceHash: row.evidence_hash,
    };
  }

  transitionKillSwitch(input: KillSwitchTransition): 'updated' | 'conflict' | 'unchanged' {
    const now = input.nowMs ?? Date.now();
    if (typeof input.active !== 'boolean' || !Number.isSafeInteger(input.expectedVersion) || input.expectedVersion < 0
      || !/^[A-Za-z0-9_-]{1,512}$/.test(input.credentialId)
      || !/^[A-Za-z0-9_-]{43}$/.test(input.evidenceHash) || !Number.isSafeInteger(now)) {
      throw new Error('A verified, bounded owner assertion and expected kill-switch version are required.');
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const anchor = this.loadPaperAuditAnchor();
      const previousAnchor = clonePaperAuditAnchor(anchor);
      const verifiedDataVersion = this.paperAuditDataVersion();
      this.ensurePaperAuditIntegrity(anchor, verifiedDataVersion);
      const current = this.readKillSwitchStateFromAnchor(anchor);
      if (current.version !== input.expectedVersion) {
        this.db.exec('COMMIT');
        return 'conflict';
      }
      if (current.active === input.active) {
        this.db.exec('COMMIT');
        return 'unchanged';
      }
      const version = current.version + 1;
      if (!Number.isSafeInteger(version)) throw new Error('The durable kill-switch version exceeded the safe integer range.');
      const event: KillSwitchAuditEventV1 = {
        version,
        active: input.active,
        changedAt: now,
        credentialId: input.credentialId,
        evidenceHash: input.evidenceHash,
      };
      const previousMac = anchor.killSwitch.headMac;
      const eventMac = killSwitchAuditEventMac(this.auditKey, previousMac, event);
      this.db.prepare(`
        INSERT INTO kill_switch_state (singleton, active, version, changed_at, credential_id, evidence_hash)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton) DO UPDATE SET active = excluded.active, version = excluded.version,
          changed_at = excluded.changed_at, credential_id = excluded.credential_id, evidence_hash = excluded.evidence_hash
      `).run(input.active ? 1 : 0, version, now, input.credentialId, input.evidenceHash);
      this.db.prepare(
        'INSERT INTO kill_switch_events (version, active, changed_at, credential_id, evidence_hash, previous_mac, event_mac) VALUES (?, ?, ?, ?, ?, ?, ?)',
      ).run(version, input.active ? 1 : 0, now, input.credentialId, input.evidenceHash, previousMac, eventMac);
      anchor.killSwitch = { version, headMac: eventMac };
      const checkpointTransition = this.preparePaperAuditCheckpointTransition(previousAnchor, anchor);
      this.db.exec('COMMIT');
      this.completePaperAuditCheckpointTransition(checkpointTransition, anchor);
      this.verifiedPaperAuditCheckpoint = { dataVersion: verifiedDataVersion, anchorJson: canonicalJson(anchor) };
      return 'updated';
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  registerOwnerCredential(credential: StoredOwnerCredential): boolean {
    if (!credential.credentialId || credential.credentialId.length > 512 || !credential.publicKey
      || !Number.isSafeInteger(credential.counter) || credential.counter < 0
      || !credential.origin || !credential.rpId || !Array.isArray(credential.transports)
      || credential.transports.length > 16 || credential.transports.some((item) => typeof item !== 'string' || item.length > 32)) {
      throw new Error('The owner passkey record is incomplete or out of bounds.');
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const existing = this.db.prepare('SELECT credential_id FROM owner_credentials WHERE revoked_at IS NULL LIMIT 1').get() as SqlRow | undefined;
      if (existing) {
        this.db.exec('COMMIT');
        return false;
      }
      this.db.prepare(
        'INSERT INTO owner_credentials (credential_id, public_key, counter, transports_json, origin, rp_id, created_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)',
      ).run(credential.credentialId, credential.publicKey, credential.counter, JSON.stringify(credential.transports), credential.origin, credential.rpId, Date.now());
      this.db.exec('COMMIT');
      return true;
    } catch (error) {
      this.rollback();
      if (isConstraintError(error)) return false;
      throw error;
    }
  }

  advanceOwnerCredentialCounter(credentialId: string, expectedCounter: number, nextCounter: number): boolean {
    if (!credentialId || !Number.isSafeInteger(expectedCounter) || !Number.isSafeInteger(nextCounter)
      || expectedCounter < 0 || nextCounter < 0 || (expectedCounter !== 0 && nextCounter <= expectedCounter)) return false;
    const result = this.db.prepare(
      'UPDATE owner_credentials SET counter = ? WHERE credential_id = ? AND counter = ? AND revoked_at IS NULL',
    ).run(nextCounter, credentialId, expectedCounter);
    return Number(result.changes) === 1;
  }

  saveHumanMandate(input: { mandateId: string; mandateHash: string; document: unknown; createdAt: number; expiresAt: number }): boolean {
    if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(input.mandateId)
      || !/^[A-Za-z0-9_-]{43}$/.test(input.mandateHash)
      || !Number.isSafeInteger(input.createdAt) || !Number.isSafeInteger(input.expiresAt) || input.expiresAt <= input.createdAt) {
      throw new Error('A valid signed human mandate record is required.');
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const existingActive = this.db.prepare(
        'SELECT mandate_id FROM human_mandates WHERE (revoked_at IS NULL AND expires_at > ?) OR revoke_requested_at IS NOT NULL LIMIT 1',
      ).get(input.createdAt) as SqlRow | undefined;
      if (existingActive) {
        this.db.exec('COMMIT');
        return false;
      }
      this.db.prepare(
        'INSERT INTO human_mandates (mandate_id, mandate_hash, document_json, created_at, expires_at, revoked_at, revoke_requested_at) VALUES (?, ?, ?, ?, ?, NULL, NULL)',
      ).run(input.mandateId, input.mandateHash, JSON.stringify(input.document), input.createdAt, input.expiresAt);
      this.db.exec('COMMIT');
      return true;
    } catch (error) {
      this.rollback();
      if (isConstraintError(error)) return false;
      throw error;
    }
  }

  saveOwnerAuthorizedPreference(input: {
    preferenceId: string;
    preferenceKey: string;
    preferenceHash: string;
    document: unknown;
    createdAt: number;
    expiresAt: number;
  }): boolean {
    if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(input.preferenceId)
      || !/^[a-z][a-z0-9_]{1,63}$/.test(input.preferenceKey)
      || !/^[A-Za-z0-9_-]{43}$/.test(input.preferenceHash)
      || !Number.isSafeInteger(input.createdAt) || !Number.isSafeInteger(input.expiresAt)
      || input.expiresAt <= input.createdAt) {
      throw new Error('A valid signed owner-authorized preference record is required.');
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const active = this.db.prepare(
        'SELECT preference_id FROM owner_authorized_preferences WHERE preference_key = ? AND revoked_at IS NULL AND expires_at > ? LIMIT 1',
      ).get(input.preferenceKey, input.createdAt) as SqlRow | undefined;
      if (active) {
        this.db.exec('COMMIT');
        return false;
      }
      this.db.prepare(
        'UPDATE owner_authorized_preferences SET revoked_at = ? WHERE preference_key = ? AND revoked_at IS NULL AND expires_at <= ?',
      ).run(input.createdAt, input.preferenceKey, input.createdAt);
      this.db.prepare(
        'INSERT INTO owner_authorized_preferences (preference_id, preference_key, preference_hash, document_json, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, NULL)',
      ).run(input.preferenceId, input.preferenceKey, input.preferenceHash, JSON.stringify(input.document), input.createdAt, input.expiresAt);
      this.db.exec('COMMIT');
      return true;
    } catch (error) {
      this.rollback();
      if (isConstraintError(error)) return false;
      throw error;
    }
  }

  getOwnerAuthorizedPreference(preferenceKey: string, nowMs = Date.now()): StoredOwnerPreference | null {
    if (!/^[a-z][a-z0-9_]{1,63}$/.test(preferenceKey) || !Number.isSafeInteger(nowMs)) return null;
    const row = this.db.prepare(
      'SELECT * FROM owner_authorized_preferences WHERE preference_key = ? AND revoked_at IS NULL AND expires_at > ? ORDER BY created_at DESC LIMIT 1',
    ).get(preferenceKey, nowMs) as SqlRow | undefined;
    return this.ownerPreferenceFromRow(row);
  }

  listOwnerAuthorizedPreferences(): StoredOwnerPreference[] {
    const rows = this.db.prepare('SELECT * FROM owner_authorized_preferences ORDER BY created_at DESC').all() as SqlRow[];
    return rows.flatMap((row) => {
      const item = this.ownerPreferenceFromRow(row);
      return item ? [item] : [];
    });
  }

  revokeOwnerAuthorizedPreference(preferenceKey: string, expectedHash: string, credentialId: string, evidenceHash: string, nowMs = Date.now()): boolean {
    if (!/^[a-z][a-z0-9_]{1,63}$/.test(preferenceKey) || !/^[A-Za-z0-9_-]{43}$/.test(expectedHash)
      || !credentialId || credentialId.length > 512 || !/^[A-Za-z0-9_-]{43}$/.test(evidenceHash)
      || !Number.isSafeInteger(nowMs)) return false;
    const result = this.db.prepare(
      'UPDATE owner_authorized_preferences SET revoked_at = ?, revoked_by_credential_id = ?, revocation_evidence_hash = ? WHERE preference_key = ? AND preference_hash = ? AND revoked_at IS NULL AND expires_at > ?',
    ).run(nowMs, credentialId, evidenceHash, preferenceKey, expectedHash, nowMs);
    return Number(result.changes) === 1;
  }

  private ownerPreferenceFromRow(row: SqlRow | undefined): StoredOwnerPreference | null {
    if (!row || typeof row.preference_id !== 'string' || typeof row.preference_key !== 'string'
      || typeof row.preference_hash !== 'string' || typeof row.document_json !== 'string'
      || typeof row.created_at !== 'number' || typeof row.expires_at !== 'number') return null;
    let document: unknown;
    try { document = JSON.parse(row.document_json) as unknown; } catch { return null; }
    return { preferenceId: row.preference_id, preferenceKey: row.preference_key, preferenceHash: row.preference_hash,
      document, createdAt: row.created_at, expiresAt: row.expires_at,
      revokedAt: typeof row.revoked_at === 'number' ? row.revoked_at : null,
      revokedByCredentialId: typeof row.revoked_by_credential_id === 'string' ? row.revoked_by_credential_id : null,
      revocationEvidenceHash: typeof row.revocation_evidence_hash === 'string' ? row.revocation_evidence_hash : null };
  }

  getHumanMandate(mandateId: string): StoredHumanMandate | null {
    if (!mandateId || mandateId.length > 128) return null;
    const row = this.db.prepare('SELECT * FROM human_mandates WHERE mandate_id = ?').get(mandateId) as SqlRow | undefined;
    if (!row || typeof row.mandate_hash !== 'string' || typeof row.document_json !== 'string'
      || typeof row.created_at !== 'number' || typeof row.expires_at !== 'number') return null;
    let document: unknown;
    try { document = JSON.parse(row.document_json) as unknown; } catch { return null; }
    return { mandateId, mandateHash: row.mandate_hash, document, createdAt: row.created_at, expiresAt: row.expires_at,
      revokedAt: typeof row.revoked_at === 'number' ? row.revoked_at : null,
      revokeRequestedAt: typeof row.revoke_requested_at === 'number' ? row.revoke_requested_at : null };
  }

  listHumanMandates(nowMs = Date.now()): StoredHumanMandate[] {
    const rows = this.db.prepare('SELECT * FROM human_mandates WHERE expires_at > ? OR revoke_requested_at IS NOT NULL ORDER BY created_at DESC')
      .all(nowMs) as SqlRow[];
    return rows.flatMap((row) => {
      if (typeof row.mandate_id !== 'string' || typeof row.mandate_hash !== 'string' || typeof row.document_json !== 'string'
        || typeof row.created_at !== 'number' || typeof row.expires_at !== 'number') return [];
      try {
        return [{ mandateId: row.mandate_id, mandateHash: row.mandate_hash, document: JSON.parse(row.document_json) as unknown,
          createdAt: row.created_at, expiresAt: row.expires_at, revokedAt: typeof row.revoked_at === 'number' ? row.revoked_at : null,
          revokeRequestedAt: typeof row.revoke_requested_at === 'number' ? row.revoke_requested_at : null }];
      } catch { return []; }
    });
  }

  getMandateCancellationSummary(mandateId: string): {
    trackedOrders: number; unresolvedOrders: number; blockedOrders: number;
    cancelledOrders: number; filledOrders: number; expiredOrders: number; openVenueOrders: number;
  } {
    if (!mandateId || mandateId.length > 128) {
      return { trackedOrders: 0, unresolvedOrders: 0, blockedOrders: 0,
        cancelledOrders: 0, filledOrders: 0, expiredOrders: 0, openVenueOrders: 0 };
    }
    const rows = this.db.prepare('SELECT state,COUNT(*) AS count FROM mandate_cancellation_outbox '
      + 'WHERE mandate_id=? GROUP BY state').all(mandateId) as SqlRow[];
    const counts = new Map<string, number>();
    for (const row of rows) {
      if (typeof row.state === 'string' && Number.isSafeInteger(row.count) && Number(row.count) >= 0) {
        counts.set(row.state, Number(row.count));
      }
    }
    const trackedOrders = [...counts.values()].reduce((sum, count) => sum + count, 0);
    const unresolvedOrders = ['pending', 'dispatching', 'retry', 'blocked']
      .reduce((sum, state) => sum + (counts.get(state) ?? 0), 0);
    const open = this.db.prepare("SELECT COUNT(*) AS count FROM venue_mandate_orders WHERE mandate_id=? "
      + "AND state IN ('resident','unknown','blocked')").get(mandateId) as SqlRow | undefined;
    return {
      trackedOrders,
      unresolvedOrders,
      blockedOrders: counts.get('blocked') ?? 0,
      cancelledOrders: counts.get('cancelled') ?? 0,
      filledOrders: counts.get('filled') ?? 0,
      expiredOrders: counts.get('expired') ?? 0,
      openVenueOrders: Number.isSafeInteger(open?.count) ? Number(open?.count) : 0,
    };
  }

  isHumanMandateActive(mandateId: string, mandateHash: string, nowMs = Date.now()): boolean {
    const row = this.db.prepare(
      'SELECT 1 AS active FROM human_mandates WHERE mandate_id = ? AND mandate_hash = ? AND revoked_at IS NULL AND revoke_requested_at IS NULL AND expires_at > ?',
    ).get(mandateId, mandateHash, nowMs) as SqlRow | undefined;
    return row?.active === 1;
  }

  revokeHumanMandate(mandateId: string, nowMs = Date.now()): 'revoked' | 'pending' | false {
    if (!mandateId || mandateId.length > 128 || !Number.isSafeInteger(nowMs)) return false;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const mandate = this.db.prepare(
        'SELECT revoked_at, revoke_requested_at FROM human_mandates WHERE mandate_id = ?',
      ).get(mandateId) as SqlRow | undefined;
      if (!mandate || mandate.revoked_at !== null || mandate.revoked_at === undefined) {
        this.db.exec('COMMIT');
        return false;
      }
      this.db.prepare(
        'UPDATE human_mandates SET revoke_requested_at = COALESCE(revoke_requested_at, ?) WHERE mandate_id = ? AND revoked_at IS NULL',
      ).run(nowMs, mandateId);
      this.enqueueFutuMandateCancellationRows(mandateId, nowMs);
      this.enqueueAllMandateCancellations(mandateId, 'revoked', nowMs);
      const finalized = this.finalizeDrainedHumanMandateRevocation(mandateId, nowMs);
      this.db.exec('COMMIT');
      return finalized ? 'revoked' : 'pending';
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  /** Persist the exact venue identity for an accepted or outcome-unknown dispatch.
   *  A late bind after revoke/expiry is immediately enqueued for cancellation. */
  registerVenueMandateOrder(input: {
    venue: string; mandateId: string; mandateHash: string; idempotencyKey: string;
    orderId: string; orderHash: string; orderQuantityAtoms: number; clientOrderId: string; venueOrderId: string | null;
    orderJson: string; dispatchState: 'accepted' | 'unknown';
  }, nowMs = Date.now()): boolean {
    const boundedId = (value: unknown, max: number) => typeof value === 'string'
      && value.length > 0 && value.length <= max && !/[\u0000-\u001f]/.test(value);
    if (!/^[a-z][a-z0-9-]{1,63}$/.test(input.venue) || !boundedId(input.mandateId, 128)
      || !/^[A-Za-z0-9_-]{43}$/.test(input.mandateHash)
      || !boundedId(input.idempotencyKey, 180) || !boundedId(input.orderId, 180)
      || !/^[A-Za-z0-9_-]{43}$/.test(input.orderHash) || !boundedId(input.clientOrderId, 180)
      || !Number.isSafeInteger(input.orderQuantityAtoms) || input.orderQuantityAtoms <= 0
      || (input.venueOrderId !== null && !isSafeVenueOrderId(input.venueOrderId))
      || (input.dispatchState === 'accepted' && !input.venueOrderId)
      || !boundedId(input.orderJson, 100_000) || !Number.isSafeInteger(nowMs)) return false;
    let parsedOrder: unknown;
    try { parsedOrder = JSON.parse(input.orderJson) as unknown; } catch { return false; }
    if (!parsedOrder || typeof parsedOrder !== 'object' || Array.isArray(parsedOrder)
      || sha256Base64Url(canonicalJson(parsedOrder)) !== input.orderHash) return false;

    this.db.exec('BEGIN IMMEDIATE');
    try {
      const mandate = this.db.prepare('SELECT mandate_hash,expires_at,revoked_at,revoke_requested_at FROM human_mandates WHERE mandate_id=?')
        .get(input.mandateId) as SqlRow | undefined;
      const order = this.db.prepare('SELECT order_id,order_hash,order_json,cancelled FROM paper_orders WHERE idempotency_key=?')
        .get(input.idempotencyKey) as SqlRow | undefined;
      const binding = this.db.prepare('SELECT mandate_id,order_id FROM human_mandate_orders WHERE idempotency_key=?')
        .get(input.idempotencyKey) as SqlRow | undefined;
      if (!mandate || mandate.mandate_hash !== input.mandateHash || order?.order_id !== input.orderId
        || order.order_hash !== input.orderHash || order.cancelled !== 0
        || canonicalJson(parseJson(order.order_json)) !== canonicalJson(parsedOrder)
        || binding?.mandate_id !== input.mandateId || binding.order_id !== input.orderId) {
        this.db.exec('COMMIT');
        return false;
      }
      if (input.venue === 'futu-simulate') {
        const authorization = this.db.prepare('SELECT mandate_id,mandate_hash,order_id,order_hash,second_lock_decision,version '
          + 'FROM futu_m1_dispatch_authorizations WHERE idempotency_key=?').get(input.idempotencyKey) as SqlRow | undefined;
        if (!authorization || authorization.mandate_id !== input.mandateId || authorization.mandate_hash !== input.mandateHash
          || authorization.order_id !== input.orderId || authorization.order_hash !== input.orderHash
          || authorization.second_lock_decision !== 'allow' || authorization.version !== 'MANDATE-M1-v1.0.0') {
          this.db.exec('COMMIT');
          return false;
        }
      }
      const existing = this.db.prepare('SELECT * FROM venue_mandate_orders WHERE venue=? AND mandate_id=? AND order_id=?')
        .get(input.venue, input.mandateId, input.orderId) as SqlRow | undefined;
      if (existing) {
        const same = existing.mandate_hash === input.mandateHash && existing.idempotency_key === input.idempotencyKey
          && existing.order_hash === input.orderHash && existing.order_quantity_atoms === input.orderQuantityAtoms
          && existing.client_order_id === input.clientOrderId
          && existing.order_json === order.order_json
          && (existing.venue_order_id === input.venueOrderId || existing.venue_order_id === null || input.venueOrderId === null);
        if (!same) {
          this.db.prepare("UPDATE venue_mandate_orders SET state='blocked',updated_at_ms=? WHERE venue=? AND mandate_id=? AND order_id=?")
            .run(nowMs, input.venue, input.mandateId, input.orderId);
          this.db.prepare("UPDATE mandate_cancellation_outbox SET state='blocked',lease_until_ms=NULL,updated_at_ms=? "
            + "WHERE venue=? AND mandate_id=? AND order_id=? AND state IN ('pending','retry','dispatching')")
            .run(nowMs, input.venue, input.mandateId, input.orderId);
          this.db.exec('COMMIT');
          return false;
        }
        if (existing.venue_order_id === null && input.venueOrderId !== null) {
          this.db.prepare('UPDATE venue_mandate_orders SET venue_order_id=?,state=?,updated_at_ms=? WHERE venue=? AND mandate_id=? AND order_id=?')
            .run(input.venueOrderId, input.dispatchState === 'accepted' ? 'resident' : String(existing.state), nowMs,
              input.venue, input.mandateId, input.orderId);
        } else if (input.dispatchState === 'accepted' && ['unknown'].includes(String(existing.state))) {
          this.db.prepare("UPDATE venue_mandate_orders SET state='resident',updated_at_ms=? WHERE venue=? AND mandate_id=? AND order_id=?")
            .run(nowMs, input.venue, input.mandateId, input.orderId);
        }
      } else {
        this.db.prepare('INSERT INTO venue_mandate_orders '
          + '(venue,mandate_id,mandate_hash,idempotency_key,order_id,order_hash,order_quantity_atoms,client_order_id,venue_order_id,order_json,state,created_at_ms,updated_at_ms) '
          + 'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)').run(input.venue, input.mandateId, input.mandateHash,
          input.idempotencyKey, input.orderId, input.orderHash, input.orderQuantityAtoms, input.clientOrderId, input.venueOrderId,
          String(order.order_json), input.dispatchState === 'accepted' ? 'resident' : 'unknown', nowMs, nowMs);
      }
      if (mandate.revoked_at !== null || mandate.revoke_requested_at !== null || Number(mandate.expires_at) <= nowMs) {
        const reason = Number(mandate.expires_at) <= nowMs ? 'expired' : 'revoked';
        this.db.prepare('UPDATE human_mandates SET revoke_requested_at=COALESCE(revoke_requested_at,?) WHERE mandate_id=?')
          .run(nowMs, input.mandateId);
        this.enqueueVenueMandateOrderCancellation(input.venue, input.mandateId, input.orderId, reason, nowMs);
      }
      this.db.exec('COMMIT');
      return true;
    } catch (error) {
      this.rollback();
      if (isConstraintError(error)) return false;
      throw error;
    }
  }

  getFutuProposalConfirmation(tokenHash: string): FutuProposalConfirmationRecordV1 | null {
    if (!/^[a-f0-9]{64}$/.test(tokenHash)) return null;
    const row = this.db.prepare('SELECT phase,payload_json,lease_owner,lease_until_ms,dispatch_lease_until_ms,expires_at_ms '
      + 'FROM futu_proposal_confirmations WHERE token_hash=?').get(tokenHash) as SqlRow | undefined;
    if (!row || typeof row.payload_json !== 'string' || !['prepared', 'processing', 'dispatching', 'complete'].includes(String(row.phase))
      || (row.lease_owner !== null && typeof row.lease_owner !== 'string')
      || (row.lease_until_ms !== null && !Number.isSafeInteger(row.lease_until_ms))
      || (row.dispatch_lease_until_ms !== null && !Number.isSafeInteger(row.dispatch_lease_until_ms))
      || !Number.isSafeInteger(row.expires_at_ms)) return null;
    let payload: unknown;
    try { payload = JSON.parse(row.payload_json) as unknown; } catch { return null; }
    if (!isRecord(payload)) return null;
    return { payload, phase: row.phase as FutuProposalConfirmationPhaseV1,
      leaseOwner: row.lease_owner as string | null, leaseUntilMs: row.lease_until_ms as number | null,
      dispatchLeaseUntilMs: row.dispatch_lease_until_ms as number | null,
      expiresAtMs: Number(row.expires_at_ms) };
  }

  createFutuProposalConfirmation(tokenHash: string, payload: Record<string, unknown>, expiresAtMs: number,
    nowMs = Date.now()): boolean {
    const payloadJson = JSON.stringify({ ...payload, phase: 'prepared' });
    if (!/^[a-f0-9]{64}$/.test(tokenHash) || !Number.isSafeInteger(expiresAtMs) || expiresAtMs <= nowMs
      || !Number.isSafeInteger(nowMs) || Buffer.byteLength(payloadJson, 'utf8') > 128 * 1024) return false;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      this.pruneFutuProposalConfirmations(nowMs);
      const active = this.db.prepare("SELECT COUNT(*) AS count FROM futu_proposal_confirmations "
        + "WHERE phase IN ('prepared','processing','dispatching') "
        + "AND (phase='dispatching' OR expires_at_ms>? OR (phase='processing' AND lease_until_ms>?))")
        .get(nowMs, nowMs) as SqlRow;
      if (!Number.isSafeInteger(active.count) || Number(active.count) >= 200) {
        this.db.exec('COMMIT');
        return false;
      }
      this.db.prepare('INSERT INTO futu_proposal_confirmations '
        + '(token_hash,phase,payload_json,lease_owner,lease_until_ms,expires_at_ms,created_at_ms,updated_at_ms) '
        + "VALUES (?,'prepared',?,NULL,NULL,?,?,?)")
        .run(tokenHash, payloadJson, expiresAtMs, nowMs, nowMs);
      this.db.exec('COMMIT');
      return true;
    } catch (error) {
      this.rollback();
      if (isConstraintError(error)) return false;
      throw error;
    }
  }

  claimFutuProposalConfirmation(tokenHash: string, owner: string, expected: FutuProposalConfirmationBindingV1,
    nowMs = Date.now(), leaseMs = 30_000): FutuProposalConfirmationClaimV1 {
    if (!/^[a-f0-9]{64}$/.test(tokenHash) || !/^[A-Za-z0-9_-]{16,128}$/.test(owner)
      || !Number.isSafeInteger(nowMs) || !Number.isSafeInteger(leaseMs) || leaseMs < 1_000 || leaseMs > 300_000) {
      return { kind: 'missing' };
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const record = this.getFutuProposalConfirmation(tokenHash);
      if (!record) {
        this.db.exec('COMMIT');
        return { kind: 'missing' };
      }
      const bindingMatches = record.payload.runId === expected.runId && record.payload.mandateId === expected.mandateId
        && record.payload.originalRequest === expected.originalRequest && record.payload.model === expected.model
        && record.payload.attackCardId === expected.attackCardId && record.payload.condition === expected.condition;
      if (!bindingMatches) {
        this.db.exec('COMMIT');
        return { kind: 'binding_mismatch' };
      }
      if (record.phase === 'complete') {
        const cachedResponse = isRecord(record.payload.cachedResponse) ? record.payload.cachedResponse : null;
        const cachedFutu = cachedResponse && isRecord(cachedResponse.futu) ? cachedResponse.futu : null;
        if (cachedResponse?.dispatch_attempted === true
          && (cachedResponse.state === 'futu_unknown' || cachedFutu?.state === 'unknown')) {
          const dispatchLeaseUntilMs = nowMs + leaseMs;
          if (!Number.isSafeInteger(dispatchLeaseUntilMs)) {
            this.db.exec('COMMIT');
            return { kind: 'missing' };
          }
          const payload = { ...record.payload, phase: 'dispatching' };
          const update = this.db.prepare("UPDATE futu_proposal_confirmations SET phase='dispatching',payload_json=?,lease_owner=?,lease_until_ms=NULL,dispatch_lease_until_ms=?,updated_at_ms=? "
            + "WHERE token_hash=? AND phase='complete'");
          const result = update.run(JSON.stringify(payload), owner, dispatchLeaseUntilMs, nowMs, tokenHash);
          if (Number(result.changes) !== 1) {
            this.db.exec('ROLLBACK');
            return { kind: 'dispatching', record };
          }
          this.db.exec('COMMIT');
          return { kind: 'dispatching-claimed', record: { ...record, payload, phase: 'dispatching',
            leaseOwner: owner, leaseUntilMs: null, dispatchLeaseUntilMs } };
        }
        this.db.exec('COMMIT');
        return { kind: 'complete', record };
      }
      if (record.phase === 'dispatching') {
        if (record.dispatchLeaseUntilMs !== null && record.dispatchLeaseUntilMs > nowMs) {
          this.db.exec('COMMIT');
          return { kind: 'dispatching', record };
        }
        const dispatchLeaseUntilMs = nowMs + leaseMs;
        if (!Number.isSafeInteger(dispatchLeaseUntilMs)) {
          this.db.exec('COMMIT');
          return { kind: 'missing' };
        }
        const update = this.db.prepare("UPDATE futu_proposal_confirmations SET lease_owner=?,dispatch_lease_until_ms=?,updated_at_ms=? "
          + "WHERE token_hash=? AND phase='dispatching' AND (dispatch_lease_until_ms IS NULL OR dispatch_lease_until_ms<=?)");
        const result = update.run(owner, dispatchLeaseUntilMs, nowMs, tokenHash, nowMs);
        if (Number(result.changes) !== 1) {
          this.db.exec('ROLLBACK');
          return { kind: 'dispatching', record };
        }
        this.db.exec('COMMIT');
        return { kind: 'dispatching-claimed', record: { ...record, leaseOwner: owner, dispatchLeaseUntilMs } };
      }
      if (record.expiresAtMs <= nowMs) {
        this.db.exec('COMMIT');
        return { kind: 'expired' };
      }
      if (record.phase === 'processing' && record.leaseUntilMs !== null && record.leaseUntilMs > nowMs) {
        this.db.exec('COMMIT');
        return { kind: 'processing', record };
      }
      const leaseUntilMs = nowMs + leaseMs;
      if (!Number.isSafeInteger(leaseUntilMs)) {
        this.db.exec('COMMIT');
        return { kind: 'missing' };
      }
      const payload = { ...record.payload, phase: 'processing' };
      const update = this.db.prepare("UPDATE futu_proposal_confirmations SET phase='processing',payload_json=?,"
        + 'lease_owner=?,lease_until_ms=?,updated_at_ms=? WHERE token_hash=? AND phase=?');
      const result = update.run(JSON.stringify(payload), owner, leaseUntilMs, nowMs, tokenHash, record.phase);
      if (Number(result.changes) !== 1) {
        this.db.exec('ROLLBACK');
        return { kind: 'processing', record };
      }
      this.db.exec('COMMIT');
      return { kind: 'claimed', record: { payload, phase: 'processing', leaseOwner: owner,
        leaseUntilMs, dispatchLeaseUntilMs: null, expiresAtMs: record.expiresAtMs } };
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  transitionFutuProposalConfirmation(tokenHash: string, owner: string, fromPhase: 'processing' | 'dispatching',
    toPhase: 'prepared' | 'dispatching' | 'complete', payload: Record<string, unknown>, nowMs = Date.now()): boolean {
    if (!/^[a-f0-9]{64}$/.test(tokenHash) || !/^[A-Za-z0-9_-]{16,128}$/.test(owner)
      || !Number.isSafeInteger(nowMs) || (fromPhase === 'dispatching' && toPhase !== 'complete')
      || (fromPhase === 'processing' && !['prepared', 'dispatching', 'complete'].includes(toPhase))) return false;
    const payloadJson = JSON.stringify({ ...payload, phase: toPhase });
    if (Buffer.byteLength(payloadJson, 'utf8') > 256 * 1024) return false;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const record = this.getFutuProposalConfirmation(tokenHash);
      if (!record || record.phase !== fromPhase || record.leaseOwner !== owner
        || (fromPhase === 'processing' && (record.leaseUntilMs === null || record.leaseUntilMs <= nowMs))
        || (fromPhase === 'dispatching' && (record.dispatchLeaseUntilMs === null || record.dispatchLeaseUntilMs <= nowMs))) {
        this.db.exec('ROLLBACK');
        return false;
      }
      const keepOwner = toPhase === 'dispatching' ? owner : null;
      const dispatchLeaseUntilMs = toPhase === 'dispatching' ? nowMs + 90_000 : null;
      if (dispatchLeaseUntilMs !== null && !Number.isSafeInteger(dispatchLeaseUntilMs)) {
        this.db.exec('ROLLBACK');
        return false;
      }
      const update = this.db.prepare('UPDATE futu_proposal_confirmations SET phase=?,payload_json=?,lease_owner=?,lease_until_ms=NULL,dispatch_lease_until_ms=?,updated_at_ms=? '
        + 'WHERE token_hash=? AND phase=? AND lease_owner=? AND '
        + '( (phase=\'processing\' AND lease_until_ms>?) OR (phase=\'dispatching\' AND dispatch_lease_until_ms>?) )');
      const result = update.run(toPhase, payloadJson, keepOwner, dispatchLeaseUntilMs, nowMs,
        tokenHash, fromPhase, owner, nowMs, nowMs);
      if (Number(result.changes) !== 1) {
        this.db.exec('ROLLBACK');
        return false;
      }
      this.db.exec('COMMIT');
      return true;
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  releaseFutuProposalDispatchLease(tokenHash: string, owner: string, nowMs = Date.now(), retryDelayMs = 5_000): boolean {
    const nextAttemptAtMs = nowMs + retryDelayMs;
    if (!/^[a-f0-9]{64}$/.test(tokenHash) || !/^[A-Za-z0-9_-]{16,128}$/.test(owner)
      || !Number.isSafeInteger(nowMs) || !Number.isSafeInteger(retryDelayMs)
      || retryDelayMs < 1_000 || retryDelayMs > 300_000 || !Number.isSafeInteger(nextAttemptAtMs)) return false;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const record = this.getFutuProposalConfirmation(tokenHash);
      if (!record || record.phase !== 'dispatching' || record.leaseOwner !== owner
        || record.dispatchLeaseUntilMs === null || record.dispatchLeaseUntilMs <= nowMs) {
        this.db.exec('ROLLBACK');
        return false;
      }
      const update = this.db.prepare("UPDATE futu_proposal_confirmations SET dispatch_lease_until_ms=?,updated_at_ms=? "
        + "WHERE token_hash=? AND phase='dispatching' AND lease_owner=? AND dispatch_lease_until_ms>?");
      const result = update.run(nextAttemptAtMs, nowMs, tokenHash, owner, nowMs);
      if (Number(result.changes) !== 1) {
        this.db.exec('ROLLBACK');
        return false;
      }
      this.db.exec('COMMIT');
      return true;
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  deleteFutuProposalConfirmation(tokenHash: string, nowMs = Date.now()): boolean {
    if (!/^[a-f0-9]{64}$/.test(tokenHash) || !Number.isSafeInteger(nowMs)) return false;
    const result = this.db.prepare("DELETE FROM futu_proposal_confirmations WHERE token_hash=? AND phase IN ('prepared','complete') "
      + 'AND expires_at_ms<=?').run(tokenHash, nowMs);
    return Number(result.changes) === 1;
  }

  /** Import the Futu SIMULATE adapter's durable result into the venue-neutral revocation index. */
  recordFutuMandateDispatchForRevocation(idempotencyKey: string, nowMs = Date.now()): boolean {
    if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$/.test(idempotencyKey) || !Number.isSafeInteger(nowMs)) return false;
    const row = this.db.prepare('SELECT a.mandate_id,a.mandate_hash,a.idempotency_key,a.order_id,a.order_hash,'
      + 'd.remark,d.broker_order_id,d.state AS dispatch_state,p.order_json '
      + 'FROM futu_m1_dispatch_authorizations a JOIN futu_simulate_dispatches d ON d.idempotency_key=a.idempotency_key '
      + 'JOIN paper_orders p ON p.idempotency_key=a.idempotency_key AND p.order_id=a.order_id '
      + 'WHERE a.idempotency_key=?').get(idempotencyKey) as SqlRow | undefined;
    if (!row || typeof row.mandate_id !== 'string' || typeof row.mandate_hash !== 'string'
      || typeof row.order_id !== 'string' || typeof row.order_hash !== 'string'
      || typeof row.remark !== 'string' || typeof row.order_json !== 'string'
      || (row.broker_order_id !== null && !isSafeVenueOrderId(row.broker_order_id))) return false;
    const dispatchState = row.dispatch_state === 'accepted' ? 'accepted'
      : ['dispatching', 'unknown', 'conflict'].includes(String(row.dispatch_state)) ? 'unknown' : null;
    if (!dispatchState) return false;
    let orderValue: unknown;
    try { orderValue = JSON.parse(row.order_json) as unknown; } catch { return false; }
    if (!isRecord(orderValue) || !Number.isSafeInteger(orderValue.quantity) || Number(orderValue.quantity) <= 0) return false;
    return this.registerVenueMandateOrder({ venue: 'futu-simulate', mandateId: row.mandate_id,
      mandateHash: row.mandate_hash, idempotencyKey, orderId: row.order_id, orderHash: row.order_hash,
      orderQuantityAtoms: Number(orderValue.quantity),
      clientOrderId: row.remark, venueOrderId: typeof row.broker_order_id === 'string' ? row.broker_order_id : null,
      orderJson: row.order_json, dispatchState }, nowMs);
  }

  /** Expiry is a durable revoke event; this call never contacts a venue. */
  enqueueExpiredMandateCancellations(nowMs = Date.now()): { mandates: number; orders: number } {
    if (!Number.isSafeInteger(nowMs)) throw new Error('A safe expiry-sweep clock is required.');
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const rows = this.db.prepare('SELECT mandate_id,mandate_hash,expires_at FROM human_mandates '
        + 'WHERE expires_at<=? AND revoked_at IS NULL ORDER BY expires_at,mandate_id').all(nowMs) as SqlRow[];
      let orders = 0;
      for (const row of rows) {
        if (typeof row.mandate_id !== 'string' || typeof row.mandate_hash !== 'string'
          || !Number.isSafeInteger(row.expires_at)) continue;
        this.db.prepare('UPDATE human_mandates SET revoke_requested_at=COALESCE(revoke_requested_at,?) '
          + 'WHERE mandate_id=? AND revoked_at IS NULL').run(Number(row.expires_at), row.mandate_id);
        this.enqueueFutuMandateCancellationRows(row.mandate_id, nowMs);
        orders += this.enqueueAllMandateCancellations(row.mandate_id, 'expired', nowMs);
        this.finalizeDrainedHumanMandateRevocation(row.mandate_id, nowMs);
      }
      const c1Rows = this.db.prepare("SELECT authorization_id FROM arena_c1_dispatch_authorizations "
        + "WHERE state IN ('accepted','unknown') AND expires_at_ms<=? ORDER BY expires_at_ms,authorization_id")
        .all(nowMs) as SqlRow[];
      for (const row of c1Rows) {
        if (typeof row.authorization_id !== 'string') continue;
        if (this.recordArenaC1DispatchForRevocationInTransaction(row.authorization_id, nowMs)) {
          const indexed = this.db.prepare('SELECT order_id FROM arena_c1_dispatch_authorizations WHERE authorization_id=?')
            .get(row.authorization_id) as SqlRow | undefined;
          if (typeof indexed?.order_id === 'string'
            && this.enqueueVenueMandateOrderCancellation('binance-spot-testnet', 'MANDATE-C1', indexed.order_id, 'expired', nowMs)) {
            orders += 1;
          }
        }
      }
      this.db.exec('COMMIT');
      return { mandates: rows.length, orders };
    } catch (error) { this.rollback(); throw error; }
  }

  /** Claim one durable cancellation intent. Retries reuse outboxId as the venue idempotency key. */
  claimMandateCancellation(nowMs = Date.now(), leaseMs = 30_000, supportedVenues?: readonly string[]): MandateCancellationOutboxItemV1 | null {
    if (!Number.isSafeInteger(nowMs) || !Number.isSafeInteger(leaseMs) || leaseMs < 1_000 || leaseMs > 300_000) {
      throw new Error('A bounded cancellation-claim lease is required.');
    }
    const venueFilter = supportedVenues === undefined ? undefined : [...new Set(supportedVenues)];
    if (venueFilter && (venueFilter.length === 0 || venueFilter.length > 16
      || venueFilter.some((venue) => !/^[a-z][a-z0-9-]{1,63}$/.test(venue)))) {
      throw new Error('A bounded cancellation venue allowlist is required.');
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      // A poisoned due row must not hide every later cancellation behind it.
      // Block invalid candidates durably, then keep scanning within this same
      // transaction so one bad binding cannot create head-of-line starvation.
      for (let scanned = 0; scanned < 128; scanned += 1) {
        const venueClause = venueFilter ? `AND venue IN (${venueFilter.map(() => '?').join(',')}) ` : '';
        const row = this.db.prepare("SELECT rowid AS row_id, * FROM mandate_cancellation_outbox WHERE "
          + "((state IN ('pending','retry') AND next_attempt_at_ms<=?) OR (state='dispatching' AND lease_until_ms<=?)) "
          + venueClause + 'ORDER BY created_at_ms,outbox_id LIMIT 1')
          .get(nowMs, nowMs, ...(venueFilter ?? [])) as SqlRow | undefined;
        if (!row) { this.db.exec('COMMIT'); return null; }
        const item = this.cancellationOutboxFromRow(row);
        if (!item) {
          if (typeof row.row_id !== 'number' || !Number.isSafeInteger(row.row_id)) { this.db.exec('COMMIT'); return null; }
          const blockedCount = this.db.prepare("UPDATE mandate_cancellation_outbox SET state='blocked',lease_until_ms=NULL,updated_at_ms=? "
            + "WHERE rowid=? AND state IN ('pending','retry','dispatching')")
            .run(nowMs, row.row_id).changes;
          if (blockedCount !== 1) { this.db.exec('COMMIT'); return null; }
          continue;
        }
        const binding = this.db.prepare('SELECT * FROM venue_mandate_orders WHERE venue=? AND mandate_id=? AND order_id=?')
          .get(item.venue, item.mandateId, item.orderId) as SqlRow | undefined;
        const mandate = this.db.prepare('SELECT mandate_hash,expires_at,revoked_at,revoke_requested_at FROM human_mandates WHERE mandate_id=?')
          .get(item.mandateId) as SqlRow | undefined;
        const c1Authorization = item.venue === 'binance-spot-testnet' && item.mandateId === 'MANDATE-C1'
          ? this.db.prepare('SELECT authorization_id,idempotency_key,order_id,order_hash,expires_at_ms,authorization_json,state '
            + 'FROM arena_c1_dispatch_authorizations WHERE idempotency_key=?').get(item.idempotencyKey) as SqlRow | undefined
          : undefined;
        const c1Control = item.venue === 'binance-spot-testnet' && item.mandateId === 'MANDATE-C1'
          ? this.db.prepare('SELECT mandate_id,policy_digest,state FROM arena_c1_mandate_control WHERE singleton=1')
            .get() as SqlRow | undefined
          : undefined;
        let orderMatchesDigest = false;
        try {
          const order = JSON.parse(item.orderJson) as unknown;
          orderMatchesDigest = Boolean(order && typeof order === 'object' && !Array.isArray(order)
            && sha256Base64Url(canonicalJson(order)) === item.orderHash);
        } catch { orderMatchesDigest = false; }
        const venueOrderMatches = binding?.venue === item.venue && binding.mandate_id === item.mandateId
          && binding.mandate_hash === item.mandateHash && binding.idempotency_key === item.idempotencyKey
          && binding.order_hash === item.orderHash && binding.client_order_id === item.clientOrderId
          && binding.order_json === item.orderJson
          && Number(binding.order_quantity_atoms) === item.orderQuantityAtoms
          && (binding.venue_order_id === item.venueOrderId
            || (item.venueOrderId === null && typeof binding.venue_order_id === 'string'))
          && ['resident', 'unknown'].includes(String(binding.state));
        const mandateStateIsWellFormed = Boolean(mandate && Number.isSafeInteger(mandate.expires_at)
          && (mandate.revoked_at === null || Number.isSafeInteger(mandate.revoked_at))
          && (mandate.revoke_requested_at === null || Number.isSafeInteger(mandate.revoke_requested_at)));
        let c1AuthorityIsClosing = false;
        if (c1Authorization && typeof c1Authorization.authorization_json === 'string') {
          try {
            const authorization = JSON.parse(c1Authorization.authorization_json) as unknown;
            const actionExpired = Number.isSafeInteger(c1Authorization.expires_at_ms)
              && Number(c1Authorization.expires_at_ms) <= nowMs;
            const mandateRevoked = c1Control?.mandate_id === 'MANDATE-C1'
              && typeof c1Control.policy_digest === 'string'
              && /^[a-f0-9]{64}$/.test(c1Control.policy_digest)
              && ['revoking', 'revoked'].includes(String(c1Control.state));
            const reasonAllowsCloseout = item.reason === 'expired' ? actionExpired : mandateRevoked;
            c1AuthorityIsClosing = isRecord(authorization)
              && c1Authorization.authorization_json === item.orderJson
              && c1Authorization.idempotency_key === item.idempotencyKey
              && c1Authorization.order_id === item.orderId
              && c1Authorization.order_hash === authorization.order_hash
              && ['accepted', 'unknown'].includes(String(c1Authorization.state))
              && reasonAllowsCloseout
              && authorization.venue === 'binance-spot-testnet' && authorization.mandate_id === 'MANDATE-C1'
              && authorization.order_id === item.orderId && authorization.client_order_id === item.clientOrderId
              && authorization.order_hash === c1Authorization.order_hash
              && authorization.quantity_minor === item.orderQuantityAtoms
              && typeof authorization.mandate_version === 'string'
              && item.mandateHash === sha256Base64Url(canonicalJson({ domain: 'orderguard-arena-mandate-v1',
                mandateId: authorization.mandate_id, version: authorization.mandate_version }));
          } catch { c1AuthorityIsClosing = false; }
        }
        const humanMandateIsClosing = mandateStateIsWellFormed && mandate?.mandate_hash === item.mandateHash
          && (mandate.revoked_at !== null || mandate.revoke_requested_at !== null || Number(mandate.expires_at) <= nowMs);
        const mandateIsClosing = humanMandateIsClosing || c1AuthorityIsClosing;
        if (!orderMatchesDigest || !venueOrderMatches || !mandateIsClosing) {
          const blockedCount = this.db.prepare("UPDATE mandate_cancellation_outbox SET state='blocked',lease_until_ms=NULL,updated_at_ms=? WHERE outbox_id=?")
            .run(nowMs, item.outboxId).changes;
          if (blockedCount !== 1) { this.db.exec('COMMIT'); return null; }
          this.db.prepare("UPDATE venue_mandate_orders SET state='blocked',updated_at_ms=? WHERE venue=? AND mandate_id=? AND order_id=?")
            .run(nowMs, item.venue, item.mandateId, item.orderId);
          continue;
        }
        const claimedCount = this.db.prepare("UPDATE mandate_cancellation_outbox SET state='dispatching',attempt_count=attempt_count+1,lease_until_ms=?,updated_at_ms=? "
          + "WHERE outbox_id=? AND ((state IN ('pending','retry') AND next_attempt_at_ms<=?) OR (state='dispatching' AND lease_until_ms<=?))")
          .run(nowMs + leaseMs, nowMs, item.outboxId, nowMs, nowMs).changes;
        if (claimedCount !== 1) {
          this.db.exec('COMMIT');
          return null;
        }
        const claimed = this.db.prepare('SELECT * FROM mandate_cancellation_outbox WHERE outbox_id=?').get(item.outboxId) as SqlRow | undefined;
        const claimedItem = this.cancellationOutboxFromRow(claimed);
        if (!claimedItem || claimedItem.state !== 'dispatching' || claimedItem.attemptCount !== item.attemptCount + 1) {
          this.db.exec('COMMIT');
          return null;
        }
        this.db.exec('COMMIT');
        return claimedItem;
      }
      this.db.exec('COMMIT');
      return null;
    } catch (error) { this.rollback(); throw error; }
  }

  /** A cancellation is terminal only with exact order+trade-history evidence. */
  finishMandateCancellation(outboxId: string, expectedAttempt: number,
    observation: MandateCancellationObservationV1, nowMs = Date.now()): 'cancelled' | 'filled' | 'expired' | 'retry' | 'blocked' | false {
    if (!/^cancel-[A-Za-z0-9_-]{43}$/.test(outboxId) || !Number.isSafeInteger(expectedAttempt)
      || expectedAttempt <= 0 || !Number.isSafeInteger(nowMs) || !isRecord(observation)
      || !['OPEN','PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED','UNKNOWN','MISMATCH'].includes(String(observation.orderStatus))
      || !['venue','mandateId','mandateHash','idempotencyKey','orderId','orderHash','clientOrderId','venueOrderId']
        .every((key) => typeof observation[key as keyof MandateCancellationObservationV1] === 'string')) return false;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const row = this.db.prepare('SELECT * FROM mandate_cancellation_outbox WHERE outbox_id=?').get(outboxId) as SqlRow | undefined;
      const item = this.cancellationOutboxFromRow(row);
      if (!item || item.state !== 'dispatching' || item.attemptCount !== expectedAttempt) { this.db.exec('COMMIT'); return false; }
      const identityMatches = observation.venue === item.venue && observation.mandateId === item.mandateId
        && observation.mandateHash === item.mandateHash && observation.idempotencyKey === item.idempotencyKey
        && observation.orderId === item.orderId && observation.orderHash === item.orderHash
        && observation.orderQuantityAtoms === item.orderQuantityAtoms
        && observation.clientOrderId === item.clientOrderId
        && (observation.venueOrderId.length === 0 || isSafeVenueOrderId(observation.venueOrderId))
        && (item.venueOrderId === null || observation.venueOrderId === item.venueOrderId)
        && /^[A-Za-z0-9_-]{43}$/.test(observation.orderHash)
        && Number.isSafeInteger(observation.matchedTradeAtoms) && observation.matchedTradeAtoms >= 0
        && Number.isSafeInteger(observation.orderQuantityAtoms) && observation.orderQuantityAtoms > 0
        && observation.matchedTradeAtoms <= item.orderQuantityAtoms;
      let state: 'cancelled' | 'filled' | 'expired' | 'retry' | 'blocked' = 'retry';
      if (!identityMatches || observation.orderStatus === 'MISMATCH') state = 'blocked';
      else if (observation.orderStatus === 'CANCELED'
        && observation.matchedTradeAtoms === item.orderQuantityAtoms) state = 'blocked';
      else if (observation.orderStatus === 'CANCELED' && observation.venueOrderId.length > 0 && observation.cancelConfirmed === true
        && observation.orderHistoryMatched === true && observation.tradeHistoryMatched === true
        && observation.orderHash === item.orderHash) state = 'cancelled';
      else if (observation.orderStatus === 'FILLED' && observation.venueOrderId.length > 0 && observation.orderHistoryMatched === true
        && observation.tradeHistoryMatched === true && observation.orderHash === item.orderHash
        && observation.matchedTradeAtoms === item.orderQuantityAtoms
        && observation.matchedTradeAtoms > 0) state = 'filled';
      else if (observation.orderStatus === 'EXPIRED' && observation.venueOrderId.length > 0
        && observation.orderHistoryMatched === true && observation.tradeHistoryMatched === true
        && observation.orderHash === item.orderHash && observation.matchedTradeAtoms < item.orderQuantityAtoms) state = 'expired';
      const serialized = canonicalJson(observation);
      if (serialized.length > 100_000) { this.db.exec('COMMIT'); return false; }
      const nextAttemptAt = state === 'retry'
        ? nowMs + Math.min(3_600_000, 1_000 * (2 ** Math.min(expectedAttempt, 12))) : 0;
      this.db.prepare('UPDATE mandate_cancellation_outbox SET state=?,venue_order_id=COALESCE(venue_order_id,?),'
        + 'lease_until_ms=NULL,next_attempt_at_ms=?,last_observation_json=?,updated_at_ms=? '
        + "WHERE outbox_id=? AND state='dispatching' AND attempt_count=?")
        .run(state, identityMatches && observation.venueOrderId.length > 0 ? observation.venueOrderId : null,
          nextAttemptAt, serialized, nowMs, outboxId, expectedAttempt);
      if (state === 'cancelled' || state === 'filled' || state === 'expired' || state === 'blocked') {
        this.db.prepare('UPDATE venue_mandate_orders SET state=?,venue_order_id=COALESCE(venue_order_id,?),updated_at_ms=? '
          + 'WHERE venue=? AND mandate_id=? AND order_id=? AND order_hash=?')
          .run(state, identityMatches && observation.venueOrderId.length > 0 ? observation.venueOrderId : null,
            nowMs, item.venue, item.mandateId, item.orderId, item.orderHash);
      } else if (identityMatches && observation.venueOrderId) {
        this.db.prepare('UPDATE venue_mandate_orders SET venue_order_id=?,updated_at_ms=? '
          + 'WHERE venue=? AND mandate_id=? AND order_id=? AND order_hash=?')
          .run(observation.venueOrderId, nowMs, item.venue, item.mandateId, item.orderId, item.orderHash);
      }
      if (state === 'cancelled' || state === 'filled' || state === 'expired') {
        if (item.mandateId === 'MANDATE-C1' && item.venue === 'binance-spot-testnet') {
          this.finalizeDrainedArenaC1MandateRevocation(nowMs);
        } else {
          this.finalizeDrainedHumanMandateRevocation(item.mandateId, nowMs);
        }
      }
      this.db.exec('COMMIT');
      return state;
    } catch (error) { this.rollback(); throw error; }
  }

  getHumanMandateUsage(mandateId: string): { orderCount: number; usedNotionalMinor: number } {
    const row = this.db.prepare(
      'SELECT COUNT(*) AS count, COALESCE(SUM(notional_usd_minor), 0) AS used FROM human_mandate_orders WHERE mandate_id = ?',
    ).get(mandateId) as SqlRow | undefined;
    const orderCount = Number(row?.count ?? 0);
    const usedNotionalMinor = Number(row?.used ?? 0);
    if (!Number.isSafeInteger(orderCount) || !Number.isSafeInteger(usedNotionalMinor) || orderCount < 0 || usedNotionalMinor < 0) {
      throw new Error('Delegated mandate usage is outside the safe integer range.');
    }
    return { orderCount, usedNotionalMinor };
  }

  getHumanMandateIdForPaperOrder(idempotencyKey: string, orderId: string): string | null {
    if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$/.test(idempotencyKey)
      || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(orderId)) return null;
    const row = this.db.prepare(`
      SELECT h.mandate_id
      FROM human_mandate_orders h
      INNER JOIN paper_orders p
        ON p.idempotency_key = h.idempotency_key AND p.order_id = h.order_id
      WHERE h.idempotency_key = ? AND h.order_id = ?
    `).get(idempotencyKey, orderId) as SqlRow | undefined;
    return typeof row?.mandate_id === 'string' && row.mandate_id.length > 0 ? row.mandate_id : null;
  }

  bindB3CellRequestDigest(cellId: string, requestSha256: string): 'bound' | 'same' | 'conflict' {
    if (!/^[A-Za-z0-9][A-Za-z0-9/._:-]{0,159}$/.test(cellId) || !/^[a-f0-9]{64}$/.test(requestSha256)) {
      throw new Error('A bounded B3 cell ID and lowercase request SHA-256 are required.');
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const existing = this.db.prepare(
        'SELECT request_sha256 FROM b3_cell_request_bindings WHERE cell_id = ?',
      ).get(cellId) as SqlRow | undefined;
      if (existing) {
        this.db.exec('COMMIT');
        return existing.request_sha256 === requestSha256 ? 'same' : 'conflict';
      }
      this.db.prepare(
        'INSERT INTO b3_cell_request_bindings (cell_id, request_sha256, bound_at) VALUES (?, ?, ?)',
      ).run(cellId, requestSha256, Date.now());
      this.db.exec('COMMIT');
      return 'bound';
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  authorizeFutuM1Dispatch(input: FutuM1DispatchAuthorization): boolean {
    const digestPattern = /^[A-Za-z0-9_-]{43}$/;
    if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$/.test(input.idempotencyKey)
      || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$/.test(input.orderId)
      || !digestPattern.test(input.orderHash) || !digestPattern.test(input.mandateHash)
      || !digestPattern.test(input.quoteReceiptHash) || !input.mandateId
      || input.secondLockDecision !== 'allow' || input.version !== 'MANDATE-M1-v1.0.0') {
      throw new Error('A complete MANDATE-M1 post-commit authorization is required for Futu SIMULATE.');
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const order = this.readByIdempotencyKey(input.idempotencyKey);
      if (!order || order.orderId !== input.orderId || order.orderHash !== input.orderHash || order.cancelled
        || sha256Base64Url(canonicalJson(order.order)) !== order.orderHash
        || sha256Base64Url(canonicalJson(order.marketQuoteReceipt)) !== input.quoteReceiptHash) {
        this.db.exec('COMMIT');
        return false;
      }
      const activeMandate = this.db.prepare(
        'SELECT 1 AS active FROM human_mandates WHERE mandate_id = ? AND mandate_hash = ? '
        + 'AND revoked_at IS NULL AND revoke_requested_at IS NULL AND expires_at > ?',
      ).get(input.mandateId, input.mandateHash, Date.now()) as SqlRow | undefined;
      if (activeMandate?.active !== 1) {
        this.db.exec('COMMIT');
        return false;
      }
      const existing = this.db.prepare(
        'SELECT order_id, order_hash, mandate_id, mandate_hash, quote_receipt_hash, second_lock_decision, version '
        + 'FROM futu_m1_dispatch_authorizations WHERE idempotency_key = ?',
      ).get(input.idempotencyKey) as SqlRow | undefined;
      if (existing) {
        const same = existing.order_id === input.orderId && existing.order_hash === input.orderHash
          && existing.mandate_id === input.mandateId && existing.mandate_hash === input.mandateHash
          && existing.quote_receipt_hash === input.quoteReceiptHash
          && existing.second_lock_decision === 'allow' && existing.version === input.version;
        this.db.exec('COMMIT');
        return same;
      }
      this.db.prepare(
        'INSERT INTO futu_m1_dispatch_authorizations '
        + '(idempotency_key, order_id, order_hash, mandate_id, mandate_hash, quote_receipt_hash, second_lock_decision, version, created_at) '
        + "VALUES (?, ?, ?, ?, ?, ?, 'allow', ?, ?)",
      ).run(input.idempotencyKey, input.orderId, input.orderHash, input.mandateId, input.mandateHash,
        input.quoteReceiptHash, input.version, Date.now());
      this.db.exec('COMMIT');
      return true;
    } catch (error) {
      this.rollback();
      if (isConstraintError(error)) return false;
      throw error;
    }
  }

  /** Create the immutable C1 control row once; a policy change never silently reactivates a revoked row. */
  ensureArenaC1MandateControl(policyDigest: string, nowMs = Date.now()):
    'active' | 'revoking' | 'revoked' | 'policy-digest-mismatch' | 'not-initialized' | 'invalid' {
    if (!/^[a-f0-9]{64}$/.test(policyDigest) || !Number.isSafeInteger(nowMs) || nowMs < 0) return 'invalid';
    this.db.exec('BEGIN IMMEDIATE');
    try {
      this.db.prepare(`INSERT OR IGNORE INTO arena_c1_mandate_control
        (singleton,mandate_id,policy_digest,state,revoke_requested_at_ms,revoked_at_ms,
         revoked_by_credential_id,revocation_evidence_hash,updated_at_ms)
        VALUES (1,'MANDATE-C1',?,'active',NULL,NULL,NULL,NULL,?)`).run(policyDigest, nowMs);
      const row = this.db.prepare('SELECT mandate_id,policy_digest,state FROM arena_c1_mandate_control WHERE singleton=1')
        .get() as SqlRow | undefined;
      if (!row) { this.db.exec('COMMIT'); return 'not-initialized'; }
      if (row.mandate_id !== 'MANDATE-C1' || row.policy_digest !== policyDigest) {
        this.db.exec('COMMIT'); return 'policy-digest-mismatch';
      }
      const state = row.state;
      this.db.exec('COMMIT');
      return state === 'active' || state === 'revoking' || state === 'revoked' ? state : 'invalid';
    } catch (error) { this.rollback(); throw error; }
  }

  getArenaC1MandateControlStatus(policyDigest: string):
    'active' | 'revoking' | 'revoked' | 'policy-digest-mismatch' | 'not-initialized' | 'invalid' {
    if (!/^[a-f0-9]{64}$/.test(policyDigest)) return 'invalid';
    const row = this.db.prepare('SELECT mandate_id,policy_digest,state FROM arena_c1_mandate_control WHERE singleton=1')
      .get() as SqlRow | undefined;
    if (!row) return 'not-initialized';
    if (row.mandate_id !== 'MANDATE-C1' || row.policy_digest !== policyDigest) return 'policy-digest-mismatch';
    const state = row.state;
    return state === 'active' || state === 'revoking' || state === 'revoked' ? state : 'invalid';
  }

  /** Revoke C1 and enqueue every resident/unknown C1 venue order in the same durable transaction. */
  revokeArenaC1MandateControl(policyDigest: string, credentialId: string, evidenceHash: string, nowMs = Date.now()):
    { revoked: boolean; pending: boolean; queued: number; reason: 'revoked' | 'already-revoked' | 'policy-digest-mismatch' | 'invalid' } {
    if (!/^[a-f0-9]{64}$/.test(policyDigest) || !credentialId || credentialId.length > 512
      || !/^[A-Za-z0-9_-]{43}$/.test(evidenceHash) || !Number.isSafeInteger(nowMs) || nowMs < 0) {
      return { revoked: false, pending: false, queued: 0, reason: 'invalid' };
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const row = this.db.prepare('SELECT mandate_id,policy_digest,state FROM arena_c1_mandate_control WHERE singleton=1')
        .get() as SqlRow | undefined;
      if (!row || row.mandate_id !== 'MANDATE-C1' || row.policy_digest !== policyDigest) {
        this.db.exec('COMMIT'); return { revoked: false, pending: false, queued: 0, reason: 'policy-digest-mismatch' };
      }
      if (row.state === 'revoked') {
        this.db.exec('COMMIT'); return { revoked: true, pending: false, queued: 0, reason: 'already-revoked' };
      }
      if (row.state !== 'active' && row.state !== 'revoking') {
        this.db.exec('COMMIT'); return { revoked: false, pending: false, queued: 0, reason: 'invalid' };
      }
      if (row.state === 'active') {
        this.db.prepare(`UPDATE arena_c1_mandate_control SET state='revoking',revoke_requested_at_ms=?,
          revoked_by_credential_id=?,revocation_evidence_hash=?,updated_at_ms=? WHERE singleton=1 AND state='active'`)
          .run(nowMs, credentialId, evidenceHash, nowMs);
      }
      this.db.prepare(`UPDATE arena_c1_dispatch_authorizations SET state='rejected',
        result_json=?,updated_at_ms=? WHERE state='authorized'`)
        .run(canonicalJson({ state: 'rejected', reason: 'mandate-revoked-before-dispatch' }), nowMs);
      const accepted = this.db.prepare("SELECT authorization_id FROM arena_c1_dispatch_authorizations "
        + "WHERE state IN ('accepted','unknown') ORDER BY created_at_ms,authorization_id").all() as SqlRow[];
      for (const authorization of accepted) {
        if (typeof authorization.authorization_id === 'string') {
          this.recordArenaC1DispatchForRevocationInTransaction(authorization.authorization_id, nowMs);
        }
      }
      const queued = this.enqueueAllMandateCancellations('MANDATE-C1', 'revoked', nowMs);
      const finalized = this.finalizeDrainedArenaC1MandateRevocation(nowMs);
      this.db.exec('COMMIT');
      // A revocation request disables authorization immediately via `revoking`;
      // `pending` separately reports whether resident orders still need closeout.
      return { revoked: finalized, pending: !finalized, queued, reason: 'revoked' };
    } catch (error) { this.rollback(); throw error; }
  }

  /** Persist only a server-minted C1 envelope, atomically charging the shared session cap. */
  authorizeArenaC1Dispatch(authorization: Record<string, unknown>, budgetKey: string, policyDigest: string, nowMs = Date.now()): boolean {
    const requiredStrings = ['authorization_id', 'ledger_row_ref', 'receiver_receipt_ref', 'lock2_receipt_ref', 'idempotency_key', 'order_id', 'order_hash', 'quote_receipt_hash',
      'client_order_id', 'symbol', 'side', 'type', 'time_in_force'];
    if (requiredStrings.some((key) => typeof authorization[key] !== 'string' || !(authorization[key] as string).length)
      || authorization.venue !== 'binance-spot-testnet' || authorization.mandate_id !== 'MANDATE-C1'
      || authorization.mandate_version !== '1.0.0' || authorization.receiver_decision !== 'allow'
      || authorization.lock2_decision !== 'allow' || authorization.type !== 'LIMIT'
      || authorization.ledger_row_ref !== authorization.authorization_id
      || authorization.receiver_receipt_ref !== authorization.quote_receipt_hash
      || !/^[a-f0-9]{64}$/.test(String(authorization.lock2_receipt_ref))
      || !['BUY', 'SELL'].includes(String(authorization.side)) || !['IOC', 'FOK'].includes(String(authorization.time_in_force))
      || authorization.quantity_scale !== 100_000_000 || authorization.price_scale !== 100
      || authorization.currency !== 'USDT' || authorization.currency_scale !== 100
      || !Number.isSafeInteger(authorization.quantity_minor) || Number(authorization.quantity_minor) <= 0
      || !Number.isSafeInteger(authorization.price_minor) || Number(authorization.price_minor) <= 0
      || !Number.isSafeInteger(authorization.notional_minor) || Number(authorization.notional_minor) <= 0
      || Number(authorization.notional_minor) > 50_000
      || !Number.isSafeInteger(authorization.expires_at_ms) || Number(authorization.expires_at_ms) <= nowMs
      || !/^[a-f0-9]{64}$/.test(policyDigest)
      || !/^[a-f0-9]{64}$/.test(String(authorization.order_hash))
      || !/^[a-f0-9]{64}$/.test(String(authorization.quote_receipt_hash))
      || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$/.test(budgetKey)) return false;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const control = this.db.prepare('SELECT mandate_id,policy_digest,state FROM arena_c1_mandate_control WHERE singleton=1')
        .get() as SqlRow | undefined;
      if (!control || control.mandate_id !== 'MANDATE-C1' || control.policy_digest !== policyDigest || control.state !== 'active') {
        this.db.exec('COMMIT'); return false;
      }
      const used = this.db.prepare('SELECT COALESCE(SUM(notional_minor), 0) AS used FROM arena_c1_dispatch_authorizations WHERE budget_key = ?')
        .get(budgetKey) as SqlRow | undefined;
      if (Number(used?.used ?? 0) + Number(authorization.notional_minor) > 200_000) {
        this.db.exec('COMMIT');
        return false;
      }
      this.db.prepare(`INSERT INTO arena_c1_dispatch_authorizations
        (authorization_id,idempotency_key,order_id,order_hash,quote_receipt_hash,notional_minor,budget_key,expires_at_ms,
         authorization_json,state,created_at_ms,updated_at_ms)
        VALUES (?,?,?,?,?,?,?,?,?,'authorized',?,?)`).run(
        String(authorization.authorization_id), String(authorization.idempotency_key), String(authorization.order_id), String(authorization.order_hash),
        String(authorization.quote_receipt_hash), Number(authorization.notional_minor), budgetKey, Number(authorization.expires_at_ms),
        canonicalJson(authorization), nowMs, nowMs);
      this.db.exec('COMMIT');
      return true;
    } catch (error) {
      this.rollback();
      if (isConstraintError(error)) return false;
      throw error;
    }
  }

  claimArenaC1Dispatch(authorizationId: string, authorization: Record<string, unknown>, policyDigest: string, nowMs = Date.now()): boolean {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const control = this.db.prepare('SELECT mandate_id,policy_digest,state FROM arena_c1_mandate_control WHERE singleton=1')
        .get() as SqlRow | undefined;
      if (!control || control.mandate_id !== 'MANDATE-C1' || control.policy_digest !== policyDigest || control.state !== 'active') {
        this.db.exec('COMMIT'); return false;
      }
      const row = this.db.prepare(`SELECT authorization_json,state,expires_at_ms FROM arena_c1_dispatch_authorizations
        WHERE authorization_id = ?`).get(authorizationId) as SqlRow | undefined;
      if (!row || row.state !== 'authorized' || Number(row.expires_at_ms) <= nowMs
        || row.authorization_json !== canonicalJson(authorization)) {
        this.db.exec('COMMIT');
        return false;
      }
      this.db.prepare("UPDATE arena_c1_dispatch_authorizations SET state='dispatching',updated_at_ms=? WHERE authorization_id=? AND state='authorized'")
        .run(nowMs, authorizationId);
      this.db.exec('COMMIT');
      return true;
    } catch (error) { this.rollback(); throw error; }
  }

  getArenaC1SessionUsage(budgetKey: string): number {
    const row = this.db.prepare('SELECT COALESCE(SUM(notional_minor), 0) AS used FROM arena_c1_dispatch_authorizations WHERE budget_key = ?')
      .get(budgetKey) as SqlRow | undefined;
    const used = Number(row?.used ?? 0);
    if (!Number.isSafeInteger(used) || used < 0) throw new Error('Arena C1 session usage is outside the safe integer range.');
    return used;
  }

  /** Return only old, unresolved C1 dispatches for venue-history recovery. */
  getArenaC1DispatchesForRecovery(cutoffMs: number): Array<{
    authorizationId: string; authorizationJson: string; state: 'dispatching' | 'unknown';
    expiresAtMs: number; updatedAtMs: number;
  }> {
    if (!Number.isSafeInteger(cutoffMs) || cutoffMs < 0) throw new Error('A bounded C1 recovery cutoff is required.');
    const rows = this.db.prepare(`SELECT authorization_id,authorization_json,state,expires_at_ms,updated_at_ms
      FROM arena_c1_dispatch_authorizations WHERE state IN ('dispatching','unknown') AND updated_at_ms <= ?
      ORDER BY updated_at_ms,authorization_id`).all(cutoffMs) as SqlRow[];
    return rows.flatMap((row) => {
      if (typeof row.authorization_id !== 'string' || typeof row.authorization_json !== 'string'
        || (row.state !== 'dispatching' && row.state !== 'unknown')
        || !Number.isSafeInteger(row.expires_at_ms) || !Number.isSafeInteger(row.updated_at_ms)) return [];
      return [{ authorizationId: row.authorization_id, authorizationJson: row.authorization_json,
        state: row.state, expiresAtMs: Number(row.expires_at_ms), updatedAtMs: Number(row.updated_at_ms) }];
    });
  }

  finishArenaC1Dispatch(authorizationId: string, state: 'accepted' | 'unknown' | 'rejected', result: unknown, nowMs = Date.now()): boolean {
    const serialized = canonicalJson(result);
    if (!/^auth_c1_[a-f0-9]{32}$/.test(authorizationId) || serialized.length > 100_000 || !Number.isSafeInteger(nowMs)) return false;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const resultOfUpdate = this.db.prepare(`UPDATE arena_c1_dispatch_authorizations SET state=?,result_json=?,updated_at_ms=?
        WHERE authorization_id=? AND state IN ('dispatching','unknown')`).run(state, serialized, nowMs, authorizationId);
      if (Number(resultOfUpdate.changes ?? 0) !== 1) { this.db.exec('COMMIT'); return false; }
      if ((state === 'accepted' || state === 'unknown')
        && !this.recordArenaC1DispatchForRevocationInTransaction(authorizationId, nowMs)) {
        this.db.prepare("UPDATE arena_c1_dispatch_authorizations SET state='unknown',result_json=?,updated_at_ms=? WHERE authorization_id=?")
          .run(canonicalJson({ state: 'unknown', closeout_binding: 'unavailable', reconciliation_required: true }), nowMs, authorizationId);
        this.db.exec('COMMIT');
        return false;
      }
      if (state === 'rejected') this.finalizeDrainedArenaC1MandateRevocation(nowMs);
      this.db.exec('COMMIT');
      return true;
    } catch (error) { this.rollback(); throw error; }
  }

  /** Index an accepted or outcome-unknown C1 Testnet dispatch in the common I4 closeout ledger. */
  recordArenaC1DispatchForRevocation(authorizationId: string, nowMs = Date.now()): boolean {
    if (!/^auth_c1_[a-f0-9]{32}$/.test(authorizationId) || !Number.isSafeInteger(nowMs)) return false;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const recorded = this.recordArenaC1DispatchForRevocationInTransaction(authorizationId, nowMs);
      this.db.exec('COMMIT');
      return recorded;
    } catch (error) { this.rollback(); throw error; }
  }

  /** Caller must hold BEGIN IMMEDIATE. Trigger and window caps share this DB transaction across workers. */
  private evaluateTriggerGuardInTransaction(candidate: DurablePaperOrder, controls: PaperCommitControls,
    requestedNotionalUsdMinor: number, nowMs: number, mandateCreatedAtMs: number): TriggerGuardDecisionV1 {
    const guard = controls.triggerGuard;
    const mandate = controls.mandate;
    if (!guard || triggerScopeError(guard.scope)
      || causalTriggerContextError(guard.context)
      || (guard.authorityKind === 'user-signed' && (!mandate || !mandate.triggerScopeV1
        || triggerScopeError(mandate.triggerScopeV1)
        || canonicalJson(guard.scope) !== canonicalJson(mandate.triggerScopeV1)
        || guard.mandateId !== mandate.id || guard.mandateHash !== mandate.hash))
      || (guard.authorityKind === 'synthetic-policy' && mandate !== undefined)
      || (guard.authorityKind !== 'user-signed' && guard.authorityKind !== 'synthetic-policy')
      || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(guard.mandateId)
      || !/^[A-Za-z0-9_-]{43}$/.test(guard.mandateHash)
      || guard.context.standingRuleRef !== guard.mandateId || guard.context.policyEpoch !== guard.scope.policyEpoch
      || causalTriggerContextError(guard.context)) return { kind: 'deny', reason: 'trigger_scope_or_context_invalid' };
    if (!this.policyPublicKeyPem) return { kind: 'deny', reason: 'trigger_event_signing_key_unavailable' };
    const event = guard.context.event;
    let eventSignatureValid = false;
    try {
      eventSignatureValid = verifySignature(null, Buffer.from(canonicalJson(event.claims)), createPublicKey(this.policyPublicKeyPem), Buffer.from(event.signature, 'base64url'));
    } catch { eventSignatureValid = false; }
    if (!eventSignatureValid) return { kind: 'deny', reason: 'trigger_event_signature_invalid' };
    const order = candidate.order && typeof candidate.order === 'object' ? candidate.order as Record<string, unknown> : null;
    const claims = event.claims;
    const rootTriggerId = guard.context.rootTriggerId;
    const parentEffectOrderId = guard.context.parentEffectOrderId ?? null;
    if (!order || typeof order.symbol !== 'string' || (order.side !== 'buy' && order.side !== 'sell')
      || !guard.scope.allowedActions.includes('order.place')
      || !guard.scope.allowedSymbols.includes(order.symbol) || !guard.scope.allowedSides.includes(order.side)
      || !guard.scope.allowedTriggerTypes.includes(claims.triggerType)
      || !guard.scope.allowedSourceProvenance.includes(claims.sourceProvenance)
      || claims.receivedAtMs > nowMs + 5_000 || claims.expiresAtMs <= nowMs
      || nowMs - claims.receivedAtMs > guard.scope.maxTriggerAgeMs
      || claims.expiresAtMs - claims.receivedAtMs > guard.scope.maxTriggerAgeMs
      || (parentEffectOrderId === null && rootTriggerId !== claims.triggerId)
      || (parentEffectOrderId !== null && parentEffectOrderId === candidate.orderId)) {
      return { kind: 'deny', reason: 'trigger_scope_out_of_scope_or_stale' };
    }
    const eventJson = canonicalJson(event);
    const eventSha256 = sha256Base64Url(eventJson);
    const scopeSha256 = sha256Base64Url(canonicalJson(guard.scope));
    const priorEvent = this.db.prepare('SELECT * FROM causal_trigger_events WHERE trigger_id=?').get(claims.triggerId) as SqlRow | undefined;
    if (priorEvent && (priorEvent.root_trigger_id !== rootTriggerId || priorEvent.mandate_id !== guard.mandateId
      || priorEvent.policy_epoch !== guard.scope.policyEpoch || priorEvent.event_json !== eventJson
      || priorEvent.event_sha256 !== eventSha256 || priorEvent.source_provenance !== claims.sourceProvenance
      || priorEvent.source_sha256 !== claims.sourceSha256)) {
      return { kind: 'deny', reason: 'trigger_event_identity_conflict' };
    }
    if (parentEffectOrderId !== null) {
      const parent = this.db.prepare('SELECT * FROM causal_trigger_effects WHERE order_id=?').get(parentEffectOrderId) as SqlRow | undefined;
      if (!parent || parent.root_trigger_id !== rootTriggerId || parent.mandate_id !== guard.mandateId
        || parent.policy_epoch !== guard.scope.policyEpoch || parent.budget_key !== controls.budgetKey) {
        return { kind: 'deny', reason: 'trigger_parent_lineage_invalid' };
      }
    }
    const breakers = this.db.prepare(`SELECT breaker_scope,scope_ref,policy_epoch,opened_at_ms
      FROM causal_trigger_breakers WHERE budget_key=?
        AND ((breaker_scope='trigger' AND scope_ref=?) OR (breaker_scope='window' AND scope_ref='account'))
      ORDER BY policy_epoch DESC,opened_at_ms DESC`).all(controls.budgetKey, rootTriggerId) as SqlRow[];
    for (const breaker of breakers) {
      if (!Number.isSafeInteger(breaker.policy_epoch) || !Number.isSafeInteger(breaker.opened_at_ms)) {
        return { kind: 'deny', reason: 'trigger_breaker_state_invalid' };
      }
      if (Number(breaker.policy_epoch) >= guard.scope.policyEpoch || mandateCreatedAtMs <= Number(breaker.opened_at_ms)) {
        return { kind: 'breaker-open', scope: breaker.breaker_scope === 'trigger' ? 'trigger' : 'window', reason: 'A trigger breaker is latched; a fresh signed policy epoch is required.' };
      }
    }
    const triggerUsage = this.db.prepare(`SELECT COUNT(*) AS count,COALESCE(SUM(notional_usd_minor),0) AS notional
      FROM causal_trigger_effects WHERE budget_key=? AND mandate_id=? AND policy_epoch=? AND root_trigger_id=?`)
      .get(controls.budgetKey, guard.mandateId, guard.scope.policyEpoch, rootTriggerId) as SqlRow | undefined;
    const triggerCount = Number(triggerUsage?.count ?? 0);
    const triggerNotional = Number(triggerUsage?.notional ?? 0);
    const triggerSymbols = this.db.prepare(`SELECT DISTINCT symbol FROM causal_trigger_effects
      WHERE budget_key=? AND mandate_id=? AND policy_epoch=? AND root_trigger_id=?`).all(
      controls.budgetKey, guard.mandateId, guard.scope.policyEpoch, rootTriggerId) as SqlRow[];
    const distinctSymbols = new Set(triggerSymbols.flatMap((row) => typeof row.symbol === 'string' ? [row.symbol] : []));
    const windowUsage = this.db.prepare(`SELECT COUNT(*) AS count,COALESCE(SUM(notional_usd_minor),0) AS notional
      FROM causal_trigger_effects WHERE budget_key=? AND created_at_ms>? AND created_at_ms<=?`)
      .get(controls.budgetKey, nowMs - guard.scope.portfolioWindowMs, nowMs) as SqlRow | undefined;
    const windowCount = Number(windowUsage?.count ?? 0);
    const windowNotional = Number(windowUsage?.notional ?? 0);
    if (![triggerCount, triggerNotional, windowCount, windowNotional].every(Number.isSafeInteger)
      || [triggerCount, triggerNotional, windowCount, windowNotional].some((value) => value < 0)
      || !Number.isSafeInteger(requestedNotionalUsdMinor) || requestedNotionalUsdMinor <= 0) {
      return { kind: 'deny', reason: 'trigger_usage_aggregate_invalid' };
    }
    let breakerScope: 'trigger' | 'window' | null = null;
    let breakerReason = '';
    if (triggerCount + 1 > guard.scope.maxOrdersPerTrigger
      || distinctSymbols.size + (distinctSymbols.has(order.symbol) ? 0 : 1) > guard.scope.maxDistinctSymbolsPerTrigger
      || BigInt(triggerNotional) + BigInt(requestedNotionalUsdMinor) > BigInt(guard.scope.maxGrossNotionalUsdMinorPerTrigger)) {
      breakerScope = 'trigger';
      breakerReason = 'The signed per-trigger order, instrument, or gross-notional cap would be exceeded.';
    } else if (windowCount + 1 > guard.scope.maxOrdersPerWindow
      || BigInt(windowNotional) + BigInt(requestedNotionalUsdMinor) > BigInt(guard.scope.maxGrossNotionalUsdMinorPerWindow)) {
      breakerScope = 'window';
      breakerReason = 'The signed account rolling-window action or gross-notional cap would be exceeded.';
    }
    if (breakerScope) {
      const scopeRef = breakerScope === 'trigger' ? rootTriggerId : 'account';
      this.db.prepare(`INSERT OR IGNORE INTO causal_trigger_breakers
        (budget_key,breaker_scope,scope_ref,policy_epoch,opened_at_ms,mandate_id,reason,scope_sha256)
        VALUES (?,?,?,?,?,?,?,?)`).run(controls.budgetKey, breakerScope, scopeRef, guard.scope.policyEpoch,
        nowMs, guard.mandateId, breakerReason, scopeSha256);
      return { kind: 'breaker-opened', scope: breakerScope, reason: breakerReason };
    }
    return { kind: 'allow', plan: {
      eventJson, eventSha256, scopeSha256, triggerId: claims.triggerId, rootTriggerId,
      parentEffectOrderId, standingRuleRef: guard.context.standingRuleRef, policyEpoch: guard.scope.policyEpoch,
      mandateId: guard.mandateId, mandateHash: guard.mandateHash, triggerType: claims.triggerType,
      sourceProvenance: claims.sourceProvenance,
      sourceSha256: claims.sourceSha256, receivedAtMs: claims.receivedAtMs, expiresAtMs: claims.expiresAtMs,
      symbol: order.symbol, side: order.side, notionalUsdMinor: requestedNotionalUsdMinor,
    } };
  }

  commit(idempotencyKey: string, candidate: DurablePaperOrder, controls: PaperCommitControls,
    makeInsertionAudit?: (order: DurablePaperOrder) => PaperExecutionAuditRecordV1): PaperCommitResult {
    validateCommitControls(controls);
    const receiptBackedAuditRequired = controls.requireReceiptBackedCommitAudit === true
      || controls.budgetKey.startsWith('synthetic-demo-account:') || controls.triggerGuard !== undefined;
    if (receiptBackedAuditRequired && !makeInsertionAudit) {
      throw new Error('The user paper-account namespace requires a receipt-backed audit factory at the ledger boundary.');
    }
    const hkdBudget = controls.maxNotionalAmount?.currency === 'HKD';
    const requestedNotionalMinor = hkdBudget
      ? calculateNotionalMinor(candidate)
      : calculateNotionalUsdMinor(candidate);
    const requestedNotionalUsd = hkdBudget
      ? convertHkdMinorToUsd(requestedNotionalMinor, controls.ledgerConversion!)
      : requestedNotionalMinor / 100;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const anchor = this.loadPaperAuditAnchor();
      const previousAnchor = clonePaperAuditAnchor(anchor);
      const ledgerIntegrity = this.verifyAllPaperExecutionAudits(anchor);
      this.verifyPaperOrderAuditLinks(anchor, new Set(), ledgerIntegrity.orderRecords);
      let clearSecondLockHold = false;
      const existing = this.readByIdempotencyKey(idempotencyKey);
      if (existing) {
        this.db.exec('COMMIT');
        return existing.intentHash === candidate.intentHash && existing.orderId === candidate.orderId
          ? { kind: 'replay', order: existing }
          : { kind: 'conflict', order: existing };
      }
      const existingOrderId = this.readByOrderId(candidate.orderId);
      if (existingOrderId) {
        this.db.exec('COMMIT');
        return { kind: 'conflict', order: existingOrderId };
      }
      if (this.readKillSwitchStateFromAnchor(this.loadPaperAuditAnchor()).active) {
        this.db.exec('COMMIT');
        return { kind: 'kill-switch-active' };
      }
      if (this.isCapabilityRevoked(controls.capabilityJti, controls.nowMs)) {
        this.db.exec('COMMIT');
        return { kind: 'revoked' };
      }
      if (controls.secondLockActionHash) {
        const actionHash = controls.secondLockActionHash;
        const proposalScope = derivePaperSecondLockHoldScope(controls.budgetKey, candidate.order);
        const exactHold = this.db.prepare('SELECT * FROM second_lock_holds WHERE action_hash = ?')
          .get(actionHash) as SqlRow | undefined;
        const scopedRows = this.db.prepare(`
          SELECT * FROM second_lock_holds
          WHERE account_key = ? AND session_key = ? AND symbol = ? AND side = ? AND approved_at IS NULL
        `).all(proposalScope.accountKey, proposalScope.sessionKey, proposalScope.symbol, proposalScope.side) as SqlRow[];
        const overlappingRows = scopedRows.filter((row) => {
          if (typeof row.action_hash !== 'string' || typeof row.account_key !== 'string'
            || typeof row.session_key !== 'string' || typeof row.symbol !== 'string'
            || (row.side !== 'buy' && row.side !== 'sell') || typeof row.quantity !== 'number'
            || typeof row.created_at !== 'number') return false;
          const hold = createPendingStepUpHold({
            accountKey: row.account_key,
            sessionKey: row.session_key,
            symbol: row.symbol,
            side: row.side,
            quantity: row.quantity,
            sourceActionHash: row.action_hash,
            createdAtMs: row.created_at,
            expiresAtMs: Number.MAX_SAFE_INTEGER,
          });
          return matchPendingStepUpHold(hold, proposalScope, controls.nowMs ?? Date.now()).matches;
        });
        const exactScopeMatches = exactHold
          && exactHold.account_key === proposalScope.accountKey
          && exactHold.session_key === proposalScope.sessionKey
          && exactHold.symbol === proposalScope.symbol
          && exactHold.side === proposalScope.side
          && exactHold.quantity === proposalScope.quantity;
        const exactApproval = Boolean(exactHold && exactHold.approved_at === null && exactScopeMatches
          && controls.mandate && controls.secondLockHoldApprovalHash === actionHash);
        if (exactHold && exactHold.approved_at !== null) {
          this.db.exec('COMMIT');
          return { kind: 'second-lock-held' };
        }
        if (overlappingRows.length > 0) {
          const onlyExactPendingHold = overlappingRows.length === 1 && overlappingRows[0]?.action_hash === actionHash;
          clearSecondLockHold = exactApproval && onlyExactPendingHold;
          if (!clearSecondLockHold) {
            this.db.exec('COMMIT');
            return { kind: 'second-lock-held' };
          }
        } else if (exactHold) {
          // Legacy rows have no scope, and exact hashes from another budget cannot inherit approval.
          clearSecondLockHold = exactApproval;
          if (!clearSecondLockHold) {
            this.db.exec('COMMIT');
            return { kind: 'second-lock-held' };
          }
        }
      }
      let mandateCreatedAtMs: number | undefined;
      if (controls.mandate) {
        const now = controls.nowMs ?? Date.now();
        const mandateRow = this.db.prepare(
          'SELECT expires_at, created_at FROM human_mandates WHERE mandate_id = ? AND mandate_hash = ? AND revoked_at IS NULL AND revoke_requested_at IS NULL',
        ).get(controls.mandate.id, controls.mandate.hash) as SqlRow | undefined;
        if (typeof mandateRow?.expires_at !== 'number' || mandateRow.expires_at <= now) {
          this.db.exec('COMMIT');
          return { kind: 'mandate-revoked' };
        }
        if (Number.isSafeInteger(mandateRow.created_at)) mandateCreatedAtMs = Number(mandateRow.created_at);
        if (clearSecondLockHold && (typeof mandateRow.created_at !== 'number'
          || mandateRow.created_at <= Number(this.db.prepare('SELECT created_at FROM second_lock_holds WHERE action_hash = ?')
            .get(controls.secondLockActionHash!)?.created_at))) {
          this.db.exec('COMMIT');
          return { kind: 'second-lock-held' };
        }
        const usage = this.db.prepare(
          'SELECT COUNT(*) AS count, COALESCE(SUM(notional_usd_minor), 0) AS used FROM human_mandate_orders WHERE mandate_id = ?',
        ).get(controls.mandate.id) as SqlRow | undefined;
        const orderCount = Number(usage?.count ?? 0);
        const usedNotionalMinor = Number(usage?.used ?? 0);
        const mandateMaxNotionalMinor = floorUsdBudgetMinor(controls.mandate.maxSessionNotionalUsd);
        const mandateNotionalMinor = calculateNotionalUsdMinor(candidate);
        if (!Number.isSafeInteger(orderCount) || !Number.isSafeInteger(usedNotionalMinor)
          || !Number.isSafeInteger(mandateMaxNotionalMinor) || !Number.isSafeInteger(mandateNotionalMinor)
          || orderCount < 0 || usedNotionalMinor < 0 || mandateMaxNotionalMinor <= 0 || mandateNotionalMinor <= 0) {
          throw new Error('The delegated mandate has an invalid atomic usage aggregate.');
        }
        if (orderCount >= controls.mandate.maxOrders) {
          this.db.exec('COMMIT');
          return { kind: 'mandate-order-limit' };
        }
        if (BigInt(usedNotionalMinor) + BigInt(mandateNotionalMinor) > BigInt(mandateMaxNotionalMinor)) {
          this.db.exec('COMMIT');
          return { kind: 'mandate-budget-exceeded', usedNotionalMinor, requestedNotionalMinor: mandateNotionalMinor, maxNotionalMinor: mandateMaxNotionalMinor };
        }
      }
      let triggerGuardPlan: TriggerGuardPlanV1 | undefined;
      if (controls.triggerGuard) {
        if (mandateCreatedAtMs === undefined && controls.triggerGuard.authorityKind === 'user-signed') {
          this.db.exec('COMMIT');
          return { kind: 'trigger-scope-denied', reason: 'trigger_mandate_creation_time_unavailable' };
        }
        const decision = this.evaluateTriggerGuardInTransaction(candidate, controls, calculateNotionalUsdMinor(candidate),
          controls.nowMs ?? candidate.createdAt ?? Date.now(), mandateCreatedAtMs ?? 0);
        if (decision.kind === 'deny') {
          this.db.exec('COMMIT');
          return { kind: 'trigger-scope-denied', reason: decision.reason };
        }
        if (decision.kind === 'breaker-open' || decision.kind === 'breaker-opened') {
          if (decision.kind === 'breaker-opened' && controls.triggerGuard) {
            const scopeRef = decision.scope === 'trigger'
              ? controls.triggerGuard.context.rootTriggerId : 'account';
            const breakerRow = this.db.prepare(`
              SELECT budget_key,breaker_scope,scope_ref,policy_epoch,opened_at_ms,mandate_id,reason,scope_sha256
              FROM causal_trigger_breakers
              WHERE budget_key=? AND breaker_scope=? AND scope_ref=? AND policy_epoch=?
            `).get(controls.budgetKey, decision.scope, scopeRef, controls.triggerGuard.scope.policyEpoch) as SqlRow | undefined;
            if (!breakerRow) throw new Error('The newly latched causal trigger breaker row is missing.');
            this.appendCausalTriggerBreakerAuditInTransaction(breakerRow, anchor);
            const checkpointTransition = this.preparePaperAuditCheckpointTransition(previousAnchor, anchor);
            this.db.exec('COMMIT');
            this.completePaperAuditCheckpointTransition(checkpointTransition, anchor);
            this.verifiedPaperAuditCheckpoint = null;
            return { kind: 'trigger-breaker-opened', scope: decision.scope, reason: decision.reason };
          }
          this.db.exec('COMMIT');
          return { kind: decision.kind === 'breaker-open' ? 'trigger-breaker-open' : 'trigger-breaker-opened', scope: decision.scope, reason: decision.reason };
        }
        triggerGuardPlan = decision.plan;
      }
      let usedNotionalUsd = 0;
      if (hkdBudget) {
        const budget = this.db.prepare(
          "SELECT COALESCE(SUM(budget_notional_minor), 0) AS used FROM paper_orders WHERE budget_key = ? AND cancelled = 0 AND budget_currency = 'HKD'",
        ).get(controls.budgetKey) as SqlRow | undefined;
        const usedNotionalMinor = Number(budget?.used ?? 0);
        if (!Number.isSafeInteger(usedNotionalMinor) || usedNotionalMinor < 0 || requestedNotionalMinor === undefined) {
          throw new Error('HKD minor-unit paper budget contains an invalid aggregate.');
        }
        usedNotionalUsd = convertHkdMinorToUsd(usedNotionalMinor, controls.ledgerConversion!);
        if (BigInt(usedNotionalMinor) + BigInt(requestedNotionalMinor)
          > BigInt(controls.maxNotionalAmount!.amount_minor)) {
          this.db.exec('COMMIT');
          return {
            kind: 'budget-exceeded', usedNotionalUsd, requestedNotionalUsd,
            maxNotionalUsd: convertHkdMinorToUsd(controls.maxNotionalAmount!.amount_minor, controls.ledgerConversion!),
            usedNotionalMinor, requestedNotionalMinor, maxNotionalMinor: controls.maxNotionalAmount!.amount_minor,
          };
        }
      } else {
        const budget = this.db.prepare(
          "SELECT COALESCE(SUM(budget_notional_minor), 0) AS used FROM paper_orders WHERE budget_key = ? AND cancelled = 0 AND budget_currency = 'USD'",
        ).get(controls.budgetKey) as SqlRow | undefined;
        const usedNotionalMinor = Number(budget?.used ?? 0);
        const maxNotionalMinor = floorUsdBudgetMinor(controls.maxNotionalUsd!);
        if (!Number.isSafeInteger(usedNotionalMinor) || usedNotionalMinor < 0
          || !Number.isSafeInteger(maxNotionalMinor) || maxNotionalMinor <= 0) {
          throw new Error('USD minor-unit paper budget contains an invalid aggregate.');
        }
        usedNotionalUsd = usedNotionalMinor / 100;
        if (BigInt(usedNotionalMinor) + BigInt(requestedNotionalMinor) > BigInt(maxNotionalMinor)) {
          this.db.exec('COMMIT');
          return { kind: 'budget-exceeded', usedNotionalUsd, requestedNotionalUsd,
            maxNotionalUsd: maxNotionalMinor / 100, usedNotionalMinor,
            requestedNotionalMinor, maxNotionalMinor };
        }
      }
      const createdAt = candidate.createdAt ?? controls.nowMs ?? Date.now();
      if (clearSecondLockHold) {
        const consumed = this.db.prepare('UPDATE second_lock_holds SET approval_mandate_id = ?, approved_at = ? WHERE action_hash = ? AND approved_at IS NULL')
          .run(controls.mandate!.id, createdAt, controls.secondLockActionHash!);
        if (Number(consumed.changes) !== 1) throw new Error('The exact-action second-lock approval was already consumed or changed.');
      }
      this.db.prepare(`
        INSERT INTO paper_orders (
          idempotency_key, order_id, order_hash, intent_hash, order_json,
          market_quote_json, market_quote_result_json, market_quote_receipt_json,
          execution_json, cancelled, created_at, budget_key, budget_notional_usd, budget_notional_minor, budget_currency
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
      `).run(
        idempotencyKey,
        candidate.orderId,
        candidate.orderHash,
        candidate.intentHash,
        JSON.stringify(candidate.order),
        JSON.stringify(candidate.marketQuote),
        JSON.stringify(candidate.marketQuoteResult),
        JSON.stringify(candidate.marketQuoteReceipt),
        JSON.stringify(candidate.execution),
        createdAt,
        controls.budgetKey,
        requestedNotionalUsd,
        requestedNotionalMinor,
        hkdBudget ? 'HKD' : 'USD',
      );
      if (controls.mandate) {
        this.db.prepare(
          'INSERT INTO human_mandate_orders (idempotency_key, mandate_id, order_id, notional_usd_minor, created_at) VALUES (?, ?, ?, ?, ?)',
        ).run(idempotencyKey, controls.mandate.id, candidate.orderId, calculateNotionalUsdMinor(candidate), createdAt);
      }
      const insertedOrder: DurablePaperOrder = { ...candidate, createdAt, cancelled: false, ledgerBinding: {
        idempotencyKey, budgetKey: controls.budgetKey, budgetNotionalUsd: requestedNotionalUsd,
        budgetNotionalMinor: requestedNotionalMinor, budgetCurrency: hkdBudget ? 'HKD' : 'USD', createdAt,
      } };
      let insertionAudit: PaperExecutionAuditRecordV1 | undefined;
      let insertionAnchorToPersist: PaperAuditAnchor | undefined;
      if (makeInsertionAudit) {
        insertionAudit = makeInsertionAudit(insertedOrder);
        if (!isPaperExecutionAuditRecordV1(insertionAudit) || insertionAudit.kind !== 'commit'
          || insertionAudit.outcome !== 'accepted' || insertionAudit.proposal.runId !== (candidate.orderId.replace(/^paper:/, ''))) {
          throw new Error('The atomic paper-order insert requires a typed receipt-backed accepted audit.');
        }
        const insertionAnchor = this.loadPaperAuditAnchor();
        const existingRecords = this.readVerifiedPaperExecutionAudits(candidate.orderId, insertionAnchor);
        if (triggerGuardPlan) {
          const expectedTriggerEffect: PaperTriggerEffectAuditV1 = {
            version: 1,
            triggerId: triggerGuardPlan.triggerId,
            rootTriggerId: triggerGuardPlan.rootTriggerId,
            parentEffectOrderId: triggerGuardPlan.parentEffectOrderId,
            standingRuleRef: triggerGuardPlan.standingRuleRef,
            policyEpoch: triggerGuardPlan.policyEpoch,
            eventSha256: triggerGuardPlan.eventSha256,
            scopeSha256: triggerGuardPlan.scopeSha256,
          };
          if (canonicalJson(insertionAudit.triggerEffect) !== canonicalJson(expectedTriggerEffect)) {
            throw new Error('The receipt-backed paper audit omitted or changed the verified causal trigger lineage.');
          }
          this.db.prepare(`INSERT OR IGNORE INTO causal_trigger_events
            (trigger_id,root_trigger_id,mandate_id,policy_epoch,trigger_type,source_provenance,source_sha256,event_json,event_sha256,received_at_ms,expires_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)`).run(triggerGuardPlan.triggerId, triggerGuardPlan.rootTriggerId,
            triggerGuardPlan.mandateId, triggerGuardPlan.policyEpoch, triggerGuardPlan.triggerType,
            triggerGuardPlan.sourceProvenance, triggerGuardPlan.sourceSha256, triggerGuardPlan.eventJson, triggerGuardPlan.eventSha256,
            triggerGuardPlan.receivedAtMs, triggerGuardPlan.expiresAtMs);
          const auditRecordHash = sha256Base64Url(JSON.stringify(insertionAudit));
          this.db.prepare(`INSERT INTO causal_trigger_effects
            (order_id,idempotency_key,budget_key,mandate_id,policy_epoch,trigger_id,root_trigger_id,parent_effect_order_id,
             standing_rule_ref,symbol,side,notional_usd_minor,created_at_ms,event_sha256,scope_sha256,audit_record_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(candidate.orderId, idempotencyKey, controls.budgetKey,
            triggerGuardPlan.mandateId, triggerGuardPlan.policyEpoch, triggerGuardPlan.triggerId,
            triggerGuardPlan.rootTriggerId, triggerGuardPlan.parentEffectOrderId, triggerGuardPlan.standingRuleRef,
            triggerGuardPlan.symbol, triggerGuardPlan.side, triggerGuardPlan.notionalUsdMinor, createdAt,
            triggerGuardPlan.eventSha256, triggerGuardPlan.scopeSha256, auditRecordHash);
        } else if (insertionAudit.triggerEffect !== undefined) {
          throw new Error('The paper audit claims causal trigger lineage without a verified receiver trigger scope.');
        }
        this.validatePaperAuditEffectClaims(candidate.orderId, insertionAudit);
        this.appendPaperExecutionAuditInTransaction(candidate.orderId, insertionAudit, insertionAnchor, existingRecords, createdAt);
        insertionAnchorToPersist = insertionAnchor;
      } else if (receiptBackedAuditRequired) {
        throw new Error('The paper-order insert requires an atomic receipt-backed audit factory.');
      }
      const checkpointTransition = insertionAnchorToPersist
        ? this.preparePaperAuditCheckpointTransition(previousAnchor, insertionAnchorToPersist)
        : null;
      this.db.exec('COMMIT');
      if (insertionAnchorToPersist) {
        this.completePaperAuditCheckpointTransition(checkpointTransition, insertionAnchorToPersist);
        this.verifiedPaperAuditCheckpoint = null;
      }
      return { kind: 'inserted', order: insertedOrder, ...(insertionAudit ? { insertionAudit } : {}) };
    } catch (error) {
      this.rollback();
      if (isConstraintError(error)) return { kind: 'conflict' };
      throw error;
    }
  }

  getByIdempotencyKey(idempotencyKey: string): DurablePaperOrder | null {
    return this.withPaperAuditRead(() => {
      const anchor = this.loadPaperAuditAnchor();
      const integrity = this.verifyAllPaperExecutionAudits(anchor);
      this.verifyPaperOrderAuditLinks(anchor, new Set(), integrity.orderRecords);
      return this.readByIdempotencyKey(idempotencyKey);
    });
  }

  getByOrderId(orderId: string): DurablePaperOrder | null {
    return this.withPaperAuditRead(() => {
      const anchor = this.loadPaperAuditAnchor();
      const integrity = this.verifyAllPaperExecutionAudits(anchor);
      this.verifyPaperOrderAuditLinks(anchor, new Set(), integrity.orderRecords);
      return this.readByOrderId(orderId);
    });
  }

  recordSecondLockHold(actionHash: string, reasonCode: string, scope: PaperSecondLockHoldScope, nowMs = Date.now()): void {
    if (!/^[A-Za-z0-9_-]{43}$/.test(actionHash) || !/^[a-z0-9_:-]{1,96}$/.test(reasonCode)
      || !Number.isSafeInteger(nowMs)) throw new Error('A valid content-addressed second-lock hold is required.');
    createPendingStepUpHold({ ...scope, sourceActionHash: actionHash, createdAtMs: nowMs, expiresAtMs: Number.MAX_SAFE_INTEGER });
    this.db.exec('BEGIN IMMEDIATE');
    try {
      this.db.prepare(`
        INSERT INTO second_lock_holds
          (action_hash, reason_code, created_at, account_key, session_key, symbol, side, quantity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(action_hash) DO UPDATE SET
          account_key = excluded.account_key, session_key = excluded.session_key,
          symbol = excluded.symbol, side = excluded.side, quantity = excluded.quantity
        WHERE second_lock_holds.approved_at IS NULL
          AND second_lock_holds.account_key IS NULL AND second_lock_holds.session_key IS NULL
          AND second_lock_holds.symbol IS NULL AND second_lock_holds.side IS NULL AND second_lock_holds.quantity IS NULL
      `).run(actionHash, reasonCode, nowMs, scope.accountKey, scope.sessionKey, scope.symbol, scope.side, scope.quantity);
      this.db.exec('COMMIT');
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  getSecondLockHold(actionHash: string): { actionHash: string; reasonCode: string; createdAt: number; approvalMandateId: string | null; approvedAt: number | null; scope: PaperSecondLockHoldScope | null } | null {
    if (!/^[A-Za-z0-9_-]{43}$/.test(actionHash)) return null;
    const row = this.db.prepare('SELECT action_hash, reason_code, created_at, approval_mandate_id, approved_at, account_key, session_key, symbol, side, quantity FROM second_lock_holds WHERE action_hash = ?')
      .get(actionHash) as SqlRow | undefined;
    if (!row || typeof row.action_hash !== 'string' || typeof row.reason_code !== 'string' || typeof row.created_at !== 'number') return null;
    const scope: PaperSecondLockHoldScope | null = typeof row.account_key === 'string' && typeof row.session_key === 'string'
      && typeof row.symbol === 'string' && (row.side === 'buy' || row.side === 'sell')
      && typeof row.quantity === 'number'
      ? { accountKey: row.account_key, sessionKey: row.session_key, symbol: row.symbol, side: row.side as 'buy' | 'sell', quantity: row.quantity }
      : null;
    return { actionHash: row.action_hash, reasonCode: row.reason_code, createdAt: row.created_at,
      approvalMandateId: typeof row.approval_mandate_id === 'string' ? row.approval_mandate_id : null,
      approvedAt: typeof row.approved_at === 'number' ? row.approved_at : null, scope };
  }

  getBudgetUsageMinor(budgetKey: string, currency: 'USD' | 'HKD'): number {
    if (!budgetKey || budgetKey.length > 256) throw new Error('A bounded paper-budget key is required.');
    return this.withPaperAuditRead(() => {
      const anchor = this.loadPaperAuditAnchor();
      const integrity = this.verifyAllPaperExecutionAudits(anchor);
      this.verifyPaperOrderAuditLinks(anchor, new Set(), integrity.orderRecords);
      const row = this.db.prepare(
        'SELECT COALESCE(SUM(budget_notional_minor), 0) AS used FROM paper_orders WHERE budget_key = ? AND cancelled = 0 AND budget_currency = ?',
      ).get(budgetKey, currency) as SqlRow | undefined;
      const used = Number(row?.used ?? 0);
      if (!Number.isSafeInteger(used) || used < 0) throw new Error('Paper budget usage exceeds the safe integer range.');
      return used;
    });
  }

  listOrdersForBudgetPrefix(prefix: string): DurablePaperOrder[] {
    if (!prefix || prefix.length > 256) throw new Error('A bounded paper-budget namespace is required.');
    return this.withPaperAuditRead(() => {
      const anchor = this.loadPaperAuditAnchor();
      const integrity = this.verifyAllPaperExecutionAudits(anchor);
      this.verifyPaperOrderAuditLinks(anchor, new Set(), integrity.orderRecords);
      const rows = this.db.prepare(`
        SELECT * FROM paper_orders WHERE substr(budget_key, 1, length(?)) = ? ORDER BY created_at, rowid
      `).all(prefix, prefix) as SqlRow[];
      return rows.map(decodeOrder);
    });
  }

  private appendCausalTriggerBreakerAuditInTransaction(row: SqlRow, anchor: PaperAuditAnchor): void {
    const event = causalTriggerBreakerEventFromRow(row);
    if (!event) throw new Error('The new causal trigger breaker could not be serialized as a typed audit event.');
    const breakerKey = event.breakerKey;
    const heads = anchor.causalTriggerBreakerHeadsV1 ?? {};
    const previousHead = heads[breakerKey];
    const existingCountRow = this.db.prepare(
      'SELECT COUNT(*) AS count FROM causal_trigger_breaker_audits WHERE breaker_key=?',
    ).get(breakerKey) as SqlRow | undefined;
    const existingCount = Number(existingCountRow?.count ?? 0);
    if (!Number.isSafeInteger(existingCount) || existingCount < 0
      || existingCount !== (previousHead?.sequence ?? 0)) {
      throw new Error('The causal trigger breaker audit chain is out of sync with its external head.');
    }
    const sequence = existingCount + 1;
    if (!Number.isSafeInteger(sequence) || sequence < 1) throw new Error('The causal trigger breaker audit sequence is invalid.');
    const previousMac = previousHead?.headMac ?? PAPER_AUDIT_GENESIS;
    const eventJson = canonicalJson(event);
    const eventHash = sha256Base64Url(eventJson);
    const eventMac = causalTriggerBreakerAuditMac(this.auditKey, breakerKey, sequence, previousMac, eventHash, eventJson);
    this.db.prepare(`
      INSERT INTO causal_trigger_breaker_audits
        (breaker_key,sequence,event_json,event_hash,previous_mac,event_mac,recorded_at_ms)
      VALUES (?,?,?,?,?,?,?)
    `).run(breakerKey, sequence, eventJson, eventHash, previousMac, eventMac, event.openedAtMs);
    anchor.causalTriggerBreakerHeadsV1 = {
      ...heads,
      [breakerKey]: { sequence, headMac: eventMac },
    };
  }

  private appendPaperExecutionAuditInTransaction(orderId: string, record: PaperExecutionAuditRecordV1,
    anchor: PaperAuditAnchor, existingRecords: PaperExecutionAuditRecordV1[], nowMs: number): string {
    const recordJson = JSON.stringify(record);
    if (typeof recordJson !== 'string' || recordJson.length > 1_000_000) {
      throw new Error('Paper execution audit could not be serialized within its storage limit.');
    }
    const recordHash = sha256Base64Url(recordJson);
    const existing = this.db.prepare(
      'SELECT sequence FROM paper_execution_audits WHERE order_id = ? AND record_hash = ? LIMIT 1',
    ).get(orderId, recordHash) as SqlRow | undefined;
    if (existing) return recordHash;
    const sequence = existingRecords.length + 1;
    if (!Number.isSafeInteger(sequence) || sequence <= 0) throw new Error('Paper execution audit sequence exceeded the safe integer range.');
    const previousMac = existingRecords.length
      ? this.getPaperAuditMac(orderId, sequence - 1)
      : PAPER_AUDIT_GENESIS;
    const recordMac = this.paperAuditRecordMac(orderId, sequence, previousMac, recordHash, recordJson);
    this.db.prepare(`
      INSERT INTO paper_execution_audits (order_id, sequence, record_json, record_hash, previous_mac, record_mac, recorded_at_ms)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(orderId, sequence, recordJson, recordHash, previousMac, recordMac, nowMs);
    anchor.orders[orderId] = { sequence, headMac: recordMac };
    return recordHash;
  }

  appendPaperExecutionAudit(orderId: string, record: PaperExecutionAuditRecordV1, nowMs = Date.now()): PaperExecutionAuditRecordV1[] {
    if (!orderId || orderId.length > 256 || !isPaperExecutionAuditRecordV1(record)
      || orderId !== 'paper:' + record.proposal.runId || !Number.isSafeInteger(nowMs)) {
      throw new Error('Paper execution audit failed its typed storage checks.');
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const anchor = this.loadPaperAuditAnchor();
      const previousAnchor = clonePaperAuditAnchor(anchor);
      const verifiedDataVersion = this.paperAuditDataVersion();
      const verifiedHistory = this.verifyAllPaperExecutionAudits(anchor, verifiedDataVersion);
      const allowedPendingCancellation = record.kind === 'cancel'
        && (record.outcome === 'applied' || record.outcome === 'unknown' || record.outcome === 'committing')
        ? new Set([orderId]) : new Set<string>();
      this.verifyPaperOrderAuditLinks(anchor, new Set([orderId]), verifiedHistory.orderRecords, allowedPendingCancellation);
      const existingRecords = this.readVerifiedPaperExecutionAudits(orderId, anchor);
      const order = this.db.prepare('SELECT 1 AS present FROM paper_orders WHERE order_id = ? LIMIT 1').get(orderId) as SqlRow | undefined;
      if (!order && !(record.kind === 'commit' && ['unknown', 'held', 'rejected', 'committing'].includes(record.outcome))) {
        throw new Error('Paper execution audit cannot be attached to an unknown ledger order.');
      }
      this.validatePaperAuditEffectClaims(orderId, record);
      this.appendPaperExecutionAuditInTransaction(orderId, record, anchor, existingRecords, nowMs);
      const checkpointTransition = this.preparePaperAuditCheckpointTransition(previousAnchor, anchor);
      this.db.exec('COMMIT');
      this.completePaperAuditCheckpointTransition(checkpointTransition, anchor);
      this.verifiedPaperAuditCheckpoint = { dataVersion: verifiedDataVersion, anchorJson: canonicalJson(anchor) };
    } catch (error) {
      this.rollback();
      throw error;
    }
    return this.listPaperExecutionAudits(orderId);
  }

  listPaperExecutionAudits(orderId: string): PaperExecutionAuditRecordV1[] {
    if (!orderId || orderId.length > 256) throw new Error('A bounded paper-order identifier is required for audit lookup.');
    return this.withPaperAuditRead(() => {
      const anchor = this.loadPaperAuditAnchor();
      const integrity = this.verifyAllPaperExecutionAudits(anchor);
      this.verifyPaperOrderAuditLinks(anchor, new Set(), integrity.orderRecords);
      const records = this.readVerifiedPaperExecutionAudits(orderId, anchor);
      return records;
    });
  }

  listPaperDecisionAttempts(limit = 50): PaperDecisionAttemptV1[] {
    return this.getPaperDecisionJournal(limit).attempts;
  }

  getPaperDecisionJournal(limit = 50): PaperDecisionJournalV1 {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 500) throw new Error('Paper decision-attempt lookup limit is out of bounds.');
    return this.withPaperAuditRead(() => {
      const anchor = this.loadPaperAuditAnchor();
      const auditIntegrity = this.verifyAllPaperExecutionAudits(anchor);
      this.verifyPaperOrderAuditLinks(anchor, new Set(), auditIntegrity.orderRecords);
      const seen = new Set(auditIntegrity.orderCounts.keys());
      const auditRecords = auditIntegrity.auditRecords;
      const rows = this.db.prepare(`
        SELECT a.order_id, a.record_json, a.record_hash, a.previous_mac, a.record_mac
        FROM paper_execution_audits a LEFT JOIN paper_orders p ON p.order_id = a.order_id
        WHERE p.order_id IS NULL ORDER BY a.recorded_at_ms DESC, a.sequence DESC LIMIT ?
      `).all(limit) as SqlRow[];
      const attemptsByTrace = new Map<string, PaperDecisionAttemptV1>();
      for (const row of rows) {
        if (typeof row.order_id !== 'string' || typeof row.record_json !== 'string' || typeof row.record_hash !== 'string'
          || typeof row.previous_mac !== 'string' || typeof row.record_mac !== 'string') {
          throw new Error('Paper decision-attempt row is incomplete.');
        }
        const record = parseJson(row.record_json);
        if (!isPaperExecutionAuditRecordV1(record) || record.kind !== 'commit'
          || !['unknown', 'held', 'rejected', 'committing'].includes(record.outcome)
          || row.order_id !== 'paper:' + record.proposal.runId
          || sha256Base64Url(row.record_json) !== row.record_hash) {
          throw new Error('Paper decision-attempt row failed its schema or integrity check.');
        }
        const key = row.order_id + ':' + record.audit.traceId;
        if (!attemptsByTrace.has(key)) attemptsByTrace.set(key, { orderId: row.order_id, record });
      }
      return {
        attempts: [...attemptsByTrace.values()],
        integrity: {
          verified: true,
          auditRecords,
          orderChains: seen.size,
          anchoredOrderHeads: Object.keys(anchor.orders).length,
          killSwitchEvents: auditIntegrity.killSwitchEvents,
          killSwitchVersion: anchor.killSwitch.version,
          causalTriggerBreakerEvents: auditIntegrity.causalTriggerBreakerEvents,
          keySource: this.auditKeySource,
          checkpoint: this.auditWitness ? 'remote-witness-configured' : this.auditAnchorPath ? 'host-local-file' : 'process-memory',
          verifiedAt: new Date().toISOString(),
        },
      };
    });
  }

  /** Return the authenticated current head for one-time independent witness bootstrap. */
  getVerifiedPaperAuditWitnessBootstrap(): { version: 0; headHash: string } {
    if (this.auditWitness) throw new Error('Disable the witness configuration while preparing a one-time witness bootstrap.');
    return this.withPaperAuditRead(() => {
      const anchor = this.loadPaperAuditAnchor();
      const integrity = this.verifyAllPaperExecutionAudits(anchor);
      this.verifyPaperOrderAuditLinks(anchor, new Set(), integrity.orderRecords);
      this.readKillSwitchStateFromAnchor(anchor);
      return { version: 0, headHash: paperAuditWitnessAnchorHash(anchor) };
    });
  }

  revokeCapability(jti: string, revokedUntil: number, nowMs = Date.now()): void {
    if (!jti || jti.length > 128 || !Number.isSafeInteger(revokedUntil) || revokedUntil <= nowMs) {
      throw new Error('Capability revocation requires a valid JTI and future expiry.');
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const now = nowMs;
      this.db.prepare('DELETE FROM revoked_capabilities WHERE revoked_until <= ?').run(now);
      this.db.prepare(`
        INSERT INTO revoked_capabilities (jti, revoked_until, revoked_at) VALUES (?, ?, ?)
        ON CONFLICT(jti) DO UPDATE SET revoked_until = MAX(revoked_until, excluded.revoked_until)
      `).run(jti, revokedUntil, now);
      this.db.exec('COMMIT');
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  isCapabilityRevoked(jti: string, nowMs = Date.now()): boolean {
    if (!jti || jti.length > 128) return false;
    const row = this.db.prepare('SELECT revoked_until FROM revoked_capabilities WHERE jti = ?').get(jti) as SqlRow | undefined;
    return typeof row?.revoked_until === 'number' && row.revoked_until > nowMs;
  }

  private paperAuditDataVersion(): number {
    const row = this.db.prepare('PRAGMA data_version').get() as SqlRow | undefined;
    const version = Number(row?.data_version);
    if (!Number.isSafeInteger(version) || version < 0) throw new Error('Paper audit SQLite data version is unavailable.');
    return version;
  }

  private ensurePaperAuditIntegrity(anchor: PaperAuditAnchor, dataVersion: number): void {
    const anchorJson = canonicalJson(anchor);
    if (this.verifiedPaperAuditCheckpoint?.dataVersion === dataVersion
      && this.verifiedPaperAuditCheckpoint.anchorJson === anchorJson) return;
    this.verifyAllPaperExecutionAudits(anchor, dataVersion);
  }

  private verifyAllPaperExecutionAudits(anchor: PaperAuditAnchor, dataVersion = this.paperAuditDataVersion()): {
    orderCounts: Map<string, number>;
    orderRecords: Map<string, PaperExecutionAuditRecordV1[]>;
    auditRecords: number;
    killSwitchEvents: number;
    causalTriggerBreakerEvents: number;
  } {
    const killSwitchEvents = this.readVerifiedKillSwitchEvents(anchor);
    const causalTriggerBreakerEvents = this.readVerifiedCausalTriggerBreakerAudits(anchor).length;
    const rows = this.db.prepare('SELECT DISTINCT order_id FROM paper_execution_audits ORDER BY order_id').all() as SqlRow[];
    const orderCounts = new Map<string, number>();
    const orderRecords = new Map<string, PaperExecutionAuditRecordV1[]>();
    let auditRecords = 0;
    for (const row of rows) {
      if (typeof row.order_id !== 'string') throw new Error('Paper execution audit order index is malformed.');
      const records = this.readVerifiedPaperExecutionAudits(row.order_id, anchor);
      orderCounts.set(row.order_id, records.length);
      orderRecords.set(row.order_id, records);
      auditRecords += records.length;
    }
    if (Object.keys(anchor.orders).some((orderId) => !orderCounts.has(orderId))) {
      throw new Error('Paper execution audit history is missing rows recorded by its external head.');
    }
    this.verifiedPaperAuditCheckpoint = { dataVersion, anchorJson: canonicalJson(anchor) };
    return { orderCounts, orderRecords, auditRecords, killSwitchEvents: killSwitchEvents.length, causalTriggerBreakerEvents };
  }

  private verifyPaperOrderAuditLinks(anchor: PaperAuditAnchor, allowedUnlinkedOrderIds: Set<string>,
    verifiedRecords: Map<string, PaperExecutionAuditRecordV1[]> = new Map(),
    allowedUnlinkedCancellationIds: Set<string> = new Set()): void {
    const rows = this.db.prepare('SELECT * FROM paper_orders ORDER BY order_id').all() as SqlRow[];
    for (const row of rows) {
      if (typeof row.order_id !== 'string' || !row.order_id || typeof row.budget_key !== 'string') {
        throw new Error('Durable paper-order index is malformed.');
      }
      // J-020 is the persistent user account restore path. Evaluation namespaces
      // are isolated replay fixtures and keep their separate evidence contract.
      if (!row.budget_key.startsWith('synthetic-demo-account:')) continue;
      const records = verifiedRecords.get(row.order_id) ?? this.readVerifiedPaperExecutionAudits(row.order_id, anchor);
      const hasReceiptBackedCommit = records.some((record) => record.kind === 'commit'
        && (record.outcome === 'accepted' || record.outcome === 'recovered'));
      if (!hasReceiptBackedCommit && !allowedUnlinkedOrderIds.has(row.order_id)) {
        throw new Error('Durable paper order is not linked to an authenticated, receipt-backed commit audit.');
      }
      const cancelled = row.cancelled === 1;
      if (row.cancelled !== 0 && row.cancelled !== 1) throw new Error('Durable paper cancellation flag is malformed.');
      const hasAppliedCancellation = records.some((record) => record.kind === 'cancel' && record.outcome === 'applied');
      if (cancelled !== hasAppliedCancellation && !allowedUnlinkedCancellationIds.has(row.order_id)) {
        throw new Error('Durable paper cancellation state is not backed by an authenticated applied-cancel receipt.');
      }
    }
  }

  private readVerifiedKillSwitchEvents(anchor: PaperAuditAnchor): SqlRow[] {
    const rows = this.db.prepare(
      'SELECT version, active, changed_at, credential_id, evidence_hash, previous_mac, event_mac FROM kill_switch_events ORDER BY version',
    ).all() as SqlRow[];
    let previousMac = KILL_SWITCH_AUDIT_GENESIS;
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index];
      const version = index + 1;
      if (!row || row.version !== version || (row.active !== 0 && row.active !== 1)
        || !Number.isSafeInteger(row.changed_at) || typeof row.credential_id !== 'string'
        || !/^[A-Za-z0-9_-]{1,512}$/.test(row.credential_id)
        || typeof row.evidence_hash !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(row.evidence_hash)
        || typeof row.previous_mac !== 'string' || typeof row.event_mac !== 'string') {
        throw new Error('The durable kill-switch event journal has a missing or malformed authenticated event.');
      }
      const event: KillSwitchAuditEventV1 = {
        version,
        active: row.active === 1,
        changedAt: row.changed_at as number,
        credentialId: row.credential_id,
        evidenceHash: row.evidence_hash,
      };
      const expectedMac = killSwitchAuditEventMac(this.auditKey, previousMac, event);
      if (!constantTimeStringEqual(row.previous_mac, previousMac)
        || !constantTimeStringEqual(row.event_mac, expectedMac)) {
        throw new Error('The durable kill-switch event chain failed authentication.');
      }
      previousMac = row.event_mac;
    }
    if (anchor.killSwitch.version !== rows.length || !constantTimeStringEqual(anchor.killSwitch.headMac, previousMac)) {
      throw new Error('The authenticated kill-switch checkpoint does not match its event journal.');
    }
    return rows;
  }

  private readVerifiedCausalTriggerBreakerAudits(anchor: PaperAuditAnchor): SqlRow[] {
    const rows = this.db.prepare(`
      SELECT breaker_key,sequence,event_json,event_hash,previous_mac,event_mac,recorded_at_ms
      FROM causal_trigger_breaker_audits ORDER BY breaker_key,sequence
    `).all() as SqlRow[];
    const computedHeads: Record<string, { sequence: number; headMac: string }> = {};
    const latestEvents = new Map<string, CausalTriggerBreakerAuditV1>();
    for (const row of rows) {
      if (typeof row.breaker_key !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(row.breaker_key)
        || !Number.isSafeInteger(row.sequence) || Number(row.sequence) < 1
        || typeof row.event_json !== 'string' || typeof row.event_hash !== 'string'
        || typeof row.previous_mac !== 'string' || typeof row.event_mac !== 'string'
        || !Number.isSafeInteger(row.recorded_at_ms)) {
        throw new Error('The causal trigger breaker audit journal has a missing or malformed event.');
      }
      const eventValue = parseJson(row.event_json);
      if (!isCausalTriggerBreakerAuditV1(eventValue) || eventValue.breakerKey !== row.breaker_key
        || eventValue.openedAtMs !== row.recorded_at_ms) {
        throw new Error('The causal trigger breaker audit event failed schema or row binding checks.');
      }
      const currentHead = computedHeads[row.breaker_key];
      const expectedSequence = (currentHead?.sequence ?? 0) + 1;
      const previousMac = currentHead?.headMac ?? PAPER_AUDIT_GENESIS;
      const eventHash = sha256Base64Url(row.event_json);
      const expectedMac = causalTriggerBreakerAuditMac(this.auditKey, row.breaker_key, expectedSequence,
        previousMac, eventHash, row.event_json);
      if (Number(row.sequence) !== expectedSequence || row.event_hash !== eventHash
        || !constantTimeStringEqual(row.previous_mac, previousMac)
        || !constantTimeStringEqual(row.event_mac, expectedMac)) {
        throw new Error('The causal trigger breaker audit chain failed sequence, hash, or authentication checks.');
      }
      computedHeads[row.breaker_key] = { sequence: expectedSequence, headMac: row.event_mac };
      latestEvents.set(row.breaker_key, eventValue);
    }
    const anchoredHeads = anchor.causalTriggerBreakerHeadsV1 ?? {};
    if (canonicalJson(computedHeads) !== canonicalJson(anchoredHeads)) {
      throw new Error('The causal trigger breaker journal does not match its externally anchored heads.');
    }

    const breakers = this.db.prepare(`
      SELECT budget_key,breaker_scope,scope_ref,policy_epoch,opened_at_ms,mandate_id,reason,scope_sha256
      FROM causal_trigger_breakers ORDER BY budget_key,breaker_scope,scope_ref,policy_epoch
    `).all() as SqlRow[];
    const seen = new Set<string>();
    for (const row of breakers) {
      const event = causalTriggerBreakerEventFromRow(row);
      if (!event) throw new Error('A durable causal trigger breaker row is malformed.');
      const breakerKey = causalTriggerBreakerKey(event);
      const latest = latestEvents.get(breakerKey);
      if (!latest || canonicalJson(latest) !== canonicalJson(event) || seen.has(breakerKey)) {
        throw new Error('A durable causal trigger breaker is not backed by exactly one authenticated, anchored event.');
      }
      seen.add(breakerKey);
    }
    if (seen.size !== latestEvents.size) {
      throw new Error('The causal trigger breaker audit journal contains an event without a durable latched breaker.');
    }
    return rows;
  }

  cancel(idempotencyKey: string, orderId: string, orderHash: string,
    makeAppliedAudit?: (order: DurablePaperOrder) => PaperExecutionAuditRecordV1): PaperCancelResult {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const activeDispatch = this.db.prepare(
        "SELECT state FROM futu_simulate_dispatches WHERE order_id = ? AND order_hash = ? "
        + "AND state IN ('dispatching','unknown','conflict','accepted') LIMIT 1",
      ).get(orderId, orderHash) as SqlRow | undefined;
      if (activeDispatch && typeof activeDispatch.state === 'string') {
        this.db.exec('COMMIT');
        return { kind: 'dispatch-blocked', state: activeDispatch.state as 'dispatching' | 'unknown' | 'conflict' | 'accepted' };
      }

      const anchor = this.loadPaperAuditAnchor();
      const previousAnchor = clonePaperAuditAnchor(anchor);
      const integrity = this.verifyAllPaperExecutionAudits(anchor);
      this.verifyPaperOrderAuditLinks(anchor, new Set(), integrity.orderRecords);

      const previousCancellation = this.db.prepare(
        'SELECT order_id, order_hash FROM paper_cancellations WHERE idempotency_key = ?',
      ).get(idempotencyKey) as SqlRow | undefined;
      if (previousCancellation) {
        const existingOrder = this.readByOrderId(orderId);
        const hasAppliedReceiptForKey = this.readVerifiedPaperExecutionAudits(orderId).some((record) =>
          record.kind === 'cancel' && record.outcome === 'applied'
          && (record.audit.paperLedgerReceipt?.result as Record<string, unknown> | undefined)?.idempotencyKey === idempotencyKey);
        this.db.exec('COMMIT');
        return previousCancellation.order_id === orderId && previousCancellation.order_hash === orderHash
          && existingOrder?.cancelled === true && hasAppliedReceiptForKey
          ? { kind: 'replay', order: existingOrder }
          : { kind: 'conflict' };
      }

      const existing = this.readByOrderId(orderId);
      if (!existing || existing.orderHash !== orderHash) {
        this.db.exec('COMMIT');
        return { kind: 'missing' };
      }
      if (!isOpenUnfilledOrder(existing.execution)) {
        this.db.exec('COMMIT');
        return { kind: 'conflict' };
      }
      if (existing.cancelled) {
        const hasAppliedReceiptForKey = this.readVerifiedPaperExecutionAudits(orderId).some((record) =>
          record.kind === 'cancel' && record.outcome === 'applied'
          && (record.audit.paperLedgerReceipt?.result as Record<string, unknown> | undefined)?.idempotencyKey === idempotencyKey);
        this.db.exec('COMMIT');
        return hasAppliedReceiptForKey ? { kind: 'replay', order: existing } : { kind: 'conflict' };
      }

      const update = this.db.prepare('UPDATE paper_orders SET cancelled = 1 WHERE order_id = ? AND order_hash = ? AND cancelled = 0')
        .run(orderId, orderHash);
      if (Number(update.changes) !== 1) {
        this.db.exec('ROLLBACK');
        return { kind: 'conflict' };
      }
      this.db.prepare('INSERT INTO paper_cancellations (idempotency_key, order_id, order_hash, created_at) VALUES (?, ?, ?, ?)')
        .run(idempotencyKey, orderId, orderHash, Date.now());
      const cancelledOrder = { ...existing, cancelled: true };
      const receiptBackedAuditRequired = cancelledOrder.ledgerBinding?.budgetKey.startsWith('synthetic-demo-account:') === true;
      if (receiptBackedAuditRequired && !makeAppliedAudit) {
        throw new Error('The user paper-account namespace requires a receipt-backed cancellation audit factory at the ledger boundary.');
      }
      let appliedAudit: PaperExecutionAuditRecordV1 | undefined;
      let anchorToPersist: PaperAuditAnchor | undefined;
      if (makeAppliedAudit) {
        appliedAudit = makeAppliedAudit(cancelledOrder);
        if (!isPaperExecutionAuditRecordV1(appliedAudit) || appliedAudit.kind !== 'cancel' || appliedAudit.outcome !== 'applied'
          || appliedAudit.proposal.runId !== orderId.replace(/^paper:/, '')) {
          throw new Error('The atomic paper cancellation requires a typed receipt-backed applied audit.');
        }
        const existingRecords = this.readVerifiedPaperExecutionAudits(orderId, anchor);
        this.validatePaperAuditEffectClaims(orderId, appliedAudit);
        this.appendPaperExecutionAuditInTransaction(orderId, appliedAudit, anchor, existingRecords, Date.now());
        anchorToPersist = anchor;
      }
      const checkpointTransition = anchorToPersist
        ? this.preparePaperAuditCheckpointTransition(previousAnchor, anchorToPersist)
        : null;
      this.db.exec('COMMIT');
      if (anchorToPersist) {
        this.completePaperAuditCheckpointTransition(checkpointTransition, anchorToPersist);
        this.verifiedPaperAuditCheckpoint = null;
      }
      return { kind: 'cancelled', order: cancelledOrder, ...(appliedAudit ? { appliedAudit } : {}) };
    } catch (error) {
      this.rollback();
      if (isConstraintError(error)) return { kind: 'conflict' };
      throw error;
    }
  }

  close(): void {
    this.db.close();
  }

  private ensurePaperAuditIntegrityColumns(): void {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const columns = new Set((this.db.prepare('PRAGMA table_info(paper_execution_audits)').all() as SqlRow[])
        .map((row) => row.name).filter((name): name is string => typeof name === 'string'));
      for (const name of ['previous_mac', 'record_mac']) {
        if (columns.has(name)) continue;
        const count = this.db.prepare('SELECT COUNT(*) AS count FROM paper_execution_audits').get() as SqlRow | undefined;
        if (Number(count?.count ?? 0) !== 0) {
          throw new Error('Legacy unauthenticated paper audit rows are present. Refusing to bless them without an independently trusted migration.');
        }
        this.db.exec(`ALTER TABLE paper_execution_audits ADD COLUMN ${name} TEXT NOT NULL CHECK (length(${name}) = 43)`);
      }
      this.db.exec('COMMIT');
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  private withPaperAuditRead<T>(read: () => T): T {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const result = read();
      this.db.exec('COMMIT');
      return result;
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  private loadPaperAuditAnchor(): PaperAuditAnchor {
    if (!this.auditAnchorPath) return clonePaperAuditAnchor(this.memoryAuditAnchor);
    const pending = this.readPaperAuditCheckpointTransition();
    if (pending) {
      const dataVersion = this.paperAuditDataVersion();
      const candidates: Array<{ anchor: PaperAuditAnchor; side: 'next' | 'previous' }> = [
        { anchor: pending.next, side: 'next' },
        { anchor: pending.previous, side: 'previous' },
      ];
      const valid: Array<{ anchor: PaperAuditAnchor; side: 'next' | 'previous' }> = [];
      for (const candidate of candidates) {
        try {
          const integrity = this.verifyAllPaperExecutionAudits(candidate.anchor, dataVersion);
          this.verifyPaperOrderAuditLinks(candidate.anchor, new Set(), integrity.orderRecords);
          this.readKillSwitchStateFromAnchor(candidate.anchor);
          if (candidate.side === 'next') this.verifyPaperAuditCheckpointTransitionRows(pending);
          valid.push(candidate);
        } catch {
          // Try the other exact endpoint; if neither validates, preserve fail-closed behavior.
        }
      }
      if (valid.length !== 1) {
        throw new Error('Staged paper-audit checkpoint does not match exactly one committed or prior SQLite state.');
      }
      const recovered = this.auditWitness
        ? this.reconcileWitnessedPaperAuditCheckpoint(pending, valid[0]!)
        : valid[0]!;
      // SQLite is atomic: recovery is limited to the exact endpoints in this
      // signed transition. A configured independent witness must also confirm
      // whether that exact transition committed before its marker is removed.
      this.writePaperAuditAnchor(recovered.anchor);
      this.clearPaperAuditCheckpointTransition(pending.transactionId);
      this.verifiedPaperAuditCheckpoint = { dataVersion, anchorJson: canonicalJson(recovered.anchor) };
      return clonePaperAuditAnchor(recovered.anchor);
    }
    const anchor = this.readPaperAuditAnchorFile();
    if (this.auditWitness) this.verifyPaperAuditWitnessHead(anchor);
    return anchor;
  }

  private reconcileWitnessedPaperAuditCheckpoint(
    transition: PaperAuditCheckpointTransitionV1,
    databaseEndpoint: { anchor: PaperAuditAnchor; side: 'next' | 'previous' },
  ): { anchor: PaperAuditAnchor; side: 'next' | 'previous' } {
    const witness = this.auditWitness!;
    const previousHash = paperAuditWitnessAnchorHash(transition.previous);
    const nextHash = paperAuditWitnessAnchorHash(transition.next);
    let state = requestPaperAuditWitness(witness, '/v1/state', { ledgerId: witness.ledgerId });
    if (state.pending) {
      const pending = state.pending;
      if (pending.transactionId !== transition.transactionId || pending.expectedVersion !== state.version
        || pending.previousHash !== previousHash || pending.nextHash !== nextHash
        || state.headHash !== previousHash) {
        throw new Error('Independent paper-audit witness has a different pending transition.');
      }
      if (databaseEndpoint.side === 'next') {
        state = requestPaperAuditWitness(witness, '/v1/commit', {
          ledgerId: witness.ledgerId, transactionId: transition.transactionId,
        });
        if (state.pending || state.headHash !== nextHash || state.lastTransactionId !== transition.transactionId
          || state.version !== pending.expectedVersion + 1) {
          throw new Error('Independent paper-audit witness did not confirm the committed transition.');
        }
        return { anchor: transition.next, side: 'next' };
      }
      state = requestPaperAuditWitness(witness, '/v1/abort', {
        ledgerId: witness.ledgerId, transactionId: transition.transactionId,
      });
      if (state.pending || state.headHash !== previousHash || state.version !== pending.expectedVersion) {
        throw new Error('Independent paper-audit witness did not confirm the rolled-back transition.');
      }
      return { anchor: transition.previous, side: 'previous' };
    }

    if (databaseEndpoint.side === 'next' && state.headHash === nextHash
      && state.lastTransactionId === transition.transactionId) {
      return { anchor: transition.next, side: 'next' };
    }
    if (databaseEndpoint.side === 'previous' && state.headHash === previousHash) {
      return { anchor: transition.previous, side: 'previous' };
    }
    throw new Error('Independent paper-audit witness does not confirm the staged SQLite endpoint.');
  }

  private verifyPaperAuditWitnessHead(anchor: PaperAuditAnchor): PaperAuditWitnessStateV1 {
    const witness = this.auditWitness!;
    const state = requestPaperAuditWitness(witness, '/v1/state', { ledgerId: witness.ledgerId });
    if (state.pending || state.headHash !== paperAuditWitnessAnchorHash(anchor)) {
      throw new Error('Local paper-audit checkpoint does not match the independent witness head.');
    }
    return state;
  }

  private readPaperAuditAnchorFile(): PaperAuditAnchor {
    if (!this.auditAnchorPath) return clonePaperAuditAnchor(this.memoryAuditAnchor);
    let fd: number;
    try {
      fd = openAuditSidecarRead(this.auditAnchorPath);
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code === 'ELOOP') throw new Error('Paper audit external head must not be a symbolic link.');
      if (code !== 'ENOENT') throw new Error('Paper audit external head cannot be opened safely.');
      const rows = this.db.prepare(`
        SELECT (SELECT COUNT(*) FROM paper_execution_audits) AS audit_count,
          (SELECT COUNT(*) FROM kill_switch_events) AS kill_switch_count,
          (SELECT COUNT(*) FROM causal_trigger_breakers) AS trigger_breaker_count,
          (SELECT COUNT(*) FROM causal_trigger_breaker_audits) AS trigger_breaker_audit_count
      `).get() as SqlRow | undefined;
      if (Number(rows?.audit_count ?? 0) > 0 || Number(rows?.kill_switch_count ?? 0) > 0) {
        throw new Error('Paper audit external head is missing while authenticated history remains in SQLite.');
      }
      if (Number(rows?.trigger_breaker_count ?? 0) > 0 || Number(rows?.trigger_breaker_audit_count ?? 0) > 0) {
        throw new Error('Paper audit external head is missing while causal trigger breaker state remains in SQLite.');
      }
      return { schemaVersion: 2, orders: {}, killSwitch: { version: 0, headMac: KILL_SWITCH_AUDIT_GENESIS } };
    }
    let decoded: unknown;
    try {
      hardenAuditSidecarDescriptor(fd, 'Paper audit external head');
      let contents: string;
      try { contents = readFileSync(fd, 'utf8'); }
      catch { throw new Error('Paper audit external head cannot be read.'); }
      try { decoded = JSON.parse(contents) as unknown; }
      catch { throw new Error('Paper audit external head cannot be parsed.'); }
    } finally {
      closeSync(fd);
    }
    if (!isRecord(decoded) || !isRecord(decoded.payload) || typeof decoded.mac !== 'string') {
      throw new Error('Paper audit external head is malformed.');
    }
    const payload = decoded.payload as unknown;
    if ((!isPaperAuditAnchor(payload) && !isLegacyPaperAuditAnchorV1(payload))
      || !constantTimeStringEqual(decoded.mac, paperAuditHmac(this.auditKey, canonicalJson(payload)))) {
      throw new Error('Paper audit external head failed authentication.');
    }
    if (isPaperAuditAnchor(payload)) return clonePaperAuditAnchor(payload);
    const legacyEvents = this.db.prepare('SELECT COUNT(*) AS count FROM kill_switch_events').get() as SqlRow | undefined;
    if (Number(legacyEvents?.count ?? 0) > 0) {
      throw new Error('Legacy unauthenticated kill-switch events are present. Refusing to bless them without an owner-approved migration.');
    }
    return {
      schemaVersion: 2,
      orders: Object.fromEntries(Object.entries(payload.orders).map(([orderId, head]) => [orderId, { sequence: head.sequence, headMac: head.headMac }])),
      killSwitch: { version: 0, headMac: KILL_SWITCH_AUDIT_GENESIS },
    };
  }

  private readPaperAuditCheckpointTransition(): PaperAuditCheckpointTransitionV1 | null {
    if (!this.auditAnchorPath || !this.auditAnchorDirectory || !this.auditAnchorFilename) return null;
    const prefix = this.auditAnchorFilename + '.pending.';
    let candidates: string[];
    try {
      candidates = readdirSync(this.auditAnchorDirectory).filter((name) => name.startsWith(prefix) && name.endsWith('.json'));
    } catch {
      throw new Error('Paper audit checkpoint transition directory cannot be read safely.');
    }
    if (candidates.length === 0) return null;
    if (candidates.length !== 1) throw new Error('Multiple staged paper-audit checkpoint transitions require manual recovery.');
    const filename = candidates[0]!;
    const transactionId = filename.slice(prefix.length, -'.json'.length);
    if (!/^[A-Za-z0-9_-]{24}$/.test(transactionId)) {
      throw new Error('Paper audit checkpoint transition filename is malformed.');
    }
    const path = resolve(this.auditAnchorDirectory, filename);
    let fd: number | undefined;
    let decoded: unknown;
    try {
      fd = openAuditSidecarRead(path);
      hardenAuditSidecarDescriptor(fd, 'Paper audit checkpoint transition');
      try { decoded = JSON.parse(readFileSync(fd, 'utf8')) as unknown; }
      catch { throw new Error('Paper audit checkpoint transition cannot be parsed.'); }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
      if ((error as NodeJS.ErrnoException).code === 'ELOOP') {
        throw new Error('Paper audit checkpoint transition must not be a symbolic link.');
      }
      throw error instanceof Error ? error : new Error('Paper audit checkpoint transition cannot be opened safely.');
    } finally {
      if (fd !== undefined) closeSync(fd);
    }
    if (!isRecord(decoded) || typeof decoded.mac !== 'string' || !isPaperAuditCheckpointTransitionV1(decoded.payload)
      || decoded.payload.transactionId !== transactionId
      || !constantTimeStringEqual(decoded.mac, paperAuditCheckpointTransitionMac(this.auditKey, decoded.payload))) {
      throw new Error('Paper audit checkpoint transition failed authentication or schema validation.');
    }
    return decoded.payload;
  }

  private preparePaperAuditCheckpointTransition(previous: PaperAuditAnchor, next: PaperAuditAnchor): PaperAuditCheckpointTransitionV1 | null {
    if (canonicalJson(previous) === canonicalJson(next)) return null;
    const transition: PaperAuditCheckpointTransitionV1 = {
      schemaVersion: 1,
      transactionId: randomBytes(18).toString('base64url'),
      previous: clonePaperAuditAnchor(previous),
      next: clonePaperAuditAnchor(next),
    };
    if (!this.auditAnchorPath) return transition;
    if (this.readPaperAuditCheckpointTransition()) {
      throw new Error('An earlier paper-audit checkpoint transition must be reconciled before writing another.');
    }
    const pendingPath = this.paperAuditCheckpointTransitionPath(transition.transactionId);
    const signed: SignedPaperAuditCheckpointTransitionV1 = {
      payload: transition,
      mac: paperAuditCheckpointTransitionMac(this.auditKey, transition),
    };
    let witnessPrepareAttempted = false;
    let witnessExpectedVersion: number | null = null;
    try {
      this.verifyPaperAuditCheckpointTransitionRows(transition);
      if (this.auditWitness) {
        const state = this.verifyPaperAuditWitnessHead(previous);
        witnessExpectedVersion = state.version;
      }
      this.writeAuthenticatedAuditSidecar(pendingPath, signed, 'Paper audit checkpoint transition');
      if (this.auditWitness) {
        witnessPrepareAttempted = true;
        const state = requestPaperAuditWitness(this.auditWitness, '/v1/prepare', {
          ledgerId: this.auditWitness.ledgerId,
          transactionId: transition.transactionId,
          expectedVersion: witnessExpectedVersion,
          previousHash: paperAuditWitnessAnchorHash(previous),
          nextHash: paperAuditWitnessAnchorHash(next),
        });
        if (!state.pending || state.pending.transactionId !== transition.transactionId
          || state.pending.previousHash !== paperAuditWitnessAnchorHash(previous)
          || state.pending.nextHash !== paperAuditWitnessAnchorHash(next)) {
          throw new Error('Independent paper-audit witness did not stage the requested transition.');
        }
      }
      // The local marker is durable before the remote prepare. After SQLite
      // COMMIT the remote witness is finalized before the local marker is cleared.
      this.writePaperAuditAnchor(next);
    } catch (error) {
      // Once a remote prepare may have reached the witness, retain the exact
      // local transition so restart can commit or abort it from durable SQLite.
      if (!witnessPrepareAttempted) {
        try {
          this.writePaperAuditAnchor(previous);
          this.clearPaperAuditCheckpointTransition(transition.transactionId);
        } catch { /* Preserve the signed marker if cleanup cannot be completed safely. */ }
      }
      throw error;
    }
    return transition;
  }

  private completePaperAuditCheckpointTransition(transition: PaperAuditCheckpointTransitionV1 | null, next: PaperAuditAnchor): void {
    if (!transition) return;
    if (!this.auditAnchorPath) {
      this.memoryAuditAnchor = clonePaperAuditAnchor(next);
      return;
    }
    if (this.auditWitness) {
      const state = requestPaperAuditWitness(this.auditWitness, '/v1/commit', {
        ledgerId: this.auditWitness.ledgerId, transactionId: transition.transactionId,
      });
      if (state.pending || state.headHash !== paperAuditWitnessAnchorHash(next)
        || state.lastTransactionId !== transition.transactionId) {
        throw new Error('Independent paper-audit witness did not finalize the committed transition.');
      }
    }
    this.clearPaperAuditCheckpointTransition(transition.transactionId);
  }

  private clearPaperAuditCheckpointTransition(transactionId: string): void {
    if (!this.auditAnchorPath || !this.auditAnchorDirectory) return;
    const pending = this.readPaperAuditCheckpointTransition();
    if (!pending || pending.transactionId !== transactionId) return;
    const path = this.paperAuditCheckpointTransitionPath(transactionId);
    try { unlinkSync(path); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return;
      throw error;
    }
    syncAuditDirectory(this.auditAnchorDirectory, 'Paper audit checkpoint transition directory');
  }

  private verifyPaperAuditCheckpointTransitionRows(transition: PaperAuditCheckpointTransitionV1): void {
    const { previous, next } = transition;
    for (const [orderId, newHead] of Object.entries(next.orders)) {
      const oldHead = previous.orders[orderId];
      if (oldHead && oldHead.sequence === newHead.sequence) continue;
      const row = this.db.prepare(
        'SELECT previous_mac, record_mac FROM paper_execution_audits WHERE order_id = ? AND sequence = ? LIMIT 1',
      ).get(orderId, newHead.sequence) as SqlRow | undefined;
      const expectedPrevious = oldHead?.headMac ?? PAPER_AUDIT_GENESIS;
      if (row?.previous_mac !== expectedPrevious || row.record_mac !== newHead.headMac) {
        throw new Error('Staged paper-audit checkpoint does not match the exact new audit row.');
      }
    }
    if (next.killSwitch.version !== previous.killSwitch.version) {
      const row = this.db.prepare(
        'SELECT previous_mac, event_mac FROM kill_switch_events WHERE version = ? LIMIT 1',
      ).get(next.killSwitch.version) as SqlRow | undefined;
      if (row?.previous_mac !== previous.killSwitch.headMac || row.event_mac !== next.killSwitch.headMac) {
        throw new Error('Staged paper-audit checkpoint does not match the exact new kill-switch event.');
      }
    }
    const previousBreakerHeads = previous.causalTriggerBreakerHeadsV1 ?? {};
    for (const [breakerKey, newHead] of Object.entries(next.causalTriggerBreakerHeadsV1 ?? {})) {
      const oldHead = previousBreakerHeads[breakerKey];
      if (oldHead && oldHead.sequence === newHead.sequence) continue;
      const row = this.db.prepare(`
        SELECT previous_mac,event_mac FROM causal_trigger_breaker_audits
        WHERE breaker_key=? AND sequence=? LIMIT 1
      `).get(breakerKey, newHead.sequence) as SqlRow | undefined;
      const expectedPrevious = oldHead?.headMac ?? PAPER_AUDIT_GENESIS;
      if (row?.previous_mac !== expectedPrevious || row.event_mac !== newHead.headMac) {
        throw new Error('Staged paper-audit checkpoint does not match the exact new causal trigger breaker audit row.');
      }
    }
  }

  private paperAuditCheckpointTransitionPath(transactionId: string): string {
    if (!this.auditAnchorPath) throw new Error('In-memory paper ledgers do not have checkpoint transition files.');
    return this.auditAnchorPath + '.pending.' + transactionId + '.json';
  }

  private writePaperAuditAnchor(anchor: PaperAuditAnchor): void {
    if (!this.auditAnchorPath) {
      this.memoryAuditAnchor = clonePaperAuditAnchor(anchor);
      return;
    }
    const envelope: SignedPaperAuditAnchor = { payload: anchor, mac: paperAuditHmac(this.auditKey, canonicalJson(anchor)) };
    this.writeAuthenticatedAuditSidecar(this.auditAnchorPath, envelope, 'Paper audit external head');
  }

  private writeAuthenticatedAuditSidecar(path: string, envelope: SignedPaperAuditAnchor | SignedPaperAuditCheckpointTransitionV1,
    label: string): void {
    const parent = dirname(path);
    mkdirSync(parent, { recursive: true, mode: 0o700 });
    const temporary = path + '.' + process.pid + '.' + randomBytes(8).toString('hex') + '.tmp';
    let fd: number | undefined;
    try {
      if (typeof constants.O_NOFOLLOW !== 'number') throw new Error(label + ' requires no-follow file creation support.');
      fd = openSync(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
      hardenAuditSidecarDescriptor(fd, label);
      const contents = Buffer.from(JSON.stringify(envelope), 'utf8');
      let offset = 0;
      while (offset < contents.length) offset += writeSync(fd, contents, offset, contents.length - offset);
      fsyncSync(fd);
      closeSync(fd);
      fd = undefined;
      renameSync(temporary, path);
      syncAuditDirectory(parent, label + ' directory');
    } catch (error) {
      if (fd !== undefined) closeSync(fd);
      try { unlinkSync(temporary); } catch { /* The rename or cleanup may already have completed. */ }
      throw error;
    }
  }

  private readVerifiedPaperExecutionAudits(orderId: string, suppliedAnchor?: PaperAuditAnchor): PaperExecutionAuditRecordV1[] {
    const anchor = suppliedAnchor ?? this.loadPaperAuditAnchor();
    const rows = this.db.prepare(`
      SELECT order_id, sequence, record_json, record_hash, previous_mac, record_mac
      FROM paper_execution_audits WHERE order_id = ? ORDER BY sequence
    `).all(orderId) as SqlRow[];
    let previousMac = PAPER_AUDIT_GENESIS;
    const records: PaperExecutionAuditRecordV1[] = [];
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index];
      const sequence = index + 1;
      if (!row || row.order_id !== orderId || Number(row.sequence) !== sequence
        || typeof row.record_json !== 'string' || typeof row.record_hash !== 'string'
        || typeof row.previous_mac !== 'string' || typeof row.record_mac !== 'string') {
        throw new Error('Paper execution audit chain has a missing, reordered, or incomplete row.');
      }
      const record = parseJson(row.record_json);
      const expectedMac = this.paperAuditRecordMac(orderId, sequence, previousMac, row.record_hash, row.record_json);
      if (!isPaperExecutionAuditRecordV1(record) || orderId !== 'paper:' + record.proposal.runId
        || sha256Base64Url(row.record_json) !== row.record_hash || row.previous_mac !== previousMac
        || !constantTimeStringEqual(row.record_mac, expectedMac)) {
        throw new Error('Paper execution audit failed its schema, chain, or authentication check.');
      }
      this.validatePaperAuditEffectClaims(orderId, record);
      records.push(record);
      previousMac = row.record_mac;
    }
    const head = anchor.orders[orderId];
    if (rows.length === 0 && head) throw new Error('Paper execution audit rows were removed after their external head was recorded.');
    if (rows.length > 0 && (!head || head.sequence !== rows.length || head.headMac !== previousMac)) {
      throw new Error('Paper execution audit chain does not match its external head.');
    }
    return records;
  }

  private validatePaperAuditEffectClaims(orderId: string, record: PaperExecutionAuditRecordV1): void {
    const orderRow = this.db.prepare('SELECT * FROM paper_orders WHERE order_id = ? LIMIT 1').get(orderId) as SqlRow | undefined;
    const triggerEffectRow = this.db.prepare('SELECT * FROM causal_trigger_effects WHERE order_id=?').get(orderId) as SqlRow | undefined;
    if (record.triggerEffect === undefined) {
      if (triggerEffectRow) throw new Error('A causal trigger effect exists without its authenticated paper-audit lineage.');
    } else {
      const effect = record.triggerEffect;
      const eventRow = this.db.prepare('SELECT event_sha256,root_trigger_id,source_provenance,source_sha256,event_json FROM causal_trigger_events WHERE trigger_id=?')
        .get(effect.triggerId) as SqlRow | undefined;
      let storedEvent: unknown;
      try { storedEvent = eventRow?.event_json ? JSON.parse(String(eventRow.event_json)) as unknown : null; } catch { storedEvent = null; }
      const storedEventClaims = isRecord(storedEvent) && isRecord(storedEvent.claims) ? storedEvent.claims : null;
      let storedEventSignatureValid = false;
      try {
        if (storedEventClaims && isRecord(storedEvent)) {
          storedEventSignatureValid = this.policyPublicKeyPem === null || (typeof storedEvent.signature === 'string'
            && verifySignature(null, Buffer.from(canonicalJson(storedEventClaims)), createPublicKey(this.policyPublicKeyPem), Buffer.from(storedEvent.signature, 'base64url')));
        }
      } catch { storedEventSignatureValid = false; }
      if (!triggerEffectRow || !eventRow) throw new Error('Paper audit causal lineage is missing its durable trigger event or effect row.');
      if (!storedEventSignatureValid) throw new Error('Stored trigger event signature no longer verifies against the policy issuer.');
      if (causalTriggerContextError({ version: 1, event: storedEvent, rootTriggerId: effect.rootTriggerId,
        parentEffectOrderId: effect.parentEffectOrderId ?? undefined, standingRuleRef: effect.standingRuleRef,
        policyEpoch: effect.policyEpoch }) !== null) throw new Error('Stored causal trigger context failed its schema check.');
      if (triggerEffectRow.trigger_id !== effect.triggerId || triggerEffectRow.root_trigger_id !== effect.rootTriggerId
        || triggerEffectRow.parent_effect_order_id !== effect.parentEffectOrderId
        || triggerEffectRow.standing_rule_ref !== effect.standingRuleRef || triggerEffectRow.policy_epoch !== effect.policyEpoch
        || triggerEffectRow.event_sha256 !== effect.eventSha256 || triggerEffectRow.scope_sha256 !== effect.scopeSha256
        || triggerEffectRow.audit_record_hash !== sha256Base64Url(JSON.stringify(record))) {
        throw new Error('Paper audit causal lineage does not match its append-only effect row.');
      }
      if (eventRow.event_sha256 !== effect.eventSha256 || eventRow.root_trigger_id !== effect.rootTriggerId
        || eventRow.source_provenance !== (storedEventClaims?.sourceProvenance ?? null)
        || eventRow.source_sha256 !== (storedEventClaims?.sourceSha256 ?? null)
        || sha256Base64Url(canonicalJson(storedEvent)) !== effect.eventSha256) {
        throw new Error('Paper audit causal lineage does not match the signed trigger event.');
      }
    }
    const commitEffectClaimed = record.audit.hops.some((hop) => hop.audience === 'paper-ledger'
      && hop.operation === 'order.commit.paper' && hop.sideEffects > 0);
    const cancelEffectClaimed = record.audit.hops.some((hop) => hop.audience === 'paper-ledger'
      && hop.operation === 'order.cancel.paper' && hop.sideEffects > 0);
    const commitOutcomeClaimsSuccess = record.kind === 'commit' && ['accepted', 'recovered'].includes(record.outcome);
    const cancelOutcomeClaimsSuccess = record.kind === 'cancel' && record.outcome === 'applied';
    const receipt = this.verifyPaperLedgerReceipt(orderId, record);
    if ((commitEffectClaimed || cancelEffectClaimed || commitOutcomeClaimsSuccess || cancelOutcomeClaimsSuccess)
      && !record.audit.requestHash) {
      throw new Error('Paper audit effect claim has no full request hash for exact receipt correlation.');
    }
    if ((commitEffectClaimed || cancelEffectClaimed || commitOutcomeClaimsSuccess || cancelOutcomeClaimsSuccess) && !receipt) {
      throw new Error('Paper audit effect claim has no independently verifiable signed paper-ledger receipt.');
    }
    if ((commitEffectClaimed || commitOutcomeClaimsSuccess || cancelEffectClaimed || cancelOutcomeClaimsSuccess) && !orderRow) {
      throw new Error('Paper audit claims a ledger effect without a matching authoritative paper order.');
    }
    if (receipt) {
      const claims = receipt.document.claims;
      if (commitEffectClaimed && (claims.action !== 'order.commit.paper' || claims.decision !== 'allow' || Number(claims.sideEffects) < 1)) {
        throw new Error('Paper audit commit effect does not match an allowing signed commit receipt.');
      }
      if (cancelEffectClaimed && (claims.action !== 'order.cancel.paper' || claims.decision !== 'allow' || Number(claims.sideEffects) < 1)) {
        throw new Error('Paper audit cancellation effect does not match an allowing signed cancellation receipt.');
      }
      if (commitOutcomeClaimsSuccess && (claims.decision !== 'allow'
        || (claims.action !== 'order.commit.paper' && claims.action !== 'order.lookup.paper'))) {
        throw new Error('Successful paper commit outcome is not backed by an allowing ledger receipt or recovery lookup.');
      }
      if (commitOutcomeClaimsSuccess && claims.action === 'order.lookup.paper'
        && (!isRecord(receipt.result) || receipt.result.found !== true)) {
        throw new Error('Recovered paper commit has no signed lookup confirming the order exists.');
      }
      if (cancelOutcomeClaimsSuccess && (claims.action !== 'order.cancel.paper' || claims.decision !== 'allow')) {
        throw new Error('Successful paper cancellation outcome is not backed by an allowing cancellation receipt.');
      }
    }
    if (orderRow) {
      const durableOrder = decodeOrder(orderRow);
      if (sha256Base64Url(canonicalJson(durableOrder.order)) !== durableOrder.orderHash) {
        throw new Error('Paper audit references a paper order whose stored order hash is invalid.');
      }
      const order = durableOrder.order;
      if (!isRecord(order) || order.market !== record.proposal.market || order.symbol !== record.proposal.symbol
        || order.side !== record.proposal.side || order.quantity !== record.proposal.quantity
        || order.orderType !== record.proposal.orderType
        || (record.proposal.orderType === 'market' ? null : order.limitPrice) !== record.proposal.limitPrice
        || (order.session ?? 'regular') !== record.proposal.session
        || (order.timeInForce === 'gtc' ? 'gtc' : 'day') !== record.proposal.timeInForce) {
        throw new Error('Paper audit proposal does not match the authoritative ledger order.');
      }
      const stableIntent = { ...order };
      delete stableIntent.referencePrice;
      delete stableIntent.estimatedNotionalUsd;
      if (sha256Base64Url(canonicalJson(stableIntent)) !== durableOrder.intentHash) {
        throw new Error('Paper ledger intent hash does not match its authoritative order fields.');
      }
      if ((cancelEffectClaimed || cancelOutcomeClaimsSuccess) && !durableOrder.cancelled) {
        throw new Error('Paper audit claims a cancellation that is absent from the authoritative order state.');
      }
    }
    if (cancelEffectClaimed || cancelOutcomeClaimsSuccess) {
      const orderHash = orderRow?.order_hash;
      if (typeof orderHash !== 'string') throw new Error('Paper audit cancellation has no authoritative order hash.');
    }
    if (receipt && orderRow) {
      const claims = receipt.document.claims;
      if (claims.orderHash !== undefined && claims.orderHash !== orderRow.order_hash) {
        throw new Error('Signed paper-ledger receipt is bound to a different order hash.');
      }
      const result = receipt.result;
      if (!isRecord(result)) throw new Error('Signed paper-ledger receipt result is malformed.');
      const receiptConfirmsOrder = (claims.action === 'order.commit.paper' && result.accepted === true)
        || (claims.action === 'order.lookup.paper' && result.found === true)
        || (claims.action === 'order.cancel.paper' && result.accepted === true && result.cancelled === true);
      if (receiptConfirmsOrder && result.orderId !== orderId) {
        throw new Error('Signed paper-ledger receipt result is not bound to the audited order.');
      }
      if (cancelEffectClaimed || cancelOutcomeClaimsSuccess) {
        const cancellationIdempotencyKey = result.idempotencyKey;
        if (typeof cancellationIdempotencyKey !== 'string' || !cancellationIdempotencyKey || cancellationIdempotencyKey.length > 256) {
          throw new Error('Signed cancellation receipt has no bounded idempotency key.');
        }
        if (typeof orderRow.order_hash !== 'string') throw new Error('Paper audit cancellation has no authoritative order hash.');
        const cancellation = this.db.prepare('SELECT 1 AS present FROM paper_cancellations WHERE idempotency_key = ? AND order_id = ? AND order_hash = ? LIMIT 1')
          .get(cancellationIdempotencyKey, orderId, orderRow.order_hash) as SqlRow | undefined;
        if (!cancellation) throw new Error('Paper audit claims a cancellation without its matching idempotency record.');
      }
      if ((claims.action === 'order.commit.paper' && result.accepted === true)
        || (claims.action === 'order.lookup.paper' && result.found === true)) {
        if (!isRecord(result.order) || sha256Base64Url(canonicalJson(result.order)) !== orderRow.order_hash) {
          throw new Error('Signed paper-ledger receipt does not carry the authoritative order intent.');
        }
        const durableOrder = decodeOrder(orderRow);
        if (canonicalJson(result.ledgerBinding) !== canonicalJson(durableOrder.ledgerBinding)) {
          throw new Error('Signed paper-ledger receipt does not match the durable budget and idempotency binding.');
        }
        for (const field of ['execution', 'marketQuote', 'marketQuoteResult', 'marketQuoteReceipt'] as const) {
          if (canonicalJson(result[field]) !== canonicalJson(durableOrder[field])) {
            throw new Error('Signed paper-ledger receipt does not match the durable ' + field + ' record.');
          }
        }
      }
    }
  }

  private verifyPaperLedgerReceipt(orderId: string, record: PaperExecutionAuditRecordV1): PaperLedgerReceiptEvidence | null {
    const evidenceValue = record.audit.paperLedgerReceipt as unknown;
    if (evidenceValue === undefined) return null;
    if (!isPaperLedgerReceiptEvidence(evidenceValue)) throw new Error('Paper audit receipt evidence is malformed.');
    const { signerPublicKey, document, result } = evidenceValue;
    const claims = document.claims;
    if (claims.version !== 1 || claims.signer !== 'paper-ledger' || claims.resource !== orderId
      || !['order.commit.paper', 'order.cancel.paper', 'order.lookup.paper'].includes(String(claims.action))
      || (claims.decision !== 'allow' && claims.decision !== 'block')
      || typeof claims.taskId !== 'string' || typeof claims.requestHash !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(claims.requestHash)
      || typeof claims.handlerInvoked !== 'boolean' || !Number.isSafeInteger(claims.sideEffects) || Number(claims.sideEffects) < 0
      || typeof claims.resultHash !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(claims.resultHash)
      || !['trusted-control', 'untrusted-data', 'none'].includes(String(claims.trust))
      || typeof claims.reason !== 'string' || typeof claims.replay !== 'boolean' || !Number.isSafeInteger(claims.createdAt)
      || claims.resultHash !== sha256Base64Url(canonicalJson(result))) {
      throw new Error('Paper audit receipt claims do not match the retained signed result.');
    }
    if (claims.action !== 'order.lookup.paper') {
      if (record.audit.requestHash ? claims.requestHash !== record.audit.requestHash
        : claims.taskId === record.audit.taskId && !claims.requestHash.startsWith(record.audit.requestHashPrefix)) {
        throw new Error('Paper audit receipt request does not match the execution trace.');
      }
    }
    const matchingHop = record.audit.hops.some((hop) => hop.audience === 'paper-ledger'
      && hop.operation === claims.action && hop.resource === orderId && hop.decision === claims.decision
      && hop.receiptVerified && hop.handlerInvoked === claims.handlerInvoked && hop.sideEffects === claims.sideEffects);
    if (!matchingHop) throw new Error('Paper audit receipt does not match any verified paper-ledger hop.');
    try {
      const key = createPublicKey(signerPublicKey);
      if (!verifySignature(null, Buffer.from(canonicalJson(claims), 'utf8'), key, Buffer.from(document.signature, 'base64url'))) {
        throw new Error('invalid signature');
      }
    } catch {
      throw new Error('Paper audit receipt signature could not be verified.');
    }
    return evidenceValue;
  }

  private paperAuditRecordMac(orderId: string, sequence: number, previousMac: string, recordHash: string, recordJson: string): string {
    return paperAuditHmac(this.auditKey, `${orderId}\n${sequence}\n${previousMac}\n${recordHash}\n${recordJson}`);
  }

  private getPaperAuditMac(orderId: string, sequence: number): string {
    const row = this.db.prepare('SELECT record_mac FROM paper_execution_audits WHERE order_id = ? AND sequence = ?')
      .get(orderId, sequence) as SqlRow | undefined;
    if (typeof row?.record_mac !== 'string') throw new Error('Paper execution audit chain predecessor is missing.');
    return row.record_mac;
  }

  private requireAuthenticatedPaperOrder(row: SqlRow): DurablePaperOrder {
    const order = decodeOrder(row);
    if (typeof row.budget_key !== 'string') throw new Error('Durable paper-order namespace is malformed.');
    if (!row.budget_key.startsWith('synthetic-demo-account:')) return order;
    const records = this.readVerifiedPaperExecutionAudits(order.orderId);
    if (!records.some((record) => record.kind === 'commit'
      && (record.outcome === 'accepted' || record.outcome === 'recovered'))) {
      throw new Error('Durable paper order is not linked to an authenticated, receipt-backed commit audit.');
    }
    return order;
  }

  /** Caller must hold the SQLite write transaction. */
  private recordArenaC1DispatchForRevocationInTransaction(authorizationId: string, nowMs: number): boolean {
    const row = this.db.prepare('SELECT authorization_id,idempotency_key,order_id,order_hash,expires_at_ms,'
      + 'authorization_json,state,result_json FROM arena_c1_dispatch_authorizations WHERE authorization_id=?')
      .get(authorizationId) as SqlRow | undefined;
    if (!row || row.authorization_id !== authorizationId || typeof row.authorization_json !== 'string'
      || typeof row.idempotency_key !== 'string' || typeof row.order_id !== 'string'
      || typeof row.order_hash !== 'string' || !/^[a-f0-9]{64}$/.test(row.order_hash)
      || !Number.isSafeInteger(row.expires_at_ms) || !['accepted', 'unknown'].includes(String(row.state))) return false;
    let authorization: unknown;
    try { authorization = JSON.parse(row.authorization_json) as unknown; } catch { return false; }
    if (!isRecord(authorization) || canonicalJson(authorization) !== row.authorization_json
      || authorization.authorization_id !== authorizationId || authorization.venue !== 'binance-spot-testnet'
      || authorization.ledger_row_ref !== authorizationId || authorization.receiver_decision !== 'allow'
      || authorization.lock2_decision !== 'allow'
      || authorization.mandate_id !== 'MANDATE-C1' || typeof authorization.mandate_version !== 'string'
      || !/^[0-9]+\.[0-9]+\.[0-9]+$/.test(authorization.mandate_version)
      || authorization.order_id !== row.order_id || authorization.order_hash !== row.order_hash
      || authorization.idempotency_key !== row.idempotency_key || authorization.client_order_id !== row.idempotency_key
      || !/^ogc1r?_[a-f0-9]{24}$/.test(String(authorization.client_order_id))
      || !['BTCUSDT', 'ETHUSDT', 'BNBUSDT'].includes(String(authorization.symbol))
      || !['BUY', 'SELL'].includes(String(authorization.side)) || authorization.type !== 'LIMIT'
      || !['IOC', 'FOK'].includes(String(authorization.time_in_force))
      || authorization.quantity_scale !== 100_000_000 || authorization.price_scale !== 100
      || authorization.currency !== 'USDT' || authorization.currency_scale !== 100
      || !Number.isSafeInteger(authorization.quantity_minor) || Number(authorization.quantity_minor) <= 0
      || !Number.isSafeInteger(authorization.price_minor) || Number(authorization.price_minor) <= 0
      || !Number.isSafeInteger(authorization.notional_minor) || Number(authorization.notional_minor) <= 0
      || !Number.isSafeInteger(authorization.expires_at_ms) || authorization.expires_at_ms !== row.expires_at_ms
      || typeof authorization.quote_receipt_hash !== 'string' || !/^[a-f0-9]{64}$/.test(authorization.quote_receipt_hash)
      || authorization.receiver_receipt_ref !== authorization.quote_receipt_hash
      || typeof authorization.lock2_receipt_ref !== 'string' || !/^[a-f0-9]{64}$/.test(authorization.lock2_receipt_ref)) return false;
    const action = {
      venue: authorization.venue, mandate_id: authorization.mandate_id, mandate_version: authorization.mandate_version,
      order_id: authorization.order_id, idempotency_key: authorization.idempotency_key,
      client_order_id: authorization.client_order_id, symbol: authorization.symbol, side: authorization.side,
      type: authorization.type, time_in_force: authorization.time_in_force, quantity_minor: authorization.quantity_minor,
      quantity_scale: authorization.quantity_scale, price_minor: authorization.price_minor, price_scale: authorization.price_scale,
      notional_minor: authorization.notional_minor, currency: authorization.currency, currency_scale: authorization.currency_scale,
      expires_at_ms: authorization.expires_at_ms, quote_receipt_hash: authorization.quote_receipt_hash,
    };
    if (createHash('sha256').update(canonicalJson(action)).digest('hex') !== authorization.order_hash) return false;
    const mandateHash = sha256Base64Url(canonicalJson({
      domain: 'orderguard-arena-mandate-v1', mandateId: authorization.mandate_id, version: authorization.mandate_version,
    }));
    const orderJson = row.authorization_json;
    const orderHash = sha256Base64Url(orderJson);
    let venueOrderId: string | null = null;
    if (typeof row.result_json === 'string') {
      try {
        const result = JSON.parse(row.result_json) as unknown;
        if (isRecord(result) && isRecord(result.reconciliation)
          && result.reconciliation.found === true && result.reconciliation.mismatch === false
          && result.reconciliation.venue === 'binance-spot-testnet'
          && result.reconciliation.client_order_id === authorization.client_order_id
          && typeof result.reconciliation.venue_order_id === 'string'
          && /^[A-Za-z0-9_-]{1,180}$/.test(result.reconciliation.venue_order_id)) {
          venueOrderId = result.reconciliation.venue_order_id;
        }
      } catch { /* An absent identity remains unknown and must be reconciled by client ID. */ }
    }
    const dispatchState = row.state === 'accepted' && venueOrderId ? 'accepted' : 'unknown';
    const orderId = String(authorization.order_id);
    const existing = this.db.prepare('SELECT * FROM venue_mandate_orders WHERE venue=? AND mandate_id=? AND order_id=?')
      .get('binance-spot-testnet', 'MANDATE-C1', orderId) as SqlRow | undefined;
    if (existing) {
      const same = existing.mandate_hash === mandateHash && existing.idempotency_key === row.idempotency_key
        && existing.order_hash === orderHash && existing.order_quantity_atoms === authorization.quantity_minor
        && existing.client_order_id === authorization.client_order_id && existing.order_json === orderJson
        && (existing.venue_order_id === venueOrderId || existing.venue_order_id === null || venueOrderId === null);
      if (!same) {
        this.db.prepare("UPDATE venue_mandate_orders SET state='blocked',updated_at_ms=? WHERE venue=? AND mandate_id=? AND order_id=?")
          .run(nowMs, 'binance-spot-testnet', 'MANDATE-C1', orderId);
        this.db.prepare("UPDATE mandate_cancellation_outbox SET state='blocked',lease_until_ms=NULL,updated_at_ms=? "
          + "WHERE venue='binance-spot-testnet' AND mandate_id='MANDATE-C1' AND order_id=? "
          + "AND state IN ('pending','retry','dispatching')")
          .run(nowMs, orderId);
        return false;
      }
      if (existing.venue_order_id === null && venueOrderId !== null) {
        this.db.prepare('UPDATE venue_mandate_orders SET venue_order_id=?,state=?,updated_at_ms=? '
          + 'WHERE venue=? AND mandate_id=? AND order_id=?')
          .run(venueOrderId, existing.state === 'unknown' && dispatchState === 'accepted' ? 'resident' : String(existing.state),
            nowMs, 'binance-spot-testnet', 'MANDATE-C1', orderId);
      }
    } else {
      this.db.prepare('INSERT INTO venue_mandate_orders '
        + '(venue,mandate_id,mandate_hash,idempotency_key,order_id,order_hash,order_quantity_atoms,client_order_id,venue_order_id,order_json,state,created_at_ms,updated_at_ms) '
        + 'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)').run('binance-spot-testnet', 'MANDATE-C1', mandateHash,
        row.idempotency_key, orderId, orderHash, Number(authorization.quantity_minor), String(authorization.client_order_id),
        venueOrderId, orderJson, dispatchState === 'accepted' ? 'resident' : 'unknown', nowMs, nowMs);
    }
    if (Number(row.expires_at_ms) <= nowMs) {
      this.enqueueVenueMandateOrderCancellation('binance-spot-testnet', 'MANDATE-C1', orderId, 'expired', nowMs);
    } else {
      const control = this.db.prepare('SELECT state FROM arena_c1_mandate_control WHERE singleton=1').get() as SqlRow | undefined;
      if (!control || control.state !== 'active') {
        this.enqueueVenueMandateOrderCancellation('binance-spot-testnet', 'MANDATE-C1', orderId, 'revoked', nowMs);
      }
    }
    return true;
  }

  private enqueueFutuMandateCancellationRows(mandateId: string, nowMs: number): void {
    const rows = this.db.prepare("SELECT a.mandate_id,a.mandate_hash,a.idempotency_key,a.order_id,a.order_hash,"
      + "d.remark,d.broker_order_id,d.state AS dispatch_state,p.order_json,p.cancelled "
      + 'FROM futu_m1_dispatch_authorizations a JOIN futu_simulate_dispatches d ON d.idempotency_key=a.idempotency_key '
      + 'JOIN paper_orders p ON p.idempotency_key=a.idempotency_key AND p.order_id=a.order_id '
      + "WHERE a.mandate_id=? AND d.state IN ('dispatching','unknown','conflict','accepted') AND p.cancelled=0 "
      + 'ORDER BY p.created_at,a.order_id').all(mandateId) as SqlRow[];
    for (const row of rows) {
      if (row.mandate_id !== mandateId || typeof row.mandate_hash !== 'string'
        || !/^[A-Za-z0-9_-]{43}$/.test(row.mandate_hash)
        || typeof row.idempotency_key !== 'string' || typeof row.order_id !== 'string'
        || typeof row.order_hash !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(row.order_hash)
        || typeof row.remark !== 'string' || !row.remark || row.remark.length > 180
        || typeof row.order_json !== 'string' || row.order_json.length > 100_000
        || (row.broker_order_id !== null && !isSafeVenueOrderId(row.broker_order_id))) continue;
      let orderValue: unknown;
      try { orderValue = JSON.parse(row.order_json) as unknown; } catch { continue; }
      if (!isRecord(orderValue) || !Number.isSafeInteger(orderValue.quantity) || Number(orderValue.quantity) <= 0) continue;
      const orderQuantityAtoms = Number(orderValue.quantity);
      const residentState = row.dispatch_state === 'accepted' ? 'resident' : 'unknown';
      const existing = this.db.prepare('SELECT * FROM venue_mandate_orders WHERE venue=? AND mandate_id=? AND order_id=?')
        .get('futu-simulate', mandateId, row.order_id) as SqlRow | undefined;
      if (!existing) {
        this.db.prepare('INSERT INTO venue_mandate_orders '
          + '(venue,mandate_id,mandate_hash,idempotency_key,order_id,order_hash,order_quantity_atoms,client_order_id,venue_order_id,order_json,state,created_at_ms,updated_at_ms) '
          + 'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)').run('futu-simulate', mandateId, row.mandate_hash,
          row.idempotency_key, row.order_id, row.order_hash, orderQuantityAtoms, row.remark, row.broker_order_id,
          row.order_json, residentState, nowMs, nowMs);
      } else if (existing.mandate_hash !== row.mandate_hash || existing.idempotency_key !== row.idempotency_key
        || existing.order_hash !== row.order_hash || existing.order_quantity_atoms !== orderQuantityAtoms
        || existing.client_order_id !== row.remark
        || existing.order_json !== row.order_json
        || (existing.venue_order_id !== null && row.broker_order_id !== null && existing.venue_order_id !== row.broker_order_id)) {
        this.db.prepare("UPDATE venue_mandate_orders SET state='blocked',updated_at_ms=? WHERE venue=? AND mandate_id=? AND order_id=?")
          .run(nowMs, 'futu-simulate', mandateId, row.order_id);
        this.db.prepare("UPDATE mandate_cancellation_outbox SET state='blocked',lease_until_ms=NULL,updated_at_ms=? "
          + "WHERE venue='futu-simulate' AND mandate_id=? AND order_id=? AND state IN ('pending','retry','dispatching')")
          .run(nowMs, mandateId, row.order_id);
        continue;
      } else if (existing.venue_order_id === null && row.broker_order_id !== null) {
        this.db.prepare('UPDATE venue_mandate_orders SET venue_order_id=?,state=?,updated_at_ms=? WHERE venue=? AND mandate_id=? AND order_id=?')
          .run(row.broker_order_id, residentState, nowMs, 'futu-simulate', mandateId, row.order_id);
      }
    }
  }

  private enqueueAllMandateCancellations(mandateId: string, reason: 'revoked' | 'expired', nowMs: number): number {
    const rows = this.db.prepare("SELECT venue,order_id FROM venue_mandate_orders WHERE mandate_id=? "
      + "AND state IN ('resident','unknown') ORDER BY venue,order_id").all(mandateId) as SqlRow[];
    let queued = 0;
    for (const row of rows) {
      if (typeof row.venue === 'string' && typeof row.order_id === 'string'
        && this.enqueueVenueMandateOrderCancellation(row.venue, mandateId, row.order_id, reason, nowMs)) queued += 1;
    }
    return queued;
  }

  /** Caller must hold the SQLite write transaction. */
  private finalizeDrainedHumanMandateRevocation(mandateId: string, nowMs: number): boolean {
    const mandate = this.db.prepare('SELECT revoke_requested_at FROM human_mandates WHERE mandate_id=?')
      .get(mandateId) as SqlRow | undefined;
    if (!mandate || mandate.revoke_requested_at === null || mandate.revoke_requested_at === undefined) return false;
    const liveVenueOrder = this.db.prepare("SELECT 1 AS active FROM venue_mandate_orders WHERE mandate_id=? "
      + "AND state IN ('resident','unknown','blocked') LIMIT 1").get(mandateId) as SqlRow | undefined;
    const unresolvedCancellation = this.db.prepare("SELECT 1 AS active FROM mandate_cancellation_outbox WHERE mandate_id=? "
      + "AND state IN ('pending','dispatching','retry','blocked') LIMIT 1").get(mandateId) as SqlRow | undefined;
    const inFlightDispatch = this.db.prepare("SELECT 1 AS active FROM futu_m1_dispatch_authorizations a "
      + "JOIN futu_simulate_dispatches d ON d.idempotency_key=a.idempotency_key "
      + "WHERE a.mandate_id=? AND d.state IN ('dispatching','unknown','conflict') LIMIT 1")
      .get(mandateId) as SqlRow | undefined;
    // An accepted dispatch is no longer transport-in-flight, but its venue order
    // still must be indexed and reconciled before a revoke can be called drained.
    const unreconciledAcceptedDispatch = this.db.prepare("SELECT 1 AS active FROM futu_m1_dispatch_authorizations a "
      + "JOIN futu_simulate_dispatches d ON d.idempotency_key=a.idempotency_key "
      + "WHERE a.mandate_id=? AND d.state='accepted' AND NOT EXISTS ("
      + "SELECT 1 FROM venue_mandate_orders v JOIN mandate_cancellation_outbox c "
      + "ON c.venue=v.venue AND c.mandate_id=v.mandate_id AND c.order_id=v.order_id "
      + "WHERE v.venue='futu-simulate' AND v.mandate_id=a.mandate_id AND v.idempotency_key=a.idempotency_key "
      + "AND v.order_id=a.order_id AND v.order_hash=a.order_hash AND v.state IN ('cancelled','filled','expired') "
      + "AND c.idempotency_key=a.idempotency_key AND c.order_hash=a.order_hash AND c.state IN ('cancelled','filled','expired') "
      + "AND c.state=v.state) LIMIT 1")
      .get(mandateId) as SqlRow | undefined;
    if (liveVenueOrder || unresolvedCancellation || inFlightDispatch || unreconciledAcceptedDispatch) return false;
    const result = this.db.prepare('UPDATE human_mandates SET revoked_at=COALESCE(revoked_at,?),revoke_requested_at=NULL '
      + 'WHERE mandate_id=? AND revoke_requested_at IS NOT NULL').run(nowMs, mandateId);
    return result.changes === 1;
  }

  /** Caller must hold the SQLite write transaction. */
  private finalizeDrainedArenaC1MandateRevocation(nowMs: number): boolean {
    const control = this.db.prepare('SELECT state FROM arena_c1_mandate_control WHERE singleton=1')
      .get() as SqlRow | undefined;
    if (control?.state !== 'revoking') return control?.state === 'revoked';
    const liveVenueOrder = this.db.prepare("SELECT 1 AS active FROM venue_mandate_orders "
      + "WHERE venue='binance-spot-testnet' AND mandate_id='MANDATE-C1' "
      + "AND state IN ('resident','unknown','blocked') LIMIT 1").get() as SqlRow | undefined;
    const unresolvedCancellation = this.db.prepare("SELECT 1 AS active FROM mandate_cancellation_outbox "
      + "WHERE venue='binance-spot-testnet' AND mandate_id='MANDATE-C1' "
      + "AND state IN ('pending','dispatching','retry','blocked') LIMIT 1").get() as SqlRow | undefined;
    const inFlightDispatch = this.db.prepare("SELECT 1 AS active FROM arena_c1_dispatch_authorizations "
      + "WHERE state='dispatching' LIMIT 1").get() as SqlRow | undefined;
    const unreconciledDispatch = this.db.prepare("SELECT 1 AS active FROM arena_c1_dispatch_authorizations a "
      + "WHERE a.state IN ('accepted','unknown') AND NOT EXISTS ("
      + "SELECT 1 FROM venue_mandate_orders v JOIN mandate_cancellation_outbox c "
      + "ON c.venue=v.venue AND c.mandate_id=v.mandate_id AND c.order_id=v.order_id "
      + "WHERE v.venue='binance-spot-testnet' AND v.mandate_id='MANDATE-C1' "
      + "AND v.idempotency_key=a.idempotency_key AND v.order_id=a.order_id "
      + "AND v.state IN ('cancelled','filled','expired') AND c.idempotency_key=a.idempotency_key "
      + "AND c.order_hash=v.order_hash AND c.state IN ('cancelled','filled','expired') AND c.state=v.state) LIMIT 1")
      .get() as SqlRow | undefined;
    if (liveVenueOrder || unresolvedCancellation || inFlightDispatch || unreconciledDispatch) return false;
    const result = this.db.prepare("UPDATE arena_c1_mandate_control SET state='revoked',revoked_at_ms=?,updated_at_ms=? "
      + "WHERE singleton=1 AND state='revoking'").run(nowMs, nowMs);
    return result.changes === 1;
  }

  private enqueueVenueMandateOrderCancellation(venue: string, mandateId: string, orderId: string,
    reason: 'revoked' | 'expired', nowMs: number): boolean {
    const binding = this.db.prepare('SELECT * FROM venue_mandate_orders WHERE venue=? AND mandate_id=? AND order_id=?')
      .get(venue, mandateId, orderId) as SqlRow | undefined;
    if (!binding || !['resident', 'unknown'].includes(String(binding.state))) return false;
    const bindingVenueOrderId = typeof binding.venue_order_id === 'string' ? binding.venue_order_id : null;
    const outboxId = 'cancel-' + sha256Base64Url(canonicalJson({
      domain: 'orderguard-mandate-cancel-outbox-v1', venue, mandateId, orderId,
    }));
    const existing = this.db.prepare('SELECT * FROM mandate_cancellation_outbox WHERE venue=? AND mandate_id=? AND order_id=?')
      .get(venue, mandateId, orderId) as SqlRow | undefined;
    if (existing) {
      const same = existing.outbox_id === outboxId && existing.mandate_hash === binding.mandate_hash
        && existing.idempotency_key === binding.idempotency_key && existing.order_hash === binding.order_hash
        && existing.order_quantity_atoms === binding.order_quantity_atoms
        && existing.client_order_id === binding.client_order_id && existing.order_json === binding.order_json
        && (existing.venue_order_id === bindingVenueOrderId || existing.venue_order_id === null || bindingVenueOrderId === null);
      if (!same) {
        this.db.prepare("UPDATE mandate_cancellation_outbox SET state='blocked',updated_at_ms=? WHERE outbox_id=?")
          .run(nowMs, String(existing.outbox_id));
        return false;
      }
      if (existing.venue_order_id === null && bindingVenueOrderId !== null) {
        this.db.prepare('UPDATE mandate_cancellation_outbox SET venue_order_id=?,updated_at_ms=? WHERE outbox_id=?')
          .run(bindingVenueOrderId, nowMs, outboxId);
      }
      return true;
    }
    this.db.prepare('INSERT INTO mandate_cancellation_outbox '
      + '(outbox_id,venue,mandate_id,mandate_hash,idempotency_key,order_id,order_hash,order_quantity_atoms,client_order_id,venue_order_id,order_json,reason,state,attempt_count,lease_until_ms,next_attempt_at_ms,last_observation_json,created_at_ms,updated_at_ms) '
      + "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending',0,NULL,0,NULL,?,?)").run(outboxId, venue, mandateId,
      String(binding.mandate_hash), String(binding.idempotency_key), orderId, String(binding.order_hash),
      Number(binding.order_quantity_atoms),
      String(binding.client_order_id), bindingVenueOrderId, String(binding.order_json), reason, nowMs, nowMs);
    return true;
  }

  private cancellationOutboxFromRow(row: SqlRow | undefined): MandateCancellationOutboxItemV1 | null {
    if (!row || typeof row.outbox_id !== 'string' || typeof row.venue !== 'string'
      || typeof row.mandate_id !== 'string' || typeof row.mandate_hash !== 'string'
      || typeof row.idempotency_key !== 'string' || typeof row.order_id !== 'string'
      || typeof row.order_hash !== 'string' || !Number.isSafeInteger(row.order_quantity_atoms)
      || Number(row.order_quantity_atoms) <= 0 || typeof row.client_order_id !== 'string'
      || (row.venue_order_id !== null && typeof row.venue_order_id !== 'string')
      || typeof row.order_json !== 'string' || (row.reason !== 'revoked' && row.reason !== 'expired')
      || !['pending','dispatching','retry','cancelled','filled','expired','blocked'].includes(String(row.state))
      || !Number.isSafeInteger(row.attempt_count) || !Number.isSafeInteger(row.next_attempt_at_ms)
      || (row.lease_until_ms !== null && !Number.isSafeInteger(row.lease_until_ms))) return null;
    return { outboxId: row.outbox_id, venue: row.venue, mandateId: row.mandate_id, mandateHash: row.mandate_hash,
      idempotencyKey: row.idempotency_key, orderId: row.order_id, orderHash: row.order_hash,
      orderQuantityAtoms: Number(row.order_quantity_atoms),
      clientOrderId: row.client_order_id, venueOrderId: row.venue_order_id as string | null,
      orderJson: row.order_json, reason: row.reason, state: row.state as MandateCancellationOutboxItemV1['state'],
      attemptCount: Number(row.attempt_count), leaseUntilMs: row.lease_until_ms as number | null,
      nextAttemptAtMs: Number(row.next_attempt_at_ms) };
  }

  private readByIdempotencyKey(idempotencyKey: string): DurablePaperOrder | null {
    const row = this.db.prepare('SELECT * FROM paper_orders WHERE idempotency_key = ?').get(idempotencyKey) as SqlRow | undefined;
    return row ? this.requireAuthenticatedPaperOrder(row) : null;
  }

  private readByOrderId(orderId: string): DurablePaperOrder | null {
    const row = this.db.prepare('SELECT * FROM paper_orders WHERE order_id = ?').get(orderId) as SqlRow | undefined;
    return row ? this.requireAuthenticatedPaperOrder(row) : null;
  }

  private pruneFutuProposalConfirmations(nowMs: number): void {
    this.db.prepare("DELETE FROM futu_proposal_confirmations WHERE phase='prepared' AND expires_at_ms<=?")
      .run(nowMs);
    this.db.prepare("DELETE FROM futu_proposal_confirmations WHERE phase='processing' AND expires_at_ms<=? AND lease_until_ms<=?")
      .run(nowMs, nowMs);
    const completed = this.db.prepare("SELECT token_hash,payload_json FROM futu_proposal_confirmations "
      + "WHERE phase='complete' AND expires_at_ms<=?").all(nowMs) as SqlRow[];
    for (const row of completed) {
      if (typeof row.token_hash !== 'string' || typeof row.payload_json !== 'string') continue;
      let payload: unknown;
      try { payload = JSON.parse(row.payload_json) as unknown; } catch { payload = null; }
      const cachedResponse = isRecord(payload) && isRecord(payload.cachedResponse) ? payload.cachedResponse : null;
      if (cachedResponse?.dispatch_attempted !== true) {
        this.db.prepare("DELETE FROM futu_proposal_confirmations WHERE token_hash=? AND phase='complete'")
          .run(row.token_hash);
      }
    }
  }

  private rollback(): void {
    try { this.db.exec('ROLLBACK'); } catch { /* Preserve the original transaction error. */ }
  }

  private backfillUsdBudgetMinorUnits(): void {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const rows = this.db.prepare(
        "SELECT order_id, order_json, market_quote_json FROM paper_orders WHERE budget_currency = 'USD' AND budget_notional_minor = 0",
      ).all() as SqlRow[];
      const update = this.db.prepare(
        "UPDATE paper_orders SET budget_notional_minor = ?, budget_notional_usd = ? WHERE order_id = ? AND budget_currency = 'USD' AND budget_notional_minor = 0",
      );
      for (const row of rows) {
        if (typeof row.order_id !== 'string' || !row.order_id) throw new Error('A legacy USD paper order is missing its durable ID.');
        const candidate = {
          order: parseJson(row.order_json),
          marketQuote: parseJson(row.market_quote_json),
        } as DurablePaperOrder;
        const amountMinor = calculateNotionalUsdMinor(candidate);
        update.run(amountMinor, amountMinor / 100, row.order_id);
      }
      this.db.exec('COMMIT');
    } catch (error) {
      this.rollback();
      throw error;
    }
  }

  private ensureColumn(table: string, name: string, definition: string): void {
    // Concurrent cold starts can both observe the same old schema. Serialize the
    // check-and-alter so the later process re-reads the schema after the first
    // migration commits instead of attempting the same ALTER TABLE.
    try {
      this.db.exec('BEGIN IMMEDIATE');
      const rows = this.db.prepare('PRAGMA table_info(' + table + ')').all() as SqlRow[];
      if (!rows.some((row) => row.name === name)) {
        this.db.exec('ALTER TABLE ' + table + ' ADD COLUMN ' + name + ' ' + definition);
      }
      this.db.exec('COMMIT');
    } catch (error) {
      this.rollback();
      throw error;
    }
  }
}

function validateCommitControls(controls: PaperCommitControls): void {
  const hasUsdBudget = typeof controls?.maxNotionalUsd === 'number' && Number.isFinite(controls.maxNotionalUsd) && controls.maxNotionalUsd > 0;
  const hasHkdBudget = controls?.maxNotionalAmount?.currency === 'HKD'
    && Number.isSafeInteger(controls.maxNotionalAmount.amount_minor) && controls.maxNotionalAmount.amount_minor > 0
    && Number.isSafeInteger(controls.ledgerConversion?.numerator) && Number.isSafeInteger(controls.ledgerConversion?.denominator)
    && controls.ledgerConversion?.numerator === 16 && controls.ledgerConversion?.denominator === 125;
  const validMandate = controls?.mandate === undefined || (
    /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(controls.mandate.id)
    && /^[A-Za-z0-9_-]{43}$/.test(controls.mandate.hash)
    && Number.isSafeInteger(controls.mandate.maxOrders) && controls.mandate.maxOrders > 0 && controls.mandate.maxOrders <= 100
    && Number.isFinite(controls.mandate.maxSessionNotionalUsd) && controls.mandate.maxSessionNotionalUsd > 0
    && (controls.mandate.triggerScopeV1 === undefined || triggerScopeError(controls.mandate.triggerScopeV1) === null)
  );
  const validTriggerGuard = controls?.triggerGuard === undefined || Boolean(
    controls.triggerGuard.authorityKind === 'synthetic-policy' ? controls.mandate === undefined
      : controls.triggerGuard.authorityKind === 'user-signed' && controls.mandate?.triggerScopeV1
        && controls.triggerGuard.mandateId === controls.mandate.id
        && controls.triggerGuard.mandateHash === controls.mandate.hash
        && canonicalJson(controls.triggerGuard.scope) === canonicalJson(controls.mandate.triggerScopeV1)
  ) && (controls?.triggerGuard === undefined || causalTriggerContextError(controls.triggerGuard.context) === null)
    && (controls?.triggerGuard === undefined || triggerScopeError(controls.triggerGuard.scope) === null);
  if (!controls || typeof controls.capabilityJti !== 'string' || !controls.capabilityJti || controls.capabilityJti.length > 128
    || typeof controls.budgetKey !== 'string' || !controls.budgetKey || controls.budgetKey.length > 256
    || (controls.secondLockActionHash !== undefined && !/^[A-Za-z0-9_-]{43}$/.test(controls.secondLockActionHash))
    || (controls.secondLockHoldApprovalHash !== undefined && (!/^[A-Za-z0-9_-]{43}$/.test(controls.secondLockHoldApprovalHash)
      || controls.secondLockHoldApprovalHash !== controls.secondLockActionHash || !controls.mandate))
    || hasUsdBudget === hasHkdBudget || !validMandate || !validTriggerGuard
    || (controls.mandate?.triggerScopeV1 !== undefined && controls.triggerGuard?.authorityKind !== 'user-signed')
    || (controls.triggerGuard?.authorityKind === 'user-signed' && !controls.mandate?.triggerScopeV1)
    || (controls.nowMs !== undefined && !Number.isSafeInteger(controls.nowMs))) {
    throw new Error('The paper commit is missing a valid signed budget scope.');
  }
}

const sqliteBusyWait = new Int32Array(new SharedArrayBuffer(4));

function enableWalMode(db: DatabaseSync): void {
  const deadline = Date.now() + 5_000;
  let delayMs = 5;
  while (true) {
    try {
      db.exec('PRAGMA journal_mode = WAL;');
      return;
    } catch (error) {
      const sqliteError = error as { errcode?: unknown };
      if ((sqliteError.errcode !== 5 && sqliteError.errcode !== 6) || Date.now() >= deadline) throw error;
      Atomics.wait(sqliteBusyWait, 0, 0, delayMs);
      delayMs = Math.min(delayMs * 2, 100);
    }
  }
}

function calculateNotionalUsdMinor(candidate: DurablePaperOrder): number {
  const order = candidate.order && typeof candidate.order === 'object' ? candidate.order as Record<string, unknown> : null;
  const quote = candidate.marketQuote && typeof candidate.marketQuote === 'object' ? candidate.marketQuote as Record<string, unknown> : null;
  if (!order || !quote || !Number.isSafeInteger(order.quantity) || Number(order.quantity) <= 0
    || (order.side !== 'buy' && order.side !== 'sell') || (order.orderType !== 'market' && order.orderType !== 'limit')
    || (quote.currency !== 'USD' && quote.currency !== 'HKD')) {
    throw new Error('Paper budget notional requires a typed order and signed quote.');
  }
  if (order.currency !== undefined && order.currency !== quote.currency) {
    throw new Error('Paper budget order currency does not match its signed quote.');
  }
  const priceValue = order.orderType === 'market'
    ? order.side === 'buy' ? quote.ask : quote.bid
    : order.limitPrice;
  if (typeof priceValue !== 'number' || !Number.isFinite(priceValue) || priceValue <= 0) throw new Error('Paper budget price must be a finite positive value.');
  let price: number = priceValue;
  const exactMinor = order.orderType === 'market'
    ? order.side === 'buy' ? quote.askMinor : quote.bidMinor
    : order.limitPriceMinor;
  if (exactMinor !== undefined) {
    if (!Number.isSafeInteger(exactMinor) || Number(exactMinor) <= 0
      || !decimalEqualsMinor(price, Number(exactMinor))) {
      throw new Error('Paper budget minor price does not match its typed order or signed quote.');
    }
    price = Number(exactMinor) / 100;
  }
  if (quote.currency === 'HKD' && order.orderType === 'limit'
    && (order.market !== 'HK' || !isHkexEquityPrice(price))) {
    throw new Error('HKD paper execution price does not follow the current HKEX equity price grid.');
  }
  return quote.currency === 'HKD'
    ? decimalToMinorCeil(price, Number(order.quantity), 16, 125)
    : decimalToMinorCeil(price, Number(order.quantity), 1, 1);
}

function calculateNotionalMinor(candidate: DurablePaperOrder): number {
  const order = candidate.order && typeof candidate.order === 'object' ? candidate.order as Record<string, unknown> : null;
  const quote = candidate.marketQuote && typeof candidate.marketQuote === 'object' ? candidate.marketQuote as Record<string, unknown> : null;
  if (!order || !quote || quote.currency !== 'HKD' || order.currency !== 'HKD' || order.market !== 'HK'
    || !Number.isSafeInteger(order.quantity) || Number(order.quantity) <= 0
    || (order.side !== 'buy' && order.side !== 'sell')
    || (order.orderType !== 'limit' && order.orderType !== 'market')) {
    throw new Error('HKD paper budget requires a typed HKD order and signed HKD quote.');
  }
  const priceMinor = order.orderType === 'limit'
    ? order.limitPriceMinor
    : order.side === 'buy' ? quote.askMinor : quote.bidMinor;
  const displayedPrice = order.orderType === 'limit'
    ? order.limitPrice
    : order.side === 'buy' ? quote.ask : quote.bid;
  if (!Number.isSafeInteger(priceMinor) || Number(priceMinor) <= 0
    || typeof displayedPrice !== 'number' || !Number.isFinite(displayedPrice) || displayedPrice <= 0
    || (order.orderType === 'limit' && Math.round(displayedPrice * 100) !== Number(priceMinor))) {
    throw new Error('HKD paper budget requires matching integer-minor order or signed quote prices.');
  }
  if (order.orderType === 'limit' && !isHkexEquityPrice(Number(displayedPrice))) {
    throw new Error('HKD paper price does not follow the current HKEX equity price grid.');
  }
  const notionalMinor = BigInt(Number(order.quantity)) * BigInt(Number(priceMinor));
  if (notionalMinor <= 0n || notionalMinor > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('HKD order notional exceeds the safe integer range.');
  return Number(notionalMinor);
}

function convertHkdMinorToUsd(amountMinor: number, conversion: { numerator: number; denominator: number }): number {
  const cents = ceilRatio(BigInt(amountMinor) * BigInt(conversion.numerator), BigInt(conversion.denominator));
  if (cents < 0n || cents > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error('Converted USD value exceeds the safe integer range.');
  }
  const usdCents = Number(cents);
  return usdCents / 100;
}

function decimalFraction(value: number): { numerator: bigint; denominator: bigint } {
  if (!Number.isFinite(value) || value <= 0) throw new Error('A positive finite decimal is required.');
  const match = value.toString().toLowerCase().match(/^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/);
  if (!match) throw new Error('The decimal value cannot be represented as a base-10 amount.');
  const fraction = match[2] ?? '';
  const exponent = Number(match[3] ?? 0);
  let numerator = BigInt(match[1] + fraction);
  const scale = fraction.length - exponent;
  if (scale > 0) return { numerator, denominator: 10n ** BigInt(scale) };
  if (scale < 0) numerator *= 10n ** BigInt(-scale);
  return { numerator, denominator: 1n };
}

function decimalEqualsMinor(value: number, minor: number): boolean {
  const decimal = decimalFraction(value);
  return decimal.numerator * 100n === BigInt(minor) * decimal.denominator;
}

function ceilRatio(numerator: bigint, denominator: bigint): bigint {
  if (numerator < 0n || denominator <= 0n) throw new Error('A non-negative ratio is required.');
  return (numerator + denominator - 1n) / denominator;
}

function safeMinor(value: bigint, message: string): number {
  if (value <= 0n || value > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error(message);
  return Number(value);
}

function decimalToMinorCeil(value: number, quantity: number, fxNumerator: number, fxDenominator: number): number {
  if (!Number.isSafeInteger(quantity) || quantity <= 0
    || !Number.isSafeInteger(fxNumerator) || fxNumerator <= 0
    || !Number.isSafeInteger(fxDenominator) || fxDenominator <= 0) {
    throw new Error('Paper budget quantity and currency conversion must be positive safe integers.');
  }
  const decimal = decimalFraction(value);
  const numerator = BigInt(quantity) * decimal.numerator * BigInt(fxNumerator) * 100n;
  const denominator = decimal.denominator * BigInt(fxDenominator);
  return safeMinor(ceilRatio(numerator, denominator), 'Paper budget notional exceeds the safe integer range.');
}

export function floorUsdBudgetMinor(value: number): number {
  const decimal = decimalFraction(value);
  const minor = (decimal.numerator * 100n) / decimal.denominator;
  if (minor <= 0n || minor > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error('USD budget limit exceeds the safe integer range.');
  }
  return Number(minor);
}

function isOpenUnfilledOrder(execution: unknown): boolean {
  if (!execution || typeof execution !== 'object') return false;
  const value = execution as Record<string, unknown>;
  return value.status === 'accepted' && value.filledQuantity === 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPaperLedgerReceiptEvidence(value: unknown): value is PaperLedgerReceiptEvidence {
  if (!isRecord(value) || typeof value.signerPublicKey !== 'string' || value.signerPublicKey.length > 8_000
    || !isRecord(value.document) || !isRecord(value.document.claims)
    || typeof value.document.signature !== 'string' || !/^[A-Za-z0-9_-]{80,100}$/.test(value.document.signature)
    || !Object.hasOwn(value, 'result')) return false;
  return true;
}

function isPaperExecutionAuditRecordV1(value: unknown): value is PaperExecutionAuditRecordV1 {
  if (!isRecord(value) || value.schemaVersion !== 1
    || (value.kind !== 'commit' && value.kind !== 'cancel')
    || typeof value.recordedAt !== 'string' || !Number.isFinite(Date.parse(value.recordedAt))
    || !isRecord(value.audit)) return false;
  if ((value.kind === 'commit' && !['accepted', 'recovered', 'unknown', 'held', 'rejected', 'committing'].includes(String(value.outcome)))
    || (value.kind === 'cancel' && !['applied', 'blocked', 'unknown', 'committing'].includes(String(value.outcome)))) return false;
  if (value.ownerApproval !== undefined) {
    if (value.kind !== 'cancel' || !isRecord(value.ownerApproval)
      || value.ownerApproval.method !== 'webauthn-passkey-v1'
      || typeof value.ownerApproval.evidenceHash !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(value.ownerApproval.evidenceHash)
      || typeof value.ownerApproval.authorizedOrderHash !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(value.ownerApproval.authorizedOrderHash)) return false;
  }
  if (value.triggerEffect !== undefined) {
    const effect = value.triggerEffect;
    if (!isRecord(effect) || effect.version !== 1
      || typeof effect.triggerId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(effect.triggerId)
      || typeof effect.rootTriggerId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(effect.rootTriggerId)
      || (effect.parentEffectOrderId !== null && (typeof effect.parentEffectOrderId !== 'string'
        || !/^paper:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(effect.parentEffectOrderId)))
      || typeof effect.standingRuleRef !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(effect.standingRuleRef)
      || !Number.isSafeInteger(effect.policyEpoch) || Number(effect.policyEpoch) < 1
      || typeof effect.eventSha256 !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(effect.eventSha256)
      || typeof effect.scopeSha256 !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(effect.scopeSha256)) return false;
  }
  if (!isRecord(value.proposal)) return false;
  const proposal = value.proposal;
  if (typeof proposal.runId !== 'string' || proposal.runId.length < 1 || proposal.runId.length > 128
    || (proposal.market !== 'US' && proposal.market !== 'HK')
    || typeof proposal.symbol !== 'string' || !/^[A-Z0-9][A-Z0-9._-]{0,19}$/.test(proposal.symbol)
    || (proposal.side !== 'buy' && proposal.side !== 'sell')
    || !Number.isSafeInteger(proposal.quantity) || Number(proposal.quantity) < 1 || Number(proposal.quantity) > 100_000
    || (proposal.orderType !== 'market' && proposal.orderType !== 'limit')
    || (proposal.orderType === 'market' && proposal.limitPrice !== null)
    || (proposal.orderType === 'limit' && (typeof proposal.limitPrice !== 'number' || !Number.isFinite(proposal.limitPrice) || proposal.limitPrice <= 0))
    || typeof proposal.session !== 'string' || !/^[a-z][a-z0-9_-]{0,31}$/.test(proposal.session)
    || (proposal.timeInForce !== 'day' && proposal.timeInForce !== 'gtc')) return false;
  const audit = value.audit;
  if (typeof audit.taskId !== 'string' || audit.taskId.length > 128
    || typeof audit.traceId !== 'string' || audit.traceId.length > 128
    || typeof audit.requestHashPrefix !== 'string' || audit.requestHashPrefix.length > 64
    || (audit.requestHash !== undefined && (typeof audit.requestHash !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(audit.requestHash)))
    || typeof audit.totalLatencyMs !== 'number' || !Number.isFinite(audit.totalLatencyMs) || audit.totalLatencyMs < 0
    || !Array.isArray(audit.hops) || audit.hops.length > 128
    || (audit.secondLock !== undefined && !isRecord(audit.secondLock))
    || (audit.paperLedgerReceipt !== undefined && !isPaperLedgerReceiptEvidence(audit.paperLedgerReceipt))) return false;
  return audit.hops.every((candidate) => {
    if (!isRecord(candidate)) return false;
    return typeof candidate.audience === 'string' && candidate.audience.length <= 80
      && typeof candidate.operation === 'string' && candidate.operation.length <= 120
      && typeof candidate.resource === 'string' && candidate.resource.length <= 256
      && (candidate.decision === 'allow' || candidate.decision === 'block')
      && (candidate.observation === undefined || candidate.observation === 'pending' || candidate.observation === 'unavailable' || candidate.observation === 'unverified')
      && typeof candidate.receiptVerified === 'boolean'
      && typeof candidate.handlerInvoked === 'boolean'
      && typeof candidate.sideEffects === 'number' && Number.isSafeInteger(candidate.sideEffects) && candidate.sideEffects >= 0
      && typeof candidate.latencyMs === 'number' && Number.isFinite(candidate.latencyMs) && candidate.latencyMs >= 0
      && typeof candidate.reason === 'string' && candidate.reason.length <= 2_000;
  });
}

function decodeOrder(row: SqlRow): DurablePaperOrder {
  const budgetCurrency = row.budget_currency === 'USD' || row.budget_currency === 'HKD' ? row.budget_currency : null;
  const budgetNotionalMinor = Number(row.budget_notional_minor);
  const budgetNotionalUsd = Number(row.budget_notional_usd);
  const createdAt = Number(row.created_at);
  if (typeof row.idempotency_key !== 'string' || !row.idempotency_key
    || typeof row.budget_key !== 'string' || !row.budget_key
    || !budgetCurrency || !Number.isSafeInteger(budgetNotionalMinor) || budgetNotionalMinor <= 0
    || !Number.isFinite(budgetNotionalUsd) || budgetNotionalUsd <= 0 || !Number.isSafeInteger(createdAt) || createdAt <= 0) {
    throw new Error('Paper ledger order is missing a valid authenticated budget binding.');
  }
  return {
    orderHash: String(row.order_hash),
    intentHash: String(row.intent_hash),
    orderId: String(row.order_id),
    order: parseJson(row.order_json),
    marketQuote: parseJson(row.market_quote_json),
    marketQuoteResult: parseJson(row.market_quote_result_json),
    marketQuoteReceipt: parseJson(row.market_quote_receipt_json),
    execution: parseJson(row.execution_json),
    cancelled: Number(row.cancelled) === 1,
    createdAt,
    ledgerBinding: {
      idempotencyKey: row.idempotency_key,
      budgetKey: row.budget_key,
      budgetNotionalUsd,
      budgetNotionalMinor,
      budgetCurrency,
      createdAt,
    },
  };
}

function parseJson(value: unknown): unknown {
  if (typeof value !== 'string') throw new Error('Paper ledger contains an invalid JSON field.');
  return JSON.parse(value) as unknown;
}

function canonicalJson(value: unknown): string {
  if (value === undefined) return '"__undefined__"';
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  const record = value as Record<string, unknown>;
  return '{' + Object.keys(record).sort().map((key) => JSON.stringify(key) + ':' + canonicalJson(record[key])).join(',') + '}';
}

function sha256Base64Url(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('base64url');
}

/** Venue order IDs are opaque protocol values; preserve common separators while excluding whitespace and controls. */
function isSafeVenueOrderId(value: unknown): value is string {
  return typeof value === 'string' && value.length >= 1 && value.length <= 180 && /^[\x21-\x7E]+$/.test(value);
}

function paperLedgerSidecarBase(path: string): string | null {
  if (path === ':memory:') return null;
  if (path.startsWith('file:')) {
    try { return fileURLToPath(new URL(path)); }
    catch { throw new Error('Paper ledger file URI cannot be mapped to a protected audit sidecar path.'); }
  }
  return resolve(path);
}

function openAuditSidecarRead(path: string): number {
  if (typeof constants.O_NOFOLLOW !== 'number' || typeof constants.O_NONBLOCK !== 'number') {
    throw new Error('Paper audit sidecars require no-follow file opening support.');
  }
  return openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
}

function hardenAuditSidecarDescriptor(fd: number, label: string): void {
  const stat = fstatSync(fd);
  const uid = typeof process.getuid === 'function' ? process.getuid() : undefined;
  if (!stat.isFile() || stat.nlink !== 1 || (uid !== undefined && stat.uid !== uid)) {
    throw new Error(label + ' must be a regular file owned by this process with one link.');
  }
  fchmodSync(fd, 0o600);
}

function syncAuditDirectory(path: string, label: string): void {
  if (typeof constants.O_DIRECTORY !== 'number' || typeof constants.O_NOFOLLOW !== 'number') {
    throw new Error(label + ' requires safe directory-open and fsync support.');
  }
  const fd = openSync(path, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try {
    if (!fstatSync(fd).isDirectory()) throw new Error(label + ' is not a directory.');
    fsyncSync(fd);
  } catch {
    throw new Error(label + ' could not be synchronized after the sidecar update.');
  } finally {
    closeSync(fd);
  }
}

function loadOrCreatePaperAuditKey(path: string | null): Buffer {
  const suppliedKey = process.env.ORDERGUARD_AUDIT_KEY;
  if (suppliedKey !== undefined) {
    if (!/^[A-Za-z0-9_-]{43}$/.test(suppliedKey)) throw new Error('ORDERGUARD_AUDIT_KEY must be a 32-byte base64url key.');
    const key = Buffer.from(suppliedKey, 'base64url');
    if (key.length !== 32 || key.toString('base64url') !== suppliedKey) throw new Error('ORDERGUARD_AUDIT_KEY has an invalid encoding.');
    return key;
  }
  if (path === null) return randomBytes(32);
  const directory = dirname(path);
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const read = (): Buffer => {
    let fd: number | undefined;
    try {
      fd = openAuditSidecarRead(path);
      hardenAuditSidecarDescriptor(fd, 'Paper audit integrity key');
      const encoded = readFileSync(fd, 'utf8').trim();
      if (!/^[A-Za-z0-9_-]{43}$/.test(encoded)) throw new Error('Paper audit integrity key is malformed.');
      const key = Buffer.from(encoded, 'base64url');
      if (key.length !== 32 || key.toString('base64url') !== encoded) throw new Error('Paper audit integrity key has an invalid encoding.');
      return key;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ELOOP') {
        throw new Error('Paper audit integrity key must not be a symbolic link.');
      }
      throw error;
    } finally {
      if (fd !== undefined) closeSync(fd);
    }
  };
  if (existsSync(path)) return read();
  const encoded = randomBytes(32).toString('base64url');
  let fd: number | undefined;
  try {
    if (typeof constants.O_NOFOLLOW !== 'number') throw new Error('Paper audit integrity key requires no-follow file creation support.');
    fd = openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    hardenAuditSidecarDescriptor(fd, 'Paper audit integrity key');
    writeSync(fd, encoded, 0, 'utf8');
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    syncAuditDirectory(directory, 'Paper audit integrity key directory');
    return Buffer.from(encoded, 'base64url');
  } catch (error) {
    if (fd !== undefined) closeSync(fd);
    if ((error as NodeJS.ErrnoException).code === 'EEXIST') return read();
    throw error;
  }
}

function paperAuditHmac(key: Buffer, value: string): string {
  return createHmac('sha256', key).update(value, 'utf8').digest('base64url');
}

function paperAuditCheckpointTransitionMac(key: Buffer, transition: PaperAuditCheckpointTransitionV1): string {
  return paperAuditHmac(key, canonicalJson({ domain: 'orderguard.paper-audit-checkpoint-transition.v1', transition }));
}

function killSwitchAuditEventMac(key: Buffer, previousMac: string, event: KillSwitchAuditEventV1): string {
  return paperAuditHmac(key, canonicalJson({ domain: 'orderguard.kill-switch-event.v1', previousMac, event }));
}

function causalTriggerBreakerKey(event: Pick<CausalTriggerBreakerAuditV1,
  'budgetKey' | 'breakerScope' | 'scopeRef' | 'policyEpoch'>): string {
  return sha256Base64Url(canonicalJson({
    domain: 'orderguard.causal-trigger-breaker-key.v1',
    budgetKey: event.budgetKey,
    breakerScope: event.breakerScope,
    scopeRef: event.scopeRef,
    policyEpoch: event.policyEpoch,
  }));
}

function causalTriggerBreakerEventFromRow(row: SqlRow): CausalTriggerBreakerAuditV1 | null {
  if (typeof row.budget_key !== 'string' || typeof row.breaker_scope !== 'string'
    || typeof row.scope_ref !== 'string' || !Number.isSafeInteger(row.policy_epoch)
    || !Number.isSafeInteger(row.opened_at_ms) || typeof row.mandate_id !== 'string'
    || typeof row.reason !== 'string' || typeof row.scope_sha256 !== 'string') return null;
  const claims = {
    version: 1 as const,
    budgetKey: row.budget_key,
    breakerScope: row.breaker_scope as 'trigger' | 'window',
    scopeRef: row.scope_ref,
    policyEpoch: row.policy_epoch as number,
    openedAtMs: row.opened_at_ms as number,
    mandateId: row.mandate_id,
    reason: row.reason,
    scopeSha256: row.scope_sha256,
  };
  const event: CausalTriggerBreakerAuditV1 = { ...claims, breakerKey: causalTriggerBreakerKey(claims) };
  return isCausalTriggerBreakerAuditV1(event) ? event : null;
}

function isCausalTriggerBreakerAuditV1(value: unknown): value is CausalTriggerBreakerAuditV1 {
  if (!isRecord(value) || Object.keys(value).some((key) => ![
    'version', 'breakerKey', 'budgetKey', 'breakerScope', 'scopeRef', 'policyEpoch', 'openedAtMs',
    'mandateId', 'reason', 'scopeSha256',
  ].includes(key)) || value.version !== 1
    || typeof value.breakerKey !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(value.breakerKey)
    || typeof value.budgetKey !== 'string' || value.budgetKey.length < 1 || value.budgetKey.length > 256
    || /[\u0000-\u001f]/.test(value.budgetKey)
    || (value.breakerScope !== 'trigger' && value.breakerScope !== 'window')
    || typeof value.scopeRef !== 'string'
    || (value.breakerScope === 'window' ? value.scopeRef !== 'account'
      : !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.scopeRef))
    || !Number.isSafeInteger(value.policyEpoch) || Number(value.policyEpoch) < 1
    || !Number.isSafeInteger(value.openedAtMs) || Number(value.openedAtMs) < 1
    || typeof value.mandateId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.mandateId)
    || typeof value.reason !== 'string' || value.reason.length < 1 || value.reason.length > 1_024
    || typeof value.scopeSha256 !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(value.scopeSha256)) return false;
  return value.breakerKey === causalTriggerBreakerKey(value as Pick<CausalTriggerBreakerAuditV1,
    'budgetKey' | 'breakerScope' | 'scopeRef' | 'policyEpoch'>);
}

function causalTriggerBreakerAuditMac(key: Buffer, breakerKey: string, sequence: number, previousMac: string,
  eventHash: string, eventJson: string): string {
  return paperAuditHmac(key, canonicalJson({
    domain: 'orderguard.causal-trigger-breaker-audit.v1',
    breakerKey,
    sequence,
    previousMac,
    eventHash,
    eventJson,
  }));
}

function constantTimeStringEqual(left: string, right: string): boolean {
  if (left.length !== right.length || left.length > 512) return false;
  const leftBytes = Buffer.from(left, 'utf8');
  const rightBytes = Buffer.from(right, 'utf8');
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

function isPaperAuditOrderHeads(value: unknown): value is PaperAuditAnchor['orders'] {
  if (!isRecord(value)) return false;
  return Object.entries(value).every(([orderId, head]) => /^paper:[^\u0000-\u001f]{1,128}$/.test(orderId)
    && isRecord(head) && Number.isSafeInteger(head.sequence) && Number(head.sequence) > 0
    && typeof head.headMac === 'string' && /^[A-Za-z0-9_-]{43}$/.test(head.headMac));
}

function isCausalTriggerBreakerHeadsV1(value: unknown): value is NonNullable<PaperAuditAnchor['causalTriggerBreakerHeadsV1']> {
  if (!isRecord(value)) return false;
  return Object.entries(value).every(([breakerKey, head]) => /^[A-Za-z0-9_-]{43}$/.test(breakerKey)
    && isRecord(head) && Number.isSafeInteger(head.sequence) && Number(head.sequence) > 0
    && typeof head.headMac === 'string' && /^[A-Za-z0-9_-]{43}$/.test(head.headMac));
}

function isLegacyPaperAuditAnchorV1(value: unknown): value is LegacyPaperAuditAnchorV1 {
  return isRecord(value) && value.schemaVersion === 1 && isPaperAuditOrderHeads(value.orders);
}

function isPaperAuditAnchor(value: unknown): value is PaperAuditAnchor {
  if (!isRecord(value) || value.schemaVersion !== 2 || !isPaperAuditOrderHeads(value.orders)
    || !isRecord(value.killSwitch) || !Number.isSafeInteger(value.killSwitch.version)
    || Number(value.killSwitch.version) < 0 || typeof value.killSwitch.headMac !== 'string'
    || !/^[A-Za-z0-9_-]{43}$/.test(value.killSwitch.headMac)
    || (value.causalTriggerBreakerHeadsV1 !== undefined
      && !isCausalTriggerBreakerHeadsV1(value.causalTriggerBreakerHeadsV1))) return false;
  return Number(value.killSwitch.version) !== 0 || value.killSwitch.headMac === KILL_SWITCH_AUDIT_GENESIS;
}

function isPaperAuditCheckpointTransitionV1(value: unknown): value is PaperAuditCheckpointTransitionV1 {
  if (!isRecord(value) || value.schemaVersion !== 1 || typeof value.transactionId !== 'string'
    || !/^[A-Za-z0-9_-]{24}$/.test(value.transactionId)
    || !isPaperAuditAnchor(value.previous) || !isPaperAuditAnchor(value.next)) return false;
  const previous = value.previous;
  const next = value.next;
  let changedChains = 0;
  for (const [orderId, oldHead] of Object.entries(previous.orders)) {
    const newHead = next.orders[orderId];
    if (!newHead || newHead.sequence < oldHead.sequence) return false;
    if (newHead.sequence === oldHead.sequence) {
      if (newHead.headMac !== oldHead.headMac) return false;
      continue;
    }
    if (newHead.sequence !== oldHead.sequence + 1) return false;
    changedChains += 1;
  }
  for (const [orderId, newHead] of Object.entries(next.orders)) {
    if (previous.orders[orderId]) continue;
    if (newHead.sequence !== 1) return false;
    changedChains += 1;
  }
  let changedBreakerChains = 0;
  const previousBreakerHeads = previous.causalTriggerBreakerHeadsV1 ?? {};
  const nextBreakerHeads = next.causalTriggerBreakerHeadsV1 ?? {};
  for (const [breakerKey, oldHead] of Object.entries(previousBreakerHeads)) {
    const newHead = nextBreakerHeads[breakerKey];
    if (!newHead || newHead.sequence < oldHead.sequence) return false;
    if (newHead.sequence === oldHead.sequence) {
      if (newHead.headMac !== oldHead.headMac) return false;
      continue;
    }
    if (newHead.sequence !== oldHead.sequence + 1) return false;
    changedBreakerChains += 1;
  }
  for (const [breakerKey, newHead] of Object.entries(nextBreakerHeads)) {
    if (previousBreakerHeads[breakerKey]) continue;
    if (newHead.sequence !== 1) return false;
    changedBreakerChains += 1;
  }
  if (next.killSwitch.version < previous.killSwitch.version) return false;
  let killSwitchChanged = false;
  if (next.killSwitch.version === previous.killSwitch.version) {
    if (next.killSwitch.headMac !== previous.killSwitch.headMac) return false;
  } else {
    if (next.killSwitch.version !== previous.killSwitch.version + 1) return false;
    killSwitchChanged = true;
  }
  return changedChains + changedBreakerChains + Number(killSwitchChanged) === 1
    && canonicalJson(previous) !== canonicalJson(next);
}

function clonePaperAuditAnchor(anchor: PaperAuditAnchor): PaperAuditAnchor {
  return {
    schemaVersion: 2,
    orders: Object.fromEntries(Object.entries(anchor.orders).map(([orderId, head]) => [orderId, { sequence: head.sequence, headMac: head.headMac }])),
    killSwitch: { version: anchor.killSwitch.version, headMac: anchor.killSwitch.headMac },
    ...(anchor.causalTriggerBreakerHeadsV1 ? {
      causalTriggerBreakerHeadsV1: Object.fromEntries(Object.entries(anchor.causalTriggerBreakerHeadsV1)
        .map(([breakerKey, head]) => [breakerKey, { sequence: head.sequence, headMac: head.headMac }])),
    } : {}),
  };
}

function isConstraintError(error: unknown): boolean {
  return error instanceof Error && 'code' in error && typeof error.code === 'string' && error.code.startsWith('SQLITE_CONSTRAINT');
}
