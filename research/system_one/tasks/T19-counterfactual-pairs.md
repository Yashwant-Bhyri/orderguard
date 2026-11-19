---
id: T19
title: Counterfactual minimal pairs - change one factor, label by code, keep the hard ones
depends: T01, T03, T15, T31
worker: opencode-go/deepseek-v4.1-flash
variant: high
isolate: false
env_keys: OPENROUTER_API_KEY
check: bash run.sh
timeout_min: 180
max_rounds: 4
---

# T19. Counterfactual minimal pairs

Read `research/system_one/POLICY.md`, `docs/vision/lab/COMBOS.md` (sections 2 and 4), `docs/vision/lab/BLUEPRINT.md` (section 7) and `og_s1/eval/SPEC.md` first. Your task folder is `research/system_one/work/T19/`.

**Isolation rule:** do not open `work/T02*`, `work/T06`, `work/T16` or `data/heldout*`.

## Why

The most informative training signal for System One is a pair of cases that differ in **one** meaningful factor, where one is fine and the other is not. A model trained on such pairs learns which changes matter, which do not, and why. That is the decision boundary itself.

## Build

From `data/ref/` causal views, generate pairs by changing exactly one factor:
- the crucial filing not yet published at the action time;
- a different owner sector restriction;
- the figure describing a forecast instead of a result;
- the right value for the wrong entity, period, accounting concept or scope;
- the authority coming from an unsigned agent note instead of the owner's signature;
- earlier actions having already used up the risk budget.

Add **invariance pairs** too: a change that must not alter the verdict, such as a paraphrase, an accurate rounding or a correct unit conversion.

For each pair:
- **Labels by code.** Compute the label, the deciding evidence and the FinVerify category with code wherever the change is formal. Record `truth_type` (`formal`, `evidential` or `preference`) and the label's provenance.
- **Wording variety.** Use DeepSeek V4.1 Flash only to rephrase surface text. Labels never come from it. Use DeepSeek V4 Pro only for the hard evidential cases, and keep those as `teacher`-labelled.
- **Difficulty filter.** Score each pair with the current best available reader (T05's, or T11's if passed). Keep pairs it gets wrong or is unsure about (0.2–0.8). Report the survival rate per factor.
- Cap API spend at $15.

## run.sh

Regenerate from the cache, print counts per factor, per FinVerify category, per truth type and per difficulty bucket, and run the tests.

## Pass bar

- At least 3,000 pairs, every factor present, and at least 20% invariance pairs.
- Every formal label is reproduced by code alone. A test re-derives 200 at random.
- No pair is built from `data/heldout*`.
- Teacher-labelled pairs are flagged, and are ≤ 25% of the total.
