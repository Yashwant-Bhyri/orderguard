VERDICT: PASS

# T14 review — taint propagation and the single-root-source cap (qwen, fresh adversarial run)

Scope: tasks/T14-taint.md, POLICY.md, work/T14/REPORT.md, work/T14/check.log,
and the code under review (og_s1/taint.py, work/T14/test_taint.py,
work/T14/evaluate.py, work/T14/run.sh, og_s1/schema.py model_view_at,
og_s1/checks.py for the T03 contract). No SOL_ADVICE.md exists in work/T14/,
so there is no binding ruling to check. The pre-existing ESCALATION.md is the
round-1 reviewer's own note with a round-2 resolution addendum, not a lead or
escalation-reviewer ruling; the pre-existing REVIEW.md is a prior round-3
PASS. This review relied on neither: everything below was re-verified from
the files and my own execution. No escalation is raised, so no new
ESCALATION.md is written.

## What I re-ran and what it printed

1. `bash run.sh` from work/T14/ — exit 0, appended capture
   `20261120T010136Z` to check.log. It printed:
   - T03 regression suite: `36 passed`.
   - T14 taint suite: `23 passed` (includes the 10,000-graph monotonicity
     property test and the causal-view mutation test).
   - Corpus: clean `episodes=1600 actions=192000 positives=40457`; shifted
     `episodes=1600 actions=192000 positives=38566`; total
     `episodes=3200 actions=384000 positives=79023`.
   - Gate on clean: `clean,clean,actions=24000,holds=0,hold_rate=0.0000`;
     `clean,shifted,actions=24000,holds=0,hold_rate=0.0000`;
     `pooled_clean_hold_rate=0.0000 bar=0.0200 PASS`.
   - `OVERALL: PASS (both pytest suites and the gate exited 0)` then
     `== end captured run 20261120T010136Z ==`.
2. Programmatic diff of my full capture block against the round-3 capture
   `20261119T090652Z` cited by REPORT.md: identical except pytest timing
   lines. Also identical to the prior reviewer's `092014Z` block. The
   round-2 final capture `075649Z` differs from round 3 only in the T14 test
   count (18 -> 23), confirming the report's "only the test count changed"
   claim. The failed intermediate block `073438Z`
   (`assert 'doc:d3' == 'note:n-ext'`, 1 failed / 17 passed) and the
   duplicated `075137Z` block are genuinely present as Section 4 describes.
3. Cell-by-cell programmatic comparison of every REPORT.md Section 3 table
   against my run: 96 feature-distribution rows (8 families x 2 shifts x 6
   features, mean/p50/p90/p99/nonzero-share), 16 gate rows, 16 cap rows, 4
   all-root-vs-untrusted-only rows, the corpus counts, the clean-gate table
   and the pass-bar lines. Zero mismatches. The "shifted identical except
   drift" claim was checked row-by-row and holds.
4. Independent probes with my own code (reviewer scratch, outside the repo;
   no worker file was edited):
   - `propagate_trust` vs an independent reachability-min implementation on
     3,000 fresh random graphs (my own seed, n=1..15, cycles included):
     0 value mismatches, 0 fixed-point-equation violations, 0 monotonicity
     violations.
   - Full-corpus re-aggregation with my own metric code over all 3,200
     episodes / 384,000 actions: every gate and cap count/rate in the report
     reproduces; 0 gate internal-consistency violations (hold ==
     decisive_support>=0.5 AND notional > max($1, 0.5% of capital)); 0 holds
     on any negative label in any family; all 24,454 holds corpus-wide have
     `decisive_kind="note"` (the tainted-decisive-claim path fires 0 times on
     data/ref); `taint_decisive_claim` is non-zero on 0 of 384,000 actions.
   - Independent sliding-window cap recomputation (my own window/count/
     exposure/tie-break code) on 2,400 sampled actions across clean, drift,
     poisoned_note, authority_spoof, stale_thesis: 0 mismatches in
     flagged/root/count.
   - Causal mutation stronger than the worker's test: compared the FULL
     root_flags dicts, gate_details and X (not just the `flagged` boolean)
     after mutating future documents/notes/actions, all labels, meta and
     thesis status — identical through the cut.
   - Label/meta-strip invariance: removing every label and meta from an
     episode leaves X, gate_holds and root_flags bit-identical.
   - Edge cases: in-band buy citing an agent note -> no hold, authority 0;
     band-excess buy citing an agent note -> hold; sell of a not-allowed
     instrument citing an agent note -> hold (see loophole 4); zero-capital
     book -> fail-closed hold via the $1 floor.
