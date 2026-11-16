# Vision journal

This journal records how OrderGuard's product vision develops: where an idea came from, how it was interpreted, what was decided, and what is still open. Each entry is dated and numbered. Entries are appended, not rewritten, so the reasoning chain stays intact even when a later view changes an earlier one. Claims here describe intent and analysis. Anything marked as not yet implemented is not in the code.

---

## Entry 1: From order gate to continuous autonomy control

**Date:** 2026-11-16

### 1. Where OrderGuard stands today

OrderGuard is built and measured as a pre-trade gate for AI agents that trade under a shared mandate. The current pieces, per the README and `docs/ARCHITECTURE.md`:

- **Signed mandates enforced in code.** A human signs symbols, sides, per-order and daily caps, a price band and a step-up threshold. The gate checks the signature, expiry and revocation. No model can loosen it.
- **A trusted price.** Orders are sized at a broker or market quote the agent cannot influence, never at the agent's own limit.
- **A swarm risk model that can only tighten.** It scores allowed orders across all agents (split positions, bursts, loops, sudden size jumps). It can turn an allow into a hold or refusal, never the reverse.
- **A review queue ranked by money at stake.** Held orders are ordered by expected bad dollars. A decision adapter can add a hold but cannot approve.
- **A hash-chained ledger.** The receiver re-checks the exact order against the signed mandate and writes to an atomic, hash-chained paper ledger.
- **A receiver as the single path to the ledger.** The architecture doc describes it as the final authority. This release runs against simulated markets and paper ledgers, so a live broker connection would be an adapter on top of the receiver, not something already built.

### 2. The trigger

The founder's observation: **"the economic consequences of permitted actions accumulate over time."** Each order can pass every check while the portfolio drifts somewhere the mandate never intended.

The founder compared what pre-trade controls already ask with what agent-native systems raise:

| Existing pre-trade control | Agent-native question |
|---|---|
| Is the order too large? | Does the order still serve the delegated investment purpose? |
| Is the account over a position limit? | Are agents independently reinforcing one mistaken thesis? |
| Is the price outside bounds? | Was the decision based on fabricated or stale information? |
| Is the algorithm over its message rate? | Has an agent entered a repetitive reasoning or action loop? |
| Can a desk stop the algorithm? | Can authorization be withdrawn across spawned agents and pending actions? |
| Can the firm reconstruct the execution? | Can it reconstruct the evidence, delegated authority, policy and resulting agent action? |

The left column is what OrderGuard already covers. The right column is the new scope.

### 3. The proposed organizing principle

A **risk-aware delegation contract**, called an **Autonomy Contract** in discussion. It is enforced against the evolving portfolio and against all outstanding agent actions, and has four parts:

1. a signed specification,
2. an authoritative portfolio state,
3. an admission controller,
4. a continuous feedback loop.

Three things must be kept apart:

- **Human intent**: what the owner wants, in plain words.
- **A proposed quantitative policy**: a model's translation of that intent into numbers.
- **The policy the human actually signs**: the numbers the owner accepts, which become the enforceable contract.

The gap between the first two and the third is where errors would enter, so the signed artifact is the only thing the system enforces.

### 4. Components discussed

