# Lead ruling on T08 (2026-11-19). It binds reviewers.

**The escalation question:** can 2026q1 be called an evaluation?

**Ruling:** no. 98.7% of the q1 series also file in q2, the quarter used to fix the classifier. q1 is a **frozen-rule score of the same funds at another date**, not a test of generalisation. The brief never required a holdout, so this costs nothing against the pass bar. Only the wording changes:
1. Rename q1 to "frozen-rule score (2026q1, same funds as the exploratory quarter)" in `REPORT.md`, `results.json` keys and the tables. Remove "holdout tests whether the rule generalises".
2. Report two small, honest subsets beside it:
   - the q1 series that do **not** appear in q2 (fund-disjoint, small, stated n);
   - q1 with the series whose names match the post-hoc "Equity Plus Bond" pattern removed, so the effect of that one fix is visible.

## The last round (the lead grants one more, round 4)

Fix the review's other findings. These are pass-bar or privacy items, not wording:
- **Every flag carries a link.** This is a pass-bar line. Write `flags.csv` with **every** strong and any-test flag: series id, fund name, test, share, and the EDGAR filing link built from the accession number. No network is needed to build the link.
- **Privacy scan.** Delete `__pycache__` in `run.sh` before the scan, and stop skipping `.pyc` files. The scan must find nothing because nothing is there, not because it skips it.
- **`EP`:** treat preferred as neither equity nor debt in the bond test, consistent with declaring it untestable. Report how many funds change (the review says seven).
- **"Any test" coverage line:** split out the 765/789 structural exclusions; do not fold them in.
- **`check.log`:** produce it from one clean run so the file inventory reproduces.
- `verify_edgar.py` stays skipped without `SEC_USER_AGENT`. Add one offline unit test of its parser on a saved fixture, so the bug the review mentions is covered.
