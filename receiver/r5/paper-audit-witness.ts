import { spawnSync } from 'node:child_process';
import { createHash, createPublicKey, randomBytes, verify as verifySignature } from 'node:crypto';

export interface PaperAuditWitnessConfig {
  url: string;
  ledgerId: string;
  token: string;
  publicKey: string;
}

export interface PaperAuditWitnessPendingV1 {
  transactionId: string;
  expectedVersion: number;
  previousHash: string;
  nextHash: string;
}

export interface PaperAuditWitnessStateV1 {
  schemaVersion: 1;
  ledgerId: string;
  version: number;
  headHash: string;
  lastTransactionId: string | null;
  pending: PaperAuditWitnessPendingV1 | null;
}

const WITNESS_REQUEST_SCRIPT = `
const chunks = [];
for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));
const request = JSON.parse(Buffer.concat(chunks).toString('utf8'));
try {
  const response = await fetch(new URL(request.path, process.env.ORDERGUARD_WITNESS_URL.replace(/\\/?$/, '/')), {
    method: 'POST',
    headers: {
      'authorization': 'Bearer ' + process.env.ORDERGUARD_WITNESS_TOKEN,
      'content-type': 'application/json',
      'accept': 'application/json',
    },
    body: JSON.stringify(request.body),
    signal: AbortSignal.timeout(5000),
  });
  const body = await response.text();
  process.stdout.write(JSON.stringify({ status: response.status, body }));
} catch {
  process.stdout.write(JSON.stringify({ status: 0, body: '' }));
  process.exitCode = 1;
}
`;

export function readPaperAuditWitnessConfig(env: NodeJS.ProcessEnv = process.env): PaperAuditWitnessConfig | null {
  const urlValue = env.ORDERGUARD_WITNESS_URL;
  const ledgerId = env.ORDERGUARD_WITNESS_LEDGER_ID;
  const token = env.ORDERGUARD_WITNESS_TOKEN;
  const publicKey = env.ORDERGUARD_WITNESS_PUBLIC_KEY;
  const configured = [urlValue, ledgerId, token, publicKey].filter((value) => value !== undefined).length;
  if (configured === 0) return null;
  if (configured !== 4 || !urlValue || !ledgerId || !token || !publicKey) {
    throw new Error('Paper audit witness configuration requires URL, ledger ID, token, and public key together.');
  }

  let url: URL;
  try { url = new URL(urlValue); }
  catch { throw new Error('Paper audit witness URL is invalid.'); }
  const localHost = url.hostname === 'localhost' || url.hostname === '127.0.0.1' || url.hostname === '[::1]';
  if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && localHost))
    || url.username || url.password || url.search || url.hash) {
    throw new Error('Paper audit witness requires HTTPS, except for a loopback development endpoint.');
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(ledgerId)
    || token.length < 32 || token.length > 512 || /\s/.test(token)
    || !/^[A-Za-z0-9_-]{40,200}$/.test(publicKey)) {
    throw new Error('Paper audit witness identity or credential is malformed.');
  }
  try {
    const key = createPublicKey({ key: Buffer.from(publicKey, 'base64url'), format: 'der', type: 'spki' });
    if (key.asymmetricKeyType !== 'ed25519') throw new Error('Wrong key type.');
  } catch {
    throw new Error('Paper audit witness public key must be an Ed25519 SPKI key encoded as base64url.');
  }
  return { url: url.toString().replace(/\/$/, ''), ledgerId, token, publicKey };
}

export function paperAuditWitnessAnchorHash(anchor: unknown): string {
  return createHash('sha256').update(canonicalJson(anchor), 'utf8').digest('base64url');
}

export function requestPaperAuditWitness(
  config: PaperAuditWitnessConfig,
  path: '/v1/state' | '/v1/prepare' | '/v1/commit' | '/v1/abort' | '/v1/bootstrap',
  body: Record<string, unknown>,
): PaperAuditWitnessStateV1 {
  const challenge = randomBytes(24).toString('base64url');
  const childEnv: NodeJS.ProcessEnv = {
    ORDERGUARD_WITNESS_URL: config.url,
    ORDERGUARD_WITNESS_TOKEN: config.token,
  };
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', WITNESS_REQUEST_SCRIPT], {
    input: JSON.stringify({ path, body: { ...body, challenge } }),
    encoding: 'utf8',
    env: childEnv,
    timeout: 7000,
    maxBuffer: 64 * 1024,
    windowsHide: true,
  });
  if (result.error || result.status !== 0 || typeof result.stdout !== 'string') {
    throw new Error('Independent paper-audit witness could not be reached.');
  }

  let response: { status?: unknown; body?: unknown };
  try { response = JSON.parse(result.stdout) as typeof response; }
  catch { throw new Error('Independent paper-audit witness returned an invalid response.'); }
  if (response.status !== 200 || typeof response.body !== 'string') {
    throw new Error('Independent paper-audit witness rejected or could not complete the request.');
  }
  let envelope: unknown;
  try { envelope = JSON.parse(response.body) as unknown; }
  catch { throw new Error('Independent paper-audit witness returned an invalid signed state.'); }
  if (!isRecord(envelope) || !isRecord(envelope.payload) || envelope.challenge !== challenge || typeof envelope.signature !== 'string'
    || !/^[A-Za-z0-9_-]{80,100}$/.test(envelope.signature)) {
    throw new Error('Independent paper-audit witness response is missing the current challenge or signature.');
  }
  const payload = envelope.payload;
  if (!isPaperAuditWitnessState(payload) || payload.ledgerId !== config.ledgerId) {
    throw new Error('Independent paper-audit witness returned an unexpected ledger state.');
  }
  let signatureValid = false;
  try {
    const key = createPublicKey({ key: Buffer.from(config.publicKey, 'base64url'), format: 'der', type: 'spki' });
    signatureValid = verifySignature(null, Buffer.from(canonicalJson({ payload, challenge }), 'utf8'), key, Buffer.from(envelope.signature, 'base64url'));
  } catch { signatureValid = false; }
  if (!signatureValid) throw new Error('Independent paper-audit witness signature verification failed.');
  return payload;
}

function isPaperAuditWitnessState(value: unknown): value is PaperAuditWitnessStateV1 {
  if (!isRecord(value)) return false;
  if (value.schemaVersion !== 1 || typeof value.ledgerId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.ledgerId)
    || !Number.isSafeInteger(value.version) || Number(value.version) < 0
    || typeof value.headHash !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(value.headHash)
    || !(value.lastTransactionId === null || (typeof value.lastTransactionId === 'string' && /^[A-Za-z0-9_-]{24}$/.test(value.lastTransactionId)))) return false;
  if (value.pending === null) return true;
  if (!isRecord(value.pending)) return false;
  return typeof value.pending.transactionId === 'string' && /^[A-Za-z0-9_-]{24}$/.test(value.pending.transactionId)
    && Number.isSafeInteger(value.pending.expectedVersion) && Number(value.pending.expectedVersion) === Number(value.version)
    && typeof value.pending.previousHash === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value.pending.previousHash)
    && typeof value.pending.nextHash === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value.pending.nextHash);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function canonicalJson(value: unknown): string {
  if (value === undefined) return '"__undefined__"';
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  const record = value as Record<string, unknown>;
  return '{' + Object.keys(record).sort().map((key) => JSON.stringify(key) + ':' + canonicalJson(record[key])).join(',') + '}';
}
