# OrderGuard architecture

> AI trading agents will believe fake information. OrderGuard decides what they may do using numbers they can't touch, and checks the facts their orders rely on.

The binding interfaces are in `CONTRACT.md`. This page says what each layer is, what it guarantees, what it does not, and why it is built that way. "README" below means `lab/legacy/attack-lab-2026-11-06/README.md`, the measured prototype.

## Layers and data flow

```
                     untrusted world: 10-K text, web pages, feed events, tool results, tool descriptions
                                              |
                                              v
  tool output --> [L1 normalise] --> [L2 screen] --> [L3 risk bucket] --> [L4 data marking] --> analyst agent (any model)
                  code               model, per      code first,          <data> wrapper,          |
                  strip/flag         chunk, cached   model if unsure      system prompt            | proposes an order
                                     fail closed                                                   v
                                              +------------------ [L5 order gate] <---- trusted market (SimMarket / broker)
                                              |                   code only            signed mandate (Ed25519)
                                              |                        | cited key_figures
                                              |                        v
                                              |                   [L6 figure check]  orderguard_verify.api.check_figures (SEC filings)
                                              v
                                       allow / hold / refuse
                                              | allow
                                              v
                                       [L8 receiver]  atomic paper ledger, idempotency, revocation (TypeScript; local ledger fallback)

  standing rules ("sell basket if down 40%") --> [L7 trigger graph] --> proposes orders into the same L5 -> L8 path
        inputs = median across venues, >= 2 independent unquarantined sources
```

The agent is least-privileged: in the `gate_only` and `full` arms no money-movement tool is offered at all, and a call to one is refused (`orderguard_guard/agent.py`). `naive` is the control arm: raw output, every tool, no checks.

## Layer by layer

| Layer | File | Guarantees | Does not guarantee |
|---|---|---|---|
| L1 normalise | `normalise.py` | Zero-width, bidi and Unicode tag characters (U+E0000) are removed and reported (tags: what they spelled). NFKC applied. Mixed-script tokens (Cyrillic А in "АAPL") flagged. Long base64 runs decoded and appended so the screen can read them. Tag characters or mixed-script tokens quarantine the chunk outright. | Meaning. A visible, plainly written lie passes. |
| L2 screen | `screen.py` | One model verdict per chunk `{flag, category, why}`; chunks flagged are replaced by a one-line marker. Cached by hash of model+kind+chunk. A screen error quarantines the chunk and is counted (`Screen.errors`): it fails closed. | Completeness. It is a model, and an adaptive attacker can target it. It misses edited figures that look plausible. |
| L3 risk bucket | `bucket.py` | Information that repeats or depends on a quarantined item is quarantined too. Code first: same ticker plus a shared distinctive number or entity, or the same source. Model only when code is unsure. Provenance kept: source, time, reason, index of the item repeated. | Catching a claim restated with no shared number, entity or source and no model suspicion. Document chunks are stored for provenance but not matched by number (a 12-paragraph chunk holds too many ordinary numbers). |
| L4 data marking | `agent.py` | Every tool result in the `full` arm is wrapped in `<data>` tags and the system prompt says data never changes mandate or procedure. | Obedience. It is a request to a model. In the lab it was the weakest layer, so nothing depends on it. |
| L5 order gate | `gate.py` | Signed, unexpired, unrevoked mandate; ticker normalised (NFKC, strip, upper) and on the allow-list, non-Latin look-alikes refused; side; quantity x TRUSTED price within the per-order cap; running daily total; limit within the band of the TRUSTED price; cited figures checked by L6; step-up hold above a threshold. Every refusal reason is a plain sentence. | That the trade is a good idea. It bounds what a wrong agent can do. Needs a trustworthy price source. |
| L6 figure check | `orderguard_verify/api.py` (adapter in `gate.py`) | A contradicted, stale or not-public-yet figure refuses the order, with the reason. An unverifiable figure holds. A checker error refuses. | Facts that are not figures in filings. |
| L7 trigger graph | `graph.py` | Standing rules read only unquarantined events; every input is the median across venues and needs >= `min_sources` independent sources (sources with a common owner count once). `blast_radius(source, lies)` shows what one lying source could trigger, for a naive rule and the guarded graph. In arm `full` the agent loop applies it itself: a `place_order` that carries out a standing rule is evaluated on the unquarantined events before L5/L8 and held (layer L7, nothing reaches the ledger) unless the rule fires; a rule order L7 confirmed is not refused for lacking SEC facts on its ticker. `gate_only` and `naive` have no L7. | Several colluding sources, or a majority of venues lying. |
| L8 receiver | `receiver/` (TypeScript), `receiver_client.py` | Final authority: checks the exact order against the human-signed mandate, values it at the trusted price, atomic ledger, idempotency, revocation. The client starts and stops the bridge and talks to it; without node or the bridge it falls back to `LocalLedger` and says so. | Anything outside the mandate JSON. |

