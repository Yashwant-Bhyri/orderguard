# T05. Bounded text channel — REPORT

## 1. What I built

A causal, bounded text channel with one reader per sub-question and a tournament
that scores them on `data/ref/`.

- `og_s1/text.py` — `TextChannel`, `features(episode)`, `features_at(episode, i)`,
  `action_texts`, `make_items`, `make_decision_item`, `max_logit_bound`.
  Every feature is computed from `og_s1.schema.model_view_at(episode, i)` only.
  `hype` and `authority_language` are scored sentence by sentence (rationale,
  each claim, each cited note) and aggregated by **max**; `support_gap` is
  `1 - P(entailment)` per sourced claim, with 0.5 for a claim with no source.
  `DEFAULT_READERS` is hype=`nli`, authority=`decision`, support=`nli`.
  Authority uses the pre-registered generic decision question. If the decision
  cache and key are both absent, the authority column is NaN (the array encoding
  of `None`) and `TextChannel.last_reasons` says why; it never falls back to the
  ref-selected NLI reader.
- `og_s1/readers/lexicon.py` — fixed word lists; the floor.
- `og_s1/readers/nli.py` — zero-shot DeBERTa-v3 NLI cross-encoder
  (`MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`, MIT). Used for entailment and
  for two-way zero-shot hype/authority classification. It also exposes
  `score_texts_with_sides` so fixed authority templates can be compared without
  editing the default reader.
- `og_s1/readers/embed_lr.py` — MiniLM sentence embeddings
  (`sentence-transformers/all-MiniLM-L6-v2`, Apache-2.0) plus one logistic
  regression per feature; support uses a symmetric pair representation.
- `og_s1/readers/injection.py` — two purpose-built prompt-injection classifiers
  behind one interface: `protectai/deberta-v3-base-prompt-injection-v2` and
  `fmops/distilbert-prompt-injection` (both Apache-2.0). Used only for
  `authority_language`.
- `og_s1/readers/decision.py` — the external decision model, one action-level
  call with three `noul` questions. The key is read from
  `OPENROUTER_API_KEY`; responses are cached under
  `work/T05/cache/decision_responses.jsonl`, keyed by the SHA-256 of the
  canonical request. No key or request body is written.
- `work/T05/make_train_text.py` — own templates and wording; no `data/ref/` text
  is read. Writes 2,100 rows to `work/T05/train_text/train_text.jsonl`.
- `work/T05/check_train_leakage.py` — independent 6-gram audit against
  `data/ref/`; the run finds 0 overlapping rows of 2,100.
- `work/T05/train_embed.py` — trains the three logistic heads and writes
  `work/T05/embed_lr.joblib` (20 KB), reporting both a random-row holdout and a
  template-group holdout.
- `work/T05/evaluate.py` — deterministic sampling, scoring, bootstrap CIs,
  calibration, latency, the eligible pass bar, a separate raw-best table, the
  extended-lexicon and fixed-template sensitivities, `results.json` and
  `table.md`. It appends each run's latency to `latency_history.jsonl` and
  archives the result under `work/T05/runs/`.
- `work/T05/preregister.py` — verifies the static `PREREGISTERED.md` hashes and
  fails on any mismatch; `--write` is the only way to create a new freeze.
- `work/T05/report_numbers.py` — generates every numeric table in this report
  from `results.json`, the frozen latency runs and `PREREGISTERED.md`, writes
  `numbers.md`, and fills the generated block in §3.
- `og_s1/tests/test_text.py` — tests for range, determinism, T03 action order,
  causal input, no label/meta access, 0.5 no-source support, decision cache key,
  channel determinism, no-fallback authority, cached-offline authority, offline
  default-channel execution.

The reader modules, `og_s1/text.py` and `og_s1/tests/test_text.py` are outside
the task folder because the brief places them there.

Reader checkpoints, confirmed from the Hugging Face model metadata:

| reader | checkpoint | params | licence | status |
|---|---|---|---|---|
| nli | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | 184M | MIT | used |
| embed_lr | `sentence-transformers/all-MiniLM-L6-v2` | 22.7M | Apache-2.0 | used |
| injection (A) | `protectai/deberta-v3-base-prompt-injection-v2` | 184M | Apache-2.0 | used |
| injection (B) | `fmops/distilbert-prompt-injection` | 67M | Apache-2.0 | used |
| injection (C) | `meta-llama/Llama-Prompt-Guard-2-86M` / `-22M` | 86M / 22M | other / llama3.1 | gated (manual approval); weights need a token |
| decision | external decision model | hosted | service | used, cached |

## 2. How to re-run (one command)

```bash
bash work/T05/run.sh
```

