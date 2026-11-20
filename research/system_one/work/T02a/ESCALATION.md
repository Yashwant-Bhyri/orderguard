# Escalation note — T02a review (round 6)

Verdict: REVISE. No high-level question blocks this review. The REVISE is driven
by concrete, locally fixable marker defects (see REVIEW.md section 3), not by an
architecture choice, a soundness dispute, or a methodology question. I settled
the two interpretive gray areas myself from the documents:

- Label-rate metric: SCHEMA defines Label per action, so "label rate" =
  positives/all-actions (21.7%-22.9%, in the 5%-60% band). The episode-level
  positive share (1.000 failures / 0.000 clean) is a different quantity, printed
  and disclosed separately; the episode-level reading is incoherent with
  "meta.family names the planted failure family". Accepted action-level. No
  escalation needed.
- shifted: a recorded flag only (content identical for True/False, verified);
  SCHEMA says "may use", so permissible. No escalation needed.

## The one gray area worth a lead decision (non-blocking)

Problem. SCHEMA.md section 3 lists `binding_error` as a failure cause (with
detailed semantics and a relative-value hard-negative rule), and
og_s1/validate.py has a binding_error-specific check (cause_refs required). But
BRIEF.md's deliverable list says "all the causes in SCHEMA.md: clean, drift,
unsupported_claim, misquote, vague_hype, poisoned_note, authority_spoof and
stale_thesis" — an explicit enumeration that omits binding_error. The worker
generated exactly those 8 plus 2 novel families (liquidity_breach,
withdrawn_target); there is no binding_error family.

What was tried. I read BRIEF, SCHEMA and validate.py together. BRIEF's explicit
enumeration is the more specific, operative deliverable spec, and the worker
matched it exactly, so I scored pass-bar item "Every family is present" as MET
against that list. The SCHEMA/validator support for binding_error looks like a
spec update (SCHEMA and validate.py both timestamped 19 Nov 17:09) that BRIEF's
enumeration did not pick up.

Gray area. Whether "all the causes in SCHEMA.md" should be read literally
(include binding_error) or as the explicit enumeration that follows it (exclude
binding_error). The two authoritative documents disagree. This is a spec
inconsistency, not a worker defect: if binding_error is required, the fix is to
add one family (a REVISE item), which is why I do not escalate it as a blocking
question.

One precise question. Does the T02a pass bar require a `binding_error` family
because SCHEMA.md lists it as a cause, or is BRIEF.md's explicit eight-family
enumeration (which omits binding_error) the definitive deliverable list? If the
former, the worker must add a binding_error family (right value bound to the
wrong entity/period, or rationale direction opposite to side, with a cause_ref
to the carrying document, plus the explicit relative-value hard negative); if
the latter, the current 10-family corpus satisfies "Every family is present"
as written.
