# Continuous autonomy control: design direction

Status: stages 1 and 2 are built and tested in simulation; nothing here runs against a real broker. The code lives in `python/orderguard_autonomy/`. What was built and what the benchmark found are in section 8. The method and full results are in [BENCHMARK.md](BENCHMARK.md), and the judgement model's research plan is in [JUDGEMENT.md](JUDGEMENT.md). The running record of how this idea developed is in [JOURNAL.md](JOURNAL.md).

## 1. The problem, stated precisely

OrderGuard today answers one question well: *is this order authorized?* A signed mandate, a trusted price, a swarm risk model that can only tighten, a review queue and a hash-chained ledger.

Trading adds a dimension that payments do not have: **the economic consequences of permitted actions accumulate over time.** A purchase ends at checkout. A position keeps moving, interacts with every other position, and creates future obligations. So a sequence of individually authorized orders can build a portfolio nobody would have signed.

Three questions, not one:

| Question | Nature | Can it be guaranteed? |
|---|---|---|
| Is this order authorized? | Cryptographic and arithmetic | Yes, from signed state |
| Is it risk-acceptable for the portfolio as it will be? | Arithmetic over projected state, plus statistical estimates | The arithmetic, yes. The estimates, only under stated assumptions |
| Does it still serve the purpose the owner delegated? | Semantic judgement | No. It can be supervised, never proven |

The design rule that follows, and that OrderGuard already enforces: **deterministic checks decide; models can only tighten.** Nothing probabilistic is ever presented as an authorization guarantee.

### What existing pre-trade controls cover, and what agents add

| Existing controls handle | Agent-native challenge |
|---|---|
| Is the order too large? | Does the order still serve the delegated investment purpose? |
| Is the account over its position limit? | Are agents independently reinforcing one mistaken thesis? |
| Is the price outside permitted bounds? | Was the decision based on fabricated or stale information? |
| Has an algorithm exceeded its message rate? | Has an agent entered a repetitive reasoning or action loop? |
| Can a desk stop the algorithm? | Can authority be withdrawn across spawned agents and pending actions? |
| Can the firm reconstruct an execution? | Can it reconstruct the evidence, delegated authority, policy and resulting action? |

Honesty about the left column: serious platforms (Trading Technologies, Interactive Brokers, any broker under SEC Rule 15c3-5 or MiFID II RTS 6) already do aggregate account checks, working-order exposure, credit limits and kill switches. OrderGuard must not claim those as new. The opportunity is the right column, and joining it to the left column under one signed authority.

## 2. The organizing principle

> An agent never receives general trading authority. It receives continuously enforceable, risk-bounded authority over a specific set of actions, and every resulting order is checked against the portfolio as it will be, including everything still outstanding, and against the purpose it was delegated for.

The primitive is an **Autonomy Contract**: a risk-aware delegation contract enforced against the evolving portfolio and all outstanding agent actions. Four parts:

1. **A signed specification**: what the owner actually signed.
2. **An authoritative portfolio state**: positions, working orders, reservations, obligations.
3. **An admission controller**: allow, hold or refuse each action against (1) and (2).
4. **A continuous feedback loop**: observe, evaluate, control, reconcile, and observe again.

## 3. Component review: what is naive, and what maturity needs

### A. From intent to a signed specification

Three distinct objects, never merged:

- **Intent**: the owner's words. "Grow it, don't bet everything on one theme."
- **Proposed policy**: numbers a model suggests for those words.
- **Signed policy**: the numbers the owner actually signed.

*Naive version:* an LLM translates "not too aggressive" into limits and the system enforces them. That silently moves a judgement from the owner to a model.

*Mature version:*
- The model proposes; the owner signs; the diff between proposal and signature is recorded.
- Preferences are elicited through **consequences, not parameters**. Show the owner what a proposed policy would have done in declared stress scenarios ("in this scenario you lose about this much"), then let them adjust. OrderGuard's mandate forecaster already does a version of this for limit hits.
- Delegation uses **capabilities with attenuation**: an agent can hand a sub-agent a narrower contract, never a wider one (the property macaroons, UCAN and Biscuit tokens are built around). Containment is already proven in code today for drafted mandates; the step is making it a chain.

### B. The authoritative state engine

The example: the account holds $10,000 of a stock and three agents each add $5,000. Checked one at a time against current state, each sees $15,000. If all fill, the account holds $25,000. This is a concurrency problem, made financial.

State: $S_t = (P_t, O_t, B_t, M_t, A_t)$: filled positions, outstanding orders, risk budgets and reservations, trusted market data, active authorizations and policy versions.

