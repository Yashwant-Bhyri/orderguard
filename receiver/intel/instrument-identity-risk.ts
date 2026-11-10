/**
 * W9 instrument-identity risk adapter.
 *
 * This consumes a cached, schema-checked risk score. It does not resolve or
 * rewrite an instrument, and it cannot make an order less restrictive. The
 * current W9 data is synthetic, so this remains disabled unless an explicit
 * feature flag is set by the caller.
 */

export const INSTRUMENT_IDENTITY_RISK_POLICY = {
  featureFlag: 'ORDERGUARD_INSTRUMENT_IDENTITY_REVIEW',
  provider: 'openrouter_jev',
  model: 'typesafe/jev-1.14-20261014',
  calibration: 'w9-cp2-identity-seeds-1-5-threshold-0.91-v1',
  minimumRiskScore: 0.91,
} as const;

export type OrderDecision = 'allow' | 'deny' | 'step_up';

export interface InstrumentIdentityRiskSignal {
  bindingId: string;
  provider: string;
  model: string;
  calibration: string;
  valid: boolean;
  choice: 'risk' | 'benign' | null;
  riskScore: number | null;
  error?: string | null;
}

export type InstrumentIdentityRiskReason =
  | 'feature_disabled'
  | 'identity_review_not_required'
  | 'base_decision_already_stricter'
  | 'identity_signal_unavailable'
  | 'identity_signal_binding_mismatch'
  | 'identity_signal_untrusted_model'
  | 'identity_signal_invalid'
  | 'identity_risk_below_threshold'
  | 'identity_risk_threshold';

export interface InstrumentIdentityRiskInput {
  baseDecision: OrderDecision;
  identityReviewRequired: boolean;
  bindingId: string;
  signal?: InstrumentIdentityRiskSignal | null;
  /** Omit to read the process flag. Tests and offline replays may inject it. */
  enabled?: boolean;
}

export interface InstrumentIdentityRiskResult {
  decision: OrderDecision;
  reason: InstrumentIdentityRiskReason;
  riskScore: number | null;
  policy: typeof INSTRUMENT_IDENTITY_RISK_POLICY.calibration;
}

export function instrumentIdentityRiskEnabled(
  env: Record<string, string | undefined> = process.env,
): boolean {
  const value = env[INSTRUMENT_IDENTITY_RISK_POLICY.featureFlag]?.trim().toLowerCase();
  return value === '1' || value === 'true' || value === 'on';
}

function result(
  decision: OrderDecision,
  reason: InstrumentIdentityRiskReason,
  riskScore: number | null,
): InstrumentIdentityRiskResult {
  return {
    decision,
    reason,
    riskScore,
    policy: INSTRUMENT_IDENTITY_RISK_POLICY.calibration,
  };
}

/**
 * A high or unavailable identity-risk score can only tighten the deterministic
 * decision. No score, alias, or model choice becomes the canonical order.
 */
export function applyInstrumentIdentityRisk(
  input: InstrumentIdentityRiskInput,
): InstrumentIdentityRiskResult {
  const enabled = input.enabled ?? instrumentIdentityRiskEnabled();
  if (!enabled) return result(input.baseDecision, 'feature_disabled', null);
  if (!input.identityReviewRequired) return result(input.baseDecision, 'identity_review_not_required', null);
  if (input.baseDecision !== 'allow') {
    return result(input.baseDecision, 'base_decision_already_stricter', null);
  }

  const signal = input.signal;
  if (!signal) return result('step_up', 'identity_signal_unavailable', null);
  if (!input.bindingId || signal.bindingId !== input.bindingId) {
    return result('step_up', 'identity_signal_binding_mismatch', null);
  }
  if (signal.provider !== INSTRUMENT_IDENTITY_RISK_POLICY.provider
      || signal.model !== INSTRUMENT_IDENTITY_RISK_POLICY.model
      || signal.calibration !== INSTRUMENT_IDENTITY_RISK_POLICY.calibration) {
    return result('step_up', 'identity_signal_untrusted_model', null);
  }
  if (signal.valid !== true || signal.error || (signal.choice !== 'risk' && signal.choice !== 'benign')
      || typeof signal.riskScore !== 'number' || !Number.isFinite(signal.riskScore)
      || signal.riskScore < 0 || signal.riskScore > 1) {
    return result('step_up', 'identity_signal_invalid', null);
  }
  if (signal.riskScore >= INSTRUMENT_IDENTITY_RISK_POLICY.minimumRiskScore) {
    return result('step_up', 'identity_risk_threshold', signal.riskScore);
  }
  return result(input.baseDecision, 'identity_risk_below_threshold', signal.riskScore);
}
