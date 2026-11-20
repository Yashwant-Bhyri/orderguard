# CS-1000 case suite

CS-1000 is the 1,000-case, multi-decision System One evaluation dataset. It is separate from T16's 600-episode capability benchmark.

Each case contains a chronological investment world, an owner mandate, a portfolio, 40–250 proposed decisions, exact ground-truth labels, time-bounded state snapshots, typed questions, and reasoning probes. The suite is designed to measure owner endorsement, cause attribution, evidence selection, action choice, calibration, and faithful explanations.

## Scope

This directory owns case authoring, case-level validation, the coverage ledger, and evaluation-input packaging. Model training, GPU runs, product UI, and the wider OrderGuard build stay outside this workstream.

## Current status

`CS-0001` is the first author draft. It is kept in reviewable case form; the ledger should be updated only after its author annotations and validation are accepted.

## Validate

From this directory:

```bash
python3 tools/validate_case.py cases/CS-0001
```

To rebuild the state snapshots and questions from the case source, use the case authoring script. The evaluation view must be built from `state/*.json`; never pass `case.json`, labels, case truths, probes' answer keys, or author annotations to a model.

Each state is an audit snapshot of the historical episode: prior recorded orders are replayed as executed, including orders whose labels say they should have been held. Later decisions therefore inherit the portfolio consequences of earlier mistakes.
