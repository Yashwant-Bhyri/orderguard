# Continuous autonomy control plane: research brief

Date of research: 2026-11-16. Scope: verify industry claims, then survey the state of the art for six components of a "risk-aware delegation contract enforced against the evolving portfolio and all outstanding agent actions".

How to read the evidence labels:
- **CONFIRMED (primary)**: read on the owner's own page or the regulator's page, via fetch or a search result quoting that page.
- **CONFIRMED (secondary)**: the substance matches several law-firm or trade summaries, but the primary text was not retrieved. Re-check the wording before quoting in public material.
- **PARTIAL / UNCONFIRMED**: see notes.
- **Background**: from general knowledge of the literature, not fetched in this session. Verify before citing.

Several primary sites (sec.gov, interactivebrokers.com, TT library body text, FINRA PDF) failed to load in this session, so some entries rest on search snippets of the primary page. That is stated per row.

---

## Part 1. Industry claims

| # | Claim | Verdict | Primary source | Exact capability |
|---|---|---|---|---|
| 1 | TT: worst-case position including working orders | CONFIRMED (primary snippet) | https://library.tradingtechnologies.com/setup/risk-management/risk-limits/reference-risk-limits/account-position-examples/ | Formula "Current Position + Working Orders on Buy/Sell side + Possible Fill from Current Order = Worst Case Position". Worked example: +5 position, +4 working buys, +7 new buy gives +16, checked against account max position. Risk aggregates across parent and child accounts. |
| 1b | TT: credit limits / worst-case margin | CONFIRMED, with a caveat | https://library.tradingtechnologies.com/user-setup/ptpr-overview.html and https://library.tradingtechnologies.com/setup/risk-management/risk-limits/description-risk-limits/credit-limits/ | Pre-Trade Portfolio Risk computes worst-case margin over working orders plus filled positions, using exchange risk-array files, and rejects when credit required exceeds the account's SPAN credit limit. The overview page said it was a UAT preview, with production "in the near future"; trade press dates the launch to mid-2025. Check which exchanges are live. |
| 1c | TT: kill switch | CONFIRMED (primary snippet) | https://library.tradingtechnologies.com/mifid-ii-support-on-the-tt-platform/platform-updates/trading-kill-switch-mifid-ii/ | A risk administrator can disable trading for all users, or per user via a "Trading Allowed" setting. The page snippet speaks of disabling trading and cancelling working orders; it did not retrieve a statement that the switch cancels orders at the exchange automatically. Do not claim that. |
| 2 | IBKR Risk Navigator: what-if and stress tests | CONFIRMED (primary snippets, IB user guide and Campus) | https://www.interactivebrokers.co.uk/en/software/tws.bak/usersguidebook/priceriskanalytics/open_the_ib_risk_navigator.htm and https://www.interactivebrokers.com/campus/trading-lessons/trading-what-if-2/ | You can open a what-if portfolio (copy of current or blank), add, close or change positions, see P&L profile and risk measures, run custom scenarios over price, time and volatility, use "Check Risk" pre-order (current P&L solid line vs what-if dashed), and generate the orders that would move the real account to the what-if. You must still review and transmit each order. IB marks projections as hypothetical. Note: it is a human analytics tool, not an enforcement point. The exact stress presets were not retrieved. |
| 3a | SEC Rule 15c3-5 | CONFIRMED (primary: Release 34-63241 and the SEC small-entity guide; fetched via search snippets) | https://www.sec.gov/files/rules/final/2010/34-63241-secg.htm and https://www.sec.gov/rules/final/2010/34-63241.pdf | Adopted 3 Nov 2010. Broker-dealers with market access must keep risk management controls and supervisory procedures reasonably designed to manage financial and regulatory risk: block orders exceeding pre-set credit or capital thresholds, orders exceeding price or size parameters (order by order or over a short period), and duplicative orders; plus regulatory controls. Controls must be under the direct and exclusive control of the broker-dealer. Annual review; annual CEO certification. Effectively ended "naked" access. Warning: some glossary sites list kill switches and LULD as explicit requirements; the primary text does not. |
| 3b | EU MiFID II RTS 6 (Delegated Reg. 2017/589) | CONFIRMED (text on legislation.gov.uk copy; EU original is OJ L 87, 31 Mar 2017) | https://eur-lex.europa.eu/eli/reg/2017/589/oj and https://www.legislation.gov.uk/eur/2017/589 | Art. 12 "kill functionality": a firm must be able to "cancel immediately, as an emergency measure" any or all unexecuted orders on any or all venues. Art. 15 pre-trade controls (price collars, max order value and volume, max message limits, per trader permissions) applied to exposure per client, instrument, trader, desk or firm. Orders sent to a venue must be counted immediately in the limit calculations. Blocked orders may only be released by a documented, temporary, exceptional procedure. From background (not retrieved here): Art. 13 adds automated surveillance, Art. 16 real-time monitoring, and the regulation requires pre-deployment testing and annual self-assessment. Verify those before citing. |
| 4 | FINRA 2026 Annual Regulatory Oversight Report (9 Dec 2025) on AI agents | CONFIRMED (secondary for the report body; primary for FINRA's follow-up blog) | https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai ; https://www.finra.org/media-center/blog/observations-on-ai-agents ; PDF https://www.finra.org/sites/default/files/2025-12/2026-annual-regulatory-oversight-report.pdf | New "GenAI: Continuing and Emerging Trends" section covers AI agents, defined as systems that autonomously perform and complete tasks for a user. Listed risks: acting "without human validation and approval"; acting beyond the user's "actual or intended scope and authority"; multi-step reasoning that is hard to trace, which hurts auditability; plus (blog, 27 Jan 2026) data sensitivity, lack of domain knowledge, and poorly designed reward functions. FINRA says its rules are technology neutral, so firms stay responsible. The FINRA page body would not load; the quoted risk list came from the blog fetch and from a search result quoting the report. |
| 5a | FSB: AI and financial stability | CONFIRMED (primary press page fetched; report PDF snippet) | https://www.fsb.org/2024/11/fsb-assesses-the-financial-stability-implications-of-artificial-intelligence/ ; report https://www.fsb.org/uploads/P14112024.pdf | Nov 2024 report names four vulnerabilities: "third-party dependencies and service provider concentration", "market correlations", cyber, and model risk/data quality/governance. The press page does not use the word "herding". The report text (per search snippet) says common models and data could raise correlations in trading, lending and pricing, and that participants imitate others' data and model choices. |
| 5b | FSB follow-ups | CONFIRMED (search result of FSB pages) | https://www.fsb.org/2025/10/monitoring-adoption-of-artificial-intelligence-and-related-vulnerabilities-in-the-financial-sector/ ; https://www.fsb.org/uploads/P100626.pdf | Oct 2025: monitoring report with indicators, finds monitoring is early-stage and data-poor. A later FSB "Sound Practices for Responsible Adoption of AI" paper (file dated P100626) says reliance on common models, data or infrastructure can cause correlated behaviour that amplifies herding and procyclicality. I saw only a snippet; its exact date is not confirmed. |
| 6 | Alpaca MCP Server V2: tool count, paper default | PARTIAL. Paper default CONFIRMED. Tool count has two figures | https://alpaca.markets/blog/alpaca-launches-mcp-server-v2/ ; https://github.com/alpacahq/alpaca-mcp-server | Launch post (dated 9 Apr 2026) says V2 "expands tool coverage from 43 to 61 endpoints". The GitHub README does not state a total; counting its "Available Tools" list gave 72, which is my tally and may reflect later additions. Say "61 at launch". README: `ALPACA_PAPER_TRADE` defaults to `true`; `ALPACA_TOOLSETS` defaults to all tools; V2 is a rewrite on FastMCP and OpenAPI, V1 tools do not carry over. The launch blog itself does not state the paper default. Notable for OrderGuard: all tools on by default, no per-order limits. |
| 7 | Stripe Shared Payment Tokens / ACP | CONFIRMED (primary docs fetched) | https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens ; https://stripe.com/newsroom/news/stripe-openai-instant-checkout | An agent issues an SPT to a named seller profile (`seller_details[network_business_profile]`) with `usage_limits` for currency, `max_amount` and `expires_at`; the token can be revoked at any time (a `/revoke` endpoint); it is a state machine (`active`, `requires_action`, `deactivated`); webhooks fire on `used`, `deactivated`; 3-D Secure can force customer action. Per-transaction issuance, not a standing multi-day budget. API version in the doc is a 2026 preview, so it may change. ACP was announced with OpenAI in Sept 2025 (from the Stripe newsroom URL and secondary reports; one blog claimed an April 2026 "production-ready" date, which I could not confirm). |
| 8 | Knight Capital 2012 SEC order | CONFIRMED (primary press release fetched; order No. 70694) | https://www.sec.gov/news/press-release/2013-222 ; order In the Matter of Knight Capital Americas LLC, Exchange Act Rel. No. 70694, 16 Oct 2013 (PDF at sec.gov/files/litigation/admin/2013/34-70694.pdf did not load) | Loss over $460 million on 1 Aug 2012; $12 million penalty, first enforcement of 15c3-5; Knight neither admitted nor denied. Findings: no controls reasonably designed to stop erroneous orders; controls could not block orders exceeding firm capital limits; weak controls on code deployment and testing (old code reactivated on one of eight servers); no adequate written incident procedures; 97 automated warning emails before the open that nobody acted on; defective 2012 CEO certification. Secondary summaries: more than 4 million orders in 45 minutes against 212 customer orders, over 397 million shares. |

What this means for the positioning:
- The worst-case-including-working-orders check is already standard at futures venues and platforms (TT). It is not new. What is new is applying it across many autonomous principals, across asset classes and against a human-signed risk specification rather than a static limit table.
- Regulators already require a firm-owned, immediate kill and pre-trade controls with working orders counted immediately (RTS 6, 15c3-5). A "continuous autonomy control plane" maps cleanly onto those obligations and onto FINRA's named agent risks (scope and authority, auditability, human validation).
- Stripe's SPT is the closest precedent for scoped, expiring, revocable agent authority, but it is per-transaction and single-seller. A portfolio-level, multi-order delegation is the gap.
- Do not claim "Alpaca MCP has no limits" without checking a current build. The README does list toolset filtering.

---

## Part 2. State of the art by component

### A. From human intent to enforceable policy

| Source | Key idea |
|---|---|
| Birgisson et al., "Macaroons: Cookies with Contextual Caveats for Decentralized Authorization in the Cloud", NDSS 2014, https://www.ndss-symposium.org/ndss2014/macaroons-cookies-contextual-caveats-decentralized-authorization-cloud | Bearer credentials where anyone holding one can add caveats (chained HMAC) that only narrow it. Attenuation without contacting the issuer. The authors note timeliness needs fresh credentials or revocation checks. |
| Biscuit (Eclipse/Clever Cloud), https://docs.rs/crate/biscuit-auth/0.8.0 ; IETF individual draft "Attenuating Agent Tokens", https://www.ietf.org/archive/id/draft-niyikiza-oauth-attenuating-agent-tokens-01.html | Macaroon-style attenuation with public-key signatures and a Datalog policy language, verified offline. The IETF draft proposes constraint types checkable without a logic engine, aimed at agent chains. It is an individual draft, not a standard. |
| UCAN specification (delegation, invocation, revocation), https://ucan-website.pages.dev/delegation and https://ucan-website.pages.dev/revocation | Capability chains where each link can only narrow the one before. Revocation names a delegation by content ID; only an issuer in the chain may revoke; the store is append-only. Critics say verifiers need reachable revocation lists. Spec is at release-candidate stage. |
| Stripe SPT docs (above) | Commercial example of a scoped, expiring, revocable agent credential. |

Preference elicitation and policy compilers have no single canonical source I could confirm. Background starting points to verify: Cedar (Amazon's analyzable authorization language, with formal verification of policy analysis), Open Policy Agent/Rego, and the multi-attribute utility and "preference elicitation" literature (Boutilier and others) for turning answers like "I can lose 2% this month" into constraints. Treat these as leads, not citations.

What is naive: a flat JSON of caps (symbols, per-order, daily). It cannot express portfolio-level intent (maximum drawdown, risk budget, exposure by sector), cannot be narrowed safely by a sub-agent, and the human's words are mapped to numbers by hand with no check that the numbers mean what the person meant.

What maturity needs:
1. A small, analyzable policy language with a compiler that proves two things: the compiled policy is no looser than the stated intent, and a child grant is never looser than its parent (attenuation as a theorem, tested by property tests).
2. Elicitation by showing consequences: replay history or simulated paths through the candidate policy ("this would have refused 14 orders and held 3 last quarter") before signing. OrderGuard's envelope lab is already the seed of this.
3. Short authorization leases (minutes to a day) that renew only if the supervisor's checks stay green, instead of relying on revocation alone. Revocation across chains is the weak point of offline-verifiable tokens, so the enforcement point should check a revocation epoch or a lease on every order and fail closed when it cannot.
4. Separation of the signed contract (rarely changes, human key) from the live limits that tighten automatically (never loosen without a signature).

### B. Portfolio-wide state under concurrency

| Source | Key idea |
|---|---|
| O'Neil, "The Escrow Transactional Method", ACM TODS 11(4), 1986, https://www.cs.umb.edu/~poneil/EscrowTM.pdf | For a hot aggregate with a bound (balance at least 0), record each pending change as an escrow: grant it only if it is safe against the worst combination of pending outcomes. Non-blocking, no deadlock. This is exactly a budget or exposure reservation. |
| Garcia-Molina and Salem, "Sagas", SIGMOD 1987 (via secondary summaries); Helland, "Life beyond Distributed Transactions: an Apostate's View", CIDR 2007 | Long work as a chain of local steps with compensations; at-least-once messaging means every handler must be idempotent; tentative operations are confirmed or cancelled later. |
| TT account position examples (above) and RTS 6 Art. 15 | Industry practice: worst-case exposure counts working orders at once. |
| Kleppmann, "Designing Data-Intensive Applications" (2017) and Fowler on event sourcing (Background) | Append-only event log as source of truth, state derived by replay. Verify exact citations. |

Key points, plainly:
- A reservation ledger is the escrow method with names changed. Reserve worst-case exposure when the order is admitted (unfilled quantity at the worst plausible price), and release or convert it on fill, cancel or reject. This is what TT's worst-case position does.
- Two-phase commit across independent firms is a poor fit: a broker is not a participant in your transaction and will not hold a lock for you. The honest model is a saga: reserve locally, send with a client order ID, treat the broker's response as one input, reconcile.
- Exactly-once across independent parties is impossible in the general case (the Two Generals problem: neither side can know the last message arrived). Practical systems use at-least-once delivery plus idempotency keys plus reconciliation. I did not retrieve a source for the formal result in this session; treat it as standard distributed-systems background.
- The hard failure is the unknown: an order sent, the network drops, no ack. The reservation must stay held at worst-case until reconciliation proves otherwise. A mature design has an explicit "unknown" state, a timeout policy that does not release reservations early, and a reconciler that compares your ledger to the broker's order and fill reports and to end-of-day positions. Breaks are logged, not hidden.
- Knight (above) is the cautionary tale: the capital-threshold control did not stop the flow, and the early warnings were not acted on.

**Does a blockchain help?** Honest assessment: not for the single-controller case.
- Wüst and Gervais, "Do you need a blockchain?", https://eprint.iacr.org/2017/375 : their own flowchart sends you to an ordinary database if there is a single writer, or if a trusted party is always online. Critics (Gerard, Rosenthal) add that append-only logs like Git or Merkle logs already give tamper evidence without consensus.
- A single-writer serializable ledger gives you everything the control plane needs: linearizable reservations, atomic budget updates, and replay. Add a hash-chained (or Merkle) audit log with periodic signed checkpoints published somewhere you do not control (a customer's own store, a timestamping service, an auditor). That gives tamper evidence, inclusion proofs and consistency proofs. Certificate Transparency (RFC 9162) is the working model of this (Background, not fetched).
- Consensus adds latency and complexity and does not solve the real problems here: the oracle problem (price source), the broker's own state, and key custody. A blockchain cannot tell you what the broker actually did.
- "Containerized blockchain state engine" adds nothing that "containerized single-writer state engine with an append-only log" does not, except as marketing. I found no financial-control source that argues otherwise.

When multi-party consensus is genuinely needed: when several firms that do not trust each other must share one authoritative state and none may be the owner. Examples: a shared exposure or margin budget across several brokers or clearing members; a market-wide kill that no single party can veto or fake; a cross-firm record of one agent's delegations. Even then a permissioned replicated log with a few known operators (Raft or a BFT protocol) is enough; a public chain is not. This is a product for a consortium, not for one desk.

What maturity needs: single-writer serializable reservations with idempotency keys; an explicit unknown state; broker reconciliation (order, fill, position); per-venue reservation expiry that never frees on timeout alone; event-sourced state with deterministic replay; signed log checkpoints; a documented failover story (a standby that fences the primary so two writers never run).

### C. Counterfactual and incremental portfolio risk

| Source | Key idea |
|---|---|
| Ledoit and Wolf, "Honey, I Shrunk the Sample Covariance Matrix", J. Portfolio Management 30(4), 2004, https://bse.eu/research/working-papers/honey-i-shrunk-sample-covariance-matrix ; Ledoit and Wolf, nonlinear shrinkage ("Markowitz meets Goldilocks"), https://econpapers.repec.org/RePEc:zur:econwp:137 | When assets are many relative to observations the sample covariance is noisy and biased. Shrink it toward a structured target (linear), or shrink each eigenvalue separately (nonlinear). Reduces realized tracking error. |
| Tasche, "Capital allocation to business units and sub-portfolios: the Euler principle", https://ar5iv.arxiv.org/html/0708.2542 ; Tasche, "Expected shortfall and beyond", https://arxiv.org/pdf/cond-mat/0203558 | Euler allocation: for a risk measure homogeneous of degree one, each position's contribution is its weight times the partial derivative, and contributions sum to total. For ES the contribution is the conditional expectation of the position's loss given the portfolio is in its tail. |
| Fissler, Ziegel and Gneiting, "Expected shortfall is jointly elicitable with value at risk", Risk 2016; Acerbi and Szekely, "Back-testing expected shortfall", Risk 2014, https://www.risk.net/risk-management/2381658/back-testing-expected-shortfall | ES alone is not elicitable (Gneiting 2011), but ES and VaR jointly are, so they can be scored and compared. Acerbi and Szekely argue elicitability matters for model comparison, not for testing, and give direct ES backtests. Backtest power is low at tail confidence levels because exceptions are rare. |
| Bangia, Diebold, Schuermann and Stroughair, "Modeling Liquidity Risk" (1998/99), https://archive.nyu.edu/bitstream/2451/27135/2/wpa99062.pdf ; Basel FRTB (97.5% ES with liquidity horizons of 10 to 120 days, via secondary summaries) | Add a liquidity cost to VaR (spread, and the time it takes to exit); regulators moved to ES with asset-specific liquidation horizons. |
| Packham and Woebbeking, "A factor-model approach for correlation scenarios and correlation stress-testing", J. Banking and Finance 2019, https://arxiv.org/abs/1807.11381 ; recent work on regime-local covariance for reverse stress tests, https://arxiv.org/pdf/2606.09274 | Stress correlations through a factor structure; a single full-history covariance blends regimes and is a poor stress input. |

Background leads not verified here: Garman (1996) for incremental and marginal VaR; Fan, Fan and Lv (2008) on factor-model covariance estimation in high dimensions; Barra-style fundamental factor models (commercial vendors: MSCI, Axioma, Bloomberg).

What is naive: sample covariance of recent returns; a single number "portfolio VaR" computed before and after the order; Gaussian assumptions; ignoring that outstanding orders and unfilled working orders are part of the portfolio; ignoring that exit costs rise in stress.

What maturity needs:
1. A factor model (market, sector, style, rates) plus shrunk idiosyncratic covariance, so that the dimension is manageable and a new position is explained by factors.
2. The counterfactual is portfolio-after-all-outstanding-orders: current positions plus worst-case fills of every working order, then this order. The check is the marginal and incremental risk it adds, with Euler contributions to show which positions dominate (so the refusal can be explained in plain words).
3. Report ES jointly with VaR, accept that tail estimates carry wide error bands and publish them; do not claim a single point value is "verified". Cap using conservative bounds (upper confidence limit), not the point estimate.
4. Liquidity-adjusted: size the exit by participation rate and spread, not just by price volatility.
5. Several scenario families, not one: historical (2008, 2020 March, 2022 rates), hypothetical, and reverse stress ("what moves lose 5% of NAV"), with correlations pushed toward one in stress. Regime detection (volatility and correlation level) selects which covariance estimate is trusted.
6. Speed: the admission path needs an incremental update (rank-one or low-rank change to exposures) so a decision takes microseconds to milliseconds; full revaluation runs off-path and refreshes the factor loadings.

### D. Continuous supervision of agents

| Source | Key idea |
|---|---|
| Page, "Continuous inspection schemes", Biometrika 41, 1954 (CUSUM), https://en.wikipedia.org/wiki/CUSUM for a summary; Wald's sequential probability ratio test (1945, Background, not retrieved) | CUSUM accumulates evidence of a shift and is minimax-optimal for detection delay at a given false-alarm rate (Lorden 1971, Moustakides 1986, per the summary). SPRT decides between two hypotheses with the fewest expected samples. |
| Gibbs and Candes, "Adaptive Conformal Inference Under Distribution Shift", NeurIPS 2021, https://proceedings.neurips.cc/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html | Wrap any predictor in prediction sets whose miscoverage level is adjusted online so coverage holds under drift. Useful for "is the agent's realized loss or slippage outside what it promised". |
| FSB Oct 2025 and Nov 2024 reports (above) | Correlated behaviour across firms using common models is a stated systemic concern; monitoring indicators are immature. |
| "Proof of Execution: Runtime Verification for Governed AI Agent Actions", arXiv 2607.05397, https://arxiv.org/abs/2607.05397 | A 2026 preprint bundling contract, causal event log and replay context so an execution can be validated. Single-prototype claims, self-reported, not independently validated. |
| Control-theory budget pacing (Background): PID or model-predictive pacing from online advertising, for example Xu et al. on budget pacing (verify) | Spend a daily budget smoothly with a feedback controller instead of hard cutoffs. |

What is naive: static thresholds on order rate; a daily cap that is exhausted in the first hour by whichever agent is fastest; per-agent checks that cannot see a group.

What maturity needs:
- Per-agent and per-group sequential tests on a handful of statistics (order rate, cancel-to-fill ratio, realized slippage versus quote, loss versus the agent's own claimed edge). CUSUM for slow drift, SPRT for a yes/no decision such as "this loop is repeating". Set false-alarm rate explicitly, because with thousands of agents a 1% rate is dozens of alerts a day (use false-discovery control).
- Conformal bands on each agent's realized outcomes, re-calibrated online, so "out of band" has a stated error rate even when the market regime changes.
- Loop detection: repeated near-identical orders, same symbol flipping side, state that does not change between calls. Easy and high value; start with a hash of order shape over a window.
- Herding detection: cross-agent correlation of order flow, cluster agents by rolling flow similarity, and cap the aggregate net exposure of any cluster. Common models make this likely, per the FSB. Group limits must key on behaviour, not on the agent's declared identity.
- Pacing: a controller that sets a per-agent rate budget from the remaining daily risk budget, tightening smoothly as consumption outpaces the plan, never loosening beyond the signed mandate.
- Escalation ladder: slow, hold for a human, reduce authority (lease not renewed), kill. Each step logged with the statistic that triggered it.

### E. Proof-carrying orders

| Source | Key idea |
|---|---|
| Necula, "Proof-Carrying Code", POPL 1997 (via bibliographic pages, e.g. https://bibtex.github.io/POPL-1997-Necula.html) | The producer ships a machine-checkable proof that the code meets a policy; the consumer only checks the proof, which is simple and fast. The trusted base is the checker and the policy definition. |
| in-toto and SLSA provenance attestations; W3C Verifiable Credentials 2.0 (Background, not fetched this session) | Signed statements about an artifact or an actor, verifiable by third parties. Attestation says who claims what; it does not make the claim true. |
| "Proof of Execution" preprint (above) | An applied version for agents. Self-reported results. |

What a certificate can prove: that the order fits the signed spec and the ledger state as of a named log position (checkable arithmetic: caps, reservations, price band, signature chain, lease unexpired); that the check ran before the order was released (if the release path is attested by the enforcement point's key); that the record has not been altered since (hash chain and checkpoint).

What it cannot prove: that the price input was true (oracle problem); that the covariance model is right or the risk number is well estimated (model risk); that the agent's intent was sound; that the broker executed the order as sent; that state outside the ledger (another account, another firm) was accounted for; that the enforcement point itself is not compromised. A signature proves origin, not correctness. Per Necula, the trusted checker is the weak point ("who verifies the verifier"), which suggests keeping the checker tiny and separately testable.

Maturity needs: a short, deterministic checker (the "receiver" in OrderGuard) whose inputs are all named in the certificate (spec hash, lease ID, ledger sequence number, price source and timestamp, model version and parameters); certificates the broker or an auditor can re-verify offline; and honest language: "proof of compliance with the signed rules given these inputs", never "proof the order is safe". Pair it with the independent auditor rebuild the repo already has.

### F. Long-horizon judgement and financial-agent evidence

| Source | Key idea |
|---|---|
| Arike, Donoway, Bartsch and Hobbhahn, "Technical Report: Evaluating Goal Drift in Language Model Agents", arXiv 2505.02709, https://arxiv.org/abs/2505.02709 | In their setting, all evaluated models show some goal drift; best case (a scaffolded Claude 3.5 Sonnet) held near-perfect adherence for over 100,000 tokens in the hardest evaluation; drift correlates with growing pattern-matching as context lengthens. |
| Backlund and Petersson, "Vending-Bench: A Benchmark for Long-Term Coherence of Autonomous Agents", arXiv 2502.15840, https://arxiv.org/abs/2502.15840 | Simple business tasks run over very long horizons (above 20M tokens); every model had runs that derailed (forgot orders, misread deliveries, "meltdown" loops); failures did not clearly track context fullness. |
| Xiao, Sun, Luo and Wang (UCLA), "TradingAgents: Multi-Agents LLM Financial Trading Framework", arXiv 2412.20138, https://arxiv.org/abs/2412.20138 | Role-based LLM firm (analysts, bull/bear debate, risk team, traders). Reports better cumulative return, Sharpe and drawdown versus baselines in backtests only; live deployment listed as future work. |
| InvestorBench, arXiv 2412.18174, https://arxiv.org/html/2412.18174v1 ; StockBench, arXiv 2510.02209, https://arxiv.org/pdf/2510.02209 ; FinBen (36 datasets, 24 tasks, includes stock trading, via secondary summary); StockAgent (simulated multi-agent market, arXiv title confirmed only via a search result) | Benchmarks for financial agents. StockBench criticizes InvestorBench for single-stock settings and data only to 2021, and addresses test-set leakage. Model choice strongly affects results (InvestorBench). |
| TwinMarket, arXiv 2502.01506, https://arxiv.org/pdf/2502.01506v1 ; Henning et al., LLM experimental asset markets, https://arxiv.org/pdf/2502.15800 | Mixed evidence on herding. TwinMarket (agents prompted with behavioural biases, social data) reports emergent bubbles from group behaviour. Henning et al. find 20 identical LLM traders price near fundamental value with only muted bubbles, and warn LLM-only data may not reproduce human market phenomena. One conference poster on panic-selling cascades was not verifiable. |

What is known: long-horizon coherence is the weak axis of LLM agents, not single-step skill; drift is real and measurable; backtested trading wins are weak evidence (leakage, short windows, fees ignored, single-asset); multi-agent simulations show herding only under some prompts and designs.

What is naive: trusting a model's own report of being on-goal; judging an agent by backtest Sharpe; assuming that diverse prompts give diverse behaviour (same weights, same data, so correlated, which the FSB also flags).

What maturity needs (for OrderGuard as a control plane, not a trading product): re-inject the signed goal at fixed intervals rather than rely on the context; checkpoint and compare agent intent against the contract by a separate, simple check; score agents on realized behaviour (cancel ratios, slippage, adherence to stated rationale) instead of claimed intent; run the herding and drift tests from Section D on live agents; evaluate on live-forward paper data after the model's training cutoff; and treat any benchmark number as indicative.

---

## What to build first (suggested order)

1. Reservation ledger with worst-case working-order accounting and an explicit unknown state, plus broker reconciliation. Standard in industry; low novelty; mandatory.
2. Policy compiler with attenuation checks and leases; show-consequences elicitation using the envelope lab.
3. Factor-model incremental risk with Euler explanations and conservative ES bounds; document its limits openly.
4. Supervisor: sequential tests, conformal bands, loop and cluster detection, pacing controller, escalation ladder.
5. Signed, re-verifiable decision certificates with plain limits-of-proof language; signed log checkpoints. Skip consensus until a multi-firm customer needs it.

## UNCONFIRMED or weak items

- Alpaca V2 exact tool count today: 61 at launch (blog); the README lists more (my tally 72). Paper default `true` is confirmed from the README, not from the launch blog.
- TT Pre-Trade Portfolio Risk production availability and per-exchange coverage (doc said UAT preview; press says mid-2025). TT kill switch cancelling live exchange orders automatically: not shown in what I retrieved.
- FINRA report exact wording: confirmed through blog fetch and search results quoting the report, not by reading the PDF body.
- FSB: the word "herding" appears in the report per a search snippet and in the later sound-practices paper; not on the press page. Later paper's date not confirmed.
- RTS 6 Arts. 13, 14 and 16 details and "annual self-assessment": background knowledge, not retrieved.
- IBKR's built-in stress-scenario presets: not retrieved.
- Stripe ACP launch date nuance (Sept 2025 versus an April 2026 claim): unresolved. SPT scope fields are confirmed from Stripe's docs.
- Wald (1945), Garman (1996), Fan-Fan-Lv (2008), RFC 9162, in-toto, SLSA, W3C VC 2.0, Cedar, Boutilier, budget-pacing papers: cited from background, not fetched.
- The "Proof of Execution" preprint (2607.05397) and the reverse-stress preprint (2606.09274): found via search or abstract only; self-reported, not independently validated.
- Panic-selling cascade poster (International Online Conference on Risk and Financial Management): could not verify.
