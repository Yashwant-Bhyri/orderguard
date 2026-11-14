# OrderGuard Node.js SDK

Small JavaScript client for OrderGuard's public HTTP receiver routes. It turns one typed order into a local preview and submits the receiver-issued capability to the receiver. It has no signing key and is not a security boundary; the receiver authorizes the exact action and commits the paper ledger.

## Install from a packed tarball

```sh
npm pack
npm install ./orderguard-sdk-0.1.0.tgz
```

The package has no runtime dependencies and requires Node.js 20 or newer (the receiver it talks to needs 22.13). Offline, from a clone of the repository, `node examples/node/check-order.mjs` starts a throwaway receiver and shows an order refused with its reason ([docs/QUICKSTART.md](../../docs/QUICKSTART.md#node)). Against a receiver of your own, initialize the client and submit a typed paper order:

```js
import { OrderGuardClient } from "@orderguard/sdk";

const orderguard = new OrderGuardClient({ baseUrl: "http://127.0.0.1:4173" });
const mandate = await orderguard.getMandate();
const mandateId = mandate.mandates.find((row) => row.active).mandateId;
const result = await orderguard.proposeOrder({
  mandateId, symbol: "AAPL", side: "buy", quantity: 1,
  orderType: "market", session: "regular", timeInForce: "day",
});
console.log(result.state);
```

A refused order returns `{ state: "denied" | "proposal_denied", reason, ... }` with the receiver's reason (a preview refusal also lists `findings`); `proposeOrder` throws only for unreachable receivers and bad input. Types are in `src/index.d.ts`. The default base URL, `http://127.0.0.1:4173`, is the mesh receiver (`receiver/r5/server.ts`); the bridge on port 8700 serves different routes. Use HTTPS for non-loopback receivers. `ORDERGUARD_URL` and `ORDERGUARD_BEARER_TOKEN` can provide defaults; do not put tokens in URLs or logs. The SDK calls `/api/human-mandate/status`, `/api/chat`, `/api/paper-orders`, and `/api/snapshot`; it never accesses a ledger or venue directly. `cancel()` can only start the receiver's human step-up ceremony.

## Verify

```sh
npm test
npm pack --dry-run
```

Release status: **owner packaged; receiver review pending**. This package currently targets the mesh's LocalSim paper routes. It is not a broker certification or production trading client.
