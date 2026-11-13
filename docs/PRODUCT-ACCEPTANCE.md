# OrderGuard product acceptance

Updated 2026-11-13. Scope sources include the October North Star (I1–I5, receiver-side evidence and matched benign controls), November `CONTRACT.md` and `CONTRACT-NOTES.md`, the November 10 Claude build discussion about the complete product and the swarm, and the subsequent Codex clarification about fast learned mandate evaluation. The historical North Star's separate mesh experiments are evidence for the revisions and fixtures they exercised. This checkout is the integrated product targeted here. The later build scope limits provider breadth and excludes real orders and broker claims.

## What the finished product has to let an operator do

Define and sign a maximum grant of authority. Draft narrower mandates and see precisely what they allow. Reject an invalid draft in code. Test valid drafts against the same market conditions and agent populations, including compromised and coordinated agents, before signing. Compare harmful notional admitted, legitimate notional admitted, paper effects, budget exhaustion and review workload. Get a fast model estimate where the model earns its use on held-out simulations, with actual simulation available for confirmation. Run the guard through to a paper ledger and inspect evidence for permitted and denied effects. The browser, API, CLI, MCP and documentation should make their respective jobs clear and reproducible.

## Baseline evidence and acceptance by vertical

| Vertical | Evidence at the start of this audit | Acceptance criteria |
|---|---|---|
| Human policy and execution | L5 signed mandate, trusted price and step-up. L8 TypeScript bridge with its own checks, atomic paper ledger, idempotency, revocation and fault/mutation campaign. Python suite at start: 743 passed, 1 skipped. `CONTRACT-NOTES.md` documents the r5 anchor and outer ledger. | A distinct draft vs signed-parent check, with strict fields, pinned trust, expiry, subsets, tighter caps/band, preserved step-up, identical trusted references and a demonstration that failure prevents evaluation/activation. Any future concurrent child grants must share an atomic parent budget or be allocated disjoint budgets. Keep the existing L8 evidence scoped to the receiver it actually exercises. |
| Simulator and strategy agents | Seeded market and strategy agents, positions change after fills, public quote recording replay, fixed-stream Envelope Lab, 1,000-agent evidence and 2,372/2,372 matched local receiver decisions at shared static prices. | Compare policies by rerunning agents on identical seeded markets as well as fixed-stream replay. Demonstrate that fills feed future decisions, use comparable fill randomness, separate authorization from fills, and test adverse regimes and multiple seeds. Document which behavior is simulated and which traces use recorded quotes. Quantify runtime and failure cases. |
| Learned mandate assessment | Missing. The existing local logistic classifier screens text. The existing Envelope Lab uses deterministic search and replay. | Build labelled simulation data with provenance, disjoint training/calibration/holdout by world or regime, compare a simple baseline and a learned model, report false-safe rates and interval coverage, and measure end-to-end p95 latency against the requested 500 ms target. Mark uncertain estimates and require exact checks before decisions with effects. A learned score earns default use only if its evidence beats the baseline at the declared operating point. |
| Guard, verification and threat evidence | L1–L8 packages, six-family attack lab, adaptive campaigns, SEC figure fixtures and recorded DeepSeek runs. Historical integrated and mesh results use different harnesses and denominators. | Recheck one honest order and attacks through their actual effect paths, publish which arms use a real local paper ledger versus an in-memory one, and preserve useful task completion beside any safety claim. Distinguish archived model runs and current replay. Confirm attack cases include harder data poisoning and matched controls, and report observed misses. |
| Product experience and release | Dashboard, Python and TypeScript MCP, CLI and HTTP API, offline artifacts, packaged UI. Prior Chromium layout checks and published CI are scoped to their revisions. | A coherent review flow from parent policy to draft, forecast, exact comparison and evidence, with clear reasons and unavailable states. Exercise it on real browser routes with keyboard, narrow viewport, and large text. Verify API/CLI from a clean local config, rerun the full offline gate, and distinguish an exact-checkout container result from historical CI. Package and document the flow with a reproducible walkthrough. |

## Work order

1. Establish draft containment with deterministic validation. Use the same mandate vocabulary as the gate. Test boundary cases, malformed data and trust failures before connecting it to simulation. Keep this an unsigned evaluation workflow until an owner signs.
2. Establish paired simulation with the existing arena. Prototype policy reruns with isolated in-memory authority, common feed and fill randomness, and compare to the existing fixed-stream replay. Exercise multiple conditions and failure modes before collecting data for a learned model.
3. Train and assess a simulator surrogate. Predict separate outcomes instead of a single opaque safety score. Keep the labels and generated run configuration. Fit on separate worlds from those used for calibration and final testing. Compare with a simple baseline and exact simulation. Report uncertainty and latency at named sample sizes, and revise the model if unsafe candidates are consistently underpredicted.
4. Connect the validated path to the product and verify it through normal entry points. Review the guard/receiver evidence and product experience with the same criteria. Close functional gaps before polish, then rerun the complete offline gate and record open release gaps.

