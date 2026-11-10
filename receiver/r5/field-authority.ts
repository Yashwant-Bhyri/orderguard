/** Signed authority modes for order fields that an agent may select. */
export type OrderFieldAuthorityModeV1 = 'exact_request_only' | 'autonomous_within_mandate';

export interface OrderFieldAuthorityV1 {
  version: 1;
  quantity: OrderFieldAuthorityModeV1;
  limitPrice: OrderFieldAuthorityModeV1;
}

export interface OwnerAuthorizedPreferenceOrderV1 {
  market: 'US' | 'HK';
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  orderType: 'market' | 'limit';
  limitPrice: number | null;
  session: string;
  timeInForce: 'day' | 'gtc';
}

export interface OwnerAuthorizedPreferenceClaimsV1 {
  version: 1;
  issuer: 'orderguard.policy-issuer';
  preferenceId: string;
  preferenceKey: string;
  subject: 'synthetic-user:candidate-demo';
  tenant: 'synthetic-tenant:demo';
  createdAt: number;
  expiresAt: number;
  order: OwnerAuthorizedPreferenceOrderV1;
  approvalMethod: 'webauthn-passkey-v1';
  approvalEvidenceHash: string;
}

export interface SignedOwnerAuthorizedPreferenceV1 {
  claims: OwnerAuthorizedPreferenceClaimsV1;
  signature: string;
}

export function isOrderFieldAuthorityV1(value: unknown): value is OrderFieldAuthorityV1 {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return Object.keys(record).length === 3
    && record.version === 1
    && (record.quantity === 'exact_request_only' || record.quantity === 'autonomous_within_mandate')
    && (record.limitPrice === 'exact_request_only' || record.limitPrice === 'autonomous_within_mandate');
}

function normalize(text: string): string {
  return text.normalize('NFKC').replaceAll('_', '-').replace(/[’]/g, "'");
}

export function isOwnerPreferenceKey(value: unknown): value is string {
  return typeof value === 'string' && /^[a-z][a-z0-9_]{1,63}$/.test(value);
}

