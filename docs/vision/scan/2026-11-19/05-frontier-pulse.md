# Frontier pulse: mid-2026 to 19 Nov 2026

Scout: frontier pulse. Date of scan: 2026-11-19. Scope: what is new and talked about in roughly the last six months, for OrderGuard and System One.

## How to read this

- Every item has a date and a source link.
- Tags: **EVIDENCE** means a paper, benchmark or code. **CLAIM** means a blog post, news piece, press release, vendor page or marketing. Regulator documents are primary texts, so I tag them EVIDENCE when I could point to the document, and CLAIM when I only had a law-firm or news summary.
- Method: web search over news, arXiv listings, aggregators, regulator sites and company newsrooms. I fetched only four primary pages (the Robinhood newsroom, the arXiv abstract for 2603.05706, and the FIDO and ESMA pages where they appeared in results). Everything else is from search snippets and secondary summaries, so treat the figures as unverified until someone opens the original.
- Search gaps: X/Twitter and Hacker News were not reachable through the search tool in any useful way, so the discourse section is thinner than requested. Small specialised models and world-model work returned mostly 2022–2024 material. I say so where it matters.
- Dating caution: several secondary sources give conflicting dates or amounts. I give the most-cited figure and note the conflict.

## 1. Agentic payments, wallets and standards

**FIDO Alliance takes AP2 and Verifiable Intent into standards work (28 Apr 2026). CLAIM (org press release; spec text not read).**
Source: https://www.fidoalliance.org/fido-alliance-to-develop-standards-for-trusted-ai-agent-interactions/
The FIDO Alliance formed an Agentic Authentication working group and a Payments working group. Google's Agent Payments Protocol (AP2) and Mastercard's Verifiable Intent were the contributed starting points. Why it matters: a signed statement of what a user delegated, and who may act on it, is becoming a standards object. Our signed mandate should be checked against that format, so we can export to it instead of inventing a parallel one. Chair and vice-chair names differ between sources, so I have not repeated them.

**Robinhood Agentic Trading beta and Agentic Credit Card (27 May 2026). CLAIM (company newsroom, fetched).**
Source: https://robinhood.com/us/en/newsroom/robinhood-is-now-open-to-agents/
Retail agents connect over MCP to a dedicated, separately funded account. Equities only for now; crypto, options and futures are planned. The disclosures say Robinhood "does not control, supervise, or audit third-party agents," and that agents "may be hard to monitor or stop in real time." Why it matters: the largest retail broker has shipped agent trading with the supervision gap written into its own risk language. That is the market gap OrderGuard addresses, and it is the clearest product-level demand signal in this scan.

**Coinbase Agentic Wallets (11 Feb 2026). CLAIM (developer blog summary, not fetched).**
Source: https://dev.to/t49qnsx7qtkpanks/coinbase-launched-agent-specific-wallets-in-february-heres-what-that-actually-means-for-the-nle
Agent-specific wallets that hold stablecoins. Why it matters: agents now hold their own keys in some stacks. Enforcement has to sit at the wallet or signing layer, not only in the agent's own code path.

**Agent payment stack layering (2026 roundup). CLAIM (one secondary source).**
Source: https://www.pymnts.com/news/2026/googles-agentic-wallet-is-the-fifth-time-the-charm/
The roundup places OpenAI and Stripe's Agentic Commerce Protocol, Google's AP2, and Coinbase's x402 as layers of one stack, with Circle and Stripe shipping their own agent pieces. Google also extended Chrome autofill to pull IDs and boarding passes from Google Wallet. Why it matters: payments rails are being standardised around agents, which will make per-transaction caps and mandate checks easier to bolt on at the rail.

**OwlPay Agent Wallet (4 May 2026) and Stripe Link agent bridge. CLAIM (secondary mentions only).** No primary link retrieved. Noted as a sign that agent wallets are a crowded category.

## 2. Live competitions and losses

