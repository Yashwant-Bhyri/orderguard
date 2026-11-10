import { createInterface } from 'node:readline';
import { PaperLedgerStore, type DurablePaperOrder, type PaperCommitControls } from './paper-ledger-store.js';

const path = process.env.ORDERGUARD_LEDGER_TEST_DB;
if (!path) throw new Error('ORDERGUARD_LEDGER_TEST_DB is required.');

const store = new PaperLedgerStore(path);
const input = createInterface({ input: process.stdin });
const workerIdentity = process.env.ORDERGUARD_LEDGER_TEST_CONTAINER === '1'
  ? 'READY ' + (process.env.HOSTNAME ?? 'unknown-container')
  : 'READY';
process.stdout.write(workerIdentity + '\n');

input.once('line', (line) => {
  try {
    const message = JSON.parse(line) as { key: string; order: DurablePaperOrder; controls: PaperCommitControls };
    const result = store.commit(message.key, message.order, message.controls);
    process.stdout.write(JSON.stringify(result) + '\n');
    store.close();
    input.close();
    process.stdin.destroy();
  } catch (error) {
    process.stderr.write((error instanceof Error ? error.message : 'Worker failed.') + '\n');
    store.close();
    process.exitCode = 1;
    input.close();
    process.stdin.destroy();
  }
});
