// A durable receiver that the parent (og-bench) kills with SIGKILL at a random moment and restarts. On every start it opens the
// ledger with verify-on-open (a damaged chain is never served), then proposes one envelope's orders from index --from, writing
// `A <index> <clientOrderId> <decision>` after each propose() returns. A kill can land before, inside or after the commit
// transaction; the parent re-sends everything it has no acknowledgement for (and a few it has), and the auditor checks the result.
//
//   node --no-warnings --import tsx receiver/bench/fault-child.ts --workload W.jsonl --env NAME --ledger L --from I

import { Market, arg, hr, loadWorkload, openCore, toOrder } from './common.ts';

const { header, lines } = loadWorkload(arg('--workload')!);
const name = arg('--env')!;
const from = Number(arg('--from', '0'));
const mine = lines.filter((l) => l.e === name);
const market = new Market(header);
const t0 = hr();
let core;
try {
  core = openCore(arg('--ledger')!, name, header, market, { verifyOnOpen: true });
} catch (e) {
  process.stdout.write(`OPEN_FAIL ${String((e as Error).message).slice(0, 200).replace(/\n/g, ' ')}\n`);
  process.exit(3);
}
const check = core.verifyLedger();
process.stdout.write(`OPEN_OK ${check.events} ${check.ok ? 'verified' : 'FAILED'} ${Number(hr() - t0) / 1e6}\n`);
for (let i = from; i < mine.length; i += 1) {
  const l = mine[i]!;
  market.at(l.t, l.day);
  const d = await core.propose(toOrder(l));
  process.stdout.write(`A ${i} ${l.k} ${d.decision}${d.replay ? ' replay' : ''}\n`);
}
core.close();
process.stdout.write('DONE\n');
