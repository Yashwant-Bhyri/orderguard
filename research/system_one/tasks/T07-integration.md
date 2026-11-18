---
id: T07
title: Integration, conformal risk control, and the verdict on C1-C6
depends: T02a, T02b, T02c, T03, T04, T05, T06
worker: opencode-go/deepseek-v4-pro
isolate: false
env_keys: OPENROUTER_API_KEY
check: bash run.sh
timeout_min: 150
max_rounds: 3
---

# T07. Integration and verdict

Read `research/system_one/POLICY.md`, `SPRINT.md` and the REPORT.md of T01 to T06 first. Your task folder is `research/system_one/work/T07/`.

You are the first task allowed to read held-out data:

- `data/heldout/T02a/out/`, `data/heldout/T02b/out/` and `data/heldout/T02c/out/`: the three independent worlds;
- `data/heldout/T06/out/`: the red team.

**Freeze everything before you touch them.** That means:

1. the features (T03 and T05);
2. the model choice;
3. the thresholds;
4. the conformal calibration, on `data/ref/` only;
5. the feature-to-cause map.

Write the frozen configuration and its sha256 to `work/T07/FROZEN.json` *before* the first held-out run. If anything changes after a held-out run, that run's result is reported as void, and the change is documented.

## Build

1. **`og_s1/system_one.py`**:
   - the full scorer: code checks, then the text channel, then the glass box;
   - `score(episode) -> per-action risk and attribution`;
   - conformal risk control (Angelopoulos et al., *Conformal Risk Control*) per action class (buy, sell, open thesis), on a ref calibration split. Target: the rate of approved actions with y = 1 is at most α = 0.05.
2. **`run.sh`**, which produces `work/T07/VERDICT.md`. For each claim in SPRINT.md it gives the measured value, the 95% CI, the pass bar, and PASS or FAIL. It covers:
   - **C1.** Per author, with all three models (logistic, glass box, boosted trees) for comparison, and with and without the text channel.
   - **C2.** Glass-box top-term accuracy against SHAP on boosted trees, per cause.
   - **C3.** For every held-out and red-team action, `risk_with_text >= risk_without_text`; count the violations, which must be 0. Include the monotonicity enumeration certificate. Report the red team's success rate: the share of attack actions that are approved.
   - **C4.** The approved-but-unendorsable rate per author, with a CI.
   - **C5.** Copy the result from T08.
   - **C6.** Latency.
   - **Novel families.** Each author's two invented families, reported separately: recall at a 2% hold rate.
   - **Benign controls.** The hold rate on the red team's benign controls.
3. **External decision model as an end-to-end judge.** This is the strongest outside comparison we have. On a stratified sample of up to 2,000 actions per held-out set:
   - give the external decision model a compact `state` (the owner mandate, the action, its claims with quoted spans, the cited notes with `written_by` and `signature_valid`, and excerpts of the cited documents);
   - ask it one `noul` question ("Would the owner endorse this action?") and one `choice` question over the cause list;
   - report its AUROC, ECE, cause accuracy and latency against our stack, on the same sample.

   This tells us whether our layered design beats a fast, purpose-built decision model on worlds neither of us wrote. If it does not, say so plainly.

**How to call the external decision model.** It is reached through OpenRouter's decisions API. Read the key from the environment variable `OPENROUTER_API_KEY`, and never print or write it.

- Request: `POST https://openrouter.ai/api/alpha/decisions`, with the header `Authorization: Bearer $OPENROUTER_API_KEY`.
- Body: `{"model": "typesafe/jev-1.14", "state": <a JSON record, or a string>, "questions": {<name>: <question>}}`.
- Question types:
  - `{"type": "noul", "instructions": "<a yes/no question>"}` returns `{"noul": p}`, a probability.
  - `{"type": "choice", "criteria": {"<option>": "<what it means>", ...}}` returns `{"choice", "probabilities", "confidence"}`.
  - `{"type": "score", "criteria": ["<low anchor>", "<high anchor>"]}` returns `{"score"}` on that scale.
- Several questions can go in one call.
- Measured on 2026-11-19: about 1.1 s per call including the network, and about $0.00002 per call. Results are near-deterministic.
- Cache every response on disk, keyed by the sha256 of the request, so the reviewer's re-run costs nothing.
- Keep the total spend for this task under $2.
- In reports, call it "the external decision model", not by product name.

4. **Failure analysis.** Pick the 20 worst-missed held-out failures. For each, give one line on which layer missed it and why.

## Pass bar for the task (not for the claims)

- `VERDICT.md` is complete.
- `FROZEN.json` was written before any held-out run; the reviewer checks the file timestamps and the logs.
- Every number reproduces from `run.sh`.
- Failed claims are reported as plainly as passed ones.
