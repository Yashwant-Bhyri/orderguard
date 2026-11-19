# T14 — Taint propagation through the why graph, and a single-root-source cap

## 1. What I built

A deterministic taint layer over the System One why graph, in a new module
`og_s1/taint.py`. It does not change `og_s1/checks.py`, so T03's 41-feature
contract and its 36 tests remain untouched.

- **Trust labels.** Every node gets an ordinal trust label in `[0, 4]` from
  provenance:
  - a document starts at its `trust_tier` (0..3);
  - a note starts from its writer and signature: `owner_signed` with a valid
    signature = 4, agent = 2, tool = 1, external = 1, an invalid owner
    signature = 0;
  - an agent-authored claim starts at 2; an unsourced claim, a citation to a
    document that is not visible, or a missing note starts at 0;
  - a thesis starts at 2 when it has evidence documents, and at 1 when it has
    none.
- **Propagation.** `propagate_trust(base, edges)` computes the least fixed
  point of `trust[v] = min(base[v], trust[cited])`. A node inherits the lowest
  trust of everything it cites or summarises, directly or through a chain.
  Trust can only fall along a chain, never rise. The same routine handles
  cycles and immediate min-propagation; `shortest_chain_length` gives the
  number of edges from an action to the nearest untrusted source root.
- **Why graph.** Documents cite nothing. Notes cite documents. Claims cite
  their `source_doc`. Theses cite their `evidence_docs`. Actions cite their
  claims, cited notes and thesis. A missing or future reference becomes an
  invisible stub with trust 0, so a citation to something not in the causal
  view is an untrusted root.
- **Six taint features**, all oriented so that a larger value means more risk:
  - `taint_claim_tainted_share` — share of the action's claims with trust
    below the untrusted threshold;
  - `taint_decisive_claim` — whether the decisive claim is tainted (a claim
    below the trust threshold);
  - `taint_decisive_support` — the gate input. It has exactly two non-zero
    cases. (i) If the action has a permission excess and cites at least one
    note that is not a valid owner-signed note, it is 1: an authority note is
    untrusted for granting permission even when its informational trust is 2
    (an agent note). (ii) Otherwise, if the action has a decisive claim, it is
    1 exactly when that claim's propagated trust is below the threshold.
    Otherwise, including an action with no decisive claim that only cites a
    tainted note for information, it is 0. There is no "first cited note"
    fallback;
  - `taint_chain_proximity_risk` — `1 / (1 + shortest_chain_length)`, a
    risk-oriented transform of the shortest chain to an untrusted root;
  - `taint_authority_untraced` — when the action needs a permission
    (permission excess above zero), whether it cites any note that is not a
    valid owner-signed note, or has no valid owner-signed note. An in-band
    action that cites a non-owner note purely for information stays at 0;
  - `taint_untrusted_root_count` — the number of distinct untrusted source
    roots reachable from the action.
- **Decisive claim.** The schema has no effect field, so the decisive claim is
  defined structurally as the claim that restates one of the action thesis's
  own evidence documents; among those, the largest magnitude wins. If no claim
  restates the thesis evidence (for example a rebalance sell whose claims are
  unrelated sector facts), there is no decisive claim. This is documented in
  Section 5.
- **Gate.** `analyze_taint` returns a hold-only gate decision for every action:
  hold when the decisive support is non-zero (the two cases above) and the
  notional exceeds `max($1, 0.5% of the book)`, regardless of any model score.
  An action with no decisive claim holds only if it also has a permission
  excess and a non-owner authority note; a tainted note cited only for
  information does not hold the action.
- **Single-root-source cap.** A causal sliding window (default 20 actions)
  groups each action by the root **documents** its evidence traces back to. The
  default is the brief's all-root grouping: every root document, trusted or
  not, plus every untrusted non-document source (a note with no document, an
  unsourced claim, a missing or empty thesis stub) and a non-owner authority
  note when the action has a permission excess. A trusted note is **not**
  itself a root: an owner-signed or agent note that cites a document is not a
  root (the document beneath it is), and a trusted note with no document is
  not a cap root either, with the single exception of a non-owner authority
  note on a permission action (already listed). Making trusted notes roots
  would flag almost every clean action, because the reference owner-mandate
  note is cited by nearly every clean action. For each root it counts recent actions and sums recent
  notional. Untrusted roots use the sensitive default (4 recent actions or 10%
  of the book); trusted document roots use a concentration default (12 of 20
  actions or 25% of the book) because normal thesis evidence is reused far more
  often. Setting `root_cap_include_trusted` to false restores the previous
  untrusted-only monitor. The parameters and reasoning are in
  `DEFAULT_CONFIG` and Section 5.
- `work/T14/test_taint.py` — 23 tests: the 10,000-graph monotonicity property
  test, chain and label tests, feature tests, a clean-reference gate test, an
  authority-assertion test (a non-owner note without a permission need must not
  set the authority feature), a round-3 regression test that an in-band action
  with no decisive claim citing one tainted note does **not** hold, root
  semantics tests that assert the exact root node ids (a missing document stub,
  an invalid owner-signed note, an agent note), root-cap tests for a trusted
  document and an untrusted note in both cap modes, a test that a trusted note
  is not an all-root cap root, a deterministic root tie-break test, and an
  extended causal-view mutation test.
- `work/T14/evaluate.py` — loads `data/ref`, calls `analyze_taint`, reads labels
  only afterwards, and prints the corpus, feature distributions, gate and cap
  tables, and the pass-bar check.

