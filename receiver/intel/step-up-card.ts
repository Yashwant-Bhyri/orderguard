/** Fixed presentation copy for a Lock-2 hold. It cannot authorize or amend an order. */
export type StepUpLocale = 'en' | 'zh-Hans' | 'zh-Hant' | 'zh-Hant-yue';

export type StepUpReasonCode =
  | 'provenance_risk'
  | 'account_quote_risk'
  | 'insufficient_context'
  | 'reviewer_timeout'
  | 'reviewer_unavailable'
  | 'triage_unknown'
  | 'untrusted_memory_authority';

export interface StepUpCard {
  decision: 'step_up';
  reasonCode: StepUpReasonCode;
  locale: StepUpLocale;
  title: string;
  message: string;
  nextAction: string;
  orderSubmitted: false;
  ledgerEffect: 'none';
}

const COPY: Record<StepUpLocale, Record<StepUpReasonCode, { title: string; message: string; nextAction: string }>> = {
  en: {
    provenance_risk: {
      title: 'Held for human review',
      message: 'The trigger source has a provenance concern.',
      nextAction: 'Review this held order in the separate approval flow. Do not retry unless review approves.',
    },
    account_quote_risk: {
      title: 'Held for human review',
      message: 'The account or signed quote needs review.',
      nextAction: 'Review this held order in the separate approval flow. Do not retry unless review approves.',
    },
    insufficient_context: {
      title: 'Held for human review',
      message: 'There is not enough trusted context to clear this order.',
      nextAction: 'Review this held order in the separate approval flow. Do not retry unless review approves.',
    },
    reviewer_timeout: {
      title: 'Held for human review',
      message: 'The semantic reviewer timed out.',
      nextAction: 'Review this held order in the separate approval flow. Do not retry unless review approves.',
    },
    reviewer_unavailable: {
      title: 'Held for human review',
      message: 'The semantic reviewer is unavailable.',
      nextAction: 'Review this held order in the separate approval flow. Do not retry unless review approves.',
    },
    triage_unknown: {
      title: 'Held for human review',
      message: 'Current source triage is unavailable.',
      nextAction: 'Review this held order in the separate approval flow. Do not retry unless review approves.',
    },
    untrusted_memory_authority: {
      title: 'Held for human review',
      message: 'A saved preference cannot establish authority for this order.',
      nextAction: 'Review this held order in the separate approval flow. Do not retry unless review approves.',
    },
  },
  'zh-Hans': {
    provenance_risk: {
      title: '订单已暂停，等待人工审核',
      message: '触发信息的来源可信度需要核实。',
      nextAction: '请在独立的审批流程中审核此订单；获批前请勿重试。',
    },
    account_quote_risk: {
      title: '订单已暂停，等待人工审核',
      message: '账户状态或已签署的报价需要审核。',
      nextAction: '请在独立的审批流程中审核此订单；获批前请勿重试。',
    },
    insufficient_context: {
      title: '订单已暂停，等待人工审核',
      message: '可信上下文不足，无法确认此订单。',
      nextAction: '请在独立的审批流程中审核此订单；获批前请勿重试。',
    },
    reviewer_timeout: {
      title: '订单已暂停，等待人工审核',
      message: '语义审核服务超时。',
      nextAction: '请在独立的审批流程中审核此订单；获批前请勿重试。',
    },
    reviewer_unavailable: {
      title: '订单已暂停，等待人工审核',
      message: '语义审核服务暂不可用。',
      nextAction: '请在独立的审批流程中审核此订单；获批前请勿重试。',
    },
    triage_unknown: {
      title: '订单已暂停，等待人工审核',
      message: '当前无法完成触发信息来源核查。',
      nextAction: '请在独立的审批流程中审核此订单；获批前请勿重试。',
    },
    untrusted_memory_authority: {
      title: '订单已暂停，等待人工审核',
      message: '已保存的偏好不能证明此订单已获授权。',
      nextAction: '请在独立的审批流程中审核此订单；获批前请勿重试。',
    },
  },
  'zh-Hant': {
    provenance_risk: {
      title: '訂單已暫停，等待人工審核',
      message: '觸發資訊的來源可信度需要核實。',
      nextAction: '請在獨立的審批流程中審核此訂單；獲批前請勿重試。',
    },
    account_quote_risk: {
      title: '訂單已暫停，等待人工審核',
      message: '帳戶狀態或已簽署的報價需要審核。',
      nextAction: '請在獨立的審批流程中審核此訂單；獲批前請勿重試。',
    },
    insufficient_context: {
      title: '訂單已暫停，等待人工審核',
      message: '可信上下文不足，無法確認此訂單。',
      nextAction: '請在獨立的審批流程中審核此訂單；獲批前請勿重試。',
    },
    reviewer_timeout: {
      title: '訂單已暫停，等待人工審核',
      message: '語義審核服務逾時。',
      nextAction: '請在獨立的審批流程中審核此訂單；獲批前請勿重試。',
    },
    reviewer_unavailable: {
      title: '訂單已暫停，等待人工審核',
      message: '語義審核服務暫時無法使用。',
      nextAction: '請在獨立的審批流程中審核此訂單；獲批前請勿重試。',
    },
    triage_unknown: {
      title: '訂單已暫停，等待人工審核',
      message: '目前無法完成觸發資訊來源核查。',
      nextAction: '請在獨立的審批流程中審核此訂單；獲批前請勿重試。',
    },
    untrusted_memory_authority: {
      title: '訂單已暫停，等待人工審核',
      message: '已儲存的偏好不能證明此訂單已獲授權。',
      nextAction: '請在獨立的審批流程中審核此訂單；獲批前請勿重試。',
    },
  },
  'zh-Hant-yue': {
    provenance_risk: {
      title: '訂單已暫停，等候人工審核',
      message: '觸發資訊嘅來源可信度需要核實。',
      nextAction: '請喺獨立審批流程審核呢張訂單；未獲批之前唔好重試。',
    },
    account_quote_risk: {
      title: '訂單已暫停，等候人工審核',
      message: '帳戶狀態或者已簽署報價需要審核。',
      nextAction: '請喺獨立審批流程審核呢張訂單；未獲批之前唔好重試。',
    },
    insufficient_context: {
      title: '訂單已暫停，等候人工審核',
      message: '可信上下文不足，暫時未能確認呢張訂單。',
      nextAction: '請喺獨立審批流程審核呢張訂單；未獲批之前唔好重試。',
    },
    reviewer_timeout: {
      title: '訂單已暫停，等候人工審核',
      message: '語義審核服務逾時。',
      nextAction: '請喺獨立審批流程審核呢張訂單；未獲批之前唔好重試。',
    },
    reviewer_unavailable: {
      title: '訂單已暫停，等候人工審核',
      message: '語義審核服務暫時用唔到。',
      nextAction: '請喺獨立審批流程審核呢張訂單；未獲批之前唔好重試。',
    },
    triage_unknown: {
      title: '訂單已暫停，等候人工審核',
      message: '目前無法完成觸發資訊來源核查。',
      nextAction: '請喺獨立審批流程審核呢張訂單；未獲批之前唔好重試。',
    },
    untrusted_memory_authority: {
      title: '訂單已暫停，等候人工審核',
      message: '已儲存嘅偏好唔能夠證明呢張訂單已獲授權。',
      nextAction: '請喺獨立審批流程審核呢張訂單；未獲批之前唔好重試。',
    },
  },
};

