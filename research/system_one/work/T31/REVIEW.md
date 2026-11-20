# T31 Review (provisional — audit in progress)

VERDICT: REVISE

Provisional: REVIEW.md written early so a timeout leaves a verdict. This file
is being updated as the re-run and audit proceed.

Initial observations from reading REPORT.md and check.log:

- check.log is corrupted/duplicated: after the full test suite at line 208 it
  contains a stray table fragment and then repeats sections 5-7 in full
  (lines 209-326). The captured evidence is therefore not a clean single run.
- REPORT.md says v2.1 generation took "29.60 s at 121.62 episodes/s" but the
  captured check.log says `elapsed=80.03s episodes_per_second=44.98`. The
  report claims all numbers come from that capture.
- In check.log section 4, the first rates table reports
  `claim_source_entity_mismatch=3174` for `unsupported_claim`, while REPORT
  says that finding is 0 on every v2 negative and the later finding-count
  table also reports 0. Column/count inconsistency to be traced.
- Shifted and unshifted v2 rates are byte-identical for six of eight families
  (including `clean`), which needs a code-level explanation rather than
  assumption.

(remaining sections to follow after re-running `bash run.sh`.)
