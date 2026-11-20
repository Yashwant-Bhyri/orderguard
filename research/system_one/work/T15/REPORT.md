# T15 — One scoring sheet and one adapter for every lane

## 1. What I built

A frozen, model-neutral evaluation bench.

- **`og_s1/eval/cases.py`** — `cases(episode) -> list[Case]`. A `Case` is built
  only from `og_s1.schema.model_view_at`: the action, its claims with the
  quoted span, the available source text and source facts, the cited notes and
  their cited documents, the anchored thesis (without `status`), and causal
  trust/provenance fields. `code_features` optionally carries T03's causal
  feature row so the code baseline can consume a Case without seeing the
  episode. `LabelRecord` and `labels(episode)` attach one truth type to every
  label; `cases` never calls `labels`, and a Case never carries a label.
- **`og_s1/eval/render.py`** — the four experiment-R renderings: `raw`,
  `typed_facts`, `claim_evidence` and `why_package` (canonical JSON). Each is a
  pure function of the Case; `render_lengths` reports characters and
  whitespace tokens.
- **`og_s1/readers/base.py`** — the reader adapter:
  `score(cases, rendering) -> dict[question, list[prob or None]]` for
  `supported`, `hype`, `authority`, `addresses_reviewer`. `None` means the
  reader cannot answer; values are validated as finite probabilities in
  `[0, 1]`. Optional `cause_scores` and `pointers` hooks expose the top-cause
  and pointer metrics without forcing a four-question reader to invent a cause.
- **`og_s1/eval/metrics.py`** — one function per metric with a group bootstrap
  95% interval: coverage at a 0.05 false-allow bound (primary), AUROC, ECE,
  top-cause accuracy, pointer accuracy, false holds per 1,000, and escalation
  rate. The primary rule is a **finite-sample Clopper-Pearson upper bound with
  a Bonferroni selection correction** over a fixed 101-point grid (see 5.2);
  the earlier empirical add-one rule remains only as a labelled diagnostic.
  Abstention is fail-closed for coverage and is reported explicitly for AUROC
  and ECE, so returning `None` cannot inflate a score. Latency and GPU-seconds
  are recorded with `cost_summary`, never used as a filter.
- **`og_s1/eval/splits.py`** — group splits by whole group with
  `assert_group_disjoint`, plus `assert_episode_disjoint` for unseen-episode
  estimates; no random-row split.
- **`og_s1/eval/SPEC.md`** — the normative definition, frozen by
  `og_s1/eval/SPEC.sha256` and exposed by `og_s1.eval.spec_hash()`.
- **`work/T15/evaluate.py`** — the end-to-end bench on `data/ref/`, scoring a
  constant reader and T03's code features through a logistic reader on the
  owner, episode and company splits.
- **`work/T15/tests/test_eval.py`** — 41 tests, including hand-computed
  examples for every metric, the `None`/fail-closed policy, the conformal
  bound, the pointer size cap, the T11 question orientation, an exhaustive
  no-future-field test, the group/episode leak tests and the spec-hash test.
- **`work/T15/check_artifacts.py`** — fails the run if generated files contain
  an absolute home path, a `__pycache__` cache, or more than 5 MB; it now scans
  the whole `og_s1/readers` tree, not just `base.py`.

The frozen spec hash is
`ad9650c87f929018e4a474d133957cc6729fd4b361807f155e1be7a9d7233896`.

## 2. How to re-run (one command)

```
bash research/system_one/work/T15/run.sh
```

From `research/system_one/work/T15/`, `bash run.sh` is equivalent. The script
runs the 41 T15 tests, runs `evaluate.py` with its defaults (`data/ref/`, 40
episodes per family/shift file, 300 bootstrap draws, 150 for slices), prints
the spec hash before and after, runs the artifact check, and writes one
immutable capture to `work/T15/captures/<RUN_ID>.log`. It appends only a
one-line pointer to `work/T15/check.log`. A `mkdir` lock refuses a concurrent
run, so captures cannot interleave; the lock records the holder PID, and a
stale lock is removed only when that PID is not alive (a legacy lock with no
PID is stale by definition), so a killed run cannot wedge the folder.
`PYTHONDONTWRITEBYTECODE=1` is set and stale `__pycache__` directories are
removed before the run.

The report cites capture **`20261120T024510Z-13418`** (round 4), produced by
the final script from a clean folder. Round 4 changed only the lock recovery
and index guard in `run.sh`; it did not change the corpus, splits, metrics,
spec or any reported number, so the deterministic tables below are
byte-identical to round 3. Earlier round-4 captures
(`20261120T022846Z-8747` and `20261120T023927Z-11391`, both after clearing a
stale lock with a dead PID, and `20261120T023351Z-10185`, from a clean folder)
reproduced every deterministic line; the only differences between captures are
wall-clock timings, test durations and the artifact file count (which grows by
one as each new capture is written). The earlier captures are retained but are
**not** the source of any number below. The pre-round-2 log is archived at
`work/T15/captures/pre-round2-check.log`. Every deterministic number in this
report comes from the cited capture; latency is stored in `results.json` but
is not tabulated here because it is a single non-reproducible sample.

## 3. Results

### 3.1 Pass bar

| Check | Result |
|---|---|
| T15 tests | **41 passed** |
| Case extraction reads only `model_view_at`; a test proves no future field reaches a Case | passes: a future thesis is created, and future theses (statement/sector/evidence/invalidation text and trigger/status), documents (publisher/trust/kind/facts/text/hash), notes (writer/signature/citations/text), actions (notional/sector/instrument/side/thesis id/cited notes/claims/rationale), labels and `meta` are mutated; every Case at or before the cut is byte-identical |
| Group-split leak test | passes; a random-row split, a manual group leak and an episode-on-both-sides split all raise; the real owner/episode splits pass both group and episode disjointness |
| Every metric has a hand-computed test | passes for AUROC (including fail-closed `None`), ECE, the empirical midpoint threshold, the finite-sample conformal bound, hold-all, fixed-tau, fail-closed coverage, top-cause (including a missing prediction), pointer (including the size cap), false holds, escalation and cost |
| Spec hash printed and stable | `ad9650c8…3896` before and after the run, matches `SPEC.sha256`, and the report quotes only the cited round-4 capture; a second round-4 run printed the same hash |

### 3.2 Corpus and splits

The bench scores **640 episodes**, **76,800 actions**, **15,765 positives**
(40 episodes from each of the 16 family/shift files). This is a deterministic
40-per-file sample of the reference corpus; it is a pipeline demonstration, not
a capability claim.

