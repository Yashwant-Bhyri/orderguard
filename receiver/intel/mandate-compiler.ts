/**
 * Deterministic validator for draft-only bilingual mandate compilation.
 * This v0 accepts only the fixed synthetic HK/HKD MANDATE-M1 subset. It never
 * signs, activates, or emits an authorization; the model output is untrusted.
 */

export interface MandateDraftV0 {
  market: 'HK' | 'US' | 'unknown';
  currency: 'HKD' | 'USD' | 'unknown';
  allowed_symbols: string[];
  side: 'buy' | 'sell' | 'unknown';
  max_quantity_per_order: number | null;
  order_type: 'limit' | 'market' | 'unknown';
  session: 'hk_regular' | 'us_regular' | 'unknown';
  time_in_force: 'day' | 'gtc' | 'unknown';
  max_order_notional_hkd: number | null;
  max_session_notional_hkd: number | null;
  limit_price_band_bps: number | null;
  limit_price_reference: 'signed_quote' | 'unknown';
  expiry_days: number | null;
  unresolved_fields: string[];
  unsupported_requirements: string[];
  intent_summary: string;
}

export interface MandateDraftValidationV0 {
  valid: boolean;
  errors: string[];
  schema_version: 'mandate-draft-v0';
  signing_required: true;
  signed: false;
  authorization_created: false;
  draft?: MandateDraftV0;
}

const SYMBOLS = ['VLTA', 'ACMX', 'BRSK'] as const;
const REQUIRED_KEYS = [
  'market', 'currency', 'allowed_symbols', 'side', 'max_quantity_per_order', 'order_type', 'session',
  'time_in_force', 'max_order_notional_hkd', 'max_session_notional_hkd', 'limit_price_band_bps',
  'limit_price_reference', 'expiry_days', 'unresolved_fields', 'unsupported_requirements', 'intent_summary',
];
const KNOWN_UPPER_TOKENS = new Set([
  ...SYMBOLS, 'HK', 'HKD', 'USD', 'BUY', 'SELL', 'LIMIT', 'MARKET', 'DAY', 'GTC', 'BPS',
]);

interface IntentConstraints {
  symbols: string[];
  side: 'buy' | 'sell';
  quantity: number;
  orderType: 'limit' | 'market';
  session: 'hk_regular';
  timeInForce: 'day';
  orderNotional: number;
  sessionNotional: number;
  bandBps: number;
  expiryDays: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function boundedInteger(value: unknown, field: string, low: number, high: number, errors: string[]): value is number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < low || value > high) {
    errors.push(`${field} must be an integer in [${low},${high}]`);
    return false;
  }
  return true;
}

