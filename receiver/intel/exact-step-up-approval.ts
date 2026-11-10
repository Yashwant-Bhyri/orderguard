import type { SecondLockAudit } from './second-lock.js';

const ACTION_HASH_PATTERN = /^[A-Za-z0-9_-]{43}$/;

/**
 * Apply a passkey approval only to the exact proposal that was durably held.
 * A reviewer deny is never overridable here; the paper ledger independently
 * checks the scoped hold and consumes the one-use approval in its commit.
 */
export function applyExactStepUpApproval(
  audit: SecondLockAudit,
  approvedActionHash: string | undefined,
  currentActionHash: string | undefined,
): SecondLockAudit {
  if (audit.decision !== 'step_up' || typeof approvedActionHash !== 'string'
    || !ACTION_HASH_PATTERN.test(approvedActionHash) || approvedActionHash !== currentActionHash) return audit;
  return {
    ...audit,
    decision: 'allow',
    reviewDecision: audit.decision,
    reason: 'The owner passkey approved this exact held action; the paper ledger will verify and consume the one-use approval atomically.',
    stepUpApproval: { method: 'webauthn-passkey-v1', actionHash: approvedActionHash },
  };
}
