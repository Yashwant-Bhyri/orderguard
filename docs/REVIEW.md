# The escalation lane: triage and the mandate copilot

What happens after code or the risk model **holds** an order, and before a human **signs** a new mandate. This lane uses TypeSafe's Jev, a typed decision model that returns probabilities instead of prose ([where it fits](RISK.md#which-decision-paradigm-where)). Code is in `python/orderguard_review/`.

## The rule

**Code is the only thing that can say yes.** Jev's output is advice. It can (a) order the human review queue, (b) add a warning or a hold, (c) be shown to a human. It cannot approve an order, release a hold, or sign or widen a mandate. Any failure (no key, no recording, budget, a transport error, a malformed or partly usable answer) becomes `advice.available: false` and the deterministic result is unchanged.

| claim | where it is enforced | test (`python/tests/review/test_principle.py`) |
|---|---|---|
| every failure is "no advice" and the model alone orders the queue | `advice.safe_ask`, `triage` | `test_triage_failure_degrades_to_no_advice_and_the_model_alone_orders` (13 failure shapes), `test_real_client_without_key_or_recording_gives_no_advice`, `test_a_partly_usable_reply_is_not_trusted_at_all` |
| advice asks for at most `none`, `warn` or `hold` | `advice.action_for` | `test_suggested_action_is_never_more_than_none_warn_or_hold` |
| advice can only raise a queue position (noisy-OR) | `advice.merge_probability` | `test_advice_never_lowers_the_queue_position_it_can_only_raise_it` |
| `apply_advice` is tighten-only: allow can become hold, a hold or refusal never moves down, unknown fails closed | `advice.apply_advice` | `test_apply_advice_is_tighten_only_whatever_the_advice_says` |
| the most reassuring answer decides nothing | whole module | `test_there_is_no_path_from_advice_to_an_approval`, `test_injection_in_the_state_is_data_it_cannot_widen_what_code_decides` |
| `fits` comes from `check_mandate_fit` alone; an uncontained draft is never shown to the model | `copilot.review_draft` | `test_fit_is_decided_by_code_...`, `test_the_best_possible_judgement_cannot_make_a_draft_fit_or_sign_it`, `test_the_worst_judgement_cannot_make_a_contained_draft_not_fit_it_only_warns`, `test_the_purpose_text_cannot_change_the_fit` |
| the scope check is a hold at most, and "matches" releases nothing | `scope.scope_check` | `test_scope_check_is_a_hold_at_most`, `test_a_fooled_scope_check_adds_nothing_and_a_suspicious_one_cannot_release` |
| no MCP tool signs, approves, releases or widens; the review tools are read-only | `orderguard_mcp` | `test_mcp_review_tools_are_read_only_and_there_is_no_signing_or_approving_tool` |
| labels never reach the model | `study.build_cases` | `test_the_labels_never_reach_the_model` |

## 1. Held-order triage

`triage(held_order, context, risk=None)` makes **one** call with three typed questions about the same information the risk model uses (the agent's recent orders, the ticker tape, the envelope, the trusted price):

| question | type | used for |
|---|---|---|
| is this likely a compromised, colluding or runaway agent? | `noul` (probability) | `p_jev`, merged into `p_bad` |
| the most likely pattern: `collusion_split`, `runaway`, `size_jump`, `stale_price`, `fat_finger`, `looks_honest` | `choice` | shown to the reviewer, with its confidence |
| urgency | `score`, 3 levels | shown to the reviewer |

It returns `{p_bad, queue_rank_key, typed_reasons, advice}`. `p_bad` is the noisy-OR of the risk model's score and `p_jev`, so advice can only raise a position; `queue_rank_key = p_bad x notional` is the expected bad dollars the queue is sorted by (`rank_queue`). `typed_reasons` lists the risk model's reasons (source `risk_model`) and the model's typed answers (source `jev`) side by side. `advice.suggested_action` is `hold` at `p_jev >= 0.5`, `warn` at `>= 0.25`, else `none`.

### Method

`python/orderguard_review/study.py` replays `results/arena/arena-s7-k1000-t2000.jsonl` (seed 7, 1,000 agents, 2,000 steps; the risk model never trained on seed 7), scoring every order point in time with the shipped order-risk model and building each order's context from the events before it (the agent's last 8 orders, the last 25 on the ticker). Truth is the arena's label (`legit` or not) and bad dollars are the order's notional at the trusted price. The labels never go to the model.

**The shipped model holds too few orders to make a queue.** Of 18,394 gate-allowed orders it holds 21 (17 honest, 4 bad) and refuses 545 outright, which no human sees. So there are three queues:

