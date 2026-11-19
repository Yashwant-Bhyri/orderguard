VERDICT: REVISE

# T03 review

## What I re-ran and what it printed

From `work/T03/` I ran `bash run.sh` (capture `20261119T052450Z`, 2026-11-19T05:24:50Z). It printed:

- T03 tests: **36 passed**; full repository suite: **105 passed**.
- features: **41**.
- corpus: clean **1600** episodes / **192000** actions / **40457** positives; shifted **1600** / **192000** / **38566**; total **3200** / **384000** / **79023**.
- latency: mean **0.2890 ms**, p50 **0.2042 ms**, p95 **0.6979 ms**, p99 **1.1752 ms** (bar **5.0 ms**), max **98.7603 ms**.
- throughput: end-to-end **117.647 s / 27.20 episodes/s / 3264.0 actions/s**; featurisation-only **110.977 s / 28.83 episodes/s / 3460.2 actions/s**.
- best shifted AUROC per cause group: drift **1.0000**, unsupported_claim **1.0000**, misquote **0.9999**, poisoned_note **1.0000**, authority_spoof **1.0000**, stale_thesis **0.8836**.
- evidence-quality **0.5341** shifted; vague_hype claim-support **1.0000**; `OVERALL: PASS`.

The report cites capture `20261119T051628Z`; that block is in `check.log`, and its counts, label rates, AUROCs, latency and throughput match the report. My rerun's deterministic values match; the sampled latency and throughput differ as the report says they will. `check.log` also contains later captures `20261119T051956Z` and this run's `20261119T052450Z`; the cited block is intact.

I read `og_s1/checks.py`, `og_s1/tests/test_checks.py`, `work/T03/evaluate.py`, `og_s1/schema.py`, `SCHEMA.md`, and the round-1..4 shell logs under `runs/T03/`. I did not open `work/T02*`, `work/T06`, or `data/heldout*`.

## Pass-bar items

| Pass-bar item | Status | Evidence |
|---|---|---|
| The tests pass | **MET** | 36 T03 tests and 105 repository tests passed in this rerun. |
| p99 latency is at most 5 ms per action on one CPU core | **MET** | p99 **1.1752 ms** in this rerun; the report's cited capture prints **0.9118 ms**. |
| No wording-based logic; no keyword lists or regexes over prose | **MET** | `og_s1/checks.py` imports no `re` and contains no prose regex. The only prose operation is the schema-mandated exact substring `quoted_span in doc["text"]`; `_UNITS` is a closed table over the structured `unit` field, not a prose keyword list. |
| Point-in-time correctness is tested | **MET** | Tests mutate future documents and notes, final thesis status, labels and `meta`; test same-time document visibility and `pre_note`/`new_note` ordering. |
| Each cause group's best shifted AUROC is at least 0.80 | **MET** | 1.0000, 1.0000, 0.9999, 1.0000, 1.0000, 0.8836 for the six cause groups. |
| Leakage guard: features and scoring use only the model view; `meta`/`label` evaluation-only | **MET** | `featurize` calls `model_view_at` per action; `evaluate.py` reads labels after `featurize`; no `meta` read. |
| Causal input: per-action `model_view_at(episode, i)` | **MET** | Implemented and tested; the feature module contains no whole-episode `model_view` call. |

The isolation rule is **MET** in the shell history: the round-1..4 worker commands show no access to `work/T02*`, `work/T06`, or `data/heldout*`. The separate absolute-path policy issue is a report correction below.

## Required fixes (in order of importance)

