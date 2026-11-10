// `npm run invariants [-- --seeds N]`: runs the seeded fault campaign, the benign suite and two mutation tests.
import { runBenignSuite, runCampaign, type Violation } from './campaign.ts';

const argIndex = process.argv.indexOf('--seeds');
const seeds = argIndex >= 0 ? Number(process.argv[argIndex + 1]) : 1000;
if (!Number.isInteger(seeds) || seeds < 5) { console.error('--seeds needs an integer >= 5'); process.exit(2); }

const started = Date.now();
const main = await runCampaign(seeds);
const benign = await runBenignSuite(20);
const mutSeeds = Math.min(seeds, 200);
const idemOff = await runCampaign(mutSeeds, { idempotencyOff: true });
const lockOff = await runCampaign(mutSeeds, { budgetLockOff: true });

const count = (vs: Violation[], inv: string) => vs.filter((v) => v.invariant === inv).length;
const rows: Array<[string, string, string, string]> = [];
const describe: Record<string, string> = {
  I1: 'no effect without exact canonical action under scope',
  I2: 'shared budget holds under concurrent agents',
  I3: 'duplicate delivery never duplicates the effect',
  I4: 'nothing commits after revocation',
  I5: 'permitted work completes',
};
for (const inv of ['I1', 'I2', 'I3', 'I4']) {
  const n = count(main.violations, inv);
  rows.push([inv, describe[inv]!, `${seeds} seeds, ${n} violations`, n === 0 ? 'PASS' : 'FAIL']);
}
const rate = main.benignEntitled ? main.benignFilled / main.benignEntitled : 1;
const i5v = count(main.violations, 'I5');
const pct = (a: number, b: number) => `${((100 * a) / b).toFixed(1)}%`;
rows.push(['I5', describe.I5!, `benign completion ${pct(benign.filled, benign.total)} (${benign.filled}/${benign.total}) fault-free; ${pct(main.benignFilled, main.benignEntitled)} (${main.benignFilled}/${main.benignEntitled}) entitled under faults`, i5v === 0 && benign.filled === benign.total ? 'PASS' : 'FAIL']);

const mut: Array<[string, string, string, string]> = [
  ['idempotency off', 'I3', `${count(idemOff.violations, 'I3')} violations in ${mutSeeds} seeds`, count(idemOff.violations, 'I3') > 0 ? 'CAUGHT' : 'MISSED'],
  ['budget lock off', 'I2', `${count(lockOff.violations, 'I2')} violations in ${mutSeeds} seeds`, count(lockOff.violations, 'I2') > 0 ? 'CAUGHT' : 'MISSED'],
];

const pad = (s: string, n: number) => s.padEnd(n);
const w = [Math.max(...rows.map((r) => r[0].length), 3), 52, Math.max(...rows.map((r) => r[2].length)), 4];
console.log('\nOrderGuard receiver invariants (offline, seeded)');
for (const r of rows) console.log(`${pad(r[0], w[0]!)}  ${pad(r[1], w[1]!)}  ${pad(r[2], w[2]!)}  ${r[3]}`);
console.log('\nFault coverage (seeds / fault actually applied)');
for (const [a, s] of Object.entries(main.byAction)) console.log(`  ${pad(a, 10)} ${s.seeds} / ${s.applied}`);
console.log('\nMutation tests (the checker must catch both)');
for (const m of mut) console.log(`  ${pad(m[0], 18)} breaks ${m[1]}  ${pad(m[2], 34)} ${m[3]}`);
const ok = rows.every((r) => r[3] === 'PASS') && mut.every((m) => m[3] === 'CAUGHT');
console.log(`\ninvariants: ${ok ? 'PASS' : 'FAIL'} (${seeds} seeds, ${((Date.now() - started) / 1000).toFixed(1)}s)`);
if (!ok) { for (const v of main.violations.slice(0, 5)) console.log('  violation', JSON.stringify(v)); process.exit(1); }