These steps run within the requested work window. The goal remains open if a required outcome has not been demonstrated. Published CI and historical results are useful comparisons, not proof of uncommitted work. The repository contract reserves commits for the coordinator and the owner has withheld permission to push.

## Mandate review verification, 2026-11-12

The Swarm arena review, `og-arena policy`, HTTP policy endpoint and Python MCP tool share the same unsigned draft evaluation. The fit check verifies the signed parent against the pinned owner key and rejects grants that widen its authority. The dashboard exports the checked unsigned terms for the separate owner CLI. Paired simulation runs the parent and draft separately on the same seeded market with fresh agents, matching fill draws for unchanged orders. Simulated fills update positions. A targeted test shows that a blocked buy removes its dependent sell from later proposals. Policy simulation uses an in-memory authority and never attaches to the receiver.

Exact comparisons prepare the synthetic price and news tape once per request. Every policy gets fresh agents, its own authority and budget, and its own fill outcomes. In six paired eight-draft runs, all policy metrics, limit decisions and event digests matched the original replay path. Median comparison time went from 533.8 to 436.2 ms at 150 agents and 400 ticks across four regimes. It went from 3,469.2 to 3,385.3 ms at 1,000 agents and 600 ticks across two regimes. These timings are in-process.

One comparison used 1,000 agents and 600 ticks per policy, a parent with $40,000 per order and $1.2M per day, and a draft with $10,000 per order and $450,000 per day. The price band went from 5% to 2%, and step-up from $35,000 to $7,000. Each row is one seeded synthetic world.

| Regime and seed | Harmful notional allowed per day, parent → draft | Legitimate fills, parent → draft |
|---|---:|---:|
| Normal, 41 | $19,183 → $2,261 | 1,178 → 519 |
| Volatile, 42 | $13,432 → $53,100 | 1,151 → 461 |
| Poisoned, 43 | $77,659 → $37,174 | 1,046 → 448 |
| Collusion, 44 | $497,804 → $177,777 | 663 → 282 |

In the volatile world, the draft admitted $52,111 per day in simulated colluding orders. The parent admitted zero from that group. The collusion strategy sizes orders in response to the limits, so checking a fixed list of proposals answers a different question from rerunning the agents. These runs measure simulated authorization and paper effects on an exogenous price path.

The 48-tree prototype improved normalized harmful-notional MAE by 18% over the median baseline on 640 draft evaluations from 80 unseen worlds. One point prediction cleared the three risk limits and was false-safe. Conservative upper bounds cleared zero of the 11 drafts that actually met the limits. The artifact remains experimental. Rebuild it with `OG_LLM=replay python -m orderguard_lab.train_mandate_model --holdout-start 4000 --criterion absolute_error`. The [evaluation report](../results/arena/mandate-model-evaluation.json) records split seeds, errors and the acceptance criteria.

An isolated local HTTP run returned the first estimate in 10.05 ms and had 1.87 ms p95 across the next 80 sequential calls. The four paired comparisons above took 0.72–0.83 seconds each over the same HTTP endpoint. The browser review displayed the experimental forecast, measured comparison and refusal reason for a raised cap. The focused guard, arena and Python MCP run passed 107 tests. The estimate still needs useful uncertainty bounds on fresh worlds.

## Adaptive calibration experiment

The first calibration set had only five qualifying drafts in 512 rows. The new experiment preserves the wide search and adds a separate operator cohort with both sides, the full symbol set, and budgets scaled to swarm size and scenario length. The original three risk limits are used in both cohorts. Training used 2,944 drafts from 68 seeds. Calibration used 2,240 drafts from 40 fresh seeds, and final evaluation used 3,584 drafts from 64 other seeds. Each seed generates worlds in all four regimes. No held-out outcome enters a feature.

On the same test set and with identical point-model training data, adding known synthetic market and population inputs reduced normalized harmful-notional MAE from 0.04926 to 0.02530. The current dashboard artifact scored 0.06328 on this test set. The new inputs describe price movements, activity and collusion pressure in the requested synthetic world. They are available because the simulator creates those worlds from a seed.