**On the blockchain idea.** The property we need is *linearizable admission over shared risk capacity*: every order is admitted against a state that already includes every earlier admitted order. A blockchain provides agreement among parties who don't trust each other, at the cost of latency measured in seconds. Pre-trade admission needs milliseconds and, inside one firm, has one trusted operator. So:

- **Within one owner or firm:** a single-writer sequencer per risk domain, with **escrow-style reservations** (O'Neil's escrow method: decrement shared capacity at admission, return the remainder at fill or cancel), event-sourced, with the hash-chained log OrderGuard already has for tamper evidence. Optionally anchor the log's root hash to a public chain so third parties can verify it was not rewritten later.
- **Across parties that don't trust each other** (several brokers, or a consortium sharing one exposure view): that is where consensus earns its cost, and it is a later, separate problem.

**Amendment: hierarchical risk escrow.** The "containerized" instinct is right in one form. Give each contract its own state partition (an actor that owns its reservations), and let a parent allocate capacity to children: firm, then book, then agent. A child admits orders against its own allocation without a global lock; it asks the parent for more when it runs low. This scales like sharding while keeping every cross-partition limit sound, because a child can never hold more than the parent granted.

**Working orders.** For linear limits (notional, net position per symbol) the conservative projection is current state plus every working order that would increase risk, assuming none of the risk-reducing ones fill. Trading Technologies already computes this kind of worst case. What OrderGuard adds is tying each reservation to the agent, the contract and the evidence that produced it.

**Uncertain broker state.** If the connection drops after sending an order, the order may or may not exist. The reservation stays held until reconciliation proves otherwise. Retries carry an idempotency key. Exactly-once execution across independent brokers cannot be promised; what can be promised is that capacity is never double-spent inside the boundary, and that every uncertain state resolves conservatively.

### C. The counterfactual risk engine

Question: how does this action change the risk of the portfolio we already have? The same $5,000 semiconductor purchase is fine in a diversified book and not in one already holding $70,000 of correlated technology.

With exposures $w$ and covariance $\Sigma$, portfolio volatility is $\sigma_p = \sqrt{w^\top \Sigma w}$. Expected Shortfall at level $\alpha$ is $ES_\alpha(L) = E[L \mid L \ge VaR_\alpha(L)]$, and the incremental risk of an order $d$ is $\Delta ES = ES_\alpha(w + d) - ES_\alpha(w)$.

*What is naive here:*
- **Sample covariance is unstable.** With many assets and limited history it is noisy and often near-singular. Mature: factor models (sector, style, market) with shrinkage toward a structured target (Ledoit and Wolf).
- **Correlations rise in crises.** A calm-period $\Sigma$ understates the tail exactly when it matters. Mature: stressed covariance and declared scenarios alongside the statistical estimate.
- **ES is hard to backtest.** It is not elicitable on its own, so you cannot simply score it against realized losses. Mature: joint VaR and ES backtests, and reporting calibration honestly.
- **Liquidity.** A position that cannot be exited at the trusted price is riskier than its volatility says. Mature: liquidity-adjusted loss using expected market impact (the simulator already models impact).

**The key technical insight: coherence makes risk budgets reservable.** $\sigma_p$ is a norm of $\Sigma^{1/2} w$, and ES is a coherent risk measure, so both are subadditive: $\rho(w + d_1 + d_2) \le \rho(w) + \rho(d_1) + \rho(d_2)$. That means a risk budget can be reserved per order, exactly like dollars in the escrow above, and the sum of reservations is a sound upper bound on the total. Admission becomes a cheap conservative check, with no need to search the $2^n$ fill combinations of working orders. Euler allocation, $\rho(w) = \sum_i w_i \, \partial\rho/\partial w_i$, then returns the diversification benefit at reconciliation.

**Two classes of control, kept separate:**

| Hard: computed from signed inputs | Model-dependent: estimated |
|---|---|
| Instrument permissions, order and position caps, leverage bans, revocation, loss in *declared* stress scenarios | Statistical ES, correlation regime, liquidity, behavioural anomaly, thesis consistency |
| Can refuse | Can hold or tighten, never approve |

Note the boundary case: loss under a declared stress suite is deterministic arithmetic once the scenarios are signed, so it can be a hard limit. It bounds loss *in those scenarios*, not real-world loss, and the page must say so.

### D. Continuous supervision

An agent is a process, not a request. So supervision is a closed loop: observe actions, market and portfolio; evaluate authority, risk, evidence and drift; control (continue, reduce limits, require review, suspend new risk while allowing cancels); reconcile and observe again.

