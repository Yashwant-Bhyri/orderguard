---
id: T14b
title: Why-graph v2 - agent words as hypotheses, a fidelity channel, proof status, the decisive-claim gate on every action, hotspots
depends: T14
worker: opencode-go/deepseek-v4.1-flash
variant: max
isolate: false
check: bash run.sh
timeout_min: 150
max_rounds: 5
---

# T14b. Why-graph v2: proof status and the decisive-claim gate

Read these first:
- `research/system_one/POLICY.md`;
- `docs/vision/lab/DECISIONS.md`, entries D14 and D15;
- `docs/vision/lab/ARCHITECTURE_MAP.html`, section 02 (rules R1–R8, the proof-status table, the hotspot table and the worked example);
- `work/T14/REPORT.md`, `work/T14/REVIEW.md` and `work/T14/REVIEW_qwen.md`;
- `og_s1/taint.py` and `og_s1/checks.py`.

Your task folder is `research/system_one/work/T14b/`. Extend `og_s1/taint.py`. If it grows past about 900 lines, add `og_s1/proof.py` and import it. Keep every T03 and T14 test passing. Where a T14 default must change, change it behind a config key and report both settings.

**Isolation rule:** do not open `work/T02*`, `work/T06`, `work/T16`, `data/heldout*` or `cs1000/`.

## Why

T14 made trust fall along a chain. That is necessary but not enough. Two failures still pass without a signal:

1. **Reinterpretation.** The agent quotes a trusted filing correctly but changes what it means: guidance read as actual, "could" read as "will", or the right number for the wrong period, entity, metric or scope. Trust stays at 3 because the source is real.
2. **Self-grounding.** The agent writes a thought into its memory ("growth confirmed at 12%", citing nothing). Later it cites that note as evidence. Today an agent note starts at trust 2, the trusted boundary, so the agent's reasoning becomes its own proof.

T14's reviews also found two gaps:
- the tainted-decisive-claim path never fires on the reference data;
- the authority gate checks only buys.

## Build

### 1. Agent words are hypotheses (R3, D14)
- **Config.** Add `agent_unanchored_trust` (default 1.0). An agent note that cites no document, or an agent claim with no `source_doc`, starts at this level instead of `agent_trust`. Keep T14's behaviour available with `agent_unanchored_trust = 2.0`.
- **Self-grounding.** Mark a claim **self-grounded** when every root of its chain is agent-authored. A note that cites only agent notes counts the same way.
- **Implicit claims.** Add a pluggable extractor interface: `extract_implicit_claims(action) -> list[Claim-like dict]`. It turns factual sentences in `action.rationale` that are not already in `action.claims` into claim nodes with `origin = "rationale"` and no source, unless the sentence contains an exact quote of a visible document.
  - Ship a deterministic baseline: sentences with a number, a percentage, or an assertion verb from a small documented list.
  - Mark it a baseline in the report. The model-based extractor comes from T24 and plugs into the same interface.
  - Rationale claims enter the graph as nodes. They are unproven unless anchored.

### 2. The fidelity channel (R2)
- Give each claim-to-source edge a fidelity in [0, 1].
- **Code part (exact):** compare the claim's value, unit, and where parseable its period and entity, against the source document's `facts`. Cover period, entity, metric, scope, and guidance against actual. If T31 has passed when you start, reuse its binding rules; if not, write them in `og_s1/proof.py` and do not edit T31's files.
  - A matched fact gives 1.0.
  - A unit or scale conversion that is correct gives 1.0. This is a hard negative and must not be penalised.
  - A binding mismatch gives a low value, with the subtype recorded.
- **Reader slot:** an optional `reader_fidelity(claim, quote, card) -> float | None` hook that F4 will fill later. When it is absent, use the code part only. When it is present, combine by minimum.
- A claim's fidelity is the minimum along its chain.

### 3. Proof status (D15)
Give every claim exactly one status, with this precedence: `TAINTED` > `CONTRADICTED` > `REINTERPRETED` > `UNPROVEN` > `SUPPORTED` > `PROVEN`.
- `PROVEN`: code matched value, unit, period and entity to a fact in a source with trust ≥ 2.
- `SUPPORTED`: trust ≥ 2 and fidelity ≥ τ (config, default 0.7), but no exact fact match.
- `UNPROVEN`: no document anchor, or self-grounded.
- `REINTERPRETED`: an anchor exists, but fidelity < τ.
- `CONTRADICTED`: a source visible at the time gives a different value for the same binding.
- `TAINTED`: some root has trust below `trusted_threshold`.

