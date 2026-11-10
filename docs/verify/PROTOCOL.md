# Native-error test: protocol

Written and committed **before any memo was drafted, labelled or checked**. Anything that changes later is listed at the bottom with its date.

## Question

On memos nobody prepared, how many wrong figures does the checker catch, and how often does it wrongly stop a memo whose figures are right?

## Material

- **25 US companies** from the 30 already in the repo (dropped for being unsuited: MRNA, PTON, SNAP, XOM, F). `data/native/companies.json`.
- **Split by name, seeded shuffle (seed 20261105):** 9 development companies (AAPL ADBE AMD CRM DIS KO META PEP PG), 16 hold-out companies (AMZN BA COST CSCO GOOGL INTC JNJ MCD MSFT NFLX NKE NVDA ORCL PFE TSLA WMT).
- Disclosure: earlier work on this repo (the synthetic 80-case set) used figures for many of these companies, so the checker's *data* for hold-out companies is not new to the builder. What is new for the hold-out is the memos and their labels: nobody has looked at them while tuning.
- **Decision date for every memo: 2025-03-31.** The checker may only use filings public on that date.
- **Memos:** models of different families draft a research note on each company *from memory, with no documents and no retrieval*: Meta Llama, Mistral and Alibaba Qwen as first planned; see the change log for what was actually used. Prompt in `orderguard_verify/native/memos.py`. 25 companies x 2 = 50 memos (see the change log). Every figure in them is a natural truth or a natural mistake; nobody planted anything.
- **Scope of claims:** reported company figures (revenue, income, EPS, cash flow, margins, growth, and similar) for fiscal years. Out of scope, not counted anywhere: share prices and valuation multiples (no trusted price source), forecasts, opinions, quarterly figures (no 10-Qs given to the labeller), rumours (cannot be confirmed; covered by the synthetic development set).

## Labels

- A **fresh labelling agent** (a Claude Haiku subagent, a different model and vendor from the memo writers and from the checker) reads each memo and the company's two most recent 10-K filings **as text from sec.gov**, and lists every in-scope claim with a verdict `true`, `false` or `not_in_filings`, a verbatim excerpt from the filing as evidence, and for false claims an error class: `wrong_figure`, `wrong_period` (a real figure of another year), `wrong_growth`, `wrong_derived` (a margin or ratio that does not follow), `other`. It may flag `borderline` where rounding makes the call a matter of judgement.
- It does **not** see the checker, its truth store, XBRL facts, or any checker output. Labels are never produced by `TruthStore` or the comparison code.
- Who labelled what is recorded per memo in `data/native/labels/`. 25 labelled claims are drawn at random for the owner to hand-check (`docs/SPOTCHECK.md`); until that is done the labels are described as **agent-labelled**, never human-reviewed.

## Arms (hold-out, same memos, same evidence)

| Arm | What it is |
|---|---|
| A. No checker | Passes everything. The floor. |
| B. Prompt-only judge, same family | DeepSeek (`deepseek/deepseek-v4-flash`), shown the memo and the **same filing figures the engine reads** (rendered as a table), asked for a verdict per claim and an overall action. |
| C. Prompt-only judge, other family | OpenAI `openai/gpt-oss-120b`, identical prompt and evidence. |
| D. The engine | DeepSeek reads the memo into claims; code looks up the figure, compares and decides. |

The judges are not weakened: same evidence, same as-of date, temperature 0. An extraction miss counts as a miss for every arm.

## Measures

1. **False holds first.** Memos whose labelled claims are all true that the arm does not pass; and true claims it calls wrong. Counts with 95% Wilson intervals.
2. **Catch rate** on false claims, by error class: the arm marks that claim wrong, or its quote cannot be matched (then it is a miss, "not extracted").
3. **Memo level:** of memos with at least one false claim, how many were not passed.
4. **Coverage:** share of labelled claims the arm could check at all (verdict other than unchecked).
5. **Cost and latency** per memo from the recorded model calls.
6. Everything is reported with counts. If a cell is below ~10 cases the interval is shown and the cell is not read as a rate.

## Rules that keep it honest

- **Tune on the development companies only.** Memos, labels and arms for those 9 may be inspected and the checker changed.
- **Freeze.** When the owner-visible change list is done, the commit is tagged `holdout-freeze`. The hold-out is run **once** from that tag with `og native --holdout`; the run writes `results/native_holdout.json` and refuses to run again unless `--again` is passed, which is recorded in the file.
- **No tuning after seeing hold-out results.** Misses are published, with each failing claim and why. If the checker later changes, the new numbers are labelled as run after the hold-out was seen.
- **The grader is independent.** `orderguard_verify/grader/` uses only the standard library and reads JSON files: labels and arm outputs. A test fails if it imports the checker (`finance`, `core`) or the truth store. A canary test shows an inverted grader and a broken checker both fail the check.
- If the data comes in smaller than the targets (about 60 memos, at least 150 labelled claims) the report says so.

## Changes after this was written