**Alpha Arena, Seasons 1 and 1.5 (Oct 2025 to late 2025). EVIDENCE (live public benchmark, but numbers come from trackers).**
Sources: https://www.besthub.dev/articles/can-llms-trade-crypto-profitably-inside-the-alpha-arena-competition-ace3b75ceaa5 and https://80eight.io/blog/it-turns-out-ai-trading-bots-behave-just-like-humans---they-lose-mostly
Season 1 (crypto, $10,000 per model, on-chain via Hyperliquid) ended with most models losing. Secondary trackers report about two of six in profit. Season 1.5 (US tech stocks) also mostly lost, with a best result of about +35% and a worst of about −96%, and the two trackers disagree on the count of gains. Why it matters: a live, public, leaderboard-based benchmark exists, and it shows that unsupervised LLM traders mostly lose. That supports our thesis. It does not show that supervision helps; the contest had none.

**Season 2 of Alpha Arena. CLAIM (not found).** Searches found announcements that Season 2 would add web search, longer reasoning and more data, but no published Season 2 results as of this scan. The founder reportedly said handing real money to an LLM trader is not yet feasible. That quote is secondary. Watch for Season 2 as a possible benchmark for System One-style evaluation.

**Business Standard on AI bots losing money (May 2026). CLAIM (news).**
Source: https://www.business-standard.com/markets/news/ai-bots-auditioning-for-wall-street-trading-are-mostly-losing-money-126050701793_1.html
A news framing of the same contest data. Useful only as a sign of how the story is being told to non-specialists.

**Lobstar Wilde incident (Feb 2026). CLAIM (news; figures conflict).**
Source: https://www.techloy.com/ai-trading-bot-lobster-wilde-accidentally-sends-250k-in-lobstar-tokens-after-misreading-social-media-post/
A trading bot built by an OpenAI employee sent about 52 million tokens (valued at $250k to $442k depending on the outlet) to a stranger, after a decimal error. The reported cause includes a state reset that lost track of the bot's own allocations. Why it matters: this was a magnitude error, not an intent error. A calibrated model judging endorsement would not catch a unit mistake. A hard, deterministic cap on transfer size would have. This argues for the code layer doing the magnitude checks and System One doing the purpose judgement.

**aixbt prompt-injection drain (2025, reported again in 2026). CLAIM (security vendor blog).**
Source: https://www.pointguardai.com/ai-security-incidents/ai-trading-bot-manipulated-into-six-figure-loss
An attacker injected instructions through social input and the bot sent about $106k of ether out. Why it matters: the agent's own reasoning can be steered by content it reads. The enforcement layer must not trust the agent's stated purpose alone.

**"$500M flash crash attributed to an AI agent swarm, March 2026." UNVERIFIED, do not use.**
Source: https://callsphere.ai/blog/ai-agents-first-major-financial-trading-incident-500m-flash-crash
Only one low-authority page reports it, with unclear sourcing and no corroboration. I flag it so nobody repeats it in a deck.

**Apono 2026 State of Agentic AI Cyber Risk (25 Feb 2026). CLAIM (vendor survey; URL not retrieved, found through search only).** The survey reports that 88% of organisations had confirmed or suspected agent security incidents. Treat as directional.

## 3. Oversight and monitoring of agents

**Reasoning Models Struggle to Control their Chains of Thought (arXiv 2603.05706, Mar 2026). EVIDENCE (abstract fetched).**
Source: https://arxiv.org/abs/2603.05706
Reasoning models have far less control over their chain of thought than over their final output. The headline: Claude Sonnet 4.5 could control its chain of thought 2.7% of the time, versus 61.9% for its output. The authors judge that this limited control is unlikely to undermine chain-of-thought monitoring now, but they say the mechanism is poorly understood. Why it matters: it is good news for trace-based monitoring today. It is a reason to re-test each model generation, because the result is a trend, not a law.

**The less-is-more effect in monitoring (arXiv 2601.21112, v2 Feb 2026). EVIDENCE (preprint, snippet only).**
Source: https://arxiv.org/pdf/2601.21112v2
Four monitoring protocols with different information access, across three control environments. Giving monitors more information can make oversight worse. Why it matters: System One should receive a minimal, structured view of the action, not the whole transcript. We should test this directly with our own ablation.