| queue | what is in it | orders | bad | honest | per hour (mean) |
|---|---|---|---|---|---|
| `model_holds` | gate-allowed orders the shipped model holds as is | 21 | 4 | 17 | 2.1 |
| `model_flagged` | every gate-allowed order with model risk >= 3e-4, held for a human instead of refused (same model, lower threshold) | 1,002 | 547 | 455 | 31 |
| `all_held` | `model_flagged` plus the 264 orders the gate itself held (uncorroborated news, step-up) | 1,266 | 744 | 522 | 40 |

The reviewer works hour by hour (an hour is 62.5 steps, 8 working hours a day). In each hour they open the top K orders of that hour's queue under one ordering; a bad dollar is *caught* when its order is opened. Orderings: FIFO, biggest notional first, the risk model's `p x notional`, Jev's `p_jev x notional`, and the headline `jev+model` (noisy-OR of both, times notional). `reviews_to_catch` counts the reviews needed, summed over hours, to open 90% or 99% of each hour's bad dollars. Confidence intervals are a seeded bootstrap over hours.

### Results (`results/review/triage.json`)

Queue `model_flagged` (1,002 orders; 31 per hour; bursts of several hundred in the colluding hours):

| ordering | reviews to open 90% of bad $ | to open 99% | bad $ caught at K=5 per hour | precision at K=5 |
|---|---|---|---|---|
| FIFO | 719 | 766 | 1.9% | 12% |
| biggest notional first | 600 | 647 | 4.4% | 17% |
| **risk model** | **470** | **514** | **5.6%** | 37% |
| Jev alone | 584 | 633 | 4.5% | 19% |
| Jev + model (headline merge) | 530 | 574 | 4.8% | 21% |

Queue `all_held` (1,266 orders): reviews to 90% of bad $: FIFO 895, notional 832, model 763, Jev alone 837, Jev + model 802.
Queue `model_holds` (21 orders): any ordering opens all four bad orders within 8 reviews; the model needs 4, Jev + model 5, Jev alone 6, FIFO 8. Too small to say more.

What this says:

- **Against FIFO, typed triage saves about a quarter of the review time**: in `model_flagged`, Jev + model needs 530 reviews against 719 to open 90% of bad dollars (26% fewer; 25% fewer for 99%), and 10% fewer in `all_held`. At a fixed 5 reviews an hour it opens 2.5x the bad dollars of FIFO (4.8% against 1.9%; the share is low for every ordering because one hour holds hundreds of colluding orders). The bootstrap interval of the difference at K=5 is +0.8 to +36.7 percentage points: wide, because it depends on which burst hours are resampled.
- **It does not beat the risk model's own ordering, and the merge makes it slightly worse.** The model alone needs 470; Jev + model 530; the interval of the difference at K=5 is -16.6 to -0.2 points. Jev's `compromised` probability separates bad from honest orders **inside this queue** at AUC 0.58 (0.55 in `all_held`). The earlier AUC of 0.998 ([RISK.md](RISK.md#which-decision-paradigm-where)) was bad against honest among gate-allowed orders on a stratified sample; here the honest orders are the hard cases, the ones the model already found unusual, and a probability that says "unusual" ranks them with the bad ones.
- **Alone, Jev is only a little better than sorting by size** (584 against 600 reviews). It is a usable ordering where no trained risk model exists, but on this stream that is a 3% edge over the cheapest baseline.
- **The typed pattern is the useful part.** It names the family correctly for 336 of 392 colluding orders (86%) and 132 of 136 runaway-loop orders (97%); `1 - P(looks_honest)` alone has AUC 0.91 in `model_flagged`. It calls 255 of the 455 honest orders in that queue `looks_honest`. It is shown to the reviewer; as a ranking input it did not beat the model either (`model+pattern`, tried after seeing the results, needs 567 reviews).
- **The 163 uncorroborated-news holds in `all_held` ($1.9M) look like honest flow.** Neither the model nor Jev can tell them apart from behaviour, and in this simulator the gate's own hold code (`l7`) labels them perfectly, which a real deployment would not have. They are why `all_held` shows the smallest gain.

Cost and speed: 1,266 calls cost US$0.0947 (**US$0.075 per 1,000 triage calls**); live latency p50 1.26 s, p95 2.05 s with six calls in flight. This is the slow lane: it never runs on the order path.

## 2. Mandate copilot

`review_draft(parent, draft, purpose_text, trusted_key=...)` returns `{fits, violations, appropriateness, scope_match, concerns, advice}`.

1. **Code decides the fit.** `check_mandate_fit` (draft within the signed parent) is the only source of `fits`. A draft that does not fit is returned with its violations and **is not shown to the model**.
2. **Jev judges only a contained draft**, with three typed questions: `appropriateness` (score: inappropriate, questionable, appropriate), `scope_match` (noul: do the symbols, sides, sizes and activity limits match the stated purpose and no more) and `concerns` (choice: none, too many symbols, asset class mismatch, size too large, too much activity, sides not needed, weakened safeguard, purpose unclear). `advice.flag_score = 1 - mean(appropriateness, scope_match)`; at or above 0.56 the suggested action is `warn`.
3. The output is never a mandate: `signed` is false, `requires_human_signature` is true.

### Labelled set (`labelled_drafts.py`)

40 drafts, **all inside the same signed parent** so containment never decides the label: 14 appropriate, 9 over-broad (narrow purpose, near-parent limits), 9 purpose-mismatched (tight but wrong symbols or sides), 8 sneaky (a good draft with one extra: a crypto symbol in a staples purpose, a step-up threshold at the parent's maximum for a "cautious" purpose, a wider band than the purpose asked for). For example, "rebalance into index ETFs" with a draft allowing TSLA and NVDA is purpose-mismatched, and the same purpose with all 15 symbols and 2,000 orders a day is over-broad.

Results (`results/review/copilot.json`):

| measure | value |
|---|---|
| AUC of `flag_score`, flagged against appropriate | 0.997 |
| AUC of the two parts: appropriateness / scope match / a named concern | 0.986 / 0.951 / 0.819 |
| AUC of a purpose-blind baseline (how much of the parent's room the draft uses) | 0.629 |
| held-out half (20 drafts, threshold set on the other 20): accuracy | 95% |
| held-out half: inappropriate drafts flagged | 13 of 13 |
| held-out half: appropriate drafts flagged | 1 of 7 |
| all 40 at the shipped threshold (optimistic): flagged by category | over-broad 9/9, mismatched 9/9, sneaky 8/8; appropriate falsely flagged 1/14 |
| flagged drafts where the named concern is one a signer would accept | 85% |
| cost | US$0.050 per 1,000 reviews |

Read the first line with care. My first combination of the two judgements (the lower of the two, flag at 0.5) flagged **all 14** appropriate drafts: the model's `scope_match` runs low in absolute terms (0.15 to 0.34 even for appropriate drafts) and only its ranking is informative. I changed to the mean and a calibrated threshold after seeing those 40, and report the held-out half separately for that reason. The AUC is threshold-free but the combiner was chosen after looking. 40 drafts written by the authors is a small set and a friendly one.

## 3. Semantic scope

`scope_check(mandate, order, agent_stated_intent)` asks one `noul` question: does the order match what the agent said it was doing? It returns the match probability and a suggested action of `none`, `warn` (mismatch >= 0.5) or `hold` (>= 0.8). The agent's own text is shown to the model as data. If the model is fooled into "matches" nothing is released, because nothing was held by it; a hold that code placed stays.

On 24 labelled pairs (`labelled_scope.py`; every order inside the mandate, so code would allow all of them; `results/review/scope.json`): AUC 1.00, 11 of 12 mismatches held, 0 of 12 matches held, US$0.025 per 1,000 checks. The one miss was a size mismatch (a "small" market-making buy that was 10x a small lot): intent against instrument and direction is easy, intent against size is not.

## Use it

```bash
# replay the arena stream and the queue study, offline from the recordings
.venv/bin/og-review triage --stream results/arena/arena-s7-k1000-t2000.jsonl
# review one unsigned draft (parent: demo, configured, or a signed mandate file with its pinned key)
.venv/bin/og-review draft --parent demo --draft draft.json --purpose "rebalance into index ETFs"
.venv/bin/og-review drafts      # the labelled copilot set       .venv/bin/og-review scope      # the labelled scope set
```

`og-review draft` exits 0 when the draft fits, 1 when it does not, 2 on a usage error. HTTP: `POST /api/review/triage` and `POST /api/review/draft` ([API](API.md)); the token is checked before the body is read, and a bad field is a 422 that names it. MCP: `review_held_order` and `review_mandate_draft` ([MCP](MCP.md)). Model calls follow `OG_LLM`: under tests and CI they replay `data/replay/decisions/` and a missing recording is "no advice"; with `OG_LLM=record` a missing recording makes one live call, capped by `OG_BUDGET_USD`. Recording the whole of this lane's evidence (1,333 calls, including probes) cost under US$0.10.

## Limits

- One synthetic stream (seed 7), 32 simulated hours, collusion concentrated in two of them. The orders, the labels, the labelled drafts and the labelled intents were written by this project's authors.
- Jev's `compromised` probability is a weak ranker among orders the risk model already flagged. Do not read the AUC 0.998 as a statement about a hard queue.
- The model sees text the agent or the author controls (the stated purpose, the stated intent). Tickers and order fields are validated to a tight alphabet at the API; purpose and intent are length-bounded only. The worst a lying text can do is suppress added advice; code is unchanged.
- The risk model's refusals are not re-simulated: refused orders never reach a human, so `model_flagged` shows what a human sees only if the model is changed to hold instead of refuse.
- Recordings pin the request, not the model: `typesafe/jev-1.14` is an alias and a later version may answer differently. Replays are exact; a live re-run may not match.
- Advice runs after a hold, at about a second per call. It is not on the order path.
