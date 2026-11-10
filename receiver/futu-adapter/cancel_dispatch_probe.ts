import { PaperLedgerStore } from '../paper-ledger-store.ts';

const [path, idempotencyKey, orderId, orderHash] = process.argv.slice(2);
if (!path || !idempotencyKey || !orderId || !orderHash) {
  throw new Error('Expected database path, idempotency key, order ID, and order hash.');
}

const ledger = new PaperLedgerStore(path);
try {
  const result = ledger.cancel(idempotencyKey, orderId, orderHash);
  process.stdout.write(JSON.stringify(result));
} finally {
  ledger.close();
}
