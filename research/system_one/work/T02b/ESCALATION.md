# Escalation — does T02b owe a `binding_error` family?

Reviewer verdict is REVISE (see REVIEW.md); this file isolates the one spec
question the lead may want to rule on. It supersedes the worker's resolved
Round-4 metric note, archived at the bottom.

## The problem

BRIEF.md "Families to generate" says: "all the causes in SCHEMA.md: clean,
drift, unsupported_claim, misquote, vague_hype, poisoned_note, authority_spoof
and stale_thesis". That enumeration lists 8 of the 9 causes actually defined in
SCHEMA.md §3 — it omits `binding_error`. The pass bar says "Every family is
present." The worker generated exactly the 8 enumerated families plus 2 novel
ones (10 total) and no binding_error (0 such labels in out/episodes.jsonl).

## What was tried

I read BRIEF.md, SCHEMA.md, og_s1/schema.py and og_s1/validate.py and re-ran
run.sh (1500 episodes, 0 errors; output byte-identical to the delivered file
and to REPORT.md §3). Findings: SCHEMA.md §3 defines binding_error in detail
(wrong entity / wrong period / rationale direction opposite to side / sibling
presented as the traded name) and requires ≥1 cause_ref; validate.py line 521
enforces that rule. SCHEMA.md §4 also requires an "explicit relative-value
comparison" hard negative in clean episodes, which is the clean counterpart to
binding_error; I found 0 such texts in any clean episode. schema.py's
KNOWN_CAUSES tuple still lists only the old 8 causes, but it is unused by the
validator, and SCHEMA.md + validate.py (both updated together) are the
authoritative contract. So the schema and validator clearly support and
document binding_error; only the BRIEF enumeration omits it.

## The gray area

Two readings of the pass bar:
(a) "Every family" = the families BRIEF explicitly enumerates → the worker is
compliant, and binding_error is out of scope for this task.
(b) "Every family" = "all the causes in SCHEMA.md" (BRIEF's own governing
phrase) → binding_error is required and currently missing.
The enumeration is demonstrably incomplete relative to the document it cites,
which favors (b); but the explicit list and five prior review rounds that
accepted 10 families favor (a). I resolved it toward (b) in REVIEW.md (fix 1)
because the schema is "the whole contract" and the validator enforces the
cause, but this is a scope interpretation the lead can settle definitively.
The other REVISE items (missing relative-value hard negative, control-note
overclaim, dead fallback, report inaccuracies) stand regardless of this ruling.

## One precise question

For T02b, does "Every family is present" require generating SCHEMA.md's
`binding_error` cause (and its paired relative-value hard negative), or is the
BRIEF's eight-family enumeration exhaustive and binding_error out of scope?

---

## Archived: worker's Round-4 note (superseded, resolved)

Status: resolved in Round 4. The 5% sentence-variety bar was not operationally
defined; exact strings passed but number-masking made one template recur in
34% of poisoned_note. Fixed by replacing templates with compositional pools
(lexicon.py, phrasing.py); run.sh now reports exact, number-masked and
number+company-masked recurrence, all below 5%. No further decision needed.