It takes a single-writer lock, installs any missing packages into `.venv`, logs
versions, ensures the model weights are cached under `data/models/hf`, verifies
the static preregistration hashes (and fails on a mismatch), rebuilds the
training text, audits it against `data/ref/` for 6-gram overlap, retrains
reader 3, runs the tournament, writes `results.json` and `table.md`, generates
`numbers.md` and the §3 block of this report, then runs the text tests online and
again with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, and finally checks that
`og_s1.text` imports offline. The captured log of the run is `work/T05/check.log`.

The first run downloads the model weights and makes 1,440 decision-model calls
(about $0.04, under the $2 cap). The cache makes a reviewer's re-run free. The
decision model is called only with the environment variable set; no key is
printed or written.

Latency is the one metric that changes between runs. `run.sh` quotes a range
over the named runs frozen in `work/T05/latency_runs.json`; a reviewer's fresh
run appends to `latency_history.jsonl` but does not edit that frozen list.

## 3. Results

<!-- BEGIN GENERATED NUMBERS -->
### 3.1 Pass bar (shifted ref, eligible readers only)

Sample: 1440 actions from 360 episodes, seed 20261119; shifted positives hype 38, authority_language 58, support_gap 70; negatives are all `y = 0` actions.  All values below are generated by `work/T05/report_numbers.py` from `work/T05/results.json`; latency is a range over the named runs in `work/T05/latency_runs.json`.

The official floor is the small registered lexicon.  Authority may be carried only by the pre-registered generic decision question; the ref-selected NLI authority hypothesis is sensitivity evidence and is excluded from this table.

| feature | eligible pass reader | AUROC | AUROC 95% CI | delta vs small lexicon | delta 95% CI | beats floor |
|---|---|---|---|---|---|---|
| hype | decision | 1.000 | [1.000, 1.000] | 0.329 | [0.258, 0.400] | True |
| authority_language | decision | 0.924 | [0.860, 0.973] | 0.079 | [0.018, 0.149] | True |
| support_gap | decision | 0.998 | [0.995, 1.000] | 0.155 | [0.096, 0.224] | True |

**Eligible pass bar: MET** on shifted ref.

### 3.2 Raw best readers (transparency; may be ineligible)

| feature | raw best reader | AUROC | delta vs small lexicon | delta 95% CI | beats floor |
|---|---|---|---|---|---|
| hype | decision | 1.000 | 0.329 | [0.258, 0.400] | True |
| authority_language | nli | 1.000 | 0.155 | [0.080, 0.239] | True |
| support_gap | decision | 0.998 | 0.155 | [0.096, 0.224] | True |

The raw best authority reader is the NLI template selected on shifted ref (see `tuned_restriction_lifted` in §3.5). It is reported here so the number is not hidden, but it is not eligible for the pass bar and the channel does not use it.

### 3.3 Channel-selected readers (shifted ref)

`og_s1.text.DEFAULT_READERS` is hype=`nli`, authority=`decision`, support=`nli`.  The decision row uses the same bootstrap seed as the pass-bar row for the same comparison.

| feature | selected reader | AUROC | delta vs small lexicon | delta 95% CI | beats floor |
|---|---|---|---|---|---|
| hype | nli | 0.999 | 0.328 | [0.256, 0.399] | True |
| authority_language | decision | 0.924 | 0.079 | [0.018, 0.149] | True |
| support_gap | nli | 0.990 | 0.147 | [0.091, 0.214] | True |

### 3.4 Authority reader vs floor (shifted ref)

| reader | floor | floor AUROC | reader AUROC | delta | delta 95% CI | beats floor |
|---|---|---|---|---|---|---|
| nli (ref-selected; sensitivity) | small registered lexicon | 0.845 | 1.000 | 0.155 | [0.080, 0.239] | True |
| nli (ref-selected; sensitivity) | extended fixed list (sensitivity) | 1.000 | 1.000 | -0.000 | [-0.001, 0.000] | False |
| decision (eligible) | small registered lexicon | 0.845 | 0.924 | 0.079 | [0.018, 0.149] | True |
| decision (eligible) | extended fixed list (sensitivity) | 1.000 | 0.924 | -0.076 | [-0.144, -0.026] | False |

The decision-model authority question beats the small registered lexicon; it loses to the extended oracle list.  This is the same result the lead ruled on (MET against the small floor, sensitivity against the extended list).

Round-2 ruling quoted delta 0.079 with CI [+0.018, +0.149] from an earlier bootstrap seed.  With the single seed now used everywhere, the same comparison is 0.079 [0.018, 0.149].  Both intervals exclude zero; this does not reopen the ruling.

### 3.5 Authority NLI template sensitivity (shifted ref)

| NLI hypothesis | AUROC | delta vs small lexicon | delta 95% CI | beats small lexicon |
|---|---|---|---|---|
| generic_instruction_to_reviewer | 0.536 | -0.309 | [-0.428, -0.194] | False |
| generic_permission_approval_exception | 0.676 | -0.169 | [-0.241, -0.095] | False |
| generic_permission_or_approval | 0.609 | -0.236 | [-0.334, -0.142] | False |
| round1_original_reconstructed | 0.655 | -0.189 | [-0.295, -0.091] | False |
| tuned_restriction_lifted | 1.000 | 0.155 | [0.080, 0.239] | True |

