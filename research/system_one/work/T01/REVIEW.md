VERDICT: REVISE

## Re-run

Ran `bash work/T01/run.sh` from the System One directory. It exited successfully and printed 3,200 episodes (8 families × 2 shift settings × 200), 24,000 actions per family/shift cell, 9,710 duplicate sentences out of 712,896 (repeat rate 0.0136), 0 validation errors across 16 files, and 54 passing tests. It printed 0 pre-onset positives for every failure family/shift cell and 0 positives for both clean cells. The run measured 19.42 seconds and 164.74 episodes/second.

The deterministic counts, label rates, repeat count, validation result, and test count match `REPORT.md`. The throughput does not: the report gives 165.36 episodes/second and 19.35 seconds, while this run printed 164.74 and 19.42. Before this re-run, `check.log` also contained two result blocks despite the report saying it held one; `run.sh` overwrote it during this re-run, and the current log has one block.

## Pass bar

| Item | Result | Evidence |
|---|---|---|
| `run.sh` runs clean with no errors | Met | Successful exit; validation and pytest completed. |
| 0 validation errors | Met | 0 across 3,200 episodes. |
| At least 10 tests pass | Met | 54 passed. |
| Sentence repeat rate under 5% | Met | 1.36%. |
| `SCHEMA.md` stands alone | Met | It describes the world, fields, causes, hard negatives, and JSONL format. |
| `SCHEMA.md` leaks no detection logic | **Not met** | “Book replay and label consistency” publishes label/replay rules, including the checks tied to `y` and the drift-above-`max` condition. |
| No positive action before failure onset | Met | The generator printed 0 pre-onset positives in all 14 failure cells. |

The explicit pass bar is therefore not met. Also, not every reported number matches the independent run: the sampled throughput is stale, even though the report discloses that timing varies.

## Required fixes, in order

1. **Remove the family signal from model-visible identifiers.** `generate.py` assigns seed ranges by family (`fi * 1000 + i`), `_owner` embeds the seed in `signing_key_id`, and `model_view` retains the owner. A model can infer the family from the key even though `meta` is stripped. Use an identifier independent of family/seed (or remove it from the model view), regenerate the reference data, and add a regression test that the model view does not reveal family through identifiers.
2. **Make per-action model input causal.** `model_view` returns all documents, all steps, and final thesis statuses. In the stale-thesis generator, the onset changes a thesis's status to `invalidated`; that final status remains visible to every action, including actions before onset. Later documents and actions are also present in the view. Provide an as-of-action view, or otherwise enforce that a scorer receives only information available at that action; time-index or omit final thesis status. Add tests that an earlier action cannot see later evidence or state.
3. **Remove detector/checker rules from the author-facing schema.** Keep the field meanings and episode format, but remove the operational replay/label checks from `SCHEMA.md` (especially its `y`-gated band and position checks and the rule identifying drift buys above `max`). The brief explicitly bars detection logic in that file.
4. **Reconcile the throughput claims.** Update all repeated throughput/time values in `REPORT.md` to the captured run, or report the measurement as a non-reproducible sample without presenting it as the current `check.log` result. Ensure the log and report-time summary describe the same single run.
5. **Close schema-validation bounds gaps.** The validator checks that band values and mandate limits are numeric, but not that sector bands are within the documented 0–1 range; it also treats a missing zero-valued sector total in `initial_book.sectors` as if it were present. Enforce the documented ranges and required sector totals, with malformed-episode regression tests.

## Loopholes found

- **Family leakage:** the seed range is a deterministic family code carried into `owner.signing_key_id`, which survives `model_view`. This is a direct label proxy in the reference corpus. I found no evidence in the reviewed files of held-out test-set peeking or threshold selection against held-out data; that does not remove this input leakage.
- **Future-information leakage:** the model view strips `meta` and `label`, but not future episode contents or the final `invalidated` thesis status. This allows a per-action scorer to use future state.
- **Detection-logic disclosure:** `SCHEMA.md` explains the reference validator's replay and label-consistency checks, contrary to the author-facing restriction.
- **Report accuracy:** deterministic results reproduce, but the throughput values do not match the independent run. The original checked-in log also had duplicate result blocks before this re-run.
- **Validator edge cases:** out-of-range mandate weights and missing zero-valued sector totals can pass schema validation. The generated corpus itself passed validation.
- I found no literal secret or absolute home path in the reviewed task report, log, package, or schema.
