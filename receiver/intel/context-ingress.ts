import { createHash } from 'node:crypto';

/** Shared W3/W1 normalization contract for provenance precompute and order review. */
export const CONTEXT_INGRESS_MAX_CHARS = 5_000;
export const CONTEXT_INGRESS_CANONICALIZATION = 'nfkc-trim-full-checked-5000-utf16-v3-append-bound';

export class ContextIngressOversizeError extends Error {
  readonly code = 'context_ingress_oversize';

  constructor() {
    super('The complete receiver trigger exceeds the Lock-2 coverage limit.');
    this.name = 'ContextIngressOversizeError';
  }
}

/** Server-owned identity for the exact source event that staged provenance. */
export interface ProvenanceStageBinding {
  sourceRunId: string;
  sourceEventId: string;
  /** Optional originating proposal-bank cell ID, carried into spend attribution. */
  cellId?: string;
  contextGeneration: number;
  contentHash: string;
  triagePolicyVersion: string;
}

export interface ProvenanceStageEvent {
  sourceRunId: string;
  sourceEventId: string;
  /** Optional originating proposal-bank cell ID, carried into spend attribution. */
  cellId?: string;
  contextGeneration: number;
}

/**
 * Build the receiver's trigger before inference. Keep the join, cap, and part
 * order identical to the order path so a precompute is reusable at review.
 */
export function buildReceiverTrigger(originalRequest: string, untrustedContext?: string | null): string {
  const trigger = [originalRequest, untrustedContext ?? '']
    .filter(Boolean)
    .join('\n\n');
  assertReceiverTriggerWithinLimit(trigger);
  return trigger;
}

/** Canonical trigger text consumed by both precompute and second-lock review. */
export function canonicalizeReceiverTrigger(trigger: string): string {
  return trigger.normalize('NFKC').trim();
}

/** Validate complete, model-visible content; this limit is UTF-16 code units (`string.length`). */
export function receiverTriggerWithinLimit(trigger: string): boolean {
  // Reject very long raw input before normalization touches it. NFKC can also
  // expand a short input, so the normalized form is checked after this cheap
  // UTF-16 code-unit bound.
  if (trigger.length > CONTEXT_INGRESS_MAX_CHARS) return false;
  return canonicalizeReceiverTrigger(trigger).length <= CONTEXT_INGRESS_MAX_CHARS;
}

/** Reject incomplete coverage instead of silently scoring or binding a prefix. */
export function assertReceiverTriggerWithinLimit(trigger: string): void {
  if (!receiverTriggerWithinLimit(trigger)) throw new ContextIngressOversizeError();
}

/** Content-only cache key; callers must bind it to the complete receiver trigger. */
export function receiverTriggerContentHash(trigger: string): string {
  const canonical = canonicalizeReceiverTrigger(trigger).replace(/\s+/g, ' ').trim();
  return createHash('sha256').update(canonical).digest('hex');
}

export interface FinalizedToolOutputV1 {
  /** Exact JSON text delivered through the provider's function-call output. */
  serializedOutput: string;
  /** Exact source-labeled text included in the receiver trigger. */
  contextEntry: string;
  truncated: boolean;
  originalChars: number;
}

/**
 * Fit one serialized tool result into the remaining receiver-trigger budget.
 * Truncation happens before either provider delivery or hashing, and the same
 * finalized bytes are used in both places. Null means even the truncation
 * marker cannot fit, so the caller must stop before another model request.
 */
export function finalizeToolOutputForContext(
  originalRequest: string,
  priorContext: readonly string[],
  toolName: string,
  callId: string,
  serializedOutput: string,
): FinalizedToolOutputV1 | null {
  if (!toolName.trim() || !callId.trim() || callId.length > 256) return null;
  const sourceLabel = `${toolName}[${callId}]`;
  const fits = (value: string): boolean => receiverTriggerWithinLimit(
    [originalRequest, [...priorContext, `${sourceLabel}: ${value}`].join('\n\n')].filter(Boolean).join('\n\n'),
  );
  if (fits(serializedOutput)) return {
    serializedOutput,
    contextEntry: `${sourceLabel}: ${serializedOutput}`,
    truncated: false,
    originalChars: serializedOutput.length,
  };

  let low = 0;
  let high = serializedOutput.length;
  let best: string | null = null;
  while (low <= high) {
    const previewChars = Math.floor((low + high) / 2);
    const candidate = JSON.stringify({
      truncated: true,
      original_chars: serializedOutput.length,
      preview: serializedOutput.slice(0, previewChars),
      warning: 'Tool output was truncated to the receiver context limit; omitted content is unknown.',
    });
    if (fits(candidate)) {
      best = candidate;
      low = previewChars + 1;
    } else {
      high = previewChars - 1;
    }
  }
  if (best === null) return null;
  return {
    serializedOutput: best,
    contextEntry: `${sourceLabel}: ${best}`,
    truncated: true,
    originalChars: serializedOutput.length,
  };
}

/** Validate that a stage receipt still names the exact post-append trigger. */
export function provenanceStageBindingMatchesTrigger(
  trigger: string,
  event: ProvenanceStageEvent,
  binding: ProvenanceStageBinding | undefined,
  triagePolicyVersion: string,
): boolean {
  if (!binding || !event.sourceRunId.trim() || !event.sourceEventId.trim()
    || !Number.isSafeInteger(event.contextGeneration) || event.contextGeneration < 1
    || !receiverTriggerWithinLimit(trigger)) return false;
  return binding.sourceRunId === event.sourceRunId
    && binding.sourceEventId === event.sourceEventId
    && (binding.cellId ?? null) === (event.cellId ?? null)
    && Number.isSafeInteger(binding.contextGeneration)
    && binding.contextGeneration === event.contextGeneration
    && binding.contentHash === receiverTriggerContentHash(trigger)
    && binding.triagePolicyVersion === triagePolicyVersion;
}