- **2026-11-05, before any memo existed:** the OpenRouter account has about US$0.0004 of credit left (a 900-token request to a paid model is refused with "can only afford 626 tokens"), so paid models cannot be used. All model roles move to free models: memo writers become `cohere/north-mini-code:free` and `recursive/flint-v1.0:free`. A third writer (`xingchen-agi/xing4.0-29b-a4b:free`) was tried and dropped because it is rate-limited to nothing, so there are **2 memos per company, 50 in all**. The engine's and judges' models are chosen and recorded below before any hold-out run. The two judges are chosen and recorded below before the hold-out is run. A paid rerun is one command (`OG_MODEL=... og native --holdout --again`) once credit exists.
- **2026-11-05, before any hold-out result existed:** the memo writers got most figures wrong, so almost no native memo is fully honest, and "does it wrongly stop an honest memo?" has no memo-level sample. I added **25 honest control memos** (one per company): a model is handed a short table of the company's figures (from the truth store) and writes a note from only those. They are labelled independently from the filing documents like every other memo, so a wrong table entry would still be labelled false. Controls are reported separately from the native memos. Memo count: 50 native + 25 controls.
- **2026-11-05, before any hold-out result existed:** the engine and the same-family judge moved from `nvidia/nemotron-3-ultra-550b-a55b:free` (it stopped answering reliably) to `nvidia/nemotron-3.5-super-vl:free`. The other-family judge is `cohere/north-mini-code:free` (Google's Gemma and others were rate-limited to nothing); Cohere also wrote one of the two memo writers' sets, so every table is also split by memo writer. The synthetic development set was re-recorded on the same engine model.
- **2026-11-05, dev tuning, hold-out untouched:** (a) the extraction prompt now lists margins, cash flow, capex, R&D and free cash flow as measures; (b) margins and free cash flow are worked out in code from stored figures; (c) when a memo names a fiscal year and gives a period-end date that disagrees, the name wins; (d) a company's own fiscal-year naming is read from its filings (January year-ends such as Lululemon); (e) the grader now assigns each engine claim to at most one label, best word overlap first, after the first scoring counted a growth claim and the figure inside it twice. The grader fix changes how every arm is scored, not just the engine.
- **2026-11-05, freeze (before any hold-out result existed):** final roles. Engine and same-family judge: `nvidia/nemotron-3.5-super-vl:free`. Other-family judge: `cohere/north-mini-code:free`. Memo writers: `cohere/north-mini-code:free`, `recursive/flint-v1.0:free`; controls written by `cohere/north-mini-code:free`. Labeller: a Claude Haiku subagent, one fresh run per company (two or more companies per run for the controls), working only from a folder of memos and 10-K text. Counts at freeze: 75 memos (50 native, 25 controls); hold-out 48 memos with 491 non-borderline true/false labelled claims in native memos (429 false, 62 true) and 202 in controls (5 false, 197 true); borderline claims are excluded from the headline and reported with `--borderline`. Dev tuning is finished: the commit tagged `holdout-freeze` is the one the hold-out is run from. The four hold-out runs (`none`, `judge_same`, `judge_other`, `engine`) are started in parallel, one process per arm, each once.

## Results as run

The hold-out was run once per arm on 2026-11-05 from commit `9db0157` (tag `holdout-freeze`, clean tree; recorded in `results/native/holdout_<arm>_run.json`, no repeat). Outputs: `results/native_holdout.md` (all tables, by error class and by memo writer), `results/native_holdout_misses.md` (every miss and false alarm of the engine), `results/native/holdout_<arm>.json` (one record per memo). The development-set equivalents are the `dev_` files. Nothing in the checker, the judges or the grader was changed after the hold-out was seen; only documentation, the demo, and the report/headline formatting were. Counts: 32 native memos (491 non-borderline true/false claims: 429 false, 62 true) and 16 honest controls (202 claims: 5 false, 197 true) in the hold-out; 80 hold-out claims marked borderline are excluded.

## Audit after the hold-out was seen (2026-11-05)

A review of the published records found that the grader's strict rule, "each engine or judge quote answers at most one label", was asymmetric: 27% of the same-family judge's quotes held two or more figures, against 4% of the engine's, so a judge that marked a whole sentence wrong was credited with one figure of it. I rescored the saved hold-out records (no model was called) and reproduced the reviewer's numbers exactly. Native memos, non-borderline claims: sentence flagged wrong, same-family judge 376/429, other-family judge 343/429, engine 377/429; exact figure named 217, 215 and 365; true claims flagged wrong (of 62) 9, 15 and 6, of which with no false figure beside them 1, 0 and 3; memos with a false claim stopped 32/32 for all three. By class, flagged, engine against same-family judge: wrong figure 270/253 of 281, wrong year 34/36 of 39, growth 28/32 of 36, margins and free cash flow 42/52 of 70.

- **Superseded:** the headline of 86% (engine) against 68% and 62% (judges) came from the strict rule. Those strict numbers are kept in the full report (`results/native_holdout.md`, last column), labelled, and nowhere else as a headline.
- **Not touched:** the checker, the judges, the models, the labels and the frozen records. Only the grader gained the two counts (and a test with a two-figure sentence); the headline, README, DEFEND and demo were rewritten.
- **Memo level cannot separate the arms:** the median native memo holds 13 false claims (fewest 5).
- **One checker change after the hold-out was seen:** a key claim whose figure the source proves was not public on the memo's date is now `revise` (rule 2b), not a pass. Replaying the hold-out from recorded answers changed no decision (`results/native_holdout_post_audit.md`); the frozen result stays the result.
- **The date mechanism was barely tested:** the restatement rule fired on 2 claims in 1 hold-out memo (PFE-flint) and rule 2b on none.
- **Known time failure:** `BA-control` states FY2023 figures as FY2024; the engine passed it, both judges stopped it. Not tuned on.
- The gate baseline now tracks the flagged and named counts; it was rewritten deliberately (`og gate --update`).

## Independent audit (2026-11-06)
Four reviewers and two blind re-labellers examined the hold-out after it was published; see `docs/AUDIT.md`. No model run, label or frozen record was changed. Changed: README and DEFEND wording (process statement, borderline-included results, paid-run honest-control result, matcher caveat, coverage definition), the full report's coverage column (any matching quote), and the grader gained `checked_loose`. Not yet done: fixes for the gateway and mandate issues, the human spot-check, a benchmark with realistic memos.