Isolation: I read `POLICY.md`, the T14 brief, `docs/vision/lab/COMBOS.md`
sections 1 and 2, `work/T03/REPORT.md`, the schema, `og_s1/checks.py`, the T03
helpers, and `data/ref/`. I did not open `work/T02*`, `work/T06` or
`data/heldout*`. I ran no git command, wrote no secret, and wrote only
`og_s1/taint.py` plus files under `work/T14/`.

## 2. How to re-run (one command)

```
bash research/system_one/work/T14/run.sh
```

From inside `research/system_one/work/T14/`, `bash run.sh` is equivalent. The
script removes the task folder's `__pycache__`, exports
`PYTHONDONTWRITEBYTECODE=1` so no cache with an absolute path is written, runs
T03's test file, the T14 test file, and `evaluate.py`, and appends a
timestamp-labelled capture block to `work/T14/check.log`. Every *measured*
result below is from the round-3 capture, headed
**`captured run 20261119T090652Z`**, in the append-only `check.log`. A reviewer
rerun appends another block at the end and preserves all earlier ones; the
deterministic corpus, feature, gate and cap numbers are identical across
successful blocks (checked with `diff` between the round-2 and round-3
captures; only the pytest timings and the T14 test count changed).
The development anecdote in Section 4 is an unlogged earlier local run, not a
reported measurement.

## 3. Results

### Tests

- T03 regression tests: **36 passed**.
- T14 taint tests: **23 passed**, including the property test over **10,000**
  random graphs.
- The property test asserts, for every edge in every random graph,
  `trust[child] <= base[child]` and `trust[child] <= trust[parent]`; by
  transitivity trust never rises along any chain.
- A round-3 regression test builds an in-band action with no claims that cites
  one trust-1 external note: `permission_excess=0.0`,
  `decisive_kind="none"`, `taint_decisive_support=0.0`, and `hold=False`. This
  pins the removal of the old undocumented "first cited note" gate branch.
- The root-semantics tests assert the actual root node ids: the missing
  `doc:d404` stub (not the claim that cites it), an `owner_signed` note with
  `signature_valid=False` (trust 0), and an agent note (trust 2, not an
  untrusted root).
- The causal-view test mutates every future document, every future note
  (including the current step's `new_notes`, which are written after the
  action), a later action's claims, notional, cited notes and thesis, every
  label, the whole `meta` and every final thesis status, and asserts that all
  earlier taint rows, gate decisions and root-cap flags are unchanged.
- A source guard test asserts that `og_s1.taint` has no `model_view` global and
  no `model_view(` call once `model_view_at(` is removed. The features therefore
  read only `model_view_at`.

### Corpus

- **3200 episodes**, **384000 actions**, **79023 positives**.
- Per shift setting: **1600 episodes**, **192000 actions**; **40457**
  positives clean and **38566** shifted.

### Feature distributions per cause family (unshifted means)

| Family | claim tainted share | decisive claim | decisive support | chain proximity | authority untraced | untrusted roots |
|---|---|---:|---:|---:|---:|---:|
| clean | 0.0425 | 0.0000 | 0.0000 | 0.0220 | 0.0000 | 0.0738 |
| drift | 0.1133 | 0.0000 | 0.0000 | 0.0585 | 0.0000 | 0.1978 |
| unsupported_claim | 0.0957 | 0.0000 | 0.0000 | 0.0991 | 0.0000 | 0.2459 |
| misquote | 0.0593 | 0.0000 | 0.0000 | 0.0423 | 0.0000 | 0.1385 |
| vague_hype | 0.1282 | 0.0000 | 0.0000 | 0.1521 | 0.0000 | 0.3437 |
| poisoned_note | 0.1201 | 0.0000 | 0.2604 | 0.1622 | 0.2604 | 0.4774 |
| authority_spoof | 0.1174 | 0.0000 | 0.2599 | 0.0646 | 0.2599 | 0.4736 |
| stale_thesis | 0.0410 | 0.0000 | 0.0000 | 0.0213 | 0.0000 | 0.0707 |

The shifted table is the same for every family except `drift`
(`claim tainted share` **0.0892**, `chain proximity` **0.0467**, `untrusted
roots` **0.1586**); the full distribution table, including p50, p90,
p99 and the non-zero share, is printed by `run.sh` and in `check.log`.

`taint_decisive_claim` is **0.0000** on every reference family: the reference
world opens its theses on tier-2 or tier-3 documents, so the thesis-evidence
claim is never tainted. The feature is exercised by a synthetic test in which
the thesis evidence is a tier-0 social document, where it becomes **1.0** and
the gate holds. This is a property of this reference generator, not a claim
that a decisive claim can never be tainted.

### Gate on clean reference episodes (pass bar)

| Clean set | Actions | Holds | Hold rate |
|---|---:|---:|---:|
| clean | 24000 | 0 | 0.0000 |
| clean.shifted | 24000 | 0 | 0.0000 |
| pooled | 48000 | 0 | 0.0000 |

The pooled clean hold rate is **0.0000** against the **0.0200** bar:
`PASS`.

### Gate recall per family

