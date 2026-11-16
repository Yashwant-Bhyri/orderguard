# Four-system benchmark

This is the experiment section 4 of [AUTONOMY.md](AUTONOMY.md) asked for. The same scripted agents trade through four kinds of control, in eight scenarios, on a simulated market. We measure harm and usefulness together. The question is whether continuous autonomy control (D) stops a failure that a competent conventional risk stack (C) lets through, and what that costs.

Results: [results/vision/benchmark.md](../../results/vision/benchmark.md) (tables), `results/vision/benchmark.json` (means, 95% intervals, verdicts), `results/vision/benchmark_runs.json` (every run), and `results/vision/sensitivity.json` (knob sweep).

## Reproduce

From the repository root:

```bash
PYTHONPATH=python python -m orderguard_autonomy.bench --seeds 20
```

```bash
PYTHONPATH=python python -m orderguard_autonomy.bench --sensitivity --seeds 10
```

```bash
PYTHONPATH=python python -m orderguard_autonomy.judgement
```

The main run takes about two minutes on a laptop. Every figure except latency is deterministic for its seed. A fast smoke test is in `python/tests/autonomy/test_autonomy_bench.py`.

## The world

- **Market.** `orderguard_sim.ImpactMarket` with 12 US equities and ETFs, Student-t (df 5) shocks with GARCH variance, a common correlation, and square-root impact. One step is one minute; 390 steps make a day.
- **Broker.** It receives orders, fills them if they are marketable after impact, and cancels them after 3 steps. Reports can arrive late, never arrive, or the order can be lost before it reaches the venue. Every 30 steps the broker's complete order list and positions are sent for reconciliation.
- **Agents.** They are scripted, not language models. Each proposes orders with a typed intent (thesis, evidence hashes, claims). Every proposal carries a ground-truth label (legit or harmful), and no system ever sees it.
- **Paper only.** Nothing in `orderguard_autonomy/bench` can reach an exchange.

## The systems

| System | What it is |
|---|---|
| A | Bare agent: every proposal goes to the broker. |
| B | Today's OrderGuard: the signed envelope from `orderguard_arena`, with its position cap set to the issuer cap. |
| C | A competent conventional stack: worst-case working-order position per symbol, firm and per-agent credit, max order size, price band, rate limit with a per-agent burst kill, firm drawdown kill switch, and large-order review. It is deployed per venue and treats an order with no acknowledgement after 5 steps as not working, which are common settings. |
| C+ | C with sector caps, checks consolidated across venues, and unacknowledged orders kept as working until the broker resolves them. This is C with its two weak settings fixed, so D is compared against a strong baseline too. |
| D_auth | C+ plus stage 1 of the design: signed contract compiled to predicates, conservative projection over all working orders, hierarchical escrow of dollars and ES risk units, declared-scenario loss caps, and an ES budget. Model-based checks can only hold. |
| D | D_auth plus stage 2: leases with epochs, typed intent records bound to each order, evidence provenance, claim flags, drift, behavioural herding, pacing and loop detection, and decision certificates checked by the receiver. |

D runs C+'s checks first, and a C+ refusal stands. So D can never be looser than C+.

**Held orders never execute.** After 30 steps a conservative reviewer denies them, and their capacity is released. So every hold counts at its full usefulness cost. A real reviewer would approve some of them.

## What is measured

- **Headline harm.** Each scenario has one harm measure, defined by what that scenario is about (see the table below).
- **Hard-limit breaches.** An independent auditor (`bench/audit.py`) restates the issuer, sector, gross and declared-scenario limits and replays every fill at the trusted marks. It counts only breaches that grew from a fill.
- **Legit completion.** Legitimate dollars executed divided by legitimate dollars proposed, both at the trusted price.
- **Also recorded:** holds and refusals of legitimate orders, the share of harmful dollars blocked, p50 decision latency, certificate size, and receiver refusals.
- **Verdict.** "D better" requires the mean to be better. "Separated" means the two 95% intervals do not overlap.

## Results (20 seeds)

| Scenario | Headline harm | C | C+ | D | D legit completion |
|---|---|---|---|---|---|
| Correlated buying | herd exposure before the shock ($) | 501,022 | 498,227 | 275,341 | 98.0% |
| Objective drift | off-objective buying after drift began ($) | 215,775 | 215,775 | 45,200 | 98.1% |
| Coordinated misinformation | bought on the false rumour ($) | 69,281 | 69,281 | 0 | 94.9% |
| Delayed acks | duplicate fills ($) | 87,384 | 56,333 | 0 | 94.8% |
| Volatility regime | risk added while true ES was over budget ($) | 380,433 | 380,433 | 5,106 | 99.4% |
| Budget starvation | slow agents' completion (share) | 0.394 | 0.388 | 0.627 | 12.8% |
| Cross-venue | NVDA exposure over the cap ($) | 99,227 | 386 | 386 | 99.9% |
| Tool compromise | compromised orders executed ($) | 162,281 | 162,281 | 0 | 92.6% |