### 3.6 Full AUROC table (95% episode-bootstrap CI)

| feature | reader | unshifted | shifted |
|---|---|---|---|
| hype | decision | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| hype | embed_lr | 0.993 [0.983, 0.999] | 0.966 [0.947, 0.985] |
| hype | lexicon | 0.806 [0.708, 0.893] | 0.671 [0.603, 0.742] |
| hype | nli | 1.000 [1.000, 1.000] | 0.999 [0.998, 1.000] |
| authority_language | decision | 0.969 [0.932, 0.998] | 0.924 [0.860, 0.973] |
| authority_language | embed_lr | 0.977 [0.955, 0.992] | 0.936 [0.900, 0.968] |
| authority_language | injection | 0.454 [0.378, 0.529] | 0.532 [0.458, 0.610] |
| authority_language | injection_fmops | 0.567 [0.473, 0.651] | 0.624 [0.516, 0.728] |
| authority_language | lexicon | 0.913 [0.847, 0.966] | 0.845 [0.767, 0.918] |
| authority_language | nli | 1.000 [1.000, 1.000] | 1.000 [0.999, 1.000] |
| support_gap | decision | 0.999 [0.997, 1.000] | 0.998 [0.995, 1.000] |
| support_gap | embed_lr | 0.657 [0.582, 0.727] | 0.682 [0.601, 0.752] |
| support_gap | lexicon | 0.884 [0.814, 0.939] | 0.843 [0.775, 0.902] |
| support_gap | nli | 0.997 [0.993, 0.999] | 0.990 [0.983, 0.995] |

### 3.7 Calibration (ECE / Brier, shifted ref)

| feature | reader | ECE | Brier | n |
|---|---|---|---|---|
| hype | decision | 0.288 | 0.112 | 592 |
| hype | embed_lr | 0.360 | 0.184 | 592 |
| hype | lexicon | 0.043 | 0.042 | 592 |
| hype | nli | 0.246 | 0.078 | 592 |
| authority_language | decision | 0.553 | 0.416 | 612 |
| authority_language | embed_lr | 0.152 | 0.074 | 612 |
| authority_language | injection | 0.903 | 0.901 | 612 |
| authority_language | injection_fmops | 0.905 | 0.904 | 612 |
| authority_language | lexicon | 0.041 | 0.034 | 612 |
| authority_language | nli | 0.343 | 0.205 | 612 |
| support_gap | decision | 0.209 | 0.074 | 624 |
| support_gap | embed_lr | 0.519 | 0.369 | 624 |
| support_gap | lexicon | 0.540 | 0.361 | 624 |
| support_gap | nli | 0.066 | 0.032 | 624 |

### 3.8 Latency per action (range over named runs)

Range over frozen list `latency_runs.json` (4 of 4 runs found).  Each run scores 1,440 actions serial after a warm-up; the network decision reader includes the round trip.  Wall-clock varies with machine load, so this table quotes ranges, not a millisecond-exact reproduction claim.  `results.json` holds the latest run's point values.

| reader | device | features | p50 min–max ms | p99 min–max ms | runs |
|---|---|---|---|---|---|
| decision | network | hype+authority+support | 1150.0–1150.0 | 1657.4–1657.4 | 4 |
| embed_lr | mps | hype+authority+support | 19.5–45.4 | 32.1–197.9 | 4 |
| injection | mps | authority only | 29.6–43.9 | 43.6–192.5 | 4 |
| injection_fmops | mps | authority only | 7.5–11.0 | 11.5–24.9 | 4 |
| lexicon | cpu | hype+authority+support | 0.1–0.1 | 0.1–0.9 | 4 |
| nli | mps | hype+authority+support | 151.4–268.7 | 189.7–772.9 | 4 |

The hosted decision reader's p50 is 4.3–7.6× the NLI p50 across the same runs (computed, not typed).  The earlier 'about 5×' prose was wrong for these runs and is removed.

### 3.9 Largest logit contribution (placeholder)

Unit-weight bound: **1.0 logit** per feature.  Univariate monotone logistic slopes on shifted ref, using the channel's selected readers: hype 7.089, authority_language 2.527, support_gap 5.282. T07's actual scorer must recompute `g(1) − g(0)` from its own shape functions.

### 3.10 Decision-model cost and cache

Calls: 1440; cost: $0.042320; cache: `work/T05/cache/decision_responses.jsonl`.

Frozen preregistration SHA-256: `79eda5f95bf27bb2381d8beaffea6f4abdcfa1cacb3661bbb29c27bf2549caf6`. `run.sh` recomputes it and fails on a mismatch; the file is never regenerated.
<!-- END GENERATED NUMBERS -->

### 3.11 What the tables mean