| Family | Positives | Holds | Hold rate on all family actions | Recall |
|---|---:|---:|---:|---:|
| clean | 0 | 0 | 0.0000 | n/a |
| drift | 5518 | 0 | 0.0000 | 0.0000 |
| unsupported_claim | 6708 | 0 | 0.0000 | 0.0000 |
| misquote | 6626 | 0 | 0.0000 | 0.0000 |
| vague_hype | 6581 | 0 | 0.0000 | 0.0000 |
| poisoned_note | 6250 | 6111 | 0.2546 | 0.9778 |
| authority_spoof | 6238 | 6116 | 0.2548 | 0.9804 |
| stale_thesis | 2536 | 0 | 0.0000 | 0.0000 |

The shifted gate table is identical for these families except that `drift` has
**3627** positives and still **0** holds. The gate is deliberately a structural
hold for untrusted decisive support (a tainted decisive claim or a non-owner
authority note on a permission action), not a general cause detector; T03's
structural features cover the other five causes.

### Single-root-source cap (default all-root grouping)

| Family | Actions | Flags | Flag rate | False-positive rate on negatives | Recall on positives |
|---|---:|---:|---:|---:|---:|
| clean | 24000 | 937 | 0.0390 | 0.0390 | n/a |
| drift | 24000 | 8405 | 0.3502 | 0.1919 | 0.8804 |
| unsupported_claim | 24000 | 1000 | 0.0417 | 0.0552 | 0.0069 |
| misquote | 24000 | 894 | 0.0372 | 0.0492 | 0.0060 |
| vague_hype | 24000 | 795 | 0.0331 | 0.0441 | 0.0041 |
| poisoned_note | 24000 | 10735 | 0.4473 | 0.2758 | 0.9344 |
| authority_spoof | 24000 | 11019 | 0.4591 | 0.2858 | 0.9527 |
| stale_thesis | 24000 | 864 | 0.0360 | 0.0383 | 0.0170 |

Shifted all-root numbers are the same except `drift`: **5430** flags, flag
rate **0.2263**, false-positive rate **0.1405**, recall **0.7080**.

The all-root default is deliberately broad and is **noisy on this reference
world**: ordinary clean thesis evidence is one document reused by many actions,
so **937 / 24000 = 3.90%** of clean actions are flagged even though the cap is
not a hold. This is the honest consequence of the brief's "root documents"
wording; the cap surfaces concentration, not guilt. Section 5.5 records the
measured split between trusted-document and untrusted-root thresholds.

For comparison, the previous untrusted-only mode (config
`root_cap_include_trusted=False`) remains available:

| Family | Shift | Actions | All-root flags | All-root rate | Untrusted-only flags | Untrusted-only rate |
|---|---|---:|---:|---:|---:|---:|
| clean | clean | 24000 | 937 | 0.0390 | 8 | 0.0003 |
| drift | clean | 24000 | 8405 | 0.3502 | 1933 | 0.0805 |
| clean | shifted | 24000 | 937 | 0.0390 | 8 | 0.0003 |
| drift | shifted | 24000 | 5430 | 0.2263 | 1009 | 0.0420 |

The untrusted-only mode keeps the old low clean rate but cannot see a
compromised high-trust document, which is why it is no longer the default.

### Pass-bar summary

- Property test over **10,000** random graphs: `PASS` (pytest).
- Features read only `model_view_at`: `PASS` (source guard test).
- Gate clean hold rate **0.0000** ≤ **0.0200**: `PASS`.
- All T03 tests pass: **36 passed**: `PASS`.
- T14 taint tests pass: **23 passed**: `PASS`.
- `run.sh` prints
  `OVERALL: PASS (both pytest suites and the gate exited 0)` and then the
  end-of-capture marker `== end captured run <id> ==`, and exits 0. The
  `OVERALL` line is printed only after both pytest suites and `evaluate.py`
  exit 0 under `set -e`.

The brief does not ask for confidence intervals; all corpus and feature numbers
are deterministic point estimates. Wall-clock timings are not part of the T14
pass bar, so none are quoted.

## 4. What did not work

- **An intermediate root-cap test failed and the log still shows it.**
  `check.log` contains a failed intermediate run (`20261119T073438Z`) of
  `test_root_cap_flags_a_repeated_untrusted_note` with
  `assert 'doc:d3' == 'note:n-ext'`: in the default all-root mode the untrusted
  note and the trusted thesis document were both candidates, and the old
  `max(..., key=(count, exposure_fraction))` had no tie-break, so the reported
  root could change. I made the root id the final key, added
  `test_root_cap_reports_a_deterministic_root_under_ties`, and added a default
  all-root test for the repeated untrusted note. `check.log` is append-only and
  still contains that failed block plus a duplicated `20261119T075137Z` block (a
  runner/tee artifact); the successful blocks reproduce the numbers below.
- **The gate briefly had an undocumented third branch.** An action with no
  decisive claim that cited a tainted note was held on the *first* cited note.
  That widened the brief's decisive-claim gate without a measurement. I removed
  the branch and added a regression test; the reference gate numbers are
  unchanged because the poisoned-note and spoof recall comes from the permission
  path.
- **Treating every claim as a possible decisive claim was too loose.** A first
  version selected the largest-magnitude claim whenever no thesis-evidence claim
  matched, and it held ordinary clean sells whose claims came from tier-0 or
  tier-1 sector facts. That exceeded the 2% clean bar in an unlogged early
  development run. The fix
  was to make a claim decisive only when it restates the action thesis's own
  evidence; a rebalance sell whose claims are unrelated sector facts has no
  decisive claim. The captured run now holds **0** of **48000** clean actions.
