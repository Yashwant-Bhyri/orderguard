# Order risk: a learned, tighten-only layer for agent swarms

The code gate (L5 to L8) refuses every order that breaks the signed mandate. It cannot see an order that is individually fine but part
of a bad pattern: five agents splitting one position into orders that each sit just under the step-up threshold, a runaway loop of
small legal orders, an agent whose sizes suddenly jump to the top of its envelope. In the 1,000-agent arena, colluding agents whose
every order was inside the envelope got **$8.0M** of bad notional through and starved honest agents of daily budget
([ARENA.md](ARENA.md)).

`python/orderguard_risk` scores every order the gate **allowed**, from behaviour across agents and time, the way a card network
scores payments. It is the semantic layer the rules lack, with one constraint that makes it safe to deploy:

> **It can only tighten.** `tighten(decision, risk)` returns the stricter of the gate's decision and the model's action: allow can
> become hold (a human decides) or refuse; hold can become refuse; refuse never changes; an unknown decision becomes refuse. A wrong
> or attacked model can cost legitimate flow, but it cannot authorise anything the signed mandate forbids. A property test checks
> this over 5,000 random decisions.

## How it works

```
proposal ─► code gate (L5) ──allow──► FeatureEngine.featurize(event)   point-in-time: only events before this one
                 │                     tree ensemble (80 trees, JSON) ─► calibrated risk p
                 │                     p ≥ hold threshold   ─► hold        p ≥ refuse threshold ─► refuse
                 │                     analyst prototypes   ─► hold        (one-shot labels, no retraining)
                 └──hold / refuse────► unchanged                           tighten() is the only way decisions combine
```

- **Features** (`features.py`, 35 behavioural columns): order against envelope (share of the per-order cap, step-up and daily cap,
  near-cap flags, envelope pace and day demand, the agent's share of the day), price (distance of the limit from the trusted price,
  position in the band), the agent's own baseline (size z-score, ticker novelty, side flips, inter-arrival time, bursts, duplicate
  keys, how often it sits near the cap), **cross-agent coordination** (distinct agents on the same ticker and side in short and
  medium windows, size similarity, same-step bursts, a co-occurrence graph of agents that repeatedly trade together, side pressure,
  ticker flow) and market volatility. Every window is a deque with O(1) amortised update, so features run inline at authorisation
  time. A test checks that appending later events never changes an earlier feature vector.
- **Model**: gradient-boosted trees (`HistGradientBoostingClassifier`, 80 trees, depth 5), exported to plain JSON (0.15 MB) and
  scored in pure Python with no sklearn, numpy or pickle at runtime. A test checks the JSON inference equals sklearn to 1e-6. Platt
  calibration and both thresholds are fitted on validation seeds only: hold flags 1% of honest allowed orders, refuse 0.05%.
- **Reasons**: every hold or refuse comes with the top contributing features in plain English (path attribution over the trees).
- **One-shot memory**: `scorer.label_attack(event)` turns one analyst-labelled event into a prototype. Its radius is set at labelling
  time so it would have captured at most 0.5% of the recent orders the model did not flag. No retraining; it can only add holds.
- **Text**: the generator also writes a rationale for each order and a hashed-n-gram text model exists, but those rationales are
  produced from the label, so text features partly encode the answer. **The shipped model uses behavioural features only**
  (`og-risk eval --with-text` reports the text variant separately).

Also built, not shipped: a numpy MLP (measured below; trees were better calibrated and faster), weight averaging of MLP checkpoints
(`models.soup`, and an EMA option in `MLP.fit`) for continual learning across time windows, and the text model. The weight-averaging
path is implemented but has not been evaluated against the trees; the time-split row below is the trees' answer to
drift.

## Data

`og-risk build-data` runs the arena engine 48 times across seeds, swarm sizes (300 to 1,000 agents), archetype mixes, market regimes
(calm, normal, volatile, shifted) and envelopes: **592,988 labelled proposals** (`data/risk/corpus.npz`, 10.6 MB). Labels come from
the arena's oracle: honest, colluding, compromised (four techniques), fat finger, runaway loop, stale price, off-list, fake news.
Seed 7, the arena's published run, is never used. A separate set of 8 runs uses **adaptive ("stealth") colluders** that randomise size, timing and tickers to look like honest agents
(`stealth.npz`, 138,901 proposals). The model never trains on them.

