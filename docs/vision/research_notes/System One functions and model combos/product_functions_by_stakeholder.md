# Product functions a robust supervisor for autonomous trading agents must perform, by stakeholder

Status: research notes as of 2026-11-19. Scope: functions, not architecture. Vendor claims are labelled "vendor claim". Items found only as search snippets (not fetched) are labelled "snippet". Items from background knowledge that I could not re-verify in this session are labelled "unverified". Older items are dated.

Caveats on source quality for this session:
- Fetched and read: FINRA 2026 Annual Regulatory Oversight Report (GenAI and AI agents section); arXiv abstract for TradeTrap.
- Federal Reserve SR 11-7 URL returned 404 in this session. SR 11-7 points below are unverified.
- The SEC Rule 15c3-5 and Knight Capital points rest on search snippets and secondary write-ups; the primary SEC release (34-63241) and press release 2013-222 were located but not read.
- Several 2026 arXiv IDs appeared only as search snippets. Treat their details as unverified until read in full.

---

# Key question 1: Owner or investor (delegators, robo-adviser clients)

## Takeaway
Owners need to know the agent stayed inside what they authorised, why each action happened, and what happens when it does not. The regulatory anchor for an owner-facing supervisor is the duty to act within mandate. The robo-adviser literature and the names rule define "mandate" in documentary terms that can be checked against the actual holdings.

### Cited findings
- The SEC's Names Rule (Rule 35d-1) requires a registered fund whose name suggests a particular investment focus to invest at least 80% of its assets accordingly, and the 80% test is checked at least quarterly under the 2023 amendments. The SEC also said a name can be "materially deceptive or misleading even where the fund complies with its 80% policy." Sources: [2001 release IC-24828](https://www.sec.gov/rule-release/ic-24828) (2001, original rule); [2023 amendments, IC-35000 with correction 35000A, as summarised](https://www.sullivanlaw.com/viewpoints/sec-adopts-amendments-to-the-investment-company-names-rule-rule-35d-1) (snippet, 2023); compliance date later extended per Release 33-11368 (snippet; the new date was not confirmed).
- FINRA's 2026 oversight report names as agent risks: agents "acting autonomously without human validation and approval," agents that "may act beyond the user's actual or intended scope and authority," and multi-step reasoning that makes "outcomes difficult to trace or explain, complicating auditability." Source: [FINRA 2026 Annual Regulatory Oversight Report, GenAI section](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai) (fetched).
- FINRA's 2026 report recommends guardrails that "limit behavior," tracking of agent actions, and human-in-the-loop review, plus "ongoing monitoring of prompts, outputs, and model versions, with logs." Source: same as above (fetched).
- Scope-exceeding agent behaviour is the failure mode owners fear most, and it is what a mandate check addresses. Source: FINRA 2026 report as above (fetched).

### Inferences
- The supervisor's owner-facing core is a signed-mandate check per action, with the mandate's language turned into testable predicates (asset classes, leverage, concentration, names-style "focus" claims). A check that only looks at trade size will miss scope violations.
- "Purpose fit" should be tested against the stated fund or account purpose, not just legal limits. The names-rule logic (name or label implies focus; the portfolio must match) is the closest regulatory analogue.
- Owners are a stakeholder who must be able to read the explanation without the agent's raw context. That argues for an explanation object that quotes the mandate clause and the evidence used, which is what the why graph already holds.

### Gaps
- I did not find documented owner-level data on approval fatigue for AI-agent trading specifically. Robo-adviser and retail-brokerage literature on alert fatigue exists but I did not retrieve it in this session.
- I did not find a published standard for "drift" detection in owner mandates. Drift as a concept appears in model risk (SR 11-7 terminology) but not as an owner-mandate standard. Unverified.