- **Authorization leases.** Authority expires unless renewed under current state. Short leases make revocation bounded in time across spawned agents, which is the hard part of revoking capabilities in a distributed system. An epoch number in each lease lets one revocation invalidate a whole delegation chain.
- **Drift.** Sequential change detection (CUSUM, SPRT) on each agent's behaviour statistics, and a structured objective record to compare actions against. An agent's own explanation is not evidence of its reasoning, so semantic checks supervise; they never authorize.
- **Herding.** A graph of which agents trade together and on which sources. Three "independent" agents acting on the same unverified rumour is a correlation signal, not three opinions.
- **Loops.** Repetition in the action sequence (same tool, near-identical arguments, rising frequency) with a rate limit that tightens as repetition rises.
- **Pacing.** Spend of the risk budget over the day treated as a control problem, so one agent or coalition cannot starve the rest.

### E. Proof-carrying orders

Every order arrives with a decision certificate: which contract and policy version, which portfolio snapshot, which reservation, which evidence by content hash and timestamp. The receiver verifies signatures, versions, freshness and the reservation, and returns a signed receipt that is sealed into the ledger.

What it proves: the order was admitted against this authority, this state and this evidence. What it does not prove: that the thesis was right. Saying the second would be security theatre.

### F. Proposal: a long-horizon judgement model

A proposal, not a feature. A calibrated baseline now exists (section 8 and [JUDGEMENT.md](JUDGEMENT.md)). It does not yet earn a place beyond drift. Today's models judge one order, or one window, at a time. Delegated trading needs judgement that persists: what the book is for, which theses it currently holds, what has already been tried, and whether today's actions still fit.

The proposal is a model that keeps a structured, persistent state of the delegation (purpose, active theses, evidence and their freshness, exposure history) and scores each new action against it over long horizons. It is trained on simulated episodes where the long-run outcome is known, calibrated, and bound by the same rule as everything else: it can tighten, never approve.

Research questions: how to represent a thesis so drift can be measured; how to tell legitimate adaptation from abandonment of purpose; how to evaluate lead time (how early drift is caught) against false holds.

## 4. How we would know it works

Compare four systems on the same scenarios, not just OrderGuard against an unprotected agent:

| System | What it is |
|---|---|
| A. Bare agent | Direct paper-trading access |
| B. Mandate gate | Signed permissions, amount limits, revocation (OrderGuard today) |
| C. Competent conventional risk stack | Hierarchical exposure, working-order checks, position and credit limits, rate limits, kill switch |
| D. Continuous autonomy control | C plus contracts, projected-state admission, risk escrow, intent and evidence supervision, leases |

Scenarios: correlated buying across agents, objective drift, coordinated misinformation, delayed broker acknowledgements, volatility regime change, budget starvation, cross-venue execution, tool compromise.

Measure safety and usefulness together: hard-limit breaches, harmful exposure reached, false holds, legitimate executions completed, incremental portfolio risk, review burden, latency and behaviour under stale state. The result that matters is D beating C on a failure C allows. That has to come out of the experiment; it cannot be assumed. It has now been run in simulation; see section 8.

## 5. What OrderGuard promises, and what it does not

It does not make agents good traders, and it does not guarantee capital is safe. Markets lose money under perfectly specified strategies.

It makes the decision to give an agent trading authority far less frightening, because that authority can be specified, measured, restricted, monitored and withdrawn.

## 6. What the research changed

The cited brief is [RESEARCH.md](RESEARCH.md). What it changed in this design:

- **Working-order exposure is standard.** Trading Technologies documents worst-case position as current position plus working orders plus the possible fill of the new order; EU RTS 6 counts orders sent to a venue against limits immediately. So the reservation ledger is mandatory but not a differentiator. The differentiator is binding each reservation to an agent, a contract and its evidence.
- **No blockchain inside one firm.** A single-writer serializable reservation ledger with a hash-chained log and signed checkpoints gives everything needed. Consensus is warranted only when firms that don't trust each other must share one state, such as a cross-broker budget or kill switch.
- **Stripe's agent payment tokens are scoped per transaction** (seller, currency, maximum amount, expiry, revocable). Trading needs the same scoping plus the time dimension, which is the case this document makes.
- **Regulators are already naming the gap.** FINRA's 2026 oversight report points to agents acting without human validation, beyond their intended scope, with weak auditability. The FSB names market correlation from shared AI models as a stability risk.
- **Long-horizon coherence is the weak axis of agents.** Goal-drift and long-run coherence studies show every model drifting or derailing on long horizons. So the supervisor re-injects the signed goal at fixed intervals, compares behaviour against the contract with a separate simple check, and scores agents on what they did (cancel ratios, slippage, adherence) rather than what they say.
- **Backtested trading wins are weak evidence**, and multi-agent herding shows up only under some designs. The benchmark in section 4 has to run on live-forward paper data after the models' training cutoff.

## 7. Build order

