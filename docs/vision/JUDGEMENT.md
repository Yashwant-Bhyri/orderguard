# Long-horizon judgement: research plan and baseline

Section 3F of [AUTONOMY.md](AUTONOMY.md) proposed a model that judges each action against a persistent picture of the delegation, rather than one order at a time: what the book is for, which theses it holds, what evidence they rest on, and what has already been tried. This document gives the research plan and the honest baseline that now exists in `python/orderguard_autonomy/judgement.py`.

**The rule it is bound by** is the same as for every model in OrderGuard. It is advisory. Its probability can turn an allow into a hold. It can never approve anything, release a hold, or widen a limit, and if it fails, the decision falls back to no advice. The escalation lane in `python/orderguard_review/` already works this way for single orders (triage, scope check, draft review), and this model follows the same contract over long horizons.

## What exists now

- **Delegation memory.** It holds:
  - the signed objective and style;
  - the theses the agent has opened, each with its evidence;
  - the agent's memory notes, and whether each one resolves to evidence on record;
  - the exposure history.
- **Episode simulator.** Each episode is 160 actions with a known label per action. There are five modes:
  - **clean:** includes legitimate adaptation, such as a new thesis with fresh evidence;
  - **slow drift:** away from the signed style;
  - **undeclared claims:** figures with no source;
  - **vague figures:** "massive", "soaring";
  - **poisoned memory:** a note that tells the agent its limits do not apply.
- **Features.** There are fourteen, all interpretable and computed by code with no model:
  - off-purpose share and its moving average;
  - a Bernoulli CUSUM;
  - book distance from the signed style;
  - unsourced and unitless claims;
  - vague wording;
  - stale or unverified theses;
  - citations that do not resolve;
  - instruction-like text in memory;
  - and others.
- **Two models.**
  - A calibrated logistic model: L2 regularization, Platt scaling, pure numpy. Its explanation for a score is its largest feature terms.
  - The same signals as fixed rules, the comparison any learned model has to beat.
- **Admission integration.** `LongHorizonJudge` keeps one memory per agent, built from the typed intents the agent actually submitted, and scores each request. Tests (`python/tests/autonomy/test_autonomy_judgement.py`) check that a judge that flags everything only produces holds, that a judge that approves everything cannot rescue an order a hard check refuses, and that a crashing judge degrades to no advice.

## Results

Command: `PYTHONPATH=python python -m orderguard_autonomy.judgement`. Output: `results/vision/judgement.json` and the fitted model in `results/vision/judgement_model.json`.

Data: 600 training, 200 calibration and 400 test episodes, 64,000 test actions.

| | AUROC | Brier | Calibration error | Recall at 0.5 | Holds on clean episodes | Drift caught |
|---|---|---|---|---|---|---|
| Logistic, same distribution | 0.974 | 0.019 | 0.009 | 0.90 | 0.1% | 67% of episodes, median 46 actions after onset |
| Rules, same distribution | 0.932 | 0.027 | 0.027 | 0.86 | 0.0% | 67%, median 57 actions |
| Logistic, shifted | 0.634 | 0.158 | 0.141 | 0.05 | 0.3% | 67%, median 56 actions |
| Rules, shifted | 0.519 | 0.171 | 0.171 | 0.04 | 0.0% | 64%, median 76 actions |

**The shifted set is adversarial on purpose.** Its vague words are not in the rule vocabulary ("stellar", "colossal"). Its poisoned notes resolve to real evidence. Its claims cite a real source that is unrelated to the claim.

**What this says:**

- **In distribution, the model mostly measures how well the features match the generator,** because both were written by the same hand. The 0.974 is not evidence of judgement.
- **Under shift, both collapse.** The learned model keeps a little signal (AUROC 0.63 against 0.52) and still catches about a third of drifting actions, because drift is measured from behaviour, not words. It catches almost none of the vague, undeclared or poisoned cases once their surface form changes.
- **Holds on clean episodes stayed at or below 0.3%,** so the model is cheap to run as a tighten-only check. But on this evidence it does not yet earn its place for anything except drift.
- **Drift is better caught by the deterministic monitor:** the benchmark's drift monitor (style distance plus CUSUM) caught 100% of drifting agents with no false alarms. The judgement model is not wired into system D in the benchmark for that reason.

## Research plan

1. **Representation.** Store a thesis as a typed record: claim, horizon, invalidation condition, evidence hashes. Then "is this still the same thesis" becomes a question code can partly answer. Measure how much of the drift signal that recovers before any model is involved.
2. **Ground truth that is not ours.** Replace generator-written labels with episodes whose long-run outcome is scored independently:
   - forward paper trading after the models' training cutoff, with owner-written objectives;
   - drift and poisoning injected by a separate red team that does not see the features.
3. **Adaptation versus abandonment.** Collect pairs where the agent changed course for a documented reason and where it did not, and measure the false-hold cost of each threshold. A judgement model that cannot tell these apart is a tax on good agents.
4. **Language, carefully.** Only after steps 1 to 3, test a language model that reads the memory and the action and returns a probability. Score it on the shifted set above and on the red team's set, and compare it with the logistic baseline. Keep it tighten-only, with the same degrade-to-no-advice path as `orderguard_review`.
5. **Lead time against false holds.** Report the curve, not one point: how early drift is caught at each false-hold rate, per agent and per day.
6. **Memory poisoning as its own problem.** A note that resolves to real evidence but misquotes it is not caught by any feature here. Verifying a quote against its cited source is code's job (hash and span), not a model's. Build that check first.

**Done looks like:** on held-out, independently labelled episodes, a model that beats the rule baseline on lead time at the same false-hold rate, with calibration error under 0.05, and no case where it loosened a decision.