| Family | Clean positives / actions | Shifted positives / actions |
|---|---:|---:|
| clean | 0 / 4,800 | 0 / 4,800 |
| drift | 1,041 / 4,800 | 706 / 4,800 |
| unsupported_claim | 1,306 / 4,800 | 1,306 / 4,800 |
| misquote | 1,308 / 4,800 | 1,308 / 4,800 |
| vague_hype | 1,293 / 4,800 | 1,293 / 4,800 |
| poisoned_note | 1,316 / 4,800 | 1,316 / 4,800 |
| authority_spoof | 1,260 / 4,800 | 1,260 / 4,800 |
| stale_thesis | 526 / 4,800 | 526 / 4,800 |

| Split axis | Groups | Train | Cal | Test | Train / cal / test cases | Episode-disjoint? |
|---|---:|---:|---:|---:|---:|---|
| owner | 320 | 192 | 64 | 64 | 46,080 / 15,360 / 15,360 | yes (0 episodes on both sides) |
| episode | 640 | 384 | 128 | 128 | 46,080 / 15,360 / 15,360 | yes (0 episodes on both sides) |
| company | 49 | 29 | 10 | 10 | 41,507 / 15,850 / 19,443 | **no (640 / 640 episodes overlap)** |
| author | 1 | — | — | — | unavailable: `data/ref` has one author | — |
| agent | 1 | — | — | — | unavailable: no `meta.agent_id`; the owner key is not relabelled as an agent split | — |

The **owner** split groups whole signing keys, so it keeps each shifted/
unshifted twin together and is also episode-disjoint. The **episode** split is
the clean unseen-episode estimate and is episode-disjoint, but it is not
owner-disjoint: a shifted twin may share its owner key with the unshifted twin
on the other side. The **company** split is group-key-disjoint but
**episode-overlapping**: every episode trades several instruments, so all 640
episodes have actions on both sides. It is a secondary transfer diagnostic and
is **not** a generalization test. Company "groups" are the action's ticker, a
judgement call recorded in 5.10.

### 3.3 Pooled metrics (all four questions, group bootstrap 95% intervals)

Both trivial readers return one shared risk for all four questions, so the four
questions are identical; the table shows `supported`. "tau" is the calibration
threshold: `hold_all` means the constant reader's threshold is `-inf` (hold
every action), stored as `hold_all=true` in `results.json`, never as `nan`. The
0.05 bound is the Clopper-Pearson/Bonferroni rule of 5.2 and SPEC 7.1. The
`cal_upper` quoted under each table is the bound at the selected `tau`; the
"test realized" share is descriptive and is not the guaranteed quantity. The
reader abstained on no clean test case on any split (`abstained_clean_test=0`),
so the fail-closed policy does not move these rows.

**Owner split (headline, episode-disjoint):**

| Reader | n test | n pos | n clean | Coverage | tau | AUROC | ECE | Top cause | Pointer | False holds / 1,000 | Escalation |
|---|---:|---:|---:|---|---|---|---|---|---|---|
| constant 0.5 | 15,360 | 3,153 | 12,207 | 0.0000 [0.0000, 0.0000] | hold_all | 0.5000 [0.5000, 0.5000] | 0.2947 [0.2675, 0.3238] | n/a | n/a | 794.7266 [767.4740, 823.8037] | 1.0000 [1.0000, 1.0000] |
| code features + logistic | 15,360 | 3,153 | 12,207 | 1.0000 [1.0000, 1.0000] | 0.990000 | 0.9963 [0.9929, 0.9985] | 0.0042 [0.0024, 0.0111] | 0.0051 [0.0014, 0.0103] | 0.7735 [0.6361, 0.8935] | 0.0000 [0.0000, 0.0000] | 0.0001 [0.0000, 0.0004] |

Owner, code reader: conformal calibration bound **0.0268** (12,556 allowed,
278 bad); test realized **0.0168** (12,207 clean and 208 bad allowed). Top
cause **15 / 2,945** held positives; pointer **1,434 / 1,854** held positives
with cause refs.

**Episode split (unseen-episode estimate; not owner-disjoint):**

| Reader | n test | n pos | n clean | Coverage | tau | AUROC | ECE | Top cause | Pointer | False holds / 1,000 | Escalation |
|---|---:|---:|---:|---|---|---|---|---|---|---|
| constant 0.5 | 15,360 | 3,237 | 12,123 | 0.0000 [0.0000, 0.0000] | hold_all | 0.5000 [0.5000, 0.5000] | 0.2893 [0.2724, 0.3065] | n/a | n/a | 789.2578 [772.3958, 806.5137] | 1.0000 [1.0000, 1.0000] |
| code features + logistic | 15,360 | 3,237 | 12,123 | 1.0000 [1.0000, 1.0000] | 0.990000 | 0.9954 [0.9924, 0.9976] | 0.0030 [0.0016, 0.0086] | 0.0047 [0.0014, 0.0081] | 0.6799 [0.5436, 0.8081] | 0.0000 [0.0000, 0.0000] | 0.0003 [0.0001, 0.0007] |

Episode, code reader: conformal calibration bound **0.0242** (12,593 allowed,
249 bad); test realized **0.0230** (12,123 clean and 285 bad allowed). Top
cause **14 / 2,952**; pointer **1,219 / 1,793**.

**Company split (company-held-out, episode-overlapping; not a generalization test):**

| Reader | n test | n pos | n clean | Coverage | tau | AUROC | ECE | Top cause | Pointer | False holds / 1,000 | Escalation |
|---|---:|---:|---:|---|---|---|---|---|---|---|
| constant 0.5 | 19,443 | 3,920 | 15,523 | 0.0000 [0.0000, 0.0000] | hold_all | 0.5000 [0.5000, 0.5000] | 0.2984 [0.2848, 0.3109] | n/a | n/a | 798.3850 [784.8270, 810.8887] | 1.0000 [1.0000, 1.0000] |
| code features + logistic | 19,443 | 3,920 | 15,523 | 1.0000 [1.0000, 1.0000] | 0.990000 | 0.9944 [0.9919, 0.9964] | 0.0022 [0.0013, 0.0085] | 0.0084 [0.0058, 0.0115] | 0.6746 [0.6315, 0.7186] | 0.0000 [0.0000, 0.0000] | 0.0003 [0.0000, 0.0005] |

Company, code reader: conformal calibration bound **0.0236** (12,986 allowed,
251 bad); test realized **0.0216** (15,523 clean and 343 bad allowed). This
split is not an unseen-episode result. Top cause **30 / 3,577**; pointer
**1,476 / 2,188**.

### 3.4 Per truth type (code reader, `supported`)

Every slice is evaluated at the **pooled** `tau` of its split, so rows share
one operating point and are comparable to 3.3. The tau column repeats that
shared value. The `preference` slice has no positive labels: `clean` is a
synthetic endorsement, not real owner preference, so it is never used as a
preference positive. The cited capture prints the ECE and false-hold intervals
for every slice; escalation's interval, which the row format omits, is in
`results.json`. The table below carries coverage and AUROC intervals.