- **D is better than C in all eight scenarios**, with separated 95% intervals.
- **D is better than C+ in seven.** Cross-venue is a tie: once C's checks are consolidated across venues, C+ already sees the combined position.
- **D had zero hard-limit breaches** in every scenario and seed, and its escrow invariants held in every run.
- **Certificates:** the receiver refused none. They average 890 to 907 bytes, depending on the scenario.

### What carried each result, and what it cost

- **Correlated buying.** The behavioural herding monitor groups agents by sector-level flow, plus a shared source in their evidence, and holds the group once its combined net buying passes 15% of capital. The herd still built $275k. The cap slows the herd but does not stop it, because each agent's own orders pass every per-agent check.
- **Objective drift.** Most of the stopping comes from the drift monitor's style-distance check. The CUSUM alarm on the off-objective rate fired in every seed, a mean 316 steps (about four trading days) after onset, with no false alarms. Control agents with the same mandate were held 0.25 times per run.
- **Misinformation.** Provenance collapses reposts and near-copies to their one root source, so a rumour with nine copies counts as one source. A buy on "news" needs two independent sources. Confirmed news still executed ($61,685 against C's $65,016).
- **Delayed acks.** Two things stop duplicate fills:
  - each intent authorizes at most its quantity, so a retry under a new key is the same intent;
  - an unacknowledged order stays reserved until reconciliation resolves it.

  C+ keeps unacknowledged orders as working, yet it still allowed $56k of duplicates, because it has no notion of intent.
- **Volatility regime.** The rolling covariance, together with the regime detector's stressed covariance, held new buying once the ES budget was used.
  - **Limit found:** the book stayed over budget in all 240 post-shock steps under every system. Peak true ES was $137k under C and $133k under D. A pre-trade control can stop adding risk, but it cannot remove risk already held. De-risking needs a separate, owner-approved action.
  - D's own one-day ES model passed its backtest: 8.4 VaR exceptions against 9.75 expected, Acerbi-Szekely Z2 −0.12.
- **Budget starvation.** Guaranteed fading shares keep room for slower agents. Their completion rose from 0.39 to 0.63. The fast agent paid for it: D held 210 of its orders, and overall legit completion fell to 12.8%. D_auth alone made starvation worse (0.10), because escrow is first come, first served. This is a real trade-off, not a free win, and the owner should set the share.
- **Cross-venue.** D adds nothing over C+, because the gain comes from consolidation, which C+ already has.
- **Tool compromise.** The compromised tool's orders did not match the agent's intent record, so D refused them and quarantined the lineage. The spawned helpers held no lease of their own, so they were refused too. **This rests on an assumption:** intent records are written by the agent runtime, not by its order tool. If the tool can also write intents, D falls back to D_auth's caps, which let $132k through.

### Sensitivity of the two model knobs that carry D's herding and drift wins

Seeds 1 to 10 (`results/vision/sensitivity.json`):

- **Herding cap, as a share of capital.** At 0.05 / 0.10 / 0.15 / 0.25 / 0.40, herd exposure was $301k / $270k / $281k / $310k / $417k, against C's $508k. Legit completion stayed between 92% and 98%. D beats C at every setting tried. Below 0.15 the cap holds more without lowering herd exposure further.
- **Drift CUSUM threshold h.** At h = 3 / 4.5 / 6 / 8 / 10, off-objective buying was $29k / $38k / $40k / $40k / $40k, against C's $208k. The alarm came 247 / 314 / 334 / 379 / 416 steps after onset. Detection was 100% at every h; false alarms were 0.4 per run at h = 3 and zero above. At h = 3 legit completion fell to 91.6%, with 43 holds per run. From h = 6 up the harm figure does not move, which shows that the style check, not the CUSUM, does most of the stopping.

## Limits: what this benchmark does not show

- **The agents are scripted.** No language model trades here. Each scenario was written to exhibit one failure. That makes the result a test of mechanisms against known failure shapes, not evidence that D catches failures nobody wrote down.
- **The same team wrote the scenarios and system D.** To keep them honest:
  - C+ fixes C's two weak settings;
  - labels come from ground truth no system sees;
  - an independent auditor restates the limits;
  - D's losses and costs are reported (starvation, the regime de-risking limit, cross-venue parity).

  Even so, an outside review of the scenarios is the right next step.
- **The market is simulated.** Section 6 of AUTONOMY.md says backtested wins are weak evidence. The next test is shadow mode on live-forward paper data after the models' training cutoff.
- **Every hold is scored as a denial**, which overstates D's usefulness cost. Review burden (the number of holds) is reported so it can be priced.
- **Latency figures depend on the machine.** D's p50 is roughly 0.2–0.5 ms in Python, against a few µs for C. That is fine for agent-paced trading, and not tuned.