/** Only a key explicitly labeled as a saved note/preference in current user text can select an artifact. */
export function referencedOwnerPreferenceKey(requestText: string): string | null {
  const value = requestText.normalize('NFKC').replace(/[’]/g, "'");
  const match = value.match(/\b(?:saved\s+(?:account\s+)?(?:preference|note)|account\s+note|preference\s+key)\s*(?:called|named|is|:|=)?\s*[`"']?([a-z][a-z0-9_]{1,63})(?:[`"']|(?=[\s.,;!?)]|$))/i);
  return match && isOwnerPreferenceKey(match[1]) ? match[1] : null;
}

export function ownerPreferenceMatchesOrder(
  preference: OwnerAuthorizedPreferenceClaimsV1 | null | undefined,
  order: Partial<OwnerAuthorizedPreferenceOrderV1>,
): boolean {
  if (!preference || preference.version !== 1 || !isOwnerPreferenceKey(preference.preferenceKey)) return false;
  const expected = preference.order;
  return order.market === expected.market && order.symbol === expected.symbol && order.side === expected.side
    && order.quantity === expected.quantity && order.orderType === expected.orderType
    && order.limitPrice === expected.limitPrice && order.session === expected.session
    && order.timeInForce === expected.timeInForce;
}

export function requestSelectsOwnerPreferenceForOrder(
  requestText: string,
  preference: OwnerAuthorizedPreferenceClaimsV1 | null | undefined,
  order: Partial<OwnerAuthorizedPreferenceOrderV1>,
): boolean {
  if (!preference || referencedOwnerPreferenceKey(requestText) !== preference.preferenceKey
    || !requestHasAffirmativeOrderAction(normalize(requestText))) return false;
  const value = normalize(requestText);
  const escapedSymbol = preference.order.symbol.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const symbolMentioned = new RegExp('(^|[^A-Z0-9])' + escapedSymbol + '([^A-Z0-9]|$)', 'i').test(value);
  const sideMentioned = preference.order.side === 'buy'
    ? /\b(?:buy|purchase)\b|买入|買入/i.test(value)
    : /\b(?:sell|dispose)\b|卖出|賣出/i.test(value);
  const sideConflicts = preference.order.side === 'buy'
    ? /\b(?:sell|dispose)\b|卖出|賣出/i.test(value)
    : /\b(?:buy|purchase)\b|买入|買入/i.test(value);
  if (!symbolMentioned || !sideMentioned || sideConflicts || !ownerPreferenceMatchesOrder(preference, order)) return false;
  if (explicitTrustedQuantity(value) !== null && explicitTrustedQuantity(value) !== preference.order.quantity) return false;
  if (explicitTrustedLimitPrice(value) !== null && explicitTrustedLimitPrice(value) !== preference.order.limitPrice) return false;
  return true;
}

function explicitTrustedQuantity(value: string): number | null {
  const number = '(?<![\\d.])([0-9]+(?:,[0-9]{3})*(?:\\.[0-9]+)?)(?![\\d.])';
  const patterns = [
    // Do not scan from an order verb to an arbitrary later number: a limit
    // price later in "BUY 10 VLTA LIMIT HKD 48.20" is not the quantity.
    new RegExp('\\b(?:buy|purchase|sell|dispose|place|submit)\\b\\s+(?:(?:exactly|quantity\\s+(?:of\\s+)?)\\s+)?' + number, 'gi'),
    new RegExp('\\bquantity\\s*(?:of|is|=|:)\\s*' + number, 'gi'),
    // In Chinese requests the limit price may appear between the buy verb and
    // quantity. Bind quantity to an explicit share unit so the price cannot win.
    new RegExp('(?:买入|買入|卖出|賣出|下单|下單)[^。！？;\\n]{0,80}?' + number + '\\s*(?:股(?:份)?|shares?)', 'gi'),
    new RegExp('(?:数量|股数)\\s*(?:为|是|[:=])\\s*' + number, 'gi'),
  ];
  for (const pattern of patterns) {
    const match = pattern.exec(value);
    if (match?.[1]) return Number(match[1].replaceAll(',', ''));
  }
  return null;
}

function limitPricePatterns(): RegExp[] {
  // A final sentence period is punctuation, not a decimal continuation.
  // Still reject another digit or a dot followed by a digit so a longer
  // numeric token cannot be accepted as a shorter price.
  const number = '(?<![\\d.])([0-9]+(?:\\.[0-9]+)?)(?!\\d|\\.\\d)';
  const currency = '(?:(?:HKD|HK\\$|USD)\\s*)?\\$?\\s*';
  return [
    new RegExp('\\b(?:limit(?:\\s+price)?(?:\\s+at)?|at)\\s*' + currency + number, 'gi'),
    new RegExp('(?:限价|限價)(?:价格|價格)?\\s*(?:为|是|[:=])?\\s*' + currency + number, 'gi'),
  ];
}

function explicitTrustedLimitPrice(value: string): number | null {
  const patterns = [
    ...limitPricePatterns(),
  ];
  for (const pattern of patterns) {
    const match = pattern.exec(value);
    if (match) return Number(match[1]);
  }
  return null;
}

function trustedRequestText(requestText: string, untrustedContext: string[]): string {
  return untrustedContext.reduce((text, source) => source.trim() ? text.replaceAll(normalize(source), '') : text, normalize(requestText));
}

function hasMatchingNumber(text: string, expected: number, patterns: RegExp[]): boolean {
  if (!Number.isFinite(expected) || expected <= 0) return false;
  return patterns.some((pattern) => {
    for (const match of text.matchAll(pattern)) {
      const value = Number(match[1]);
      if (Number.isFinite(value) && value === expected) return true;
    }
    return false;
  });
}

function requestHasAffirmativeOrderAction(text: string): boolean {
  if (/\b(?:do not|don't|never|avoid|without|hypothetical|what if|suppose|for example|example only)\b[^.!?;\n]{0,100}\b(?:buy|purchase|sell|dispose|place|submit|order)\b/i.test(text)
    || /\b(?:should|would|could|can|may)\s+(?:i|we)\s+(?:buy|purchase|sell|dispose|place|submit|order)\b/i.test(text)
    || /["“‘][^"”’]{0,180}\b(?:buy|purchase|sell|dispose|place|submit|order)\b[^"”’]{0,180}["”’]/i.test(text)
    || /(?:不要|不需要|無需|无需|不想|不打算|未要求).{0,30}(?:买入|買入|卖出|賣出|下单|下單|订单|訂單)/i.test(text)) return false;
  return true;
}

export function currentRequestExplicitlyAuthorizesQuantity(
  requestText: string,
  quantity: number,
  untrustedContext: string[] = [],
): boolean {
  const value = trustedRequestText(requestText, untrustedContext);
  if (!requestHasAffirmativeOrderAction(value)) return false;
  const number = '(?<![\\d.])([0-9]+(?:,[0-9]{3})*(?:\\.[0-9]+)?)(?![\\d.])';
  return hasMatchingNumber(value, quantity, [
    // Quantity must be the number attached to the action verb (or use one of
    // the explicit quantity forms below), never a later price or limit.
    new RegExp('\\b(?:buy|purchase|sell|dispose|place|submit)\\b\\s+(?:(?:exactly|quantity\\s+(?:of\\s+)?)\\s+)?' + number, 'gi'),
    new RegExp('\\bquantity\\s*(?:of|is|=|:)\\s*' + number, 'gi'),
    // The price can precede the share count after the Chinese action verb.
    // Require a share unit to avoid treating that price as quantity.
    new RegExp('(?:买入|買入|卖出|賣出|下单|下單)[^。！？;\\n]{0,80}?' + number + '\\s*(?:股(?:份)?|shares?)', 'gi'),
    new RegExp('(?:数量|股数)\\s*(?:为|是|[:=])\\s*' + number, 'gi'),
  ]);
}

export function currentRequestExplicitlyAuthorizesLimitPrice(
  requestText: string,
  limitPrice: number,
  untrustedContext: string[] = [],
): boolean {
  const value = trustedRequestText(requestText, untrustedContext);
  if (!requestHasAffirmativeOrderAction(value)) return false;
  return hasMatchingNumber(value, limitPrice, limitPricePatterns());
}

export function requiresUserAuthorizedQuantity(text: string): boolean {
  const value = normalize(text);
  const quantity = /\b(?:quantity|share quantity|share size|number of shares)\b|(?:数量|股数)/i.test(value);
  const userAuthorization = /\buser[- ]authorized\b|\buser[- ]approved\b|\bauthorized by (?:the )?user\b|\bapproved by (?:me|the user)\b|用户授权|经用户批准/i.test(value);
  const confirmation = /\bask me first\b|\bask before\b|\bconfirm with me\b|\bget my approval\b|\bseek my approval\b|先问我|先向我确认|请先确认/i.test(value);
  return quantity && userAuthorization && confirmation;
}

/**
 * Raw memory and research text cannot prove quantity authorization. Callers may pass true
 * only after the policy signature, expiry, key reference, and full order match were verified.
 */
export function userAuthorizedQuantityHoldReason(
  requestText: string,
  proposedQuantity: number | null,
  untrustedContext: string[] = [],
  ownerAuthorizedPreferenceMatches = false,
): string | null {
  if (!requiresUserAuthorizedQuantity(requestText)) return null;
  if (ownerAuthorizedPreferenceMatches) return null;
  if (proposedQuantity !== null && currentRequestExplicitlyAuthorizesQuantity(requestText, proposedQuantity, untrustedContext)) return null;
  return untrustedContext.length > 0
    ? 'The request requires a user-authorized quantity. Untrusted notes or research cannot establish that authorization; ask the user to confirm the exact quantity.'
    : 'The request requires a user-authorized quantity, but the current request contains no exact authorized quantity. Ask the user to confirm it.';
}