| Split | Truth type | n test | n pos | n clean | Coverage | AUROC | ECE | Top cause | Pointer | False holds / 1,000 | Escalation | tau |
|---|---|---:|---:|---:|---|---|---|---|---|---|---:|---:|
| owner | formal | 13,112 | 905 | 12,207 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 0.0168 | 0.0077 | 0.0000 | 0.0000 | 0.0000 | 0.990000 |
| owner | evidential | 14,455 | 2,248 | 12,207 | 1.0000 [1.0000, 1.0000] | 0.9948 [0.9899, 0.9978] | 0.0044 | 0.0039 | 1.0000 | 0.0000 | 0.0001 | 0.990000 |
| owner | preference | 12,207 | 0 | 12,207 | 1.0000 [1.0000, 1.0000] | n/a | 0.0180 | n/a | n/a | 0.0000 | 0.0000 | 0.990000 |
| episode | formal | 13,130 | 1,007 | 12,123 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 0.0158 | 0.0020 | 0.0000 | 0.0000 | 0.0000 | 0.990000 |
| episode | evidential | 14,353 | 2,230 | 12,123 | 1.0000 [1.0000, 1.0000] | 0.9933 [0.9880, 0.9963] | 0.0031 | 0.0061 | 1.0000 | 0.0000 | 0.0003 | 0.990000 |
| episode | preference | 12,123 | 0 | 12,123 | 1.0000 [1.0000, 1.0000] | n/a | 0.0170 | n/a | n/a | 0.0000 | 0.0000 | 0.990000 |
| company | formal | 16,711 | 1,188 | 15,523 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 0.0160 | 0.0068 | 0.0000 | 0.0000 | 0.0001 | 0.990000 |
| company | evidential | 18,255 | 2,732 | 15,523 | 1.0000 [1.0000, 1.0000] | 0.9919 [0.9882, 0.9948] | 0.0023 | 0.0092 | 1.0000 | 0.0000 | 0.0002 | 0.990000 |
| company | preference | 15,523 | 0 | 15,523 | 1.0000 [1.0000, 1.0000] | n/a | 0.0172 | n/a | n/a | 0.0000 | 0.0000 | 0.990000 |

For comparison, evaluating each slice at its own re-selected threshold changes
the operating point. The variant is stored under `per_truth_type_self_tau` in
`results.json`; the reported table above is the pooled-tau variant. With the
conformal rule the self-selected point is also 0.99 for both positive truth
types and 1.00 for the zero-positive preference slice, so the two variants do
not differ materially here:

| Split | Truth type | self tau | Coverage (self tau) | False holds (self tau) | Escalation (self tau) |
|---|---|---:|---|---:|---:|
| owner | formal | 0.990000 | 1.0000 | 0.0000 | 0.0000 |
| owner | evidential | 0.990000 | 1.0000 | 0.0000 | 0.0001 |
| owner | preference | 1.000000 | 1.0000 | 0.0000 | 0.0000 |
| episode | formal | 0.990000 | 1.0000 | 0.0000 | 0.0000 |
| episode | evidential | 0.990000 | 1.0000 | 0.0000 | 0.0003 |
| episode | preference | 1.000000 | 1.0000 | 0.0000 | 0.0000 |
| company | formal | 0.990000 | 1.0000 | 0.0000 | 0.0001 |
| company | evidential | 0.990000 | 1.0000 | 0.0000 | 0.0002 |
| company | preference | 1.000000 | 1.0000 | 0.0000 | 0.0000 |

Those rows are not comparable across slices (each has its own threshold), which
is why they are not the headline slice table.

### 3.5 Per shift axis (code reader, `supported`, fixed pooled tau)

Each axis slice uses positives tagged with that axis plus all clean actions;
slices overlap and are descriptive. Positives with a given axis can appear in
several rows, so rows are not disjoint.

| Split | Axis | n pos | Coverage | AUROC | ECE | Top cause | Pointer | False holds / 1,000 | Escalation | tau |
|---|---|---:|---|---|---|---|---|---|---:|---:|
| owner | semantic | 2,243 | 1.0000 [1.0000, 1.0000] | 0.9965 [0.9934, 0.9986] | 0.0092 | 0.0066 | 0.8404 | 0.0000 | 0.0001 | 0.990000 |
| owner | financial | 558 | 1.0000 [1.0000, 1.0000] | 0.9926 [0.9854, 0.9984] | 0.0157 | 0.0157 | 1.0000 | 0.0000 | 0.0002 | 0.990000 |
| owner | temporal | 158 | 1.0000 [1.0000, 1.0000] | 0.9524 [0.9239, 0.9744] | 0.0067 | n/a | n/a | 0.0000 | 0.0000 | 0.990000 |
| owner | behavioural | 485 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 0.0173 | 0.0144 | n/a | 0.0000 | 0.0000 | 0.990000 |
| owner | adversarial | 1,440 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 0.0161 | 0.0000 | 0.6097 | 0.0000 | 0.0000 | 0.990000 |
| episode | semantic | 2,459 | 1.0000 [1.0000, 1.0000] | 0.9967 [0.9932, 0.9985] | 0.0079 | 0.0052 | 0.7851 | 0.0000 | 0.0003 | 0.990000 |
| episode | financial | 547 | 1.0000 [1.0000, 1.0000] | 0.9950 [0.9916, 0.9973] | 0.0154 | 0.0241 | 1.0000 | 0.0000 | 0.0004 | 0.990000 |
| episode | temporal | 229 | 1.0000 [1.0000, 1.0000] | 0.9465 [0.9302, 0.9636] | 0.0039 | n/a | n/a | 0.0000 | 0.0000 | 0.990000 |
| episode | behavioural | 433 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 0.0165 | 0.0047 | n/a | 0.0000 | 0.0000 | 0.990000 |
| episode | adversarial | 1,519 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 0.0151 | 0.0000 | 0.4416 | 0.0000 | 0.0000 | 0.990000 |
| company | semantic | 2,902 | 1.0000 [1.0000, 1.0000] | 0.9955 [0.9938, 0.9969] | 0.0066 | 0.0103 | 0.7761 | 0.0000 | 0.0003 | 0.990000 |
| company | financial | 684 | 1.0000 [1.0000, 1.0000] | 0.9943 [0.9908, 0.9986] | 0.0154 | 0.0345 | 1.0000 | 0.0000 | 0.0002 | 0.990000 |
| company | temporal | 292 | 1.0000 [1.0000, 1.0000] | 0.9378 [0.9290, 0.9539] | 0.0016 | n/a | n/a | 0.0000 | 0.0000 | 0.990000 |
| company | behavioural | 476 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 0.0167 | 0.0169 | n/a | 0.0000 | 0.0000 | 0.990000 |
| company | adversarial | 1,838 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 0.0154 | 0.0000 | 0.4047 | 0.0000 | 0.0000 | 0.990000 |

Each axis has 12,207 owner / 12,123 episode / 15,523 company clean negatives.
The n/a entries mean the fixed operating point held no held positive with cause
refs, so the pointer metric has no denominator; top-cause n/a instead means the
slice held no positive at all (it does not use cause refs). Both are properties
of the trivial reader's very confident score, not missing metric functions.