### Functions required (owner side)
| Function | Why (incident / rule / practice) | Speed | Incumbent or adjacent handling |
|---|---|---|---|
| Signed mandate ingestion and versioning | Scope exceedance (FINRA 2026); owner must be able to prove what they authorised | Batch on change, checked per action | Robo-advisers use investment policy statements and suitability profiles; no common standard for agent mandates found |
| Per-action endorsement check against mandate predicates | FINRA 2026: agents may exceed scope | Must complete before order release (sub-second is inferred, not sourced) | No incumbent for AI agents found; trading-platform pre-trade checks cover limits, not purpose |
| Purpose-fit and naming-style focus test | Names Rule 35d-1 (80% test, quarterly check) | Periodic plus on each order | Fund compliance does this quarterly for funds; not per action |
| Drift detection (portfolio vs mandate over time) | Inference from quarterly-check practice; FINRA monitoring language | Continuous monitoring, alert on threshold | Portfolio-analytics vendors do exposure drift; I did not verify their mandate-level tooling |
| Plain-language explanation citing mandate clause and evidence | FINRA auditability concern | On demand, plus at every hold or ask | No incumbent found for agent explanations |
| Interruption policy (when to ask owner vs hold vs proceed) | Approval fatigue is an inference from common UX practice; no primary source found | Set in advance; reviewed periodically | Brokerage order-routing "ask" modes exist in many retail apps; no sourced agent standard |

---

# Key question 2: Regulators and compliance

## Takeaway
The directly binding rules are on broker-dealers and market access, not on the supervisor vendor. A supervisor that sits between an agent and a broker will mostly be a control the broker or the adviser relies on, so it must produce evidence those firms can keep. FINRA's 2024 and 2026 guidance says existing rules apply to GenAI and agents; it adds no new rule. The EU AI Act high-risk classification is narrower than many assume for trading.

### Cited findings