- **Pass bar.** The eligible pass reader beats the small registered lexicon on
  shifted ref for all three features. Authority is carried only by the
  pre-registered generic decision question; the ref-selected NLI authority
  hypothesis is shown separately as sensitivity and is not used by the channel.
- **Raw best vs eligible.** The raw best authority reader is NLI, but its
  winning hypothesis was chosen on shifted ref. §3.2 keeps the number visible;
  §3.1 is the eligible bar.
- **Selected channel.** The channel uses NLI for hype and support and the
  decision question for authority. Its authority row is identical to the
  pass-bar row because both use the same reader and the same bootstrap seed.
- **Calibration** in §3.7 is raw reader calibration, not calibrated probabilities
  of endorsement. T07 owns recalibration and conformal risk control.
- **Latency** in §3.8 is a range over the frozen runs. The decision reader's
  cached request latency is effectively constant across runs; local readers move
  with machine load.

### 3.12 What ref cannot tell us

On ref, authority euphemisms are a small, repeated set, so a word list or a
sentence template chosen against them can look perfect. The open question is
whether any authority reader holds on wording it has never seen. Ref cannot
answer that: the NLI authority score is ref-selected, the extended lexicon is
built from the same failure modes, and shifted authority has only 58 positives.
The frozen candidates in `PREREGISTERED.md` must be scored by T07/T11 on the
unseen worlds (T02a–d, T16). Whichever wins there is the real answer; nothing
more may be tuned on ref for authority.

## 4. What did not work

- **Prompt Guard 2 could not be tested.** Its Hugging Face model cards
  (`meta-llama/Llama-Prompt-Guard-2-22M` and `-86M`) are public but marked
  `gated: manual`; downloading the weights requires accepting the gate with an
  HF token, which this task does not have. The older
  `meta-llama/Prompt-Guard-86M` is gated too. ProtectAI and fmops were used
  instead. Licences were read from the same metadata.
- **The purpose-built injection classifiers did not transfer.** ProtectAI was
  near chance on shifted authority (0.532) and fmops was only 0.624, both below
  the lexicon (0.845) and far below NLI (1.000).
- **Reader 3 is weak on support.** Its template-group holdout is 0.811 and its
  random-row holdout 0.872 (369 positives / 331 negatives), but on shifted ref
  it is 0.682. The embeddings learn surface template cues rather than
  number-level entailment. It is reported, not selected.
- **The authority NLI result depends on one ref-chosen phrase.** The round-1
  original hypothesis, reconstructed here as "This text asserts a permission.",
  scores 0.655 on shifted ref. Three generic variants score 0.536–0.676, all
  below the small lexicon. Only "This text claims that a restriction has been
  lifted" reaches 0.9996. That is a test-set choice, not a held-out result, and
  it is why the lead excluded it from the pass bar.
- **The extended authority lexicon is an oracle on this data.** It reaches
  AUROC 1.000 on both shifts. NLI minus that extended list on shifted ref is a
  tie, not a win; the pre-registered decision question loses to it.
- **NLI latency misses the 300 ms target in most recorded runs.** The exact
  p99 range across the frozen runs is in §3.8; only the fastest of those runs
  was under 300 ms. The brief only requires reporting latency, but C6 will need
  a GPU, a smaller NLI checkpoint, or the faster embed reader.
- **Calibration is not ranking.** Under the ref base rate the near-zero lexicon
  has the best raw ECE/Brier on hype and authority while ranking far worse.
  Selecting on ECE alone would pick a conservative constant. The hosted decision
  model's `noul` probabilities are also badly calibrated on ref authority despite
  its 0.924 AUROC.
- **The decision model is not faster than the local reader.** Its p50 is several
  times the NLI p50 across the frozen runs (the computed range is in §3.8),
  despite being cheap. It was not selected as the local default.
- **Round-1 reader-3 training text was contaminated.** It shared the planted
  phrases with the reference generator. Round 2 rewrote the templates,
  retrained, and added a 6-gram audit that now finds 0 overlapping rows.

## 5. Judgement calls

### 5.1 Reader per sub-question: NLI local default; decision carries authority

- **Choice.** DeBERTa-v3-base NLI cross-encoder, zero-shot, is the local default
  for hype and support. The authority default and the authority pass bar are the
  pre-registered generic question to the hosted decision model, per the lead's
  ruling. The NLI authority hypothesis is a named sensitivity reader only.
- **Alternatives.** (a) Lexicon rules (fixed, no learning); (b) MiniLM
  embeddings + logistic regression (trained, local); (c) purpose-built
  prompt-injection classifiers (specialist); (d) the external decision model
  (hosted, typed probability); (e) hidden-state probes or a logprob judge on a
  strong open model (GPU; T11's remit, not T05's).