- **(A) Intent to enforceable contract.** Converting plain-language intent into a signed specification with reviewable terms.
- **(B) Real-time portfolio-wide state engine.** It projects state including outstanding orders. Example: an account holds $10,000 of a stock and three agents each add $5,000. Each agent, looking alone, sees $15,000. Together they hold $25,000. Admission must use the projected total.
- **(C) Counterfactual risk engine.** The same order can be acceptable in one portfolio and not in another. The engine measures portfolio volatility as sqrt(w'Σw), Expected Shortfall, and the incremental ΔES of a proposed order against the current book.
- **(D) Continuous supervision with authorization leases.** Authority is granted for a time and scope and must be renewed, so it can be withdrawn across agents and pending actions.
- **(E) Proof-carrying orders.** Each order carries a decision certificate and a receipt, so the evidence, authority and policy behind it can be reconstructed later.
- **(F) A proposal, not a feature.** A long-horizon judgement model for financial agents that sustains understanding across time. This is a research direction only.

### 5. Founder interpretations (open, not decided)

- A containerized blockchain state engine might supply the authoritative portfolio state in (B). Not evaluated.
- TT already computes worst-case exposure including working orders. OrderGuard's opportunity may be to join that discipline with delegated agent authority and the full agent-action lifecycle, rather than to build exposure maths from scratch. This is an interpretation to check against what TT actually does.

### 6. Guardrails stated so far

- Hard constraints stay deterministic and in code.
- Model-based risk can only tighten a decision.
- A probabilistic judgement is never presented as an authorization guarantee.
- OrderGuard does not promise profitable trades. It makes delegated authority bounded, supervisable and accountable.
- A credible benchmark must beat a competent conventional risk stack, not only an unprotected agent. The current benchmarks compare against a bare model, so they are not yet sufficient for this claim.

### 7. Next steps as announced

1. A research pass. Results will be added in a later entry.
2. A design critique that identifies the naive parts of this vision.
3. Code pathways, as interfaces only, clearly marked as not yet implemented.
4. A vision page on the website.

### Open questions

- Can a containerized blockchain state engine provide authoritative portfolio state, and at what latency and trust cost?
- Does TT's existing worst-case exposure calculation include working orders the way the founder describes? What can OrderGuard reuse, and what is missing?
- What is the right unit of an authorization lease: time, notional, symbol set, or a combination?
- How is "the evidence and policy behind an order" captured without storing sensitive strategy data?
- How is a long-horizon judgement model evaluated, and what would count as sustaining understanding?
- Which of the six agent-native questions can be checked in code, and which need a human or a model judgement?

### Decisions so far

- The signed mandate is the only enforceable contract. Intent and proposed policies are inputs, not authority.
- Hard constraints stay deterministic; model risk can only tighten.
- No probabilistic output is described as an authorization guarantee.
- OrderGuard makes delegated authority bounded, supervisable and accountable. It does not promise returns.
- Benchmarks must include a competent conventional risk stack as the comparison.
- Research, design critique, interface-only code pathways and a vision page are the next steps, in that order of intent. No implementation is started.

---

## Entry 2: Research pass, design critique and first pathways

**Date:** 2026-11-16

### 1. What the research confirmed

Source: [RESEARCH.md](RESEARCH.md). Labels below follow that brief.

- **TT worst-case position includes working orders** (confirmed, primary snippet): current position plus working orders on the same side plus the possible fill of the new order. This is industry practice, not new.
- **IBKR what-if is an analytics tool** (confirmed): a human previews projected P&L and risk, then must still review and transmit each order. It is not an enforcement point.
- **SEC Rule 15c3-5 and EU RTS 6** (confirmed, primary text for 15c3-5 via release snippets; RTS 6 via legislation text): pre-trade credit, size and price controls, a firm-owned immediate kill, and working orders counted against limits as soon as they are sent. Both are controls the firm must own.
- **FINRA 2026 oversight report** (confirmed, secondary for the report body): names AI agents acting without human validation, beyond their intended scope and authority, and with multi-step reasoning that is hard to audit. The PDF body was not read directly.
- **FSB** (confirmed): flags third-party concentration and market correlation from shared models and data. The word "herding" appears in the report text per a snippet, not on the press page.
- **Stripe Shared Payment Tokens** (confirmed, primary docs): scoped per transaction by seller, currency, maximum amount and expiry, and revocable. Trading needs the same scoping plus a time dimension.
- **Knight Capital 2012** (confirmed, SEC press release): a $460M loss from deployment and control failures. The capital-threshold control did not stop the flow, and automated warnings went unactioned.

Unconfirmed items (see the end of RESEARCH.md): Alpaca's current tool count; TT Pre-Trade Portfolio Risk's production coverage and whether its kill switch cancels exchange orders; RTS 6 Articles 13, 14 and 16; Stripe ACP's launch date; the two self-reported preprints; and several background citations.

### 2. How the founder's interpretations were resolved

- **The blockchain state engine became** a single-writer reservation ledger with a hash-chained log and signed checkpoints. Consensus is needed only across firms that do not trust each other, for example a shared cross-broker budget or a kill switch no one party can veto. The research found no financial-control source arguing for public-chain consensus inside one firm.
- **The "containerized" instinct was kept** as hierarchical risk escrow. Each firm, book and agent is a partition. A parent grants capacity to a child, which admits orders against its own allocation without a global lock. A child can never hold more than the parent granted, so cross-partition limits stay sound.
- **TT's working-order discipline is mandatory, not the differentiator.** The differentiator is binding each reservation to the agent, the contract and the evidence that produced the order.

### 3. The key technical insight

Volatility and Expected Shortfall are both subadditive, because they are coherent risk measures. A risk budget can therefore be reserved per order, the same way dollars are held in escrow, and the sum of reservations is a sound upper bound on total risk. Admission becomes a cheap conservative check. It does not need to search the 2^n combinations of possible fills across working orders. Euler allocation returns the diversification benefit at reconciliation.

### 4. Decisions

- Controls are split into two classes. **Hard controls** (caps, price bands, signatures, leases, reservations) are deterministic and in code. **Model-dependent controls** (risk estimates, judgement, herding signals) can only tighten.
- **Declared-scenario loss** is a hard check. It bounds loss only in the scenarios the owner declared, and the documentation must say so.
- The **long-horizon judgement model stays a research proposal.** It has no implementation.
- The **benchmark must include a competent conventional risk stack** (system C) and must run on live-forward paper data after the models' training cutoff. Backtested wins are not accepted as evidence.

### 5. What was built

- The design document, [AUTONOMY.md](AUTONOMY.md), and the research brief, [RESEARCH.md](RESEARCH.md).
- Code pathways in `python/orderguard_autonomy/`: contract, state, risk, admission, supervise, certificate and judgement.
- Only the tighten-only combine rule is implemented, in `admission.py`. A test checks that the strictest decision wins and that a hard refusal always stands.
- The other pathways raise `NotImplementedError`, and `python/tests/test_autonomy_pathways.py` checks that each one names its design section. Correction: `judgement.py` defines types and a protocol only, with no callable pathway, so the test does not cover it.
- A vision page at `site/vision.html` acts out the scenarios. It is labelled as illustrative, not as real results.

### 6. Open questions

- Which concrete reservation ledger design (single writer with fencing, or a standby) is acceptable for an owner's own capital?
- Does TT's pre-trade portfolio risk cover the exchanges OrderGuard would target, and what does TT actually cancel on a kill?
- What is the right unit for an authorization lease: time, notional, symbol set, or a combination?
- Which factor model and covariance estimator are used, and how are their error bands published with the ES figure?
- How is the herding signal defined so it keys on behaviour rather than declared identity, and how is its false-alarm rate controlled across thousands of agents?
- How are decision certificates kept small enough for the receiver to verify deterministically, and what do they say they cannot prove?
- Does the "Proof of Execution" preprint's approach hold up independently, or is it only a self-reported prototype?

## Entry 3: Built, benchmarked, and what it taught

**Date:** 2026-11-17

### 1. What was built

- Stages 1 and 2 of the build order now exist as working code in `python/orderguard_autonomy/`:
  - contract compiler and attenuation;
  - reservation ledger, projection and reconciliation;
  - hierarchical escrow of dollars and ES units;
  - risk models and backtests;
  - admission controller;
  - leases, intents, provenance, drift, herding, loops and pacing;
  - decision certificates with a receiver-side checker.
- The test suite covers each piece: unit, property and adversarial tests (concurrency, forged and altered certificates, stale leases, replayed retries).
- A four-system benchmark runs in `orderguard_autonomy/bench` on the existing impact market, with an independent auditor. See [BENCHMARK.md](BENCHMARK.md).
- A calibrated long-horizon judgement baseline and its research plan. See [JUDGEMENT.md](JUDGEMENT.md).
- AUTONOMY.md section 8 summarizes what was found.

### 2. First designs that failed, and why

- **Holds that reserved capacity.** A model hold took its reservation, so approving it later could fail on an exhausted escrow, and a hold quietly became a refusal. Fix: a hold reserves nothing, and approval re-admits the order through every check.
- **Plan-line pacing.** Pacing against a planned spend line let a fast agent ride the line and still starve the others. It was replaced by guaranteed shares that fade over the day and count net exposure. Even then, fairness has a visible cost: the fast agent is held.
- **Capacity stuck in children.** Escrow granted capacity down to agents but never took it back, so an idle agent's grant starved the busy ones. Fix: idle capacity returns to the root at each rebase.
- **A certificate that refused good sells.** The receiver required the reservation to cover the order, but risk-reducing orders reserve nothing. Certificates now say when an order was admitted as risk-reducing, and the receiver re-checks that it still reduces.
- **Herding keyed on symbols.** Agents buying different names in the same theme did not look alike. The herding signal is now sector-level flow plus a shared root source in the evidence.
- **Drift that flagged the book's size.** Style distance flagged small books whose weights were noisy. It now flags only books above a minimum size, and only orders that move the book further from the signed style.
- **A judgement model that graded itself.** The first evaluation used the same generator for training and testing, so it scored 0.97. An adversarial shifted set brought it to 0.63 with 5% recall, and that is the honest number.
- **Benchmark confounds found and fixed:**
  - limits that saturated in every system, so nothing could differ;
  - a herding measure that counted legitimate background buying;
  - a conventional baseline that applied fills twice and tripped its own kill switch;
  - drift control agents that copied the drifter's rotation rule.

### 3. What was learned

- **The win over a competent stack comes from binding, not from risk maths.** The large differences come from tying each order to a typed intent, a lineage lease and its evidence roots:
  - duplicates are stopped by intent quantity;
  - a compromised tool by intent mismatch;
  - rumours by root-source counting;
  - drift by comparing behaviour against the signed style.

  Projection and escrow mostly match what C+ already does with worst-case working-order position.
- **Pre-trade control cannot take risk off.** Once volatility rises, a book can be over its signed budget with no new order. De-risking is a separate, owner-approved action, and it is not designed yet.
- **Fairness is a policy choice.** Escrow without pacing is first come, first served, and it made starvation worse than no escrow.
- **Some wins rest on stated assumptions.** The intent records must come from the agent runtime and not from the agent's tools. That has to be enforced in deployment, not assumed.

### 4. Decisions

- The judgement model stays out of system D. The deterministic drift monitor does better.
- The next evidence is shadow mode on live-forward paper data, with the scenarios reviewed by someone outside the team.

### 5. Open questions

- What is the owner-facing control for de-risking a book that is over budget through no new order of its own?
- How should pacing shares be set: equal, by contract, or by the owner per agent?
- How is "intent written by the runtime, not the tool" enforced? Separate process, separate key, or attestation?
- Can herding caps be set from the owner's declared scenarios rather than as a share of capital?