## Results

All numbers are on gate-**allowed** orders (the model's job), measured with the shipped behavioural model; `results/risk/eval.json`
has every protocol, `results/risk/shipped_model.json` the exported model's own test numbers.

| protocol | orders | PR-AUC | bad $ held or refused | honest orders held | hold precision |
|---|---|---|---|---|---|
| held-out seeds | 126,579 | 0.994 | 99.8% | 1.07% | 72% |
| regime shift: train calm/normal, test volatile | 123,744 | 0.996 | 99.9% | 1.60% | 59% |
| regime shift: test "shifted" | 126,848 | 0.993 | 99.8% | 1.73% | 72% |
| time split: train early steps, test late | 216,793 | 0.996 | 99.95% | 1.02% | 70% |
| **adaptive colluders, never trained on** | 125,345 | 0.943 | **94.0%** | **0.86%** | 87% |

Calibration on held-out seeds: Brier 0.0009, ECE 0.0001. The MLP reached PR-AUC 0.981 with more false holds (1.4%).

**Leave one family out** (train without it, test on it) shows where the model generalises and where it does not:

| family held out | its bad $ caught |
|---|---|
| collusion | 99.3% |
| compromised agents | 64.7% |
| runaway loops | 59.2% |
| fat finger | 22.5% |
| stale price | 0% (17 orders) |

Coordination generalises because its signature is behavioural. Single-agent mistakes of a kind the model has never seen do not, which
is why those stay the code gate's job: fat fingers and stale prices that break a cap or the band are refused by L5 regardless.

**Feature ablation** (held-out seeds): envelope features alone reach PR-AUC 0.839; the agent baseline and cross-agent features take it
to 0.994. Ordinary colluders in this generator are easy (even envelope-only features catch them); the adaptive set is the real test.

**One analyst label** (`og-risk demo-oneshot`, 10 trials, each labelling ONE missed stealth order and measuring only on the other runs):
stealth dollars caught rose from 93.6% to a median of 94.5% (range 93.6% to 99.5%), with a median of 0.013% of honest orders newly held
(at most 0.5%). Some labels help a lot and some barely; that spread is reported, not hidden.

**In the arena** (`og-risk arena`, inline point-in-time replay of a recorded decision stream):

| stream | bad $ the gate allowed | after the risk layer | honest orders tightened | scoring time |
|---|---|---|---|---|
| synthetic, seed 7, 1,000 agents, 2,000 steps | $7,965,456 | $0 | 0.40% | 39 µs median, 108 µs p99 |
| recorded Binance public prices, 1,000 agents | $5,027,887 | $0 | 1.82% | 42 µs median, 178 µs p99 |

The dashboard's Swarm arena shows the same replay for every run, and `/api/arena/run` returns it under `risk`.

## Limits

- Everything is simulated: the agents, their failure modes and the colluders are ours. A real adversary would adapt to the model; the
  adaptive set is one step of that, not the end of it.
- The arena replay scores the recorded decisions. It does not re-simulate the budget a refused colluder would have freed for honest
  agents, so it understates the benefit to honest flow.
- Holds cost human attention: at the shipped threshold the model flags about 100 orders per run-day in a 1,000-agent swarm. The hold
  threshold is a review-capacity decision and is set in the model file.
- Unseen single-agent failure modes are weak (table above). Retraining with new labelled runs, or one-shot labels, is the remedy.

## Run it

```bash
.venv/bin/og-risk build-data      # 48 arena runs + 8 adaptive-colluder runs (several minutes)
```

```bash
.venv/bin/og-risk train           # fit, calibrate, export data/models/order_risk.json (seconds once features are cached)
```

```bash
.venv/bin/og-risk eval            # every protocol -> results/risk/eval.json
```

```bash
.venv/bin/og-risk arena --stream results/arena/arena-s7-k1000-t2000.jsonl
```

In Python:

```python
from orderguard_risk.scorer import RiskScorer, tighten
scorer = RiskScorer.load()
scorer.set_envelopes({"core": {"per_order": 25_000, "daily": 8_000_000, "step_up": 20_000, "band_pct": 1.0}}, steps_per_day=500)
risk = scorer.score(event)          # point-in-time
decision = tighten(gate_decision, risk)
scorer.observe(event)
```
