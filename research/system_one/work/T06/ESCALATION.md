# ESCALATION — reviewer record (round 5)

Status: NO LIVE ESCALATION. Verdict is REVISE. Every finding is fixable by the
worker, so per the review rules nothing is escalated to the lead. This file
records the one gray area I considered, how I settled it myself, and preserves
the worker's earlier historical note.

## The problem

The BRIEF pass bar says "No two attack texts more than 80% identical" but does
not define "attack text". The worker reports two definitions (full attack text
= rationale + claim text + quoted spans + cited-note text; core payload = first
rationale sentence + first claim sentence) and both pass. My exhaustive
all-pairs audit (sound indel upper bound over all 134,940 attack pairs, then
exact difflib) confirms full-text max 0.7743 and core max 0.7450, 0 pairs >=
0.80. But under a rationale-ONLY reading, one pair exceeds the bar:
false_attribution seeds 37 and 61 (both MSFT sell 15,000) at 0.8030. Six more
rationale-only pairs sit at 0.755-0.783.

## What was tried

- Re-ran ./run.sh: 0 validation errors, 740/740 deterministic, byte-identical
  corpus. Verified every REPORT number independently (counts, book replay
  243/277, claim audit 902/821/82, facts 2,805/0, spans, hashes).
- Removed the worker's 0.05 Jaccard screen with a provable bound: difflib ratio
  <= rapidfuzz indel similarity (matching blocks are a common subsequence, so
  M <= LCS). Bound validated empirically (0 violations / 3,000 pairs). This
  proves the disclosed maxima are the true exhaustive maxima for full/core,
  and that rationale+claims (0.7548) and raw full text (0.7725) also pass.
- Inspected the crossing pair: a stride collision (base=seed+49 gives 86 and
  110; (base*7+1)%8=3 and (base*13+2)%6=4 for both) selects the same conclusion
  clause and reference-tail frame, compounded by the fixed metric literal
  "order cut" and an identical target. Their full-text ratio is 0.6659.

## The gray area

Whether "attack text" must include the claim. For false_attribution the false
provenance lives in the CLAIM text ("audited annual report"), so a
rationale-only view strips out the very locus of the attack. Under any
definition that includes the claim, the bar holds. The round-1 escalation on
this ambiguity was closed in round 2 once both disclosed definitions passed.

## One precise question (resolved, not live)

"Must the 80% diversity bar hold for the rationale alone, or only for text that
includes the attack's claim?" I settle it myself: the disclosed definitions
(which include the claim) are reasonable and were accepted in round 2, so the
pass-bar item is MET; but the rationale-only crossing is a real template-clone
fragility and is required to be fixed (REVIEW fix #2) so the corpus is robust
to the stricter reading. This is a concrete generator defect a REVISE can fix,
not a methodology dispute requiring a ruling — hence no escalation.

## Historical note (worker, round 1-3, preserved)

The round-1 question was whether "attack text" meant the full emitted text
including audit boilerplate or only the attack-specific payload. Round 1 passed
only under the padded definition (core 0.9941, 5,265 pairs >= 0.80). Round 2
removed the padding; round 3 removed shared process-line sentences and
rebalanced sizes/structure. Both definitions now pass (full 0.2135/0.7743,
core 0.1520/0.7450, 0 pairs >= 0.80), so the ambiguity no longer changes the
verdict. (The worker's retained figure of 0.7859 for whole-episode exact char
max is stale; the current run measures 0.7772 — see REVIEW fix #4.)
