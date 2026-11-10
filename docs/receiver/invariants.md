# Safety invariants

Run `npm run invariants` (add `-- --seeds N`; default 1,000). It runs offline in seconds and prints a table. Each invariant is checked after every seed from the ledger alone.

| ID | Invariant | How it is checked |
|---|---|---|
| I1 | No effect unless the receiver authorises the exact canonical action under current scoped authority | Every ledger row is in scope (symbol, side, trusted-price cap, price band); none of the four attack orders (fake split, sell, Cyrillic symbol, unlisted ticker) has a row |
| I2 | Shared limits hold atomically | Five concurrent agents race for a 20,000 budget; total spent never exceeds it |
| I3 | Duplicate delivery never duplicates the effect | At most one ledger row per clientOrderId, including a concurrently double-sent order and retries after drop or crash |
| I4 | Nothing commits after revocation | No fill or approval event is sequenced after the revoke event, including a revoke injected between approval and commit |
| I5 | Permitted work still completes | Benign completion rate is reported: fault-free suite and entitled orders under faults |

Faults come from `receiver/r5/fault-scheduler.ts` (drop, duplicate, delay, crash and restart, revoke); every five seeds cover all five. Two mutations, idempotency off and budget lock off, are run and the checker must flag them.

Scope: synthetic prices, a local SQLite ledger and in-process agents. This is evidence about the core, not about real money, a broker or production. Older measured claims in the other documents here refer to an evidence archive that is not part of this repository.