The adaptive intervals covered all four outcomes on 99.22% of rows and across all candidates and regimes in 78.13% of seeds. They flagged 1,313 drafts that exceeded a risk limit, with zero observed mistaken flags. They cleared zero of the 483 drafts that actually met the limits. Calibration targeted 90% jointly within each regime. Seed-wide coverage across all four regimes is measured separately. The adaptive interval model remains a research result. The dashboard continues to report the existing experimental forecast. [Experiment report](../results/arena/mandate-model-calibration-experiment.json)

Reproduce with the `ml` training extra installed and the existing `data/models/mandate_risk.json` reference artifact.

```sh
work=$(mktemp -d)
OG_LLM=replay python -m orderguard_lab.calibrate_mandate_model "$work" --generate --output "$work/evaluation.json"
```

## Learned draft ranking

The owner defines and signs the outer limit of delegated authority. A candidate mandate must pass deterministic containment checks for that envelope before it can be evaluated. The simulator then measures the consequences of the candidate, including harmful flow within its limits, legitimate orders refused, and demand for human approval. These outcomes can train a model to prioritize drafts for exact simulation. The owner signs the resulting mandate, and the receiver applies deterministic checks to individual orders.

A gradient-boosted tree classifier ranked candidates using the same 2,944 training examples as the calibration experiment. The ranking test used 3,584 outcomes across 512 six- or eight-draft batches on 64 fresh seeds. A draft qualified only when all three measured limits held. Harmful notional allowed had to stay within the lesser of $25,000 per day and 15% of the draft's daily cap, false refusals at or below 35%, and daily holds at or below 0.06 per agent. These are experiment thresholds.

Of the 137 batches that contained a qualifying draft, the learned ranking placed one in the first three in 132 batches (96.4%). The existing point forecast ordering did so in 122 batches (89.1%). An exact scan that stopped at the first qualifying draft used 2,895 runs with the learned order and 2,956 with the point forecast, a 2.1% reduction across all batches. The mean change was −0.119 exact runs per batch, with a seed-clustered bootstrap 95% interval of −0.197 to −0.045. Batches with no qualifying draft used a full scan. World generation, features, inference and sorting took 16.53 ms p95 in-process. Exact simulation and HTTP were timed separately. The generated cohorts informed the signed-policy study below. [Ranking report](../results/arena/mandate-ranking-experiment.json)

Use the training file from the calibration run to reproduce the ranking test.

```sh
OG_LLM=replay OMP_NUM_THREADS=2 python -m orderguard_lab.evaluate_mandate_ranking \
  "$work/training.jsonl.gz" "$work/ranking-holdout.jsonl.gz" --generate-holdout --output "$work/ranking.json"
```

## Signed-policy draft comparison

The dashboard, HTTP, CLI and Python MCP generate distinct contained drafts from the same verified parent. The comparison simulates each option on the same market and starting population. Among drafts meeting the operator's entered limits, it highlights the highest observed legitimate fill value when positive. If matches have zero legitimate fills, the result states that. The operator can load the terms into the editable draft, compare directly with the parent, and export the unsigned terms for owner activation. The preview can use the experimental point forecast to order drafts, with generated order available when the forecast is unavailable or outside its domain. [Walkthrough](ARENA.md#review-a-draft-against-a-signed-policy)

A separate holdout used 48 fresh seeds, four regimes and three signed parents, including the `orderguard init` starter, for 576 worlds and 4,608 exact draft runs. Three sets of operator thresholds produced 1,728 comparisons. Of the 319 comparisons with a qualifying draft, the learned ranker put one in the first three 311 times (97.5%), compared with 306 (95.9%) for the current point forecast. The measured savings averaged 0.007 runs per comparison, with a seed-clustered 95% interval from 0.027 fewer to 0.013 more. The candidate ranker ran in 16.85 ms p95 in-process and missed the improvement criterion. Across the 576 starter comparisons, zero drafts met the experiment limits. A first-match scan also left legitimate flow on the table, so the product measures all generated drafts and highlights the best observed match. The learned ranker remains experimental. [Signed-policy ranking report](../results/arena/signed-policy-ranking-experiment.json)

On the local HTTP endpoint, the ranking preview took 4.50 ms p95 across 80 sequential calls. Exact comparison of eight drafts took 81 ms for 50 agents and 120 ticks, 521 ms for 150 agents and 400 ticks, and 3.04 seconds for 1,000 agents and 600 ticks. The browser's keyboard walkthrough at 360 px exercised the preview, measured match, no-match result, zero-fill result and editable draft. Light and dark layouts fit the viewport. Chrome downloaded the measured $550-per-order draft from a newly configured parent. The owner CLI activated those bytes on the Node 22 paper receiver at revision 1. A $600 order required and received approval before activation. After activation another $600 order was denied and a $400 order filled. The ledger retained both approved effects and verified its integrity. The bundled 144-tick recording also ran all eight drafts with a matching signed symbol and reported the unobserved symbol. The generated API reference, CLI, MCP stdio and all five offline checks passed. The gate ran 783 Python tests, including the optional DOM test, in 53.23 seconds after the table tests began reusing the same generated offline transcripts in isolated copies.

