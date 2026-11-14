# Evidence in detail

The numbers behind the README's [Proof](../README.md#proof) section, with the lab's own terms. Every figure on this page is rebuilt from the committed result files by `og-arena verify --quick`, which fails if a sentence here goes stale.

Terms used below: the attack lab groups its cases into **families** A to F (A to D try to make the agent act on false information or injected instructions, E tries to make it drop a legitimate trade, F holds natural errors). An **arm** is how much of OrderGuard a run uses: `naive` (bare model, no checks), `gate_only` and `full`. Layers are numbered L1 to L8 ([ARCHITECTURE.md](ARCHITECTURE.md)): L5 is the mandate gate, L7 the corroboration check for standing rules, L8 the TypeScript receiver.

## Agents against fake information

The fixed-case live comparisons below use DeepSeek V4.1 Flash 1017. The separate sandbox rows use scripted agents in simulation. The report also covers an earlier Flash variant, other scripted controls and detector experiments. [Results report](RESULTS.md) · [Fixed-case runs](../results/runs/20261110T230149.jsonl) · [Sandbox runs](../results/sweeps/20261110T230155.jsonl)

| Simulated outcomes | Bare model | Full guard |
|---|---|---|
| Attack goals achieved (families A–D) | 7 of 180 | **0 of 180** |
| Attacker actions executed (same A–D trials) | 0 of 180 | 0 of 180 |
| Planted claims repeated without a matching doubt term (belief-targeted A–D trials) | 7 of 48 | **0 of 48** |
| Legitimate trades dropped (family E denial-of-service trials) | 15 of 21 | **1 of 21** |
| Clean controls completed | 17 of 20 | 18 of 21 |
| Sandbox attack goals achieved (22 techniques × 6 seeds) | 14 of 130 evaluable trials, $9,762.50 executed notional | **0 of 132**, $0 executed notional |
| Sandbox benign-twin tasks completed | 113 of 138 | **132 of 138** |

One bare-model clean control and two bare-model sandbox attack trials ended in errors. Benign-twin utility includes six natural-error scenarios and correct abstention in 18 trigger scenarios per arm. [Clean-control and sandbox breakdowns](RESULTS.md)

- An adaptive attacker recorded **0 observed successes** across five goals with up to five rounds each. One campaign stopped after two evaluated rounds when the attacker produced unusable output. [Adaptive runs](../results/adaptive/20261110T232836.jsonl)
- In a one-envelope, one-day paper-ledger check at shared static prices, **2,372 of 2,372** eligible decisions agreed with the TypeScript receiver. [L8 comparison](../results/arena/l8-agreement-s23-k1000.txt)

## Swarms: 1,000 agents inside shared envelopes

- In the 1,000-agent synthetic benchmark, the strict path processed **58,314 decisions/s** on a 5,000-proposal sample. The inline path had a **9.25 µs p99**, and the end-to-end run processed **28,771 proposals/s**. [Benchmark results](../results/arena/bench.json) · [Exchange-scale bench](BENCH.md)
- In the seeded 1,000-agent run, the arena authorized zero transfers, off-list or look-alike symbols, fake-reference oversize orders, stale-limit proposals or uncorroborated news orders. It held 163 uncorroborated news proposals. [Arena baseline](../results/arena/arena-s7-k1000-t2000.summary.json)
- The baseline authorized $7.97M of bad notional, including $7.43M from one colluding group. The daily cap accounted for 1,068 of the 1,158 legitimate refusals. A separate run with the same seed and a 1% per-agent share authorized $0.91M of bad notional and refused 2.36% of legitimate proposals. [Baseline event log](../results/arena/arena-s7-k1000-t2000.jsonl) · [Fair-share run](../results/arena/arena-s7-k1000-t2000-fairshare.summary.json)
- **The envelope lab** replays the recorded proposals through hundreds of candidate envelopes. The recommended envelope would have authorized 95.9% of legitimate notional, leaked $219,347 per simulated day and refused 2.43% of legitimate proposals. The human reviews and signs the envelope. [Frontier](../results/arena/arena-s7-k1000-t2000.frontier.json)

