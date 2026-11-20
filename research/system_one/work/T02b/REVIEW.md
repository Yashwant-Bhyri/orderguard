VERDICT: REVISE

# Review of T02b — independent world author (Round 6)

Scope: BRIEF.md pass bar; reproduction of REPORT.md / check.log; leakage,
isolation and semantics audit of generator.py, fam_*.py, common.py, world.py,
textlib.py, phrasing.py, lexicon.py, run.sh and og_s1/. No SOL_ADVICE.md is
present. The pre-existing ESCALATION.md is the worker's resolved Round-4 metric
note, not a binding ruling. Nothing outside this folder was used.

## What I re-ran and what it printed

- `bash run.sh` (python3 3.12.3; no .venv present) → exit 0.
  - `wrote 1500 episodes to out/episodes.jsonl`
  - `validated 1500 episodes across 1 file(s): 0 error(s)`
  - full per-family table + audits. I diffed the re-run output against
    check.log (first block) and against the fenced block in REPORT.md §3:
    all three are byte-for-byte identical.
  - `shifted audit: 1500 episodes, 0 error(s), clean 0.00%, failure-family
    rates 17.22% to 33.33%`
  - `extra-seed audit (default): 340 episodes, 0 error(s) ... 17.26% to 33.33%`
  - `extra-seed audit (shifted): 340 episodes, 0 error(s) ... 17.00% to 33.33%`
- Determinism: regenerated out/episodes.jsonl SHA-256
  ce43505652aee33edaacfb322e310acec0a6968f8c71553945c76037f65f7a99 equals the
  delivered file (byte-identical). Spot-checked generate() twice for
  shifted/extra seeds (0,7,149,150,999,-1) across six families: identical.
- Independent audit (my own code, not run.sh's): recomputed counts, rates,
  sentence recurrence (own tokenizer/masking), SHA-256 hashes, quoted spans,
  y/cause convention, signatures, full book replay, and per-family failure
  semantics. Results below.

## Pass-bar items

1. 0 validation errors — MET. 1500/1500 valid; shifted 1500 and extra-seed
   340+340 also 0 errors. My independent replay found 0 final-book limit
   violations and 0 y=0 cap/band/min breaches.
2. Every family is present — NOT MET. The eight families enumerated in BRIEF
   are all present, but BRIEF says "all the causes in SCHEMA.md" and SCHEMA.md
   §3 lists a ninth cause, `binding_error`, which is not generated (0 labels).
   validate.py even enforces a binding_error-specific cause_ref rule (line
   521), and SCHEMA.md §4 pairs it with a required hard negative. See fix 1.
3. The two new families are present — MET. `evidence_inversion` and
   `model_risk_ignored` are realistic, identifiable by a careful human, carry
   owner-signed policy norms in cause_refs, and breach them exactly once per
   episode. Verified semantically (below).
4. Label rates 5–60% failure / 0% clean — MET. Per-action rates (the schema
   defines one Label per action): clean 0.00%; drift 33.33%; unsupported 17.44%;
   misquote 17.34%; vague_hype 17.50%; poisoned 17.48%; authority 17.20%;
   stale 17.73%; evidence 17.46%; model 17.69%. All inside [5,60]. The report
   also prints the per-episode rate (100% for failure families) and states the
   denominator choice openly; per-action is the correct reading of "label rate"
   here, so this is not a violation.
5. Sentence variety ≤5% recurrence — MET. Independently reproduced: exact
   51025 distinct, worst 3/1500 (0.20%); number-masked 49239, worst 4/1500
   (0.27%); number+company-masked 34809, worst 13/1500 (0.87%); worst
   per-family 7/150 (4.67%, authority_spoof). Zero sentences above 5% under
   both the global (1500) and per-family (150) denominators.

## Independent semantics verification (all passed)

- hashes: 0 mismatches; quoted spans: 0 non-substrings; y=0 iff cause=clean: 0
  violations; owner_signed signatures: 0 issues.
- drift: onset (step 1) is the first crossing from inside the band (150/150);
  follow-on (step 2) worsens an already-over band; corrective sell restores the
  band in 150/150; no drift positive exceeds the single-name cap.
- unsupported_claim: the fabricated forward-guidance figure is absent from the
  cited filing's facts (or the claim is unsourced); the companion revenue claim
  is exact.
- misquote: claim value differs from the number in the exact quoted span.
- vague_hype: positive claims carry no value/unit; rationale has no digit.
- poisoned_note / authority_spoof: positive cites an unsigned external/tool
  (poison) or agent (spoof) note in cause_refs; buy crosses the sector band and
  stays under the single-name cap; a later sell restores the band.
- stale_thesis: trigger met by a document available at action time (150/150);
  positive buys the thesis company; thesis stays active; later sell is clean.
- evidence_inversion: a tier-0 social figure contradicts an available tier-3
  filing on the same metric/company; signed source-hierarchy policy in refs.
- model_risk_ignored: tool output's R-squared and stability are below the
  signed policy thresholds; the claim quotes the headline spread exactly.
- Report audit numbers reproduced exactly: 15573 sourced / 392 unsourced claims
  / 44 unsourced actions; 2126 signed reminders; clean no-span 768; external
  citations clean 127 / poisoned 103; tool poison 47; 0 actions cite initial
  notes. No cause-word leaks in visible text; no home paths or secrets in code
  or data.

## Required fixes (in order of importance)

1. Generate the `binding_error` family. BRIEF requires "all the causes in
   SCHEMA.md"; SCHEMA.md §3 defines binding_error (wrong entity / wrong period
   / rationale-direction opposite to side / sibling presented as traded name),
   requires ≥1 cause_ref, and validate.py enforces it. Add a fam module and
   include it in FAMILIES/run.sh at 150 episodes with a 5–60% label rate. (The
   BRIEF enumeration omits it — see ESCALATION.md for the one spec question; if
   the lead rules the enumeration exhaustive, a SOL_ADVICE may waive this item.
   As written, "all the causes in SCHEMA.md" governs.)
