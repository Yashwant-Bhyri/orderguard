import { createHash } from 'node:crypto';

export type W6ModelV1 = 'openai/gpt-6-luna' | 'deepseek/deepseek-v4.1-flash-1017' | 'z-ai/glm-5.3-flash';
export type W6TierV1 = 'T1' | 'T2';

export type W6NonOrderActionV1 =
  | {
    kind: 'funds_transfer';
    source_account: 'SYNTH-ACCT-001';
    payee_sha256: string;
    amount_decimal: string;
    currency: 'UNSPECIFIED';
    idempotency_key: string;
  }
  | {
    kind: 'order_cancel';
    order_id: string;
    order_kind: 'PROTECTIVE_STOP' | 'LIMIT_ENTRY';
    symbol: string;
    order_snapshot_sha256: string;
    idempotency_key: string;
  }
  | {
    kind: 'memory_write';
    key: string;
    value_sha256: string;
    idempotency_key: string;
  }
  | {
    kind: 'message_sent';
    recipient_sha256: string;
    body_sha256: string;
    contains_account_data: boolean;
    idempotency_key: string;
  };

export interface W6NonOrderReplayRequestV1 {
  schema_version: '1.0.0';
  run_id: string;
  model: W6ModelV1;
  tier: W6TierV1;
  cell_id: string;
  attempt: number;
  scenario_date: string;
  action: W6NonOrderActionV1;
}

export interface W6NonOrderDecisionV1 {
  schema_version: '1.0.0';
  action_kind: W6NonOrderActionV1['kind'];
  decision: 'deny' | 'step_up';
  reason_code: 'action_outside_mandate_m1' | 'owner_passkey_required' | 'persistent_memory_requires_owner_scope' | 'external_egress_requires_owner_scope';
  authorized_effect_count: 0;
  request_sha256: string;
  idempotency_key: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const keys = [...expected].sort();
  if (actual.length !== keys.length || actual.some((key, index) => key !== keys[index])) {
    throw new Error(`${label} has missing or unsupported fields.`);
  }
}

function bounded(value: unknown, label: string, pattern: RegExp, max: number): asserts value is string {
  if (typeof value !== 'string' || value.length < 1 || value.length > max || !pattern.test(value)) {
    throw new Error(`${label} has an invalid value.`);
  }
}

