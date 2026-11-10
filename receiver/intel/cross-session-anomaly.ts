/**
 * Local, one-way cross-agent anomaly triage for a shared budget.
 *
 * The caller supplies recent same-budget proposal events, keyed as a stream
 * would be by budget_id. This module can only recommend step-up review; it
 * cannot approve, sign, deny, or submit an order. Time-window grouping follows
 * Apache Flink's keyed event-time window pattern, with no Flink runtime here.
 */

export interface CrossSessionEvent {
  proposalId: string;
  budgetId: string;
  agentId: string;
  timestampMs: number;
  notionalMinor: number;
  triggerHash?: string | null;
}

export interface CrossSessionAnomalyResult {
  scorerVersion: 'cross-session-anomaly-v0.1';
  riskScore: number;
  reviewRecommended: boolean;
  reason: 'insufficient_context' | 'cross_session_pattern' | 'no_cross_session_signal';
  signals: string[];
  eventCount: number;
  distinctAgents10m: number;
  distinctAgents5m: number;
  sharedSourceAgents10m: number;
  nearCapAgents10m: number;
  budgetConcentration: number | null;
  contextComplete: boolean;
}

const WINDOW_MS = 10 * 60 * 1000;
const BURST_WINDOW_MS = 5 * 60 * 1000;
const REVIEW_THRESHOLD = 85;

function incomplete(reason: string, eventCount = 0): CrossSessionAnomalyResult {
  return {
    scorerVersion: 'cross-session-anomaly-v0.1',
    riskScore: 100,
    reviewRecommended: true,
    reason: 'insufficient_context',
    signals: [reason],
    eventCount,
    distinctAgents10m: 0,
    distinctAgents5m: 0,
    sharedSourceAgents10m: 0,
    nearCapAgents10m: 0,
    budgetConcentration: null,
    contextComplete: false,
  };
}

function validEvent(event: CrossSessionEvent | null | undefined): event is CrossSessionEvent {
  return Boolean(event && typeof event.proposalId === 'string' && event.proposalId.trim()
    && typeof event.budgetId === 'string' && event.budgetId.trim()
    && typeof event.agentId === 'string' && event.agentId.trim()
    && Number.isSafeInteger(event.timestampMs) && event.timestampMs >= 0
    && Number.isSafeInteger(event.notionalMinor) && event.notionalMinor > 0);
}

export function scoreSharedBudgetWindow(
  history: readonly CrossSessionEvent[] | null | undefined,
  candidate: CrossSessionEvent | null | undefined,
  historyComplete: boolean,
  sessionBudgetMinor: number,
  perOrderCapMinor: number,
): CrossSessionAnomalyResult {
  if (!Array.isArray(history) || !validEvent(candidate) || typeof historyComplete !== 'boolean'
      || !Number.isSafeInteger(sessionBudgetMinor) || sessionBudgetMinor <= 0
      || !Number.isSafeInteger(perOrderCapMinor) || perOrderCapMinor <= 0) {
    return incomplete('invalid_or_missing_state');
  }

  const windowStart = candidate.timestampMs - WINDOW_MS;
  const burstStart = candidate.timestampMs - BURST_WINDOW_MS;
  const deduped = new Map<string, CrossSessionEvent>();
  let incompleteHistory = !historyComplete;
  for (const event of [...history, candidate]) {
    if (!validEvent(event)) {
      incompleteHistory = true;
      continue;
    }
    const previous = deduped.get(event.proposalId);
    if (previous) {
      if (previous.budgetId !== event.budgetId || previous.agentId !== event.agentId
          || previous.timestampMs !== event.timestampMs || previous.notionalMinor !== event.notionalMinor
          || previous.triggerHash !== event.triggerHash) incompleteHistory = true;
      continue;
    }
    if (typeof event.triggerHash !== 'string' || !event.triggerHash.trim()) incompleteHistory = true;
    deduped.set(event.proposalId, event);
  }
  const rows = [...deduped.values()].filter((event) => event.budgetId === candidate.budgetId
    && event.timestampMs >= windowStart && event.timestampMs <= candidate.timestampMs);
  if (typeof candidate.triggerHash !== 'string' || !candidate.triggerHash.trim()) return incomplete('missing_candidate_trigger_hash', rows.length);
  if (!rows.some((event) => event.proposalId === candidate.proposalId)) {
    return incomplete('candidate_outside_window', rows.length);
  }

  const burstAgents = new Set(rows.filter((event) => event.timestampMs >= burstStart).map((event) => event.agentId));
  const matchingHashAgents = new Set(rows.filter((event) => event.triggerHash === candidate.triggerHash).map((event) => event.agentId));
  const nearCapAgents = new Set(rows.filter((event) => event.notionalMinor >= perOrderCapMinor * 0.90).map((event) => event.agentId));
  const budgetConcentration = rows.reduce((sum, event) => sum + event.notionalMinor, 0) / sessionBudgetMinor;
  const signals: string[] = [];
  let riskScore = 0;
  if (burstAgents.size >= 3) { riskScore += 25; signals.push('multi_agent_burst'); }
  if (matchingHashAgents.size >= 3) { riskScore += 30; signals.push('shared_trigger_across_agents'); }
  if (budgetConcentration >= 0.80) { riskScore += 30; signals.push('shared_budget_concentration'); }
  if (nearCapAgents.size >= 3) { riskScore += 25; signals.push('repeated_near_order_cap'); }
  if (incompleteHistory) signals.push('incomplete_history');

  const reviewRecommended = riskScore >= REVIEW_THRESHOLD || incompleteHistory;
  return {
    scorerVersion: 'cross-session-anomaly-v0.1',
    riskScore: Math.min(110, riskScore),
    reviewRecommended,
    reason: incompleteHistory ? 'insufficient_context' : (reviewRecommended ? 'cross_session_pattern' : 'no_cross_session_signal'),
    signals,
    eventCount: rows.length,
    distinctAgents10m: new Set(rows.map((event) => event.agentId)).size,
    distinctAgents5m: burstAgents.size,
    sharedSourceAgents10m: matchingHashAgents.size,
    nearCapAgents10m: nearCapAgents.size,
    budgetConcentration: Number(budgetConcentration.toFixed(4)),
    contextComplete: !incompleteHistory,
  };
}