The full arena write-up is [ARENA.md](ARENA.md).

## The order-risk layer

Rules see one order at a time; coordination only shows across agents and time. `orderguard_risk` scores every order the gate allowed with programmed and learned weights: seven hand-written units state the mandate's semantics and the known attack signatures, and gradient-boosted trees fitted on 592,988 labelled proposals from 48 simulated swarms learn the rest. The two combine by noisy-OR, so data can add risk on top of a programmed unit but cannot explain it away. The model is exported to 0.15 MB of JSON and scored in pure Python (40 µs median, 142 µs p99, features included). [Risk model](RISK.md)

- **It can only tighten.** Allow can become hold (a human decides) or refuse. Nothing the signed mandate forbids can be allowed; a property test checks this over 5,000 random decisions.
- **On the baseline arena stream above,** inline replay held or refused all $7.97M of bad notional the gate allowed, and sent 0.11% of allowed honest orders to a human. On the recorded Binance-price stream: $5.03M to $0, 1.03% of honest orders. Budget a refused colluder would have freed is not re-simulated. [Replay](../results/risk/arena-replay-arena-s7-k1000-t2000.json)
- **On held-out seeds, at a review budget of 0.25% of honest orders,** 99.78% of bad dollars are held or refused with 0.26% of honest orders held (the first model's architecture at the same budget: 99.68% with 0.41%). **On adaptive colluders it never trained on: 99.32% with 0.28% held** (first architecture: 92.17% with 0.37%). [Evaluation](../results/risk/eval.json)
- **Unseen attack families:** with a family left out of training entirely, the programmed units still stop 82.5% of fat-finger dollars and 96.9% of stale-price dollars (trees alone: 11.1% and 0.0%); compromised agents remain the weak family at 70.5%. [Leave one family out](../results/risk/oneshot.json)
- **One analyst label, no retraining.** `label_attack(event)` writes a new unit from one example against honest statistics: one labelled fat-finger order took a model that had never seen the family from 11.1% to a median of 69.6% of that family's dollars (quartiles 25.6% to 75.3%). It does little for attacks that sit inside honest flow.
- **Its limits are measured too.** A white-box attacker that knows the model and imitates busy honest agents gets $1.14M a day past the new model, against $0.55M a day for the attacker tuned on the first model against the first model. Signed per-symbol and position limits in the mandate bound that attacker by rule. [Attacker](../results/risk/adversary.json) · [Which decision paradigm, where](RISK.md#which-decision-paradigm-where)
- The shipped model uses no rationale text: the simulator writes rationales from each order's label, so text features would flatter the scores.

## The review lane

After a hold, a typed decision model (TypeSafe's Jev, via OpenRouter) orders the human queue and reviews mandate drafts. It can only advise or add a hold, never release one. On the 1,002-order flagged queue it needs 530 reviews to open 90% of bad dollars, against 719 first-in-first-out, but the risk model's own ordering needs 470, so it does not beat the model. [Review lane](REVIEW.md) · [Triage study](../results/review/triage.json)

## Detector and model limits

- The recorded earlier DeepSeek Flash detector flagged 35 of 52 false-data chunks in the lab. [Detector results](RESULTS.md#detectors)
- The agent dropped a legitimate trade after a forged owner note in one of 21 DeepSeek Flash 1017 denial-of-service trials with the full guard. [Recorded run](../results/runs/20261110T230149.jsonl#L649)
- On the mixed lab chunk set, the local classifier flagged 56 of 99 attacks and 9 of 174 clean chunks. The earlier DeepSeek Flash detector flagged 82 attacks and 4 clean chunks. The classifier ships off by default. [Classifier evaluation](CLASSIFIER.md)
- Live fixed-case trials cover two variants of one DeepSeek Flash family, with up to three repeats per case and arm. The people who built the defences wrote the cases and techniques. The adaptive campaigns cover a small set of goals and rounds.