### 4. The decisive-claim gate (R6), on every action
- **Decisive claim:** the claim with the largest share of the action's support. Use T14's `_decisive_claim_index` and include implicit claims.
- **Hold** when the decisive claim is not `PROVEN` or `SUPPORTED` and the notional is above the T14 size threshold. This applies to both sides, buy and sell.
- **Authority (R5).** Any owner-authority assertion, in a cited note or in the rationale, that does not trace to a valid owner signature raises a signal on both sides. It also holds above the threshold, with cause `authority_spoof`.
- **Why the T14 path never fires.** Explain why the tainted-decisive-claim path never fires on `data/ref/`, using counts from the data. Then add a synthetic probe set (below) where it must fire.

### 5. Hotspots (R8 and the hotspot table)
- **Score:** per node, `exposure × (1 − min(trust / 4, fidelity))`.
  - `exposure` is the notional of every later action that traces to the node, as a share of the book.
  - Use a window equal to T14's root-cap window.
- **Kind:** label each hotspot `manipulation`, `reinterpretation`, `self_grounding` or `echo`. `echo` means many mentions with one root.
- **Case memory (R8).** Once a node is found poisoned, stale or reinterpreted, every later action that traces to it inherits that finding as a feature, read only from `model_view_at`.
- **Output.** `rank_hotspots(view, i) -> list[{node, kind, score, exposure, downstream_actions}]`.

### 6. Features for the combiner
Each feature is oriented so that a larger value means more risk:
- share of supporting claims in each proof status;
- the decisive claim's status as an ordinal;
- minimum fidelity;
- self-grounded share;
- top hotspot score;
- case-memory hits;
- an authority-without-signature flag, for any side.

## Probe set: write it yourself, under `work/T14b/probes/`
At least 120 small episodes built by code. Each holds one planted pattern and has a matched benign twin that differs in one factor:
- **reinterpretation:** guidance → actual, wrong period, wrong entity, wrong metric, wrong scope;
- **self-grounding:** an agent note at t, cited at t + k;
- **echo:** three notes, one root;
- **authority spoof on a sell;**
- **tainted decisive claim** above and below the size threshold;
- **hard negatives:** correct unit conversion, accurate rounding, a properly signed owner note, a legitimate relative-value comparison.

The labels come from the generator. You must not tune thresholds on the probes and then report the probes as evidence: fix τ and the defaults on `data/ref/` first, then score the probes once.

## run.sh
- Run all tests, including:
  - T14's monotonicity property test, extended to fidelity: fidelity never rises along a chain, over ≥ 10,000 random graphs;
  - a causal-view test.
- Print the proof-status distribution per cause family on `data/ref/`.
- Print the gate's hold rate on clean `data/ref/` actions for both `agent_unanchored_trust` settings, and its recall per family, with T14's numbers alongside.
- Print probe recall per pattern and the false-hold rate on the benign twins.
- Print the worked example from the map (D1, D2, N1, N2, C1–C4, A1), rebuilt as a probe: its statuses, its gate decision and its top three hotspots.

## Pass bar
- Trust and fidelity each never rise along any chain (property tests).
- Features read only `model_view_at`. Labels and `meta` are never read.
- The hold rate on clean `data/ref/` actions is ≤ 2% with the new defaults. If D14's default pushes it higher, report by how much, and which clean actions are held and why. Do not quietly revert the default.
- Probes:
  - recall ≥ 0.95 on every planted pattern;
  - false holds ≤ 5% on the benign twins;
  - authority spoofs on sells are held.
- The worked example holds A1, with the decisive claim `REINTERPRETED` and N2 as the top or second hotspot.
- All T03 and T14 tests pass.

## Report (`work/T14b/REPORT.md`)
Write it for the founder, with numbers and their scale:
- what changed;
- the before and after against T14;
- what the reference world cannot test;
- which rules (R2, R3, R5, R6, R8) are now built;
- the config defaults and why;
- the two settings for D14, side by side.
