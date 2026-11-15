// Parity probe for python/tests/guard/test_cents_parity.py: runs the receiver's own TypeScript (no port, no network) on cases sent as
// JSON on stdin and prints the answers as JSON. Numbers that JSON cannot carry are sent as the strings "NaN", "Infinity", "-Infinity".
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

const root = process.argv[2];
const load = (p: string) => import(pathToFileURL(join(root, p)).href);
const { notionalCents, buildTrustedPrices } = await load('receiver/core/valuation.ts');
const { SignedPaperPolicy } = await load('receiver/core/paper-policy.ts');
const { parentProofFromFile, pythonFloatRepr } = await load('receiver/core/signed-mandate.ts');
const { ReceiverCore } = await load('receiver/core/receiver-core.ts');

const num = (v: unknown) => (v === 'NaN' ? NaN : v === 'Infinity' ? Infinity : v === '-Infinity' ? -Infinity : v);
let text = '';
for await (const chunk of process.stdin) text += chunk;
const input = JSON.parse(text);
const out: Record<string, unknown> = {};

out.cents = (input.cents ?? []).map(([q, p]: [number, number]) => notionalCents(q, p));
out.refs = (input.refs ?? []).map((v: unknown) => {
  try { buildTrustedPrices({ referencePrices: { AAPL: num(v) as number } }); return true; } catch { return false; }
});
out.floats = (input.floats ?? []).map((x: number) => pythonFloatRepr(x));
out.mandates = (input.mandates ?? []).map((m: { text: string; pub: string }) => {
  try {
    const policy = new SignedPaperPolicy(parentProofFromFile(m.text), m.pub);
    return { ok: true, parentId: policy.parentId, scope: policy.parent };
  } catch (e) { return { ok: false, error: String((e as Error).message) }; }
});
out.decisions = [];
for (const c of input.decisions ?? []) {
  const mandate = { symbols: ['AAPL'], sides: ['buy'], maxOrderNotionalUsd: c.cap, maxDailyNotionalUsd: c.daily, priceBandPct: 5,
    expiresAt: '2099-01-01T00:00:00Z', referencePrices: { AAPL: c.ref }, ...(c.stepUp === null ? {} : { stepUpThresholdUsd: c.stepUp }) };
  const core = new ReceiverCore({ ledgerPath: ':memory:', mandateId: 'parity', mandate });
  const d = await core.propose({ symbol: 'AAPL', side: 'buy', quantity: c.qty, limitPrice: c.ref, clientOrderId: 'p1' });
  (out.decisions as unknown[]).push({ decision: d.decision, reason: d.reason, notionalUsd: d.notionalUsd ?? null });
  core.close();
}
process.stdout.write(JSON.stringify(out));
