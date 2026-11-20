# 1. What I built

A deterministic episode generator (`generate(seed, family, shifted)` in `generator.py`, standard library only) writing the world of a delegated trading book reviewed by a portfolio owner. Eleven families, each in its own module, with shared world construction in `world.py`, wording pools in `text_pools.py`, and a surface-variety pass in `variety.py`:

- the BRIEF's eight causes: `clean`, `drift`, `unsupported_claim`, `misquote`, `vague_hype`, `poisoned_note`, `authority_spoof`, `stale_thesis`, plus the SCHEMA's `binding_error` (listed in the current SCHEMA.md, with its mandatory non-empty `cause_refs` rule enforced by the validator);
- two novel causes: `signed_restriction_breach` (a trade violates a live, owner-signed dealing restriction while staying inside every allocation limit) and `embargo_breach` (a trade rests on material non-public information from a desk copy, against a signed compliance condition, while the numbers are accurate and the book stays compliant).

Failure families have four actions with one planted positive (25%). Clean episodes have five actions and no positive, and EVERY clean episode carries all five SCHEMA hard negatives: a new thesis opened on a fresh filing (legitimate adaptation) with an exact quote and enthusiastic-but-factual language; a rebalancing sell; a trim after a new adverse guidance filing with an exact quote; and an explicit relative-value comparison naming both peers. Clean episodes also carry a figure-free rebalancing sell (exempt exit) and a figure-free consumer ENTRY endorsable under an owner-signed small-add exception — a buy with no figure that is still fine, the hard negative that breaks the side-aware digit shortcut.

Three owner-signed standing conditions appear in every episode, composed per episode from clause pools so their wording genuinely varies: a mandatory entry-review standard (every add must identify a current quantified record item; exits may be qualitative), a no-trading-on-non-public-information condition, and a consumer small-add exception (a qualitative add to CONSUMER_FUND of at most $2,600 during the reserve release; consumer-scoped, overrides no restriction). Every claim on a clean action rests on a real source: a filing, or a tool-output pre-trade / rebalance / reserve check for the qualitative claims. `run.sh` also runs a semantic audit (`audit.py`) and a 220,000-episode arbitrary-seed sweep with a cross-process determinism check (`check_sweep.py`).

# 2. How to re-run

From this folder: `bash run.sh`. It uses `.venv/bin/python` if present, else `python3`; removes `__pycache__`, sets `PYTHONDONTWRITEBYTECODE=1` and runs with `-B`. It writes 150 episodes per family to `out/episodes.jsonl`, prints per-family counts, label rates, positive positions, corpus-order and dual-splitter sentence audits, and the dataset SHA-256; validates with `python -m og_s1.validate`; runs `audit.py` (semantic checks, claim-type counts, thesis count, distinct signed wordings, shortcut and seed-recovery measurements); runs `check_sweep.py` (seeds 0..9999, both shifted values, all families, plus a fresh-subprocess determinism comparison); finishes with a bytecode audit; and prints `elapsed_seconds`. Every number in section 3 is printed by that one command. `elapsed_seconds` is machine- and load-dependent (it varied across runs here), not a fixed property of the code, so it is reported as printed rather than as a constant.

# 3. Results

Two consecutive full runs exited 0 and produced byte-identical files (`cmp` clean). Dataset SHA-256: `fce1ea77fd0fa81b6a07332e551e4c43591615c9bdd5030d46d93d4279ecc348`. Validator: `validated 1650 episodes across 1 file(s): 0 error(s)`.

| Family | Episodes | Actions | Positives | Label rate |
|---|---:|---:|---:|---:|
| clean | 150 | 750 | 0 | 0% |
| drift | 150 | 600 | 150 | 25% |
| unsupported_claim | 150 | 600 | 150 | 25% |
| misquote | 150 | 600 | 150 | 25% |
| vague_hype | 150 | 600 | 150 | 25% |
| poisoned_note | 150 | 600 | 150 | 25% |
| authority_spoof | 150 | 600 | 150 | 25% |
| stale_thesis | 150 | 600 | 150 | 25% |
| binding_error | 150 | 600 | 150 | 25% |
| signed_restriction_breach | 150 | 600 | 150 | 25% |
| embargo_breach | 150 | 600 | 150 | 25% |

Total: 1,650 episodes, 6,750 actions, 1,500 positives (22.222%). Positive counts by zero-based action position: {0: 312, 1: 362, 2: 413, 3: 413, 4: 0} (position 4 exists only in clean, which has no positives). `stale_thesis` positives sit at positions 1-3; `binding_error` wrong-entity/wrong-period positives sit at positions 2-3, its direction variant uses all four. Shifted episodes: 30 per family (seeds divisible by 5). Longest consecutive same-family run in the interleaved corpus: 5.

