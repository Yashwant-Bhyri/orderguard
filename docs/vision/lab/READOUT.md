# Readout, 2026-11-19: the scan, what I take from it, and where the moat is

This is the lab lead's read of the first wide scan. The scouts' notes are in [scan/2026-11-19/](../scan/2026-11-19/) and are options, not truth. Their numbers come mostly from abstracts and vendor pages and are unverified. Their X/Twitter searches returned almost nothing, so the practitioner view rests on blogs and arXiv. What follows is my own ideation, written against our problem.

## 1. System One, taken apart

| Part | What is off the shelf today | What is not | Where we put the effort |
|---|---|---|---|
| The question it answers | nothing | judging a *delegation* against an owner's purpose (D1) | settled |
| What it sees | trace formats and guardrail classifiers that look at one tool call | the why-graph, recorded at decision time (D3) | high: only the harness can see it |
| Labels | market data, finance Q&A sets, a few agent benchmarks | endorsement labels, planted causes, purpose against behaviour | **highest** |
| The scorer | boosted trees, tabular foundation models, monotone and additive models, small LMs | knowing which fits our data and keeps attribution exact | low: pick it to be debuggable, not novel |
| Training | LoRA and QLoRA, Brier-loss SFT, KTO, RL | the one gate that trains, certifies, calibrates and releases | medium |
| Calibration | temperature scaling, isotonic, conformal risk control | the loss that maps endorsement to a tighten-only risk, and how it handles shift | medium |
| Proof | monotone networks, exact certification, alpha-beta-CROWN | turning mandate clauses into checkable properties | medium-high, and it grows with every clause |
| Evaluation | generic calibration and safety benchmarks | a planted-cause benchmark that others measure against | high |

**The verdict.** The moat is not the model. It is three things: what we see (the graph), what we can label (the label factory), and what we can prove (the property library). So the model should be deliberately plain and as inspectable as possible. Every hour spent on clever architecture is an hour not spent on the parts nobody can copy.

## 2. Four ideas worth testing

### Idea 1. The explanation is the model
The founder's master stroke is weighing the causes behind an action against the purpose it serves. So far we planned to compute that afterwards, with Shapley values over a black box.

Instead, make the scorer additive. The score is a sum of terms, one per cause in the why-graph and one per purpose dimension, plus a few pairwise terms. Explainable Boosting Machines (generalised additive models with pairwise interactions) already work this way. Three consequences follow:

- **Purpose attribution is exact.** It is the model's own terms, not an estimate of them.
- **Proof becomes cheap.** Each term is a small lookup table, so "more leverage never raises approval" can be checked by enumerating every cell. No verifier is needed. The scout found a known trap: correlated features can break monotonicity learned at fit time. So we also monotonise after fitting, and check again when exporting.
- **Debugging becomes direct.** A wrong verdict points at one term, and we can read that term's curve.

The risk is that it is too weak. That is Q1, and E0 tests it first, on CPU.

### Idea 2. Text gets a bounded blast radius
News, notes and the agent's own reasoning are where poisoning enters. A small LM reads them, but it does not decide. It emits a few features (is the source credible, does the claim match its cited evidence, is the language off-purpose). Each feature is clipped to a fixed range and **can only push the score toward holding**.

The product property, true by construction: *no text, however crafted, can make System One more permissive, and it can make it stricter only by a known amount.* Prompt injection becomes a nuisance that causes holds, not a breach.

The scan supports keeping the text channel small. One preprint found that giving a monitor more context made oversight worse, and another found that chain-of-thought is hard for a model to control on purpose but easy to make misleading. That is Q2 and E4.

### Idea 3. The public world already has "stated purpose versus actual book"
US funds file their stated objective (N-1A) and then their holdings every month (N-PORT). Funds whose name implies an investment focus must keep 80% of assets in it (the names rule, amended in 2023). Advisers file a brochure (Form ADV Part 2A), and large managers file quarterly holdings (13F).

Together these form a large, free, real dataset of *purpose against behaviour, with a legal line between fitting and drifting*. Nobody uses it to judge agents. It could pretrain the purpose side of System One before a single owner reviews anything. That is Q3a and E1.

