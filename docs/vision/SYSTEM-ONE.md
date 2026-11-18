# System One: what it is, and why it is a different kind of model

Status: exploration, 2026-11-19. Nothing here is built beyond the baseline in [JUDGEMENT.md](JUDGEMENT.md).

This document follows the problem from the failure inward, instead of starting from a model. The evidence comes from six research threads. Their notes are in [research_notes/System One decision model research/](research_notes/System%20One%20decision%20model%20research/), and their synthesis is in [reports/](reports/).

A correction first. The earlier vision work (RESEARCH.md) researched the state engine, regulation, drift and herding. It did not research decision models, attribution, purpose representation or how such a model would be trained. This pass fills that gap.

## 1. Start from what actually goes wrong

| What happens | Measured | Source type |
|---|---|---|
| A capable model that never drifted on its own drifted once it continued another model's corrupted history, in a simulated trading environment | Drift appeared only with the inherited context | Peer-reviewed (Arike et al., AIES 2025) |
| A trading agent fed a false picture of its own positions went from +0.91% to −61% | 92% drawdown, 6.5× the intended leverage, no internal alarm | Preprint (TradeTrap) |
| Prompt injection concentrated an agent's book into one stock | 99.98% of the portfolio; trades rose from 47 to 391 | Preprint (TradeTrap) |
| Memory injection through ordinary queries | 98.2% injection success, 76.8% attack success | Peer-reviewed (MINJA) |
| Agents' stated reasoning hides what drove them | A hint the model used was mentioned 25% of the time (Claude 3.7) and 39% (R1) | Lab research |
| Finding the step that caused a multi-agent failure | 5–25% for GPT-4o in 2025; about 33–50% for the best 2026 methods | Benchmark (Who&When and successors) |
| Brokers' agent controls | Per-order and per-account limits only; nothing judges a sequence of trades | Broker documentation |

**Three conclusions:**

- **The founder's thesis holds.** The reasoning can be locally right while the context under it is already wrong, and nothing inside the agent notices.
- **Explanations cannot be the evidence.** An agent's own explanation is unreliable, and post-hoc attribution from traces is weak.
- **Every guardrail and payment standard found judges one action at a time.** Nobody judges a delegation over time.

## 2. First reframe: judge the delegation, not the market

**The trap.** "Is this a good trade?" is the wrong question. Kahneman and Klein (2009) showed that fast, intuitive judgement is trustworthy only where two conditions hold:

1. the environment is regular;
2. feedback is quick.

Their example of where it fails is stock picking. A model asked to judge trades inherits that failure, whatever its size.

**The reframe.** Ask a question about the *owner* instead of the market:

> **Would this owner endorse this action, given what the agent legitimately knew when it acted?**

This question meets both of Kahneman and Klein's conditions.

- **The environment is regular.** An owner's purpose and tolerances change slowly, and they are partly written down in the signed contract.
- **Feedback is quick.** Every held order the owner approves or rejects is a label, and it arrives in minutes, not quarters.

So System One is a model of the principal, not of the market. Its target is the *endorsement probability*. This target has a ground truth, the owner's own decision when asked, whereas "serves the purpose" in the abstract has none.

**What this reframe buys:**

- **It is calibratable.** Endorsement is a yes/no event that is observed again and again, so Brier score, calibration error and conformal coverage all have real data behind them.
- **It turns the review queue into the training signal.** Every hold teaches System One about this owner, so the queue is no longer only a safety cost.
- **It decides when to ask.** Ask the owner when the expected cost of acting on a stale estimate of their wishes exceeds the cost of interrupting them, which is the trade-off Capponi et al. formalise for robo-advisers. The output is a principled interruption policy, not a fixed threshold.
- **It keeps OrderGuard honest.** It never claims to know whether a trade will make money. It claims to know whether the owner would have signed it.

**Caveats:**

- Owners can endorse bad trades. That is their right, and profitability is not OrderGuard's job.
- Labels exist only for the orders that were held, so they are biased. A small random audit slice of allowed orders, shown to the owner after the fact, corrects this (off-policy evaluation, as fraud teams do).

## 3. Second reframe: every agent-native failure is a shape in the "why graph"

The harness can record, *at decision time*, the graph of why each order exists. This is not reconstructed afterwards from the agent's text. The nodes are:

- every input read (news, filings, prices, tool results);
- every memory note read or written;
- every peer action observed;
- every thesis opened, with its evidence hashes;
- the typed intent;
- the order.

Edges say what was read before what was written. This is cheap because the harness sits on every tool call and every memory access.

With that graph, the failures we have been treating as separate detectors become one representation:

| Failure | Its shape in the graph |
|---|---|
| Poisoned input | Much of the order's weight traces to a root that is untrusted or unverified |
| Herding | Orders from many agents trace to the *same* root, often one unverified source |
| Drift | Over time, weight moves from theses inside the signed purpose to causes outside it |
| Loop | The order's weight traces mainly to the agent's own earlier actions: a cycle |
| Corrupted context | Weight sits on items whose provenance is broken: notes that resolve to nothing, quotes that do not match their source |
| Compromised tool | An order with no path back to any typed intent the runtime wrote |
| Legitimate adaptation | Weight moves to a *new* thesis whose evidence is fresh, verified and inside the purpose |

The last row matters most. "Telling legitimate adaptation from abandonment" was the hardest open question in JUDGEMENT.md. In the graph it becomes concrete: did the change of course arrive through a new, verified thesis, or did it just appear?

**What becomes possible:**

- The signals in the simulation build so far (style distance, CUSUM, root-source counting, loop windows) each become a view of the same graph. The graph is what is new.
- Explanations can point at nodes ("62% of this order traces to headline H, single root, unverified") instead of at the agent's prose.

## 4. Third reframe: purpose attribution, borrowing from finance

Finance already has an exact discipline for "how much did each decision contribute to the objective": performance attribution.

- **Brinson-Fachler** splits active return into allocation, selection and an interaction term.
- **Euler risk contributions** sum exactly to total risk.
- **Implementation shortfall** separates the value of the decision from what execution cost it.

These tools are exact but say nothing about *why* a decision was made. The agent-trace methods are about *why*, but they are noisy. **Purpose attribution joins the two.**

For each order, split its fit with the owner's purpose into four effects:

| Effect | Question | Measured by |
|---|---|---|
| Evidence effect | Were the beliefs the agent acted on credible? | Provenance and verification of the roots in the graph |
| Reasoning effect | Does the action follow from those beliefs and the open thesis? | Coherence of intent, thesis and order |
| Objective effect | Given those beliefs, does the action move the book toward the owner's purpose? | The order's marginal contribution to the contract's objectives and risk budget, Euler-style |
| Interaction | What the three do together | Shapley values over the causes, because causes interact: CausalLoss-Fin found 27.8% of cases could not be split one cause at a time |

Two disciplines carry over from implementation shortfall.

- **Charge the agent only for what the agent did.** A loss caused by stale data, a broker fault or the market is not the agent's failure. CausalLoss-Fin found that a judge looking only at the agent blamed it for 100% of infrastructure-caused losses.
- **Keep a bucket for "unexplained / prior knowledge".** Attribution fails when the model already knew the fact, so forcing every unit of weight onto a visible node would lie.

This is what the founder described: assigning calibrated weights to the several causes behind an action, measured against the purpose of the original portfolio. In this form it has an exact accounting frame from finance, causal weights from the agent graph, and a calibrated top-level probability.

## 5. System One works at six levels

One family of models, asked typed questions at different levels and tempos. Every level can only tighten.

| Level | Question | Tempo | What it can tighten |
|---|---|---|---|
| 1. Signal | Is this input credible, and does this quote match its source? | On read, milliseconds | Mark the input untrusted, and so everything it feeds |
| 2. Thesis | Would the owner endorse this thesis, given its evidence? | On thesis change, seconds | Withhold the thesis's risk budget until judged |
| 3. Action | Does this order follow from a judged, still-valid thesis and its intent? | On the order path, microseconds (a cached verdict plus a code check) | Hold the order |
| 4. Trajectory | Is this agent drifting, looping, or acting on corrupted context? | Continuous, over minutes | Shorten the lease, shrink the budget, re-inject the purpose |
| 5. Swarm | Are "independent" agents in fact driven by one root? | Continuous | Cap the combined exposure to that root |
| 6. Book | Taken together, do all open theses still describe what the owner signed? | Daily, and on regime change | Ask the owner; propose de-risking for them to sign |