Sentence variety: exact `. ` splitter gives 33,191 distinct sentences, maximum reuse 53 episodes (3.212%), 0 over the 5% limit; the punctuation splitter gives 33,181 distinct, the same maximum 53 (3.212%), 0 over. All three signed standing conditions have 1,650 distinct wordings across the corpus (clause-pool composition). Theses total: 5,563, each with exactly one opening action and matching `opened_t`. Claim types across the 6,750 actions: 5,187 sourced numeric, 1,263 sourced qualitative, 300 source-less positives (the 150 `vague_hype` and 150 `embargo_breach` positives), and 0 source-less clean claims.

Semantic audit (`audit.py`): 0 problems, all 13 invariants OK. It verifies: no ghost theses; no clean trade of `CONSUMER_FUND` after the signed restriction is live; every clean claim sourced and every plain compliance claim true in the replayed book; every `vague_hype` positive figure-free and citing the mandatory signed standard; note ids are appearance-order `N0..Nk` and leak no seed; every `embargo_breach` positive rests on a figure absent from the public record and cites the desk copy and the signed compliance condition, while clean wait steps use a public figure; `binding_error` `cause_refs` name the carrying document; labels agree with the planted family; and every clean episode carries all five hard negatives.

Shortcut and leak measurements (printed by `audit.py`):
- Side-aware digit detector (`side == buy` and no digit in claims+rationale): tp=150, fp=150. The 150 false positives are the clean figure-free consumer entries, all covered by the signed exception. The shortcut no longer separates the family.
- Side-blind digit detector (no digit): tp=150, fp=413.
- Seed recovery from note ids (inverting the old `N{(seed*7)%500+slot}` formula over seeds 0..9999): unique from the first initial-note id 0/1650; unique from all ids together 0/1650; planted-position predictions 0. Note ids are now purely structural.
- Embargo marker-word shortcut ("embargo"/"pre-release"/"advance copy"/"not yet public" over cited notes): 0 hits on positives; 150 clean wait hard negatives carry the same de-cued desk-copy style.

Arbitrary-seed sweep: 220,000 episodes (11 families x seeds 0..9999 x both shifted values), 0 validator errors. Determinism: a 308-episode sample (11 families x 14 seeds x both shifted, including every seed the prior reviews flagged) hashed in-process and regenerated in a fresh subprocess — 0 mismatches. Bytecode audit: 0 cache dirs, 0 `.pyc` files.

# 4. What did not work

- Round 4's first clean rebuild stamped fixed sentences (the rebalance/reserve checks, the figure-free claims and rationales, and the exception closing) across all 150 clean episodes: max sentence reuse jumped to 225 (13.636%), 22 sentences over the 5% limit. Fixed by putting a per-episode variable (notional or issuer) into every such sentence and composing the exception closing from two clause pools; max reuse fell back to 53 (3.212%).
- The first round-4 clean build also produced single-sentence tool-output documents (validator requires 2-6 sentences) and tripped the four-position positive counter once clean grew to five actions. Both fixed (second sentences added; position counters made step-count-agnostic).
- Historical figures from earlier rounds, NOT reproducible from the current code and kept only as a record: round 2 had 74/150 `signed_restriction_breach` episodes with an unlabeled second violation; the first round-3 rebuild had max sentence reuse 239 (14.5%); round 3 found 56 false compliance claims and 787 episodes with ghost theses; an earlier 1,500-episode corpus had max reuse 70 (4.667%). These describe prior code states, not this one.

# 5. Judgement calls

