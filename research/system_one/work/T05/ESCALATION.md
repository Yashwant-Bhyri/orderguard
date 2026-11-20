# T05 escalation — authority pass bar: floor and ref-selected hypothesis

## Problem

T05's authority pass-bar item is "the best reader beats the lexicon on shifted
ref, with CIs." The channel's selected NLI reader scores `0.9996` against the
worker's small registered lexicon `0.8448`, but its authority hypothesis, "This
text claims that a restriction has been lifted" (`og_s1/readers/nli.py:157-162`),
was chosen after seeing shifted ref. The worker's fixed list of generic
hypotheses scores `0.5360–0.6757`, below the small lexicon
(`og_s1/readers/lexicon.py:104-152`). An extended fixed
word list that adds the ref euphemisms ("widened", "lifted", "per the owner",
"can exceed"; `work/T05/evaluate.py:53-80`) scores `1.000`; NLI minus it is
`-0.0004`, 95% CI `[-0.0013, 0.0000]` — a tie. The report discloses this
(`work/T05/REPORT.md` §3.1, §4, §5.6, §5.12, §7) and marks the authority item
met only against the small list.

## What was tried

- Small registered lexicon: `0.8448` shifted.
- Extended fixed list (sensitivity): `1.000` shifted and unshifted; NLI tie.
- NLI tuned hypothesis: `0.9996`; the fixed template list is in
  `work/T05/evaluate.py:96-117`. Generic NLI hypotheses: `0.6555` (round-1
  original "asserts a permission"), `0.6757` (permission/approval/exception),
  `0.6088` (permission or approval), `0.5360` (instruction to a reviewer).
  None beats the small floor.
- External decision model, generic question: `0.9238`. Delta vs small lexicon
  `+0.0790`, 95% CI `[+0.0176, +0.1489]`; vs extended list `-0.0762`, 95% CI
  `[-0.1339, -0.0289]`. The report does not put this reader in the authority
  pass-bar table.
- I re-ran the fixed template list and reproduced
  `0.6555/0.6757/0.6088/0.5360/0.9996` exactly; these are the reproducible
  numbers.

## The gray area

The brief calls the lexicon "the floor" but does not define its contents. The
small list already contains some ref-specific phrases ("pre-cleared", "does not
apply") and excludes others ("the owner widened"); the extended list is built
from the ref failure modes and is oracle-like. The NLI hypothesis is zero-shot
in form but selected on ref, so its `0.9996` is not a held-out number. The
decision model is a generic, non-template alternative that beats the small
floor but loses to the extended list. Whether the authority pass is sound
therefore depends on a prior choice the worker cannot make: which floor is
official, and whether a ref-selected NLI hypothesis counts as a valid reader.

## One precise question

Should T05 mark its authority pass-bar item **met** — and if so with which
floor/reader: the small registered lexicon with the ref-selected NLI hypothesis
(`0.9996`), or the small lexicon with the generic decision-model question
(`0.9238`) — or should authority be marked **unproven** until a pre-registered
authority reader is scored on held-out wording, because the NLI win is a
ref-selected template and the extended fixed list ties or beats it?