Level 3 is why System One never slows the order path. The judgement happens at level 2, when a thesis is formed. An order only has to prove, in code, that it belongs to a thesis that has already been judged.

**The hole in "judge theses, not orders".** Orders inside a valid thesis can still add up to harm. One example is overtrading within the caps: in a live competition, one model paid about 13% of its capital in fees. So turnover, fee drag and cancel ratios are checked in code on every order, per thesis, whatever the thesis verdict.

## 6. Why it is a different kind of model

| | General decision model | System One |
|---|---|---|
| Input | A state as text | A typed graph: the contract, the theses, the provenance graph, positions. Agent-written text reaches it only through code extraction and a quarantined reader |
| Question | Any question | A fixed set of typed questions about one delegation |
| Output | A probability per answer | A calibrated endorsement probability, weights over graph nodes, and a conformal bound on the error rate of what it lets pass |
| Whom it models | The world | One owner, starting from a population prior and adapted to that owner |
| Authority | Its answer is the decision | Its answer can only tighten |
| Ground truth | Labels for general tasks | Causes planted in the simulator, counterfactual replays, and the owner's own decisions |

**Why it reads graphs and not text.** A judge that reads the agent's text can be injected by it: superficial tokens alone fool frontier judges up to about 90% of the time. So System One's text reader sees only quarantined fields that code has already typed and checked.

**Architecture, from the research.** Code computes the graph and its features. A tabular or graph model scores the numeric structure. A small fine-tuned language model reads the quarantined text fields. An ensemble of five protects calibration under shift, and a conformal wrapper sets thresholds with a stated error rate. Escalations go to a frontier-model reviewer and then to the human.

## 7. How it learns

Four label sources. None of them is the model grading itself.

1. **Causes planted in the simulator.** The arena already plants poisoned feeds, colluders and loops, so we know the true cause of every order. That gives exact attribution labels, which no real-world dataset has. Ground truth for "why did this order happen" is the rarest thing in this field, and we can produce it at scale.
2. **Counterfactual replay.** Replay an escalated episode with one cause removed or corrected, and see whether the order survives. AgenTracer showed this produces training labels good enough for an 8B model to beat frontier models at failure attribution.
3. **Owner decisions.** Endorse or reject, from the review queue and from a random audit slice of allowed orders.
4. **A delegation constitution.** A written list of what owners do and do not delegate, used to generate adversarial data. This is the method of Anthropic's Constitutional Classifiers, which held up in about 3,000 hours of red-teaming with no universal jailbreak found.

**Training objectives:**

- **Supervised fine-tuning first.** It holds calibration better under shift than RL does.
- **Then RL with a *bounded* proper scoring reward** (Brier; RLCR cut calibration error from 0.37 to 0.03 in-domain).
- **Ensembles for shift.**
- **A conformal risk-control wrapper** for the guarantee, valid only while new data resembles the calibration data, so calibration drift is monitored live.

**What the research says not to expect.** RL mostly sharpens skills the base model already has. New detection skill has to come from the data: the planted causes and the counterfactual replays.

## 8. What being an agent taught us

The founder asked for this angle, and it earns its place. This conversation shows the same failure modes the design guards against.

- **Compaction loses the invalidation condition.** Long sessions are summarised to fit the context. In this project, a summary dropped nuance that later had to be recovered from the raw transcript. A trading agent's summary will drop "exit if the guidance is cut" long before it drops "we are long semiconductors". **Design rule:** the signed purpose and each thesis's invalidation condition live outside the agent's context, are never summarised, and System One judges against the records, not against the agent's memory of them.
- **Optimising the visible proxy.** An agent asked to produce something fills it, because "done" is easier to see than "right". The founder's criticism of page-filling is this failure. A trading agent optimises for orders placed or P&L, not the purpose. **Design rule:** never score an agent on activity; score its endorsement rate and the attribution of its orders.
- **Trusting an inherited context.** An agent continues from whatever it is handed; Arike et al. measured exactly this. **Design rule:** every inherited item carries provenance, and System One weights it by that provenance, not by the fact that it is present.
- **Self-justification.** An agent explains a decision after making it. **Design rule:** attribution comes from the graph recorded at decision time, never from the explanation.

