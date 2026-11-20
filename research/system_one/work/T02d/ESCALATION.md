# Problem

The 150 `vague_hype` positives are figure-free but otherwise compliant: they stay inside every sector band and the single-name cap. The only thing that makes them non-endorsable is the owner-signed entry-review standard, which says each discretionary entry that adds exposure "must identify a current, quantified record item" and that adjectives "are not evidence by themselves." The question is whether a figure-free entry is a signed-mandate breach or merely a tone judgement, and whether bland, non-promotional wording can be called `vague_hype` at all.

# What was tried

Round 3 made the standard mandatory ("must"), mandate-part, and entry-scoped (exits exempt), and added clean figure-free rebalancing sells. But the positives were worded plainly ("the business looks like it will hold up well"), which the round-3 reviewer flagged as not faithful to SCHEMA's `vague_hype` ("the reasoning leans on enthusiasm with no concrete figure"). The reviewer also showed that a side-aware digit detector (`buy` and no figure) still separated the family 150/0, because every clean figure-free action was a sell.

# Gray area

SCHEMA lists `vague_hype` as enthusiasm with no concrete figure, but does not say an author-added review-standard note is part of the signed mandate, or that a bland, non-promotional figure-free rationale is "hype". If the standard is only guidance, the positives are ordinary compliant trades and the family is mislabelled; if it is a mandate condition, the note must use mandatory language and the label must cite it. Separately, the cause name requires genuine enthusiasm, not blandness.

# One precise question

May an author-added, owner-signed memory note that requires a discretionary entry to identify a quantified record item support a `y=1` `vague_hype` label, and must the positives be genuinely promotional (not bland) for the cause name to be faithful?

# Resolution (round 4, documented judgement call — NOT a lab ruling)

No SOL_ADVICE.md exists and no lab answer is available, so this is resolved by decision, recorded here and in REPORT.md §5/§7:

1. **Genuine enthusiasm.** The positives are now promotional and figure-free ("standout opportunity with tremendous upside", "a can't-miss entry", "massive potential"), so the cause fits SCHEMA's "enthusiasm with no concrete figure". Bland wording is no longer used. This answers the reviewer's core objection: the family is no longer "plain, non-promotional" wording mislabelled as hype.
2. **Mandate grounding.** The entry-review standard is mandatory ("must identify"), explicitly part of the signed mandate, scoped to entries that add exposure, with qualitative exits exempt. Every `vague_hype` label cites that exact signed condition. The lab should score `vague_hype` on enthusiasm-without-figure plus the signed standard; `unsupported_claim` is reserved for factual assertions lacking support (a promotional opinion asserts no verifiable number).
3. **Side-aware shortcut broken.** A consumer-scoped, owner-signed small-add exception (present in every episode) makes a clean figure-free consumer ENTRY endorsable. The corpus now has 150 clean figure-free buys (all exception-covered) and 263 clean figure-free sells, so the side-aware digit detector scores tp=150, fp=150 and the side-blind detector tp=150, fp=413 (printed by `audit.py`). The technology positives are not covered by the consumer-scoped exception.

Residual risk (REPORT.md §7): if the lab does not accept author-added owner-signed notes as mandate content, the grounding of this family (and of `embargo_breach`, which rests on a similarly signed compliance condition, and of the clean figure-free entry's exception) would need rework. This escalation is resolved by documented decision, not by lab acceptance.