### 3.6 Rendering lengths (all 76,800 cases)

| Rendering | chars mean | chars p50 | chars p95 | chars p99 | chars max | tokens mean | tokens p50 | tokens p95 | tokens p99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| raw | 1,188.0767 | 1,174 | 1,492 | 1,650 | 2,077 | 162.8798 | 162 | 208 | 232 |
| typed_facts | 1,122.7203 | 1,105 | 1,352 | 1,454 | 1,592 | 65.6085 | 64 | 82 | 86 |
| claim_evidence | 938.4382 | 935 | 1,297 | 1,513.01 | 2,009 | 124.9725 | 124 | 171 | 200 |
| why_package | 1,966.2688 | 1,954 | 2,332 | 2,588 | 2,820 | 57.7221 | 57 | 70 | 77 |

The package is the longest by characters but the shortest by whitespace
tokens because it is compact JSON; raw text is the longest by tokens.

### 3.7 Latency (recorded, not tabulated)

Latency and GPU-seconds are recorded per reader in `results.json` for the cited
capture (`cost` under each split). They are deliberately **not** tabulated here:
they are single-run wall-clock samples that move with machine load and do not
reproduce, so no lane should be filtered on them. GPU-seconds are zero because
both readers are CPU-only. The previous round quoted a table from a different
capture; that provenance error is fixed by not quoting a moving number.

## 4. What did not work

- **The conformal bound is conservative, and the easy reference world
  saturates coverage at 1.0000.** The selected `tau` is 0.99 on all three
  splits; the calibration bounds are **0.0268** (owner), **0.0242** (episode)
  and **0.0236** (company), and the descriptive test realized shares are
  **0.0168**, **0.0230** and **0.0216**. Those realized shares are well under
  0.05, so the primary metric does not separate the two readers beyond the
  constant reader's zero. The earlier empirical add-one rule *did* miss 0.05 on
  the episode (0.0574) and company (0.0553) splits, which is why it is now only
  a labelled diagnostic, not the primary rule.
- **Top-cause accuracy is very weak.** The code reader's cause adapter is a
  plain per-feature-group maximum, not a cause model. It scores **0.0051**
  (15 / 2,945) on owner, **0.0047** (14 / 2,952) on episode and **0.0084**
  (30 / 3,577) on company. The metric function is tested and correct; the
  adapter is the limitation. Do not use these numbers as a cause claim.
- **The constant reader is deliberately useless.** It holds every action
  (`hold_all`, coverage 0), escalates everything (1.0), has AUROC 0.5 and ECE
  about 0.29. It is a plumbing check, not a baseline to beat.
- **All four questions share one risk.** The code baseline returns the same
  action risk for every question. The pipeline exercises all four keys, but
  these numbers say nothing about per-question reader quality.
- **The author and agent splits are unavailable on `data/ref`.** The reference
  corpus has one author (`reference`) and no `meta.agent_id`. The splitter is
  tested on synthetic multi-group data, but no real multi-author or multi-agent
  reference table exists. The agent axis is explicitly unavailable rather than
  silently using the owner key (round-2 fix).
- **Adaptive evasion is not implemented.** `COMBOS.md` section 4 asks for
  20-attempt adaptive evasion; the T15 brief's metric list does not, and a weak
  attacker built here would be an overclaim. It is left to T06/T07.
- **The full reference corpus was not run.** The default is 40 episodes per
  file (640 episodes, 76,800 actions), not the whole file. This is a pipeline
  demonstration, not a capability result. Raising `--limit` runs the full
  reference files with the same code.
- **The four renderings were not scored by a text reader.** They are built,
  deterministic, length-measured and unit-tested, but both trivial readers
  ignore text. Experiment R has no quality conclusion here.
- **Some per-axis/truth slices have n/a ranking metrics.** Top-cause is n/a
  when the fixed operating point held no positive at all (it does not use cause
  refs); pointer is n/a when there was no held positive with true cause refs.
  Coverage, ECE, false holds and escalation are still reported.
- **The logistic fit is dependency-sensitive.** It uses scikit-learn 1.9.1's
  `LogisticRegression`; a different solver version could move the probabilities
  slightly. The Case/renderings/metrics are dependency-free.
- **The company split cannot be both company-disjoint and episode-disjoint on
  this corpus.** Every episode trades several instruments, so keeping whole
  episodes together would put every company on both sides. The honest fix is
  the episode split plus the relabelled company table, not a false claim.

## 5. Judgement calls

### 5.1 Case as the single model-neutral input

- **Choice:** one causal `Case` built only from `model_view_at`, carrying the
  action, claims, quoted spans, source text/facts, cited notes, thesis and
  trust/provenance.
- **Alternatives:** (a) pass the whole-episode `model_view` with a step mask;
  (b) pass only raw text; (c) pass only T03's feature row.
- **Why it wins:** it is the same object for code, encoders, probes, decision
  models and judges; every field is causal and testable; it can be rendered
  four ways without re-reading the episode; it has no label, `meta`, final
  status or future field.
- **What evidence would flip it:** if a reader needs long history or the full
  book, add explicit causal history/book snapshots to the Case; do not pass the
  full episode, which would reintroduce the future.

### 5.2 Coverage: conditional precision with a finite-sample conformal-style bound

- **Choice:** for each fixed threshold on a 101-point grid, compute the exact
  one-sided Clopper-Pearson upper bound on the calibration conditional
  false-allow proportion `B/A` at confidence `1 - 0.05/101`; choose the largest
  grid threshold whose bound is at most 0.05. The Bonferroni union bound over
  the 101 fixed candidates gives at least 95% simultaneous coverage on
  calibration, and under the standard exchangeability assumption for labels it
  transfers to test. This is the primary metric.
- **Alternatives:** (a) the earlier empirical add-one rule
  `(B + 1) / (A + 1)`, kept only as a diagnostic; (b) unconditional conformal
  risk control on the bad-allowed indicator, which controls `P(bad and
  allowed)` rather than the conditional share COMBOS asks for; (c) a fixed
  hold-rate recall number; (d) a proper CRC quantile with a search correction.
- **Why it wins:** `COMBOS.md` says "at most 5% of allowed actions being ones
  the owner would reject", which is the conditional precision, not
  `P(allow | bad)`. Clopper-Pearson is exact for the binomial proportion and
  the selection correction is auditable; the fixed grid makes the searched
  candidate set data-independent. The cost is conservatism (the bound is
  0.0268/0.0242/0.0236, below 0.05) and lower coverage headroom on a harder
  world.
- **What evidence would flip it:** if the calibration split is too small for
  any grid threshold to be feasible (hold-all), or if a lane needs tighter
  coverage, use a larger calibration split or a sequential/anytime-valid
  bound; if the lead rules that an empirical rule is acceptable, the
  diagnostic is already computed. The earlier empirical overshoots (0.0574 and
  0.0553) are why the empirical rule is no longer primary.

