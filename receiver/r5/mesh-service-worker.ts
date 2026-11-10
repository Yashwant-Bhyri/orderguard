import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { startMeshServiceWorker, type MeshWorkerConfig, type MeshWorkerRpc } from './execution-mesh.js';
import { signedInternalHeaders } from './mesh-internal-auth.js';
import { MESH_SERVICE_AUDIENCES, type ContainerWorkerConfig } from './mesh-container-config.js';

type ParentMessage =
  | { type: 'initialize'; config: MeshWorkerConfig }
  | { type: 'rpc-response'; id: string; ok: boolean; result?: unknown; error?: string }
  | { type: 'shutdown' };

type PendingRpc = { resolve(value: unknown): void; reject(error: Error): void; timer: NodeJS.Timeout };

const pending = new Map<string, PendingRpc>();
let service: Awaited<ReturnType<typeof startMeshServiceWorker>> | null = null;
let starting = false;

function send(message: unknown): Promise<void> {
  return new Promise((resolveSend, rejectSend) => {
    if (!process.send) return rejectSend(new Error('The service worker IPC channel is unavailable.'));
    process.send(message, (error) => error ? rejectSend(error) : resolveSend());
  });
}

const rpc: MeshWorkerRpc = (method, payload) => new Promise((resolveRpc, rejectRpc) => {
  const id = randomUUID();
  const timer = setTimeout(() => {
    pending.delete(id);
    rejectRpc(new Error('The policy host did not answer the service RPC in time.'));
  }, method === 'tool-invoke' ? 20_000 : 2_500);
  pending.set(id, { resolve: resolveRpc, reject: rejectRpc, timer });
  void send({ type: 'rpc', id, method, payload }).catch((error: unknown) => {
    clearTimeout(timer);
    pending.delete(id);
    rejectRpc(error instanceof Error ? error : new Error('Service RPC could not be sent.'));
  });
});

function handleParentMessage(raw: unknown): void {
  if (!raw || typeof raw !== 'object') return;
  const message = raw as ParentMessage;
  if (message.type === 'rpc-response') {
    const request = pending.get(message.id);
    if (!request) return;
    clearTimeout(request.timer);
    pending.delete(message.id);
    if (message.ok) request.resolve(message.result);
    else request.reject(new Error(message.error ?? 'The policy host rejected the service RPC.'));
    return;
  }
  if (message.type === 'initialize' && !starting) {
    starting = true;
    void startMeshServiceWorker(message.config, rpc).then(async (startedService) => {
      service = startedService;
      await send({ type: 'ready', url: startedService.url });
    }).catch(async (error: unknown) => {
      await send({ type: 'fatal', error: error instanceof Error ? error.message : 'Service worker startup failed.' }).catch(() => undefined);
      process.exitCode = 1;
      process.disconnect?.();
    });
    return;
  }
  if (message.type === 'shutdown') {
    void (async () => {
      for (const request of pending.values()) {
        clearTimeout(request.timer);
        request.reject(new Error('The service worker is shutting down.'));
      }
      pending.clear();
      await service?.close();
      await send({ type: 'stopped' }).catch(() => undefined);
      process.disconnect?.();
    })().catch(() => {
      process.exitCode = 1;
      process.disconnect?.();
    });
  }
}

if (process.send) {
  process.on('message', handleParentMessage);
} else {
  const configPath = process.env.ORDERGUARD_MESH_CONFIG;
  if (!configPath) throw new Error('ORDERGUARD_MESH_CONFIG is required for a standalone service worker.');
  const parsed = JSON.parse(readFileSync(configPath, 'utf8')) as Partial<ContainerWorkerConfig>;
  if (parsed.schemaVersion !== 1 || !parsed.audience || !MESH_SERVICE_AUDIENCES.includes(parsed.audience)
    || typeof parsed.policyPublicKey !== 'string' || typeof parsed.publicKey !== 'string' || typeof parsed.privateKey !== 'string'
    || !Array.isArray(parsed.servicesPublicKeys) || typeof parsed.ledgerPath !== 'string'
    || parsed.listenHost !== '0.0.0.0' || !Number.isInteger(parsed.port) || typeof parsed.policyRequestSecret !== 'string'
    || typeof parsed.handlerRpcSecret !== 'string' || typeof parsed.handlerRpcUrl !== 'string'
    || (parsed.persistInternalNonceReplay !== undefined && typeof parsed.persistInternalNonceReplay !== 'boolean')) {
    throw new Error('Standalone worker configuration is malformed.');
  }
  // Standalone workers are the container deployment surface. Always enable
  // the shared replay journal, including for configs generated before the
  // opt-in field was added.
  const config = { ...parsed, persistInternalNonceReplay: true } as ContainerWorkerConfig;
  const rpc: MeshWorkerRpc = async (method, payload) => {
    if (method !== 'tool-invoke') throw new Error('The service worker requested an unsupported policy-host RPC.');
    const pathname = new URL(config.handlerRpcUrl).pathname;
    const body = JSON.stringify({ ...payload, audience: config.audience });
    const response = await fetch(config.handlerRpcUrl, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...signedInternalHeaders(config.handlerRpcSecret, config.audience, 'POST', pathname, body),
      },
      body,
      signal: AbortSignal.timeout(20_000),
    });
    if (!response.ok) throw new Error('The policy host rejected the scoped handler RPC.');
    const result = await response.json() as { result?: unknown };
    if (!Object.hasOwn(result, 'result')) throw new Error('The policy host returned a malformed handler RPC response.');
    return result.result;
  };
  const restart = () => {
    if (!service) {
      process.exit(77);
      return;
    }
    const current = service;
    service = null;
    void current.close().finally(() => process.exit(77));
  };
  void startMeshServiceWorker(config as MeshWorkerConfig, rpc, restart).then(async (startedService) => {
    service = startedService;
    process.stdout.write('OrderGuard container worker ready: ' + config.audience + ' at ' + startedService.url + '\n');
    const close = async () => {
      if (!service) return;
      const current = service;
      service = null;
      await current.close();
    };
    process.once('SIGTERM', () => { void close().finally(() => process.exit(0)); });
    process.once('SIGINT', () => { void close().finally(() => process.exit(0)); });
  }).catch((error: unknown) => {
    process.stderr.write((error instanceof Error ? error.message : 'Standalone service worker startup failed.') + '\n');
    process.exitCode = 1;
  });
}
