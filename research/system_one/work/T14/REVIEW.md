VERDICT: PASS

# T14 review — taint propagation and the single-root-source cap

## What I re-ran

From `work/T14/`, `bash run.sh` (captured run `20261119T092014Z`, exit 0). It
appended a new block to `check.log` and printed:

- T03 regression suite: **36 passed**.
- T14 taint suite: **23 passed** (includes the 10,000-graph monotonicity
  property test and the causal-view test).
- Corpus: clean **1600 episodes / 192000 actions / 40457 positives**; shifted
  **1600 / 192000 / 38566**; total **3200 / 384000 / 79023**.
- Gate on clean: clean **0 / 24000**, clean.shifted **0 / 24000**, pooled
  **0.0000** against the **0.0200** bar: `PASS`.
- `OVERALL: PASS (both pytest suites and the gate exited 0)` followed by
  `== end captured run 20261119T092014Z ==`.

I compared the full new block with `REPORT.md` Section 3: the feature means
(all eight families, both shifts), gate holds/recalls (`poisoned_note` 6111 /
0.9778, `authority_spoof` 6116 / 0.9804, the others 0), cap flags/rates
(clean 937 / 0.0390; drift 8405 / 0.3502; shifted drift 5430 / 0.2263; etc.),
and the all-root vs untrusted-only rows (clean 8 / 0.0003, drift 1933 / 0.0805,
shifted drift 1009 / 0.0420) all match the report cell for cell. The reported
pass-bar numbers reproduce exactly.

## Pass-bar items

1. **Property test: trust never rises along any chain, ≥ 10,000 random
   graphs — MET.** `test_trust_never_rises_along_any_chain_over_10000_random_graphs`
   passed; its loop runs 10,000 random graphs (n = 1..12, random base levels,
   random directed edges including cycles) and asserts, for every edge,
   `trust[node] <= base[node]` and `trust[node] <= trust[cited]`. The
   document -> note -> claim -> action chain test also passed.
2. **Features read only `model_view_at` — MET.**
   `og_s1/taint.py` imports only `model_view_at`; `analyze_taint` builds every
   row from `model_view_at(episode, i)`. The source-guard test passed. The only
   non-view access is `len(episode.steps)` as the iteration bound, the same
   convention T03 uses; it does not feed feature values.
3. **Gate clean hold rate ≤ 2% — MET.** 0 / 48000 pooled clean actions =
   0.0000, printed by `evaluate.py` and reproduced in my run.
4. **All T03 tests still pass — MET.** 36 passed in the same run.

The `run.sh` requirements — run both suites including the causal-view test,
print each feature distribution per cause family on `data/ref/`, and print the
gate's clean hold rate and per-family recall — are all MET.

## Required fixes

None for PASS.

## Loopholes found and residual weaknesses (non-blocking)

1. **The decisive-claim gate path never fires on `data/ref`.** `taint_decisive_claim`
   is 0.0000 in every reference family. An independent probe over all 24,000
   actions of `poisoned_note` and `authority_spoof` found all 6111 and 6116
   holds come through the non-owner authority-note path (`decisive_kind=note`,
   claim path 0). The tainted-decisive-claim gate is therefore validated only
   by the synthetic low-trust-thesis unit test, not by any reference action.
   The report discloses this in Sections 3, 4 and 7.
2. **The gate over-holds on authority notes.** Any action with a permission
   excess that cites *any* non-owner note, even an informational agent/tool
   note, holds if size exceeds the threshold. Clean reference holds are zero,
   but a held-out clean world with an agent note on a permitted but large buy
   could produce false holds. Documented in Sections 5.4 and 7.
3. **The default all-root cap is noisy.** 937 / 24000 clean actions (3.90%)
   and 19.19% of clean drift negatives are flagged. It is a monitor, not a
   hold, and the report states the rate rather than hiding it; still, a
   deployment would need a per-source baseline or a different alert budget.
4. **Trusted notes are not cap roots.** An attack concentrated on one trusted
   note (as opposed to a trusted document) is invisible to the cap. Report
   Section 7 says so.
5. **Design and thresholds used `data/ref` outcome.** The decisive-claim
   definition, the trust threshold and the cap's 12/20-actions and 25%-book
   concentration defaults were chosen after looking at reference results, so
   the pass-bar clean rate is an in-sample estimate, not a held-out one. This
   is a reference-only design weakness, not a policy breach: no held-out file,
   `work/T02*` or `work/T06` is referenced or read, and labels are read only
   after featurization. The report labels the design reference-only.
6. **The causal-view test compares only the boolean `flagged` field for the
   root cap, not the full root/count/exposure detail.** Because `model_view_at`
   strips future steps, the detail cannot depend on the mutations either; the
   test is adequate but slightly narrower than the report's "root-cap flags"
   wording.
7. **Minor report overbreadth:** "T03's structural features cover the other
   five causes" is imprecise for `vague_hype` (T03 says it has no dedicated
   structural cause feature, though the best unsupported feature separates the
   reference family at AUROC 1.0000). T14's gate recall of 0.0000 on that
   family is correctly reported.
8. **Stale artifact:** the pre-existing `ESCALATION.md` is from round 1 and
   says the verdict was REVISE. No `SOL_ADVICE.md` exists, so it is not a
   binding ruling; its cap-scope question is handled by the
   `root_cap_include_trusted` config and both modes are measured. It is not a
   current escalation.

## Hygiene and isolation

No test-set peeking found: `evaluate.py` loads only `data/ref`, calls
`analyze_taint`, and reads labels afterwards; the tests use `simulate` and
synthetic graphs. No code or evaluator reads `data/heldout*`, `work/T02*` or
`work/T06`; those names appear only in the report's isolation statements.
No absolute home paths, keys, tokens or emails in the task folder or
`check.log` (an absolute-home-prefix scan found none), no large files (largest is
`check.log`, about 205 KB), and no evidence of hard-coded result tables: every
reported table is printed by `evaluate.py` from the corpus. `og_s1/checks.py`
is untouched by this work and T03's 36 tests pass. The one write outside the
task folder is `og_s1/taint.py`, which the T14 brief explicitly authorises.

## Conclusion

All four pass-bar items are met and every reported number reproduces from the
one-command entry point. The residual weaknesses are the narrow, in-sample gate
and the noisy all-root cap; both are disclosed in the report and neither is a
pass-bar item. PASS.
