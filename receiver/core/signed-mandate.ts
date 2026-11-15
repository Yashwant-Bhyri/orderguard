// A mandate signed by the Python side (`orderguard init`, gate.sign_mandate) as a parent proof the receiver can verify.
//
// Python signs Ed25519 over canonical JSON: Mandate.from_dict(d).to_dict(with_signature=False), dumped with sort_keys, no spaces,
// ensure_ascii=False. Python's float repr ("10000.0", "1e-05") is not JavaScript's ("10000", "0.00001"), so the bytes are rebuilt
// from the file's own number lexemes (JSON.parse source access) and Python's repr rules. The result is the exact byte string the
// owner signed; SignedPaperPolicy then verifies it against the PINNED owner key and parses the scope. Nothing here decides
// anything: a mistake can only make a valid signature fail to verify, never make an invalid one pass.

/** The Python Mandate dataclass fields, in no particular order. Anything else in the file is not covered by the signature. */
const MANDATE_FIELDS = new Set(['symbols', 'sides', 'maxOrderNotionalUsd', 'maxDailyNotionalUsd', 'priceBandPct', 'expiresAt',
  'referencePrices', 'stepUpAboveUsd', 'maxSymbolDailyNotionalUsd', 'maxPositionUsd', 'maxOrdersPerDay']);
const SIGNATURE_FIELDS = new Set(['signature', 'signerPublicKey']);

/** A JSON number with the lexeme it was written as: Python's json keeps "10000" an int and "10000.0" a float. */
class Num { constructor(readonly value: number, readonly source: string) {} }
type Json = null | boolean | string | Num | Json[] | { [key: string]: Json };

/** Python's repr(float) for a finite double: shortest round-trip digits, scientific below 1e-4 or from 1e16 up. */
export function pythonFloatRepr(x: number): string {
  if (!Number.isFinite(x)) throw new Error('a mandate number is not finite');
  if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
  const sign = x < 0 ? '-' : '';
  const [mantissa, expText] = Math.abs(x).toExponential().split('e');
  const digits = mantissa.replace('.', '');
  const exp = Number(expText);
  if (exp < -4 || exp >= 16) {
    const m = digits.length > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
    const e = String(Math.abs(exp)).padStart(2, '0');
    return `${sign}${m}e${exp < 0 ? '-' : '+'}${e}`;
  }
  if (exp < 0) return `${sign}0.${'0'.repeat(-exp - 1)}${digits}`;
  if (digits.length <= exp + 1) return `${sign}${digits}${'0'.repeat(exp + 1 - digits.length)}.0`;
  return `${sign}${digits.slice(0, exp + 1)}.${digits.slice(exp + 1)}`;
}

function numberText(n: Num): string {
  if (/[.eE]/.test(n.source)) return pythonFloatRepr(n.value);
  return BigInt(n.source).toString();                 // a Python int: exact digits, "-0" is 0
}

function stringText(s: string): string {
  // Python's json escapes the same characters as JSON.stringify for well-formed text; a lone surrogate cannot be signed by Python.
  if (!s.isWellFormed()) throw new Error('a mandate string holds an unpaired surrogate');
  return JSON.stringify(s);
}

function canonical(v: Json): string {
  if (v === null) return 'null';
  if (v === true) return 'true';
  if (v === false) return 'false';
  if (typeof v === 'string') return stringText(v);
  if (v instanceof Num) return numberText(v);
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  const keys = Object.keys(v).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  return `{${keys.map((k) => `${stringText(k)}:${canonical(v[k])}`).join(',')}}`;
}

function parseKeepingLexemes(text: string): Json {
  let sawSource = true;
  const value = JSON.parse(text, function (this: unknown, _key: string, v: unknown, context?: { source?: string }) {
    if (typeof v !== 'number') return v;
    if (typeof context?.source !== 'string') { sawSource = false; return v; }
    return new Num(v, context.source);
  }) as Json;
  if (!sawSource) throw new Error('this Node.js cannot read JSON number lexemes; upgrade to Node 22.13 or later');
  return value;
}

export interface ParentProof { payload: string; signature: string }

/**
 * Turn the text of a Python-signed mandate file into {payload, signature}: payload is the canonical bytes Python signed (base64),
 * signature is the file's own. Throws a plain sentence for an unsigned file or fields the signature does not cover.
 * The signature is NOT checked here; SignedPaperPolicy checks it against the pinned owner key.
 */
export function parentProofFromSignedMandate(text: string): ParentProof {
  const raw = parseKeepingLexemes(text);
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || raw instanceof Num) throw new Error('the mandate file is not a JSON object');
  const unknown = Object.keys(raw).filter((k) => !MANDATE_FIELDS.has(k) && !SIGNATURE_FIELDS.has(k));
  if (unknown.length) {
    throw new Error(`the mandate has fields the owner's signature does not cover (${unknown.slice(0, 5).join(', ')}): remove them and re-sign with \`orderguard init --resign\``);
  }
  const signature = raw.signature;
  if (typeof signature !== 'string' || signature.length === 0) {
    throw new Error('the mandate is not signed: sign it with `orderguard init` (or `orderguard init --resign` after editing it)');
  }
  // Mandate.from_dict(d).to_dict(with_signature=False): known fields only, a null value dropped, referencePrices defaults to {}.
  const body: { [key: string]: Json } = {};
  for (const [k, v] of Object.entries(raw)) if (MANDATE_FIELDS.has(k) && v !== null) body[k] = v;
  if (!('referencePrices' in raw)) body.referencePrices = {};
  const payload = Buffer.from(canonical(body), 'utf8').toString('base64');
  return { payload, signature };
}

/** The file is a proof ({payload, signature}) already, or a Python-signed mandate to convert. */
export function parentProofFromFile(text: string): ParentProof {
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { throw new Error('the mandate file is not valid JSON: re-create it with `orderguard init --resign`'); }
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed) && 'payload' in parsed && Object.keys(parsed).every((k) => k === 'payload' || k === 'signature')) {
    return parsed as ParentProof;
  }
  return parentProofFromSignedMandate(text);
}