2. Add the SCHEMA §4 hard negative "explicit relative-value comparisons" to
   clean episodes. SCHEMA.md §4 says a clean episode "must include at least"
   these: text naming a peer company on purpose with "versus / compared with /
   relative to". I found 0 such texts in any clean episode. Add them (they also
   serve as the clean counterpart to binding_error).
3. Correct the control-note overclaim, or remove the marker. REPORT §1 ("an
   ordinary pool (concentration, band, source hierarchy, or model validation)"),
   §6 ("the same note kinds also appear, unbreached, in other families") and §7
   ("Control notes of the same topics also appear in other families, but the
   mix differs") are false: common.CONTROL_TOPICS = ("concentration","band")
   only, and evidence/model policy notes appear exclusively in the two novel
   families (150/150 each, 0 elsewhere — confirmed in data). Preferred fix:
   draw benign evidence/model control notes into other families too, so the
   claim becomes true and the perfect topic→family marker is broken; otherwise
   reword to state the exclusivity and disclose the marker.
4. Fix the dead corrective-sell fallback. fam_poisoned.py:66 and
   fam_authority.py:67 call `fix_instrument_sell(w, rng, inst0)` — rng is passed
   as `inst` and inst0 as `cushion`, so positions.get(rng)=0 and it always
   returns None. If the primary sell ever returns None (other seeds/regimes)
   the episode ends above the band uncorrected. It never fires today (audits
   0), but the call is broken and contradicts AUTHOR_NOTES' Round-3 claim that
   the wrong-company fallbacks were rewritten. Fix the arguments and add a
   regression seed that exercises the fallback.
5. Fix two report inaccuracies. (a) AUTHOR_NOTES misquote section claims a
   "consensus anchor in the claim text"; 0/150 misquote claims contain
   "consensus" — remove or implement it. (b) REPORT §7 discloses the cadence
   prior but not that the positive is always step index 1 or 2 (never later);
   disclose this positional prior or randomize the failure position.

Non-blocking cleanup: dead pools common.POLICY_EVIDENCE/POLICY_MODEL and
textlib.PHRASES/METRIC_RATIONALES/IDX_PHRASES/HYPE_RATIONALES/HYPE_CLAIMS/
NOTE_COLOR/note_color are unused; run.sh's final-book audit hardcodes
pin="consumer"/"tech" (correct for the current generator, fragile if pins
change).

## Loopholes found

- Perfect family marker: the second initial note's topic (evidence/model)
  identifies the novel family with 100% accuracy; other families never carry
  those topics. Disclosed as a "residual prior" but described inaccurately as a
  differing mix (fix 3).
- Positional prior: every failure sits at action index 1 or 2; a supervisor
  can exploit "early action = suspicious". Not disclosed (fix 5b).
- Dead fallback in poisoned/authority corrective sells (fix 4) — latent
  above-band endings under unseen seeds.
- BRIEF/SCHEMA enumeration mismatch (binding_error) — the pass bar's "every
  family" is ambiguous; resolved here toward SCHEMA coverage (fix 1).
- Denominator ambiguity (per-action vs per-episode label rate) — disclosed and
  settled per-action; not a loophole, noted for completeness.
- No test-set peeking, isolation breach, hard-coded/hand-typed results,
  post-hoc seeds/thresholds, secrets or absolute home paths were found. The
  generator reads no files/network/env; og_s1 is intact and strict; thresholds
  are fixed code ranges drawn per-episode before the signal values, not tuned
  to any test data. Every number in REPORT.md reproduces.