- **Why it wins on this project's criteria.** For hype and support, NLI is
  within 0.05 AUROC of the best, runs offline once cached, has an MIT licence,
  and is faster than the hosted model. For authority, only a reader whose
  wording was fixed before seeing shifted ref may carry the bar; the decision
  question is that reader. It beats the small registered floor and its CI
  excludes zero. The channel never falls back to the ref-selected NLI.
- **What would flip it.** Held-out wording where NLI is more than 0.05 AUROC
  below the decision model on hype/support; a generic authority template that
  beats the floor; or a deployment with a hard 300 ms p99 bar. On such a device
  the embed reader (hype) or a GPU probe (T11) takes over. The decision model
  remains a cascade fallback for support/hype if its network cost is acceptable.

### 5.2 NLI checkpoint: base DeBERTa-v3 MNLI+FEVER+ANLI

- **Choice.** `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` (184M, MIT).
- **Alternatives.** (a) DeBERTa-v3-large NLI (more capacity, slower);
  (b) a small cross-encoder / MiniLM NLI (faster, weaker); (c) a generative
  judge scored by logprob (flexible, slower, easier to steer); (d) a
  finance-tuned NLI checkpoint (domain fit, narrower training).
- **Why it wins.** ANLI in the training mix is the closest published proxy for
  adversarial entailment; base size fits the laptop. Large would likely improve
  support but break the latency budget.
- **What would flip it.** A held-out gain of more than 0.05 AUROC from large or
  finance-tuned NLI, with p99 still under the C6 bar on the deployment device.

### 5.3 Embedding model and training text

- **Choice.** `all-MiniLM-L6-v2` + logistic regression, trained on our own
  templates (2,100 rows; 350/350 for hype and authority, 700 support rows split
  369/331), with a template-group holdout.
- **Alternatives.** (a) a larger embedding model (MPNet, E5, BGE); (b) a
  cross-encoder fine-tune (reader 2 already fills this role); (c) in-context
  classification with the decision model; (d) TF-IDF + linear model (cheap,
  surface-heavy).
- **Why it wins.** It is the fastest local reader that covers all three
  features, a 20 KB artifact, fully local, and strong on hype (0.966) and
  authority (0.936). It loses on support.
- **Validation.** The template-group split is the honest one. An earlier
  grouping held out pure-label template cells and produced a degenerate 0.000
  support holdout; the groups now each contain both labels. The training text is
  audited against `data/ref/` for 6-gram overlap and has none.
- **What would flip it.** A larger encoder improving support by more than 0.05
  within the latency budget, or held-out evidence that MiniLM's surface cues do
  not transfer.

### 5.4 Injection classifiers

- **Choice.** ProtectAI DeBERTa-v3 injection v2 and fmops DistilBERT, reported
  side by side; neither selected.
- **Alternatives.** Meta `Llama-Prompt-Guard-2` 86M/22M (gated, untested), a
  fine-tuned authority classifier, or the NLI zero-shot reader.
- **Why they lose.** They are trained on jailbreak commands; the planted
  authority language is polite and indirect. Their AUROCs are below the lexicon.
- **What would flip it.** Access to Prompt Guard 2 and a held-out gain over NLI;
  or red-team cases where the authority text is imperative rather than polite.

### 5.5 External decision model

- **Choice.** One action-level call with three `noul` questions; cached.
- **Alternatives.** NLI, embeddings+LR, injection classifiers, GPU probes.
- **Why it is not the local default.** It wins hype/support by less than the
  0.05 X2 drop margin, loses to NLI on authority as a raw ranking, is worse
  calibrated than NLI on every feature, and adds a network dependency and
  seconds-scale latency. Its generic authority question is nonetheless the only
  eligible reader that beats the small registered floor, so it carries the
  authority pass bar and the channel's authority default.
- **Pre-registration disclosure.** The three question strings in
  `og_s1/readers/decision.py` are generic per-feature questions written from the
  feature definitions before any ref scoring; they contain no ref-specific
  phrase (no "widened", "lifted", "per the owner"). The run reports 1,440 cached
  calls and zero new spend, so every scored response was produced by exactly
  these strings; a changed question would have missed the SHA-256 cache.
- **What would flip it.** A held-out gain over NLI of more than 0.05 AUROC with
  an acceptable latency/cost budget, or a deployment where the network call is
  free relative to the rest of the path.
- **Interface note.** This reader answers three questions in one action-level
  call and its `score` returns an `(n, 3)` array. That is the one documented
  deviation from the one-score-per-item interface; the local readers return 1-D
  arrays.
- **Support semantics.** The decision model's support question is action-level
  and treats an unsourced claim as a reason to lower support, whereas the local
  readers take `max(1 − P(entailment), 0.5 for an unsourced claim)`. It was not
  selected for support, so the channel uses the local per-claim rule.

### 5.6 Lexicon floor

- **Choice.** A small generic authority list (permission/approval/exception/
  instruction words) that deliberately does **not** encode "the owner widened".