1. **Correct the adversarial-prose overclaim in `REPORT.md` §5.1 (and any "never reads prose" phrasing).** The span check is `span in doc["text"]`; the structural layer does read document text for the exact quote. A document whose text contains the quoted span and whose structured facts match the claim passes even if the surrounding prose, or the claim's own narrative, is misleading; that is T05's job. "It cannot be talked around by adversarial prose because it never reads prose" is false as written and conflicts with §6's "the only prose access is `quoted_span in document.text`." Replace it with a scope statement: no claim, note, thesis or rationale prose is read; the only prose operation is the schema-mandated exact-span test; prose-only manipulation is out of scope for this layer.
2. **Correct the absolute-home-path claim in `REPORT.md` §6.** The task-folder files and `check.log` contain no absolute home path, but the round-1/2 shell commands under `runs/T03/` contain `cd` commands using the worktree's absolute home-directory path (not reproduced here). "No ... absolute home paths: none were used or written" is false for the task history. Report the bad news: the earlier commands logged the absolute path, do not repeat it, and state precisely what is clean (the current task-folder files and `check.log`).
3. **Correct the "Disk" bullet in `REPORT.md` §6.** At report time the task folder also contained `ESCALATION.md` and `__pycache__/evaluate.cpython-312.pyc`; this review adds `REVIEW.md`. "The task folder contains only REPORT.md, run.sh, evaluate.py and check.log" is false. There is no 5 MB violation, but list the actual contents, or remove the generated `__pycache__` inside the task folder and list the review artifacts.
4. **Correct the Round 4 "every claim gets ..." description.** `_claim_features` `continue`s after an unsourced claim or an unavailable source, so the quoted-span and unit checks are not run for those claims; their own shares and `claim_support_failure_share` catch them. Say: every claim gets the source-presence check; claims with a source get the availability and span checks; claims with an available source and a unit or numeric value get the unit check; the support share is the maximum of the per-share failures over all claims.
5. **Correct the evidence-quality description or make the code match it.** `evaluate.py` sets every action in every non-clean family to positive (`np.ones(len(y))`), including that family's `y=0` actions; the clean family is negative. The report's "clean actions are negatives and every failure action is a positive" is ambiguous and, on the label-level reading, wrong (the evidence line prints 168000 positives out of 192000 actions, not 79023 label positives). Either say "clean-family actions are negatives and all actions from the seven non-clean families, including their hard negatives, are positives," or use the actual `y` labels. The number is descriptive, not a pass-bar item, but the description must match the code.
6. **Correct the "Clean actions" loophole in `REPORT.md` §6.** The clean-reference test checks `drift_out_of_band_increase`, `drift_sector_excess_after`, and the claim/value/note/authority composites; it does not assert that every drift feature is zero. `drift_daily_turnover_ratio` and `drift_position_ratio` are normal risk ratios. Say "no out-of-band drift failure signal," not "no drift ... signal."
7. **Add two held-out fragilities to `REPORT.md` §7, or justify their absence.** (a) The drift features treat a sell that pushes a sector below its `min` as an out-of-band increase, while the schema's drift family is buys above `max`; a held-out clean world with a positive `min` and a rebalancing sell could false-positive. (b) `_thesis_features` matches invalidation facts by `name` only and compares raw values without a unit check; a held-out fact with the same name in a different unit can fire the trigger falsely.

## Loopholes and fragility found

- **Reference AUROC is a same-family, best-of-group selection.** The "best feature" and its AUROC are selected and reported on the same reference family, so the values are optimistic; the report correctly calls this a sanity check, and the independent T02/held-out worlds remain the real test. No held-out data was used here.
- **The `drift` features are broader than the schema's drift cause.** `_out_of_band_total` counts below-`min` weight as out of band, while the schema's drift family is buys that leave a sector above `max`; the reference clean test does not exercise a clean sell below a positive `min`. `drift_out_of_band_increase` still separates the reference family perfectly.
- **Thesis-trigger unit mismatch.** The trigger has `name`, `op`, `value`; the code compares raw fact values by name and never checks the fact's `unit`. The reference data matches; a held-out author using the same fact name in a different unit could produce false triggers.
- **The tier-0 mixed-citation rule is a judgment call.** `_note_features` uses `any(tier == 0)` for an external/tool note; the task's "cites documents of trust tier 0" does not quantify. The previous review raised this, the report documents it in §5.13, and `ESCALATION.md` keeps the question. The reference poisoned-note shifted AUROC is 1.0000 under the current any rule; the report does not show a reference mixed-citation case that would distinguish the readings.
- **The `_UNITS` table is a closed vocabulary.** It contains word forms (`percent`, `billion`, `basis_points`, etc.) but is applied to the structured `unit` field, not to prose; a literal "no keyword lists" reading would still notice it. The task's unit-swap requirement needs a table, and the report documents the choice.
- **The authority conjunction is an approximation.** It flags any cited note with `signature_valid` false plus a permission excess, including an agent's own unsigned note; it does not check that the note actually claims a permission change. The report's §5.7 and §7 say a spoof inside the mandate or a forged signature needs T05.
- **Evidence quality is weak and pooled by family.** The best evidence feature is 0.5370 clean and 0.5341 shifted on the pooled family-membership comparison; the report labels it descriptive, which is right.
- **The `vague_hype` claim-support AUROC of 1.0000 is generator-specific.** The reference hype actions are sourceless non-numeric claims; the report explicitly says this is not a general hype detector and defers the cause to T05.
- **Latency is sampled with GC disabled inside `featurize`.** The report discloses the GC change and the sampled tail; p99 clears 5 ms with a wide margin in both the cited and this rerun.
- **No isolation breach found.** The worker's shell commands read `data/ref/` and the repository, and the round-1 T01 report; none read the held-out T02/T06/heldout paths. The current task-folder text and `check.log` contain no secret or absolute home path; the earlier shell-log absolute path is the §6 correction above.
