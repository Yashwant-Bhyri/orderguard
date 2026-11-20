# Escalation — model-visible scenario metadata

## Problem

The benchmark's model-facing view leaks the planted scenario. `generate()` puts `scenario_type` and `truth_type` on every action (`generator.py:73`). The provided `og_s1.schema.model_view()` strips only the top-level `meta` and each step's `label` (`og_s1/schema.py:366-369`), so both fields survive into the supervisor's input. The values identify the family directly: `authority_spoof`, `shared_poisoned_source`, `future_data`, `benign_legitimate_adaptation`, and so on. Document, note and thesis ids leak the same information (`n_fake_authority`, `d_social_poison`, `d_cache_log`, `n_no_energy`, `n_issuer_limit`, `d_fresh`, `th_adapt`).

I verified the consequence: a rule using only `action.scenario_type` plus the step index (`purpose_drift`/`concentration_build` negative from step 2 onward; `benign_*` clean; all other families negative) scores 960/960 = 1.000 on the released labels. `scenario_type` alone scores 720/960 = 0.75. A model can therefore pass without reading any document, rationale or claim, and the “benign look-alikes” hard negatives are vacuous because the action itself says `benign_*`.

The report acknowledges the design: “Endorsed actions use `cause='clean'`; the scenario is recorded in `action.scenario_type`” (`REPORT.md:49`). `run.sh:43` asserts the fields exist but never inspects `model_view` or checks for leakage. The report's “loopholes I checked” section does not mention this.

## What I tried

I reran `bash run.sh` twice. It reproduced 600 episodes, 240/600 messy, 180 benign, 1,350 unique attack texts, 0 validation errors, and the same JSONL SHA-256. I then called `model_view()` and `model_view_at()` directly on generated episodes: both retain `scenario_type`, `truth_type`, semantic ids and `cites_notes`; only `meta` and `label` disappear. I tested the trivial metadata classifier above and confirmed 100% accuracy on all 960 labelled actions. I also checked the worker's prior future-data escalation; Round 3 resolves it by removing post-action documents, and I verified that future-data episodes contain no document timestamped after the action.

I found no evaluator interface definition in this folder that states whether extra action fields are stripped before scoring, and the brief does not say whether `truth_type` is evidential metadata or model input. The schema says `meta` and `label` are evaluation-only and that every downstream model must consume `model_view`; that implies extra fields should not encode the scenario, but `model_view` does not enforce it.

## The gray area

The brief requires every action to carry `label.y`, “a `cause` naming the scenario type”, `cause_refs` and `truth_type`. The worker satisfies the scenario/cause requirement partly through `action.scenario_type` and `action.truth_type`, which are visible to the supervisor. The schema's evaluation-only rule suggests those should be stripped. It is an architecture decision whether (a) action-level scenario/truth metadata is intentionally visible to the supervisor, in which case the benchmark is not a capability test, or (b) it must be moved under `label`/`meta` (or otherwise excluded) and ids made neutral. I cannot settle that from the files alone.

## Precise question

When scoring an action, must the supervisor's input exclude `action.scenario_type`, `action.truth_type` and scenario-bearing document/note/thesis ids (with all such metadata moved to `label`/`meta` or neutral ids), or is action-level visibility of the scenario type and truth type intended?

If the answer is “exclude”, the required fix is clear and I have listed it first in `REVIEW.md`. If the answer is “visible”, the benchmark's pass-bar similarity work is insufficient: the task is solvable from metadata alone and needs a redesign of the model view.