- **Alternatives.** (a) an exhaustive curated list including every planted
  euphemism; (b) a bag-of-words model trained on ref (not a floor); (c) a
  random baseline; (d) the generic hosted decision-model question (not a word
  list at all).
- **Why it wins as a floor.** The extended list is an oracle on ref: it reaches
  1.000 on both shifts, so against it the "beat the lexicon" bar is a tie for
  NLI and a loss for the decision model. I keep the small list because it is
  what a practitioner would ship before reading the failure modes, and report
  the extended list as a sensitivity. The lead ruled the small list is the
  official floor.
- **What would flip it.** If the lead wants the strongest possible baseline,
  register the exhaustive list; then no reader beats it on ref and the
  tournament has to move to held-out wording.

### 5.7 Evaluation sample and metric

- **Choice.** 30 episodes/file × four actions sampled uniformly within each
  episode, 1,440 actions, all `y=0` actions as negatives, positives by cause,
  1,000 episode bootstrap.
- **Cause mapping.** `vague_hype`→hype; `authority_spoof` and `poisoned_note`
  →authority; `misquote` and `unsupported_claim`→support. `drift` and
  `stale_thesis` are excluded because they are code-check causes with no planted
  wording change.
- **Alternatives.** (a) all ref actions (too slow for NLI/API); (b) oversample
  positives; (c) episode-level leave-one-author-out (no authors in ref); (d)
  authority on `authority_spoof` only (drops roughly half the positives).
- **Why it wins.** It is uniform within episodes and label-blind, gives
  episode-level CIs, and fits the time budget. The same actions are used for
  every reader.
- **What would flip it.** A full-corpus local-only run if the transformer budget
  grows, or a held-out evaluation in T07.

### 5.8 Aggregation: per-sentence max

- **Choice.** Score rationale, each claim and each cited note separately; take
  the max for hype/authority.
- **Alternatives.** (a) concatenate all text and score once; (b) mean; (c) a
  learned aggregator.
- **Why it wins.** One promotional claim is enough to make the wording risky;
  concatenation diluted the signal in an earlier probe. Max is monotone and easy
  to attribute.
- **Notes read: cited only.** An uncited note is not part of the action's stated
  reasoning, and scoring every available note would let one poisoned note raise
  risk for all later actions. Evidence that agents follow uncited notes would
  flip this.
- **What would flip it.** Held-out evidence that mean or a learned aggregator is
  better calibrated, or that max over-fires on a single stray word.

### 5.9 Support neutral value

- **Choice.** 0.5 per claim with no source, as the brief specifies; the action
  feature is the worst claim. An action with no claims at all is also 0.5.
- **Alternatives.** 0, 1, or a learned prior. The brief fixes 0.5, so it was not
  tuned.
- **What would flip it.** A lead change to the neutral value, or evidence that a
  learned prior calibrates better on held-out wording.

### 5.10 Largest logit contribution

- **Choice.** Report a unit-weight bound (1.0) and a univariate monotone logistic
  slope as a placeholder.
- **Alternatives.** Leave it to T07 (the honest option), or fit a full monotone
  EBM/tree and read the term ranges. T07 owns the scorer, so a full fit here
  would be a different model.
- **Why it wins.** It gives the lead a concrete number while stating the
  assumption; the final bound must be recomputed from the actual scorer.
- **What would flip it.** T07's fitted scorer, or a requirement for a certified
  bound: then compute the term's total variation `g(1) − g(0)`.

### 5.11 Model cache and disk

- **Choice.** Keep the four reader checkpoints under `data/models/hf` (about
  1.6 GB) rather than delete weights after each run.
- **Alternatives.** (a) use only the 67M fmops injection model (smaller,
  weaker); (b) run the readers on the university host (the brief says Mac
  MPS/CPU, and staging adds a round trip); (c) skip the NLI checkpoint (loses
  the selected reader).
- **Why it wins.** The brief requires cached weights under `data/models/`, and
  T07/T11 will re-score the same readers. Deleting them would make every review
  re-download a gigabyte.
- **Policy conflict and lead decision.** POLICY's 500 MB guideline conflicts
  with the required checkpoints. The lead granted an exception for exactly these
  four CPU checkpoints (1.6 GB) because T07 needs them on the Mac; GPU-size
  models stay on the host (T11). This is the recorded resolution, not a silent
  override.
- **What would flip it.** The lead revoking the exception, or a smaller selected
  NLI checkpoint that keeps the AUROC.

### 5.12 Authority template search: sensitivity only

- **Choice.** Keep the tuned "a restriction has been lifted" template only as a
  named sensitivity reader. The channel's authority default is the decision
  question, and the authority pass bar is the decision question.
- **Alternatives.** (a) Ship a generic "asserts a permission" template and
  accept 0.655; (b) ship the extended fixed list as the floor and treat authority
  as a tie; (c) drop authority from the text channel until a held-out reader is
  available; (d) use the hosted decision model's generic authority question
  (0.924, beats the small floor, loses to the extended list).