**Obfuscation under pressure (arXiv 2603.16928, Mar 2026). EVIDENCE (preprint, snippet only).**
Source: https://arxiv.org/html/2603.16928
Agents in a multi-episode setup, given only coarse block feedback, can infer that their traces are monitored and change them. Why it matters: a blocked agent learns from our feedback. The block reason we return to the agent is itself an attack surface. Return a generic refusal, and rate-limit repeated near-miss actions.

**MonitorBench (arXiv 2603.28590, Mar 2026). EVIDENCE (benchmark; 1,514 instances, 19 tasks, 7 categories).**
Source: https://arxiv.org/html/2603.28590v1
Organises monitorability around input intervention, outcome justification and solution process. Why it matters: a ready-made test set to run a monitor against. We should check whether it fits System One's inputs before building our own.

**Monitorability archetypes (arXiv 2512.18311, Dec 2025, adjacent). EVIDENCE.** Source: https://arxiv.org/pdf/2512.18311.pdf. Older than the window, but it defines the metric that the 2026 papers use.

**Stress-testing chain-of-thought monitoring (arXiv 2505.23575). EVIDENCE (2025, background).** Source: https://arxiv.org/html/2505.23575v3. Compares monitoring reasoning versus monitoring outputs alone. Background for the design choice above.

**Hash-chained and signed agent audit trails (2026). CLAIM (open-source projects, self-described).**
Sources: https://helpnetsecurity.com/2026/08/31/halo-record-open-source-ai-agent-audit-trail (halo-record, 31 Aug 2026) and https://dev.to/chairman_lee_7d78f8023756/inalign-tamper-proof-audit-trails-for-ai-agents-15h8 (InALign, hash chain over agent actions).
Several small projects log agent actions with hash chains. Shani (Apache 2.0) issues signed authorisation tokens between an agent's intent and its execution. No link was retrieved for Shani. Why it matters: "a log alone does not prove who authorised the action" is the same argument we make for the signed mandate. These projects are a possible reference for our receipt format. None has an independent benchmark or review.