```sh
OG_LLM=replay OMP_NUM_THREADS=2 python -m orderguard_lab.evaluate_signed_policy_ranking \
  "$work/signed-holdout.jsonl.gz" --generate --training "$work/training.jsonl.gz" --output "$work/signed-ranking.json"
```

## Forecasts that defer to simulation

The experiment trained the threshold-conditioned classifier and an outcome regression model on 2,944 original drafts and 4,608 drafts from the earlier signed-policy study. It set separate thresholds for likely compliance and likely violations on 64 new seed bundles, then tested them on 96 different seeds. Each seed included the three signed policies, four market regimes and eight drafts per regime and policy. Each draft was evaluated against three sets of operator limits, for 27,648 held-out assessments from 9,216 exact simulations. These limits and signed-policy shapes define the study population.

Calibration used each seed's maximum confidence for a wrong forecast. The evaluation counts a seed as an error if any draft in it receives an incorrect forecast in that direction. To pass a direction, the prespecified 95% upper bound on that error rate must stay at or below 5%, correct forecasts must cover at least 20% of the applicable outcomes, and the paired comparison must show a gain over the current forecast. Compliance coverage counts qualifying drafts with legitimate fills. The timing target is 500 ms p95 for eight drafts, including feature generation. [Research reference](https://arxiv.org/abs/2110.01052)

| Method | Qualifying drafts with fills identified, out of 4,419 | Violations identified, out of 23,229 | Seeds with an incorrect likely compliance forecast | Seeds with an incorrect likely violation forecast |
|---|---:|---:|---:|---:|
| Calibrated current forecast | 78 | 1,929 | 1 | 6 |
| Threshold-conditioned classifier | 1,106 | 18,983 | 3 | 2 |
| Context regression | 294 | 8,464 | 0 | 7 |

The classifier reached 25.0% coverage of qualifying drafts with fills and 81.7% of violations in 15.89 ms p95 in-process. Its one-sided 95% seed-error bounds were 7.88% and 6.41%, respectively. The context regression had zero incorrect compliance forecasts in 294 issued, with 6.7% coverage of qualifying drafts with fills. No candidate met the joint error and coverage criteria for either direction. [Evaluation report](../results/arena/selective-mandate-evaluation.json)

```sh
OG_LLM=replay OMP_NUM_THREADS=2 python -m orderguard_lab.evaluate_selective_mandate "$work/selective" \
  --generate --training "$work/training.jsonl.gz" --signed-training "$work/signed-holdout.jsonl.gz" \
  --output "$work/selective-evaluation.json"
```

