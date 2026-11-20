# Lead review of CS-0001 (2026-11-20)

**Verdict: strong scaffolding, not yet a strong test. Revise before writing CS-0002.**

The structure is right, and better than I expected from a first case:
- causal snapshots with exact visibility (the lookahead document is cited, never shown);
- a replayable book;
- labels with evidence spans, truth types, severity and an owner-facing reason;
- a 1,272-word mandate in a real voice;
- genuinely good twists: a valid exception signed early and needed 50 items later, "probably" misread as approval, a reviewer-directed injection, and laundered sources.

But a model can score well on it **without reading**, and several documents tell the reader where the trap is. Both problems would repeat across 1,000 cases, so they must be fixed in the generator now.

`python tools/audit_case.py cases/CS-0001` now checks all of this automatically. Run it after `validate_case.py` on every case.

## What the audit found

| Gate | Result | What it means | Fix |
|---|---|---|---|
| **H1 surface shortcut** | **FAIL: 0.85** | A model that sees only side, order size, position and text lengths separates bad from good decisions at AUROC 0.85, without reading a word. The strongest cue is order size (0.88) | Bad orders of every size; large benign orders; target ≤ 0.65 |
| **H2 side balance** | **FAIL: 0 of 13** | Every bad decision is a buy. "Flag the buys" scores well | At least 25% of bad decisions are sells, rebalances, thesis updates or owner requests. The case already has 23 benign non-buys |
| **H3 editorialising** | **FAIL: 8 of 53** | Documents announce the trap: "No evidence in this document supports treating a trailing twelve-month…", "The review found that three market summaries repeated one press briefing", "…makes no commitment…" | Documents state facts the way real filings and news do. The reviewer must infer the trap. Real filings do not comment on how they might be misused |
| **H4 agent voice** | **FAIL: 35 of 40** | The rationale is a copy of the claim, so there is no reasoning to check | 2–5 sentence rationales in the persona's voice: sometimes sound reasoning on a wrong number, sometimes several claims combined, sometimes a hedge |
| H5 theme depth | PASS: 5 of 13 | Binding and grounding is the theme, but only one decision is an actual binding error | For a binding-themed case: 4–6 binding errors with different subtypes (period, entity, metric, scope, guidance vs actual) |
| **H6 gray vs ask** | **FAIL** | d039 is both the gray decision and the ask_owner decision | Separate decisions, testing separate skills |
| **H7 runnable probes** | **FAIL: 0 of 12** | Each probe describes its variant in a sentence ("Show the ambiguous owner message…"). No model can be run on a description | Write the variant as a real state file: `probes/<id>.state.json`, referenced by `model_input.variant_state_ref`, plus a recorded diff from the base state |
| S1 length mix | WARN: 0 of 54 | 49 items are under 40 words and 4 are over 1,000. Real inboxes are mostly 100–500 words, with the key figure buried in the middle | ≥ 30% of items at 80–600 words. Bury the figure in tables, footnotes and boilerplate |
| S2 difficulty | WARN: 25 of 40 at difficulty 1 | Mostly easy, even for the standard tier | ≤ 40% easy in standard, ≤ 25% in hard, ≤ 10% in expert |

## What is already good, and should stay
- The snapshots leak no labels; I checked the lookahead decision by hand.
- The causes are broad: 13 bad decisions across 13 causes, and 23 lookalikes covering 15 causes.
- The owner and the mandate have real texture: the signed narrow exception, the fiscal calendar clause, the purpose of the reserve.
- The noise share (43%), the unstructured share (72%) and the duplicates meet the clutter quotas.

## How strong is the suite plan, and how much more do we need?

**For evaluation, 1,000 cases is enough, if they are as diverse as planned.** At about 20 bad decisions per case (short cases ~13, long ~40), the suite holds about 20,000 bad decisions, and each failure cause appears in roughly half the cases. Bootstrapping by case (decisions inside one case are correlated), that gives about ±0.03 on each cause's recall. It is not enough for every crossing of cause × clutter × difficulty: about 55 cases per cell, so about ±0.10. Report those cells only as directions.

**For training, 700 cases is too little on its own.** That is about 21,000 decisions. Multiply it with:
- **materialised twins:** every probe and every bad decision gets 5–20 counterfactual variants, labelled by the same rules (H7 makes this possible);
- **XBRL binding pairs** from real filings (PLAN.md section 4);
- the T19 counterfactual pairs.

## Diversity fronts CS-0001 does not touch yet

Each needs at least 100 cases across the suite (the quotas are in the paradigm, section 7):

| Front | Why it matters |
|---|---|
| Bonds and duration, options and hedges, FX and international (IFRS reporting, non-US calendars) | Binding errors look different in each: yield vs coupon, notional vs premium, local currency vs USD |
| Real filings, quoted exactly (200 cases) | Real documents are longer and messier than anything we write |
| Multi-agent swarms; long cases (150–250 decisions) | Error chains over 20 decisions, and correlated agents trading on one root source |
| Mandate amendments, owner vs mandate conflicts, delegates | Authority is where real losses happen |
| Corporate actions, tax constraints (wash sales, lot selection), liquidity (order size vs average volume) | Formal truths that code must catch and models usually do not |
| Personas: compromised, over-literal, momentum | Different failure textures |

## Process changes before CS-0002

1. **Gates:** `validate_case.py`, then `audit_case.py`. Both must pass before the case card is written.
2. **Several authors.** No single model family writes more than 40% of the cases; use at least three (for example GPT, Qwen and Claude, with DeepSeek as a fourth). Otherwise the suite measures how well a model reads its own family's style. Results are reported per author family.
3. **A blind solve per case.** A model from another family answers the typed questions with no labels. Then:
   - where it disagrees with a label, the label is checked, which catches labelling errors;
   - if it solves everything, the case is too easy for its tier.
4. **Oversight at this scale.** The founder reviews the first ~20 cases closely. After that: every case that fails a gate or has a blind-solve dispute, plus a random 1 in 10. Reviewing all 1,000 in sequence would take months.
5. **Regenerate CS-0001** with these fixes, rather than patching it, and keep this version as `CS-0001-v0` for comparison.
