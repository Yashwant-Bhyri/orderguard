# T14 escalation note — non-blocking

The verdict in `REVIEW.md` is REVISE. This note records the one architecture
gray area so the lead can settle it if they want to; it is not a request to
pause the worker, because the worker can implement both options behind a config
and keep working.

## The problem

The single-root-source cap groups only **untrusted** roots. `_untrusted_roots`
in `og_s1/taint.py` returns documents, notes and claims whose own provenance is
below the trust threshold, plus terminal nodes whose propagated trust is below
it. A tier-2 or tier-3 document cited by many actions is never grouped. The
brief says "Group actions by the root documents their evidence traces back to"
and does not restrict that to untrusted roots. The report's own Open risks says
"A compromised high-trust source is invisible to the cap."

## What was tried

I read the T14 brief, `REPORT.md` (especially 5.5 and 7), `COMBOS.md` sections 1
and 2, and the cap code. I re-ran `bash run.sh`: all pass-bar items are met and
all reported numbers reproduce. I also probed `build_why_graph` and
`_untrusted_roots` directly:

- a trusted tier-3 root cited by repeated actions produces no cap root;
- a missing thesis stub has trust 0 and `shortest_chain_length` 1, but
  `_untrusted_roots` returns no root and `taint_untrusted_root_count` is 0;
- an external note with no documents is a root at trust 1; an agent note with
  no documents is not a root (trust 2); only a missing note is trust 0.

The first is the architecture question below. The other two are REVISE fixes in
`REVIEW.md`.

## The gray area

The report argues that all-root grouping "would flag every thesis whose
evidence is reused, which is normal", so it groups only taint roots. That may
be right: the task's Why paragraph is about low-trust text, and the swarm
monitor's example is "one poisoned feed". But a compromised trusted feed is
also a single root source, and the brief's wording does not exclude it. The
worker's choice is documented, but it is a narrowing of the brief, so it should
be an explicit decision rather than a report-only assumption.

## One precise question

For T14's single-root-source cap, should the default group **every root
document regardless of trust**, or **only untrusted taint roots** (with
trusted-root grouping as an opt-in config)? If the answer is "untrusted only",
the report should say that the brief's "root documents" means taint roots, and
the trusted-root case stays an accepted limitation rather than a silent gap.

## Round 2 resolution (non-blocking)

The worker did not wait for a ruling. It implemented both options behind
`root_cap_include_trusted`: the default is all-root grouping (all root
documents plus untrusted non-document sources), and setting the flag to false
restores the untrusted-only monitor. Both modes are measured in `REPORT.md`
Section 3. The all-root default is noisier on `data/ref` because thesis
evidence is reused; that is reported, not hidden. The lead can still settle the
scope question without a code change.