5. Data claims spot-checked against data/ref: book capital $1,000,000;
   120 steps/episode; the owner-mandate note n0 (owner_signed, valid, no
   cites) is cited by 100% of sampled clean actions; thesis evidence
   documents are tier 2/3 only; authority_spoof notes are agent-written and
   unsigned. All match the report's stated rationale.

## Pass-bar items

1. Property test: trust never rises along any chain, over at least 10,000
   random graphs — MET.
   `test_trust_never_rises_along_any_chain_over_10000_random_graphs` runs
   exactly 10,000 graphs (fixed seed 20261119, n=1..12, random base levels
   0..4, random directed edges incl. cycles) and asserts for every edge
   `trust[child] <= base[child]` and `trust[child] <= trust[parent]`, which
   gives chain monotonicity by transitivity. Passed in my run. I additionally
   verified the propagation semantics themselves against an independent
   implementation (probe above), since monotonicity alone would also be
   satisfied by a degenerate all-zero labelling.
2. Features read only `model_view_at` — MET. Full read of og_s1/taint.py:
   the only episode accesses are `model_view_at(episode, i)` per action and
   `len(episode.steps)` as the iteration bound (the same convention T03's
   featurize uses). No label, meta, prose or whole-episode model_view
   access; the source-guard test passes; my label/meta-strip probe confirms
   invariance. evaluate.py reads labels only after analyze_taint returns.
3. Gate hold rate on clean data/ref episodes <= 2% — MET. 0 holds of 24,000
   clean and 0 of 24,000 clean.shifted actions; pooled 0.0000 <= 0.0200,
   printed by evaluate.py in my run and reproduced by my independent
   full-corpus aggregation.
4. All of T03's tests still pass — MET. 36 passed in my run;
   og_s1/checks.py still exports the 41-feature contract; its mtime predates
   T14's first capture, and the worker added og_s1/taint.py instead of
   editing checks.py, as the brief permits.

run.sh requirements — all MET: both suites run (including the monotonicity
and causal-view tests); all six feature distributions per cause family on
data/ref are printed (mean/p50/p90/p99/nonzero share, both shifts); the
gate's clean hold rate and per-family recall are printed. `OVERALL: PASS`
is emitted only after both suites and evaluate.py exit 0 under
`set -euo pipefail`, and evaluate.py exits non-zero if the gate bar fails.

## Required fixes

None. All pass-bar items are met and every reported number reproduces from
the one-command entry point, confirmed both by re-running run.sh and by an
independent full-corpus re-aggregation.

## Loopholes found and residual weaknesses (non-blocking)

1. The tainted-decisive-claim gate path never fires on data/ref. All 24,454
   reference holds (both shifts, all families) come through the
   permission-excess + non-owner-authority-note path; `taint_decisive_claim`
   is 0 on all 384,000 actions because reference theses open on tier-2/3
   evidence. That path is validated only by the synthetic low-trust-thesis
   test. Disclosed in REPORT.md Sections 3, 4 and 7; my probes confirm it.
2. The gate is wider than the brief's literal decisive-claim rule: it also
   holds permission-exceeding actions that cite any non-owner note, even an
   informational agent note and even when no claim is tainted. This is a
   documented judgement call (5.4), hold-only, and keeps the clean rate at
   0, but a held-out clean world with agent notes on large permitted buys
   could produce false holds. Disclosed in Sections 5.4 and 7.
3. `_permission_excess` diverges from T03's checks.py on sells: T03 flags a
   sell that pushes a sector below its band minimum (and any weight when a
   band is absent); T14's band excess is buy-only. The divergence can only
   remove hold triggers, so no reported number or pass-bar item is affected,
   but a sell-side authority spoof in a held-out world would escape this
   gate while T03 flags the permission breach. Not documented in the report;
   recommend aligning with T03's band logic or recording the difference in a
   future round.