1. **Risk-aware authorization.** Projected-state admission with working-order reservations, hierarchical escrow, issuer and sector exposure caps, declared-scenario loss limits. US equities and ETFs, paper broker, no leverage.
2. **Continuous supervision.** Leases with epochs, typed intent records, evidence provenance, drift and herding detection, and the system C baseline to compare against.
3. **Integration and validation.** Shadow mode against broker order and position feeds, then limited live use only with brokerage, security and compliance review.

Stages 1 and 2 are built and tested in simulation. Stage 3 has not started.

## 8. What was built, and what the benchmark found

### Built (`python/orderguard_autonomy/`; 140 tests in `python/tests/autonomy/` and `python/tests/test_autonomy_pathways.py`)

- **Contract (`contract.py`).**
  - Intent, proposed policy and signed policy are kept as separate objects. The proposed limits are explained through their consequences in declared scenarios, and the diff between what was proposed and what the owner signed is itself signed.
  - Contracts are Ed25519 over canonical JSON. A schema states which way each limit may move, so a delegation chain is checked as attenuation only.
  - The signed contract compiles to predicates. Hard predicates (permissions, caps, price band, no short, gross, issuer, sector, declared-scenario loss, rate) can refuse. Model predicates (risk budget, portfolio ES) can only hold. A risk-reducing order always passes the cap checks.
- **State (`state.py`).**
  - An event-sourced portfolio state with an order lifecycle.
  - A single-writer reservation ledger with fencing tokens, a hash-chained log and signed checkpoints.
  - Conservative projection over every subset of working-order fills.
  - Reconciliation that keeps uncertain orders reserved until the broker's complete record resolves them.
  - Hierarchical escrow (firm, book, agent) of dollars and ES units. Capacity flows down on demand and returns when idle. Locks are always taken child before parent.
- **Risk (`risk.py`).**
  - Gaussian and Student-t ES.
  - Ledoit-Wolf constant-correlation shrinkage, a factor covariance and a stressed covariance.
  - A rolling covariance and a regime detector with hysteresis.
  - Incremental ES, Euler and group Euler allocation, and liquidity cost.
  - Kupiec and Acerbi-Szekely backtests.
  - Declared-scenario loss. Its worst case over fills is checked against a linear program in the tests.
- **Admission (`admission.py`).**
  - Order of checks: idempotency, contract and version, hard predicates, intent match (a mismatch refuses and quarantines the lineage), intent-quantity dedupe, escrow, then model checks.
  - Combining is tighten-only. A hold reserves nothing; approving it re-admits the order.
- **Supervision (`supervise.py`).**
  - Leases with epochs per contract and lineage, with renewal refused on a stale snapshot, and revoke-all.
  - Typed intent records.
  - Evidence provenance, which collapses reposts and near-copies to their root.
  - Claim flags.
  - A Bernoulli CUSUM and a style distance for drift.
  - Behavioural herding on sector flows plus a shared source.
  - Time-windowed loop detection, and pacing with guaranteed fading shares.
- **Certificates (`certificate.py`).**
  - Each allowed order carries a signed certificate of about 900 bytes.
  - The receiver checks it with a short deterministic checker: signature, trusted issuer, policy version, snapshot freshness, lease epoch, a matching reservation that covers the order (or, for a risk-reducing order, that it still reduces), and evidence freshness. The receiver's receipt is sealed into the ledger, and the certificate states what it does not prove.

### Found (20 seeds; [BENCHMARK.md](BENCHMARK.md))

- **D beat the competent conventional stack (C) on its own harm measure in all eight scenarios,** with separated 95% intervals. It beat C with C's weak settings fixed (C+) in seven. D had zero hard-limit breaches.
- **Cross-venue is a tie with C+.** The gain there comes from consolidating checks across venues, which a conventional stack can also do.
- **Pre-trade control cannot de-risk.** In the volatility regime scenario D stopped adding risk once the true ES was over budget ($5k added, against $380k under C). Even so, the book stayed over its signed budget for the whole post-shock window under every system. Reducing risk already held needs a separate action that the owner approves.
- **Fairness has a price.** Pacing raised slow agents' completion from 0.39 to 0.63, but it held 210 of the fast agent's orders. Escrow alone (D_auth) made starvation worse (0.10), because escrow is first come, first served. The owner has to choose the share.
- **The tool-compromise win rests on an assumption:** intent records are written by the agent runtime, not by the order tool. Without that assumption, D falls back to D_auth's caps, which let $132k through.
- **The judgement baseline does not generalize.** AUROC is 0.97 in distribution and 0.63 on an adversarial shift, where recall falls to 5%. Drift is better caught by the deterministic monitor, which detected every drifting agent with no false alarms. The judgement model stays a research track.
- **The agents are scripted, and the same team wrote the scenarios and D.** The next evidence has to come from shadow mode on live-forward paper data, with scenarios reviewed by someone else.
