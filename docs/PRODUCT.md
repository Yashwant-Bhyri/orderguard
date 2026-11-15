# OrderGuard product brief

**A thousand AI agents. One signed mandate. Nothing outside it reaches the market.**

OrderGuard lets one person safely authorise thousands of AI trading agents. Code enforces the limits they signed, a risk model catches the bad flow that breaks no single rule (one position split across agents, runaway loops, colluding groups draining a shared budget), and people review only the orders most likely to cost money. It sits between the agents (any model, any tools) and the ledger. It is a working prototype on paper ledgers, not a hosted service.

## Who it is for

- **Exchanges and brokers** that will receive order flow from customers' AI agents, and want a control that does not depend on the agent being honest or well built.
- **Trading and product teams** that run their own agents, or swarms of them, and need a human to stay accountable for what those agents may do.
- **Risk, compliance and audit**, who need every decision explained in plain words and reproducible from a record.

## Jobs to be done

| When... | I want to... | OrderGuard gives you |
|---|---|---|
| an agent proposes an order | know it is within what the account owner approved | a signed mandate checked in code at a trusted price, with reasons for every refusal |
| many agents share one budget | stop them from splitting one big position or starving each other | shared daily budgets, per-symbol and position caps, orders-per-day limits |
| behaviour looks wrong across the swarm | hold it for a person before it reaches the ledger | a risk layer that can only tighten, and a ranked human review queue |
| an agent reads news, feeds or filings | stop false or injected text from turning into orders | input screening, filing checks on cited figures, two-source rule for standing triggers |
| a desk writes a new mandate | see what it would allow before anyone signs it | draft review against the signed parent and replay of recorded traffic through candidate limits |

## How a desk would roll it out

OrderGuard has no single "shadow mode" switch today. The stages below use what ships.

1. **Shadow.** Call `POST /api/check-order` (or the MCP `check_order` tool) next to your existing order path and log the verdict without acting on it. In parallel, replay recorded proposals through candidate limits with the envelope lab (`og-arena frontier`) to see what each would have refused, held and allowed.
2. **Holds.** Start sending holds to people: set a conservative step-up threshold in the mandate and switch on the risk layer, so unusual orders wait for a human while ordinary flow passes. The review lane orders that queue by expected bad dollars.
3. **Enforce.** Make the receiver the only path to the ledger. It re-checks the signed mandate at commit time, keeps a hash-chained ledger and honours revocation. Refusals now block.

At every stage the owner signs the limits; nothing widens them without a new signature.

## What it is not

- **Not a trading strategy.** It bounds what a wrong or fooled agent can do. It does not judge whether a trade is a good idea.
- **Not a broker or an exchange connector.** This release writes to paper ledgers; a venue connects as an adapter behind the receiver.
- **Not a model that approves orders.** Models screen text and rank the review queue. Only code says yes.
- **Not affiliated** with any brokerage or exchange.

## Integration surface

| Surface | What it does | Docs |
|---|---|---|
| HTTP API | Check an order, screen text, evaluate standing rules, review a held order or a mandate draft | [API.md](API.md) |
| MCP server | The same checks as tools for any MCP client; only `submit_order` can reach a ledger, and only through the receiver | [MCP.md](MCP.md) |
| Python | `run_agent` wraps an agent loop with every check | [GUIDE.md](GUIDE.md#integrating-your-own-agent) |
| Receiver and Node SDK | The final authority before the ledger, with idempotency and revocation | [OPERATIONS.md](OPERATIONS.md), [receiver docs](receiver/architecture.md) |
| Policy packs | Four unsigned templates to size and sign | [policies/](../policies/README.md) |

## FAQ

**Does an LLM ever approve an order?**
No. The mandate check, the portfolio limits and the receiver are plain code. Models appear in two places: screening text before the agent reads it, and advising on held orders. Advice can add a warning or a hold; there is no code path from advice to an approval, and tests check that ([REVIEW.md](REVIEW.md#the-rule)).

**What does it cost per decision?**
The order path makes no model call. The mandate check is code that runs in microseconds ([BENCH.md](BENCH.md)); the risk layer scores an order in about 40 µs median and 142 µs at p99 in pure Python ([RISK.md](RISK.md)). Model costs sit off the order path: the optional input screen is billed per text chunk by your provider, and the review lane recorded about US$0.075 per 1,000 triage calls ([REVIEW.md](REVIEW.md)). Every process enforces a spend cap.

**What happens when a model is wrong?**
It can only make things stricter. The risk layer can turn an allow into a hold or a refusal, never the reverse, and a property test checks that over 5,000 random decisions. A wrong model costs some honest flow (orders held for a person); it cannot authorise anything the signed mandate forbids. If the input screen misses a fake, the order still has to pass the mandate check at the trusted price.

**How do we tune it?**
Start from a policy pack, size it to your account and sign it (`orderguard policy sign`). Use the envelope lab to replay recorded traffic through candidate limits and compare refusals, holds and leaked notional before you sign a change. Review the queue with the triage ranking: on a recorded swarm, ranking by expected bad dollars reached 90% of them in 470 reviews instead of 719 first-in-first-out ([REVIEW.md](REVIEW.md)).

**Can we see it working?**
Run `sh scripts/quickstart.sh` and open `/theater` for the 90-second replay of a 1,000-agent run, or read the [README](../README.md#proof) for the headline numbers and [EVIDENCE.md](EVIDENCE.md) for the detail.
