# OrderGuard, the vision version: the product specification

Status: working specification, 2026-11-17. It brings together, in one place:

- the outside research brief that started this direction ("Rethinking OrderGuard");
- the founder's additions to it;
- our extension of it in [AUTONOMY.md](AUTONOMY.md);
- what has been built since.

Every item carries two tags.

**Where it came from:**

- **[brief]**: the research brief.
- **[founder]**: the founder's own words.
- **[ext]**: our earlier extension.
- **[new]**: added in this pass.

**How far it has got:**

- **SHIPPED**: in the released product, on paper ledgers.
- **BUILT**: in `python/orderguard_autonomy/` on this branch, tested in simulation only.
- **DESIGNED**: written down, not built.
- **PROPOSAL**: a research direction, stated as such in public.
- **GAP**: missing from everything so far.

## 0. What the product is

**One sentence [brief].** An AI agent should not receive general trading authority. It should receive continuously enforceable, risk-bounded authority over a specific set of financial actions. Every resulting order is checked against the actual portfolio state and against its delegated purpose.

**The primitive [brief].** The *Autonomy Contract*: a risk-aware delegation contract enforced against the evolving portfolio and all outstanding agent actions.

**The bigger product [founder].** OrderGuard is the whole harness and runtime for trading agents: "pre-trade infrastructure for AI agents, and a runtime harness to execute the trades safely inside the trading sandbox". It is a carefully hedged form of automation. The tax it pays is the safety that keeps loopholes and self-degrading behaviour out.

**Three versions [brief].**

| Version | Proposition | Where we are |
|---|---|---|
| 1.0 | Stop unauthorized agent orders | SHIPPED |
| 2.0 | Keep agents inside portfolio-aware, signed risk constraints | BUILT, simulation only |
| 3.0 | Continuously govern what agents may do, why they do it, and how their collective actions change risk | Partly BUILT; System One is a PROPOSAL |

Build 2.0 as the foundation for 3.0.

**The three questions, and who answers each [brief, founder].**

| Question | Nature | Answered by | Guarantee |
|---|---|---|---|
| Is it authorized? | Cryptography and arithmetic | Hard policy engine | Yes, from signed state |
| Is it risk-acceptable for the portfolio as it will be? | Arithmetic over projected state, plus estimates | Risk engine | The arithmetic, yes. The estimates, only under stated assumptions |
| Does it still serve the purpose it was delegated for? | Semantic judgement, a grey area | System One (section 6) | None. It is supervised, never proven |

**The hierarchy [founder], and the one rule that keeps it safe [ext].**

- **Information flows up.** System One reads purpose and evidence and produces a calibrated judgement. That judgement informs the risk posture. Risk feeds the authorization decision. Risk control is grounded in risk modelling and authorization, not in prompts.
- **Authority flows only down.** Only deterministic code says yes. Models can tighten, hold or shrink a budget. They can never approve, release a hold or widen a limit, and if they fail, the decision falls back to no advice.

**What it promises [brief].** Autonomy that is bounded, supervisable and accountable. The authority can be specified, measured, restricted, monitored and withdrawn.

**What it does not promise.** It does not make agents profitable and it does not make capital safe.

**What lies beyond the conventional stack [ext, measured].** Trading platforms already know the account: aggregate limits, working orders, kill switches. They do not know the agent. The benchmark found that D's lead over a competent stack comes from *binding*, not from better risk maths: each reservation is tied to an agent, a signed contract, a typed intent, a lease and the root of its evidence. This answers the founder's question "what is there beyond TT".

## 1. The Autonomy Contract (component A)

### 1.1 Three objects, never merged [brief, ext]

- **Intent**: the owner's words.
- **Proposed policy**: the numbers a model suggests for those words.
- **Signed policy**: the numbers the owner actually signs.

The diff between proposed and signed is itself signed. BUILT.

### 1.2 Fields

What ships today (SHIPPED):

