# Escalation

**Status: resolved in round 2; no policy decision is now requested.**

The round-1 question was whether `thesis.invalidation` counts as a sentence and
whether the 5% share is pooled across the file or computed per family.

I took the conservative reading and met the bar on both: `check_variety.py` now
includes `thesis.invalidation` and every other narrative string, and enforces
the 5% limit on the pooled denominator and on a per-family denominator. The
invalidation text is generated from templates seeded with entry/trigger values,
so it is no longer a fixed string. Current result: worst pooled exact-sentence
share 0.733%; worst per-family share 4.000% (drift).

Remaining note: the optional digit-normalised line is 5.467% pooled. That
normalisation is not part of the brief's pass bar; it collapses short sentences
that differ only by one number (for example an ETF expense ratio). Exact
sentences are far below the limit.
