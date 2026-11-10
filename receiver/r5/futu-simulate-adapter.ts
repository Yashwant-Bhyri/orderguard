import { spawn } from 'node:child_process';
import { basename, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const FUTU_SIMULATE_ENV = 'SIMULATE' as const;

export interface FutuSimulateDispatchRequest {
  orderId: string;
  idempotencyKey: string;
  localPaperConfirmed: boolean;
  futuSimulateConfirmed: boolean;
}

export interface FutuSimulateDispatchResult {
  ok: boolean;
  state: 'accepted' | 'unknown' | 'rejected' | 'conflict' | 'refused';
  broker_order_id: string | null;
  paper_account: string | null;
  endpoint: '127.0.0.1:11111';
  trd_env: 'SIMULATE';
  idempotency_remark?: string;
  replayed_or_reconciled?: boolean;
  code?: string;
}

export interface FutuSimulateQuoteSnapshot {
  code: string;
  last_price: number;
  bid_price: number;
  ask_price: number;
  lot_size: number;
  update_time: string;
  suspension: boolean;
  market_state: 'MORNING' | 'AFTERNOON';
}

export interface FutuSimulateQuoteResult {
  ok: true;
  endpoint: '127.0.0.1:11111';
  trd_env: 'SIMULATE';
  quotes: FutuSimulateQuoteSnapshot[];
  diagnostic?: FutuSimulateQuoteDiagnostic;
}

export type FutuQuoteCallSite = 'receiver_prepare' | 'receiver_post_model' | 'scheduler_health' | 'dashboard_refresh' | 'replay' | 'adapter_cli' | 'diagnostic_probe';

export interface FutuSimulateQuoteDiagnostic {
  call_site?: string;
  source?: string;
  path?: string;
  cache_used?: boolean;
  endpoint?: string;
  stage?: string;
  elapsed_ms?: number;
  global_state_ms?: number;
  market_snapshot_ms?: number;
  sdk_ret_code?: number | null;
  upstream_http_status?: string;
  response_body_summary?: unknown;
  quote_count?: number;
  returned_codes?: string[];
  validation_reason?: string;
  error_code?: string | null;
  market_state?: string;
}

export class FutuQuoteBridgeError extends Error {
  constructor(readonly code: string, readonly diagnostic?: FutuSimulateQuoteDiagnostic) {
    super('OpenD SIMULATE quote bridge failed.');
    this.name = 'FutuQuoteBridgeError';
  }
}

export type FutuSimulateBridge = (request: FutuSimulateDispatchRequest) => Promise<FutuSimulateDispatchResult>;
export type FutuSimulateQuoteBridge = (callSite?: FutuQuoteCallSite, requestedCodes?: string[]) => Promise<FutuSimulateQuoteResult>;

const moduleDirectory = resolve(fileURLToPath(new URL('.', import.meta.url)));
const appRoot = basename(moduleDirectory) === 'dist' ? resolve(moduleDirectory, '..') : moduleDirectory;

export function futuSimulateGatesOpen(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.ORDERGUARD_B3_DISPATCH_STARTED === '1'
    && env.ORDERGUARD_FUTU_SIMULATE_ENABLED === '1'
    && env.ORDERGUARD_MESH_MODE !== 'containers';
}

export async function dispatchFutuSimulateOrder(
  request: FutuSimulateDispatchRequest,
  env: NodeJS.ProcessEnv = process.env,
  bridge: FutuSimulateBridge = runPythonBridge,
): Promise<FutuSimulateDispatchResult> {
  if (!futuSimulateGatesOpen(env)) {
    return refused('futu_simulate_gate_closed');
  }
  if (request.localPaperConfirmed !== true || request.futuSimulateConfirmed !== true) {
    return refused('explicit_confirmation_required');
  }
  if (!bounded(request.orderId) || !bounded(request.idempotencyKey)) {
    return refused('invalid_request');
  }
  try {
    return await bridge(request);
  } catch {
    // The Python bridge journals before its one send attempt. Treat process or
    // transport loss as unknown so callers reconcile the same key, never resend.
    return {
      ok: false,
      state: 'unknown',
      broker_order_id: null,
      paper_account: null,
      endpoint: '127.0.0.1:11111',
      trd_env: FUTU_SIMULATE_ENV,
      code: 'bridge_outcome_unknown',
    };
  }
}

export async function readFutuSimulateQuotes(
  env: NodeJS.ProcessEnv = process.env,
  bridge: FutuSimulateQuoteBridge = runPythonQuoteBridge,
  callSite: FutuQuoteCallSite = 'adapter_cli',
  requestedCodes?: string[],
): Promise<FutuSimulateQuoteResult> {
  if (!futuSimulateGatesOpen(env)) throw new Error('Futu SIMULATE quote access is disabled.');
  if (requestedCodes && (!requestedCodes.length || requestedCodes.some((code) => !/^HK\.\d{5}$/.test(code)))) {
    throw new Error('Invalid configured HK quote request.');
  }
  const result = await bridge(callSite, requestedCodes);
  if (!isQuoteResult(result)) throw new Error('Malformed Futu SIMULATE quote response.');
  return result;
}

function bounded(value: string): boolean {
  return typeof value === 'string' && value.length > 0 && value.length <= 180 && !/[\u0000-\u001f]/.test(value);
}

function refused(code: string): FutuSimulateDispatchResult {
  return {
    ok: false,
    state: 'refused',
    broker_order_id: null,
    paper_account: null,
    endpoint: '127.0.0.1:11111',
    trd_env: FUTU_SIMULATE_ENV,
    code,
  };
}

async function runPythonBridge(request: FutuSimulateDispatchRequest): Promise<FutuSimulateDispatchResult> {
  const scriptPath = resolve(appRoot, 'futu-adapter', 'cli.py');
  const python = process.env.ORDERGUARD_FUTU_PYTHON || 'python3';
  const configPath = process.env.ORDERGUARD_FUTU_CONFIG ?? resolve(appRoot, 'futu-adapter', 'config.json');
  const ledgerPath = process.env.ORDERGUARD_LEDGER_DB ?? resolve(process.cwd(), '.orderguard/paper-ledger.sqlite');
  const childEnv: NodeJS.ProcessEnv = {
    PATH: process.env.PATH ?? '',
    ...(process.env.HOME ? { HOME: process.env.HOME } : {}),
    ...(process.env.LANG ? { LANG: process.env.LANG } : {}),
    ORDERGUARD_LEDGER_DB: ledgerPath,
    ORDERGUARD_FUTU_CONFIG: configPath,
    ORDERGUARD_B3_DISPATCH_STARTED: process.env.ORDERGUARD_B3_DISPATCH_STARTED,
    ORDERGUARD_FUTU_SIMULATE_ENABLED: process.env.ORDERGUARD_FUTU_SIMULATE_ENABLED,
    ...(process.env.ORDERGUARD_FUTU_SIM_ACCOUNT_ID
      ? { ORDERGUARD_FUTU_SIM_ACCOUNT_ID: process.env.ORDERGUARD_FUTU_SIM_ACCOUNT_ID }
      : {}),
  };
  const payload = {
    action: 'dispatch',
    order_id: request.orderId,
    idempotency_key: request.idempotencyKey,
    trd_env: FUTU_SIMULATE_ENV,
    confirm_local_paper: request.localPaperConfirmed,
    confirm_futu_simulate: request.futuSimulateConfirmed,
  };
  return new Promise((resolveResult, rejectResult) => {
    const child = spawn(python, [scriptPath], {
      cwd: appRoot,
      env: childEnv,
      shell: false,
      stdio: ['pipe', 'pipe', 'ignore'],
    });
    let stdout = '';
    let settled = false;
    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        child.kill('SIGKILL');
        rejectResult(new Error('OpenD bridge outcome is unknown.'));
      }
    }, 45_000);
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk: string) => {
      stdout += chunk;
      if (stdout.length > 8192 && !settled) {
        settled = true;
        clearTimeout(timeout);
        child.kill('SIGKILL');
        rejectResult(new Error('OpenD bridge response exceeded the limit.'));
      }
    });
    child.on('error', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      rejectResult(new Error('OpenD bridge could not start.'));
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      try {
        const result = JSON.parse(stdout.trim()) as FutuSimulateDispatchResult;
        if (!isDispatchResult(result)) throw new Error('Malformed OpenD bridge result.');
        if (code !== 0 && result.state === 'accepted') throw new Error('OpenD bridge exit status disagrees with result.');
        resolveResult(result);
      } catch {
        rejectResult(new Error('OpenD bridge outcome is unknown.'));
      }
    });
    child.stdin.end(JSON.stringify(payload) + '\n');
  });
}

