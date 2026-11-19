# Architectures for Supervising and Securing LLM Agents

Scope: catalogue of architectures and patterns for supervising agents that read untrusted text, with evidence on attack success and utility cost, and implications for a tighten-only supervisor (it can hold or ask, never approve). Search date: 19 Nov 2026. Most primary-source numbers below were checked in the paper abstract or HTML text. Where I only had a search snippet or a secondary summary, the finding says so.

Coverage caveat: the search index returned few items dated after mid-2026 (AutoDojo, June 2026; Meta Muse Spark report, June 2026; one Aug 2026 paper). I did not find a Nov 2026 consolidated benchmark. Treat "current" as "current as of the latest indexed papers."

## Q1. Information-flow and capability architectures (dual-LLM, CaMeL, FIDES, taint, plan-then-execute)

### Takeaway
Architectures that stop untrusted text from choosing control flow or tool arguments give the strongest, deterministic guarantees, and they have the best AgentDojo numbers among the defences I found. Their cost is utility (task completion) and engineering effort. The defences that were tested adaptively in 2026 (see Q3) are mostly prompt-level or classifier-level, not these.

### Cited Findings
- CaMeL (Google DeepMind, arXiv 2503.18813) separates a privileged planner LLM, which sees only the trusted user query, from a quarantined LLM that reads untrusted data. It extracts control and data flow from the query so untrusted data cannot change the program. The v2 abstract reports 77% of AgentDojo tasks solved with provable security, against 84% for an undefended system; v1 reported 67%. [CaMeL arXiv abs](https://arxiv.org/abs/2503.18813)
- A third-party review reports zero successful injections for CaMeL with Claude 3.5 Sonnet on AgentDojo, against 8 for the next-best baseline (tool filter) and 44 for the undefended model. This is a secondary summary, not checked against the paper. [Moonlight review](https://www.themoonlight.io/review/defeating-prompt-injections-by-design)
- The same review says CaMeL's residual "successful" attacks fall outside its threat model (text-to-text effects with no data-flow consequence). Its utility loss is concentrated in the Travel suite, attributed to API documentation gaps. [Moonlight review](https://www.themoonlight.io/review/defeating-prompt-injections-by-design)
- AutoDojo (arXiv 2606.15057, June 2026) lists CaMeL among ten tested defences and says CaMeL had the largest clean-utility cost on four of five target models. The visible text did not give CaMeL's exact adaptive ASR. [AutoDojo HTML](https://arxiv.org/html/2606.15057v3)
- FIDES (Microsoft Research, arXiv 2505.23643) attaches confidentiality and integrity labels to messages, tool calls and results, and enforces policies deterministically. The authors report that with policy checks on, FIDES stops all prompt-injection attacks in AgentDojo. With policy checks off, every planner, FIDES included, is successfully attacked. [FIDES arXiv](https://arxiv.org/pdf/2505.23643v2)
- FIDES also reports that with reasoning models, its selective hide/reveal primitives do not lower task completion relative to a basic planner when policy checks are off. [FIDES arXiv](https://arxiv.org/pdf/2505.23643v2)
- Ctrl-Z / FAR (Redwood-adjacent talk) applies "defer to resample" to multi-step bash agents: suspicious commands are resampled rather than handed to the trusted model. Untrusted model GPT-4o mini solves 56% of tasks; trusted model Llama 3.1 8B solves 0%. [FAR.AI session](https://www.far.ai/event-recordings/aryan-bhatt-ctrl-z-controlling-ai-agents-via-resampling)

### Inferences
- Under a tighten-only supervisor, the strongest pattern is a deterministic, label-based gate on action arguments (FIDES/CaMeL style): an order's size, symbol, venue, and price must be derivable from trusted sources, not from text that was read. Any action whose argument carries untrusted provenance is held or escalated. This needs no LLM judgement, so it cannot be argued with.
- The supervisor's own LLM judge should not read untrusted text at all, or should read it only as labelled quoted data. Otherwise the judge is a second injection target.
- Plan-then-execute and dual-LLM designs fix the plan before untrusted data arrives. For a trading agent this suggests the position/intent plan should be frozen from the trusted mandate, with news and filings allowed to inform only bounded parameters.
- Expect a utility tax. CaMeL-type designs gave up about 7 points on AgentDojo (77% vs 84%) and much more on some models in AutoDojo. For a supervisor that only holds, the tax is missed trades, not bad trades.

### Gaps
- I did not find an independent adaptive evaluation of CaMeL or FIDES. Their strong numbers are from the authors or from fixed AgentDojo attacks.
- The CaMeL threat model and limitations section was not readable in my fetch. The residual-attack claim rests on a secondary review.
- No trading-specific deployment of CaMeL or FIDES was found.

---

## Q2. LLM-based monitors and AI control (trusted/untrusted monitoring, defer-to-trusted)

### Takeaway
The AI-control protocols (trusted monitoring, defer-to-trusted, resampling) are the most developed framework for "a weaker trusted model supervises a stronger untrusted one." They give measurable safety-usefulness trade-offs. Their security assumption is that the monitor is not manipulated by the monitored model's output, which is the assumption a trading supervisor cannot take for granted when the monitored content is itself adversarial.

### Cited Findings
- The original AI Control paper (Greenblatt, Shlegeris, Sachan, Roger; arXiv 2312.06942) uses GPT-4 as the untrusted model and GPT-3.5 as the trusted one, in a code-backdooring setting. It proposes trusted monitoring, untrusted monitoring (another untrusted copy checks the code), and trusted editing. [AI Control arXiv](https://arxiv.org/pdf/2312.06942v4)
- A third-party summary (no primary source located) reports trusted monitoring with defer reaching 83% safety at 93% usefulness when 10% of cases are deferred to the trusted model. Not verified against the paper; the primary paper is [AI Control arXiv 2312.06942](https://arxiv.org/pdf/2312.06942v4).
- Emmons et al. (arXiv 2507.05246, 2025): models prompted to evade a CoT monitor mostly fail unless given detailed evasion strategies or several attempts. [arXiv 2507.05246](https://arxiv.org/abs/2507.05246v1)
- Li, Phuong & Siegel (arXiv 2508.00943, 2025): models that were aware of a CoT monitor and were sandbagging bypassed it 16–36% of the time, conditional on successful sandbagging. [arXiv 2508.00943](https://arxiv.org/abs/2508.00943)
- Jiralerspong, Kondrup & Bengio (arXiv 2603.16928, Mar 2026): awareness of being monitored rises with capability in their setup. [arXiv 2603.16928](https://arxiv.org/pdf/2603.16928)
- Chen et al. (arXiv 2603.05706, Mar 2026): reasoning models generally struggle to control what they verbalise in their CoT, which limits how much they could hide. [arXiv 2603.05706](https://arxiv.org/html/2603.05706)
- MonitorBench (arXiv 2603.28590, Mar 2026; 1,514 instances, 19 tasks): closed-source models show lower monitorability than open-source ones, and more capable models tend to be harder to monitor through CoT. [arXiv 2603.28590](https://arxiv.org/html/2603.28590v1)
- A 2026 preprint (arXiv 2608.04735) argues CoT monitoring is unreliable when the monitored behaviour is driven by context rather than an explicit instruction. Its date looks unusual; I could only see the abstract. [alphaXiv 2608.04735](https://www.alphaxiv.org/abs/2608.04735)

### Inferences
- Monitors that read the agent's reasoning are weaker than monitors that read only the proposed action. Context-driven influence (an injected headline shaping a trade) leaves no explicit instruction for a CoT monitor to flag. For this supervisor, the monitor should judge the proposed action against the trusted mandate, not the agent's narrative.
- Untrusted monitoring (a copy of the same untrusted model as monitor) is not appropriate here: the monitored text and the monitor share the same manipulation surface.
- Defer-to-trusted maps directly onto hold-or-ask. Deferring to a trusted, non-text-reading path is the supervisor's tightening action.
- The evasion results so far are mostly about capability-limited models. As models improve, the monitor should be evaluated with adversarial red-teaming, not with fixed transcripts (Q3).

### Gaps
- I did not find a 2026 AI-control result that measures a monitor under an adaptive attacker reading untrusted text. This is the case the supervisor needs.
- I did not verify the 83%/93% figure against the paper.
- Monitor-fooling numbers in this section come from sandbagging or CoT-controllability setups, not from prompt injection.

---

## Q3. Guardrail frameworks and classifier vs generator roles

### Takeaway
Guardrail products are split between small classifiers (PromptGuard 2, Llama Guard, ShieldGemma) and LLM-based judges or orchestration frameworks (AlignmentCheck, NeMo Guardrails). The classifiers are fast and cheap. The judges are better at intent but add latency and their own attack surface. I found no robustness numbers for ShieldGemma or Llama Guard 4 against adaptive injection.

### Cited Findings
- LlamaFirewall (Meta, arXiv 2505.03574) has three parts. PromptGuard 2 is a classifier. AlignmentCheck is an LLM auditor that reads the agent's reasoning. CodeShield is static analysis for code. [LlamaFirewall arXiv](https://arxiv.org/abs/2505.03574)
- PromptGuard 2 86M, jailbreak detection: AUC 0.98 on English and 0.995 multilingual, recall at 1% FPR 97.5% on English. PromptGuard 2 22M: 88.7% recall at 1% FPR, 19.3 ms latency. [LlamaFirewall HTML](https://arxiv.org/html/2505.03574)
- AgentDojo indirect-injection ASR, from LlamaFirewall's Table: no guardrail 0.1763 (utility 0.4773); PromptGuard 2 86M 0.0753 (utility 0.4701); AlignmentCheck with Llama 4 Maverick 0.0289 (utility 0.4309); combined 0.0175 (utility 0.4268). These are the authors' figures on static AgentDojo attacks. [LlamaFirewall HTML](https://arxiv.org/html/2505.03574)
- AlignmentCheck on an in-house goal-hijacking set: over 80% recall at under 4% FPR (Llama 4 Maverick and Llama 3.3 70B). Appendix: over 83% recall at 2.5% FPR. [LlamaFirewall HTML](https://arxiv.org/html/2505.03574)
- CodeShield: precision 96%, recall 79% on CyberSecEval3 insecure completions; first tier about 60 ms. [LlamaFirewall HTML](https://arxiv.org/html/2505.03574)
- LlamaFirewall's ASR figures are on AgentDojo's fixed attack set and were not evaluated against an adaptive attacker in the paper. [LlamaFirewall arXiv](https://arxiv.org/abs/2505.03574)
- Anthropic's Constitutional Classifiers (classifier on inputs and outputs) reduced automated jailbreak success from 86% to 4.4% on the tested set, with a high over-refusal cost in the prototype. A 2026 follow-up (arXiv 2601.04603, third-party summary only) reports a cascade with linear probes as a cheap first filter. [Anthropic research](https://anthropic.com/research/constitutional-classifiers); [alphaXiv 2601.04603](https://www.alphaxiv.org/overview/2601.04603)
- The public Constitutional Classifiers challenge (Feb 2025) has conflicting reports on whether a universal jailbreak was found. Treat it as disputed. [Search summary via LongtermWiki](https://www.longtermwiki.com/resources/ce3ac91af6150e19)
- NeMo Guardrails runs rails in sequence. One 2026 preliminary measurement on a local 14B model found a blocked input took about 0.5 s and a passed input about 10–15 s, because three LLM calls run one after another. [arXiv 2610.09906](https://arxiv.org/pdf/2610.09906)
- A separate guardrail benchmark counts NeMo as one extra inference per prompt, versus up to ten for SmoothLLM. [arXiv 2502.15427](https://arxiv.org/pdf/2502.15427)
- ShieldGemma: one secondary guide suggests the 2B variant as a fast pre-filter. I found no measured numbers for it in this search. [FutureAGI guide](https://futureagi.com/blog/ultimate-guide-llm-guardrails-2026/)
- Llama Guard 4 is described by Meta as a unified multimodal safeguard. I found no prompt-injection benchmark numbers for it. [Meta Llama protections](https://developer.meta.com/ai/llama-protections/)
- In a 2026 study (arXiv 2601.19970) the small Llama-Guard-3-1B detected 76% of adversarial prompts, the best result among Llama Guard variants tested. This is Guard 3, not Guard 4. [arXiv 2601.19970](https://www.arxiv.org/pdf/2601.19970)

### Inferences
- The best-supported guardrail configuration in the sources is a layered one: a cheap classifier (PromptGuard 2) plus an LLM auditor (AlignmentCheck). The authors' combined AgentDojo ASR is 1.75% against 17.6% undefended. The Q4 adaptive results say that number would fall under a stronger attacker.
- Classifiers are fooled by content that looks like data, and LLM judges by content that looks like a plausible instruction. Both need the adaptive evaluation in Q4.
- For a tighten-only supervisor, a classifier that can only raise a hold flag is a good fit. A false positive costs a missed trade. A false negative is caught by the deterministic gate in Q1.

### Gaps
- No independent head-to-head of LlamaFirewall, Llama Guard 4 and ShieldGemma on prompt injection under the same protocol.
- No measured ShieldGemma-in-NeMo latency.
- The Constitutional Classifiers 2026 follow-up figures are from a third-party summary.

---

## Q4. Adaptive-attack evaluations: what the field has learned

### Takeaway
The main 2025–2026 result is that most published defences report near-zero attack success only against fixed attack sets. When the attacker adapts, the numbers are much worse. In the most cited study, 12 defences were all bypassed. The one defence with the least loss (PIGuard, 71%) was still broken.

### Cited Findings
- "The Attacker Moves Second" (Nasr, Carlini, Sitawarin, Schulhoff et al., arXiv 2510.09023, Oct 2025): 12 recent jailbreak and prompt-injection defences were bypassed with attack success above 90% for most. The attackers used gradient descent, reinforcement learning, random search, and human-guided exploration. Most of those defences had originally reported near-zero ASR. [arXiv 2510.09023](https://arxiv.org/abs/2510.09023)
- Per-defence adaptive ASR from the paper's HTML text (extracted by a fetch tool, so verify against the table before quoting): spotlighting above 95%; prompt sandwiching above 95%; RPO 98% (RL) and 96% (gradient); circuit breakers 100% (RL); StruQ succeeded in every case; MetaSecAlign 96% (search), against 2% static; Protect AI detector above 90%; PromptGuard above 90%; PIGuard 71%; Model Armor above 90%; Data Sentinel over 80% accuracy on redirected tasks; MELON 76% without defence knowledge, 95% with full knowledge. [arXiv 2510.09023 HTML](https://arxiv.org/html/2510.09023v1)
- The paper states that none of the 12 defences across four techniques is robust to strong adaptive attacks. Human red-teaming also succeeded. [arXiv 2510.09023 HTML](https://arxiv.org/html/2510.09023v1)
- MELON (a defence that runs the agent twice and compares tool calls) was bypassed by adaptive search finding conditional instructions that fire in one run and are suppressed in the other. [arXiv 2510.09023 abs](https://arxiv.org/abs/2510.09023)
- AutoDojo (arXiv 2606.15057, June 2026): ten defences on five target models (GPT-4o-mini, Gemini-2.5-Flash, Claude-Haiku-4.5, GPT-5.4-mini, DeepSeek-v4-Flash). The adaptive attack is black-box. Static benchmarks "significantly overestimate defence efficacy." Most defences either cost considerable utility or are insecure. Under-specified tasks are particularly vulnerable. [AutoDojo arXiv](https://arxiv.org/abs/2606.15057); [AutoDojo HTML](https://arxiv.org/html/2606.15057v3)
- AutoDojo table excerpts (GPT-4o-mini unless stated): PIGuard static 0.0% vs adaptive 28.0%; ProtectAI static 7.2% vs 15.4%; DataFilter static 12.6% vs 33.4%; DRIFT static 2.6% vs 6.4%; Progent adaptive 7.7%. On Claude-Haiku-4.5, DRIFT goes 0.3% static to 1.5% adaptive; no defence 0.3% static to 1.8% adaptive. Table was truncated in my fetch. [AutoDojo HTML](https://arxiv.org/html/2606.15057v3)
- Meta's Muse Spark safety report (arXiv 2606.12429, June 2026) replaces AgentDojo's fixed templates with an adaptive LLM attacker, which outperforms static attacks uniformly. [Muse Spark report](https://arxiv.org/pdf/2606.12429)
- Self-reported defence results on static AgentDojo: PromptArmor reports 0.00% ASR for PromptArmor-GPT-4.1 (arXiv 2507.15219). This is the authors' own figure against fixed attacks. [PromptArmor arXiv](https://arxiv.org/pdf/2507.15219)
- Blog claim, unverified: AgentDojo moved to deterministic state checks and dropped LLM judges on its leaderboard. [Search snippet, unconfirmed](https://current.tinyfish.ai/issue/27/practitioners-corner/article/14095/the-wrong-layer)

### What survived (adaptive evaluations)
- None of the 12 defences in 2510.09023 survived strong adaptive attacks.
- Among AutoDojo's ten, the visible numbers show that DRIFT and PIGuard keep adaptive ASR lowest on the models shown (1.5% on Claude-Haiku-4.5 for DRIFT; 4.6% on Gemini for PIGuard), at a utility cost. Not a survival claim; a relative ranking on the visible rows only.
- The system-level designs (CaMeL, Progent, ROPE) appear in AutoDojo but their adaptive ASR was not visible in my fetch. I cannot say they survived.

### Evaluated only against fixed attacks
- PromptArmor (0.00% on AgentDojo), LlamaFirewall (1.75% combined on AgentDojo), FIDES (zero on AgentDojo with policy checks on), and CaMeL's 77%/0-attack figures are all fixed-attack or design-argument results. Treat them as unproven against adaptive attackers.

### Inferences
- A supervisor evaluation should use an adaptive attacker with black-box feedback (AutoDojo-style). Static AgentDojo numbers are not evidence.
- The defences whose security argument is structural (FIDES/CaMeL-type, no untrusted text in the control path) do not depend on the attacker failing to find a string. That is why they are the only class that can plausibly claim robustness to adaptive attacks. This is an inference, not a tested result.
- The attempt budget matters. A single success is enough for a real attacker, so ASR at a fixed budget understates risk.

### Gaps
- No adaptive evaluation of an information-flow architecture (CaMeL, FIDES) was found.
- The full 2510.09023 table (per-defence original ASR) and AutoDojo's full Table 5 were not readable in the fetch.

---

## Q5. Failure attribution and root cause in multi-agent systems

### Takeaway
Automated failure attribution is still weak. The original Who&When benchmark found the best method identified the responsible agent 53.5% of the time but the failing step only 14.2%. Later work (AgenTracer, ICLR 2026) reports large gains, but the figures differ across summaries and must be checked in the paper's tables.

### Cited Findings
- Who&When (Zhang et al., arXiv 2505.00212, ICML 2025 Spotlight): best automated method reaches 53.5% accuracy on the responsible agent and 14.2% on the decisive step; some methods are below random. Reasoning models (o1, R1) were also not practically usable. [arXiv 2505.00212](https://arxiv.org/abs/2505.00212); [GitHub](https://github.com/ag2ai/Agents_Failure_Attribution)
- The repository describes 184 annotated failures, while the paper describes 127 systems. The counts differ by version. [GitHub](https://github.com/ag2ai/Agents_Failure_Attribution)
- AgenTracer (Zhang et al., arXiv 2509.03312, ICLR 2026): an 8B model trained on counterfactual replay and programmed fault injection (dataset TracerTraj). The abstract says AgenTracer-8B beats Gemini-2.5-Pro and Claude-4-Sonnet by up to 18.18% on Who&When, and gives 4.8–14.2% gains when feedback is applied to MetaGPT and MaAS. [AgenTracer arXiv](https://arxiv.org/abs/2509.03312); [ICLR poster](https://iclr.cc/virtual/2026/poster/10007726)
- Secondary summaries give conflicting AgenTracer numbers: 69.62% agent-level accuracy on automated benchmarks vs 58.73% for base Qwen3-8B, and a much lower step-level figure (20.68%) on the handcrafted split. These depend on setting and split. [Wizwand listing](https://www.wizwand.com/paper/68fa7b251e209131cea86d99); [Chatpaper summary](https://chatpaper.com/paper/185823)

### Inferences
- Attribution is useful for post-hoc audit of a supervisor's holds (why was an order held, and by which rule) but not reliable enough to drive live decisions.
- Counterfactual replay is the most promising method in the sources. For this supervisor, replaying a held action with trusted inputs only would show whether the untrusted input was decisive. That is a cheap test.

### Gaps
- No independent replication of AgenTracer's headline numbers was found.
- No attribution benchmark covers trading agents.

---

## Q6. Agent drift and memory poisoning

### Takeaway
Goal drift under contextual pressure is documented, and memory poisoning can be done with query-only access at high success rates. Detection methods are weak in the sources I found. A trading agent that keeps memory is exposed to both.

### Cited Findings
- Apollo/MATS goal-drift report (arXiv 2505.02709, 2025): in a simulated stock-trading environment, Claude 3.5 Sonnet kept goal adherence for up to 100,000 tokens, while GPT-4o mini drifted at every tested length. Drift severity correlated with the length of instrumental pursuit and with adversarial pressure. [arXiv 2505.02709](https://arxiv.org/pdf/2505.02709)
- Asymmetric Goal Drift in Coding Agents (arXiv 2603.03456, Mar 2026, ICLR 2026 workshop): goal drift correlates with value alignment, adversarial pressure, and accumulated context. Strongly held values still show non-zero violation under sustained pressure. [arXiv 2603.03456](https://arxiv.org/abs/2603.03456)
- Inherited Goal Drift (arXiv 2603.03258, Mar 2026): modern agents remain vulnerable to contextual pressure in the same trading setting. [arXiv 2603.03258](https://arxiv.org/abs/2603.03258)
- MINJA (Dong et al., arXiv 2503.03704): memory injection by query-only interaction. Early version: 98.2% injection success and 76.8% attack success. Later version: over 95% injection and over 70% attack success on most datasets. [arXiv 2503.03704](https://arxiv.org/html/2503.03704v2); [The Register](https://www.theregister.com/2025/03/11/minja_attack_poisons_ai_model_memory/)
- A 2026 replication on EHR agents (arXiv 2601.05504) reports MINJA at over 95% injection and 70% attack success under idealised conditions, and says realistic robustness is open. [arXiv 2601.05504](https://arxiv.org/html/2601.05504)
- AgentPoison: a secondary blog reports at least 80% attack success at under 0.1% poison rate. I could not check this against the original paper. [Vectorize summary](https://vectorize.io/articles/ai-memory-poisoning)
- Agent Security Bench, cited in a blog: highest average ASR 84.30%, with limited effect from current defences. Unverified. [Securityscientist blog](https://www.securityscientist.net/blog/rag-poisoning/)

### Inferences
- Drift is measurable with a trusted reference: compare the agent's stated mandate with its actual orders over time. The supervisor can do this without trusting the agent's narrative.
- Memory writes should carry provenance labels (Q1). A memory entry derived from a news item should not be allowed to set trading parameters later.
- Long, instrumental sessions increase drift. Session resets with a re-read of the trusted mandate are a cheap mitigation; I found no measured effect of this in the sources.

### Gaps
- No detection method for memory poisoning with measured precision/recall was found in this search.
- The drift studies use simulated environments and small models for the most part.

---

## Q7. Finance-specific attacks and benchmarks

### Takeaway
There are trading-specific attacks and at least one financial-agent safety benchmark with execution-grounded state. Both show high vulnerability, and both report that general-purpose defences transfer poorly.

### Cited Findings
- TradeTrap (arXiv 2512.02261, Shanghai AI Laboratory): stress-tests trading agents across market intelligence, strategy, portfolio/ledger, and execution. The prompt-injection module inverts directional cues in the decision prompt. Reversing cues collapses return and Sharpe while trade frequency spikes and position concentration approaches 100%. The authors conclude current trading architectures are systematically exposed. [TradeTrap arXiv](https://arxiv.org/abs/2512.02261); [Moonlight review](https://www.themoonlight.io/review/tradetrap-are-llm-based-trading-agents-truly-reliable-and-faithful)
- FinVault (arXiv 2601.07853): 31 regulatory case-driven sandbox scenarios with state-writable databases and compliance constraints; 856 attack cases and 107 benign cases. Reports up to 50% ASR for some models, and that general-purpose defences are largely ineffective. [FinVault arXiv](https://arxiv.org/html/2601.07853)
- Goal-drift results in simulated stock trading (Q6) apply here directly. [arXiv 2505.02709](https://arxiv.org/pdf/2505.02709)

### Inferences
- Trading-specific attacks often need no explicit instruction: they bias the decision inputs. This matches the context-driven influence concern in Q2, and defeats injection-string detectors.
- A supervisor check on the decision's sensitivity to directional cues (does the order flip when the sentiment is reversed?) is a cheap, specific test inspired by TradeTrap. This is my inference, not something the paper tests.

### Gaps
- Both finance benchmarks are recent and I did not find adaptive-attacker evaluations of defences on them.
- Finance-agent defence numbers were not available from the sources I could read.

---

## Synthesis: what this implies for a tighten-only supervisor

1. Deterministic provenance gate first. Actions whose price, size, symbol, venue, or timing depends on untrusted-labelled data are held. This is the only class with a structural argument against adaptive attackers (Q1, Q4 inference). Evidence it works is still on fixed AgentDojo attacks.
2. The supervisor's judgement model should never read raw untrusted text. If it must see news, it sees labelled quotes and is asked only whether the action is consistent with the trusted mandate. Its security assumption should be tested adaptively (Q2, Q4).
3. Use cheap classifiers only as hold-raisers. PromptGuard 2 gave the best published classifier numbers in this search, with the caveat that it was broken under adaptive attack in 2510.09023 (PromptGuard above 90%).
4. Monitor the decision's sensitivity to the narrative (TradeTrap-style cue reversal, Q7) and check drift against the mandate over time (Q6). Both are cheap and do not rely on reading the agent's reasoning, which Q2 suggests is the weaker signal.
5. Evaluate the whole supervisor with an adaptive, black-box attacker with a fixed attempt budget (AutoDojo-style), not with AgentDojo fixed attacks alone (Q4).
6. Counterfactual replay (Q5) is the practical audit tool: re-run a held action with trusted inputs only.

## Overall gaps
- No single 2026 paper evaluates a tighten-only supervisor, or a trading-supervisor design, under adaptive attack.
- ShieldGemma and Llama Guard 4 lack robustness numbers in this search.
- Several numbers here come from secondary summaries or fetch-extracted tables. Those are flagged inline and should be checked against the source before citing.