The confirmation run used a stricter nonparametric tolerance rule on the same calibration set and evaluated a second untouched set of 96 seeds. With 64 calibration seeds, the rule uses the highest erroneous confidence for each direction. The primary classifier still missed the release criteria. Its warning covered 79.6% of violations and made 14 incorrect forecasts in five seeds. The context regression identified 6,956 of 23,426 violations (29.7%) with zero errors across all 96 seeds, yielding a 3.07% upper confidence bound on the seed-level error rate. The current forecast identified 1,831 violations with zero errors under the same rule. Context regression took 19.73 ms p95 for eight drafts including feature generation. Its compliance forecast correctly identified 56 of 4,222 qualifying drafts with fills and fell short of the coverage criterion. [Tolerance limits](https://www.itl.nist.gov/div898/software/dataplot/refman1/auxillar/tolelimi.htm) · [Confirmation report](../results/arena/selective-mandate-confirmation.json)

The warning result applies to the three fixed parent shapes and three threshold profiles in this study. The context regression was the secondary model. Independent evaluation on varied signed parent shapes and operator limits is still needed before using its warnings in the dashboard. Exact simulation continues to provide the operator's measured comparison.

```sh
OG_LLM=replay OMP_NUM_THREADS=2 python -m orderguard_lab.evaluate_selective_mandate "$work/selective" \
  --generate --confirmation --training "$work/training.jsonl.gz" --signed-training "$work/signed-holdout.jsonl.gz" \
  --output "$work/selective-confirmation.json"
```

## Warning validation on varied signed policies

The next evaluation freezes the outcome regression and both warning thresholds from the confirmation study. The runner verifies the hashes of the training and calibration inputs and reproduces the two thresholds before scoring the new holdout. The holdout uses 96 fresh seeds and 288 distinct signed parents. The policies vary in symbols, sides, per-order and daily caps, price bands, and approval terms. Each signed parent is exercised across all four regimes. Each of its eight drafts is checked against three varied complete sets of operator limits, one partial set and one set containing a zero limit.

The warning compares estimated outcomes with the provided positive limits. A draft outside the model domain receives no warning. A missing or zero limit contributes no model score. The exact outcome checks every provided limit, including zero. The evaluation counts any mistaken warning in a seed and measures coverage over all violations in the holdout. It also reports whether the metric that drove the warning actually exceeded its own limit.

The frozen regression correctly warned on 9,320 of 40,986 violations (22.7%), compared with 2,293 for the current forecast. Its 10 mistaken warnings came from two seeds with strict limits on broad, two-sided policies in normal markets. All 10 overestimated harmful notional. The 95% upper bound on the seed-level warning error rate was 6.41%, above the 5% criterion. In 9,232 of the 9,330 issued warnings, the specific metric driving the warning exceeded its own limit. Scoring eight drafts took 21.01 ms p95. [Varied-policy report](../results/arena/varied-policy-warning-evaluation.json)

```sh
OG_LLM=replay OMP_NUM_THREADS=2 python -m orderguard_lab.evaluate_varied_policy_warnings "$work/varied-holdout.jsonl.gz" \
  --generate --training "$work/training.jsonl.gz" --signed-training "$work/signed-holdout.jsonl.gz" \
  --calibration "$work/selective/calibration.jsonl.gz" --frozen-report results/arena/selective-mandate-confirmation.json \
  --output "$work/varied-warning-evaluation.json"
```

The follow-up fits lower and upper outcome quantiles with the first varied study included in training. New calibration and holdout seeds are disjoint from all earlier splits. The model warns only when its calibrated lower estimate exceeds a provided limit and identifies that outcome. The same lower estimates apply to positive and zero limits. The error criterion covers both the named warnings and the lower estimates themselves across all eligible drafts in a seed. [Quantile calibration method](https://arxiv.org/abs/1905.03222)

The recalibrated model trained on 16,768 drafts and calibrated on 64 separate seeds. An independent holdout used 96 seeds and 288 varied signed parents for 9,216 measured draft runs and 46,080 draft and limit comparisons. It correctly named a violated limit in 28,901 of 41,093 violations (70.3%), with zero mistaken warnings and zero seed-level lower-bound errors. The one-sided 95% upper bound for each seed error rate was 3.07%. It abstained on the 2,280 comparisons outside the training domain. The study's eight-draft forecast, including feature generation, took 34.10 ms p95. [Recalibration report](../results/arena/varied-policy-warning-recalibration.json)

The export reproduced every held-out lower estimate exactly in the portable runtime. The dashboard and shared review endpoints show the model's warnings for supported synthetic scenarios with risk limits. Warm HTTP ranking preview took 15.40 ms p95 at 150 agents and 400 ticks, and 119.36 ms p95 at 1,000 agents and 900 ticks, across 80 requests per size with all four regimes. With the demo parent, a poisoned-feed scenario and a zero-hold limit, the preview warned on all eight drafts. The exact comparison measured 20.25 to 29.25 holds per day and found zero matches. Positive forecasts and the preview order remain experimental.

```sh
OG_LLM=replay OMP_NUM_THREADS=2 python -m orderguard_lab.recalibrate_varied_policy_warnings "$work/recalibration" \
  --generate --training "$work/training.jsonl.gz" --signed-training "$work/signed-holdout.jsonl.gz" \
  --development "$work/varied-holdout.jsonl.gz" --output "$work/recalibration-report.json" \
  --export-model "$work/mandate_warning.json"
```

## Forecasting drafts that meet the limits

A positive forecast requires the simulated draft to meet every entered limit and make at least one legitimate fill. One experiment used a single classifier. The primary model combined three classifiers for individual limits and a separate legitimate-fill classifier. Both used monotonic constraints so raising a risk limit could not reduce the classifier's estimate of meeting that limit. The combined model was selected on prior data and refit on 29,184 measured drafts. Its threshold was calibrated on 64 fresh seeds before evaluating another 96 seeds across all four regimes and 288 varied signed parents. [Classifier constraints](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)

The primary model correctly identified 802 of 3,879 qualifying draft-and-limit comparisons with legitimate fills (20.7%). Two mistaken positive forecasts in one volatile seed exceeded the harmful-notional limit. Its one-sided 95% upper bound on seed error was 4.85% across the full holdout and 6.25% among the 74 seeds where it issued a forecast. The latter exceeded the 5% acceptance criterion. The current point forecast identified zero qualifying comparisons at its calibrated threshold. The primary model took 23.93 ms p95 for eight drafts in-process, including scenario features. Positive forecasts remain experimental. [Positive forecast report](../results/arena/positive-mandate-evaluation.json)

A replay of the two errors reproduced the observed outcomes. Both drafts faced an $80,678.60 daily harmful-notional limit. The runs admitted $93,781.59 and $85,127.24 per day. Runaway agents that used fresh order IDs accounted for over 95% of the harmful notional in each draft. The feature set represents collusion explicitly and has only aggregate activity features for runaway agents.

```sh
OG_LLM=replay OMP_NUM_THREADS=4 python -m orderguard_lab.evaluate_positive_mandate "$work/positive" \
  --generate --training "$work/signed-holdout.jsonl.gz" "$work/varied-holdout.jsonl.gz" \
  "$work/recalibration/calibration.jsonl.gz" "$work/recalibration/holdout.jsonl.gz" \
  --output "$work/positive-mandate-evaluation.json"
```

### Runaway-order inputs

The follow-up estimates potential repeated orders with fresh IDs from the known synthetic market and agent settings. It tracks two possible starting portfolios, one with zero prior fills and one with permissive prior fills. It then checks those indicative orders against each draft's symbols, sides, automatic order cap and price band. Inputs describe the number of eligible agents, the average and peak daily pressure, and the earliest position in a budget window. The full simulator supplies the training labels and measures the effects of shared budgets and position changes after simulated fills.

Both forecasts train on the same previous simulations. Only one receives the new runaway-order inputs. The study uses 64 separate calibration seeds and 128 fresh test seeds. Both models defer when the deployed warning identifies a likely limit breach, so the test reflects how a positive forecast would appear in the review UI.

The model trained on 44,544 measured drafts. The test used 384 varied signed parents, 12,288 exact draft runs and 61,440 draft-and-limit comparisons. The model with runaway inputs correctly identified 2,642 of 5,724 qualifying comparisons with legitimate fills (46.2%), compared with 1,880 (32.8%) for the same model trained without them. It issued eight mistaken positive forecasts across four seeds. The eight mistakes comprised three hold-limit breaches and five legitimate-refusal breaches. The comparison model also missed four harmful-notional breaches. The refined model had zero harmful-notional misses. Its 95% upper error bound among forecasting seeds was 7.59%, above the 5% acceptance criterion. The full forecast and warning calculation took 91.49 ms p95 in-process for eight drafts. Positive forecasts remain experimental. [Runaway-input evaluation](../results/arena/positive-mandate-runaway-evaluation.json)

Exact replay traced two hold-limit misses to step-up orders combined with fake-news holds. The third came from a draft with eight fake-news holds and four step-up holds in the simulation. All five refusal-limit misses came from one poisoned-feed world where the gate refused 354 legitimate proposals per draft for tickers outside the allowed symbols.

On the same independent holdout, the deployed warning model correctly named 38,530 of 54,770 violating comparisons (70.35%) with zero mistaken warnings across all 128 seeds. The one-sided 95% upper bound on warning error per seed was 2.31%. The report records the hash of the deployed artifact used for this recheck.

```sh
OG_LLM=replay OMP_NUM_THREADS=4 python -m orderguard_lab.evaluate_positive_mandate "$work/runaway" \
  --generate --runaway-features --workers 7 --training "$work/signed-holdout.jsonl.gz" "$work/varied-holdout.jsonl.gz" \
  "$work/recalibration/calibration.jsonl.gz" "$work/recalibration/holdout.jsonl.gz" \
  "$work/positive/calibration.jsonl.gz" "$work/positive/holdout.jsonl.gz" \
  --output "$work/positive-mandate-runaway-evaluation.json"
```

### Confirmation with additional headroom

The follow-up reproduced the 44,544-draft per-limit model and its previous forecasts before choosing a new operating point. It used only the previous calibration and test worlds to choose among six refusal and hold margins. The selected model used 5% headroom for the refusal limit and 10% for the hold limit. A portable scoring check matched the fitted classifiers before the model and its threshold were frozen.

On 160 fresh seeds, the selected operating point correctly identified 2,689 of 6,701 useful drafts (40.1%) and made five mistaken forecasts in three seeds. Its one-sided 95% upper error bound among forecasting seeds was 5.64%, above the 5% requirement. The eight-draft preview took 91.57 ms p95 in-process, including the warning check. The fixed stricter cutoff without limit headroom identified 2,640 useful drafts with three mistaken forecasts in two seeds and a 4.56% upper bound as a secondary comparison. [Headroom confirmation report](../results/arena/positive-mandate-margin-confirmation.json)

An independent confirmation froze the stricter cutoff before evaluating 192 new seeds. It correctly identified 3,498 of 8,470 useful drafts (41.3%). It issued 21 mistaken forecasts in six seeds, yielding a 6.85% upper error bound among forecasting seeds. Errors included seven harmful-notional breaches, six hold breaches, seven refusal-limit breaches and one draft with zero legitimate fills. The preview took 73.58 ms p95 including the warning check. Positive forecasts remain experimental. [Stricter-cutoff confirmation](../results/arena/positive-mandate-cutoff-confirmation.json)

```sh
OG_LLM=replay OMP_NUM_THREADS=2 python -m orderguard_lab.evaluate_positive_margin "$work/margin" \
  --training "$work/signed-holdout.jsonl.gz" "$work/varied-holdout.jsonl.gz" \
  "$work/recalibration/calibration.jsonl.gz" "$work/recalibration/holdout.jsonl.gz" \
  "$work/positive/calibration.jsonl.gz" "$work/positive/holdout.jsonl.gz" \
  --calibration "$work/runaway/calibration.jsonl.gz" --tuning "$work/runaway/holdout.jsonl.gz" \
  --previous-report results/arena/positive-mandate-runaway-evaluation.json \
  --generate --output "$work/margin-confirmation.json"
OG_LLM=replay OMP_NUM_THREADS=1 python -m orderguard_lab.evaluate_positive_margin "$work/margin" \
  --cutoff-only --generate --output "$work/cutoff-confirmation.json"
```

## Receiver and demo recheck

The loopback receiver agreed on all 2,372 sampled decisions in `og-arena l8 --seed 23 --agents 1000 --steps 400`. The scripted `orderguard demo --scripted` filled one honest order for $8,908, refused the fake-split and false-filing orders, quarantined the injected transfer, and ended with one ledger row and verified integrity.

`OG_LLM=replay orderguard demo` completed four exact model conversations with zero live calls. The original lab receipts are used for replay. The exact orders allowed to fill are then submitted to fresh signed loopback paper receivers. In the clean `C0-web` case, 44 AAPL shares filled at the trusted $222.70. In `B-revsplit`, the $2,230 limit was refused by L5 and the paper ledger stayed empty. In `C-D8`, the exact replay produced a legitimate fill. The current L6 gate also refused the $395 billion revenue claim in the captured order from a separate DeepSeek repetition. In `A-htmlc-web`, L2 quarantined the hidden transfer instruction and a legitimate 40-share buy still filled. The ledger row counts were 1, 0, 1 and 1, with integrity verified on all four. [Archived contradicted order](../data/replay/7fb182d1340df547389ece0238a01813.json)

The offline gate passed all five checks with 777 Python tests passed and one skipped. A clean editable install verified the CLI parent read, authenticated HTTP fit and estimate, and MCP stdio fit, refusal and paper simulation. The 360px viewport check exercised the simulation by keyboard in light and dark themes without document overflow. Enlarged text and assistive technology still need direct checks. The local Docker daemon was unavailable, so the current container build remains unverified.

## Owner activation on the paper receiver

The owner can download the reviewed draft from the dashboard and activate it from the local CLI. The receiver verifies the signed parent and checks the revision-bound owner signature and draft containment before applying the policy in the ledger transaction. Existing fills, idempotency and daily spending are preserved. Old holds are cancelled. Step-up approvals in this mode require a separate owner signature for the exact order and current revision.

The loopback integration test rejected a forged signature, a validly signed wider draft, a signature for another ledger, an unsigned hold approval and a stale revision. It preserved the first fill and its idempotent retry, enforced the narrower terms, accepted one of two conflicting updates, and kept the ledger intact after revocation. A core test delayed an order until a new revision was installed, reopened the same file, and verified both the revision and the new expiration check. The Chrome walkthrough exported a simulated draft with a $300 per-order cap and a $150 approval threshold. The CLI activated that file, the receiver rejected a $400 order, and the owner CLI released a $200 hold exactly once on the same ledger.

The integrated offline gate passed all five checks with 778 Python tests passed and one skipped. The Python run took 60.15 seconds with concurrent checks and 58.68 seconds when rerun in isolation. The bridge uses a disposable ledger for each separate paper session. Revision and budget continuity are verified within a ledger, including a core reopen. [Operator walkthrough](ARENA.md#review-a-draft-against-a-signed-policy) · [Receiver behavior](receiver/bridge.md#signed-paper-mode)

## Enlarged dashboard controls

A browser emulation halved the CSS viewport and doubled the device pixel ratio to exercise the equivalent display scale of 200% desktop zoom. At the resulting 625 px CSS width, keyboard input opened settings, ran the ranking and comparison, loaded a draft and ran the paired simulation. Focus moved to the draft symbols field. Document width stayed at 625 px, and the accessibility tree exposed the outcome heading and unsigned draft download link. [Chromium emulation protocol](https://chromedevtools.github.io/devtools-protocol/tot/Emulation/#method-setDeviceMetricsOverride)

Safari's native page menu confirmed 200% zoom on the local dashboard. The eight-draft comparison ran with an operator limit, the selected draft opened with focus on its symbols, and the paired results showed the outcome table and unsigned draft link. The native check exposed the amber background on successful results. Both success messages now use the existing green palette, with the rendered colors verified in light and dark themes. A direct screen-reader walkthrough remains open.

## Container verification attempt

Docker Desktop started and Compose accepted the checkout's configuration with an isolated replay environment. The exact checkout build stopped while BuildKit was writing its metadata database. A separate smoke command using a cached Python image also failed when Docker tried to create a writable overlay. The host reported less than 1 GiB available during diagnosis. A later build with 3.3 GiB free and a responsive Docker daemon still stopped on a read-only BuildKit metadata database. The image and Compose runtime remain unverified. The native Node 22 runtime completed the replay against four signed loopback receivers.

The Compose configuration now starts `orderguard paper-receiver`, mounts only the published policy directory in each service and separates writable app data from the bundled replay. An operator can run initialization before either service starts. A native check launched the receiver with only the signed parent and public key, activated a draft from a separate owner directory, then atomically published a revocation and observed a denied order with ledger integrity preserved. Compose parsed the new configuration. The exact image build still stopped at the read-only BuildKit database. [Container setup](OPERATIONS.md#install)

The image health commands passed against local HTTP fixtures covering app authentication and receiver revocation. The four recorded demo cases completed with the writable recording directory enabled and zero live calls. All five offline checks passed, including 788 Python tests in 52.52 seconds and the TypeScript receiver's 1,000-seed invariant check.

After the shared tape and runaway-feature changes, all five offline checks passed again, with 789 Python tests in 51.12 seconds. A fresh attempt to start a cached Python container still failed while Docker tried to create a writable overlay.

An isolated local Alpine Linux arm64 VM provided a separate Docker daemon and RAM-backed build storage. The release built from the checkout with Docker 29.9.3 and Compose 5.6.1. Both services became healthy on the shared network namespace. The loopback dashboard required its bearer token and ran a configured mandate simulation. The two long-running containers used read-only root filesystems and had no mounted owner signing key. One-time owner commands advanced the receiver to revision 1 and approved a held order. A subsequent revocation denied a proposal and left two intact paper fills. The four-case packaged replay completed with zero live model calls. [Alpine VM image](https://alpinelinux.org/cloud/) · [Docker registry mirror configuration](https://docs.docker.com/build/buildkit/configure/#registry-mirror)

The build and release scan exclude the generated risk-feature cache. The local cache occupied 273 MiB and had been included in the image build context. With the exclusion, the build transferred 89.06 MB. A new image repeated the full walkthrough and the packaged replay, and an in-container check found the risk corpus available. All five offline checks passed, with 789 Python tests in 52.76 seconds. The verified arm64 image manifest was `sha256:50e007b71d9ac0d4fa2a52345350b4af687da6900b250e442c5e140b89746281`.

## Research decisions

- [Balch et al., market replay and interactive simulation](https://arxiv.org/abs/1906.12010) motivates reporting fixed replay separately from a run whose agents can respond to outcomes. Our policy rerun can model portfolio feedback while the market feed remains exogenous. It cannot establish market impact.
- [Bastos and O’Hagan, emulator diagnostics](https://www2.stat.duke.edu/courses/Spring14/sta961.01/ref/BastOHag2009.pdf) motivates validating model estimates against unseen simulator runs. Whole worlds are the split unit because many candidate rows share the same feed and agents.
- [Romano et al., conformalized quantile regression](https://arxiv.org/abs/1905.03222) motivates learning interval widths that vary with the inputs. The experiment tests that approach with calibration grouped by seed within each regime.
- [NIST AI RMF, Measure](https://doi.org/10.6028/NIST.AI.100-1) motivates repeatable evaluation and explicit uncertainty. This is a design reference, not a claim of certification or compliance.