- **Trusting an agent-written authority note as agent-trusted missed the
  authority spoof.** The reference authority-spoof note is `written_by=agent`
  with no valid owner signature, so a rule that only treated external/tool
  notes as untrusted gave low spoof recall. The fix separates informational
  agent trust from authority: when an action needs a permission, any cited note
  that is not a valid owner-signed note is an untraced authority assertion. The
  first version of that rule fired on any non-owner note even when the action
  was in band and needed no permission; a test now pins the narrower rule, and
  the reference numbers are unchanged. The captured spoof recall is **0.9804**.
- **The same problem initially weakened the root cap on spoofs.** A spoof note
  written by the agent was not an untrusted source root, so the cap did not
  group spoof actions by it. The cap now adds non-owner authority notes as root
  sources when the action has a permission excess. The captured spoof cap recall
  is **0.9527** in the default all-root mode.
- **The gate does not catch unsupported_claim, misquote, vague_hype, drift or
  stale_thesis.** Their bad claim is not the action's decisive thesis-evidence
  claim, and they have no untraced authority note. Their captured gate recalls
  are all **0.0000**. That is the honest result: T03's structural checks, not
  this narrow taint gate, are the layer for those causes. The taint features
  still vary across those families (for example `taint_claim_tainted_share` is
  **0.0957** for unsupported_claim and **0.1282** for vague_hype, against
  **0.0425** for clean).
- **`taint_decisive_claim` is constant zero on the reference corpora.** The
  reference world always opens theses on tier-2/3 evidence, so a thesis-evidence
  claim is not tainted. This is a limitation of the reference data, not a proof
  that the feature is useless; the synthetic low-trust-thesis test pins its
  behaviour.
- **The default all-root cap is noisy on ordinary reuse.** The captured clean
  flag rate is **937 / 24000 = 0.0390**, and clean drift negatives are flagged
  at **0.1919** (shifted drift **0.1405**), because one thesis-evidence document
  is normally cited by many actions. Raising the trusted-document thresholds
  reduces this but also hides smaller swarms; the report keeps the measured rate
  rather than tuning it away. The untrusted-only mode still flags only
  **8 / 24000 = 0.0003** clean actions and flags **0.0805** of clean / **0.0420**
  of shifted drift actions, but it cannot see a high-trust root. The cap is a monitor
  that raises a signal; it does not hold actions.

## 5. Judgement calls

### 5.1 Ordinal min-propagation versus learned or probabilistic trust

- **Choice:** ordinal trust labels and a min-plus propagation to the least fixed
  point.
- **Alternatives:** (a) a learned probabilistic trust model over source features;
  (b) Bayesian reputation updating per publisher; (c) a text classifier that
  predicts "trusted" from note prose; (d) a simple allowlist of publishers.
- **Why it wins on this project's criteria:** it has exact, auditable semantics
  and a provable monotonicity property, so an adaptive attacker cannot talk a
  high-trust label into existence without a valid owner signature or a high-tier
  source. It needs no training data, adds no model weights or inference cost, is
  deterministic and debuggable, and is invariant to wording. A learned model
  would need labels for source trust, would be attackable through the same text
  channel, and could not give the "never rises" guarantee.
- **What evidence would flip it:** if held-out worlds show that trust depends on
  features the ordinal rules cannot express (for example a forged signature that
  the schema marks valid), add a calibrated reliability term beside the
  structural labels. Do not replace the min-propagation, which is the part with
  the exact guarantee.

### 5.2 The trust scale and the threshold at 2

- **Choice:** documents use their tier directly (0..3), owner-signed notes are 4,
  agent notes/claims are 2, tool/external notes are 1, unsourced or invisible
  support is 0, and a node is untrusted when trust is below 2.
- **Alternatives:** (a) use only `trust_tier`, ignoring writer and signature;
  (b) use only the signature bit; (c) map every source to a continuous
  probability; (d) set the threshold at 3 so tier-2 analyst/tool-output
  documents are also untrusted.
- **Why it wins:** the schema already gives a meaningful tier ordering; the
  writer/signature fields are the only structured evidence of owner authority.
  Threshold 2 keeps tier-2 analyst and tool-output documents, agent notes and
  agent claims usable as ordinary evidence, while tier-0/1 documents,
  tool/external notes and owner-signed notes with an invalid signature are
  untrusted. Agent notes are *not* in that untrusted list: they are trust 2, at
  the boundary, and count as trusted for informational purposes. They are still
  untrusted for *authority* on a permission action, which is a separate rule
  (Section 5.7). Setting the threshold at 3 would make most ordinary claims
  tainted and would make the gate too noisy; ignoring writer/signature would
  treat an unsigned external note as a filing.
- **What evidence would flip it:** held-out data in which tier-2 sources are
  routinely wrong or in which a signed owner note is not authoritative. The
  threshold and the writer table are config values in `DEFAULT_CONFIG`, so a
  ruling is a one-line change.

### 5.3 Decisive claim means the thesis-evidence claim

- **Choice:** the decisive claim is the claim whose source document is one of
  the action thesis's `evidence_docs`; among those, the largest `|value|` wins.
  If no claim restates the thesis evidence, there is no decisive claim.
- **Alternatives:** (a) the largest-magnitude claim among all claims; (b) the
  first claim; (c) the claim whose value is closest to the action notional;
  (d) a learned attribution model trained on labels; (e) read the rationale text
  to see which claim the agent says decided it.