## 9. How it joins the rest of OrderGuard

- **The hierarchy the founder set out.** Judgement informs risk, and risk informs authorization. Concretely: the thesis's endorsement probability scales down the risk budget reserved for it. A purpose-adjusted risk budget is ES budget × g(endorsement), and g can only shrink.
- **Authority still flows only downward.** Code is the only thing that says yes.
- **The harness is System One's sensor.** Without it there is no graph. This is the deeper reason the runtime harness (PRODUCT-SPEC.md, F11) comes first: it is security, and it is also the only place the graph can be recorded.

## 10. The moat

1. **The graph captured at decision time.** Brokers see orders. Guardrails see messages. Only the harness sees why. Rebuilding that afterwards from traces is the 5–33% problem in section 1.
2. **Planted-cause data at scale.** No public dataset labels the true cause of agent orders. Our simulator produces them in volume, and it improves as the arena grows.
3. **The endorsement flywheel.** Every owner's review decisions improve the population prior, the way Radar improves across Stripe's merchants. More owners mean better judgement for each one.
4. **Deployability.** A judge that can only tighten, inside signed authority, can go live where a judge that approves never could. That is what lets the data flywheel start.

## 11. What would prove it, and what would kill it

**Experiments, in order:**

1. **Graph without a model.** Record the graph in the arena and compute the section 3 shapes in code alone. Measure how much of drift, herding and poisoning they catch against the existing detectors. If the graph adds nothing over today's detectors, the reframe is wrong.
2. **Attribution accuracy against planted causes.** Compare three ways of ranking causes: the agent's own explanation, attention traceback through a stand-in model, and counterfactual replay. Report accuracy at finding the true cause, and its cost.
3. **Endorsement with simulated owners.** Build owners with known, slowly changing preferences. Measure calibration, how many questions it takes to learn an owner, and the curve of lead time against false holds.
4. **Shift.** Hold out attack families, simulator settings and time periods. Report Brier score and calibration error on every split, and check that answers stay consistent when options are reordered or the question is negated.
5. **Real owners in shadow mode.** Compare the endorsement prediction with what real reviewers actually decided.

**Kill criteria.** System One does not ship beyond the baseline if any of these hold:

- it fails to beat the deterministic monitor on lead time at the same false-hold rate on held-out families;
- calibration error exceeds 0.05 in distribution after recalibration;
- calibration error under adversarial shift is not reported, or misses the stretch target of about 0.10;
- there is any case in which it loosened a decision.

The target is split because no published method reaches 0.05 under shift. The best calibration-trained model goes from 0.03 in its own domain to 0.21 outside it.

**The name is a risk.** At least one decision-model vendor already calls its model "the first System One model", and another vendor's client library has a `system_one` call. Settle the public name and run a trademark search before the vision page uses it. Internally, "System One" stays as the working name.

## 12. Research programme

| Stage | Work | Rough cost |
|---|---|---|
| 0 | Record the graph in the harness and the arena; define the typed thesis record | Engineering only |
| 1 | Shapes in code; planted-cause labels; re-score the logistic baseline on held-out families | CPU |
| 2 | Five-model ensemble and a tabular model on graph features; conformal wrapper | CPU, a little GPU |
| 3 | Small fine-tuned model for the quarantined text fields, distilled from a frontier reviewer, with replay labels | Fine-tuning is cheap (hours on a few GPUs); generating data and replays is the real cost |
| 4 | RL with a bounded scoring reward on simulator outcomes and owner labels | Moderate; to be measured at stage 3 |
| 5 | Shadow mode with real owners | Partners and time, not compute |

## 13. For the vision page: the ideas that make it click

The full storyboard is a separate piece of work. These are the three ideas it has to land:

- **"Radar knows the card. System One knows the owner."** Fraud models learn what a cardholder would never do. System One learns what an owner would never have signed.
- **Every order has a family tree.** Show one order and its roots: the headline, the memory note, the thesis. Then show three "independent" agents whose trees meet at the same unverified root.
- **Judgement before the trade, not during it.** A thesis is judged once, in seconds; a thousand orders then pass through it in microseconds. Like a flight plan filed once: the controller checks each turn against the plan rather than re-deciding the destination.