**SEC Rule 15c3-5 (market access rule)**
- Requires firms with market access to control the risks of market access so as not to jeopardise their financial condition. Controls must be pre-trade and automated, cover erroneous orders, credit and capital limit breaches, and failure to comply with trading rules, and must be under the broker's direct and exclusive control with limited exceptions. Annual CEO certification. Source: [FINRA Market Access key topics](https://www.finra.org/rules-guidance/key-topics/market-access) and [FINRA 2026 oversight report market access section](https://finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/market-access-rule) (snippets; the rule text itself is [SEC Release 34-63241](https://www.SEC.gov/rules/final/2010/34-63241.pdf), 2010, not read in this session).
- The rule effectively ended unfiltered sponsored access. Source: snippet of FINRA page (above).
- Enforcement: Knight Capital, 2012 loss reported at roughly $440M to $465M+ (figures vary by source). Root cause: an incomplete code deployment left old test code live on one of eight servers, with no second-person review and no written procedure requiring one. The SEC settled for $12M on 2013-10-16 as the first enforcement action under 15c3-5, and required an independent consultant to review controls. Sources: [SEC press release 2013-222](https://www.sec.gov/news/press-release/2013-222) (listed, not read); [Mondo Visione summary](https://mondovisione.com/news/sec-charges-knight-capital-with-violations-of-market-access-rule-20131016/) (snippet). Note the SEC noted its risk assessment focused on inventorying existing controls, not on malfunction scenarios, and that an internal system had sent 97 alert emails before the open.

**FINRA Regulatory Notice 24-09 (June 27, 2024)**
- Existing rules apply to generative AI and LLMs, including in-house and third-party or embedded tools. No new requirements. Rule 2210 content standards and Rule 3110 supervision apply. Source: [FINRA Notice 24-09](https://www.finra.org/rules-guidance/notices/24-09) (snippet from search; not fetched).

**FINRA 2026 Annual Regulatory Oversight Report, GenAI and agents**
- Names agent risks (autonomy, scope, auditability, data sensitivity, domain knowledge, reward design). Expects supervisory processes "specific to the type and scope of the AI agent," pre-deployment testing, model-version monitoring, logs, and guardrails. Source: [FINRA 2026 report](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai) (fetched). Prompt injection is not named in this section.

**MiFID II RTS 6 (Commission Delegated Regulation (EU) 2017/589)**
- Requires: a kill switch that lets a senior manager withdraw all unexecuted orders from a malfunctioning algorithm; pre-trade controls on market and credit risk limits, maximum order volumes, execution throttles and price collars (practitioner summary); conformance testing, stress testing, scenario analysis; annual self-assessment and validation; outsourced arrangements must still comply, and outsourcing contracts should include kill-switch capabilities. Sources: [RTS 6 PDF](https://ec.europa.eu/finance/securities/docs/isd/mifid/rts/160719-rts-6_en.pdf) (listed, not read in full); [Kroll on RTS 6](https://www.kroll.com/en/publications/financial-compliance-regulation/algorithmic-trading-under-mifid-ii) and [Deloitte on the ESMA supervisory briefing](https://www.deloitte.com/uk/en/blogs/ecrs/mind-the-gaps-why-esma-s-algorithmic-trading-supervisory-briefing-is-a-turning-point-for-firms.html) (snippets). Hogan Lovells and Kroll commentary dates from 2016 to 2018. The ESMA algorithmic trading supervisory briefing is more recent; I did not retrieve its text.
- Applicability to an agent supervisor: RTS 6 defines algorithmic trading broadly. An LLM agent that decides and places orders is plausibly in scope for the investment firm that uses it. Whether an external judgement layer is "part of the algorithm" is an open legal question. Unverified and not settled by any source I found.

**SEC Names Rule (Rule 35d-1)**
- Original 2001 adoption (IC-24828) set an 80% policy; 2023 amendments added thematic and characteristic-based names, a quarterly check, and "materially deceptive" language. Source: as above.
- Applies to registered funds, not to agent accounts. The useful analogy is purpose fit. Its applicability to an autonomous agent account is not established.

**Federal Reserve SR 11-7 (model risk management, April 2011)**
- Background knowledge, unverified in this session (the fetch returned 404): defines a model, separates development/implementation/use, independent validation, and governance; expects ongoing monitoring and outcomes analysis; flags use of a model outside its intended purpose as a core risk. Applies to bank-supervised institutions, so it reaches a supervisor only where a bank or a bank-affiliated adviser uses the agent. Relevant functions: model inventory, documented intended use, out-of-purpose detection, outcomes analysis.

**EU AI Act (Regulation (EU) 2024/1689), Annex III high-risk**
- Credit scoring of natural persons is high-risk under Annex III point 5(b). Fraud-detection systems are excluded from that category. Article 6(3) derogation does not apply to systems that profile natural persons. Source: snippets from [Williams & Fry](https://www.williamfry.com/knowledge/high-risk-ai-in-financial-services/) and [Commission AI Act service desk Annex III](https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-3) (snippet; the Commission page is listed, not read).
- Models that score portfolios, institutional counterparty risk, or treasury signals without scoring individuals appear to fall outside. Pricing combined with credit scoring in one integrated process is high-risk. Sources: snippets only.
- Timing conflicts across sources: one says Annex III obligations apply from 2 December 2027 after the Digital Omnibus; another says 2 August 2026. Do not rely on either without the Official Journal text. Unverified.
- No source found classifies an autonomous trading agent as high-risk. Gap.

### Inferences
- The regulatory functions a supervisor is forced to have, if it is in a regulated chain: (1) pre-trade automated controls that can be proven (15c3-5, RTS 6); (2) a kill switch that cancels unexecuted orders, not only blocks future ones (RTS 6); (3) an audit trail that lets a human reconstruct why an action was approved (FINRA 2026 auditability); (4) a documented intended-use statement and out-of-purpose detection (SR 11-7 where bank-supervised); (5) periodic self-assessment and conformance and stress testing (RTS 6); (6) vendor and outsourcing contract terms covering kill-switch and logs (RTS 6, FINRA 2026 third-party risk).
- The 15c3-5 point that controls must be "under the direct and exclusive control" of the broker means a supervisor sitting outside the broker cannot itself satisfy 15c3-5; it can only feed the broker's controls. That affects the product design.
- Knight Capital suggests the deployment pipeline of the supervisor itself is a control surface. Version control, dual review of changes to decision rules, and alerting on mismatched deployment are functions to build.

### Gaps
- No SEC or FINRA guidance found that names AI-agent trading supervisors specifically.
- The FINRA 24-09 and SEC 15c3-5 primary texts were not read in full in this session.
- RTS 6 kill-switch wording was not read in primary form.

### Functions required (regulatory side)
| Function | Rule or case | Speed | Incumbent handling |
|---|---|---|---|
| Automated pre-trade control with broker-owned enforcement | 15c3-5 | Pre-trade, per order | Exchange and broker gateways (see Key question 3) |
| Kill switch that withdraws all unexecuted orders | RTS 6 | Immediate; not sourced | Algo platforms; broker "cancel all" |
| Immutable decision record with reconstructable reasoning | FINRA 2026; Rule 17a-4 recordkeeping (background, unverified) | Write at decision time | Trade surveillance archives; no agent-reasoning standard |
| Intended-use register and out-of-purpose detection | SR 11-7 (unverified) | Continuous | Model inventories at banks |
| Annual conformance, stress and scenario testing | RTS 6 | Periodic | Algo-test harnesses |
| Deployment change control with two-person review | Knight Capital | Each deployment | Standard SDLC practice; SEC cited its absence |

---

# Key question 3: Brokers and exchanges

## Takeaway
Pre-trade risk checks (fat-finger, price collar, notional, position, credit, rate limits, self-trade prevention) and kill switches already exist at the broker and exchange level. They check orders, not reasons. An AI agent layer adds a new need: checks against the agent's authority and rationale, and the ability to stop per agent, not per account.

### Cited findings
- 15c3-5 requires automated pre-trade controls including erroneous orders and credit and capital limits, and FINRA's 2026 report flags fixed-income pre-trade "hard" blocks as a current supervisory focus. Sources: FINRA snippets as above.
- Kill switches scoped per user, API key, strategy, desk, or firm-wide: vendor-blog claim, [Gravitee](https://gravitee.io/corpus/gen-1134/electronic-trading/pre-trade-risk-controls-and-kill-switches-for-electronic-trading-apis.html) (vendor claim, snippet; not verified).
- Kill switches must halt in-flight actions, not just future ones: practitioner claim, [kunalganglani.com](https://www.kunalganglani.com/blog/ai-agent-kill-switch-spend-limits) (snippet; a blog, treat as opinion).

### Inferences
- The broker will keep its own fat-finger and credit checks. A supervisor should not duplicate them. It should add what brokers do not check: whether the owner endorses the action given the agent's knowledge.
- Per-agent kill switch is a gap. Broker kill switches stop a session or account; an agent fleet needs stop-by-agent, stop-by-strategy, and stop-by-mandate.
- Self-trade prevention and rate limits matter more with many agents on one account (herding and cross-agent self-trades).

### Gaps
- I did not retrieve exchange primary documentation (CME, Nasdaq, ICE rulebooks on kill switches and message throttles) in this session. Exchange-level kill-switch and message-throttle specifics are unverified.
- No broker or exchange AI-agent-specific control found.

### Functions required (broker side)
| Function | Why | Speed | Incumbent handling |
|---|---|---|---|
| Fat-finger, price collar, notional, position, credit checks | 15c3-5; RTS 6 | Microseconds to milliseconds at exchange gateways (order-of-magnitude, unverified) | Broker risk gateways (vendor and in-house) |
| Stop-by-agent / stop-by-mandate kill switch | Gap; RTS 6 kill-switch concept applied per agent | Immediate | Session or account kill switches |
| Message throttle and order rate limits per agent | RTS 6 throttles; herding | Per message | Exchange message throttles; per-API-key limits |
| Self-trade prevention across agents on one account | Market practice | Pre-trade | Exchange STP flags |
| Attribution of each order to agent and decision record | FINRA 2026 auditability | Per order | Order tags; no agent-level standard |

---

# Key question 4: Agent builders and platforms

## Takeaway
Guardrail, spend-control, and policy-engine products for agents exist, but they are almost all for payments and wallets (spend caps, allowlists, kill switches). Trading-specific semantics (mandate, purpose fit, position risk, market context) are absent. Most products rely on rules, not on judgement with evidence. Vendor claims are unverified.

### Cited findings
- Policy engines for agent wallets with spend limits, allowlists and kill switches enforced before execution: vendor claims from WAIaaS (21 policy types, 4 security tiers), Policy Layer (non-custodial limits and kill switches), three.ws agent-guards (trade-limit kill switch, wallet freeze), zerocopy-systems (enclave claim). Sources: [WAIaaS and related DEV posts](https://dev.to/walletguy/21-policy-types-4-security-tiers-building-bulletproof-ai-agent-guardrails-31g6), [Policy Layer](https://policylayer.com/glossary/financial-guardrail), [agent-guards npm](https://socket.dev/npm/package/@three-ws/agent-guards), [zerocopy-systems](https://zerocopy-systems.pages.dev/agents). All vendor claims, snippets only, not verified.
- Design recurrence: enforcement outside the model; judge the transaction, not the agent's stated rationale, because a prompt-injected agent can justify a malicious transfer convincingly. Source: [coincub](https://coincub.com/?p=14039) (snippet, opinion).
- Nested caps (per-transaction at or below daily, weekly, monthly). Source: [stablecoininsider](https://stablecoininsider.org/how-to-set-spend-limits-ai-agent-usdc-wallet.md) (snippet, opinion).
- Search found no established incumbent for trading-specific agent guardrails.

### Inferences
- The existing products cover the "rules" half: caps, allowlists, freezes. The missing half is evidence-linked judgement and mandate semantics. That is the gap OrderGuard-style supervisors would fill.
- Rationale-blind enforcement (judge the trade) and rationale-aware judgement (judge the reason) are both needed. Products that only do the first cannot tell whether a trade was endorsed.

### Gaps
- Not checked: major agent frameworks' built-in guardrail features (e.g., agent SDK permission hooks, guardrail frameworks from large platforms). Not searched in this session.
- No trading-specific agent guardrail product with independent review was found.

### Functions required (platform side)
| Function | Why | Incumbent handling |
|---|---|---|
| Caps and allowlists per agent, per counterparty, per instrument | Spend control; trade caps | Wallet policy engines (vendor claims) |
| Stop-by-agent freeze with owner-only resume | Kill-switch practice | Same products (vendor claims) |
| Tool-permission gating before any tool call | Scope control | Framework-level permission hooks (not checked) |
| Enforcement independent of the model | Prompt-injection resistance | Policy engines (vendor claims) |

---

# Key question 5: Attackers

## Takeaway
Attacks on LLM trading agents are documented in academic work from late 2025 through 2026, mostly on backtests. Prompt injection via news and social posts, data poisoning of feeds, and multi-agent role attacks have measured effects. Fake authority (a message claiming to be the owner or the compliance team) is documented as a class in agentic-commerce work and in FinVault-type benchmarks, but I did not find a trading-specific measurement.

### Cited findings
- TradeTrap (arXiv 2512.02261, 1 Dec 2025, Yan et al.): controlled perturbations at a single component of an LLM trading agent propagate through the decision loop to "extreme concentration, runaway exposure, and large portfolio drawdowns." Backtests on US equity data. Source: [arXiv abstract](https://arxiv.org/abs/2512.02261) (fetched). The abstract gives no figures. A search snippet from another site claims one agent's return fell from about 7.8% to 0.9% under injection; I did not confirm this in the full paper, so treat it as unverified.
- FinVault (arXiv 2601.07853, Jan 2026): benchmark for financial agent safety covering prompt injection and jailbreaks; reports attack success rates up to 50% on state-of-the-art models. Source: [arXiv 2601.07853](https://arxiv.org/html/2601.07853v1) (snippet; not fetched). Verify.
- SoK on academic financial LLM trading schemes (arXiv 2609.19705, 2026): reports indirect prompt injection succeeding in 10.7% to 29.6% of cases against current frontier models. Source: [arXiv 2609.19705](https://arxiv.org/pdf/2609.19705) (snippet; unverified, the ID is recent, read in full before citing).
- Multi-agent trading robustness study (ICLR 2026 listing, Analyst / Researcher / Trader / Risk Manager roles): data poisoning of news articles and hidden instructions in social posts, matched to roles. Sources: [ICLR listing](https://iclr.cc/virtual/2026/10016542), [alphaxiv](https://www.alphaxiv.org/abs/2608.24069) (snippets).
- Agentic commerce SoK (arXiv 2604.15367): crafted news or social posts with hidden instructions push an agent into a specific trade; attacks are economically motivated because the attacker profits from the trade. Source: [arXiv 2604.15367](https://arxiv.org/pdf/2604.15367) (snippet).
- Live-market incidents: Alpha Arena Season 1 (Nof1, crypto, ended early Nov 2025). Most models lost money; two of six were profitable. Nof1 attributed much of the loss to trading costs from over-trading. Nof1 said its short duration and small capital mean the results are not a definitive ranking. Sources: [iweaver summary](https://iweaver.ai/blog/alpha-arena-ai-trading-season-1-results), [Protos](https://protos.com/llm-crypto-trading-contest-finds-llms-cant-trade-crypto), [KuCoin flash](https://www.kucoin.com/news/flash/ai-trading-models-struggle-in-live-market-tests-majority-of-systems-report-losses) (snippets; secondary, figures vary by source).

### Inferences
- Over-trading and cost-erosion (Alpha Arena) is a failure mode a supervisor should catch with turnover and cost budgets, not only with mandate checks. It is an operator failure, not an attack.
- Injection surfaces in a trading agent are: news and filings, social feeds, the agent's own memory and notes, and the owner's mandate if editable. A supervisor that reads the why graph is exposed to injection through the agent's notes (which quote external text). Evidence quotes must be tagged by source trust before the judge sees them.
- Fake authority: the judgement layer must verify that an "owner approval" comes through the signed-channel path, not from text in the record.

### Gaps
- No trading-specific measurement of fake-authority attacks found.
- No documented incident of real money lost through injection in a live market was found. Alpha Arena losses are overtrading, not attack.
- Memory poisoning on trading agents: I did not find a dedicated paper in this session.
- Full texts of the 2026 arXiv items were not read.

### Functions required (attacker-facing)
| Function | Threat | Incumbent handling |
|---|---|---|
| Source-trust tagging of quoted evidence | Injection via news, filings, posts | Generic LLM injection defences; FinVault suggests they are weak in finance |
| Signed-channel verification for owner or compliance approvals | Fake authority | Standard signed-request practice |
| Memory integrity and provenance on agent notes | Memory poisoning | Not found |
| Judge the trade against mandate, not the rationale | Plausible justification of a bad trade | Vendor design claim (coincub) |
| Turnover and cost budget | Overtrading; manipulated churn | Broker commission and turnover reporting |

---

# Key question 6: Operators

## Takeaway
Operators need monitoring of decision quality over time, calibration drift of the judge, incident handling with a replay path, and audit exports. The primary sources give the what (FINRA 2026: monitoring prompts, outputs, model versions, logs). Mechanisms are mostly practitioner practice; I did not retrieve primary sources for drift or replay tooling.

### Cited findings
- FINRA 2026 expects ongoing monitoring of prompts, outputs, and model versions, with logs and human-in-the-loop review, and monitoring of agent actions. Source: [FINRA 2026 report](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai) (fetched).
- Knight Capital shows an incident can come from deployment and not only from the model. The response included an independent consultant review. Source: as above.
- SR 11-7 (unverified) expects outcomes analysis and ongoing monitoring of model performance against outcomes.

### Inferences
- Calibration of the judge is itself a model-risk object. Its agreement with owner decisions (on a held-out set of owner rulings) is the metric to track. This is an inference from SR 11-7 practice.
- Incident replay must reconstruct the exact graph state at each decision, including what the judge saw. That means versioned snapshots of the why graph at decision time, not the current state.
- Operators need a kill switch that is tested on a schedule, since a kill switch that has never been exercised is a failure mode of its own (Knight Capital-type risk).

### Gaps
- No primary source on judge calibration drift for LLM judges found.
- Incident-response playbook standards for AI trading found: none.

### Functions required (operator side)
| Function | Why | Incumbent handling |
|---|---|---|
| Decision-time snapshot of the full why graph for replay | FINRA 2026 auditability; Knight Capital reconstruction | Trade archives; no agent-graph standard |
| Judge calibration dashboard vs owner rulings | SR 11-7 outcomes analysis (unverified) | Model risk tooling at banks |
| Scheduled kill-switch drills | Practice inference | Broker operational testing |
| Deployment change control and rollback for rules and prompts | Knight Capital | Standard SDLC |
| Alerting on rate of holds and asks (approval-fatigue signal) | Inference | Not found |

---

# Key question 7: Scale (a million decisions a day)

## Takeaway
A million decisions per day averages about 12 per second. The peaks are the problem: market opens, news bursts, and correlated triggers. Latency budgets, cost per judgement, and correlated failures across agents are the main issues. Most of the numbers below are my arithmetic, not sourced.

### Cited findings
- Alpha Arena Season 1: one model placed 1,418 trades in a round while the top model placed 158 orders under the same prompt. This is one example of wide variance in order volume. Source: [besthub or iweaver summaries](https://www.besthub.dev/articles/can-llms-trade-crypto-profitably-inside-the-alpha-arena-competition-ace3b75ceaa5) (snippet, secondary).
- TradeTrap: single-component perturbations propagated to concentration and runaway exposure across agent types. This is an empirical correlated-failure pattern. Source: [arXiv 2512.02261](https://arxiv.org/abs/2512.02261) (fetched).
- Knight Capital: one faulty deployment generated 97 alert emails before the open. Alerts existed; response did not. Source: [SEC order summary](https://www.financemagnates.com/forex/regulation/a-costly-error-knight-capital-to-pay-12-million-to-sec-as-penalty-for-catastrophic-2012-trading-incident/) (snippet).

### Inferences
- Arithmetic: 1,000,000 per day is about 11.6 per second on average. With a 10x peak factor during opens and news bursts it is about 120 per second. A judge call that takes 2 seconds needs roughly 240 concurrent judge slots at peak. Cost depends on tokens per judgement; at a few thousand tokens per judgement, daily token volume is in the billions. These are inferences, not sourced.
- Most decisions should not reach a model judge. A deterministic pre-filter (mandate predicates, caps, position limits) should clear the majority and reserve judge calls for ambiguous actions. This keeps cost and latency bounded and is also what 15c3-5-style automated controls already do.
- Correlated failure: when many agents share a model version, a prompt-injection or a bad news feed can trigger the same action across agents at once. Diversity of judges (model combos) and per-agent exposure caps reduce this. The herding risk is an inference from TradeTrap and market practice, not a sourced number.
- Latency in the judge path must sit inside the order cycle of the broker. Exchange gateways operate on microseconds; an LLM judge cannot. So the judge must sit on decisions that are not latency-critical, with the pre-filter and hold states handling the fast path. This is inference.

### Gaps
- No source found quantifying LLM judge cost or latency at this scale.
- No source found on multi-agent herding in live markets with LLM agents.

### Functions required (scale)
| Function | Why | Notes |
|---|---|---|
| Deterministic pre-filter before any judge call | Latency and cost | Inference |
| Queueing with priority for exposure-reducing actions | Peak handling | Inference |
| Cross-agent exposure aggregation and cap | Herding and correlated failure | TradeTrap; market practice |
| Judge diversity across model families | Correlated-judge failure | Inference from model-combo design |
| Circuit breaker that defaults to hold when judges are unavailable | Fail-safe | Consistent with "can only tighten" rule; RTS 6-style kill-switch logic |

---

# Cross-cutting: what is missing from incumbents for AI trading agents

1. Mandate semantics: no incumbent turns a signed mandate into per-action predicates with purpose-fit tests.
2. Evidence-linked judgement: broker checks and agent policy engines judge orders or spends, not whether the owner would endorse the action given what the agent knew.
3. Agent-level stop and scope: broker kill switches are per account or session.
4. Reasoning audit: no standard for replayable agent reasoning under FINRA's auditability concern.
5. Source-trust and injection defence for evidence quoted into judgement.
6. Judge calibration and drift tied to owner rulings.

# Summary of source status
- Read in full or fetched: FINRA 2026 GenAI section; arXiv 2512.02261 abstract.
- Snippets only (verify before citing): FINRA 24-09, FINRA 15c3-5 page, RTS 6 commentary, EU AI Act timing and classification, Knight Capital summaries, Alpha Arena reports, 2026 arXiv items (2601.07853, 2609.19705, 2604.15367, 2608.24069), vendor products.
- Unverified background: SR 11-7 content; 17a-4 recordkeeping; exchange-level latency and kill-switch specifics; RTS 6 kill-switch text.
- Not found: any SEC, FINRA, or ESMA guidance naming AI-agent trading supervisors; a live-market loss caused by prompt injection; an incumbent for trading-specific agent mandate checks.
