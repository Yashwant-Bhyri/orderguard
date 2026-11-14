# Order risk: a tighten-only layer of programmed and learned weights for agent swarms

The code gate (L5 to L8) refuses every order that breaks the signed mandate. It cannot see an order that is individually fine but part
of a bad pattern: five agents splitting one position into orders that each sit just under the step-up threshold, a runaway loop of
small legal orders, an agent whose sizes suddenly jump to the top of its envelope. In the 1,000-agent arena, colluding agents whose
every order was inside the envelope got **$8.0M** of bad notional through and starved honest agents of daily budget
([ARENA.md](ARENA.md)).

`python/orderguard_risk` scores every order the gate **allowed**, from behaviour across agents and time, the way a card network
scores payments, with one constraint that makes it safe to deploy:

> **It can only tighten.** `tighten(decision, risk)` returns the stricter of the gate's decision and the model's action: allow can
> become hold (a human decides) or refuse; hold can become refuse; refuse never changes; an unknown decision becomes refuse. A wrong
> or attacked model can cost legitimate flow, but it cannot authorise anything the signed mandate forbids. A property test checks
> this over 5,000 random decisions.

**Status.** The shipped model is v2 (`data/models/order_risk.json`, format `orderguard-order-risk/2`). The first model is kept as
`data/models/order_risk_v1.json` and still loads. v2 was shipped because it passed the rule declared before measuring: at the
operating budget (0.25% of honest orders held) it stops more bad dollars with fewer honest holds than the v1 architecture on held-out
seeds and on the adaptive colluders, and it improves every leave-one-family-out row. **It loses to v1 in one place that matters: a
white-box attacker optimised against v2 gets more through v2 than the attacker optimised against v1 gets through v1** (see
[Adversarial robustness](#adversarial-robustness-and-the-cost-of-evasion)). Reverting is a file copy.

## Method

```
proposal ─► code gate (L5) ──allow──► FeatureEngine.featurize(event)        point-in-time: only events before this one
                 │                     ├─ 7 programmed units u_k(x)          hand-written weights: mandate semantics + attack signatures
                 │                     ├─ 80 monotone trees  p_learned(x)    fitted on data
                 │                     │   risk = 1 − (1 − p_learned) · Π_k (1 − π_k · u_k)          noisy-OR
                 │                     ├─ one-shot weight edits              units written from ONE labelled example, no retraining
                 │                     └─ risk ≥ hold threshold ─► hold      risk ≥ refuse threshold ─► refuse
                 └──hold / refuse────► unchanged                             tighten() is the only way decisions combine
```

### 1. Programmed weights

Some things are known before any data: what the mandate means and what the known attacks look like. Those are written directly as
units instead of being learned (`program.py`). The first layer is a set of **invariants** in `features.py`: quantities relative to the
mandate (share of the cap and of the step-up threshold, position in the price band, the agent's share of the daily budget) or to a
baseline (the agent's own usual size, rate, schedule and distance from the price; its peers' rate and notional; recent price moves).
One threshold on an invariant means the same thing in every envelope and for every agent. A unit is a soft AND of ramps over
invariants, `u(x) = Π_t clip((x_f − lo) / (hi − lo), 0, 1)`, with a weight π = the probability that an order on which it fully fires is
bad. Thresholds were set from the mandate and the attack definitions, then checked against honest orders of the training runs only.

| unit | signature | terms (feature: ramp from, to) | programmed weight | after refit | fires on honest orders | catches (bad $ of its family, training runs) |
|---|---|---|---|---|---|---|
| `split_under_threshold` | collusion | cap_ratio: 0.3 to 0.45; sync_size_agents: 2.5 to 3.5; sizesim: 12 to 24 | 0.9 | 0.9988 | 0.002% | 91.1% |
| `coordinated_burst` | collusion | agent_burst: 3.5 to 6; hot_peers: 0.5 to 2.5; trig: -0.5 to -1 | 0.9 | 0.9873 | 0.035% | 89.0% |
| `order_rate` | runaway | agent_burst: 5 to 9; trig: -0.5 to -1 | 0.9 | 0.9852 | 0.045% | 70.2% |
| `repeat_loop` | runaway | dup_run: 1.5 to 3.5 | 0.95 | 0.9983 | 0.000% | 90.2% |
| `size_discontinuity` | fat finger | size_jump: 0.8 to 1.4 | 0.9 | 0.9965 | 0.001% | 86.3% |
| `limit_far_from_trusted` | stale price | abs_dev: 0.03 to 0.04; dev_vol: 2 to 5 | 0.85 | 0.5884 | 0.019% | 84.2% |
| `schedule_break` | compromised | off_cadence: 0 to 1 | 0.8 | 0.9943 | 0.005% | 42.2% |

Any unit fires on 0.07% of honest gate-allowed orders in the training runs. Nearly all of those are orders labelled honest
that come from an agent in the middle of an attack (a colluder's own strategy orders); in a check on the training runs,
`coordinated_burst`, `order_rate` and `schedule_break` never fired on an agent with no attack in its run.

**Why the data cannot erase them.** Units enter by noisy-OR, so `risk ≥ π_k · u_k(x)` whatever the trees say (tested). The weights are
refitted from data with a Beta prior centred on the programmed value (50 pseudo-firings) and a floor at half of it: honest firings pull
a weight down (the stale-price unit went from 0.85 to 0.59), and a family with zero examples keeps its programmed weight.

### 2. Learned residual

80 gradient-boosted trees (depth 5) over 54 behavioural columns: the 35 of v1 plus the invariants. They are constrained to be
**non-decreasing** in 17 features where more can only mean more risk (order rate, repeats, peer-relative notional, distance of the
limit from the trusted price, synchrony counts), so there is no pocket where doing more of the suspicious thing lowers the score.
Platt scaling and every threshold come from **out-of-fold** scores over whole training runs; the trees never score a run they were
fitted on when a threshold is set. Text features are not used (the generator's rationales are produced from the label).

### 3. One-shot weight edits

`scorer.label_attack(event, note, hint=None)` turns ONE labelled order into a new unit, immediately, with no retraining
(`program.edit_from_example`):

1. Standardise the example on 34 invariant coordinates against the honest statistics stored in the model (median and one-sided robust
   scales). Keep the coordinates where it is at least 3 honest scales out in the suspicious direction; an analyst `hint` can name the
   coordinates instead.
2. The unit fires when every chosen coordinate is at least κ of the way from the honest median to the example. That is a half-space
   per coordinate (a weight and a bias written directly), so a later attack that is *more* extreme still fires. A nearest-neighbour
   prototype (v1) only matched look-alikes.
3. Take the **fewest** coordinates (most extreme first) and the smallest κ in {0.5 … 1.0} that capture at most 0.1% of the recent
   orders the model did not flag, excluding the labelled agent's own orders. If even the tightest conjunction looks like honest flow,
   no edit is written. An edit can only hold, never refuse.

When the example is not outside honest flow on any coordinate, the scorer falls back to the v1 prototype with a calibrated radius.

### 4. Engineering

One JSON file (0.15 MB), scored in pure Python with no sklearn at runtime; the contract is unchanged
(`RiskScorer.load / set_envelopes / score / observe / label_attack`, `tighten`). `score()` keeps `risk`, `action`, `reasons`,
`prototype_similarity`, `latency_us` and adds `learned_risk` and `units` (`[{name, family, activation}]`). Reasons name the unit that
fired, in plain English, before the tree attributions. Every window is a deque with O(1) amortised update; a test checks that
appending later events never changes an earlier feature vector, and another that JSON inference equals the numpy/sklearn reference
to 1e-6.

**Latency**, pure Python, features included, 20,503 orders of the seed-7 stream on an Apple-silicon laptop:
**40 µs median, 142 µs p99**, 700 µs p99.9. The tail is the hold path, which also computes the explanation.

## Data and protocol

`og-risk build-data` runs the arena engine 48 times across seeds, swarm sizes (300 to 1,000 agents), archetype mixes, market regimes
and envelopes: **592,988 labelled proposals** (`data/risk/corpus.npz`). Seed 7, the arena's published run, is never used. A separate
set of 8 runs uses **adaptive colluders** that randomise size, timing and tickers (`stealth.npz`, 138,901 proposals); no model ever
trains on them. A third attacker is generated fresh by a search against the model (below).

Runs are split whole: 36 to fit (trees, out-of-fold calibration and thresholds), 12 held out and touched only to report. Numbers are
on gate-**allowed** orders. "v1" in the tables is the v1 architecture (35 features, trees only) fitted and thresholded by exactly the
same procedure, so the two columns differ only in the model. The first model as it was shipped, at its 1% threshold, stopped
99.84% at 1.06% honest held on held-out seeds and 93.95% at 0.86% on the adaptive colluders.

Two disclosures. While designing the units I looked once at which adaptive-colluder orders v1 missed; the unit thresholds themselves
were set from training runs. And I chose the 0.25% operating budget before measuring, but saw the comparison at all four budgets
before writing this page.

## Results

### Operating points (bad dollars stopped at a fixed honest-hold budget)

Held-out seeds (126,579 allowed orders, $57.3M bad):

| honest-hold budget | v2 bad $ stopped | v2 honest held | v2 hold precision | v2 honest holds / run-day | v1 bad $ stopped | v1 honest held | v1 hold precision | v1 honest holds / run-day |
|---|---|---|---|---|---|---|---|---|
| 0.10% | **99.65%** | 0.09% | 96.8% | 2.3 | 99.58% | 0.20% | 93.2% | 5.1 |
| 0.25% | **99.78%** | 0.26% | 91.4% | 6.7 | 99.68% | 0.41% | 86.9% | 10.6 |
| 0.50% | **99.87%** | 0.62% | 81.7% | 15.9 | 99.75% | 0.72% | 79.3% | 18.5 |
| 1.00% | **99.92%** | 1.21% | 69.8% | 30.9 | 99.85% | 1.28% | 68.5% | 32.7 |

Adaptive colluders, never trained on (125,345 allowed orders, $51.3M bad):

| honest-hold budget | v2 bad $ stopped | v2 honest held | v2 hold precision | v2 honest holds / run-day | v1 bad $ stopped | v1 honest held | v1 hold precision | v1 honest holds / run-day |
|---|---|---|---|---|---|---|---|---|
| 0.10% | **98.88%** | 0.17% | 97.5% | 6.1 | 89.66% | 0.21% | 96.2% | 7.7 |
| 0.25% | **99.32%** | 0.28% | 96.0% | 10.2 | 92.17% | 0.37% | 93.8% | 13.7 |
| 0.50% | **99.60%** | 0.54% | 92.4% | 20.0 | 93.48% | 0.59% | 90.7% | 21.7 |
| 1.00% | **99.67%** | 0.98% | 87.1% | 36.2 | 94.78% | 1.06% | 84.7% | 39.0 |

At the operating budget v2 stops 99.78% of bad dollars on held-out seeds while holding 0.26% of honest orders
(0.20% of orders from agents with no attack in their run), and 99.32% at 0.28% (0.12%) on the adaptive
colluders. By family on held-out seeds: collusion 100.0%, compromised 98.3%, fat finger 94.3%, runaway 100.0%, stale price 96.9%. The refuse threshold alone: 97.74% of bad dollars refused outright at 0.04% of honest orders refused.

**Where this is not a clean win.** Against the first model *as shipped at 1%* (99.84% at 1.06% honest held), v2 at 0.25% holds about a
quarter as many honest orders and gives up a few hundredths of a point of bad-dollar recall on held-out seeds (99.78%); v2 at the 0.5% budget
(99.87% at 0.62%) is better on both.
The realised honest rate drifts above the budget when the market regime shifts (table below): the thresholds are quantiles of the
training regimes. Trees alone on the v2 features stop slightly more on held-out seeds (99.84% at 0.33% honest held) than the shipped combination; the programmed units pay for themselves on the adaptive set and on unseen families, not in distribution.

| protocol (v2, 0.25% budget) | bad $ stopped | honest orders held | hold precision |
|---|---|---|---|
| regime shift: train calm/normal, test volatile | 99.92% | 0.39% | 85.5% |
| regime shift: test "shifted" | 99.79% | 0.51% | 89.9% |
| time split: train early steps, test late | 99.95% | 0.19% | 92.6% |

### Calibration

| set | v2 Brier | v2 ECE | v1 Brier | v1 ECE |
|---|---|---|---|---|
| held-out seeds | 0.00082 | 0.00062 | 0.00095 | 0.00033 |
| adaptive colluders | 0.00211 | 0.00077 | 0.01749 | 0.01993 |

In distribution v2's ECE is slightly worse than v1's (the noisy-OR double-counts evidence the trees already have); out of
distribution it is far better, because v1 gives the adaptive colluders it misses a near-zero risk.

### Leave one family out: zero-shot, one-shot, few-shot, full retrain

Each row removes a family from fitting entirely, then measures the bad dollars of that family stopped on the held-out runs at the
0.25% budget. "+1 label" and "+5 labels" write weight edits from orders of the family that the base model missed in the fitting runs
(median over 20 random draws, quartiles in brackets). The last row treats the adaptive colluders as the unseen family: labels come from
one run and are measured on the others.

| family held out | v1 trees, zero-shot | v2 trees only, zero-shot | + 1 label | + 5 labels | **v2 programmed, zero-shot** | + 1 label | + 5 labels | full retrain |
|---|---|---|---|---|---|---|---|---|
| collusion (2507 orders) | 97.5% | 96.5% | 96.5% (96.5% to 98.7%) | 98.5% (98.0% to 98.8%) | **99.3%** | 99.5% (99.3% to 99.8%) | 99.7% (99.5% to 99.8%) | 100.0% |
| compromised (213 orders) | 49.7% | 65.0% | 80.9% (76.9% to 80.9%) | 83.8% (82.4% to 84.7%) | **70.5%** | 77.4% (70.5% to 77.4%) | 80.5% (77.4% to 82.4%) | 98.3% |
| fat finger (172 orders) | 20.1% | 11.1% | 69.6% (25.6% to 75.3%) | 82.5% (70.4% to 82.5%) | **82.5%** | 82.5% (82.5% to 82.5%) | 82.5% (82.5% to 83.6%) | 94.3% |
| runaway (528 orders) | 43.2% | 80.9% | 96.5% (92.9% to 98.2%) | 98.2% (98.1% to 99.8%) | **98.8%** | 100.0% (100.0% to 100.0%) | 100.0% (100.0% to 100.0%) | 100.0% |
| stale price (17 orders) | 0.0% | 0.0% | 16.9% (5.2% to 74.3%) | 76.7% (65.4% to 81.1%) | **96.9%** | 96.9% (96.9% to 96.9%) | 96.9% (96.9% to 96.9%) | 96.9% |
| adaptive colluders (never trained on) | 91.8% | 91.6% | 91.9% (91.8% to 92.3%) | 93.0% (92.5% to 94.7%) | **99.4%** | 99.5% (99.4% to 99.5%) | 99.6% (99.5% to 99.6%) | 99.8% |

- **Zero-shot is where programming the weights pays.** With no example of the family, fat finger goes from 11.1% (trees only) to
  82.5%, runaway from 80.9% to 98.8%, stale price from 0.0% to 96.9%, the adaptive colluders from 91.6% to 99.4%.
- **Compromised agents remain the weak row** (70.5% zero-shot). Their gate-allowed orders are sell-everything orders that look like
  an honest liquidation; the only programmed signature is that they arrive off the agent's schedule.
- **One label is a real weight edit where the base model has no prior.** On the trees-only base, one labelled fat-finger order takes
  the family from 11.1% to a median of 69.6%, one runaway order from 80.9% to 96.5%, one compromised order from 65.0% to
  80.9%. Stale price needs five (0.0%, 16.9%, then 76.7%).
- **One label does little where the programmed prior already covers the family, and almost nothing for the adaptive colluders**
  (91.6% to 91.9% on the trees-only base): the orders the base misses there sit inside honest flow on every coordinate, so the
  edit is either narrow or refused. The spread across draws is wide and is reported, not hidden.
- The worst honest cost of any edit set in these experiments was 0.58% of honest orders newly held.
- Stale price has 17 held-out orders; its percentages move in steps of several points.

### Ablations

| variant (0.25% budget) | held-out: bad $ stopped | honest held | adaptive: bad $ stopped | honest held |
|---|---|---|---|---|
| v2 shipped (programmed units + monotone trees) | 99.78% | 0.26% | 99.32% | 0.28% |
| v2 trees only (no programmed units) | 99.84% | 0.33% | 91.97% | 0.30% |
| v2 without the schedule features and unit | 99.79% | 0.28% | 99.16% | 0.29% |
| v2 without monotone constraints | 99.86% | 0.27% | 99.53% | 0.27% |
| v1 architecture (35 features, trees only) | 99.68% | 0.41% | 92.17% | 0.37% |

The schedule features (an agent's order arrives off its own established cadence) are strong in this simulator because simulated
honest agents are perfectly periodic. Real agents are not, so the row without them is the more conservative reading; the difference
is small.

### Adversarial robustness and the cost of evasion

`adversary.py` gives an attacker ten colluding agents and nine knobs (order schedule and probability, size range, window length,
price aggression, one ticker or many, and "warm-up" noise orders that stop an agent from ever having a baseline to break). It knows
the model and its threshold and searches (81 simulated 4-day runs per target: random draws, then perturbations of the best)
for the parameters that maximise bad dollars that are allowed by the gate **and** not held by the model. Winners are re-measured on
three fresh seeds. Both models are at the 0.25% budget unless stated.

| attacker (10 colluding agents, 600-agent swarm, fresh seeds) | bad $ the gate allows / day | v2 stops | v2 lets through / day | v1 stops | v1 lets through / day | v1 at a 1% budget stops | lets through / day |
|---|---|---|---|---|---|---|---|
| naive adaptive colluder (the `stealth.npz` behaviour) | $2,782,679 | 99.4% | **$16,683** | 91.8% | **$227,906** | 94.7% | $147,860 |
| optimised against v1 | $3,705,845 | 98.7% | **$46,650** | 85.4% | **$545,434** | 92.2% | $297,054 |
| optimised against v2 | $1,958,223 | 41.4% | **$1,141,096** | 78.8% | **$418,577** | 85.0% | $297,356 |

- Against the naive adaptive colluder and against the attack tuned on v1, v2 lets through roughly a tenth of what v1 does.
- **Against its own optimised attacker, v2 is worse than v1 is against its own**: the worst case found for v2 is about twice the worst
  case found for v1, and v1 happens to stop most of the attack that was tuned on v2. Each model has a blind spot the other does not;
  the search is small, so these are lower bounds on what an attacker can do, not upper bounds.
- **What the attacker had to give up.** The winning attack on v2 (`{"aggr": 0.0005, "groups": 2, "hi": 0.3826, "lo": 0.2186, "one_ticker": 1, "p": 0.6154, "period": 5, "warm": 0.0, "window": 1159}`) acts once every 5 steps instead of every step, sends
  a quarter to a third of the cap instead of slices just under the threshold, and never bursts. Each of its agents then looks like a busy
  honest market maker with larger clips, moving $114,110 per agent per day. Evasion costs it throughput (what it
  gets past v2 is 41% of what the naive colluder gets through the gate) and forces a long window. It does not cost it everything.
- **What this means.** A per-order model cannot separate an agent that imitates a heavy honest agent. What bounds that attacker is
  the signed daily cap, the number of agents it controls, and portfolio-level signals (next section). Next steps that the evidence
  points to: score with both tree sets (an attacker must then evade both blind spots), and add group-level concentration (the share of
  an envelope's daily flow that comes from its few heaviest agents on one ticker and side) as an invariant.

The winning attack on v1 was `{"aggr": 0.0007, "groups": 2, "hi": 0.4919, "lo": 0.3314, "one_ticker": 0, "p": 0.9351, "period": 4, "warm": 0.0, "window": 938}`.

### In the arena

`og-risk arena` replays a recorded decision stream inline, point-in-time:

| stream | bad $ the gate allowed | after the risk layer | honest orders tightened (v2) | (v1) | scoring time |
|---|---|---|---|---|---|
| synthetic, seed 7, 1,000 agents, 2,000 steps | $7,965,456 | $0 | 0.11% (19 orders) | 0.40% (72 orders) | 41 µs median, 139 µs p99 |
| recorded Binance public prices, 1,000 agents | $5,027,887 | $0 | 1.03% (9 orders) | 1.82% | 40 µs median, 234 µs p99 |

The dashboard's Swarm arena shows the same replay for every run, and `/api/arena/run` returns it under `risk` (same shape).

## Which decision paradigm, where

Is a learned model the right tool at all? For the decision made **while the order waits**, here is what each option can and cannot do.
Columns (a), (b) and (d) are measured in this repository's result files. Column (c) was measured live by the project in
`results/decision_paradigms/llm_judge.json` (this page made no model calls).

| | (a) deterministic code rules | (b) programmed + learned weights | (c) LLM judging each order in context | (d) simulation / mathematical risk models, distilled |
|---|---|---|---|---|
| what it is here | the L5 gate: caps, band, allow-list, shared daily budget at trusted prices | this page | a model reads the order, the agent's recent history and the mandate, and answers allow/hold/refuse | closed-form or simulated portfolio risk (budget drain, concentration, exposure), reduced to a formula or a tiny model |
| latency on the order path | microseconds | 40 µs median, 142 µs p99 (measured) | 2.6 s median, 6.5 s p95 (measured) | 0.78 µs for the drain forecast (measured); the simulation behind it runs offline |
| cost per decision at swarm scale | none beyond CPU | none beyond CPU; one core scores about 20,000 orders/s | US$0.05 for 200 calls with a small fast model, about US$0.26 per 1,000 orders, plus a network and rate-limit dependency on the order path | none beyond CPU online; simulation cost is offline |
| calibration | not a probability: yes or no | measured: ECE 0.00062 held-out, 0.00077 on adaptive colluders | self-reported confidence is not calibrated without a separate calibration set | as good as the model's assumptions: the closed form below is poorly calibrated (ECE 0.1538) |
| adversarial robustness | cannot be argued with; can be worked around inside the limits (the $8.0M collusion) | can be evaded by imitating heavy honest agents (measured above); tighten-only bounds the damage to missed holds | reads attacker-controlled text (rationales, tickers, news): **prompt injection is a direct attack on the judge**; outputs vary run to run | hard to game per order because it looks at the aggregate; an attacker can still stay under the aggregate thresholds |
| explainability | exact: the rule and the number | unit fired plus feature values in plain English; tree attributions are approximate | fluent, but a rationale is not a faithful account of the computation | exact: a formula over state |
| good at | invariants that must never break, whatever anyone says | patterns across agents and time at order speed; known signatures with zero examples; new signatures from one label | reading unstructured context: whether a stated rationale matches the order, whether a news trigger is plausible, triaging a hold for the human | questions about the envelope or portfolio rather than the order: will the budget run out, is exposure concentrating |
| bad at | anything not written down in advance | attackers who look honest per order; regimes it has not seen | deciding in microseconds, cheaply, reproducibly, under injection | per-order intent; non-stationary demand |

How they fit together for this product:

- **(a) decides what is forbidden.** Nothing else on this page can authorise an order, by construction.
- **(b) decides which allowed orders a human should look at**, inline. It earns its place only as a tightening layer: its mistakes cost
  review time, not money. Most of its value on unseen attacks comes from the programmed units, which are closer to (a) than to
  machine learning: rules with soft edges and a calibrated weight. The honest answer to "do we need ML" is: the learned trees add
  recall in distribution and ranking for the review queue; the programmed units and the invariants do the generalising.
- **(c) does not belong on the order path.** It is four orders of magnitude slower, it costs money per order, and it reads text the
  attacker writes. Its place is the slow lane **after** a hold: summarising the evidence for the human reviewer, checking a stated
  rationale against the order, proposing the `hint` for a one-shot edit, and drafting a mandate for a human to sign. Even there its
  output is advice to a human or an input to `tighten`, never a way to loosen.
- **(d) answers a different question and is the natural answer to the attacker (b) cannot see.** The evasion that works against (b) is
  a group of agents that each look honest; what they cannot hide is the aggregate.

**(c) measured head to head.** `results/decision_paradigms/llm_judge.json`: on a stratified sample of 60 bad and 140
honest gate-allowed orders from the seed-7 arena stream, judged one by one:

| judge | bad $ stopped | bad orders stopped | honest orders held | latency p50 | latency p95 | cost |
|---|---|---|---|---|---|---|
| risk model (v2) | 100.0% | 100.0% | 0.0% | 196 µs | 569 µs | none beyond CPU |
| LLM judge `deepseek/deepseek-v4.1-flash-1017` | 98.8% | 96.7% | 9.3% | 2.6 s | 6.5 s | US$0.05 for 200 calls |
| LLM judge `qwen/qwen3.8-flash` | 99.3% | 95.0% | 7.9% | 6.2 s | 15.6 s | US$0.10 for 200 calls (14 errors, held) |

Every fast decision API reachable from the test location was tried on the same 200 orders (`judges` in the same file).
`google/gemini-3.5-flash-lite`, `openai/gpt-6-luna` and `anthropic/claude-haiku-5.5` are refused by OpenRouter in this region
(HTTP 403, nothing billed); OpenAI's own API is reachable (`OG_PROVIDER=openai`) but the account had no credits. `liquid/lfm-2.5-24b-a2b`
answered all 200 calls with empty content after spending its whole output budget reasoning (US$0.22): a judge that does not answer
holds everything. The two judges that worked agree with each other and with the conclusion below: they find almost all bad dollars,
hold 8 to 9% of honest orders, and take seconds per order.

The LLM judge is a credible reviewer (it finds almost all of the bad dollars) and an expensive, slow, noisy gatekeeper: it holds
9.3% of honest orders on this sample, which at swarm scale is thousands of false holds a day, and 3 of its calls
errored and were counted as holds. Three cautions on reading this table. The rates are on a stratified sample, not the population.
The risk model's latency in that file (p50 196 µs) was taken by a different harness than `results/risk/latency.json`
(40 µs); both are microseconds. And **seed 7 does not overlap the model's training data**: the corpus uses seeds 100 to 147
(`dataset.default_specs`), the adaptive colluders 300 to 307, the attacker search 900 to 903, and `default_specs` states that seed 7
is never used. It is, however, the same simulator and the same attack families the model trained on, so the risk model's 100% here is
an in-distribution result; its out-of-distribution numbers are the adaptive-colluder and white-box rows above. The test did not include
injected rationales, which is the attack an LLM judge is most exposed to.

**Deterministic portfolio limits now cover part of what the model used to catch.** A signed mandate can carry
`maxSymbolDailyNotionalUsd`, `maxPositionUsd` and `maxOrdersPerDay`, enforced in code (`gate.portfolio_reasons`). Collusion that splits
one position in one ticker runs straight into a per-symbol daily cap, and a runaway loop into an order-count cap, with no model
involved. Measured on the seed-7 stream by applying an illustrative per-symbol daily cap, in order, to the orders the gate allowed
(`results/risk/portfolio_limits_overlap.json`; the cap sizes are ours, the recorded envelopes carry none):

| per-symbol daily cap | bad $ the cap alone refuses | honest $ it refuses | bad $ still passing | of which the risk model stops |
|---|---|---|---|---|
| 1x the envelope's daily cap divided by its number of symbols | $6,145,096 (77.1%) | 0.16% | $1,820,360 | $1,820,360 (100.0%) |
| 2x the envelope's daily cap divided by its number of symbols | $4,817,159 (60.5%) | 0.14% | $3,148,296 | $3,148,296 (100.0%) |
| 3x the envelope's daily cap divided by its number of symbols | $3,490,276 (43.8%) | 0.12% | $4,475,180 | $4,475,180 (100.0%) |

So a per-symbol cap removes between roughly half and three quarters of the bad dollars by rule, at a small honest cost, and that is the
better tool for that part: exact, signed, and impossible to evade by looking honest. The model's added value is what passes the cap:
attacks spread across tickers, behavioural breaks, and mistakes inside the limits. On this stream it stops all of the remainder.
The white-box attacker above (one ticker, long window) is exactly the pattern a per-symbol cap bounds.

**Conclusion.** Code says yes or no. The model only tightens, inline, in microseconds. The LLM is a slow escalation-lane reviewer and a
mandate drafter, never the gate.

**Prototype of (d): will the envelope's shared daily budget run out today?** `portfolio.py` keeps O(1) state per envelope (reserved
dollars today, mean and variance of reservations per step over the last 50 steps) and computes
`P(exhaust) = Φ((m·T − R) / (s·√T))` for remaining budget R and T steps left. Ground truth is the simulator: did the gate refuse an
order for the daily cap later that day. Sampled every 10 steps on the 12 held-out runs (6,566 envelope-states not yet exhausted,
base rate 26.9%):

| forecaster | ROC AUC | Brier | ECE | recall at P ≥ 0.5 | precision at P ≥ 0.5 |
|---|---|---|---|---|---|
| closed form (no training) | 0.7969 | 0.1724 | 0.1538 | 63.3% | 65.0% |
| logistic distilled from simulated days | 0.8179 | 0.1642 | 0.1028 | 8.1% | 78.1% |
| used fraction of the cap alone | 0.5884 | | | | |

It costs 0.78 µs per call and its first alarm comes a median of 392 steps before the first cap refusal on days that
exhaust. It is clearly better than watching the used fraction, and it is **not good enough to act on alone**: AUC 0.7969 and poor
calibration, because demand in the arena is not stationary (a collusion window starts mid-day and the recent rate says nothing about
it beforehand). The distilled logistic is a little better ranked and far too timid at 0.5. This is a useful dashboard signal and a
candidate invariant for (b), not a decision. It is not wired into the scorer.

## Limits

- Everything is simulated: the agents, their failure modes and the attackers are ours. The schedule features in particular lean on
  simulated honest agents being periodic.
- A white-box attacker gets more through v2 than through v1 in the worst case found (above). The search is small; a better attacker
  will do better.
- The arena replay scores recorded decisions. It does not re-simulate the budget a refused colluder would have freed for honest agents.
- Holds cost human attention. The hold threshold is a review-capacity decision: the model file carries the threshold for each of the
  four budgets under `thresholds.by_honest_hold_budget`.
- One-shot edits depend on the example: some labels generalise, some do not, and an attack hiding inside honest flow gets no edit.
- The one-shot reference is recent unflagged flow, which can contain the attack's own undetected orders; only the labelled agent's
  orders are removed.

## Run it

```bash
.venv/bin/og-risk build-data      # 48 arena runs + 8 adaptive-colluder runs (several minutes)
.venv/bin/og-risk train           # fit v2 and the v1 architecture, apply the ship rule, export data/models/order_risk.json
.venv/bin/og-risk program         # the programmed units: weights, honest firing rate, recall by family
.venv/bin/og-risk eval            # budgets, calibration, regime/time splits, leave-one-family-out with 0/1/5 labels, ablations
.venv/bin/og-risk oneshot-eval    # only the leave-one-family-out part
.venv/bin/og-risk attack          # white-box attacker and cost of evasion
.venv/bin/og-risk demo-oneshot    # one and five labels on the adaptive colluders, through the shipped model
.venv/bin/og-risk arena --stream results/arena/arena-s7-k1000-t2000.jsonl
```

Results land in `results/risk/`: `eval.json`, `shipped_model.json`, `programmed_units.json`, `adversary.json`, `oneshot_demo.json`,
`drain_forecast.json`, `portfolio_limits_overlap.json`, `latency.json`, `arena-replay-*.json`, and `v1_shipped_reference.json` (the first model's published numbers).

In Python:

```python
from orderguard_risk.scorer import RiskScorer, tighten
scorer = RiskScorer.load()
scorer.set_envelopes({"core": {"per_order": 25_000, "daily": 8_000_000, "step_up": 20_000, "band_pct": 1.0}}, steps_per_day=500)
risk = scorer.score(event)                       # point-in-time; risk["units"] names the programmed units that fired
decision = tighten(gate_decision, risk)
scorer.observe(event)
scorer.label_attack(bad_event, note="case 12")   # one label -> a weight edit; similar orders are held from now on
```