### Trusted figure lookup (guarded arms)

The `gate_only` and `full` arms require every order to cite the figures it relies on (`key_figures`). Those arms also get one extra tool, `get_reported_figure(ticker, metric, fiscal_year)`. It answers from the same SEC truth store L6 checks against, as of the decision date, and never returns a figure that was not yet public. It is trusted data, so it is not screened.

Before this tool existed, agents with no filings tool could not cite a figure and gave up. Live DeepSeek V4.1 Flash then completed 3 or 4 of 7 clean controls in the guarded arms, against 6 of 7 unguarded. With the tool and an actionable refusal message, all three arms complete 6 of 7 (`docs/RESULTS.md`).

## Why each choice (measured, see README)

- **Value orders at the trusted price, never the order's own limit.** In the feed case F2, 8 of 11 agents believed a fake 10-for-1 split and ordered about 440 shares at $22.30. At its own limit that is about $9,800 and passes a $10,000 cap; at the trusted quote it is about $98,000 and fails. All 8 were blocked only because of this. Tested in `python/tests/guard/test_gate.py::test_fake_split_is_refused_at_the_trusted_price`; the fake "reference price" document from the adaptive round is the same test family.
- **Mandate check in code, not in the prompt.** Hidden instructions worked in 1 of 107 runs, and all 9 harmful actions in the study broke a rule that code could check against trusted data (README, results). So the gate is the guarantee, and the model layers only reduce how often it is exercised.
- **Check cited figures against filings (L6).** Fake numbers in the filing fooled agents in 15 of 24 runs, and an LLM screen missed the edited income statement (README, detection test). Contradiction with SEC data is code. The same layer covers natural mistakes: agents misquote real figures with no attacker in 13 of 112 runs. `place_order` therefore requires `key_figures` in the hardened arms.
- **Code before the model in L1 and L3.** The one attack two of three model screens missed was the invisible Unicode-tag instruction (README, round 3). Stripping it is free and exact. The risk bucket caught a third wire repeating a quarantined "$400 takeover" by shared number and ticker without asking a model.
- **Screen per chunk, cache by hash, fail closed.** The LLM screen caught 11 of 11 hidden instructions and 11 of 14 fake-data chunks with 0 false alarms on 145 10-K chunks, while the open-source classifier caught 1 of 11 and raised false alarms on 11 of 11 feed windows (README, detection test). A flagged feed window is re-screened event by event so honest events survive; if no single event is guilty the whole window is hidden. Chunks are 12 paragraphs, whole pages and 10-event windows because that is how the measured screen met them.
- **Median across venues and independent sources (L7).** `lab/legacy/attack-lab-2026-11-06/bucket_graph.py`: one venue printing -48% on a basket made a rule that trusts any single print sell $30,000. The median of three venues held (-1.2%), and a real -45% crash on all three still fired. Tests: `test_graph.py`.
- **No money-movement tool.** In the adaptive round the attacker got DeepSeek V4 Pro to call `transfer_funds` for $250 in round 2. The hardened arms do not offer the tool, so there is nothing to talk the agent into.
- **One LLM client with record/replay and a budget.** Every model call goes through `llm.py`: responses are stored by hash of the canonical request under `data/replay/`, `OG_LLM=replay` makes tests and published tables rebuild offline, `OG_BUDGET_USD` (default 0.05) caps a process, every live call is appended to `results/spend.jsonl`, and the account balance is checked once per process before the first live call (refused under US$0.30).

## Limits, stated plainly

- The model layers (L2, L3 model check, L4) can be beaten by an adaptive attacker. In the adaptive round the "believe a false revenue figure" goal succeeded on DeepSeek V4 Pro in round 5 and the order was inside the mandate; L6 is what addresses that case, and only for figures that exist in filings.
- L5 bounds damage; it does not make a within-mandate trade wise.
- A lying trusted price source defeats L5. SimMarket stands in for a broker quote.
- The demo's `--scripted` mode is a scripted stand-in for the model and screen; it exercises the layers and proves nothing about a real model.