const REASON_CODES = new Set<StepUpReasonCode>([
  'provenance_risk', 'account_quote_risk', 'insufficient_context', 'reviewer_timeout',
  'reviewer_unavailable', 'triage_unknown', 'untrusted_memory_authority',
]);

/** Parse only the browser's explicit locale preference; never inspect trigger or model text. */
export function stepUpLocaleFromAcceptLanguage(header: string | undefined): StepUpLocale {
  if (!header || header.length > 512) return 'en';
  const entries = header.split(',').map((item, index) => {
    const [rawTag, ...params] = item.trim().split(';');
    const tag = rawTag?.trim().toLowerCase() ?? '';
    const qParam = params.find((param) => /^\s*q\s*=/.test(param));
    const parsedQ = qParam ? Number(qParam.split('=')[1]) : 1;
    const q = Number.isFinite(parsedQ) && parsedQ >= 0 && parsedQ <= 1 ? parsedQ : 0;
    return { tag, q, index };
  }).filter((entry) => entry.q > 0).sort((a, b) => b.q - a.q || a.index - b.index);

  for (const { tag } of entries) {
    if (tag === 'yue' || tag.startsWith('yue-') || tag === 'zh-hant-yue') return 'zh-Hant-yue';
    if (tag === 'zh-hant' || tag.startsWith('zh-hant-') || ['zh-tw', 'zh-hk', 'zh-mo'].includes(tag)) return 'zh-Hant';
    if (tag === 'zh' || tag === 'zh-hans' || tag.startsWith('zh-hans-') || tag === 'zh-cn' || tag === 'zh-sg') return 'zh-Hans';
    if (tag === 'en' || tag.startsWith('en-')) return 'en';
  }
  return 'en';
}

/** Fixed strings only; this card is display copy and leaves the hold and audit untouched. */
export function buildStepUpCard(reasonCode: string, locale: StepUpLocale): StepUpCard {
  const normalizedReason: StepUpReasonCode = REASON_CODES.has(reasonCode as StepUpReasonCode)
    ? reasonCode as StepUpReasonCode : 'insufficient_context';
  return {
    decision: 'step_up',
    reasonCode: normalizedReason,
    locale,
    ...COPY[locale][normalizedReason],
    orderSubmitted: false,
    ledgerEffect: 'none',
  };
}
