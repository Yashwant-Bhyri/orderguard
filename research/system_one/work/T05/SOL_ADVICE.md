# Lead's answer to the T05 escalation (2026-11-19; Codex and Sol are out of quota, so the lead answers)

**Decision: mark the authority item MET against the registered floor, using the generic decision-model question only. Report everything tuned on ref as a sensitivity, never as evidence. Freeze all candidate readers now, for scoring on unseen wording.**

1. **The official floor is the small registered lexicon,** exactly as committed before you looked at the shifted ref. The extended list is built from the ref failure modes, so it is an oracle. Report it as an upper-bound sensitivity, never as a reader or a floor.

2. **Only a reader whose wording was fixed before seeing the ref can carry the pass bar.** Of the candidates, that is the external decision model's generic authority question:
   - +0.079 over the small lexicon;
   - 95% CI [+0.018, +0.149], which excludes zero.

   Mark the item met on that basis, and say so in the pass-bar table.

3. **The NLI hypothesis chosen on ref** ("claims that a restriction has been lifted", 0.9996) is a legitimate candidate. Its ref score is not evidence, because the hypothesis was selected on ref. Report it as "ref-selected; not a held-out number". The generic NLI hypotheses (0.54–0.68) are the honest NLI result on ref: below the floor.

4. **Freeze, today, in a file `work/T05/PREREGISTERED.md`:**
   - the small lexicon;
   - the extended list;
   - every NLI hypothesis;
   - the decision-model question.

   Give each its exact text and a sha256 of the reader configuration. T07 and T11 will score these frozen readers on the unseen worlds (T02a–d, T16). Whichever wins there is the real answer. Nothing more may be tuned on ref for authority.

5. **Add a short "What ref cannot tell us" paragraph to REPORT.md.** On ref, authority euphemisms are a small, repeated set, so word lists look perfect. The open question is whether any reader holds on wording it has never seen. That is decided downstream, not here.

## Addendum after round 3 (lead, 2026-11-19). It binds reviewers. Final round 4.

The substance is met. Round 4 fixes provenance and consistency only. Make the round-3 reviewer's required fixes 1–7, with these lead decisions:
- **Authority default (fix 2 and fix 5).** `og_s1.text.DEFAULT_READERS["authority"]` becomes the generic decision-model question. If its cache or key is missing, the channel returns `None` for authority with a reason. It never falls back to the ref-selected NLI. The NLI reader stays as a named sensitivity reader. `results.json["pass_bar"]` uses only eligible readers.
- **Bootstrap seed (fix 3).** Use one seed for every comparison and report the interval it gives. Add one line noting that the round-2 ruling quoted [+0.018, +0.149], from an earlier seed. This does not reopen the ruling.
- **Preregistration (fix 6).** `PREREGISTERED.md` becomes static. `run.sh` recomputes the hashes and fails on any mismatch. Changing a reader means writing a new preregistration file, never overwriting this one.
- **Model cache (fix 7).** The lead grants an exception for T05's four CPU checkpoints (1.6 GB under `data/models/hf/`): T07 needs them on the Mac. This exception covers only these four. GPU-size models stay on the host (T11).
- **Every number** in `REPORT.md` comes from the one run that wrote the delivered `results.json`, through code, not typed by hand. Ratio claims ("about N× faster") are computed or removed.