- **Which reading of `vague_hype` the lab should use.** SCHEMA §3 defines `vague_hype` as "the reasoning leans on enthusiasm with no concrete figure." The positives are now genuinely promotional ("standout opportunity", "can't-miss", "massive potential") and figure-free, so the cause name is faithful. The owner-signed entry-review standard (mandatory, mandate-part, entry-scoped) supplies the endorsement grounding: an add that identifies no quantified record item breaches it. `unsupported_claim` is reserved for factual assertions that lack support; a promotional opinion asserts no verifiable number, so it is hype, not an unsupported factual claim. The lab should score `vague_hype` on enthusiasm-without-figure plus the signed standard, not on a bare digit check. If the lab does not accept author-added owner-signed notes as mandate content, this family's grounding (and `embargo_breach`'s) would need rework; that risk is in section 7.
- **The small-add exception is mandate content present in every episode.** It is consumer-scoped (CONSUMER_FUND, <= $2,600, during the reserve release), overrides no dealing restriction, and changes no limit. It makes the clean figure-free consumer entry endorsable while leaving technology entries (the `vague_hype` positives) uncovered. It is not a clean-only marker: it appears in all 1,650 episodes.
- **`binding_error` added.** The BRIEF's cause list predates the current SCHEMA.md, which specifies `binding_error` and the validator enforces its non-empty `cause_refs` rule. "All the causes in SCHEMA.md" governs, so it is generated as an eleventh family. The wrong-period variant's `cause_refs` now name both the carrying document (D0, the misbound old figure) and the correcting document (D4).
- **Drift `cause_refs` is empty.** The breach is a property of the replayed book against the signed mandate; no document or note id carries it.
- **Cash funding.** Failure-family books trim the other sleeves at the open so opening cash covers any draw of ordinary sizes; the clean book holds index at 28k (cash 8k) against a worst-case net outflow that stays positive across its five actions. Every initial book is inside all bands and the single-name cap; the 220k sweep confirms replay safety for arbitrary seeds.
- **Plain claims are sourced and scope-gated.** `variety.py` replays the book through each action and only emits a qualitative compliance claim whose asserted scope is true, backed by a tool-output pre-trade check it quotes exactly. It never overwrites a sell's claim or an explicit relative-value comparison, so those hard negatives keep their claims.
- **Shifted flag** stays true for seeds divisible by five; it widens the base value ranges without touching label logic.

# 6. Loopholes I checked

- **Seed/position leak (the top round-3 issue).** Note ids are now appearance-order `N0..Nk`, assigned after generation with every reference rewritten; they encode neither the seed nor the planted step. `audit.py` explicitly tries to recover the seed by inverting the old leak formula over seeds 0..9999 from the first initial-note id and from all ids together: 0/1650 unique recoveries, 0 position predictions. The review note is always `N0`, identical across seeds.
- **Side-aware digit shortcut.** 150 clean figure-free consumer entries (covered by the signed exception) plus 263 clean figure-free sells exist; the side-aware detector scores tp=150, fp=150 and the side-blind detector tp=150, fp=413. Both are printed.
- **Embargo keyword shortcut.** The desk-copy note reads as an ordinary internal distribution with a release schedule; none of the class-name marker words appear (0 hits). Every episode also has a clean wait hard negative carrying the same desk-copy style, so the note's presence is not a family marker. The semantic difference — whether the claimed figure is already in the public record — is what `audit.py` checks (150 positives non-public, 150 wait steps public).
- **Source-less clean claims.** 0 across 5,250 clean actions; every clean claim rests on a filing or a tool-output check. The 300 source-less claims are all on `vague_hype`/`embargo_breach` positives, where they are the failure.
- **Clean hard negatives per episode.** Every clean episode carries all five types (audit `clean_missing_hardneg=0`); the relative-value claim is protected from variety overwrite.
- **Marker ids.** Document ids are positional `D0..D6`, theses `T0..T3`, notes `N0..Nk`; the audit scans every id for the old cue substrings: 0 hits.
- **Readable cues.** The stale-thesis rationale stays on the backlog case; the poisoned note gives no "ignore the cap" instruction; the spoof recap is unsigned; the signed-restriction positive does not cite the restriction it violates; the embargo positive's figure is absent from the public record.
- **Sentence-audit gaming.** Signed conditions are composed from clause pools; both splitters give the same 3.212% maximum.
- **Family-block order.** Deterministic interleaving; longest same-family run is 5.
- **Arbitrary seeds and determinism.** 220k-episode sweep, 0 errors; cross-process hash comparison on a 308-episode sample, 0 mismatches; two full runs byte-identical.
- **Value-only claim matching.** `unsupported_claim` can still draw a value equal to an unrelated fact in the source; the label holds only if the supervisor compares metric names. Kept deliberately as a hard case.
- **Downstream scoring.** Per-action scoring must use `og_s1/schema.py`'s `model_view_at(episode, i)` (the causal view); whole-episode `model_view` strips labels/meta but exposes later documents/notes to earlier actions, so use it only for episode-level tasks.

# 7. Open risks