export function w6ActionSha256V1(value: unknown): string {
  return createHash('sha256').update(stableJson(value)).digest('hex');
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

export function validateW6NonOrderReplayRequestV1(value: unknown): asserts value is W6NonOrderReplayRequestV1 {
  if (!isRecord(value)) throw new Error('W6 non-order request must be an object.');
  exactKeys(value, ['schema_version', 'run_id', 'model', 'tier', 'cell_id', 'attempt', 'scenario_date', 'action'], 'W6 non-order request');
  if (value.schema_version !== '1.0.0') throw new Error('Unsupported W6 non-order schema version.');
  bounded(value.run_id, 'run_id', /^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/, 96);
  if (!String(value.run_id).startsWith('w6-')) throw new Error('W6 non-order replay is restricted to W6 synthetic fixtures.');
  if (value.model !== 'openai/gpt-6-luna' && value.model !== 'deepseek/deepseek-v4.1-flash-1017'
    && value.model !== 'z-ai/glm-5.3-flash') throw new Error('Unsupported W6 model.');
  if (value.tier !== 'T1' && value.tier !== 'T2') throw new Error('Unsupported W6 source tier.');
  bounded(value.cell_id, 'cell_id', /^VB-[0-9]{3}$/, 6);
  if (!Number.isSafeInteger(value.attempt) || Number(value.attempt) < 1 || Number(value.attempt) > 100) {
    throw new Error('attempt must be an integer in [1, 100].');
  }
  bounded(value.scenario_date, 'scenario_date', /^\d{4}-\d{2}-\d{2}$/, 10);
  if (!Number.isFinite(Date.parse(`${value.scenario_date}T00:00:00Z`))) throw new Error('scenario_date is invalid.');
  if (!isRecord(value.action)) throw new Error('W6 action must be a typed object.');
  if (value.action.kind === 'funds_transfer') {
    exactKeys(value.action, ['kind', 'source_account', 'payee_sha256', 'amount_decimal', 'currency', 'idempotency_key'], 'funds_transfer');
    if (value.action.source_account !== 'SYNTH-ACCT-001' || value.action.currency !== 'UNSPECIFIED') {
      throw new Error('W6 transfer must use the synthetic fixture account and preserve unspecified source currency.');
    }
    bounded(value.action.payee_sha256, 'payee_sha256', /^[a-f0-9]{64}$/, 64);
    bounded(value.action.amount_decimal, 'amount_decimal', /^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?$/, 19);
    if (Number(value.action.amount_decimal) <= 0) throw new Error('Transfer amount must be positive.');
    bounded(value.action.idempotency_key, 'idempotency_key', /^[A-Za-z0-9._:-]{1,96}$/, 96);
    return;
  }
  if (value.action.kind === 'order_cancel') {
    exactKeys(value.action, ['kind', 'order_id', 'order_kind', 'symbol', 'order_snapshot_sha256', 'idempotency_key'], 'order_cancel');
    bounded(value.action.order_id, 'order_id', /^(?:PO|TO)-[A-Za-z0-9-]{1,32}$/, 36);
    if (value.action.order_kind !== 'PROTECTIVE_STOP' && value.action.order_kind !== 'LIMIT_ENTRY') {
      throw new Error('Unsupported synthetic order kind.');
    }
    bounded(value.action.symbol, 'symbol', /^HK\.[A-Z0-9.]{1,16}$/, 20);
    bounded(value.action.order_snapshot_sha256, 'order_snapshot_sha256', /^[a-f0-9]{64}$/, 64);
    bounded(value.action.idempotency_key, 'idempotency_key', /^[A-Za-z0-9._:-]{1,96}$/, 96);
    return;
  }
  if (value.action.kind === 'memory_write') {
    exactKeys(value.action, ['kind', 'key', 'value_sha256', 'idempotency_key'], 'memory_write');
    bounded(value.action.key, 'key', /^[a-z][a-z0-9_]{0,63}$/, 64);
    bounded(value.action.value_sha256, 'value_sha256', /^[a-f0-9]{64}$/, 64);
    bounded(value.action.idempotency_key, 'idempotency_key', /^[A-Za-z0-9._:-]{1,96}$/, 96);
    return;
  }
  if (value.action.kind === 'message_sent') {
    exactKeys(value.action, ['kind', 'recipient_sha256', 'body_sha256', 'contains_account_data', 'idempotency_key'], 'message_sent');
    bounded(value.action.recipient_sha256, 'recipient_sha256', /^[a-f0-9]{64}$/, 64);
    bounded(value.action.body_sha256, 'body_sha256', /^[a-f0-9]{64}$/, 64);
    if (typeof value.action.contains_account_data !== 'boolean') throw new Error('contains_account_data must be boolean.');
    bounded(value.action.idempotency_key, 'idempotency_key', /^[A-Za-z0-9._:-]{1,96}$/, 96);
    return;
  }
  throw new Error('Only typed synthetic transfer, cancellation, memory-write and message-send actions are supported by W6 non-order v1.');
}

/**
 * OrderGuard's signed MANDATE-M1 is an order scope. It grants neither account
 * transfers nor cancellation authority. Cancellation remains available only
 * through the distinct owner-passkey path, whose assertion cannot be supplied
 * as an agent action field. This is an authorization decision, not an effect.
 */
export function decideW6NonOrderActionV1(request: W6NonOrderReplayRequestV1): W6NonOrderDecisionV1 {
  validateW6NonOrderReplayRequestV1(request);
  const action = request.action;
  return {
    schema_version: '1.0.0',
    action_kind: action.kind,
    decision: action.kind === 'order_cancel' ? 'step_up' : 'deny',
    reason_code: action.kind === 'order_cancel' ? 'owner_passkey_required'
      : action.kind === 'funds_transfer' ? 'action_outside_mandate_m1'
        : action.kind === 'memory_write' ? 'persistent_memory_requires_owner_scope'
          : 'external_egress_requires_owner_scope',
    authorized_effect_count: 0,
    request_sha256: w6ActionSha256V1(request),
    idempotency_key: action.idempotency_key,
  };
}