### 5.3 Group bootstrap

- **Choice:** resample whole groups (owner, episode or company) with
  replacement, with a fixed seed.
- **Alternatives:** (a) i.i.d. row bootstrap; (b) episode-cluster bootstrap only;
  (c) an analytic DeLong interval for AUROC.
- **Why it wins:** actions from one episode are correlated; row bootstrap
  pretends they are independent and narrows intervals. Group resampling is
  conservative and matches the split unit.
- **What evidence would flip it:** if groups are tiny and numerous, a
  cluster-robust analytic interval may be tighter; if only AUROC is needed,
  DeLong is a cheaper alternative.

### 5.4 Truth types from the cause

- **Choice:** a fixed cause-to-truth-type map; `clean` is `preference` but is
  marked synthetic and is never a preference positive.
- **Alternatives:** (a) per-label human annotation; (b) question-level truth
  types (`supported` evidential, `authority` formal, etc.); (c) map `clean` to
  `formal`.
- **Why it wins:** the schema has no `truth_type` field, so any mapping is a
  judgement; the cause map is transparent, deterministic and testable. Mapping
  `clean` to `preference` is semantically right (endorsement is a preference),
  and the zero-positive preference table makes the synthetic limitation
  visible.
- **What evidence would flip it:** if authored worlds add a real `truth_type`
  field, use it; if real owner preference labels arrive, evaluate preference
  separately and do not pool `clean` into it.

### 5.5 Splits: owner headline, episode unseen-episode, company secondary

- **Choice:** headline on owner groups; an unseen-episode table on episode
  groups; a secondary, explicitly episode-overlapping table on company groups;
  author and agent unavailable when the corpus cannot support them.
- **Alternatives:** (a) random rows; (b) only an owner split; (c) four full runs
  with synthetic author/agent ids; (d) a connected-component split that keeps
  both companies and episodes disjoint.
- **Why it wins:** owner is the strongest delegation boundary and keeps each
  shifted/unshifted twin together; the episode split answers the
  unseen-episode question without inventing keys; company is a transfer
  diagnostic but cannot keep episodes together on this corpus; inventing author
  or agent ids would be fake; the connected-component split would merge nearly
  every episode through shared tickers and leave too few test components.
- **What evidence would flip it:** if T02 worlds carry several authors or agent
  ids, run those axes; if a company split must not split an episode, use a
  connected-component split or an episode split and drop the company claim.

### 5.6 The two trivial readers

- **Choice:** a constant 0.5 and T03's 41 causal features through one logistic
  risk model; the latter answers every question with the same risk.
- **Alternatives:** (a) four per-question heads trained on cause-derived
  question labels; (b) a zero-shot decision model; (c) the T05 text reader.
- **Why it wins:** T15 is a plumbing task, not a reader race. One shared risk
  proves the Case/renderings/None/metrics path with no synthetic question-label
  invention. The alternative would create labels the owners never gave.
- **What evidence would flip it:** when T05/T11 readers exist, substitute them
  through the same adapter; do not compare per-question quality using this
  baseline.

### 5.7 Shift axes from `meta`

- **Choice:** derive axes from `meta.family` and `meta.shifted`, attach them to
  Cases for reporting only, and strip them before a reader is called.
- **Alternatives:** (a) infer axes from Case content; (b) no axis tags; (c) ask
  each author to declare axes in the world.
- **Why it wins:** the reference metadata is the only source that names the
  planted family and the shift; it is evaluation-only; the Cases are tagged,
  the readers never see the tags, and the per-axis tables are descriptive.
- **What evidence would flip it:** if T02/held-out worlds do not carry the same
  metadata, require the authors to declare axes or use a documented
  content-based tagger; do not infer from labels at scoring time.

### 5.8 The spec hash

- **Choice:** SHA-256 of the normative `SPEC.md`, stored in `SPEC.sha256`,
  printed before and after every run.
- **Alternatives:** (a) a version string only; (b) a signed manifest of code
  and spec; (c) no freeze.
- **Why it wins:** it is portable, testable, and forces every lane to quote the
  same definitions. It is cheap and does not depend on a signing key.
- **What evidence would flip it:** if the code and spec can drift independently,
  extend the manifest to a hash of the evaluation package; the current hash
  deliberately covers only the normative text.

### 5.9 The 40-per-file sample

- **Choice:** score the first 40 episodes of each family/shift file.
- **Alternatives:** (a) every episode in each file; (b) a random sample; (c) only
  the clean file.
- **Why it wins:** 76,800 actions is enough to exercise every metric and the
  group splits while keeping the pipeline round to minutes on this machine.
  The sample is deterministic and declared in the report.
- **What evidence would flip it:** if a lane comparison needs the full
  reference corpus, raise `--limit` to the file length; the code and spec do
  not change.

### 5.10 "Company" equals the action's ticker

- **Choice:** group by `step.action.instrument`, i.e. the ticker.
- **Alternatives:** (a) group by the issuer entity parsed from documents;
  (b) group by sector; (c) a manual company-to-ticker map.
- **Why it wins:** the action carries exactly one structured entity field and it
  is the ticker; parsing issuer names from prose is error-prone and would make
  the split depend on a text model; sector is too coarse (7 groups) and is not a
  company. The key is deterministic and auditable.
- **What evidence would flip it:** if the schema adds an issuer id, group by
  that; if one issuer trades under several tickers, merge them before splitting.

### 5.11 Split fractions 0.6 / 0.2 / 0.2

- **Choice:** 60% train, 20% calibration, 20% test by whole group.
- **Alternatives:** (a) 80/10/10; (b) 70/15/15; (c) cross-fitting with several
  folds.
- **Why it wins:** the calibration split must be large enough for a 0.05
  add-one rule (a handful of bad cases moves the statistic), and the test split
  must have enough groups for a percentile interval; 60/20/20 balances those
  needs with a training set big enough for a 41-feature logistic fit. The
  fractions are fixed in the SPEC so lanes share them.
- **What evidence would flip it:** if calibration widens to a formal bound, it
  needs more data; if groups are few, a larger calibration share is preferable
  and must be fixed in the SPEC for all lanes.

### 5.12 Escalation band 0.4 <= risk <= 0.6

- **Choice:** escalate when the oriented risk is within 0.4 of 0.6.
- **Alternatives:** (a) a calibrated abstention threshold chosen on
  calibration; (b) a fixed top-k escalate rule; (c) a decision-model judge.
- **Why it wins:** it is fixed before results, needs no extra label, is
  symmetric around the decision boundary and is trivially auditable. A
  calibration-selected band would be another data-dependent threshold and
  would make escalation a second tuned operating point.
- **What evidence would flip it:** if escalation cost is measured, choose the
  band by expected cost on calibration and freeze it in the SPEC; if a judge
  catches failures outside the band, add it as a separate signal.