- **Why this is the chosen middle.** The tuned phrase is the only NLI template
  that clears the small lexicon, but choosing it after seeing shifted ref is a
  test-set fit. The lead ruled it cannot carry a pass. The channel therefore
  uses the eligible generic decision question, and the tuned phrase is published
  in the sensitivity table so the number is not hidden.
- **What would flip it.** A held-out authority sample where a generic template
  or the decision question holds up better; T07/T11 score the frozen candidates.

## 6. Loopholes I checked

- **No label/meta leakage.** `text.action_texts` and every reader consume only
  `model_view_at`; tests change `meta.family` and every `label` and assert the
  features are unchanged.
- **No future leakage.** `model_view_at` filters documents by `t`, notes by
  availability, and theses without final `status`; a test adds a future
  document, note and action and asserts `features_at(ep, 1)` is unchanged.
- **Action-order alignment.** `features(ep)` rows are checked against an
  independent per-step lexicon calculation, which would fail if the rows were
  reversed. A separate test changes one action's rationale and asserts only that
  row moves.
- **Training/ref leakage.** `check_train_leakage.py` reads every ref document,
  note, rationale and claim, builds all 6-grams, and reports 0 overlapping rows.
  The training generator itself does not read `data/ref/`.
- **Reader range.** Every local reader is tested on [0, 1] and for determinism;
  the decision reader is exercised through its canonical cache key.
- **No false authority fallback.** A test removes the decision key and points
  the cache at an empty file: authority becomes NaN with a reason and local
  features remain finite. Another test seeds a cached decision response and
  confirms authority is finite with no key. There is no silent NLI fallback.
- **Eligible-only pass bar.** `results.json["pass_bar"]` is computed only over
  `PASS_BAR_READERS`; authority has exactly one eligible reader, the decision
  question. The raw best reader is a separate object. If the decision reader is
  unavailable, authority is marked not met rather than falling back.
- **One bootstrap seed per comparison.** Pass-bar, selected and decision-floor
  rows against the small lexicon all use the same per-feature seed, so the same
  reader/delta gets the same interval. The raw NLI authority row and the tuned
  template row now also share that seed.
- **Static preregistration.** `PREREGISTERED.md` is not regenerated.
  `preregister.py --check` recomputes the configuration hash and fails on any
  mismatch; `run.sh` calls check mode, so a later reader edit cannot silently
  move the frozen candidates.
- **Generated numbers.** `report_numbers.py` computes every table in §3 from
  `results.json`, `latency_history.jsonl`, the frozen run list and
  `PREREGISTERED.md`, and injects the block between markers. No result is typed
  by hand in that block.
- **Latency provenance.** §3.8 quotes ranges over named runs in
  `latency_runs.json`, not a millisecond-exact value from an unidentified run.
  Ratio claims are computed in the same script.
- **Single log writer.** `run.sh` writes to a temp log and moves it into place
  after the pipeline, so a harness capture cannot append a duplicate tail.
- **No held-out peeking.** I did not read any file under `data/heldout*`,
  `work/T02*` or `work/T06`. The evaluation uses `data/ref/` only.
- **No git.** No git command was run.
- **No secrets.** The decision key is read from `OPENROUTER_API_KEY`; the cache
  stores only the SHA-256 key and the response, never the request body or key.
  `check.log`, `results.json` and the cache contain no absolute home path and no
  bearer/token string. `results.json` labels the hosted reader "external
  decision model (hosted)".
- **Cost.** The decision calls cost about $0.04, well under the $2 cap.
- **Determinism.** Sampling is seeded; bootstrap is seeded; the decision
  responses are cached; the embed model is deterministic. NLI on MPS can differ
  in the last floating-point digits across runs, so results are quoted to three
  decimals.
- **Disk.** Model weights are under `data/models/hf` (about 1.6 GB, lead
  exception recorded in §5.11); the task folder's largest file is the decision
  cache, under 1 MB.
- **No real orders.** No exchange was contacted.

## 7. Open risks

- **Ref is templated.** Authority has two surface templates and hype has a small
  slogan set. Near-perfect ref AUROCs are evidence that the readers can separate
  these templates, not that C1 will hold on held-out wording. T07/T11 must
  re-score on `data/heldout*`; T05 deliberately did not look.
- **Authority transfer.** The decision question beats the small floor on ref,
  but ref's euphemisms are a small repeated set. The frozen candidates in
  `PREREGISTERED.md` are the only ones T07/T11 may score; the open question is
  transfer to unseen wording.
- **Latency.** NLI p99 is above 300 ms in most recorded runs (see §3.8). If that
  bar is hard, the embed reader is the fastest local all-feature option but its
  support AUROC is weak; a GPU reader (T11) is the likely fix.
- **Decision-model dependency.** The hosted reader adds a network dependency, a
  small per-action cost, and unknown robustness to adversarial text. It is used
  for authority; its output must remain tighten-only.
