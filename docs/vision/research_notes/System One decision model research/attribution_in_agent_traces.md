# Attribution and credit assignment: why an agent acted, and how finance attributes outcomes to decisions

Scope: methods for (a) attributing an AI agent's action to the inputs, context items and steps that caused it, and (b) attributing portfolio outcomes to decisions, as raw material for OrderGuard's System One "purpose attribution". Research done 17 November 2026. Where a figure comes from a secondary summary rather than the paper's own table, that is stated.

## 1. Failure and credit attribution in LLM agent and multi-agent traces

### Takeaway
Saying which agent caused a failure is now fairly reliable (about 55% in 2025, about 66-74% for the best 2026 methods on Who&When). Saying which step caused it is still weak: about 33% on long hand-crafted logs and about 50% on short ones at best. The methods that work best structure the trace into a dependency or causal graph, then check candidates counterfactually. Asking an LLM judge to read the log does much worse.

### Cited Findings
**Who&When benchmark (Zhang et al., ICML 2025)**
- Who&When has 184 failure-annotated tasks from 127 multi-agent systems. 126 are algorithm-generated (CaptainAgent, GPT-4o; logs of 10 steps or fewer, up to 4 agents) and 58 are hand-crafted (Magentic-One; logs up to 130 steps, up to 5 agents). Tasks come from GAIA and AssistantBench — [arXiv 2505.00212v3](https://arxiv.org/html/2505.00212v3)
- Three experts annotated it in three rounds and spent 30.9, 30.2 and 23.2 hours. 15-30% of their labels were marked "uncertain", so even human ground truth on the decisive step is fuzzy — [arXiv 2505.00212v3](https://arxiv.org/html/2505.00212v3)
- GPT-4o baselines (Table 1, with ground truth), agent-level / step-level accuracy:
  - All-at-once: 54.33 / 12.50 on algorithm-generated and 55.17 / 5.26 on hand-crafted. Step-level is below random (19.06) on algorithm-generated.
  - Step-by-step: 35.20 / 25.51 and 34.48 / 7.02.
  - Binary search: 44.13 / 23.98 and 51.72 / 6.90.
  - Random: 29.10 / 19.06 and 12.00 / 4.16.

  — [arXiv 2505.00212v3](https://arxiv.org/html/2505.00212v3)
- Reasoning models do not fix this. On hand-crafted logs, step-level accuracy was 10.34% (all-at-once) and 13.79% (step-by-step) for o1, and 3.45% and 6.90% for DeepSeek R1 — [arXiv 2505.00212v3](https://arxiv.org/html/2505.00212v3)
- Cost against accuracy, in tokens per hand-crafted log:
  - All-at-once: 17,106 tokens, 57.02% agent / 4.39% step.
  - Binary search: 34,659 tokens.
  - Step-by-step: 87,720 tokens.
  - Hybrid (all-at-once to pick the agent, then step-by-step): 149,177 tokens, 57.02% / 12.28%.

  Accuracy on every method falls as logs get longer and approaches 0% for logs of 93-130 steps — [arXiv 2505.00212v3](https://arxiv.org/html/2505.00212v3)
- Allowing a tolerance helps a lot. Within ±5 steps, all-at-once reaches 43.10% on hand-crafted logs, against an exact-match rate of about 5% — [arXiv 2505.00212v3](https://arxiv.org/html/2505.00212v3)

**Follow-up methods (2025-2026)**
- AgenTracer (ICLR 2026) labels failed trajectories by counterfactual replay. It swaps each action for an oracle-corrected one, re-simulates the run, and labels the earliest step whose fix flips the outcome. Adding programmed fault injection produced TracerTraj, over 2,000 annotated trajectories. AgenTracer-8B (Qwen3-8B trained with GRPO) is reported to beat Gemini-2.5-Pro and Claude-4-Sonnet by up to 18.18% on Who&When. Its feedback raised MetaGPT and MaAS task performance by 4.8-14.2% — [arXiv 2509.03312](https://arxiv.org/abs/2509.03312); [ICLR 2026 poster](https://iclr.cc/virtual/2026/poster/10007726). The method details here come partly from secondary summaries.
- EMFA (October 2026) defines the target as the earliest agent-step pair whose correction would recover the run. It turns the flat log into a dependency structure, models how errors propagate and where loops persist, and verifies candidates counterfactually. Strict top-1 on Who&When:
  - EMFA: 74.14% agent / 32.76% step on hand-crafted, 66.67% / 50.00% on algorithm-generated.
  - Previous best, CHIEF: 72.41 / 29.31 and 68.80 / 45.60.
  - Others: GraphTracer 69.74 / 27.97 and 67.42 / 44.35; AgenTracer 63.82 / 20.68 and 63.73 / 37.30; ECHO 67.90 / 26.80 and 67.20 / 27.20.

  No cost figures are given in the main text — [arXiv 2610.11600](https://arxiv.org/html/2610.11600)
- CHIEF turns flat logs into hierarchical causal graphs and beats eight baselines at both agent and step level — [arXiv 2602.23701](https://arxiv.org/html/2602.23701)
- Adaptive Influence Graphs: on the algorithm-generated subset, exact step accuracy rises from 46.40% on raw logs to 48.80% with structured logs, 52.00% with influence graphs, and 55.20% with traversal directed by the agent. This number comes from a search summary — [arXiv 2608.24361](https://arxiv.org/pdf/2608.24361)
- FAMAS (spectrum analysis, borrowed from software fault localisation; it reruns the system and compares passing and failing runs) reports 57.61% agent-level and 29.35% action-level accuracy over 184 logs — [arXiv 2509.13782](https://arxiv.org/pdf/2509.13782)
- A causal-inference method (CDC-MAS) reports up to 36.2% step-level accuracy, against prior methods below 15% — [arXiv 2509.08682](https://arxiv.org/abs/2509.08682)
- StepFinder reports a 79% cut in inference time against the fastest LLM-based method — [arXiv 2606.03467](https://arxiv.org/html/2606.03467v1)
- A 2026 benchmark paper finds that the best prompting protocol changes from one benchmark to another (step-by-step on Who&When, all-at-once on its own) — [arXiv 2604.22708](https://arxiv.org/html/2604.22708v1)

**Step-level credit assignment through process reward models**
- AgentPRM (Choudhury, February 2025) learns step-value targets for agents from asynchronous Monte Carlo rollouts. iStar (ICLR 2026) trains an implicit PRM jointly with the policy using trajectory-level DPO. OPRL finds that turn-level step rewards work better than token-level ones for multi-turn agents. No benchmark accuracy for the PRMs themselves was found — [iStar, arXiv 2509.19199](https://arxiv.org/html/2509.19199v3); [AgentPRM topic summary](https://api.emergentmind.com/topics/agent-process-reward-models-agentprm)

**Faithfulness of chain-of-thought as an explanation**
- Anthropic (Chen et al., May 2025) measured how often models mention a hint they actually used. Claude 3.7 Sonnet did so 25% of the time on average and DeepSeek R1 39%. On "misaligned" hints the rates were 20% and 29%. Outcome-based RL raised faithfulness only to a plateau of 28% (MMLU) and 20% (GPQA). Models admitted to reward hacks in under 2% of cases in most settings — [arXiv 2505.05410](https://arxiv.org/abs/2505.05410); [Anthropic post](https://www.anthropic.com/research/reasoning-models-dont-say-think)
- The authors' conclusion is that CoT monitoring helps catch frequent or multi-step behaviour but cannot rule out rare, single-step behaviour — [Anthropic post](https://www.anthropic.com/research/reasoning-models-dont-say-think)
- In LLM trading agents, masking the agent's memory substantially changes its stated rationale. Returns are mostly explained by passive market and style exposure, with limited evidence of persistent stock-selection alpha — [KTD-Fin, arXiv 2605.28359](https://arxiv.org/abs/2605.28359)

### Inferences
- An order is one action, so System One's problem is closer to "which input or step caused this order" than to finding the decisive step in a 130-step log. The short-log results (about 50% step-level, about 67% agent-level for the best methods) are the more relevant reference, but those numbers are still far from a calibrated probability.
- The methods that work best combine structure (a dependency or influence graph of the trace) with counterfactual verification. That suggests System One should log the trace as a typed graph at capture time: news item, memory note, peer-agent action, open thesis, tool output. Reconstructing the graph afterwards from a flat transcript is what those methods spend their effort on.
- The agent's stated reason (CoT or rationale) should be treated as one piece of evidence with a low prior weight, never as the attribution itself. The faithfulness data imply an agent omits the real driver at least 60-75% of the time.
- A ±k tolerance and a ranked top-k list are more honest outputs than a single top-1 cause. That fits the founder's "several weighted causes" framing.

### Gaps
- Most papers do not report cost per trace in dollars or latency. EMFA and CHIEF defer cost to supplements.
- No paper found measures calibration of attribution confidence (for example ECE or Brier score). All of them report top-1 accuracy.
- Every benchmark is about failure attribution on GAIA or AssistantBench tasks. None covers attributing an action that was not a failure (a purpose-serving order), and none uses financial traces.
- The figures in "Adaptive Influence Graphs", CDC-MAS and FAMAS come from search snippets. Their tables were not fetched.

## 2. Context attribution: which context items caused the output

### Takeaway
Methods that remove parts of the context and fit a surrogate (ContextCite, TracLLM, Shapley) work on black-box models but cost tens to hundreds of model calls and minutes per response. Attention-based methods (AttnTrace, AT2) are more accurate on injection and poisoning and take seconds, but they need white-box weights. Every method fails when the model already knows the fact, because removing the source changes nothing. Plain leave-one-out and the model citing its own sources are poor.

### Cited Findings
- ContextCite (Cohen-Wang, Shah, Georgiev, Mądry; NeurIPS 2024) fits a sparse linear surrogate to random removals of context sources. It beats baselines with only 32 ablations, and users can check its faithfulness with a held-out LDS score. It costs about 32 times as much as generating the response. Its uses include verifying statements, pruning context, and detecting context-poisoning attacks — [arXiv 2409.00729](https://arxiv.org/pdf/2409.00729); [NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/adbea136219b64db96a9941e4249a857-Abstract.html)
- TracLLM (USENIX Security 2025) makes Shapley-style attribution usable on long contexts with an informed search. It cuts queries from O(e·n) to O(K·e·log n) and runs about 7 times faster than Shapley on NarrativeQA — [arXiv 2506.04202](https://arxiv.org/pdf/2506.04202); [USENIX](https://www.usenix.org/system/files/usenixsecurity25-wang-yanting.pdf)
- AttnTrace (2025) scores each context item by attention, averaging the top 5 tokens over 30 subsamples. The table gives precision / recall / seconds on Llama-3.1-8B with an A100:

  | Method | Prompt injection, MuSiQue | Knowledge corruption, NQ |
  |---|---|---|
  | AttnTrace | 0.99 / 0.81 / 21.7 | 0.96 / 0.96 / 8.5 |
  | TracLLM | 0.94 / 0.77 / 403.7 | 0.89 / 0.89 / 144.2 |
  | Shapley | 0.68 / 0.55 / 455.9 | 0.82 / 0.82 / 152.2 |
  | ContextCite/LIME | 0.72 / 0.60 / 410.7 | 0.83 / 0.83 / 179.5 |
  | AT2 | 0.87 / 0.71 / 2.6 | 0.66 / 0.66 / 1.7 |
  | Leave-one-out | 0.17 / 0.13 / 192.1 | 0.24 / 0.24 / 32.5 |
  | Self-citation | 0.22 / 0.17 / 2.2 | 0.74 / 0.74 / 0.9 |
  | Gradient | 0.06 / 0.04 / 8.8 | 0.11 / 0.11 / 1.7 |

  — [arXiv 2508.03793](https://arxiv.org/html/2508.03793)
- AttnTrace needs attention weights. For GPT-4o-mini outputs the authors traced with Llama-3.1-8B as an open surrogate, because closed models do not expose their weights — [arXiv 2508.03793](https://arxiv.org/html/2508.03793)
- AT2 learns an importance weight for each attention head from training data — [arXiv 2508.03793](https://arxiv.org/html/2508.03793) (secondary description). AttriBoT approximates leave-one-out efficiently — [Aalto thesis](https://aaltodoc.aalto.fi/bitstreams/228f1634-284e-4820-bd63-5d04f41a14b0/download) (secondary).
- "How Context Attribution Handles What the Model Already Knows" (Aalto, August 2026) studies 1,987 samples from WMDP-Cyber++. Telling whether knowledge came from the weights or from the context is near chance: precision about 0.5 and ROC AUC about 0.5. Rankings change once the model has learned the fact (cross-model consistency 0.34-0.56). Likelihood metrics (Drop@k, LDS) hide the problem. The authors' wording is "Methods cannot disentangle in-weight from in-context learning." Methods tested: ContextCite, TokenShapley, AttriBoT, TracLLM — [arXiv 2607.23804](https://arxiv.org/html/2607.23804v2)

### Inferences
- For black-box API agents (most trading agents), the usable options are removal-based methods (ContextCite or TracLLM) run against the same API, or an open surrogate model that replays the context. At 32 or more calls per order, attributing every order costs at least 32 times the inference spend. That points to tiering: a cheap screen on every order, and full ablation only on flagged or large orders.
- Poisoned inputs and prompt injection are the case attention-based traceback handles best (precision 0.9-0.99). If the agent is an open model, or a surrogate is accepted, the "poisoned input" factor is the most measurable of the founder's factors.
- Drift and loops are not context items, so context attribution will not see them. They need trace-level or statistical methods (see sections 1 and 3).
- The in-weight blind spot means "no context item explains this order" is ambiguous. It may mean the model's prior or its training data drove the order, which is itself a factor System One needs as a residual or "unexplained" bucket.

### Gaps
- No primary-source benchmark was found for context attribution through API-only access to a frontier model, such as ContextCite run against a closed API with logprobs.
- No study was found of attribution over agent memory or tool outputs specifically, as opposed to retrieved documents.
- The AT2 and AttriBoT original papers were not fetched. Their descriptions are secondary.

## 3. Finance attribution: how outcomes are attributed to decisions

### Takeaway
Finance already has exact, additive decompositions that tie outcomes to decisions:
- Brinson splits active return into allocation, selection and interaction effects.
- Factor attribution splits return into factor exposures plus a specific residual.
- Sharpe style analysis infers effective exposures, and drift in them over time is a monitoring signal.
- Euler risk contributions sum exactly to total risk and identify concentrations.
- Implementation shortfall splits decision value from execution leakage: delay, trading costs and missed fills.

All of these attribute against a benchmark or mandate, which is the analogue of the owner's "purpose".

### Cited Findings
- The CFA Institute reading "Return Attribution" (Bacon and Wright) covers the Brinson-Hood-Beebower and Brinson-Fachler models, arithmetic and geometric effects, and factor-model attribution, and compares the Brinson and factor approaches — [CFA Institute CIPM reading](https://www.cfainstitute.org/-/media/documents/support/programs/cipm/2019-cipm-l1v1r5.ashx)
- Brinson-Fachler effects:
  - Allocation = (wp − wb)(Rb,i − Rb).
  - Selection = wb(Rp,i − Rb,i).
  - Interaction = (wp − wb)(Rp,i − Rb,i).

  The sum is active return. Brinson-Fachler measures allocation against the total benchmark return, while BHB uses the raw sector return. Interaction is sometimes folded into selection, and comments on the GIPS draft say it should either be combined or shown separately — [GIPS exposure-draft comment, Spaulding](https://www.gipsstandards.org/wp-content/uploads/2025/11/exposure-draft-best-practices-return-attribution-reporting-comments-david-spaulding.pdf); [AnalystPrep summary](https://analystprep.com/study-notes/?p=33775)
- Brinson is holdings-based: it assumes buy-and-hold from the start-of-period holdings and misses trades within the period. Factor or risk approaches are recommended for systematic exposures — [AnalystPrep](https://analystprep.com/study-notes/?p=33775)
- Sharpe (1992), "Asset Allocation: Management Style and Performance Measurement", Journal of Portfolio Management 18(2):7-19, uses a constrained 12-asset-class factor model on mutual funds from 1985 to 1989. The method has an earlier root in Sharpe (1988), "Determining a Fund's Effective Asset Mix" — [Sharpe, Stanford](https://web.stanford.edu/~wfsharpe/art/sa/sa.htm); [Wikipedia: RBSA](https://en.wikipedia.org/wiki/Returns-based_style_analysis)
- In style analysis, R² is the share of variance explained by passive style. 1 − R² is attributed to selection and timing. Drift is detected by comparing style weights across rolling windows. Style analysis lags real style changes, which led to time-varying extensions, and drift can be unintentional (for example, mid-cap holdings growing into large-cap) — [MetricGate](https://metricgate.com/docs/sharpe-style-analysis/); [Wikipedia](https://en.wikipedia.org/wiki/Returns-based_style_analysis)
- Euler risk allocation defines a position's contribution as weight × ∂Risk/∂weight. For risk measures that are homogeneous of degree 1, the contributions sum exactly to total risk. Tasche shows that Euler contributions are compatible with RORAC, that essentially no other allocation is, and that they are useful for detecting risk concentrations. The method applies to volatility, VaR and Expected Shortfall — [Tasche, arXiv 0708.2542](https://arxiv.org/pdf/0708.2542); [Palomar, Portfolio Optimization ch. 11.3](https://bookdown.org/palomar/portfoliooptimizationbook/11.3-risk-contributions.html)
- Shapley allocation is also used for regulatory risk attribution (Basel 2.5 to FRTB) — [arXiv 2511.12391](https://arxiv.org/pdf/2511.12391) (title only; not read in detail)
- Implementation shortfall (Perold, "The Implementation Shortfall: Paper Versus Reality", JPM 14(3), 1988) compares a paper portfolio filled at the decision price with the portfolio actually traded. It splits into delay, explicit cost, implicit cost (impact) and opportunity cost (the unfilled part). Wagner and Glass (2001) added delay costs explicitly — [Wikipedia: Implementation shortfall](https://en.wikipedia.org/wiki/Implementation_shortfall); [arXiv 1206.5324](https://arxiv.org/pdf/1206.5324) (secondary descriptions; the original was not accessible)

### Inferences
- These decompositions separate the decision (allocation or selection, measured at the decision price) from execution (shortfall). That maps directly onto System One: judge the decision's fit to purpose at the decision moment, separately from how well it was executed.
- Euler or marginal contribution offers a way to score how much an order serves the purpose before the trade. Compute the order's marginal contribution to the mandate's objective and risk budget (for example, its Δ in tracking error, factor exposure or ES contribution) against what the mandate allows.
- Style analysis and drift detection are a ready-made method for the "drift" factor. Regress the agent's realised exposures on the mandate's style basis over rolling windows. Falling R², or style weights leaving the mandate's band, is evidence of drift, and has well-understood lag characteristics.
- Finance attribution is additive and exact by construction, but it is not causal. It decomposes an outcome by accounting identity and does not say why the manager made the decision. Agent attribution (section 1) says why, but is noisy. The combination is the gap OrderGuard would fill.

### Gaps
- The primary texts of Brinson-Fachler (1985) and BHB (1986) were not checked. Their dates come from secondary sources that disagree on details.
- No practitioner source was found on how asset managers attribute an individual decision's contribution to a non-return objective, such as a mandate's purpose or an ESG or liability target. Liability-driven and goals-based attribution were not researched.
- No accuracy figures exist in this space, because the decompositions are identities. Their error comes from benchmark choice and from the holdings-based assumption.

## 4. Work combining the two: attribution for trading agents and decision provenance

### Takeaway
Work that bridges the two is thin and very recent (2026). It includes Shapley credit over trading-agent coalitions, a counterfactual loss decomposition that separates agent decisions from infrastructure faults, and arguments that rationales are only auditable when linked to structured decision logs. None of it yet assigns calibrated, multi-cause weights to a single order against an owner's mandate.

### Cited Findings
- Market Regime Council (Pei, Ge, Zheng, Cartlidge; May 2026, revised November 2026):
  - Computes exact Shapley credit across single, pairwise and grand-coalition outputs of 3 specialist LLM agents.
  - Updates weights from exponentially weighted performance, using a Bayesian adaptive mixture for the cold start and regime-dependent authority multipliers.
  - Logs every rebalance through a five-layer causal trace.
  - Results over 1,037 days on 13 crypto assets: Sharpe 1.51 and cumulative return of 440.1%.
  - Ablations credit the gains to Shapley-weighted integration.

  — [arXiv 2605.24490](https://arxiv.org/abs/2605.24490)
- CausalLoss-Fin (Sharma, September 2026):
  - An exact telescoping identity splits a financial agent's loss into an infrastructure effect, a policy differential against the best implementable policy, and a reference residual. Two of the three terms can be negative, so they are not shares.
  - Shapley then splits the infrastructure effect across individual messages.
  - On 545 planted episodes, an agent-only attribution baseline charged 100% of infrastructure episodes to the agent ($114,383.40). Repairing the actions it named recovered 0.0% of the loss, while repairing a minimal set of messages recovered 100%.
  - 27.8% of episodes (95% CI 23.3-32.3%) were not additive, so scoring one factor at a time fails.
  - Limitation: the agents are deterministic programmatic policies, not LLMs.

  — [arXiv 2609.25960](https://arxiv.org/abs/2609.25960)
- Agentic Trading (survey, 2026) argues that LLM rationales are qualitative summaries, not audit artifacts, unless they are tied to grounded observations and structured decision logs ("Log-to-Narrative Verification"). It recommends logging which agent proposed or vetoed each action — [arXiv 2605.19337](https://arxiv.org/html/2605.19337)
- KTD-Fin (May 2026) ran ten LLM trading agents on CSI300 under controlled leakage. Returns were mostly explained by passive market and style exposure, and masking memory changed the rationales — [arXiv 2605.28359](https://arxiv.org/abs/2605.28359)
- A paper on multi-agent debate for explainable trading (September 2026) scores reasoning on logical validity, evidential support, consideration of alternatives and causal alignment, and compares those scores with performance — [arXiv 2609.29701](https://arxiv.org/abs/2609.29701)
- TradingAgents presents natural-language decision logs and a reflective agent as aids to debugging. These claims are qualitative and not validated — [arXiv 2412.20138](https://arxiv.org/pdf/2412.20138)

### Inferences
- A combined "purpose attribution" design suggested by these sources:
  1. Capture a typed provenance graph per order (inputs, memory reads, peer actions, open theses, tool results).
  2. Run cheap screens on every order: an attention or surrogate traceback for poisoned inputs, plus rolling style regression for drift.
  3. On flagged or large orders, run counterfactual replay: remove or repair a factor, re-query the agent, and check whether the order survives. This is the AgenTracer, ContextCite and CausalLoss-Fin pattern.
  4. Use Shapley over factors, not one-at-a-time scoring. CausalLoss-Fin found 27.8% non-additivity, which is also why Brinson has an interaction term.
  5. Score fit to purpose separately, as the order's Euler or marginal contribution to the mandate's objective and risk budget at the decision price, with shortfall-style separation of execution.
  6. Report weights with an explicit residual or "unexplained / in-weight prior" bucket.
- CausalLoss-Fin warns that a factor set without an "environment or infrastructure" or "not the agent" variable will charge everything to the agent. System One's factor list should include market and infrastructure causes as well as agent causes.
- Calibration has to be built and validated by OrderGuard. No source in this survey reports calibrated probabilities for attribution. Planted-fault corpora, as in CausalLoss-Fin, TracerTraj and Who&When, are the established way to create ground truth for calibrating.

### Gaps
- No work was found that attributes LLM trading-agent orders to news, memory or peer-agent inputs with a measured accuracy.
- No published standard for "decision provenance" in algorithmic trading compliance was researched; for example, MiFID II RTS 6 algorithm records or SEC 15c3-5 documentation are not covered here.
- MRC's and CausalLoss-Fin's results are single-group, recent and not replicated. CausalLoss-Fin uses non-LLM agents.