async function runPythonQuoteBridge(callSite: FutuQuoteCallSite = 'adapter_cli', requestedCodes?: string[]): Promise<FutuSimulateQuoteResult> {
  const scriptPath = resolve(appRoot, 'futu-adapter', 'cli.py');
  const python = process.env.ORDERGUARD_FUTU_PYTHON || 'python3';
  const configPath = process.env.ORDERGUARD_FUTU_CONFIG ?? resolve(appRoot, 'futu-adapter', 'config.json');
  const childEnv: NodeJS.ProcessEnv = {
    PATH: process.env.PATH ?? '',
    ...(process.env.HOME ? { HOME: process.env.HOME } : {}),
    ...(process.env.LANG ? { LANG: process.env.LANG } : {}),
    ORDERGUARD_FUTU_CONFIG: configPath,
    ORDERGUARD_FUTU_SIMULATE_ENABLED: process.env.ORDERGUARD_FUTU_SIMULATE_ENABLED,
  };
  return new Promise((resolveResult, rejectResult) => {
    const child = spawn(python, [scriptPath], {
      cwd: appRoot,
      env: childEnv,
      shell: false,
      stdio: ['pipe', 'pipe', 'ignore'],
    });
    let stdout = '';
    let settled = false;
    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        child.kill('SIGKILL');
        rejectResult(new Error('OpenD quote outcome is unknown.'));
      }
    }, 45_000);
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk: string) => {
      stdout += chunk;
      if (stdout.length > 8192 && !settled) {
        settled = true;
        clearTimeout(timeout);
        child.kill('SIGKILL');
        rejectResult(new Error('OpenD quote response exceeded the limit.'));
      }
    });
    child.on('error', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      rejectResult(new Error('OpenD quote bridge could not start.'));
    });
    child.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      try {
        const result = JSON.parse(stdout.trim()) as unknown;
        if (isQuoteResult(result) && code === 0) {
          resolveResult(result);
          return;
        }
        const failure = typeof result === 'object' && result !== null ? result as Record<string, unknown> : {};
        const diagnostic = typeof failure.diagnostic === 'object' && failure.diagnostic !== null
          ? failure.diagnostic as FutuSimulateQuoteDiagnostic : undefined;
        const errorCode = typeof failure.code === 'string' && /^[a-z0-9_]{1,64}$/.test(failure.code)
          ? failure.code : 'quote_bridge_failed';
        rejectResult(new FutuQuoteBridgeError(errorCode, diagnostic));
      } catch {
        rejectResult(new FutuQuoteBridgeError('quote_bridge_outcome_unknown'));
      }
    });
    child.stdin.end(JSON.stringify({ action: 'quotes', call_site: callSite, ...(requestedCodes ? { codes: requestedCodes } : {}) }) + '\n');
  });
}