function parseIntentConstraints(intent: string): { constraints: IntentConstraints | null; errors: string[] } {
  const errors: string[] = [];
  const symbols = SYMBOLS.filter((symbol) => new RegExp(`\\b${symbol}\\b`, 'i').test(intent));
  if (!symbols.length) errors.push('intent must name at least one supported fictional symbol');

  const unknownTokens = [...new Set(intent.match(/(?<![A-Z0-9])[A-Z]{2,6}(?![A-Z0-9])/g) ?? [])]
    .filter((token) => !KNOWN_UPPER_TOKENS.has(token)).sort();
  if (unknownTokens.length) errors.push(`unrecognized uppercase symbol-like token(s): ${unknownTokens.join(', ')}`);
  if (/\bUS\s+(?:market|equities|stocks?)\b/i.test(intent) || /\bUSD\b/i.test(intent) || /美元/.test(intent)) {
    errors.push('intent includes unsupported non-HK market or currency scope');
  }
  if (!(/\bHK\s+regular\s+session\b/i.test(intent) || /香港正常交易時段|香港正常交易时段/.test(intent))) {
    errors.push('intent must explicitly state HK regular session');
  }
  if (!(/\bHKD\b/i.test(intent) || /港幣|港币/.test(intent))) errors.push('intent must explicitly state HKD currency');

  const expiryMatch = intent.match(/\b(?:next|future)\s+(\d+)\s+days?\b/i) ?? intent.match(/(?:未來|未来)\s*(\d+)\s*天/);
  const expiryDays = expiryMatch ? Number(expiryMatch[1]) : null;
  if (expiryDays === null) errors.push('intent expiry must use the explicit v0 EN/中文 duration grammar');

  const firstSymbol = symbols[0] ?? 'VLTA';
  const quantityMatch = intent.match(new RegExp(`at most\\s+(\\d[\\d,]*)\\s+${firstSymbol}\\s+shares?\\s+per order`, 'i'))
    ?? intent.match(/每單最多\s*(\d[\d,]*)\s*股|每单最多\s*(\d[\d,]*)\s*股/);
  const quantityText = quantityMatch?.[1] ?? quantityMatch?.[2];
  const quantity = quantityText ? Number(quantityText.replaceAll(',', '')) : null;
  if (quantity === null) errors.push("intent quantity must explicitly say 'at most N SYMBOL shares per order' or '每單最多 N 股'");

  const orderMatch = intent.match(/\bHKD\s*([\d,]+)\s+per order\b/i)
    ?? intent.match(/每單最多港幣\s*([\d,]+)\s*元|每单最多港币\s*([\d,]+)\s*元/);
  const orderText = orderMatch?.[1] ?? orderMatch?.[2];
  const orderNotional = orderText ? Number(orderText.replaceAll(',', '')) : null;
  if (orderNotional === null) errors.push('intent must state the per-order HKD cap');

  const sessionMatch = intent.match(/\bHKD\s*([\d,]+)\s+(?:total\s+)?per session\b/i)
    ?? intent.match(/每個交易時段合計最多港幣\s*([\d,]+)\s*元|每个交易时段合计最多港币\s*([\d,]+)\s*元/);
  const sessionText = sessionMatch?.[1] ?? sessionMatch?.[2];
  const sessionNotional = sessionText ? Number(sessionText.replaceAll(',', '')) : null;
  if (sessionNotional === null) errors.push('intent must state the per-session HKD cap');

  const bandMatch = intent.match(/\bwithin\s+(\d+(?:\.\d+)?)%/i)
    ?? intent.match(/(\d+(?:\.\d+)?)%\s*(?:範圍內|范围内)/);
  const bandValue = bandMatch ? Number(bandMatch[1] ?? bandMatch[2]) : null;
  const bandBps = bandValue === null ? null : Math.round(bandValue * 100);
  if (bandBps === null) errors.push('intent must state the signed-quote price band');
  if (!(/\bsigned quote\b/i.test(intent) || /已簽署報價|已签署报价/.test(intent))) {
    errors.push('intent must explicitly anchor its price band to a signed quote');
  }

  const sideWords = intent.match(/\b(buy|purchase|sell|short)\b/gi) ?? [];
  const sides = new Set(sideWords.map((word) => /^(?:buy|purchase)$/i.test(word) ? 'buy' : 'sell'));
  if (/買入|买入|買|买/.test(intent)) sides.add('buy');
  if (/賣出|卖出/.test(intent)) sides.add('sell');
  if (sides.size !== 1) errors.push('intent must state exactly one unambiguous buy/sell side');
  const side = sides.size === 1 ? [...sides][0] as 'buy' | 'sell' : null;

  let orderType: 'limit' | 'market' | null = null;
  if (/\blimit orders? only\b/i.test(intent) || /限價單|限价单/.test(intent)) orderType = 'limit';
  else if (/\bmarket orders? only\b/i.test(intent)) orderType = 'market';
  if (!orderType) errors.push('intent must explicitly state limit-only order type');
  if (!(/\bday only\b/i.test(intent) || /當日有效|当日有效/.test(intent))) {
    errors.push('intent must explicitly state day-only time in force');
  }

  if (errors.length || expiryDays === null || quantity === null || orderNotional === null
    || sessionNotional === null || bandBps === null || side === null || orderType === null) {
    return { constraints: null, errors };
  }
  return {
    constraints: {
      symbols, side, quantity, orderType, session: 'hk_regular', timeInForce: 'day',
      orderNotional, sessionNotional, bandBps, expiryDays,
    },
    errors: [],
  };
}

