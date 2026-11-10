# OrderGuard Node.js SDK

Small JavaScript client for OrderGuard's public HTTP receiver routes. It turns one typed order into a local preview and submits the receiver-issued capability to the receiver. It has no signing key and is not a security boundary; the receiver authorizes the exact action and commits the paper ledger.

## Install from a packed tarball

```sh
npm pack
npm install ./orderguard-sdk-0.1.0.tgz
```

The package has no runtime dependencies and requires Node.js 20 or newer. In a receiver host, initialize it and submit a typed paper order:

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

Use HTTPS for non-loopback receivers. `ORDERGUARD_URL` and `ORDERGUARD_BEARER_TOKEN` can provide defaults; do not put tokens in URLs or logs. The SDK calls `/api/human-mandate/status`, `/api/chat`, `/api/paper-orders`, and `/api/snapshot`; it never accesses a ledger or venue directly. `cancel()` can only start the receiver's human step-up ceremony.

## Verify

```sh
npm test
npm pack --dry-run
```

Release status: **owner packaged; receiver review pending**. This package currently targets the mesh's LocalSim paper routes. It is not a broker certification or production trading client.