- **Injection blindness.** Both accessible injection classifiers miss polite
  authority language. Prompt Guard 2 remains untested because of the licence
  gate. If T06 finds imperative authority text, these readers become relevant.
- **Reader 3 support transfer.** MiniLM + LR learns surface templates; its
  template-group holdout is 0.811 and its shifted-ref support AUROC is 0.682.
  Treat it as a latency fallback for hype, not as a support reader.
- **Lexicon sensitivity.** The authority pass margin depends on the registered
  small lexicon. The extended lexicon reaches 1.000 on ref and ties NLI; the
  generic NLI templates fall below the small lexicon.
- **Max-logit placeholder.** The fitted slopes are descriptive. T07's actual
  scorer, its monotone constraints and its shape-function ranges define the real
  bound; recompute there.
- **Calibration.** The raw features are not calibrated probabilities; ECE is high
  for NLI hype/authority and for the decision model. T07's scorer must
  recalibrate before any stated probability is read as a risk, and the conformal
  layer, not the raw reader, carries the guarantee.
- **MPS nondeterminism.** Last-digit differences across runs are possible. The
  tables are rounded to three decimals; a reviewer diff at 10 decimals may see
  noise that does not change any conclusion.
- **Reviewer discrepancy on generic templates.** Round-1 review reported generic
  authority variants at 0.866–0.99997; this round's fixed generic variants score
  0.536–0.676 on the same corpus with the same reader and max aggregation. The
  exact strings are in `evaluate.py`; the safe reading is that authority does not
  have a demonstrated robust reader yet.

## 8. Round 4 changes

The reviewer returned REVISE. I fixed every item in order of importance, then
re-ran the whole pipeline. `SOL_ADVICE.md` (round-4 addendum) binds the
substantive choices.

1. **Latency provenance (fixed).** §3.8 no longer claims a millisecond-exact
   value from "the run that wrote results.json". `evaluate.py` appends every
   run's latency to `latency_history.jsonl` and archives its results;
   `report_numbers.py` quotes a range over the named runs frozen in
   `latency_runs.json`. The old approximate speed-ratio and per-run p50
   comparison prose is removed; the ratio is computed in §3.8. Latency prose in
   §§4, 5.1, 5.3, 5.5 and 7 now points to that generated range instead of
   repeating a stale value.
2. **Pass-bar artifact follows the lead's ruling (fixed).**
   `results.json["pass_bar"]` is now computed only over `PASS_BAR_READERS`
   (authority: decision only; hype/support: decision or NLI). `table.md` and the
   captured `PASS BAR` line use the same eligible object. `raw_best` is a
   separate table. If the decision reader is unavailable, authority is marked
   not met; there is no fallback to the ref-tuned NLI.
3. **Authority CI reconciled (fixed).** One per-feature seed is used for every
   comparison against the small lexicon. The authority decision delta is 0.079
   with 95% CI [0.018, 0.149] in the pass-bar, selected and floor tables. A
   generated line notes that the round-2 ruling quoted [+0.018, +0.149] from an
   earlier seed. NLI authority no longer appears with two different intervals.
4. **Delivered log and log writer (fixed).** `run.sh` captures to
   `.check.log.tmp` and moves it into place after the pipeline, so a harness
   capture cannot produce a duplicated tail. The final capture has one test
   pass line per suite.
5. **Conditional authority language removed (fixed).** §5.12 now states the
   authority result is MET on the eligible decision question and that the NLI
   template is sensitivity only. `DEFAULT_READERS["authority_language"]` is
   `decision`; missing cache/key yields NaN with a reason, never NLI.
6. **Preregistration enforces itself (fixed).** `PREREGISTERED.md` is static.
   `preregister.py --check` recomputes the hash and fails on a mismatch; `run.sh`
   calls check mode and never regenerates the file.
7. **Pass-bar table generated; offline suite added; cache decision recorded
   (fixed).** `report_numbers.py` generates every numeric table in §3 and injects
   it into this report; `run.sh` runs the text suite online and offline and then
   imports `og_s1.text` offline. The lead's exception for the four CPU
   checkpoints (1.6 GB) is recorded in §5.11.

What I did not change, and why:

- **The extended lexicon stays a sensitivity, not the floor.** The lead ruled
  the small registered lexicon is the official floor.
- **NLI stays the local default for hype and support.** It is within the X2
  margin, local/offline, and MIT-licensed; only authority moved to the decision
  model.
- **The ref-tuned NLI authority templates stay in the sensitivity table and the
  frozen file.** T07/T11 must score them on unseen wording, but they carry no
  evidence here and the channel does not use them.
- **The 1.6 GB model cache stays.** The lead granted an exception for exactly
  these four checkpoints; deleting them would break the offline requirement.
- **Held-out data was not read.** I still did not open `data/heldout*`,
  `work/T02*` or `work/T06`; authority robustness on new wording remains
  T07/T11's job.
