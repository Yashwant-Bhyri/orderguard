import { b3StableJsonV2 } from '../scenario-contract-b3-v2.js';

export type W2ProposalGuardResult =
  | { ok: true }
  | { ok: false; state: 'proposal_mismatch'; dispatch_attempted: false };

export function guardW2ExpectedProposal(expected: unknown, actual: unknown): W2ProposalGuardResult {
  if (!isRecord(expected) || !isRecord(actual)) {
    return { ok: false, state: 'proposal_mismatch', dispatch_attempted: false };
  }
  try {
    return b3StableJsonV2(expected) === b3StableJsonV2(actual)
      ? { ok: true }
      : { ok: false, state: 'proposal_mismatch', dispatch_attempted: false };
  } catch {
    return { ok: false, state: 'proposal_mismatch', dispatch_attempted: false };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}
