export interface TriggerScopeV1 {
  version: 1;
  /** A user-approved policy epoch. A breaker only clears under a newer signed mandate. */
  policyEpoch: number;
  allowedTriggerTypes: string[];
  allowedSourceProvenance: string[];
  allowedActions: Array<'order.place'>;
  allowedSymbols: string[];
  allowedSides: Array<'buy' | 'sell'>;
  maxTriggerAgeMs: number;
  maxOrdersPerTrigger: number;
  maxDistinctSymbolsPerTrigger: number;
  maxGrossNotionalUsdMinorPerTrigger: number;
  portfolioWindowMs: number;
  maxOrdersPerWindow: number;
  maxGrossNotionalUsdMinorPerWindow: number;
}

export interface TriggerEventClaimsV1 {
  version: 1;
  triggerId: string;
  triggerType: string;
  sourceProvenance: string;
  sourceSha256: string;
  receivedAtMs: number;
  expiresAtMs: number;
}

export interface SignedTriggerEventV1 {
  claims: TriggerEventClaimsV1;
  signature: string;
}

export interface CausalTriggerContextV1 {
  version: 1;
  event: SignedTriggerEventV1;
  /** Root event identity is preserved by every descendant effect. */
  rootTriggerId: string;
  /** A prior committed effect in this same root's append-only lineage. */
  parentEffectOrderId?: string;
  /** Bound to the user-signed standing mandate. */
  standingRuleRef: string;
  policyEpoch: number;
}

export interface PaperTriggerEffectAuditV1 {
  version: 1;
  triggerId: string;
  rootTriggerId: string;
  parentEffectOrderId: string | null;
  standingRuleRef: string;
  policyEpoch: number;
  eventSha256: string;
  scopeSha256: string;
}

export function triggerScopeError(value: unknown): string | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['version', 'policyEpoch', 'allowedTriggerTypes', 'allowedSourceProvenance', 'allowedActions', 'allowedSymbols', 'allowedSides', 'maxTriggerAgeMs', 'maxOrdersPerTrigger', 'maxDistinctSymbolsPerTrigger', 'maxGrossNotionalUsdMinorPerTrigger', 'portfolioWindowMs', 'maxOrdersPerWindow', 'maxGrossNotionalUsdMinorPerWindow'])
    || value.version !== 1
    || !Number.isSafeInteger(value.policyEpoch) || Number(value.policyEpoch) < 1
    || !isStringArray(value.allowedTriggerTypes, 1, 16, /^[a-z][a-z0-9._-]{0,63}$/)
    || !isStringArray(value.allowedSourceProvenance, 1, 16, /^[a-z][a-z0-9._-]{0,63}$/)
    || !Array.isArray(value.allowedActions) || value.allowedActions.length !== 1 || value.allowedActions[0] !== 'order.place'
    || !isStringArray(value.allowedSymbols, 1, 100, /^[A-Z0-9][A-Z0-9._-]{0,19}$/)
    || !Array.isArray(value.allowedSides) || value.allowedSides.length < 1 || value.allowedSides.length > 2
    || value.allowedSides.some((side) => side !== 'buy' && side !== 'sell')
    || new Set(value.allowedSides).size !== value.allowedSides.length
    || !Number.isSafeInteger(value.maxTriggerAgeMs) || Number(value.maxTriggerAgeMs) < 1_000 || Number(value.maxTriggerAgeMs) > 86_400_000
    || !Number.isSafeInteger(value.maxOrdersPerTrigger) || Number(value.maxOrdersPerTrigger) < 1 || Number(value.maxOrdersPerTrigger) > 10_000
    || !Number.isSafeInteger(value.maxDistinctSymbolsPerTrigger) || Number(value.maxDistinctSymbolsPerTrigger) < 1
      || Number(value.maxDistinctSymbolsPerTrigger) > (value.allowedSymbols as string[]).length
    || !Number.isSafeInteger(value.maxGrossNotionalUsdMinorPerTrigger) || Number(value.maxGrossNotionalUsdMinorPerTrigger) < 1
    || !Number.isSafeInteger(value.portfolioWindowMs) || Number(value.portfolioWindowMs) < 1_000 || Number(value.portfolioWindowMs) > 31_536_000_000
    || !Number.isSafeInteger(value.maxOrdersPerWindow) || Number(value.maxOrdersPerWindow) < 1 || Number(value.maxOrdersPerWindow) > 100_000
    || !Number.isSafeInteger(value.maxGrossNotionalUsdMinorPerWindow) || Number(value.maxGrossNotionalUsdMinorPerWindow) < 1) {
    return 'trigger_scope_invalid';
  }
  return null;
}

export function causalTriggerContextError(value: unknown): string | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['version', 'event', 'rootTriggerId', 'parentEffectOrderId', 'standingRuleRef', 'policyEpoch'])
    || value.version !== 1 || !isRecord(value.event)
    || !hasOnlyKeys(value.event, ['claims', 'signature']) || !isRecord(value.event.claims)
    || !hasOnlyKeys(value.event.claims, ['version', 'triggerId', 'triggerType', 'sourceProvenance', 'sourceSha256', 'receivedAtMs', 'expiresAtMs'])
    || typeof value.event.signature !== 'string'
    || !/^[A-Za-z0-9_-]{80,100}$/.test(value.event.signature)
    || value.event.claims.version !== 1
    || typeof value.event.claims.triggerId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.event.claims.triggerId)
    || typeof value.event.claims.triggerType !== 'string' || !/^[a-z][a-z0-9._-]{0,63}$/.test(value.event.claims.triggerType)
    || typeof value.event.claims.sourceProvenance !== 'string' || !/^[a-z][a-z0-9._-]{0,63}$/.test(value.event.claims.sourceProvenance)
    || typeof value.event.claims.sourceSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.event.claims.sourceSha256)
    || !Number.isSafeInteger(value.event.claims.receivedAtMs) || !Number.isSafeInteger(value.event.claims.expiresAtMs)
    || Number(value.event.claims.expiresAtMs) <= Number(value.event.claims.receivedAtMs)
    || typeof value.rootTriggerId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.rootTriggerId)
    || (value.parentEffectOrderId !== undefined && (typeof value.parentEffectOrderId !== 'string'
      || !/^paper:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.parentEffectOrderId)))
    || typeof value.standingRuleRef !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.standingRuleRef)
    || !Number.isSafeInteger(value.policyEpoch) || Number(value.policyEpoch) < 1) {
    return 'trigger_context_invalid';
  }
  return null;
}

function isStringArray(value: unknown, min: number, max: number, pattern: RegExp): value is string[] {
  return Array.isArray(value) && value.length >= min && value.length <= max
    && value.every((entry) => typeof entry === 'string' && pattern.test(entry))
    && new Set(value).size === value.length;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}