- **Why it wins:** the thesis is the action's why-anchor and `evidence_docs` is
  the only structured link from an action to its deciding evidence. The
  all-claims magnitude rule selected unrelated low-trust sector facts on ordinary
  sells and broke the clean gate bar; the first-claim rule is arbitrary. It
  needs no labels and no prose parsing. The reference generator's clean actions
  show the intended shape: thesis-evidence claims are tier 2/3, while unrelated
  sector facts can be tier 0/1.
- **What evidence would flip it:** a schema field that records the deciding fact
  or the planted cause's claim, or held-out evidence that agents routinely make
  decisions from claims outside the thesis evidence. If the schema adds an
  effect field, use it directly; until then, the structural thesis link is the
  least arbitrary available choice.

### 5.4 The gate uses decisive support, including an authority note

- **Choice:** hold when the decisive support is non-zero and notional exceeds
  `max($1, 0.5% of book value)`. "Decisive support" is not always "a tainted
  claim", and the report does not call it that:
  - if the action has a permission excess and cites at least one note that is
    not a valid owner-signed note, the decisive support is that authority note
    and the value is **1**, even when the note's informational trust is 2 (an
    agent note). This is untrusted *authority*, not a taint below the
    threshold;
  - otherwise, if the action has a decisive claim, the decisive support is that
    claim and the value is **1** exactly when the claim's propagated trust is
    below the threshold;
  - otherwise (no permission need and no decisive claim) there is no decisive
    support and the value is **0**. In particular, a tainted note cited only
    for information is not decisive. Round 3 removed an earlier undocumented
    fallback that used the first cited note in this case.
- **Alternatives:** (a) gate only on claims, ignoring notes; (b) gate only on
  buys; (c) gate on a model score above a threshold; (d) gate on every tainted
  claim share above a threshold; (e) hold everything with any untrusted root.
- **Why it wins:** a permission grant cannot live in a factual claim; in this
  schema it lives in a note. Ignoring notes would miss every poisoned-note and
  authority-spoof action. A model-score gate would be attacked through the model
  channel and would not be deterministic. A claim-share gate would hold ordinary
  clean actions that happen to cite one tier-0 sector fact. The notional
  threshold is small relative to book value (0.5%) but still excludes tiny
  trades; the `$1` floor prevents a zero threshold on a tiny book.
- **What evidence would flip it:** if a held-out attack produces a bad action
  through a tainted claim that is not a thesis-evidence claim, the decisive-claim
  definition must widen. If legitimate owner-authorised actions cite agent notes
  while exceeding a band, the authority-note rule needs a signature or delegation
  field. The gate is deliberately hold-only, so a widening is safe for the
  parent system.

### 5.5 The single-root-source cap and its defaults

- **Choice:** a causal window of 20 actions. The default groups all root
  **documents** (trusted or not) plus untrusted non-document sources and
  non-owner authority notes, as the brief asks. Untrusted roots use 4 recent
  actions or 10% of book value; trusted document roots use 12 of 20 actions or
  25% of book value. `root_cap_include_trusted=False` restores the
  untrusted-only mode. A trusted note is not a root: a trusted note that cites
  a document is not a root (the document is), and a trusted note with no
  document is not a cap root either. Only a non-owner authority note on a
  permission action is grouped as a note.
- **Alternatives:** (a) group only untrusted taint roots, as in round 1; (b)
  group all roots with one shared threshold; (c) a count-only or exposure-only
  monitor; (d) an EWMA or statistical anomaly detector per source; (e) group by
  thesis instead of source.
- **Why it wins:** grouping only taint roots silently narrows the brief and
  makes a compromised trusted filing invisible, which is exactly the adaptive
  attacker the brief is about. One shared threshold is also wrong in this
  world: four actions on a rare untrusted note is a strong signal, while four
  actions on a normally reused thesis filing is ordinary. The split thresholds
  keep the untrusted monitor sensitive and make the trusted-document monitor a
  concentration alert. A 20-action window is one sixth of a 120-step episode;
  12 of 20 and 25% of book value are the measured concentration points that
  keep the all-root flag rate from swallowing every action. The report records
  the measured rates rather than hiding them. Trusted notes are excluded on
  purpose: the reference owner-mandate note `n0` has no cited document and is
  cited by almost every clean action, so making it a root would flag nearly
  the whole clean corpus and the monitor would lose its signal.
- **What evidence would flip it:** held-out worlds with different reuse patterns
  would need a data-driven baseline per source, not fixed counts. If a held-out
  attack concentrates on one trusted note rather than on a document, the cap
  would miss it (a valid owner-signed note is never a root; an agent note is a
  root only as a non-owner authority note). That would argue for adding trusted
  notes as roots with per-kind thresholds. If the lead rules that the cap is
  only a taint monitor, the untrusted-only mode becomes the deployment default.
  A compromised high-trust document is now grouped, but it is indistinguishable
  from ordinary heavy reuse without an integrity signal (for example a
  signature failure or source anomaly), so this cap raises a signal rather than
  proving compromise.

### 5.6 A separate `og_s1/taint.py` rather than extending `og_s1/checks.py`

- **Choice:** add a new module for the taint graph, gate and cap.
- **Alternatives:** (a) add the six features to `checks.FEATURE_NAMES` and
  extend `featurize`; (b) put taint in a work-folder-only script; (c) replace
  the checks layer with one combined graph featuriser.