/** Validate a structured model draft against both the synthetic envelope and explicit intent. */
export function validateMandateDraftV0(intent: string, candidate: unknown): MandateDraftValidationV0 {
  const errors: string[] = [];
  if (!isRecord(candidate)) {
    return { valid: false, errors: ['draft must be an object'], schema_version: 'mandate-draft-v0',
      signing_required: true, signed: false, authorization_created: false };
  }
  if (Object.keys(candidate).length !== REQUIRED_KEYS.length || REQUIRED_KEYS.some((key) => !(key in candidate))) {
    errors.push('draft keys must exactly match mandate-draft-v0; extra properties are rejected');
  }
  if (candidate.market !== 'HK') errors.push('market must be HK');
  if (candidate.currency !== 'HKD') errors.push('currency must be HKD');
  const symbols = candidate.allowed_symbols;
  if (!Array.isArray(symbols) || symbols.length === 0 || symbols.some((item) => typeof item !== 'string')
    || new Set(symbols).size !== symbols.length || symbols.some((item) => !SYMBOLS.includes(item as typeof SYMBOLS[number]))) {
    errors.push('allowed_symbols must be a non-empty unique subset of the fictional HK allowlist');
  }
  if (candidate.side !== 'buy') errors.push('only buy is supported by the current MANDATE-M1 envelope');
  if (candidate.order_type !== 'limit') errors.push('order_type must be limit');
  if (candidate.session !== 'hk_regular') errors.push('session must be hk_regular');
  if (candidate.time_in_force !== 'day') errors.push('time_in_force must be day');
  if (candidate.limit_price_reference !== 'signed_quote') errors.push('limit_price_reference must be signed_quote');
  boundedInteger(candidate.max_quantity_per_order, 'max_quantity_per_order', 1, 10_000, errors);
  boundedInteger(candidate.max_order_notional_hkd, 'max_order_notional_hkd', 1, 40_000, errors);
  boundedInteger(candidate.max_session_notional_hkd, 'max_session_notional_hkd', 1, 40_000, errors);
  boundedInteger(candidate.limit_price_band_bps, 'limit_price_band_bps', 0, 200, errors);
  boundedInteger(candidate.expiry_days, 'expiry_days', 1, 30, errors);
  if (!Array.isArray(candidate.unresolved_fields) || candidate.unresolved_fields.length !== 0) {
    errors.push('unresolved fields must be empty before human review');
  }
  if (!Array.isArray(candidate.unsupported_requirements) || candidate.unsupported_requirements.length !== 0) {
    errors.push('unsupported requirements must be empty');
  }
  if (typeof candidate.intent_summary !== 'string' || !candidate.intent_summary.trim()) {
    errors.push('intent_summary must be non-empty');
  }

  const parsed = parseIntentConstraints(intent);
  errors.push(...parsed.errors);
  const requested = parsed.constraints;
  if (requested) {
    if (!Array.isArray(symbols) || symbols.some((symbol) => !requested.symbols.includes(String(symbol)))) {
      errors.push('allowed_symbols may only be a subset of symbols explicit in the intent');
    }
    if (candidate.side !== requested.side) errors.push('side must preserve the explicit intent value');
    if (candidate.order_type !== requested.orderType) errors.push('order_type must preserve the explicit intent value');
    if (candidate.session !== requested.session) errors.push('session must preserve the explicit intent value');
    if (candidate.time_in_force !== requested.timeInForce) errors.push('time_in_force must preserve the explicit intent value');
    if (candidate.limit_price_reference !== 'signed_quote') errors.push('limit_price_reference must preserve the explicit intent value');
    if (typeof candidate.max_quantity_per_order !== 'number' || candidate.max_quantity_per_order > requested.quantity) {
      errors.push('max_quantity_per_order may not exceed the explicit intent limit');
    }
    for (const [key, limit] of [
      ['max_order_notional_hkd', requested.orderNotional],
      ['max_session_notional_hkd', requested.sessionNotional],
      ['limit_price_band_bps', requested.bandBps],
      ['expiry_days', requested.expiryDays],
    ] as const) {
      if (typeof candidate[key] !== 'number' || candidate[key] > limit) errors.push(`${key} may not exceed the explicit intent limit`);
    }
    const orderCap = candidate.max_order_notional_hkd;
    const sessionCap = candidate.max_session_notional_hkd;
    if (typeof orderCap === 'number' && typeof sessionCap === 'number' && orderCap > sessionCap) {
      errors.push('max_order_notional_hkd may not exceed max_session_notional_hkd');
    }
  }

  const uniqueErrors = [...new Set(errors)];
  const valid = uniqueErrors.length === 0;
  return {
    valid, errors: uniqueErrors, schema_version: 'mandate-draft-v0',
    signing_required: true, signed: false, authorization_created: false,
    ...(valid ? { draft: candidate as unknown as MandateDraftV0 } : {}),
  };
}
