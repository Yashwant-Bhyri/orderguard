VERDICT: ESCALATE

# T20 adversarial review

## What I re-ran and what it printed

I ran the brief's entry point from `research/system_one`:

```bash
bash work/T20/run.sh
```

It exited 0 and printed:

- `wrote 200 items ... counts={'failed_case': 37, 'label_noise_probe': 20, 'ref_action': 120, 'review_finding': 23}`;
- `rule-labeled (blind-checked) 200 items from case content; reference-cause agreement 117/120 reference actions, 20/20 probes detected as flipped`;
- the `label_audit` 3 disagreements, all reference-clean actions labelled `temporal_integrity`, and `stale-thesis sample: 6 actions; trigger document names the thesis instrument 0, a different instrument 6`;
- `44` catalogued decision models, snapshot `2026-11-19T04:12:13+00:00`;
- primary cache `$0.109210`, blind cache `$0.104451`, lifetime across both `$0.213661` (cap `$5`);
- the primary and blind tables, Wilson intervals, paired bootstrap, diagnostics, hint baselines and both recommendations (`perplexity/pplx-decider-v1.3:free`);
- `9 passed in 0.54s`;
- `log check: headers=1 passed=1 spend-sections=1`;
- `task folder: 3.73 MB in 44 files; largest triage_responses.jsonl 809.0 KB`.

The generated `results.json`, `results_blind.json`, `handlabels.jsonl`, `table.md`, `table_blind.md` and `blind_reliability.json` are byte-identical to the copies I hashed before the re-run. I also independently recomputed the cache costs, row counts, request-key coverage and the rule-versus-blind agreement counts from the raw files; they match the report. The four models have 200 rows each in each cache, no duplicate keys, no refusals and no missing answers.

**Artifact problem.** The delivered `check.log` was not a clean run: it was 363 lines with one header, **two** `9 passed` markers and **two** spend sections, ending with `check.log is not a single clean run: headers=1 passed=2 spend=2`. Its tail is a truncated copy of the blind section, the catalog, the spend line and the tests. The report's round-6 claim that the current log prints `headers=1 passed=1 spend-sections=1` was false for the delivered artifact. My direct re-run produced a clean 275-line log with 1/1/1. The duplication is consistent with the lab runner's own capture: `lab/run_lab.py:515` redirects `bash run.sh` stdout into `work/T20/check.log`, while `work/T20/run.sh:64` also tees stdout to the same path; the two writers corrupt the file. This is not a result-number error, but the entry point fails its own marker check when run under the official check.

## Pass-bar items

1. **The 200 labels are written down, with a sentence of reasoning for every 10th — MET under the lead's ruling.** `handlabels.jsonl` has 200 rows and 440 question labels; `label_reasons.json` has exactly the 20 ordinals 10,20,...,200; every Appendix B row matches the file. They are **rule labels (blind-checked)**, not manual annotation; `SOL_ADVICE.md` rules that naming and the 60-item blind check satisfy the item. Caveats: the second blind pass is not new evidence for `finding_kind` (below), and only 15 of the 23 finding labels were blind-checked.

2. **Every number reproduces from the cache — MET for the results.** The re-run and the independent recomputations match every table, interval, bootstrap, cost, diagnostic and recommendation, and the generated result files are hash-identical. The submitted `check.log` itself was not clean, and the code's own marker check exited 1 under the lab runner; that is a defect in the evidence file/entry point, not in the reproduced numbers.

3. **Spend ≤ $5 — MET for the two delivered caches, with an unresolved lifetime caveat.** Provider-reported `usage.cost` is $0.109210 + $0.104451 = $0.213661. Earlier probe/discarded-cache spend is unlogged, so total lifetime spend is not provable from the folder. `score.py` checks every `triage*.jsonl` in the cache directory; `fetch_triage.py` passes `spent_before` across the two known caches. The `prefetch` cap check is not atomic under its worker threads, but the actual spend is far below the cap.

4. **`og_s1/triage.py` has a test using a recorded response, with no network — MET.** `work/T20/test_triage.py` has nine tests, recorded fixtures, `_post` monkeypatched to raise, `allow_network=False` and a spend-cap test; all nine pass offline.

## Binding `SOL_ADVICE.md`

Of the first ruling, item 1 (naming), item 2 (report the blind check) and item 3 (re-weight) are followed; item 4 (clean `check.log`) is only partly followed because the lab runner re-corrupts the log. Of the round-6 addendum, item 1 (both blind passes side by side) and item 4 (no re-fetch) are followed; item 2 is only partly followed: `finding_kind` is the only ranking question and `label_ok` is descriptive, but the blanket sentence is not written; item 3 (round-5 fixes 1-5) is mostly followed except for the log interaction.

**Item 2 is not followed, and this is the escalation question.** The addendum says: "State plainly that no hosted decision model is shown to beat the majority baseline on any reliable question." The report deliberately does not write that sentence (`REPORT.md:152`, judgement call 14, repeated at `REPORT.md:399`). The reason is factual: on the only reliable question, `finding_kind`, all four models score 0.783-0.957 against a 0.391 majority baseline. The sentence is true for `label_ok` (best 0.743 vs 0.836) but false for `finding_kind`. The worker cannot both obey the binding sentence and obey POLICY rule 7 (no overclaims). That is a methodology/claim-soundness dispute, not a bug the worker can fix by editing code. I therefore do not require the worker to write a false sentence; I escalate the conflict.

## Fixable defects for the next round (not the escalation)

