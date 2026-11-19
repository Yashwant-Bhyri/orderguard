---
id: T17
title: Public data adapters and licence audit - closest-to-the-job datasets first
depends: T15
worker: opencode-go/deepseek-v4.1-flash
variant: high
isolate: false
check: bash run.sh
timeout_min: 150
max_rounds: 4
---

# T17. Public data, with licences, in our Case format

Read `research/system_one/POLICY.md`, `docs/vision/lab/COMBOS.md` (section 4), `docs/vision/research_notes/System One functions and model combos/data_sources.md`, and `og_s1/eval/SPEC.md` from T15. Your task folder is `research/system_one/work/T17/`. Store data in `data/public/<source>/`, no more than 2 GB in total.

**Isolation rule:** do not open `work/T02*`, `work/T06`, `work/T16` or `data/heldout*`.

## Build

For each source below, in this order:

1. confirm it exists, from its primary page;
2. record its licence **exactly**, and give it a usage class:
   - `train`: commercial training allowed;
   - `eval-only`: the licence or card restricts it to evaluation;
   - `research-only`;
   - `excluded`;
3. download it, or a capped sample;
4. write an adapter to the T15 Case format, mapping its labels to our questions (`supported`, `hype`, `authority`, `addresses_reviewer`) and to FinVerify's five categories where possible. Never relabel financial NLI as owner endorsement.

Sources, closest to our job first:
- SEC XBRL hard negatives;
- FinNLI;
- agent finance reasoning trajectories (Snorkel);
- FinChain;
- FinQA;
- VitaminC;
- LLM-AggreFact (evaluation only);
- TRAIL (evaluation only);
- AgentDojo injection cases.

Skip any source you cannot confirm, and say why.

## run.sh

Rebuild every adapter from the cached downloads, print one table (source, licence, usage class, cases, label types, FinVerify categories covered), and run the adapter tests.

## Pass bar

- Every source has a licence quoted from its primary page, and a usage class.
- No `eval-only`, `research-only` or `excluded` source is reachable from any training loader. A test checks this.
- Adapters produce valid Cases; spot-check 20 per source in REPORT.md.
- Total data ≤ 2 GB.