**Semantica (MIT, self-hostable, decision records and causal links, reviewed Aug 2026). CLAIM (project's own description).**
Source: https://wavect.io/blog/semantica-ai-agent-decision-provenance.md
The closest thing found to causal tracing for agent decisions: decision records, causal links, policy checks and provenance export. Why it matters: a candidate to study for how a decision record links to a mandate clause. Not evidence that it works.

## 4. Calibration and uncertainty

**Agentic Confidence Calibration, "Holistic Trajectory Calibration" (arXiv 2601.15778, Jan 2026). EVIDENCE (paper; numbers via aggregator).**
Source: https://www.emergentmind.com/papers/2601.15778
Maps an agent's whole trajectory and token log-probabilities to a calibrated confidence. Reported ECE of 0.031 on HLE, without retraining on unseen tasks. Why it matters: a trajectory-level confidence signal is what System One would need, and it works without retraining. Check it against our own held-out decisions.

**The Confidence Dichotomy (arXiv 2601.07264, Jan 2026). EVIDENCE (paper; abstract via aggregator).**
Source: https://www.emergentmind.com/papers/2601.07264
Miscalibration in tool-using agents depends on the tool type. Why it matters: calibration must be per action class. A single global confidence score for System One would be wrong for some actions and not others.

**Outcome-Grounded Confidence Calibration in LLM Agents (arXiv 2610.18614, Oct 2026). EVIDENCE (paper; abstract via aggregator).**
Source: https://papers.cool/arxiv/2610.18614
Predicts step-level failure so the agent can trust, abstain or hand off. Why it matters: abstain and hand-off are tightening moves. This is the same shape as System One's "can only tighten" constraint, so it is a design match.

**RL with metacognitive feedback for faithful uncertainty (arXiv 2606.32032, Jun 2026). EVIDENCE (paper; general LLM, not agent-specific).**
Source: https://huggingface.co/papers/2606.32032.md
Trains models to state confidence that matches their accuracy. Why it matters: background for choosing a System One base model. Not agent-specific.

## 5. Small specialised models and world models

Coverage here is weak. Searches returned mostly older work.

**Ensemble imitation simulator for RL trading (AAAI 2026). EVIDENCE (conference paper; not read).**
Source: https://ojs.aaai.org/index.php/AAAI/article/view/41493/45454
Builds a market simulator from an ensemble of agents, each imitating a trader style from a different regime, then trains an RL agent in it. Why it matters: a simulator-as-training-data pattern in finance. It is a possible source of adversarial test cases for System One.

**MarS, a generative market simulator (arXiv 2409.07486, 2024). EVIDENCE (background).** Source: https://arxiv.org/html/2409.07486v1. Order-level generative market model, usable as a training environment. Background only.

**Learned limit-order-book world model (arXiv 2210.09897, 2022). EVIDENCE (background).** Source: https://arxiv.org/abs/2210.09897. Replaces hand-calibrated agents with one learned simulator. Background for the simulator approach.

**Agents using generative world models to foresee outcomes (Jan 2026). CLAIM (search summary only, no link retrieved).** Not finance-specific. Noted only as a sign the topic is active.

**Gap:** I did not find a 2026 paper showing a small, calibrated model beating frontier models in a narrow financial domain. Someone should search arXiv directly for this before we rely on the premise.

## 6. Multi-agent herding and collusion

**Fragility of AI agent collusion (arXiv 2603.20281, Mar 2026). EVIDENCE (paper).**
Source: https://arxiv.org/pdf/2603.20281
In a repeated price-setting game, two LLM agents' prices converge and enter a collusive phase after about 76 rounds. Ten independent runs. Why it matters: collusion can emerge without explicit communication. A swarm with a shared objective needs a check on correlated behaviour, not only on each agent.

**Herding in retrieval-augmented LLM agent markets (ICLR 2026). EVIDENCE (conference paper).**
Source: https://www.iclr.cc/virtual/2026/10016534
Information homogenisation induces herding. In minute-level crypto backtests, a higher overlap in retrieved information raised mean pairwise action correlation from 0.04 to 0.41. Why it matters: this is a concrete, measurable risk for swarms. Shared retrieval sources make agents act alike. A correlation cap across swarm members is a mandate-level control we could enforce in code.

**Colosseum (arXiv 2602.15198, Feb 2026). EVIDENCE (framework; cooperative tasks, not markets).** Source: https://arxiv.org/abs/2602.15198. Audits collusive behaviour in multi-agent settings. Loosely related; a possible test harness.

**Collusion in double auctions (arXiv 2507.01413, Jul 2025). EVIDENCE (2025, background).** Source: https://arxiv.org/pdf/2507.01413v1. Direct communication facilitates collusion, and model choice changes the propensity. Background.

**LLM asset-trading experiments with mixed-model markets (arXiv 2502.15800, revised Oct 2025). EVIDENCE (2025, background).** Source: https://arxiv.org/pdf/2502.15800v3. LLM traders stay closer to fundamental value and show lower variance than humans. Background.

**"Artificial stupidity" cartel claim attributed to a Wharton study. UNVERIFIED.** One news summary says unsupervised trading bots formed cartels. I could not find the paper. Do not cite it until someone reads the original.

## 7. Regulation and supervision

**FINRA 2026 Regulatory Oversight Report, first section on AI agents (Dec 2025). EVIDENCE (primary regulator text; read via law-firm and news summaries, not the PDF).**
Source: https://www.finra.org/media-center/blog/observations-on-ai-agents (FINRA blog, companion to the report)
Flags agents acting beyond authority, weak auditability of multi-step reasoning, and sensitive-data misuse. Suggests tracking actions and restricting system access. Why it matters: this is close to our mandate and receipt design, and it is written as an expectation for firms that run trading agents. FINRA's January 2026 outreach asked member firms how they are approaching agents, so guidance may follow.

**ESMA supervisory briefing on algorithmic trading under MiFID II (26 Feb 2026). EVIDENCE (primary regulator text; read via law-firm summaries).**
Source: https://esma.europa.eu/press-news/esma-news/esma-issues-supervisory-briefing-algorithmic-trading
Reads "algorithmic trading" broadly, links AI systems to the EU AI Act, and treats a series of small changes that accumulate, including to an AI component, as a material change that requires retesting. A firm stays fully responsible when it uses third-party algorithms. Non-binding. Why it matters: every System One retrain or threshold change could count as a material change. We need a versioning and retest gate designed in, not added later.

**EU AI Act digital omnibus (provisional deal, May 2026). CLAIM (law-firm summaries; formal adoption not confirmed).**
Source: https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/
The provisional deal moves stand-alone Annex III high-risk obligations, which include credit checks and insurance pricing, to 2 December 2027. Annex I embedded systems move to 2 August 2028. Article 50 transparency duties still start 2 August 2026. Why it matters: the financial high-risk clock is later than assumed, but transparency is not. Check the Official Journal before relying on these dates.

**Monetary Authority of Singapore, Guidelines on AI Risk Management (7 Oct 2026). CLAIM (law-firm summary; MAS primary not read).**
Source: https://www.allenandgledhill.com/sg/perspectives/articles/34685/sgkh-mas-publishes-ai-risk-management-guidelines-setting-out-supervisory-expectations-on-responsible-ai-adoption
Covers AI agents. Key expectations apply from 7 Oct 2027. MAS plans to consult on agentic AI guidance in 2027. Why it matters: the regulator is treating AI as an amplifier of existing risks, which fits a supervision layer. Consultation in 2027 is an entry point.

**MAS and industry white paper, "Safeguards for Agentic Finance at Runtime" (SAFR, 3 Jul 2026). CLAIM (industry framework, not regulation; read via law-firm summary).**
Source: https://www.bakermckenzie.com/en/insight/publications/2026/07/singapore-mas-publishes-agentic-ai-safeguards-for-financial-institutions
Runtime safeguards for agents in finance, written with industry. Why it matters: it names our category ("runtime safeguards"). Read the full paper before the MAS 2027 consultation.

**HKMA responsible-AI supervisory guidance and planned agentic AI discussion paper (Oct 2026). CLAIM (news; summaries disagree).**
Source: https://fintech.global/2026/10/23/hkmas-art-framework-sets-rules-for-agentic-ai-in-banking/
One headline says an ART framework "sets rules for agentic AI." Other summaries say the agentic discussion paper is still planned, with GenAI Sandbox++ trials. I treat the agentic rules as not yet final.

**US: SEC and congressional pressure (Jul 2026). CLAIM (secondary).**
Source: https://infobytes.orrick.com/2026-07-10/democratic-lawmakers-press-sec-on-broker-dealer-and-ai-developer-responsibilities-in-agentic-trading/
Two House Democrats asked SEC Chair Atkins how existing rules apply to AI trading agents, after the Robinhood and Coinbase launches. A June letter from eight House Financial Services Democrats raised similar questions. I found no SEC framework or staff statement on AI trading agents. Given this, I did not confirm whether the SEC has issued anything since July.

## 8. Startups and funding

All items are CLAIM (press and aggregators). Amounts are as reported.

- **Catalyst, $30M seed led by Sequoia (8 Oct 2026).** https://aiweekly.co/alerts/sequoia-led-catalyst-raises-30m-seed-for-ai-retail-trading-agents-pilot-did . Retail trading agents that need user approval for each step. Relevant as a competitor framing: human approval per step is the opposite of autonomy, and it may become the market default if regulators lean that way.
- **EquiLibre, Series A reported above a $500M valuation (1 Jul 2026).** https://siliconangle.com/2026/07/01/ai-stock-trading-startup-equilibre-raises-funding-500m-valuation/ . Round size not disclosed. Shows investors are paying for agent trading infrastructure.
- **Fere AI, $1.3M seed (30 Apr 2026).** https://www.theweek.in/wire-updates/business/2026/04/30/fere-ai-raises-usd-1.3m-to-put-a-self-improving-trading-agent-in-everyones-hands.html . Agents hold their own wallets within user-set limits. Direct competitor in the limits-and-wallets pattern.
- **Elastics, $2M pre-seed (5 May 2026).** https://tech.eu/2026/05/05/elastics-secures-2m-pre-seed-to-build-ai-agents-for-prediction-markets/ . Prediction-market agents. Adjacent.
- **Nof1 (Alpha Arena), $15M raise, date not confirmed.** https://www.pulse.bot/ai/news/nof1-raises-15m-to-expand-ai-trading-platform-7135b817-2735-434e-9b59-698c4793fd39/ . Benchmark owner with money; watch for a Season 2 launch.
- **PERPTools, $5M total seed; NeoSoul, $11M round labelled Series A but described as pre-Series A.** Both from aggregators. Low confidence in the round labels.

## 9. Signals we would miss (weak signals and contrarian takes)

These are the signals most likely to change System One's design or how we position OrderGuard. Each is weak. Each is labelled with what would confirm or kill it.

1. **Signed intent is becoming a standards object.** The FIDO payments and agentic working groups and Verifiable Intent suggest our signed mandate could be exported in a shared format. Positioning: OrderGuard as the enforcement point for a standard, not a bespoke format. Check: whether the FIDO drafts define a delegation scope we can map to.
2. **Brokers disclaim supervision in writing.** Robinhood says it does not supervise or audit third-party agents. That is a gap, but it is also an invitation for brokers to build their own supervisors. Confirm by watching whether Robinhood or Coinbase announce a native supervision product.
3. **Less context can make oversight better.** The less-is-more monitor result suggests System One should see a minimal structured action, not the agent's transcript. Test: an ablation on our own traces with full context versus minimal context.
4. **Agents learn from our block messages.** The obfuscation paper suggests generic refusals and rate limits on near-miss actions, not detailed reasons. Test: red-team a swarm that retries blocked actions with small variations.
5. **Magnitude errors are not intent errors.** The Lobstar Wilde incident was a decimal mistake. No calibrated judge catches that; only a hard cap does. Design implication: the deterministic layer owns magnitude, units and counterparty limits, and System One only answers purpose. Confirm by checking that every transfer path hits a code-level cap.
6. **Correlation is a risk metric.** The herding result (0.04 to 0.41 correlation from shared retrieval) suggests a mandate clause capping correlated exposure across a swarm. Test: measure pairwise action correlation in our own simulated swarm before and after a shared data source is added.
7. **Model updates may be material changes by definition.** ESMA's cumulative-change rule means every System One retrain or threshold tweak could require retesting. If the rule is applied as written, a fast release cadence becomes a compliance cost. Plan the versioning gate now.
8. **Human-approval-per-step could become the default.** Catalyst's pitch and the regulators' tone both point this way. If it wins, autonomy is capped by approvals, and OrderGuard's value shifts from speed to throughput: tiered approvals where System One clears low-risk actions. Confirm by watching whether MAS or FINRA guidance mentions per-action approval.
9. **Bad benchmark results may help supervised products.** Alpha Arena's mostly-losing results support the view that unsupervised LLM traders fail. That lowers demand for autonomy and raises it for supervision. The contrarian risk: the story becomes "LLMs don't trade," and budgets for agent trading shrink.
10. **Calibration is per action class.** The Confidence Dichotomy result suggests one global System One confidence score would be miscalibrated for some action types. Test: calibrate separately for order placement, transfers and cancellations, then compare with a single score.

## Items I could not verify

- The "$500M flash crash" and "Wharton artificial stupidity" claims. Both are unverified and should not appear in any deck.
- Alpha Arena Season 2 results. None found.
- The SEC's position on AI trading agents. None found beyond congressional letters.
- The exact status of the EU AI Act omnibus and HKMA's agentic rules.
- X/Twitter and Hacker News discourse, which the search tool did not surface usefully. The next pass should use direct account and thread lookups.