1. **Make `run.sh` pass the lab's check without corrupting `check.log`.** The current `tee` and the runner's stdout redirection write the same file. Write the log to a temporary path and rename it after the run, or stop teeing when stdout is already the log, or remove the internal marker check and let the runner own `check.log`. Re-run once and verify 1 header / 1 `9 passed` / 1 spend section in the artifact the runner captures. Correct the round-6 log claim if the delivered artifact is not clean.
2. **Reconcile the recommendation with the code default.** `REPORT.md:161` says "Use `perplexity/pplx-decider-v1.3:free` as the default triage model", but `og_s1/triage.py:31` still sets `DEFAULT_MODEL = "typesafe/jev-1.14"` and the module docstring says the default is the external T05 model. Either set the default to the recommended model or state explicitly that the recommendation is report-only and the module default is unchanged.
3. **Correct the "two independent blind checks" claim for `finding_kind`.** The no-rules rerun only removes `triage_rules` from the 45 reference/probe/failed items; review findings never had `triage_rules`, so `labels_norules.jsonl` and `labels.jsonl` have the same `finding_kind` values on all 60 items (I checked: 60/60 identical). The second pass is therefore not independent evidence for the only ranked question. Also disclose that only 15 of the 23 finding labels were blind-checked; the ranking uses all 23, with 8 unvalidated labels.
4. **Correct remaining overclaims.** `REPORT.md:189` says the models "expose calibrated probabilities" but no calibration was measured. `REPORT.md:165` and `REPORT.md:307` say "13 of the 23 findings and the 0.957 finding accuracy are historical"; the accuracy is computed over all 23, of which 13 are historical, so say "partly historical". "Statistically indistinguishable" is a failure to reject; the report defines the interval rule, but the wording should not imply proof of equality.
5. **Fix or document the latent drift rule.** `handcheck.py:317-320` treats `drift_position_excess` (post-action position excess) as a drift defect, although the comment and the report's "a reducing sell is allowed" rule say the failure is a buy that increases exposure. No current item triggers it, but a future item could be mislabelled. Use an increase-only condition or disclose the exception.
6. **Minor: make the cap check race-free or state the limitation.** `og_s1/triage.py` `prefetch` checks `spent` under a lock but calls `poster` outside it, so concurrent workers can pass the cap together. Actual spend is $0.214; this is defensive only.

## Loopholes found

- **The lead's blind sample is not fully blind.** It still carries `owner_label` for every item and `task`/`review_verdict`/`section` for the 15 review findings. Only `triage_rules` was removed for the no-rules rerun, and those rules existed only on the 45 non-review items. The `finding_kind` 14/15 agreement is on 15 items with section/task hints; it is not a second independent check of the only ranking question.
- **The ranked labels are only partly validated.** 15 of the 23 finding labels were in the blind sample; the other 8 are the worker's labels. The 0.957 finding accuracy and the recommendation use all 23, and one item moves the metric by 1/23 = 0.043. The report calls the stratum a snapshot, but does not quantify the 15/23 coverage.
- **The labels are a deterministic content rubric, not human annotation.** The lead accepted them under the ruling; the 117/120 agreement with the reference shows the rubric re-derives much of the generator, and the 3 disagreements are a sector-scope design choice. The report discloses both, but a reader should not treat this as independent hand annotation.
- **The primary model input is hint-assisted.** It exposes the exact `triage_rules` on the 177 non-review items and the displayed `owner_label`; the blind condition removes the rules and review metadata but keeps `owner_label`. The displayed-label baseline is stronger than every model on `label_ok`, FinVerify and difficulty (0.836, 0.858, 0.758), so the primary table is not a blind result.
- **The 60-item model side-by-side table uses primary-cache answers.** It is not a blind-condition model result; the report says so in the section and in section 4, but the heading "on the 60 blind items" can still be misread.
- **`failure_kind` and `finverify` are not ground truth.** The blind annotator calls all 15 failures `reasoning_error`; the rule and blind references disagree 0.60 and 0.47-0.53, so the side-by-side table cannot rank models. The report states this.
- **The probe stratum is artificial.** The 20 flipped labels test detection of a deliberately wrong displayed label, not real-world label noise; the report says so.
- **The sample is stratified, not random.** `build_handset.py` uses reference labels and a fixed seed; the family/shift mix is a design choice, not an estimate of the live triage stream. The report says so.
- **The spend is final-cache only.** Earlier discarded-cache spend has no log; the $5 lifetime cap is unverified beyond the two delivered caches.
- **The catalog is a snapshot.** Free-tier availability and prices can change; the report says so. The four-model selection is not a pre-registered census of the 44 entries; the report discloses the absence of a probe log.
- **No held-out/T02/T06/T16 access found.** The code reads `data/ref`, the generated `data/t20`/`data/t20_blind`, `review_findings.json` and `label_reasons.json`; a grep of the task folder found no `heldout`, `T02`, `T06` or `T16` data path. No secret, bearer string or absolute home path appears in the task folder, caches, logs or results. No hard-coded result values were found; the tables, intervals, costs and recommendation are computed from the caches.

## Verdict rationale

The four pass-bar items are met on the evidence, and every reported number reproduces from the cache on a direct re-run. The reason this is not PASS is the binding `SOL_ADVICE.md` item 2: the lead's required sentence is false on the only reliable question, and the worker deliberately declined it rather than write an overclaim. That is a claim-soundness/methodology conflict the reviewer cannot settle, so the task escalates (see `ESCALATION.md`). The `run.sh`/`check.log` harness interaction, the code-versus-report default mismatch, the "two independent checks" overclaim, the 15/23 validation gap and the minor overclaims are fixable and should be handled in the next round regardless of the escalation answer.