- **Why it wins:** T03's tests assert its exact 41-feature shape and cause-group
  set; adding a seventh group to `checks.py` would change that contract and
  force T03's tests to change, which the brief forbids. A work-folder-only
  script would not be reusable by the rest of System One. A separate module
  keeps T03 stable, lets the taint layer be tested against random graphs, and
  makes the gate and cap first-class functions.
- **What evidence would flip it:** if the scorer wants one feature matrix, add a
  thin join function that concatenates T03's `featurize` output with
  `featurize_taint`; do not merge the internals. If T03 itself is superseded,
  merge the modules then.

### 5.7 The authority feature is signature-based, not prose-based

- **Choice:** `taint_authority_untraced` is evaluated only when the action has
  a permission excess; in that case it is 1 when any cited note is not a valid
  owner-signed note, or when no cited note is validly owner-signed. An in-band
  action citing a non-owner informational note is 0.
- **Alternatives:** (a) a text classifier for "the owner widened the band";
  (b) only external/tool notes; (c) only signed documents; (d) use the note's
  trust tier after propagation; (e) flag any non-owner note regardless of
  whether the action needs a permission.
- **Why it wins:** the schema's only structured evidence of owner authority is
  `written_by=owner_signed` plus `signature_valid`. Agent-written spoof notes
  are the reference world's authority-spoof vector, so restricting the rule to
  external/tool notes misses them. Parsing note prose would be a wording
  dependency and would break under paraphrase. Requiring a permission excess
  keeps an ordinary agent note cited for information from being mistaken for an
  authority claim.
- **What evidence would flip it:** if held-out worlds forge `signature_valid` on
  a non-owner note, or add delegation records, the rule must check the signing
  key or delegation, not just the boolean.

### 5.8 No new dependencies

- **Choice:** standard library plus `numpy`, and `pytest` for tests, all already
  used by the repository.
- **Alternatives:** `networkx` for graph propagation; `scipy` for graph
  algorithms; a DataFrame/pandas pipeline for distributions.
- **Why it wins:** the propagation is a short min-fixed-point loop; a graph
  library would add a dependency and obscure the exact monotonicity property.
  `numpy` is already used by T03, and `pytest` is the repository's test runner,
  so the T14 tests sit beside the existing suite with no new install.
- **What evidence would flip it:** if the why graph grows to millions of nodes,
  replace the dict scan with a topological or sparse-matrix relaxation and prove
  equivalence on the existing property test.

## 6. Loopholes I checked

- **Future documents do not change earlier rows.** The causal-view test mutates
  every future document's text, facts, trust tier and kind, and appends a future
  document; earlier rows are unchanged.
- **Future notes do not change earlier rows.** Future `pre_notes` and
  `new_notes` are rewritten to external, unsigned, tier-0-citing notes, the
  current step's `new_notes` (written after its action) are rewritten and
  extended, a later action's claims, notional, cited notes and thesis are
  replaced, and new future notes are appended; earlier rows are unchanged.
- **Labels and `meta` are not read.** The same test replaces every label and the
  whole `meta`; earlier rows are unchanged. `evaluate.py` reads labels only
  after `analyze_taint`.
- **Final thesis status is not read.** The same test sets every final thesis to
  `invalidated`; earlier rows are unchanged. `model_view_at` strips `status`.
- **No whole-episode `model_view`.** A source guard asserts the module has no
  `model_view` global and no `model_view(` call after removing `model_view_at(`.
- **Trust never rises.** The property test checks every edge of **10,000**
  random graphs, with random base levels in the same `[0, 4]` scale and random
  directed edges, including cycles. The deterministic chain test checks
  document -> note -> claim -> action.
- **Roots are what the code says they are.** A claim citing a missing document
  is an internal node that inherits trust 0; the missing **document** stub
  (`doc:<id>`) is the trust-0 root, not the claim. A missing thesis stub is a
  trust-0 root and an empty thesis is a trust-1 root. An external or tool note
  with no document is a trust-1 untrusted root. An `owner_signed` note whose
  `signature_valid` is false is a trust-0 untrusted root, so a missing note is
  not the only trust-0 note. An agent note with no document has trust 2, so it
  is not an untrusted taint root and is **not** an all-root cap root; it is
  grouped only when it is a non-owner authority note on a permission action.
  Round-3 tests assert the exact root node ids for the missing document, the
  invalid owner note and the agent note. A trusted note that merely passes
  through a document is not a root (the document is), but an external note that
  cites a trusted document is still an untrusted root because its own writer
  trust is 1.
- **The all-root cap groups trusted documents, not trusted notes.** The default
  mode's cap candidates are every sensitive (untrusted) root, every trusted
  **document** root, and non-owner authority notes on permission actions. A
  valid owner-signed note and an agent note with no document are not roots; a
  round-3 test cites the same owner/agent note from six clean actions and shows
  that none of them becomes the reported root or flags.
- **Owner authority needs a valid signature.** An agent-written unsigned note
  that asserts a permission is flagged as untraced; a valid owner-signed note is
  not, and a non-owner note cited on an in-band action without a permission need
  does not set the feature; both tested.
- **Clean gate is silent on the reference world.** The captured run holds **0**
  of **24000** clean actions and **0** of **24000** clean.shifted actions.
- **The removed gate branch is not reachable.** A round-3 test builds an in-band
  action with no claims that cites one trust-1 external note and asserts
  `decisive_kind="none"`, `taint_decisive_support=0.0` and `hold=False`.
