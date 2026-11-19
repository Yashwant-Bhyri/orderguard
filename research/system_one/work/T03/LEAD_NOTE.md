# Lead note on T03 (2026-11-19)

**Verdict: PASS (lead).** Four review rounds found every pass-bar item met:
- 36 T03 tests pass;
- p99 latency is about 1 ms per action;
- the code has no wording logic;
- the code is causal per action;
- every cause group's best shifted AUROC is at least 0.80.

The round-4 review's required fixes are accepted as follows.

**Report corrections (items 1–6), recorded here instead of a fifth round:**
1. The structural layer reads document text in exactly one place: the exact quoted-span substring test. It reads no claim, note, thesis or rationale prose. It *can* be fooled by misleading surrounding prose around an accurate quote. That is the text channel's job (T05, T11), not this layer's.
2. The round-1 and round-2 shell commands under `runs/T03/` logged an absolute home path. The current task-folder files and `check.log` are clean.
3. The task folder also holds `ESCALATION.md`, `REVIEW.md` and a `__pycache__` directory.
4. Every claim gets the source-presence check. Claims with a source get the availability and span checks. Claims with an available source and a unit or numeric value get the unit check.
5. The evidence-quality line treats every action in a non-clean family as positive, including that family's hard negatives. It is descriptive only, not a pass-bar number.
6. Clean reference episodes show no out-of-band drift failure signal. Ordinary turnover and position ratios are non-zero, as expected.

**Fragilities (item 7):**
- **(a) A sell that pushes a sector below its minimum counts as an out-of-band move.** Kept deliberately: below the signed minimum is outside the owner's band too. T07 should report it separately on the unseen worlds.
- **(b) Invalidation triggers matched facts by name only.** **Fixed by the lead** in `og_s1/checks.py`. If a trigger carries an optional `unit`, a fact with the same name fires it only if its unit has the same dimension, and both values are converted to base scale first. The schema's trigger has no unit, so the reference world is unchanged. Regression test: `og_s1/tests/test_lead_fixes.py::test_invalidation_trigger_respects_units_when_given`. 106 tests pass.

**What the numbers mean.** The shifted AUROCs of about 1.0 show that the code checks catch what the reference generator plants, in the form it plants it. That is the circularity the independent blueprints warned about. The real test is T16's messy benchmark, where documents carry no structured facts, and the independent worlds T02a–d.
