import { createHash, createPublicKey, verify, type KeyObject } from 'node:crypto';
import type { MandateScope } from './receiver-core.js';
import { normaliseSymbol } from './valuation.js';

export interface PaperPolicyState {
  ledgerId: string;
  parentId: string;
  revision: number;
  activeId: string;
  scope: MandateScope;
}

export const digest = (value: Buffer) => createHash('sha256').update(value).digest('hex');

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Expected a policy object');
  return value as Record<string, unknown>;
}

function decode(value: unknown, length?: number): Buffer {
  if (typeof value !== 'string') throw new Error('Expected base64 policy data');
  const bytes = Buffer.from(value, 'base64');
  if (bytes.length === 0 || bytes.toString('base64') !== value || (length !== undefined && bytes.length !== length)) {
    throw new Error('Invalid base64 policy data');
  }
  return bytes;
}

function verifiedBody(envelope: unknown, key: KeyObject) {
  const { payload, signature } = object(envelope);
  const bytes = decode(payload);
  if (!verify(null, bytes, key, decode(signature, 64))) throw new Error('Owner signature did not verify');
  return { body: object(JSON.parse(bytes.toString('utf8'))), digest: digest(bytes) };
}

function money(value: unknown, allowZero = false): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < (allowZero ? 0 : 0.01)
      || value > 1e12 || Number(value.toFixed(2)) !== value) throw new Error('Invalid policy amount');
  return value;
}

function symbol(value: unknown): value is string {
  const checked = normaliseSymbol(value);
  return checked.ok && checked.symbol === value;
}

function parseScope(body: Record<string, unknown>): MandateScope {
  const supported = new Set(['symbols', 'sides', 'maxOrderNotionalUsd', 'maxDailyNotionalUsd', 'priceBandPct',
    'expiresAt', 'referencePrices', 'stepUpAboveUsd', 'maxSymbolDailyNotionalUsd', 'maxPositionUsd', 'maxOrdersPerDay']);
  if (Object.keys(body).some((key) => !supported.has(key))) throw new Error('Unsupported policy field');
  const { symbols, sides, priceBandPct, expiresAt } = body;
  if (!Array.isArray(symbols) || symbols.length < 1 || symbols.length > 100 || !symbols.every(symbol)
      || new Set(symbols).size !== symbols.length) throw new Error('Invalid policy symbols');
  if (!Array.isArray(sides) || sides.length < 1 || !sides.every((s) => s === 'buy' || s === 'sell')
      || new Set(sides).size !== sides.length) throw new Error('Invalid policy sides');
  if (typeof priceBandPct !== 'number' || !Number.isFinite(priceBandPct) || priceBandPct < 0 || priceBandPct > 100) {
    throw new Error('Invalid policy price band');
  }
  if (typeof expiresAt !== 'string' || !/T.*(?:Z|[+-]\d\d:\d\d)$/.test(expiresAt) || !Number.isFinite(Date.parse(expiresAt))) {
    throw new Error('Invalid policy expiration');
  }
  const maxOrderNotionalUsd = money(body.maxOrderNotionalUsd);
  const maxDailyNotionalUsd = money(body.maxDailyNotionalUsd);
  if (maxOrderNotionalUsd > maxDailyNotionalUsd) throw new Error('Per-order cap exceeds the daily cap');
  const refs = Object.entries(object(body.referencePrices === undefined ? {} : body.referencePrices));
  const referencePrices: Record<string, number> = {};
  for (const [ticker, value] of refs) {
    if (!symbols.includes(ticker) || typeof value !== 'number' || !Number.isFinite(value) || value <= 0 || value > 1e12) {
      throw new Error('Invalid policy reference price');
    }
    referencePrices[ticker] = value;
  }
  const stepUpThresholdUsd = body.stepUpAboveUsd === undefined ? undefined : money(body.stepUpAboveUsd, true);
  const maxSymbolDailyNotionalUsd = body.maxSymbolDailyNotionalUsd === undefined ? undefined : money(body.maxSymbolDailyNotionalUsd);
  const maxPositionUsd = body.maxPositionUsd === undefined ? undefined : money(body.maxPositionUsd);
  const orders = body.maxOrdersPerDay;
  if (orders !== undefined && (typeof orders !== 'number' || !Number.isSafeInteger(orders) || orders < 1 || orders > 1e9)) {
    throw new Error('Invalid policy order count');
  }
  return { symbols, sides, maxOrderNotionalUsd, maxDailyNotionalUsd, priceBandPct, expiresAt, referencePrices,
    ...(stepUpThresholdUsd === undefined ? {} : { stepUpThresholdUsd }),
    ...(maxSymbolDailyNotionalUsd === undefined ? {} : { maxSymbolDailyNotionalUsd }),
    ...(maxPositionUsd === undefined ? {} : { maxPositionUsd }),
    ...(orders === undefined ? {} : { maxOrdersPerDay: orders as number }) };
}

/** An optional limit in a child: if the parent has one the child must have one too, and no looser. */
function tighter(child: number | undefined, parent: number | undefined): boolean {
  return parent === undefined || (child !== undefined && child <= parent);
}

function automaticCap(scope: MandateScope): number {
  return Math.min(scope.stepUpThresholdUsd ?? Infinity, scope.maxOrderNotionalUsd);
}

export class SignedPaperPolicy {
  readonly parentId: string;
  readonly parent: MandateScope;
  private readonly owner: KeyObject;

  constructor(parentProof: unknown, publicKey: string) {
    this.owner = createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: decode(publicKey, 32).toString('base64url') }, format: 'jwk' });
    const signed = verifiedBody(parentProof, this.owner);
    this.parentId = signed.digest.slice(0, 16);
    this.parent = parseScope(signed.body);
  }

  authorization(proof: unknown, state: PaperPolicyState, purpose: string, previousDigest?: string) {
    const signed = verifiedBody(proof, this.owner);
    const { parentId, ledgerId, revision } = signed.body;
    if (signed.body.purpose !== purpose || parentId !== state.parentId || ledgerId !== state.ledgerId) {
      throw new Error('Signature was issued for a different policy action or ledger');
    }
    const replay = revision === state.revision - 1 && signed.digest === previousDigest;
    if (revision !== state.revision && !replay) throw new Error('The active policy changed. Review the current revision and sign again');
    return { ...signed, replay };
  }

  containedDraft(raw: unknown, now: number): MandateScope {
    const candidate = parseScope(object(raw));
    const parent = this.parent;
    if (Date.parse(candidate.expiresAt) <= now || Date.parse(candidate.expiresAt) > Date.parse(parent.expiresAt)
        || !candidate.symbols.every((s) => parent.symbols.includes(s)) || !candidate.sides.every((s) => parent.sides.includes(s))
        || candidate.maxOrderNotionalUsd > parent.maxOrderNotionalUsd || candidate.maxDailyNotionalUsd > parent.maxDailyNotionalUsd
        || candidate.priceBandPct > parent.priceBandPct
        || !tighter(candidate.maxSymbolDailyNotionalUsd, parent.maxSymbolDailyNotionalUsd)
        || !tighter(candidate.maxPositionUsd, parent.maxPositionUsd)
        || !tighter(candidate.maxOrdersPerDay, parent.maxOrdersPerDay) || automaticCap(candidate) > automaticCap(parent)
        || !candidate.symbols.every((s) => candidate.referencePrices?.[s] === parent.referencePrices?.[s])) {
      throw new Error('The signed draft does not fit the signed parent policy');
    }
    return candidate;
  }
}