- `symbols`, `sides`
- `maxOrderNotionalUsd`, `maxDailyNotionalUsd`
- `priceBandPct`, `stepUpAboveUsd`
- `expiresAt`
- optional: `maxSymbolDailyNotionalUsd`, `maxPositionUsd`, `maxOrdersPerDay`

What the brief adds (BUILT as contract predicates):

- **Identity:** `contract_id`, `principal`, `authorized_agents`.
- **Trading:** `allowed_assets`, `allow_short_selling`, `allow_leverage`, `max_single_order_usd`.
- **Portfolio:** `max_single_issuer_weight`, `max_technology_factor_exposure` (sector cap in the build), `max_loss_usd_in_declared_stress_suite`, `max_daily_turnover_usd`.
- **Autonomy:** `authorization_lease_seconds`, `max_orders_per_agent_per_hour`, `human_review_on_policy_exception`, `require_fresh_risk_state`.

Our additions (BUILT):

- the risk budget in ES units;
- gross exposure;
- a declared scenario set;
- a schema that says which way each limit may move.

### 1.3 How a contract is made

- **Elicit through consequences, not parameters [ext].** Show the owner what a proposed policy would have done in declared scenarios, then let them adjust. BUILT (consequence explanations); the shipped mandate forecaster does a version of this.
- **Mandates made on the go, inside the human's envelope [founder, 2026-11-14].** The human signs one envelope. For each agent and task, the copilot drafts a sub-mandate fitted to what that agent is doing. Code checks that the draft only narrows the envelope (attenuation), and a scope check asks whether the action fits the mandate.
  - SHIPPED in part: mandate copilot, draft review against a signed parent, semantic scope.
  - BUILT: attenuation chains.
  - GAP: a policy for when a fresh sub-mandate may be issued without a human. For example, within N% of an existing signed sub-mandate, otherwise a human signs.
- **Compiled to predicates [brief, ext].**
  - Hard predicates can refuse: permissions, caps, band, no short, gross, issuer, sector, declared-scenario loss, rate.
  - Model predicates can only hold: statistical ES, regime, liquidity, behaviour, thesis consistency.
  - A risk-reducing order always passes the caps.
  - BUILT.

### 1.4 Gaps in the contract

- **GAP [new]: pinned definitions.** "Technology exposure" means nothing until the sector taxonomy and factor model are named. The contract must pin the version of its classification, factor model and scenario set, or the same signature means different limits next month.
- **GAP [new]: who may sign and change it.** Missing pieces:
  - roles;
  - four-eyes approval above a size;
  - the amendment and versioning lifecycle;
  - emergency tightening by a risk officer without the owner;
  - what happens to working orders when a contract is superseded.
- **GAP [new]: key custody.** Missing pieces:
  - the owner's signing key in a hardware key or KMS;
  - rotation;
  - recovery;
  - what a stolen owner key can do (bounded by expiry, revocable by a second key).

## 2. The authoritative state engine (component B)

- **State [brief]: $S_t=(P_t,O_t,B_t,M_t,A_t)$.**
  - $P_t$: filled positions.
  - $O_t$: working and partly filled orders.
  - $B_t$: budgets and reservations.
  - $M_t$: trusted market data.
  - $A_t$: authorizations and policy versions.

  BUILT.
- **Order lifecycle [brief].** PROPOSED → POLICY_VALIDATED → RISK_RESERVED → SUBMITTED → ACKNOWLEDGED → PARTIAL/FILLED/REJECTED/CANCELED → RECONCILED. BUILT.
- **Conservative projection [brief, ext].** Every risk-increasing working order is assumed to fill and no risk-reducing one is. An uncertain broker state stays reserved until reconciliation proves otherwise. Retries carry idempotency keys. Exactly-once across independent brokers is never claimed. BUILT.
- **Ledger, and the blockchain question [founder asked, ext answered].** Inside one firm there is one trusted operator, so the right design is:
  - a single-writer sequencer per risk domain with fencing tokens;
  - a hash-chained log and signed checkpoints;
  - optionally, the root anchored publicly.

  Consensus earns its cost only across parties that do not trust each other. BUILT, except anchoring.
