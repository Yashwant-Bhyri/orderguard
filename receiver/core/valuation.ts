// Trusted-price valuation and ticker normalisation for the receiver (layer L8).
//
// The receiver never values an order from the order's own limit price. Notional
// is quantity x a TRUSTED reference price (from the human-signed mandate, or from
// a quote source configured at boot), and the limit price must sit inside a band
// around that trusted price.

export type DenyCode =
  | 'invalid_order'
  | 'non_ascii_symbol'
  | 'invalid_symbol'
  | 'unlisted_symbol'
  | 'side_not_allowed'
  | 'no_trusted_price'
  | 'limit_outside_band'
  | 'per_order_cap'
  | 'daily_cap'
  | 'symbol_daily_cap'
  | 'position_cap'
  | 'order_count_cap'
  | 'mandate_revoked'
  | 'mandate_expired'
  | 'mandate_changed'
  | 'idempotency_conflict'
  | 'approval_invalid'
  | 'not_held';

export type SymbolResult = { ok: true; symbol: string } | { ok: false; code: DenyCode; detail: string };

/** trim, NFKC, uppercase, ASCII-only. Anything that is not plain ASCII after NFKC is denied. */
export function normaliseSymbol(raw: unknown): SymbolResult {
  if (typeof raw !== 'string') return { ok: false, code: 'invalid_symbol', detail: 'symbol must be a string' };
  const folded = raw.trim().normalize('NFKC');
  // Check ASCII before uppercasing: toUpperCase() can map non-ASCII letters (e.g. U+00DF) to ASCII.
  if (/[^\x20-\x7e]/.test(folded)) return { ok: false, code: 'non_ascii_symbol', detail: 'symbol contains non-ASCII or control characters after NFKC' };
  const symbol = folded.toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9.-]{0,11}$/.test(symbol)) return { ok: false, code: 'invalid_symbol', detail: 'symbol is not a plain ticker' };
  return { ok: true, symbol };
}

export type QuoteSource = (symbol: string) => number | undefined;

/** No listed instrument trades above this per unit; a larger "price" is a unit or data error. Python: gate.MAX_TRUSTED_PRICE. */
export const MAX_TRUSTED_PRICE = 1e7;

/** A usable trusted price: a finite number above zero and not absurdly large. Python: gate.trusted_price_ok. */
export function trustedPriceOk(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= MAX_TRUSTED_PRICE;
}

export interface TrustedPriceConfig {
  /** From the signed mandate; keys are normalised on load. */
  referencePrices?: Record<string, number>;
  /** Trusted quote source configured at boot. Used only when the mandate has no price for the symbol. */
  quoteSource?: QuoteSource;
}

export function buildTrustedPrices(config: TrustedPriceConfig): QuoteSource {
  const table = new Map<string, number>();
  for (const [key, value] of Object.entries(config.referencePrices ?? {})) {
    const symbol = normaliseSymbol(key);
    if (!symbol.ok || !trustedPriceOk(value)) {
      throw new Error('mandate referencePrices contains an invalid symbol or price');
    }
    table.set(symbol.symbol, value);
  }
  return (symbol) => {
    const fromMandate = table.get(symbol);
    if (fromMandate !== undefined) return fromMandate;
    const quoted = config.quoteSource?.(symbol);
    return trustedPriceOk(quoted) ? quoted : undefined;
  };
}

export function withinBand(limitPrice: number, trustedPrice: number, priceBandPct: number): boolean {
  return Math.abs(limitPrice - trustedPrice) <= (trustedPrice * priceBandPct) / 100 + 1e-9;
}

/** Notional in integer cents: Math.round(quantity * price * 100) on IEEE doubles (half-cents round up). Python's
 *  orderguard_guard.money.notional_cents is the same rule; python/tests/guard/test_cents_parity.py checks the two agree. */
export function notionalCents(quantity: number, trustedPrice: number): number {
  return Math.round(quantity * trustedPrice * 100);
}