- **Root cap is causal.** It only counts actions already seen inside the
  window; the future is never used. In the default all-root mode the clean flag
  rate is **937 / 24000 = 0.0390**; the untrusted-only mode is
  **8 / 24000 = 0.0003**.
- **The cap groups trusted root documents.** A test with one tier-3 document
  cited by five actions shows the trusted document as the reported root; the
  previous code reported no root. A normal thesis filing is therefore no longer
  invisible to the cap.
- **Feature determinism and shape.** The test suite checks the six names, the
  group map, determinism across two calls, finite non-negative values, and the
  empty-episode shape.
- **No wording logic.** The module reads trust tiers, writers, signatures,
  citations, times, facts, values and notional; it never reads document, note or
  claim prose. The only text-like field used is `written_by`, a structured enum.
- **No test-set peeking.** `data/ref` is the only corpus read; `work/T02*`,
  `work/T06` and `data/heldout*` were not opened. Labels are read only in the
  evaluator after featurisation.
- **No git, no secrets, no absolute paths in source or logs.** No git command
  was run; the source, report, tests and logs contain no key, token, email or
  absolute home path. Generated `.pyc` caches did embed an absolute source path
  in round 1; they were removed and `run.sh` now exports
  `PYTHONDONTWRITEBYTECODE=1` and clears the task `__pycache__` before running.
- **Disk.** No data was copied; every file in the task folder is well under the
  5 MB limit.
- **T03 contract is untouched.** `og_s1/checks.py` was not edited; its **36**
  tests pass unchanged.

## 7. Open risks

- **Reference-only design.** The trust table and the decisive-claim definition
  were designed against `data/ref`. Held-out authors may use different note
  writers, a note that cites another note, or a thesis whose evidence is not the
  claim that decides the action. The `work/T02*` and `work/T06` worlds are the
  real test.
- **A compromised high-trust source is grouped but not distinguishable.** The
  all-root cap now groups a tier-3 filing (and, on a permission action, a
  non-owner authority note), but normal thesis evidence is reused so heavily
  that a compromised high-trust source looks like ordinary concentration. A
  valid owner-signed note is **not** a root, so an attack concentrated on one
  trusted note is invisible to this cap. The cap raises a signal; proving
  compromise needs an integrity signal outside provenance (for example a
  signature failure or a source anomaly detector).
- **The gate is narrow.** It catches the reference poisoned-note and
  authority-spoof vectors with high recall, but it has **0.0000** recall on
  unsupported_claim, misquote, vague_hype, drift and stale_thesis. Those causes
  remain with T03 and the text channel. A bad action whose bad claim is not a
  thesis-evidence claim will pass this gate unless it also needs a permission
  and cites a non-owner note.
- **The decisive-claim definition is a proxy.** The schema has no effect field,
  so "largest effect on size or direction" is approximated by the
  thesis-evidence link and then by numeric magnitude. A held-out agent that
  decides on a claim outside its thesis evidence would be mis-ranked.
- **The default all-root cap is noisy.** Clean actions are flagged at
  **0.0390**, and clean drift negatives at **0.1919** clean / **0.1405**
  shifted, because the reference world reuses one thesis-evidence document many
  times. The cap is a monitor, not a hold, but a deployment would need a
  per-source baseline or a different alert budget; the untrusted-only mode is
  much quieter but blind to trusted roots.
- **A benign non-owner note can look like an authority claim.** When an action
  exceeds a permission and cites an agent/tool/external note for information,
  `taint_authority_untraced` and the gate fire even if the note says nothing
  about authority. The schema does not label which note grants a permission, so
  the rule is deliberately conservative; the reference clean families cite only
  the owner note, giving a **0.0000** feature mean there.
- **The cap groups untrusted non-document roots as well as root documents.**
  The default follows the brief's "root documents", but the reference
  poisoned/spoof notes are roots with no cited document. Restricting the
  all-root pass to documents would make those vectors ungroupable, so untrusted
  notes, unsourced claims and missing/empty thesis stubs also count as roots.
  A trusted note that only passes through a document is not a root; the
  document beneath it is, and a trusted note with no document is not a root at
  all (except a non-owner authority note on a permission action). An external
  note that cites a trusted document is still an untrusted root because of its
  own writer trust.
- **Trust is an ordinal judgment, not a calibrated probability.** The levels 4,
  3, 2, 1 and 0 are hand-set from schema fields. They are not learned or
  calibrated, and a different owner or source taxonomy could need a remap.
- **Claims cannot cite notes in this schema.** The graph has note -> document and
  claim -> document edges but no claim -> note edge. If held-out authors let a
  claim rest on a note, the propagation needs that edge; otherwise a claim that
  summarises a poisoned note would not inherit the note's trust.
- **The root cap's window is action-based, not time-based.** A held-out world
  with long gaps between actions or many same-time actions would need a time
  window or an explicit clock.
- **Notional is the only exposure measure.** The cap sums action notional; it
  does not compute mark-to-market exposure or net exposure after sells. The
  schema has no price moves, so this is consistent with the current world but
  not a general portfolio-risk measure.
- **No confidence intervals.** The brief does not ask for them; the reported
  rates are deterministic point estimates over the full reference corpus.

## Round 2 changes

I addressed the five required fixes in `REVIEW.md` in order.

