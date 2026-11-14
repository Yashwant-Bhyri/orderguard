# Policy packs

Four unsigned Mandate templates. They are starting points, not advice: size them to your account. They are not derived from the envelope-lab
frontier in `results/arena/` (that run models a 1,000-agent swarm sharing envelopes, a different scale from one person's account); the order-of-magnitude
ratios between per-order, daily, per-name and position caps are judgment calls, and the lab (`og-arena policy`, `og-arena frontier`) is the place to test a variant.

| Template | Per order | Per day | Per name per day | Net position | Orders/day | Band | Step-up above | Lifetime |
|---|---|---|---|---|---|---|---|---|
| `conservative-equities` | $2,500 | $10,000 | $4,000 | $7,500 | 10 | 0.5% | $1,500 | 168 h |
| `balanced-equities` | $10,000 | $40,000 | $15,000 | $25,000 | 30 | 1.0% | $6,000 | 72 h |
| `active-equities` | $25,000 | $150,000 | $50,000 | $75,000 | 100 | 1.5% | $15,000 | 24 h |
| `crypto-sleeve` | $5,000 | $25,000 | $10,000 | $15,000 | 40 | 2.5% | $3,000 | 24 h |

Each file is the Mandate JSON shape with `ttlHours` instead of `expiresAt` (resolved when you sign) and an `_about` note. `maxSymbolDailyNotionalUsd`,
`maxPositionUsd` and `maxOrdersPerDay` are the optional portfolio limits; the gate, the arena and the receiver all enforce them from the signed mandate.

```bash
orderguard policy list
orderguard policy show balanced-equities
orderguard policy sign balanced-equities --key var/orderguard/signing.key --out var/orderguard/mandate.json
orderguard policy sign balanced-equities --key var/orderguard/signing.key --out mandate.json --symbols AAPL MSFT
```

`sign` refuses a template that contradicts itself (per-order cap above the daily cap, a per-name cap above the daily cap or below the per-order cap, a position cap
below the per-order cap, a step-up above the per-order cap, a bad `ttlHours`, unknown fields). `--symbols` only replaces the allow-list. Templates carry no
`referencePrices`: the gate and receiver then need a trusted quote source, or add `referencePrices` to the signed file by editing a copy of the template.
Quantities are whole units, so a symbol priced above the per-order cap (BTC at today's prices, say) cannot trade until you raise that cap.
