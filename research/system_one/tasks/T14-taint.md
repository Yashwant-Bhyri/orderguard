---
id: T14
title: Taint propagation through the why graph, and a single-root-source cap
depends: T01, T03
worker: opencode-go/deepseek-v4.1-flash
variant: high
isolate: false
check: bash run.sh
timeout_min: 120
max_rounds: 4
---

# T14. Taint propagation and the single-root-source cap

Read `research/system_one/POLICY.md`, `docs/vision/lab/COMBOS.md` (sections 1 and 2), `work/T03/REPORT.md` and `og_s1/checks.py` first. Your task folder is `research/system_one/work/T14/`. Extend `og_s1/checks.py` (keep T03's tests passing), or add `og_s1/taint.py`.

**Isolation rule:** do not open `work/T02*`, `work/T06` or `data/heldout*`.

## Why

An attacker's goal is not to loosen System One's decision, which tighten-only already prevents. It is to get a bad action through **without raising any signal**. Published adaptive attacks get past most text classifiers. The defence that survives is structural: track where every piece of information came from, and let low trust flow forward.

## Build

1. **Trust labels.** Give every document, note and claim a trust level from its provenance:
   - the source's trust tier;
   - who wrote it: owner, agent, tool or external;
   - whether it is signed;
   - whether it was visible at the time.
2. **Propagation.** A node inherits the **lowest** trust of everything it cites or summarises, directly or through a chain:
   - a note summarising a low-trust post is low-trust;
   - a claim citing that note is low-trust;
   - a thesis resting on such claims is low-trust.

   Trust can only fall along a chain, never rise. Prove this with a property test over random graphs.
3. **Taint features**, each oriented so that a larger value means more risk:
   - the share of the action's supporting claims that are tainted;
   - whether the action's **decisive** claim (the one with the largest effect on size or direction) is tainted;
   - the length of the shortest chain from the action to an untrusted root;
   - whether an owner-authority assertion traces to anything other than a valid owner signature.
4. **Single-root-source cap**, code only.
   - Group actions by the root documents their evidence traces back to.
   - If many recent actions, or a large exposure, trace back to one root, flag it. Parameters go in a config, with defaults and the reasoning for them.
   - This is the code part of the swarm monitor, brought forward.
5. **Gate.** A rule that holds any action whose decisive claim is tainted and whose size exceeds a small threshold, regardless of any model's score.

## run.sh

- Run all tests, including the monotonicity property test and the causal-view test.
- Print each new feature's distribution per cause family on `data/ref/`.
- Print the gate's hold rate on clean episodes and its recall per family on `data/ref/`.

## Pass bar

- Property test: trust never rises along any chain, over at least 10,000 random graphs.
- Features read only `model_view_at`.
- The gate's hold rate on clean `data/ref/` episodes is ≤ 2%.
- All of T03's tests still pass.