### 5.13 ECE with 10 equal-width bins

- **Choice:** 10 equal-width bins on [0, 1], empty bins skipped.
- **Alternatives:** (a) 15 or 20 bins; (b) equal-frequency bins; (c)
  Brier/reliability diagrams only.
- **Why it wins:** 10 is the common reliability-diagram resolution, keeps at
  least a few hundred cases per occupied bin at this test size, and is fixed in
  the SPEC so lanes share it. Equal-frequency bins adapt to the score
  distribution but make the bin edges lane-dependent and harder to audit.
- **What evidence would flip it:** if score mass concentrates in one region, a
  fixed 10-bin ECE can hide miscalibration; then add equal-frequency ECE and
  report both, keeping the headline fixed for comparability.

### 5.14 Bootstrap draw counts 300 / 150

- **Choice:** 300 group draws for pooled metrics, 150 for slices.
- **Alternatives:** (a) 1,000+ draws; (b) 100 draws; (c) analytic intervals.
- **Why it wins:** the intervals are percentile summaries of a deterministic
  seed; 300 resolves the 2.5/97.5 percentiles without dominating the run, and
  150 keeps 8 slices per split tractable. The wall time is machine-load
  dependent (about 9-10 minutes on this Mac in round 3), so no fixed minute
  count is claimed. More draws would tighten
  Monte-Carlo noise but cannot fix the small number of test groups on the
  company split.
- **What evidence would flip it:** if a lane compares intervals at the third
  decimal, raise to 1,000 and record the runtime; if the group count is tiny,
  draw counts are not the binding problem and more data is.

## 6. Loopholes I checked