1. **All-root cap.** The default now groups every root document (trusted or
   not), plus untrusted non-document sources and non-owner authority notes.
   `root_cap_include_trusted=False` keeps the old untrusted-only mode. I added
   `root_cap_all_root_min_actions=12` and
   `root_cap_all_root_max_exposure_fraction=0.25` so the trusted-document pass
   is a concentration alert rather than a flood; untrusted roots keep the
   sensitive 4-action / 10% thresholds. The report now gives the measured
   all-root and untrusted-only clean/drift rates, and a test covers a trusted
   tier-3 document cited by five actions.
2. **Root semantics and report claims.** `_untrusted_roots` now includes
   `THESIS`, so a missing or empty thesis stub is counted as an untrusted root
   consistently with `shortest_chain_length`. I added tests for an agent note
   with no documents, an external note with no documents, and a missing and an
   empty thesis. I corrected the three overbroad report claims: a note with no
   documents is not always trust 0 (agent is 2, external/tool is 1, missing is
   0); a missing thesis is now a root; and a note pass-through is not a root
   only when the note itself is trusted, while an external note remains an
   untrusted root because of its own writer trust.
3. **Causal-view test.** The test now mutates the current step's `new_notes`
   and a later action's claims, notional, cited notes and thesis, in addition to
   future documents, future steps' notes, labels, `meta` and final thesis
   status. The report's claim now matches the test.
4. **Absolute paths in caches.** I removed the generated `__pycache__` files
   from the task folder and the `og_s1/taint` bytecode cache, set
   `PYTHONDONTWRITEBYTECODE=1` in `run.sh`, and made `run.sh` clear the task
   `__pycache__` before running. The report now limits the claim to source and
   logs and records the cache fix.
5. **Computed pass-bar lines.** I removed the three hard-coded "covered by
   pytest" lines from `evaluate.py`. `run.sh` runs both pytest suites first
   under `set -e` and prints the final `OVERALL: PASS` line only after both
   suites and the gate exit 0; `evaluate.py` now prints only the computed gate
   status. I also scoped the "every number" sentence to measured results and
   labelled the development anecdote as an unlogged early run.

I did **not** change the brief's gate, the six feature names, the decisive-claim
definition, the trust scale or T03's `checks.py`. The all-root cap is noisier
than the untrusted-only monitor; that is measured and reported rather than
tuned away, because the brief asks for root documents and a compromised trusted
source must not be silently invisible.

## Round 3 changes

`SOL_ADVICE.md` was absent, so I worked only from `REVIEW.md`. I addressed its
six required fixes in order.

1. **Removed the gate's undocumented no-decisive-claim branch.** The old
   `elif cited_note_nodes:` in `analyze_taint` held an action on its first
   cited note when it had no decisive claim. The brief's gate is the decisive
   claim, so I removed the branch entirely rather than documenting a wider
   gate. `decisive_support` is now non-zero only on (i) a permission action
   citing a non-owner authority note or (ii) a tainted decisive claim. I added
   `test_gate_does_not_hold_on_a_tainted_informational_note_without_a_decisive_claim`,
   which reproduces the review's in-band 20000-notional example and asserts
   `hold=False`. The reference gate numbers are unchanged because all reference
   poisoned-note and spoof holds come through the permission path (checked by
   re-running `evaluate.py`).
2. **Corrected the cap-coverage claims.** The all-root mode groups trusted
   **documents**, not trusted notes. I chose to correct the report rather than
   add trusted notes as roots: the reference owner-mandate note `n0` has no
   cited document and is cited by almost every clean action, so making trusted
   notes roots would flag nearly the whole clean corpus and destroy the
   monitor. Sections 1, 5.5, 6 and 7 now say this explicitly, and
   `test_all_root_cap_does_not_group_a_trusted_note_as_a_root` pins it.
3. **Corrected the root-semantics claims and pinned them.** Section 6 now says
   a claim citing a missing document is an internal node whose root is the
   missing `doc:` stub, and that an invalid `owner_signed` note is also trust 0
   (a missing note is not the only trust-0 note).
   `test_root_ids_pin_the_real_source_not_the_internal_node` asserts the exact
   root ids for a missing document, an invalid owner note and an agent note.
4. **Clarified `taint_decisive_support`.** Sections 1 and 5.4 now spell out its
   two non-zero cases: a non-owner authority note on a permission action
   (untrusted authority, even at agent trust 2) and a decisive claim below the
   trust threshold; with no decisive support the value is 0. I kept the feature
   name because the fix is semantic clarity, not a new signal.
5. **Corrected the threshold sentence.** Section 5.2 no longer says "non-owner
   notes are untrusted"; it distinguishes tier-0/1 documents, tool/external
   notes and invalid owner signatures (untrusted) from agent notes and claims
   (trust 2, trusted for information, separately untrusted for authority).
6. **Test/log honesty and determinism.** The root selection now uses the root
   id as a final `max` key, so equal `(count, exposure_fraction)` ties are
   deterministic. I added a default all-root test for a repeated untrusted note
   (the old test was narrowed to `root_cap_include_trusted=False`), a
   deterministic tie-break test, and Section 4 records the failed intermediate
   run `20261119T073438Z` and the duplicated block in `check.log`. Section 3
   now says `run.sh` prints `OVERALL` and then the `== end captured run ==`
   marker before exiting 0; Section 2's capture id is the round-3 run.

I did **not** change the six feature names, the decisive-claim definition, the
trust scale, the cap's config defaults, T03's `checks.py`, or `run.sh`'s
structure. The round-3 reference numbers are identical to round 2 because the
removed gate branch never fired on `data/ref`; only the T14 test count changed
(18 to 23).
