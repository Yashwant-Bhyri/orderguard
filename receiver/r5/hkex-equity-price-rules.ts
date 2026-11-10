/**
 * HKEX equity price grid for spread table code 01 after Phase 2.
 * Effective date: 2026-08-03. This is an order-price validity rule, not a
 * market-data spread; update it when HKEX changes the applicable schedule.
 */
export const HKEX_EQUITY_SPREAD_TABLE_VERSION = 'code-01-phase-2-2026-08-03' as const;

interface PriceBand {
  maxPriceMills: number;
  tickMills: number;
}

// Prices and ticks are represented in mills (HKD 0.001) so the HKD 0.005
// tick introduced for the 0.50–10.00 band remains exact.
const HKEX_EQUITY_CODE_01_PHASE_2_BANDS: readonly PriceBand[] = [
  { maxPriceMills: 250, tickMills: 1 },
  { maxPriceMills: 10_000, tickMills: 5 },
  { maxPriceMills: 20_000, tickMills: 10 },
  { maxPriceMills: 50_000, tickMills: 20 },
  { maxPriceMills: 100_000, tickMills: 50 },
  { maxPriceMills: 200_000, tickMills: 100 },
  { maxPriceMills: 500_000, tickMills: 200 },
  { maxPriceMills: 1_000_000, tickMills: 500 },
  { maxPriceMills: 2_000_000, tickMills: 1_000 },
  { maxPriceMills: 5_000_000, tickMills: 2_000 },
  { maxPriceMills: 9_995_000, tickMills: 5_000 },
];

/** Return whether an HKD price lies on the current HKEX equity price grid. */
export function isHkexEquityPrice(price: number): boolean {
  if (!Number.isFinite(price) || price <= 0) return false;
  const priceMills = Math.round(price * 1_000);
  if (!Number.isSafeInteger(priceMills) || Math.abs(price - priceMills / 1_000) > 1e-9) return false;
  const band = HKEX_EQUITY_CODE_01_PHASE_2_BANDS.find(({ maxPriceMills }) => priceMills <= maxPriceMills);
  return Boolean(band && priceMills % band.tickMills === 0);
}

/** Check a typed HKD amount in cents against the same HKEX equity price grid. */
export function isHkexEquityPriceMinor(amountMinor: number): boolean {
  if (!Number.isSafeInteger(amountMinor) || amountMinor <= 0) return false;
  return isHkexEquityPrice(amountMinor / 100);
}
