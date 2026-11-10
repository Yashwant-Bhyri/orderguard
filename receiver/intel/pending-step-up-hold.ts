import { createHash } from 'node:crypto';

export interface PendingStepUpHoldInput {
  accountKey: string;
  sessionKey: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  sourceActionHash: string;
  createdAtMs: number;
  expiresAtMs: number;
}

export interface PendingStepUpHold extends PendingStepUpHoldInput {
  schemaVersion: 'orderguard-pending-step-up-v1';
  holdKey: string;
  status: 'pending' | 'approved' | 'expired' | 'resolved';
}

export interface PendingStepUpProposal {
  accountKey: string;
  sessionKey: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
}

export interface PendingStepUpMatch {
  matches: boolean;
  overlapQuantity: number;
  reason: 'pending_step_up_match' | 'hold_inactive' | 'different_account' | 'different_session'
    | 'different_symbol' | 'different_side' | 'no_positive_size_overlap';
}

function sha256(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

function validate(input: PendingStepUpHoldInput): void {
  if (typeof input.accountKey !== 'string' || !input.accountKey.trim() || input.accountKey.length > 180
    || typeof input.sessionKey !== 'string' || !input.sessionKey.trim() || input.sessionKey.length > 180
    || !/^[A-Z0-9][A-Z0-9._-]{0,19}$/.test(input.symbol)
    || (input.side !== 'buy' && input.side !== 'sell')
    || !Number.isSafeInteger(input.quantity) || input.quantity <= 0
    || !(/^[a-f0-9]{64}$/.test(input.sourceActionHash) || /^[A-Za-z0-9_-]{43}$/.test(input.sourceActionHash))
    || !Number.isSafeInteger(input.createdAtMs) || !Number.isSafeInteger(input.expiresAtMs)
    || input.expiresAtMs <= input.createdAtMs) {
    throw new Error('pending_step_up_hold_input_invalid');
  }
}

/** Stable content address for one pending human-review decision. */
export function createPendingStepUpHold(input: PendingStepUpHoldInput): PendingStepUpHold {
  validate(input);
  const content = [
    'orderguard-pending-step-up-v1', input.accountKey, input.sessionKey, input.symbol,
    input.side, String(input.quantity), input.sourceActionHash,
  ].join('\u001f');
  return {
    ...input,
    schemaVersion: 'orderguard-pending-step-up-v1',
    holdKey: sha256(content),
    status: 'pending',
  };
}

/**
 * True for any shared positive share interval: both quantities describe
 * exposure from share 1 through quantity, so min(q1, q2) is the overlap.
 * The caller must run this against durable pending rows inside the same
 * BEGIN IMMEDIATE transaction that reserves/inserts the paper order.
 */
export function matchPendingStepUpHold(
  hold: PendingStepUpHold,
  proposal: PendingStepUpProposal,
  nowMs: number,
): PendingStepUpMatch {
  if (hold.schemaVersion !== 'orderguard-pending-step-up-v1' || hold.status !== 'pending'
    || !Number.isSafeInteger(nowMs) || hold.expiresAtMs <= nowMs) {
    return { matches: false, overlapQuantity: 0, reason: 'hold_inactive' };
  }
  if (hold.accountKey !== proposal.accountKey) return { matches: false, overlapQuantity: 0, reason: 'different_account' };
  if (hold.sessionKey !== proposal.sessionKey) return { matches: false, overlapQuantity: 0, reason: 'different_session' };
  if (hold.symbol !== proposal.symbol) return { matches: false, overlapQuantity: 0, reason: 'different_symbol' };
  if (hold.side !== proposal.side) return { matches: false, overlapQuantity: 0, reason: 'different_side' };
  if (!Number.isSafeInteger(proposal.quantity) || proposal.quantity <= 0) {
    return { matches: false, overlapQuantity: 0, reason: 'no_positive_size_overlap' };
  }
  const overlapQuantity = Math.min(hold.quantity, proposal.quantity);
  return overlapQuantity > 0
    ? { matches: true, overlapQuantity, reason: 'pending_step_up_match' }
    : { matches: false, overlapQuantity: 0, reason: 'no_positive_size_overlap' };
}