function isDispatchResult(value: unknown): value is FutuSimulateDispatchResult {
  if (typeof value !== 'object' || value === null) return false;
  const result = value as Partial<FutuSimulateDispatchResult>;
  return typeof result.ok === 'boolean'
    && ['accepted', 'unknown', 'rejected', 'conflict', 'refused'].includes(String(result.state))
    && (result.broker_order_id === null || typeof result.broker_order_id === 'string')
    && (result.paper_account === null || typeof result.paper_account === 'string')
    && result.endpoint === '127.0.0.1:11111'
    && result.trd_env === FUTU_SIMULATE_ENV;
}

function isQuoteResult(value: unknown): value is FutuSimulateQuoteResult {
  if (typeof value !== 'object' || value === null) return false;
  const result = value as Partial<FutuSimulateQuoteResult>;
  if (result.ok !== true || result.endpoint !== '127.0.0.1:11111' || result.trd_env !== 'SIMULATE' || !Array.isArray(result.quotes)) return false;
  return result.quotes.every((quote) => typeof quote === 'object' && quote !== null
    && typeof quote.code === 'string' && /^HK\.\d{5}$/.test(quote.code)
    && typeof quote.last_price === 'number' && Number.isFinite(quote.last_price) && quote.last_price > 0
    && typeof quote.bid_price === 'number' && Number.isFinite(quote.bid_price) && quote.bid_price > 0
    && typeof quote.ask_price === 'number' && Number.isFinite(quote.ask_price) && quote.ask_price >= quote.bid_price
    && Number.isSafeInteger(quote.lot_size) && quote.lot_size > 0
    && typeof quote.update_time === 'string' && quote.update_time.length > 0
    && typeof quote.suspension === 'boolean'
    && ['MORNING', 'AFTERNOON'].includes(quote.market_state));
}