- **Hierarchical risk escrow [founder's "containerized" instinct, ext].** Firm, then book, then agent. Each child admits against its own allocation with no global lock. It asks its parent for more, and idle capacity returns to the root. BUILT.

**Gaps in the state engine:**

- **GAP [new]: Outside fills.** Trades the human or another system makes must enter $P_t$ through a broker drop-copy or position feed. Otherwise the projection is wrong from the first manual trade.
- **GAP [new]: Market plumbing that changes $P_t$ without an order:**
  - corporate actions (splits, dividends, symbol changes);
  - settlement (T+1) and cash versus buying power;
  - margin;
  - halts and auctions;
  - short locates once shorting is allowed.
- **DESIGNED, open: failover.** The design of a standby for the single writer, and how many seconds of admission may pause during a failover.
- **GAP [new]: OrderGuard's own failure mode.** Must be written as a spec line: fail closed for new risk, fail open for cancels. If OrderGuard is down, agents can always take risk off and never add it.

## 3. The counterfactual risk engine (component C)

- **The core question [brief].** How does this order change the risk of the portfolio we already hold? The measures are $\sigma_p=\sqrt{w^\top\Sigma w}$, $ES_\alpha$, and $\Delta ES$ of the order. BUILT.
- **What maturity needs [ext]. All BUILT:**
  - Ledoit-Wolf shrinkage and a factor covariance;
  - a stressed covariance and a regime detector with hysteresis;
  - Student-t ES;
  - liquidity cost from market impact;
  - Kupiec and Acerbi-Szekely backtests.
- **Reservable risk [ext].** Volatility and ES are subadditive, so a risk budget can be reserved per order like dollars. The sum of reservations is a sound upper bound, which avoids searching $2^n$ fill combinations. Euler allocation returns the diversification benefit at reconciliation. BUILT.
- **Hard and model-dependent controls kept apart [brief].** Loss under *declared* scenarios is arithmetic once the scenarios are signed, so it can refuse. Statistical ES can only hold. BUILT.
- **Distilled risk [founder, 2026-11-14].** Simulation and heavy maths are distilled into microsecond formulas or tiny models for the order path. SHIPPED as a prototype: the budget-exhaustion forecast, 0.78 µs, AUC 0.80. It is not good enough to act on alone.
  - [new] A distilled surrogate used for admission must be an *upper bound* on the quantity it replaces. That needs a conservative training objective and a measured violation rate, otherwise distillation silently loosens a limit.

**Gaps in the risk engine:**

- **GAP, found by the benchmark: pre-trade control cannot take risk off.** When volatility jumps, a book goes over its signed budget with no new order. The product needs a de-risking action the owner pre-approves: "if over budget, these agents may reduce by up to X, by these means", or a one-tap human approval. It is not designed yet. The founder's "keep the whole system running" requirement depends on it.
- **GAP [new]: Model risk governance**, the discipline banks apply to every model under SR 11-7. Missing pieces:
  - each risk model versioned and pinned in the contract;
  - its error band published next to every ES figure (open question in JOURNAL);
  - independent validation before a model can tighten live flow.
- **GAP [new]: Asset coverage.** US equities and ETFs only today. Options need Greeks and nonlinear scenario loss. Leverage and shorts need margin and locates. Crypto and FX need 24/7 state. Each is a real extension of component C, not a configuration change.

## 4. Continuous supervision (component D)

- **A closed loop, not a gate [brief].**
  - Observe actions, market and portfolio.
  - Evaluate authority, risk, evidence and drift.
  - Control: continue, reduce limits, require review, or suspend new risk while still allowing cancels.
  - Reconcile, then observe again.

  BUILT.
- **Authorization leases with epochs [brief, ext].** Authority expires unless renewed under current state. One epoch bump revokes a whole delegation chain, including spawned agents and pending actions. BUILT.
- **Drift [brief, founder].** Is the agent still pursuing the signed objective? Bernoulli CUSUM plus distance from the signed style. In the benchmark this caught every drifting agent with no false alarms. BUILT.
- **Herding [brief, founder].** "Three independent agents on one unverified rumour is one opinion, not three." Measured as sector-level flow plus a shared root source in the evidence. BUILT.
- **Loops [brief, founder].** Repetition in actions, with a rate that tightens as repetition rises. BUILT. Also SHIPPED in the swarm model as the runaway-loop family.
- **Pacing [ext].** Guaranteed shares that fade over the day, so no agent or coalition starves the rest. BUILT. It has a measured cost to the fast agent, and the owner must choose the shares (open).
- **Selective human review [brief].** A ranked queue ordered by expected bad dollars. SHIPPED.

**Gaps in supervision:**

- **GAP [founder, 2026-11-16, not yet a primitive]: Context integrity.** The founder's point: an agent's reasoning can be right while the context it reasoned from has already been corrupted. Corruption snowballs because no judge watches the context, and this is the long-horizon failure seen in coding agents too. Today we have:
  - evidence provenance (reposts collapse to their root);
  - memory-poisoning features in the judgement baseline.

  The missing primitive is a context ledger: every item in an agent's working context carries its source, its age and a hash, and every claim an order relies on traces back to it.
  - A quote that does not match its cited source is caught by code (hash and span check), not by a model (JUDGEMENT.md plan item 6).
  - The signed goal is re-injected at fixed intervals.
- **GAP [brief named it, not built]: Graduated autonomy.** Lease length and limits fixed per contract are not enough. Autonomy should widen *only by a new signature* after a measured track record, and narrow automatically after incidents. The system proposes, the owner signs. "Dynamic autonomy contracts" in the brief's system D point here.
- **GAP [new]: Self-trading and market conduct across one owner's agents.**
  - Two agents of the same owner can trade against each other (wash trades), or place and cancel in patterns that look like spoofing or layering.
  - Self-match prevention and a market-abuse surveillance view across the swarm are obligations a broker will ask about first.
  - The simulator's "tremors" and "crowding" results already show agents moving prices.

## 5. Proof-carrying orders (component E)

- **The decision certificate [brief].** Every order arrives with: the order, the agent and its strategy version, the delegation, the intent (objective, horizon, evidence references), and the authorization (policy version, portfolio snapshot, reservation). BUILT, about 900 bytes, Ed25519.
- **What the receiver checks [ext].**
  - signature and trusted issuer;
  - policy version and snapshot freshness;
  - lease epoch;
  - a reservation that covers the order, or, for a risk-reducing order, that it still reduces;
  - evidence freshness.

  It then seals a signed receipt into the ledger. BUILT.
- **What it proves and what it does not [brief].** It proves the order was admitted against this authority, this state and this evidence. It does not prove the thesis was right; claiming that would be security theatre. BUILT: the certificate says so itself.
- **Commercial form [brief].** A standard authorization receipt that a broker receiving third-party agent flow can verify. DESIGNED, not specified as an external format.
- **GAP [new]: prior art and naming.** Agent payment protocols already use signed "mandates" and scoped tokens. Stripe's shared payment tokens are in RESEARCH.md. Other agent-payment mandate schemes are not yet checked. Before publishing a receipt format, survey them so OrderGuard's format can interoperate rather than collide.

## 6. System One: financial judgement for agents (component F)

**Status: PROPOSAL.** It stays a proposal in public. It is the potential the launch points to, not a feature.

**Superseded in part (2026-11-19).** The exploration in [SYSTEM-ONE.md](SYSTEM-ONE.md) and the research report in [reports/](reports/) refine this section. In short:

- The target becomes the owner's *endorsement probability*.
- Agent-native failures become shapes in a decision-time provenance graph.
- Purpose attribution borrows Brinson and Euler from finance.
- System One works at six levels.
- The calibration target is split between in-distribution and shifted data.
- The name carries a risk: it is already used by a decision-model vendor.

Where they differ from this section, they win.

### 6.1 What the founder proposed (2026-11-16)

- A *System One for financial intelligence for agents*: a decision model that understands what "does this still serve the purpose it was delegated for" means.
- General-purpose LLMs do not grasp that nuance. Humans differ on it too.
- The model would be built from a base decision model, by one or more of:
  - post-training on financial decisions;
  - robust fine-tuning;
  - adding domain knowledge;
  - better representations of "serving the purpose".
- It holds long-horizon understanding of how an investment objective evolves, using credible evidence.
- It produces reasoning that informs the risk layer, which in turn informs authorization.
- The analogy is the typed, calibrated decision models that recently changed how the field thinks about decisions. One such model was measured in RISK.md.

### 6.2 What the extension specified (AUTONOMY.md 3F, JUDGEMENT.md)

- **A persistent delegation state:**
  - purpose and signed style;
  - active theses with their evidence and its freshness;
  - what has already been tried;
  - exposure history.
- **Scoring:** each new action is scored against that state over long horizons.
- **Training:** on simulated episodes whose long-run outcome is known.
- **Bounds:** calibrated, tighten-only, degrades to no advice.

### 6.3 What exists and what it showed (BUILT, honest)

- **The baseline.** Fourteen interpretable features and a calibrated logistic model.
- **In distribution:** AUROC 0.97.
- **On an adversarial shift:** AUROC 0.63, with recall at 5%.
- **Against the deterministic drift monitor:** the monitor did better, so System One is not wired into D.
- **One order at a time:** the typed decision model ranked held orders almost perfectly (AUC 0.998 on a 200-order sample) at about 1.1 s per call. That is a slow-lane tool, not a gate.

### 6.4 Specification for System One [new, from all of the above]

1. **It answers typed questions with calibrated probabilities, never prose.** The questions:
   - P(the action serves the signed purpose);
   - P(the cited evidence supports the claim);
   - P(the agent's context is corrupted);
   - P(this is a change of course with a documented reason, rather than drift).

   Its explanation must point at typed records (a thesis, an evidence hash), not at free text.
2. **It judges theses, not orders.** This is how it stays off the microsecond order path.
   - When an agent opens or changes a thesis (a typed record of claim, horizon, invalidation condition and evidence hashes), System One judges it asynchronously, in seconds.
   - The order path then only checks, in code, that the order belongs to a thesis already judged and still valid.
   - A new thesis waits for its judgement. An order that belongs to no thesis is held.
3. **It is bound by the same rule as every model.** It may tighten: hold, shorten a lease, shrink a budget. It never approves.
4. **It is trained and tested on ground truth that is not ours:**
   - forward paper trading after the model's training cutoff, with owner-written objectives;
   - drift and poisoning injected by a red team that does not see the features;
   - documented-change versus abandonment pairs, so its false-hold cost on good agents is measured.
5. **Done looks like this.** On held-out, independently labelled episodes it beats the deterministic monitor on lead time at the same false-hold rate, with calibration error under 0.05. It never loosens a decision.
6. **The simulator is its training ground.** The impact-aware market and the million-agent arena become the place where long-run outcomes are known.

## 7. The foundational pieces

These are the things being built at a foundational level, under the product.

| # | Piece | What it is | Status |
|---|---|---|---|
| F1 | **System One** | Calibrated long-horizon judgement of purpose, evidence and context (section 6) | PROPOSAL; baseline BUILT |
| F2 | **Programmed swarm risk model** | Rules written directly into model weights (7 programmed units), plus 80 learned monotone trees, combined by noisy-OR. A new failure family can be added from one labelled example by a one-shot weight edit. 40 µs median, tighten-only | SHIPPED |
| F3 | **Decision adapter and slow lane** | A typed decision model fitted for review triage, the mandate copilot and the semantic scope check. Probabilities, not prose; advice only | SHIPPED in part |
| F4 | **Distilled risk** | Simulation and heavy portfolio maths reduced to microsecond formulas, which must be conservative (section 3) | Prototype SHIPPED |
| F5 | **The wind tunnel** | An impact-aware market simulator and the million-agent arena (12,946,507 orders, 0 limits broken). Today it is the test bed; next it is System One's training ground and the certification suite | SHIPPED |
| F6 | **Assurance workbench** | 180 curated attacks, adaptive attackers, a red team that becomes permanent regression tests. Enforcement and assurance are two halves of one product | SHIPPED |
| F7 | **Verified data layer** | Input screening, filing checks on cited figures, a trusted price, the two-source rule for triggers. Next: the context ledger (section 4) | SHIPPED; context ledger GAP |
| F8 | **Reservation ledger and risk escrow** | Linearizable admission over shared risk capacity, firm to book to agent | BUILT |
| F9 | **Autonomy Contract language** | Intent, proposal, signature; attenuation chains; compiled predicates | BUILT |
| F10 | **Decision certificates** | Proof-carrying orders and receipts | BUILT; external format DESIGNED |
| F11 | **The runtime harness** | The process agents run inside: it writes intent records itself (not the agent's tools), holds no signing key the agent can reach, and is the only route to the receiver | GAP (see below) |
| F12 | **The four-system benchmark** | A to D, measuring safety and usefulness together; the result that matters is D beating a competent C | BUILT; external review GAP |

**Why F11 matters most among the gaps.** The benchmark's tool-compromise win rests on one assumption: the agent's runtime writes the intent records, not the agent's tools. Without it, D falls back to its caps and $132k got through. The runtime harness is what turns that assumption into a property. The open choice is how: a separate process, a separate key, or attestation. This is also the concrete form of the founder's "OrderGuard as the whole harness and runtime".

## 8. Checked for what was missed

Against the brief, the founder's messages, AUTONOMY.md, JUDGEMENT.md, JOURNAL.md and the shipped docs.

**From the brief, not yet done:**

- Stage 3: shadow mode against a real broker's order and position feeds, then limited live use after security and compliance review. Not started.
- The benchmark with agents that are not scripted. The brief asked for adversaries who know how the risk engine works; ours are scripted, and the same team wrote the scenarios and D.
- Measuring estimated against realized losses on held-out scenarios, under changing correlations.
- Multi-broker global state. Deliberately later.
- The first customer, from the brief: developers and trading teams already letting agents propose trades. No pricing, packaging or pilot plan is written yet.

**From the founder, not yet done:**

- Context integrity as a first-class primitive (section 4).
- Mandates made on the go without a human each time: the rule for when that is allowed (section 1.3).
- The runtime harness and trading sandbox as the product's outer shell (F11).
- A simple, relatable cascade example for the vision page, not the $20,000 tech-exposure illustration. A story person, not an engineer, owns this.

**New in this pass:**

- de-risking;
- pinned definitions;
- signer roles and key custody;
- outside fills and market plumbing;
- the fail-closed-for-new-risk rule;
- model risk governance;
- self-trading and market conduct;
- conservative distillation;
- the asset-class roadmap;
- prior art on agent mandates;
- System One judging theses rather than orders.

**Still open from JOURNAL.md:**

- lease units;
- the reservation ledger's standby;
- herding false-alarm control across thousands of agents;
- certificate size;
- pacing shares;
- how runtime-written intents are enforced.

## 9. Suggested order from here

1. **F11, the runtime harness.** It closes the biggest assumption in the evidence, and it is the bigger product.
2. **De-risking, and the fail-closed-for-new-risk rule.** Without them the control loop can only stop, never recover.
3. **The thesis record and the context ledger.** Both are code, both are needed before any System One model, and they recover part of the judgement signal with no model at all.
4. **System One research, following section 6.4.** Ground truth first, model second.
5. **Shadow mode on live-forward paper data**, with the scenarios reviewed by someone outside the team.