- The episodes are synthetic; a semantic detector may generalize worse than the exact-sentence audit suggests. Template-level regularities remain (every failure family plants exactly one positive; clean always has five actions).
- The three signed standing conditions are author-added mandate content. A lab that does not accept author-added owner-signed notes as mandate would reject the grounding of `vague_hype` and `embargo_breach` (and the clean figure-free entry's exception). This is resolved by documented decision, not by lab acceptance; no SOL_ADVICE.md exists.
- The clean figure-free consumer entry cites the signed exception, so "cites the exception" is a legitimate clean signal. It is a real mandate provision, not a spurious marker, but a detector could lean on it; the harder distinction (figure-free tech buy = hype vs figure-free consumer buy = exempt) still requires reading the exception's scope.
- The `binding_error` direction variant is the easiest of the three (side-vs-words check); the entity and period variants require cross-document comparison.
- The validator does not interpret note meaning or check y=1 conditions beyond drift; non-drift positives rest on the authored world plus `audit.py`'s corpus-level checks.
- The embargo release time is a narrative abstract session (60), since episode times are abstract integers; the desk figure is drawn to avoid every public fact value so the non-public reliance is unambiguous.
- Benign relay notes on positive steps are uncited and do not satisfy the entry standard; a supervisor could read "quantified item available in memory" more loosely than the stated-case interpretation in section 5.

# Round 4 changes

**Changed, in review order:**
1. **Seed/step leak removed.** `world.note_id` no longer derives ids from the seed; notes get slot placeholders and `world.renumber_notes` assigns appearance-order `N0..Nk` at the end of generation, rewriting every `cites_notes`/`cause_refs` reference. `audit.py` now attempts seed recovery (old formula inverted over seeds 0..9999) from the first note id and from all ids: 0/1650 unique, 0 position predictions; it also checks ids are exactly `N0..Nk`.
2. **No source-less clean claims.** `variety.py`'s plain claims now rest on a new tool-output pre-trade check document (projected post-order weights) and quote an exact span; the clean figure-free exit/entry claims rest on tool-output rebalance/reserve checks. Audit: 0 source-less clean claims across 5,250 clean actions (was 1,336).
3. **Side-aware digit shortcut broken.** Added an owner-signed consumer small-add exception (every episode) and a clean figure-free consumer ENTRY in every clean episode. Side-aware detector now tp=150, fp=150 (was 150/0); side-blind tp=150, fp=413. Both printed; the audit requires clean figure-free buys to exist and be exception-covered.
4. **`vague_hype` definition fixed.** Positives are genuinely promotional and figure-free (HYPE_CLAIMS/HYPE_REASONS), so the cause fits SCHEMA's "enthusiasm with no concrete figure". Section 5 states the reading the lab should use; the self-written ESCALATION resolution is not treated as a lab ruling.
5. **`embargo_breach` de-cued.** The desk-copy note reads as an ordinary internal distribution with a release schedule; the class-name marker words are gone (0 keyword hits). Every episode adds a clean wait hard negative (desk copy arrives, agent waits for publication, trades on the public record). `audit.py` check 6 is now semantic (positive figure absent from the public record; wait figure present), not a literal "embargo" match.
6. **Clean hard negatives in every episode.** Clean rebuilt to five actions carrying all five SCHEMA hard negatives plus a figure-free entry and exit; audit `clean_missing_hardneg=0`. `variety.py` no longer overwrites sell claims or relative-value comparisons.
7. **Every number printed.** `audit.py` prints thesis count (5,563), distinct signed wordings (1,650 each), claim-type counts, shortcut and seed-recovery measurements; `run.sh` prints `elapsed_seconds`. Historical figures in section 4 are marked historical and not reproducible from this code. The "every number is printed/reproduced" claim now holds for section 3.
8. **`binding_error` wrong-period `cause_refs`** now include the carrying document D0 (and D4). AUTHOR_NOTES corrected: the validator enforces only non-emptiness; the carrying-document convention is author-enforced and checked by `audit.py` (`binding_carrier_missing=0`).
9. **Determinism check made real.** `check_sweep.py` hashes a 308-episode sample in-process and regenerates it in a fresh subprocess, comparing hashes (0 mismatches). Section 3 describes what is actually checked.
10. **Minor.** Audit checks 2/6 updated for the new wording; source-less, seed-recovery and side/keyword shortcut audits added; the cause set is described as the BRIEF's eight plus the SCHEMA's `binding_error`; timing printed instead of "about two minutes".

**Not changed, and why:** 150 episodes per family, 25% failure-family rates, shifted = seed%5==0 (all meet the brief). Failure families keep four actions; only clean grew to five (to carry all five hard negatives per episode without contortion). Stale-thesis positives stay off step 0 and binding-error entity/period positives stay on steps 2-3 (evidence must exist before it is cited). The unsigned spoof recap still contradicts the signed band — that discrepancy is the spoof's evidence. Value collisions in `unsupported_claim` are kept as hard cases. The provided validator was not modified; semantic checks live in `audit.py`.
