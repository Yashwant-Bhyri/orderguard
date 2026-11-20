# Brief: regenerate CS-0001 to blueprint v2

**Read first:**
- `docs/vision/lab/CS_BLUEPRINT.md` (version 2 of the paradigm, which wins where it differs from version 1); Parts B and C matter most;
- `research/system_one/cs1000/reviews/CS-0001_REVIEW.md` (what failed, and why);
- `research/system_one/cs1000/tools/audit_case.py` (the new hard gates).

**Keep:** the owner, the mandate and the story of CS-0001. They are good. Move the current case to `cases/CS-0001-v0/` and leave it untouched.

**Change:**
1. **No shortcut.** At least 25% of bad decisions are sells, rebalances, thesis updates or owner requests. At least 30% of bad decisions are small orders. Some large orders are benign. `audit_case.py` H1 must report leave-one-out AUROC ≤ 0.65.
2. **Neutral documents.** Remove every sentence that comments on a trap ("does not describe…", "no evidence in this document supports…", "the review found that…repeated…", "makes no commitment…"). State facts as filings and news state them. Put figures in tables and footnotes.
3. **Realistic lengths.** At least 30% of items at 80–600 words. Keep the long mandate and filings.
4. **The agent's own voice.** Rationales of 2–5 sentences in the people-pleaser persona, never a copy of a claim. Some combine several claims; some reason soundly on a wrong figure.
5. **Theme depth.** Binding and grounding gets 4–6 binding errors with different subtypes: period, entity, metric, scope, guidance against actual. Each has a lookalike that is correct.
6. **Separate gray and ask_owner decisions.**
7. **At least one decision that is the right action for the wrong reason** (`reason_flag`, blueprint C9).
8. **Runnable probes.** For each probe, write `probes/<id>.state.json` (the actual variant) and `model_input.variant_state_ref`, plus a recorded diff from the base state.
9. **`reasoning.jsonl`.** The ideal reasoning chain for every decision, in the format of blueprint B5, with required and forbidden elements and the minimal sufficient evidence.
10. **Difficulty.** At most 40% of decisions at difficulty 1.
11. **Length.** 60–90 decisions. Short is fine, but 40 is the floor, not the target.

**Done when:**
- `python tools/validate_case.py cases/CS-0001` passes;
- `python tools/audit_case.py cases/CS-0001` passes every hard gate (H1–H7), with S1 and S2 passing or explained;
- the case card lists the capabilities (C1–C12) each hard decision tests;
- you stop for founder review before starting CS-0002.

**Do not:** commit, push, run models, or open anything under `data/heldout*` or `work/T02*`, `work/T06`, `work/T16`.
