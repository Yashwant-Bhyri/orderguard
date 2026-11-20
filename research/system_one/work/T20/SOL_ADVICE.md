# Lead ruling on the T20 escalation (2026-11-19)

**Question:** do the deterministic content-rule labels satisfy "The 200 hand labels are written down"?

**Ruling:** yes, under their true name and with an independent check. The lead had a blind sample of them labelled by a model from another family, so they are no longer one annotator checking itself. The item is **met** once the changes below are made. This ruling binds reviewers.

## The independent check the lead ran

The lead drew 60 items from `handlabels.jsonl`, 15 per question kind, and removed every field that names the family, the id or the source. Claude Haiku labelled them blind from `QUESTIONS.md`, in a separate context that had never seen `handcheck.py` or the reference labels. Files are in `blind_lead/`:
- `items.jsonl`: what the annotator saw;
- `.key.json`: item to id;
- `labels.jsonl`: Haiku's labels;
- `agreement.json`: the counts.

| Question | Rule vs blind agreement | Verdict on the rule labels |
|---|---|---|
| `label_ok` | 26/30 = 0.87 | **Reliable.** One of the four disagreements is a reference defect (below) |
| `finding_kind` | 14/15 = 0.93 | **Reliable** |
| `failure_kind` | 9/15 = 0.60 | **Unreliable.** On unsourced claims, the rule says `missing_information` and the blind reader says `reasoning_error`. The claim's `source_doc: null` is visible in the case, so the blind reading is at least as defensible |
| `finverify` | 8/15 = 0.53 | **Unreliable** as a single reference |
| `difficulty` | 3/15 raw; 6/15 exact and 13/15 within one step after aligning scales (rule 0–2, blind 1–3) | **Coarse.** Use only as a bucket, never to rank models |

**A reference defect, not a rubric error.** In `ref:clean.jsonl:57:80`, the action sells PEP. Its claims are about CL and COST, and its rationale says "We add COST…". It is still labelled clean. The generator does this on about 15% of reference negatives. The lead has opened **T31** to fix it. Record this item as a disagreement caused by the reference.

## What the worker must change (one round)

1. **Name.** Call them "rule labels (blind-checked)" everywhere: `REPORT.md`, `table.md` and `table_blind.md` headings, and code comments. Do not call them "hand labels".
2. **Report the blind check.** Add the table above to `REPORT.md`, generated from `blind_lead/agreement.json` by a script, not typed by hand. Say in one sentence how the lead drew the sample.
3. **Re-weight the headline.** Report each decision model's accuracy as follows:
   - `label_ok` and `finding_kind`: primary, against the rule labels, with intervals as now.
   - `failure_kind` and `finverify`: on the 60 blind items, give each model's agreement with the rule labels **and** with the blind labels, side by side. Use the cached model answers only; no new API spend. State that neither reference is ground truth for these two questions.
   - `difficulty`: drop it from any ranking.

   Restate the conclusion ("the hosted decision models are about at the majority baseline") only for the questions where the reference is reliable. If it changes, say so.
4. **Clean the duplicated `check.log`** with one re-run.

## What the lab takes from this

- A decision model is acceptable as a **triage tool** only for questions where an independent reading agrees with our labels at least 0.85 of the time. Today that means `label_ok` and `finding_kind`. FinVerify categorisation needs a better reference before any model is scored on it. T19 and T24 should not use `finverify` labels from T20 as ground truth.
- The 0.60 on `failure_kind` is a finding in itself. "Missing information" and "reasoning error" are not cleanly separable on unsourced claims. The taxonomy needs a rule for that case before it is used for training labels.

## Addendum (2026-11-19, after round 5). It binds reviewers.

The round-5 reviewer was right: the lead's blind items still carried `triage_rules`, and Haiku's reasons quote them. The lead reran the check with `triage_rules` removed (`blind_lead/items_norules.jsonl` → `labels_norules.jsonl`; counts in `blind_lead/agreement_norules.json`).

| Question | Rule vs blind, rules shown | Rule vs blind, no rules | Reliable? |
|---|---|---|---|
| `finding_kind` | 0.93 | 0.93 (14/15) | **Yes**, the only one |
| `label_ok` | 0.87 | 0.73 (22/30) | **No, not yet.** 6 of the 8 disagreements are the reference defect T31 fixes: the "clean" action argues about another stock, cites a figure from another company, or argues the wrong direction. There the blind reading is the right one. The other two (`ref:clean.shifted.jsonl:24:80`, `ref:poisoned_note.shifted.jsonl:188:33`) go to T31 to check |
| `failure_kind` | 0.60 | 0.60 | No |
| `finverify` | 0.53 | 0.47 | No |
| `difficulty` (aligned) | 0.40 | 0.20 | No |

**What changes for the final round (round 6):**
1. Report both blind checks side by side, generated from the two agreement files, with one sentence on why the rerun was needed.
2. **Rank only on `finding_kind`.** Report `label_ok` descriptively, with the note that its reference is defective until v2.1. State plainly that no hosted decision model is shown to beat the majority baseline on any reliable question.
3. Make the reviewer's required fixes 1–5 from round 5.
4. Do not re-fetch. The cache stays as it is.

**After T31 passes,** the lab will rescore `label_ok` on reference v2.1. That needs no new spend for scoring, and at most $0.25 if new items are fetched. It is backlog item T32.

## Addendum 2 (2026-11-20): answer to the round-6 escalation. It binds reviewers.

The round-6 sentence "no hosted decision model is shown to beat the majority baseline on any reliable question" is **withdrawn**. It was written expecting the earlier combined result, and on `finding_kind` it is false: all four models score 0.783–0.957 against a 0.391 baseline (n = 23). The report's per-question statement is the correct one:
- on `label_ok`, no model beats its 0.836 baseline (best 0.743);
- on `finding_kind`, all four beat the 0.391 baseline, with the small-n caveat the report already gives.

Item 2 is met as the worker wrote it. No other change is required by this ruling.