Other places where a stated purpose and actual behaviour are both on record, from the scouts and worth a later look:
- DAO treasury proposals against the transfers actually executed;
- DeFi vault strategy descriptions against onchain fills;
- SEC enforcement orders quoting the mandate that was breached.

### Idea 4. The simulator must be written by a different hand
JUDGEMENT.md already showed the trap. The 0.97 in distribution was the features matching the generator, because one hand wrote both. Under shift it fell to 0.63.

So the label factory needs **independent generator families**: written separately, from different failure descriptions, with at least one family fully held out. Each simulated owner also gets an explicit utility function, so endorsement labels are exact. Real reviews then only have to calibrate per owner, not teach the concept.

If a model trained on our generator cannot score 0.70 on an independent one, nothing downstream matters. That is Q3b and E5, and it may be the most important test here.

## 3. What the scan changed, and what I dropped

- **Reinforced.** Units and magnitudes belong to code, not to the model (a decimal-error loss in February 2026 is exactly what a calibrated judge would miss) (D4).
- **Reinforced.** Calibrate per action class, not with one global score.
- **New.** Plain reward RL makes models overconfident, especially under shift. So: SFT with a Brier term first, KTO for approve and reject logs, RL last if at all.
- **New.** European supervisors (ESMA) treat cumulative changes to an AI component as material. Every retrain needs a release bundle: certificate, calibration report, data manifest and metamorphic tests. That bundle is also something to sell to owners' validators.
- **New.** Signed agent intent (AP2, and FIDO's Verifiable Intent work) is becoming a standard. Our mandate should export to it.
- **Dropped for now.** Sparse autoencoders as the debugging method. The 2025 evidence says they do not beat plain linear probes. They are useful for generating hypotheses, not for proof.
- **Dropped for now.** Graph neural networks over the trace. Nothing published, and graph features fed to an additive or tabular model are the lower-risk path.
- **Dropped for now.** Tabular foundation models as the product model. The strongest one's weights are non-commercial. It stays as a baseline in E0.

## 4. Experiments, smallest first

| # | Answers | Compute | What it does |
|---|---|---|---|
| E0 | Q1 | CPU, hours | Glass box against boosted trees against a tabular foundation model on the existing simulator labels; AUROC and ECE in distribution and under shift; per-term attribution against planted causes |
| E5 | Q3b | CPU, days | An independently written generator family, held out; retrain and score |
| E1 | Q3a | CPU plus downloads | 200-fund pilot: N-1A objective text, N-PORT holdings, names-rule test, hand check of 50 |
| E2 | Q4, Q5 | 1 GPU, about 2 h | No training: shift stress test of two small checkpoints as bounded text-feature readers; real A6000 throughput |
| E3 | Q4 | 1 GPU, about 3 h | Brier-loss LoRA against plain SFT for the text features |
| E4 | Q2 | CPU | 500 injection notes; check that the score never rises (a code test, since it holds by construction) and measure how much it falls |

E0, E5 and E1 need no GPU. That is lucky, because **the GPU is not ready**.

## 5. The GPU, as of today

The read-only probe through the Codex lab chat changed nothing on the machine. It found:

- Three A6000s were idle. The disk volume has 4.2 TB free.
- The existing environment is the robotics one (PyTorch 2.5.1, Transformers 4.49). It has no FlashAttention, and PEFT and TRL are unverified.
- **The job controller is built for the robotics campaign.** It has one fixed approval file and a robotics scorer, and it cannot host a second campaign as it stands.
- Jobs are offline, and the bridge cannot download. Weights and data have to be staged on the machine some other way.

To run E2 and E3, the founder would need to approve the following:

1. a separate controller path for OrderGuard;
2. a separate Python environment;
3. a way to stage two small checkpoints and our data;
4. an approval file with a GPU-hour cap.

The controller's hard limit is 24 hours per job.

A cost note: forking the lab chat carried its whole history and spent about 6.3M tokens on one read-only question. Future instructions will go to a fresh Codex run with a short brief, since the lab bridge is in Codex's global configuration.