- **Future documents, notes, actions and theses.** An exhaustive test creates a
  future thesis and mutates future thesis statement/sector/evidence/
  invalidation/trigger/status, future document publisher/trust tier/kind/facts/
  text/hash, future note writer/signature/citations/text (including the cut
  step's own `new_notes`), and future action notional/sector/instrument/side/
  thesis id/cited notes/claims/rationale; every earlier Case is byte-identical
  and contains no `FUTURE` marker. Tested.
- **Labels and `meta`.** Changing every label (`y`, `cause`, refs) and the
  entire `meta` dict (including a new `agent_id`) leaves every Case unchanged;
  a Case has no `label`, `meta` or `status` key. Tested.
- **No whole-episode `model_view`.** The cases module has no `model_view`
  global, and its source contains no `model_view(` call once `model_view_at(`
  is removed. Tested.
- **Episode key.** It is built from the owner, the first action and the initial
  book; appending a future step or mutating future fields does not change it.
  Tested.
- **Group leakage.** A random-row split, a manual one-group-on-both-sides
  split, and a company-style split that puts two episodes on both sides all
  raise. The owner and episode splits pass both group and episode
  disjointness. Tested.
- **Metric arithmetic.** AUROC 0.75 and fail-closed AUROC 0.5 with an
  abstention, ECE 0.4 (and 0), the empirical midpoint threshold (0.595 with
  upper 1/21), the finite-sample conformal bound (tau 0.29 with `B=0`,
  `A=205`), fixed-tau coverage, hold-all, top-cause 0.5 with a missing
  prediction counted as a miss, pointer 2/3 and an oversized set counted as a
  miss, false holds 250/1,000, escalation 0.25, and a hand-computed cost
  summary. Tested.
- **Abstention is not a free denominator.** Coverage keeps `None` clean test
  cases in the denominator as not allowed (1/3 in the hand-computed case);
  AUROC ranks `None` above every answered risk and reports the answered-subset
  value and the abstention rate; ECE assigns `None` the maximal risk; a missing
  cause or pointer prediction counts as a miss. Tested.
- **Pointer flooding.** A predicted pointer set larger than
  `max(1, len(true_refs)) + 2` is a miss even if it contains the deciding ref.
  Tested.
- **Unit wildcard.** A unitless claim matches only a unitless fact; it is not a
  wildcard for a fact in any unit. Tested.
- **Question orientation.** T11's wording is quoted in SPEC 5 and pinned by a
  test: `supported` is `1 - p`; `hype`, `authority` and `addresses_reviewer`
  are all bad-property questions with risk `p`, so a lane returning the natural
  P(yes) is oriented correctly.
- **Threshold search.** The conformal rule searches a fixed 101-point grid and
  pays a Bonferroni penalty of `0.05/101`; it does not pick a favourable
  observed score after seeing labels. The empirical midpoint rule is retained
  only as a diagnostic.
- **Hold-all is explicit.** `tau = -inf` is printed as `hold_all`, stored as
  `hold_all=true`, and tested; it is never `nan` or a missing value. Tested.
- **Slice comparability.** Every slice is evaluated at the pooled `tau`; the
  self-selected variant is stored separately, and the shared `tau` is printed
  in every slice row. Tested for the fixed-tau path.
- **Bootstrap determinism.** The same seed gives the same interval; the
  interval brackets the mean in the test case.
- **Spec freeze.** `spec_hash()` is stable across calls and matches the
  committed `SPEC.sha256`; `run.sh` prints the same value before and after.
- **Isolation.** Only `data/ref/`, `og_s1/` and the T01/T03 reports were read.
  No `work/T02*`, `work/T06` or `data/heldout*` was opened, and no git command
  was run. The deliverables mention held-out paths only in explicit
  out-of-scope statements.
- **Secrets and paths.** No key, token, password or absolute home path is
  written. `check_artifacts.py` scans the task folder, all of `og_s1/eval` and
  all of `og_s1/readers` for absolute home paths, `__pycache__` directories and
  files over 5 MB, reports counts only (never the matched path), and fails the
  run on a hit; it reports 0 hits and 0 oversized files in the cited capture.
  `run.sh` disables bytecode and removes stale `__pycache__` directories, and a
  unit test asserts the scan roots cover the whole readers package.
- **Disk.** The task folder is small; the capture is about 24 KB and
  `results.json` about 190 KB. No data is copied.
- **Reproducibility of the capture.** Each run writes its own immutable
  capture file and appends only a pointer to `check.log`, under a `mkdir` lock,
  so a rerun cannot destroy or interleave the cited capture. The lock holds the
  holder PID; a leftover lock from a SIGKILLed run is cleared when that PID is
  dead (and always when it is a legacy lock with no PID), so the entry point
  stays reproducible after an interrupted run.
- **Session/split leakage.** The company split is labelled as
  episode-overlapping everywhere, and the episode overlap count (640/640) is
  printed and stored; the unseen-episode claim is made only on the episode
  split.

## 7. Open risks

- **The numbers are a pipeline demonstration, not a capability result.** The
  code reader is trivial and the constant reader is deliberately useless; do
  not compare lanes on these values.
- **The reference world is too easy.** AUROC near 0.99 on reference data says
  little about unseen wording. T07's held-out worlds are the real test.
- **The conformal bound is a calibration bound, not a test-set oracle.** It is
  a `1 - delta` finite-sample bound on the calibration conditional
  false-allow proportion after a Bonferroni correction for the 101-point
  search; transfer to test relies on the usual exchangeability assumption. The
  observed test shares (1.68%, 2.30%, 2.16%) are under 0.05 here, but a future
  distribution shift could still overshoot. More calibration data or a
  sequential/anytime-valid bound would tighten it.
- **The episode split is not owner-disjoint.** A shifted twin may share an
  owner key with its unshifted twin on the other side, so the episode table is
  an unseen-episode estimate, not an unseen-owner estimate. The owner table is
  the stronger delegation boundary.
- **The company split is not a generalization test.** All 640 episodes have
  actions on both sides. Its AUROC is a within-episode transfer number and
  should not be quoted as unseen-world performance.
- **Top-cause and pointer metrics are only as good as the optional hooks.** The
  code reader's cause adapter is weak, and a reader that returns `None` makes
  those metrics n/a. T11/T07 must supply real cause and pointer heads.
- **The author and agent axes are untested on real reference data.** The
  splitter works on synthetic multi-group data, but `data/ref` has one author
  and no agent id, so no real table exists. An earlier owner-proxy result is
  deliberately gone.
- **Shift-axis tags come from `meta`.** If independent authors omit `family` or
  use different names, the axes degrade to `semantic`/none; per-axis tables
  would then under-report.
- **Rendering length is whitespace-token length.** A model tokeniser will
  differ, especially for JSON and numbers; treat the token counts as a
  consistent relative measure, not a context-window guarantee.
- **Dependency drift.** The logistic baseline depends on scikit-learn's solver;
  the metrics, Cases and renderings are dependency-free. The spec hash covers
  the normative text, not installed versions.
- **Latency is a single sample.** The appendix numbers move with machine load
  and do not reproduce across runs; the p99 in particular is unstable. Do not
  quote them as an end-to-end system latency.
- **No adaptive-evasion number.** `COMBOS.md` asks for it; T15 does not
  implement it. T06/T07 must add it or the lane comparison remains incomplete
  on the evasion axis.
- **Small test-group counts for some CIs.** The company split has 10 test
  groups, so its percentile intervals are fragile even with 300 draws; the
  owner and episode splits have 64 and 128 test groups.

## Round 2 changes

Fixed, in the reviewer's order of importance:

1. **Company split overclaim.** Added a separate **episode** split (whole
   episodes, episode-disjoint) as the unseen-episode estimate, relabelled the
   company split as "company-held-out, episode-overlapping; NOT a
   generalization test" in the code, SPEC, capture and report, and added
   `assert_episode_disjoint`. The run now prints and stores that all 640/640
   episodes overlap on the company split and 0 on owner/episode. Tests cover
   the episode-leak case where company keys are disjoint.
2. **"Conformal" removed where it was not a guarantee.** Renamed the threshold
   function to `select_calibration_threshold` (old name kept as an alias),
   rewrote SPEC 7.1 and every report table to "empirical add-one calibration
   bound, no finite-sample test guarantee", and reported the two observed test
   overshoots as results.
3. **No-future-field test made exhaustive.** Added
   `test_no_future_field_of_any_kind_reaches_case`, covering a new future
   thesis, future thesis content, future document publisher/trust/kind/facts/
   text/hash, future note writer/signature/citations/text, and future action
   notional/sector/instrument/side/thesis id/cited notes/claims/rationale;
   asserts byte-identical earlier Cases.
4. **Slice thresholds.** Slices now run at the **pooled** `tau`, the shared
   value is printed and reported in every slice row, and the self-selected
   variant is stored under `*_self_tau`. The report states the change and shows
   the difference.
5. **Latency honesty.** Moved the exact table to an appendix labelled "one
   example sample, not a result", added a group CI on the mean, and removed the
   unsupported "stable at this size" claim.
6. **Absolute paths in generated files.** `run.sh` sets
   `PYTHONDONTWRITEBYTECODE=1`, removes stale `__pycache__` directories, and
   runs `check_artifacts.py`; the cited capture reports 0 absolute-home-path
   hits and 0 oversized files. The report no longer claims paths are absent
   without a check.
7. **Hold-all display.** `-inf` now prints as `hold_all` and is stored as
   `hold_all=true`; the constant reader's row is labelled hold-all. Added
   hand-computed tests.
8. **Agent split.** The agent axis is now **unavailable** when no
   `meta.agent_id` exists; the owner key is never printed as an agent split.
   The corpus prints `agent_id_present: False`.
9. **Missing judgement calls.** Added 5.10 company key, 5.11 split fractions,
   5.12 escalation band, 5.13 ECE bins and 5.14 bootstrap draw counts, each
   with at least one alternative from a different paradigm, why the choice wins
   and what would flip it.
10. **Safe logging.** Replaced `tee -a` with per-run capture files and a
    one-line pointer under a `mkdir` lock; the pre-round-2 interleaved log is
    archived and not cited.
11. **Minor corrections.** The report names its capture, does not call it
    "current", and does not state a capture count or a stability claim. The
    spec hash and the test count are re-read from the new capture.

Not changed, with reasons:

- **The 40-per-file sample stays.** The brief permits `data/ref` and the review
  treated the sample as disclosed, not a pass-bar failure. The full 200
  episodes per file would multiply runtime and memory on a 13 GB Mac; `--limit`
  still runs it with the same code.
- **The company axis stays as an action's ticker.** It is still a useful
  transfer diagnostic once labelled honestly; changing the key would need an
  issuer id the schema does not carry.
- **The trivial readers stay trivial.** T15 is plumbing; a real per-question
  head would invent labels the owners never gave and is T11's job.
- **The threshold is still selected on calibration, not replaced by
  Clopper-Pearson.** The reviewer allowed relabelling; implementing an exact
  bound with a search correction is a metric-design change better made by the
  lead, and the current report states the limitation precisely.
- **The spec hash still covers only `SPEC.md`.** A code-and-spec manifest is a
  larger freeze change; the existing judgement call records the limit.
- **Latency is still measured and stored.** The brief asks for it to be
  recorded, never used as a filter; it now appears only in the appendix.

## Round 3 changes

Fixed, in the reviewer's order of importance:

1. **Fail-closed abstention is now the policy for every metric.** Coverage keeps
   a `None` clean test case in the denominator and counts it as not allowed
   (`n_abstained_clean_test`, `abstention_rate_clean_test` are reported).
   AUROC ranks `None` above every answered risk and also reports the
   answered-subset value; ECE assigns `None` the maximal risk 1.0.
   `SPEC.md` 7.1 and 7.2 state the policy, and new hand-computed tests cover
   the reviewer's concrete `[0.1, nan, nan, 0.5]` case (coverage 1/3) and
   fail-closed AUROC.
2. **The threshold candidate set is fixed.** The empirical add-one diagnostic
   now searches midpoints between adjacent distinct calibration scores (plus
   the maximum), so it no longer understates coverage for continuous scores
   (the hand example now selects 0.595, not 0.20). The primary rule searches a
   fixed 101-point grid and is the most permissive feasible grid point.
   `SPEC.md` 7.1 and 5.2 were rewritten to match.
3. **The primary metric is now a finite-sample conformal-style bound.** The
   primary rule is an exact one-sided Clopper-Pearson upper bound on the
   calibration conditional false-allow proportion, at confidence
   `1 - 0.05/101`, with a Bonferroni correction for the fixed 101-point search.
   The empirical add-one rule is retained only as a labelled diagnostic. All
   three splits were re-run: selected `tau` is 0.99, the calibration bounds are
   0.0268/0.0242/0.0236, and the test realized shares are
   0.0168/0.0230/0.0216. `ESCALATION.md`'s question is therefore answered by
   implementation rather than by a lead ruling; the report no longer quotes an
   "empirical, not conformal" primary number.
4. **The artifact scan now covers the whole readers package.** `SCAN_ROOTS`
   includes all of `og_s1/readers`, so a stale `__pycache__` is a failure; the
   caches were removed, and a test asserts the scan roots. The cited capture
   reports `artifact_scan files=32 absolute_home_hits=0 oversized=0`.
5. **The latency table was dropped.** The old table came from a different
   capture and was a single non-reproducible sample. Latency is still recorded
   in `results.json` for the cited capture, and the report says so without
   quoting a moving number.
6. **`_fact_matches` requires unit equality.** A unitless claim matches only a
   unitless source fact; `SPEC.md` 2 states the rule and a test pins it. The
   reference sample had no numeric unitless claim that matched a unitful fact,
   so no reported number moved.
7. **The question orientation is documented and pinned.** `SPEC.md` 5 quotes
   T11's exact wording for all four questions. `supported` is the only
   good-property question (`1 - p`); `hype`, `authority` and
   `addresses_reviewer` are all bad-property questions (`p`), so the natural
   `P(yes)` from a T11 lane is oriented correctly. A test pins this.
8. **Loopholes closed.** A missing cause/pointer prediction now counts as a
   miss instead of shrinking the denominator, and a pointer set larger than
   `max(1, len(true_refs)) + 2` is not a hit. The minor documentation fixes
   (top-cause vs pointer n/a wording, future-field list including
   `invalidation_trigger` and `status`, the scoped prose-access sentence, the
   removed fixed runtime claim, the "arithmetic tested" wording) are applied.
   The spec hash is now `ad9650c8…3896`; `SPEC.sha256` and every quoted hash
   were regenerated, and the cited capture is `20261119T103401Z-72904`.

Not changed, with reasons:

- **The 40-per-file sample stays.** It is a disclosed pipeline sample, not a
  capability claim; the full files remain available through `--limit`.
- **The company axis stays as the action's ticker.** The schema has no issuer
  id; the company table is labelled episode-overlapping and is not a
  generalization test.
- **The trivial readers stay trivial.** T15 is plumbing and a real
  per-question head is T11's job; inventing question labels here would be a
  worse error than a weak baseline.
- **The spec hash still covers only `SPEC.md`.** A code-and-spec manifest is a
  larger freeze change; 5.8 records the limit.
- **Adaptive evasion is still out of scope.** COMBOS section 4 asks for it but
  the T15 brief's metric list does not; implementing a weak attacker here
  would be an overclaim, and T06/T07 own it.
- **The older round-2 captures are kept but no longer cited.** They used the
  superseded empirical threshold and `None` policy; keeping them preserves the
  audit trail without mixing rules.

## Round 4 changes

The round-4 review was provisional: `bash run.sh` could not start because a
stale `work/T15/captures/.lock` from an interrupted run was still held, so the
entry point was not reproducible from the folder as delivered. That was the
only required fix; the pass-bar items were marked pending because the reviewer
could not run the checks.

Fixed:

1. **Stale-lock recovery in `run.sh`.** The capture lock now records the
   holder PID in `$LOCK/pid`. If the lock already exists, `run.sh` refuses only
   when that PID is alive (`kill -0`); otherwise it reports the stale holder,
   removes the lock and retries once. A legacy lock with no `pid` file is
   treated as stale, because the old script never wrote one and treating it as
   live is exactly what made the folder unreproducible. Cleanup removes the
   whole lock directory, not just an empty one.
2. **Evidence that the fix works.** Before the first round-4 run I created a
   lock containing a dead PID (`999999`). `bash run.sh` printed
   `removing stale T15 lock ... holder pid 999999 is not alive`, ran to
   completion and released the lock (exit 0, capture
   `20261120T022846Z-8747`). A second run from a clean folder also completed
   (capture `20261120T023351Z-10185`). After the lock messages were changed to
   relative paths (so a refusal cannot print an absolute home path), a run
   with a dead PID (`999998`) cleared that lock and produced
   `20261120T023927Z-11391`. After adding the index guard, a final clean run
   produced the cited capture `20261120T024510Z-13418`. A live holder is still
   refused by design; I checked this by holding a lock with a live `sleep`
   PID, which made `run.sh` exit 75 without running the bench and left the
   live holder's lock in place. The lock protects capture interleaving during
   a real run.
3. **Re-ran everything.** All round-4 captures show 41 tests passing, the same
   640 episodes / 76,800 actions / 15,765 positives, the same split counts,
   the same metric tables, the same selected `tau = 0.99`, and the spec hash
   `ad9650c87f929018e4a474d133957cc6729fd4b361807f155e1be7a9d7233896` before
   and after. Diffs between the captures differ only in wall-clock timings,
   test durations and the artifact file count (it grows by one whenever a new
   capture exists before the scan). Every deterministic number in this report
   is reproduced by the cited round-4 capture.
4. **Index guard and provenance.** The final `check.log` append now refuses to
   write a line when the spec hash is empty, so a killed interpreter cannot
   leave a malformed index entry. I removed one such line left by the pre-fix
   baseline append (its capture is complete but is not cited). Section 2 now
   names the cited round-4 capture and the earlier runs that reproduced it,
   section 3.1 says the hash was stable across round-4 runs, and the
   reproducibility risk in section 6 describes the PID-checked lock.

Not changed, with reasons:

- **No metric, corpus, split or spec change.** The review found no defect in
  them and did not ask for one; changing any of them would invalidate the
  round-3 numbers for no reason. `SPEC.md` and `SPEC.sha256` are untouched, so
  the frozen hash stays `ad9650c8…3896`.
- **The live-lock refusal stays.** The fix is stale-lock recovery, not removal
  of mutual exclusion; two concurrent bench runs would still interleave writes
  to `results.json`, so a live holder must still block.
- **The earlier captures stay on disk.** They are the audit trail and are not
  cited as the source of any current number.
