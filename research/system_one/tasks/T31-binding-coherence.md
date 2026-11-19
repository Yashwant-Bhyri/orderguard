---
id: T31
title: Binding coherence - the reference world labels incoherent actions as clean; fix it as v2.1 and add a binding-error family
depends: T01, T03
worker: opencode-go/deepseek-v4.1-flash
variant: max
isolate: false
env_keys:
check: bash run.sh
timeout_min: 150
max_rounds: 4
---

# T31. Binding coherence in the reference world

Read `research/system_one/POLICY.md`, `og_s1/SCHEMA.md`, `og_s1/world.py` and `work/T03/LEAD_NOTE.md` first. Your task folder is `research/system_one/work/T31/`.

**Isolation rule:** do not open `work/T02*`, `work/T06`, `work/T16` or `data/heldout*`.

## What the lead found (2026-11-19)

The reference generator labels some incoherent actions as `clean`. Example: `data/ref/clean.jsonl`, episode 57, step 80. The action **sells PEP**. Its claims are about CL and COST. Its rationale says "We add COST because customer growth is 47.618%…". The label is `y=0, cause=clean`.

There are two causes in `og_s1/world.py`:
- `_clean_rationale` and `_clean_claims` pick any fact from the pool given to them. `_rebalance_sell` gives them every fact in the sector, so the facts are often about another company.
- The `RATIONALE` templates ignore the side. "We add {company}…" and "Rebalancing into {company}…" are used on sells, and "Taking some {company} off the table…" on buys.

The lead measured this on the unshifted files: among negatives, about 15% of rationales name another instrument, about 7% are sells with buying words, and about 12% have no claim about the traded name. (The shifted files rename companies, so a name match does not work there; your measure must handle that.)

**Why it matters.** "Right number, wrong attachment" is the binding error the lab ranks first. In v2, a reader that catches binding errors is punished with false positives on clean actions, and a model trained on v2 learns that incoherence is normal.

## Build

1. **Measure it properly.** Write `og_s1/coherence.py` with a code check `coherence(action, case) -> list of findings`:
   - the rationale's direction contradicts the side;
   - the rationale's subject is a different instrument from the traded one;
   - no claim is about the traded instrument or its sector's thesis evidence.

   It must handle the shifted renaming (use the world's own entity map, not string matching on tickers). Report the rate of each finding per family and per split for **v2 as it stands**. Then re-score T03's code checks and T05's registered readers, if their scorers can be run, with the incoherent negatives removed. Report how much each headline number moves. Do not edit T03 or T05 files.

2. **Reference world v2.1.** Add a generator option (`coherent=True`, default off so v2 reproduces byte for byte) that:
   - picks claim and rationale facts about the traded instrument where any exist, and otherwise uses a sector-level template that names no other company;
   - uses side-aware rationale templates (separate buy and sell lists).

   Generate it to `data/ref_v21/`, with the same families, sizes, seeds and shifted splits as `data/ref/`. Regenerate the validator outputs. In v2.1, every `clean` action must have zero coherence findings.

3. **A new failure family: `binding_error`.** In v2.1, this is the only place incoherence appears. Plant one of these, each with `cause_refs` pointing at the claim or rationale:
   - the right value for the wrong entity;
   - the right value for the wrong period;
   - the rationale's direction opposite to the side;
   - a claim about a sibling instrument presented as the traded one.

   Include **hard negatives**: actions that legitimately mention another company (a relative-value comparison, written so the comparison is explicit) and must stay clean. Add the family to `SCHEMA.md` and to the validator.

4. **Tests** in `og_s1/tests/test_coherence.py`:
   - v2 still reproduces exactly;
   - v2.1 clean actions have zero findings;
   - every `binding_error` positive has at least one finding pointing at its `cause_refs`;
   - the hard negatives have zero findings.

## run.sh

Regenerate v2.1 from seeds, print the coherence rates for v2 and v2.1 per family, print the re-scored T03 and T05 numbers, and run the full test suite (`python3 -m pytest og_s1/tests -q`).

## Pass bar

- v2 reproduces byte for byte. All existing tests pass.
- v2.1 clean actions have 0 coherence findings. The `binding_error` family has at least 2,000 positives and at least 20% hard negatives.
- The coherence check's recall on `binding_error` positives is at least 0.95, and its false-positive rate on the hard negatives is at most 0.05, both on the shifted split.
- REPORT.md gives the v2 incoherence rates and how much the T03 and T05 headline numbers move when the incoherent negatives are removed. It ends with a recommendation for which tasks should move to v2.1. The lead decides.
- No API spend.