4. `instrument_not_allowed` applies to sells as well as buys (consistent
   with T03): a risk-reducing sell of a not-allowed instrument that cites a
   non-owner note is held (verified by probe). A specific case of the
   disclosed conservative-authority risk; a held-out clean unwind could
   false-hold.
5. The default all-root cap is noisy on ordinary reuse: 937/24,000 clean
   actions flagged (3.90%), 19.19% of clean drift negatives (14.05%
   shifted). It is a monitor, not a hold, and the rates are reported rather
   than tuned away; deployment would need a per-source baseline. Disclosed.
6. Trusted notes are never cap roots (except non-owner authority notes on
   permission actions), so an attack concentrated on one trusted note is
   invisible to the cap. The report explains why (n0 is cited by every clean
   action — verified 100% in my sample) and discloses the gap in Section 7.
7. In-sample design: the decisive-claim definition, trust threshold and the
   cap's 12-of-20 / 25%-of-book concentration defaults were chosen after
   looking at data/ref results. This is the brief's own pass-bar corpus, not
   held-out data — no heldout/T02/T06 file is referenced or read anywhere in
   the code, and data/ref is static (mtime predates every T14 round) — so it
   is not a policy breach, but the clean hold rate is an in-sample estimate.
   Disclosed as reference-only design in Section 7.
8. Minor wording overbreadth: "T03's structural features cover the other
   five causes" (Section 3). T03's own report says vague_hype has no
   dedicated structural cause feature (its AUROC-1.0000 separation via the
   unsupported feature is a generator property, and the cause is left to the
   text channel). T14's gate recall of 0.0000 on that family is correctly
   reported; suggest softening "cover" to "separate on the reference
   corpus". Optional wording fix, not a measurement error.
9. The property test asserts monotonicity but not the fixed-point equation;
   a degenerate all-zero propagation would pass it. The deterministic chain
   and label tests pin exact values, and my independent probe verified the
   true semantics, so this is a test-strength suggestion only.
10. The worker's causal-view test compares only the cap's `flagged` boolean;
    my full-detail comparison (root/count/exposure/reason, gate_details, X)
    found no difference, so the claim holds, but the test could be
    strengthened to match the report's wording.
11. Stale artifacts: ESCALATION.md is the round-1 reviewer's cap-scope
    question, resolved in round 2 by the `root_cap_include_trusted` config
    with both modes measured; it is not a current escalation and not a
    binding ruling. REVIEW.md is the prior round-3 PASS.

## Hygiene and isolation

- No test-set peeking: evaluate.py loads only data/ref; tests use simulate
  and synthetic graphs; no code path reads data/heldout*, work/T02* or
  work/T06 (grep-verified). Labels are consumed only after featurisation,
  and strip-invariance was verified by probe.
- No hard-coded or hand-typed results: every table is computed by
  evaluate.py from the corpus; my independent re-aggregation matches; the
  only fixed numbers in tests are synthetic expectations and the <=2% bar.
- Seeds: the property-test seed is a date constant over synthetic graphs;
  no seed selection against outcomes. Config defaults are printed by
  evaluate.py and match DEFAULT_CONFIG in code.
- No secrets, keys, tokens, emails or absolute home paths in the task
  folder, og_s1/taint.py or check.log (scans found none; the only
  "signing_key_id" is the synthetic "test-key" in test fixtures). No
  bytecode caches in the task folder; run.sh sets
  PYTHONDONTWRITEBYTECODE=1 and clears task caches. Largest file is
  check.log at about 223 KB, well under 5 MB. No data copied into the task
  folder.
- Writes outside the task folder are limited to og_s1/taint.py, which the
  brief explicitly authorises; og_s1/checks.py is untouched by this work.
- REPORT.md has the seven required sections in order, records negative
  results (Section 4), and every major choice in Section 5 has real
  alternatives, project-criteria reasoning and flip evidence, as POLICY
  requires.

## Conclusion

All four pass-bar items are met; every number in REPORT.md reproduces from
`bash run.sh` and from my independent full-corpus re-aggregation; the
propagation semantics, cap window arithmetic, causal isolation and
label-blindness were verified beyond the worker's own tests. The residual
weaknesses (narrow in-sample gate, noisy all-root cap, sell-side permission
divergence) are disclosed or non-blocking and none is a pass-bar item. PASS.
