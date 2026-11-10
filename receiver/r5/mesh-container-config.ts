export const MESH_SERVICE_AUDIENCES = [
  'market-data',
  'research-index',
  'portfolio-store',
  'risk-engine',
  'approval-service',
  'paper-ledger',
] as const;

export type ContainerServiceAudience = typeof MESH_SERVICE_AUDIENCES[number];

export interface ContainerPolicyService {
  audience: ContainerServiceAudience;
  url: string;
  publicKey: string;
  policyRequestSecret: string;
  handlerRpcSecret: string;
}

export interface ContainerPolicyConfig {
  schemaVersion: 1;
  policyPublicKey: string;
  policyPrivateKey: string;
  ledgerPath: string;
  services: ContainerPolicyService[];
}

export interface ContainerWorkerConfig {
  schemaVersion: 1;
  audience: ContainerServiceAudience;
  policyPublicKey: string;
  publicKey: string;
  privateKey: string;
  servicesPublicKeys: Array<{ audience: ContainerServiceAudience; publicKey: string }>;
  ledgerPath: string;
  listenHost: '0.0.0.0';
  port: number;
  policyRequestSecret: string;
  handlerRpcSecret: string;
  handlerRpcUrl: string;
  persistInternalNonceReplay?: boolean;
}
