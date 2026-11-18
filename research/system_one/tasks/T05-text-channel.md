---
id: T05
title: Bounded text channel - hype, authority language, claim support
depends: T01
worker: opencode-go/deepseek-v4.1-flash
isolate: false
env_keys: OPENROUTER_API_KEY
check: bash run.sh
timeout_min: 150
max_rounds: 3
---

# T05. Bounded text channel

Read `research/system_one/POLICY.md`, `SPRINT.md` and `SCHEMA.md` first. Your task folder is `research/system_one/work/T05/`. Code goes in `research/system_one/og_s1/text.py`, plus tests.

**Isolation rule:** do not open `work/T02*`, `work/T06` or `data/heldout*`.

## Problem

Some failures are visible only in wording: hype that dresses up a weak claim, a note that *claims* authority in words, and a cited document that does not actually support the claim. A small model reads the text. It must never decide on its own, and it must never be able to make the supervisor *more permissive*.

So the text channel outputs three features, each in [0, 1] and each "higher means riskier":

- `hype`: promotional or vague language in claims and rationale.
- `authority_language`: text in notes or rationale that asserts permission, approval, an exception or an instruction to a reviewer.
- `support_gap`: 1 minus the probability that the cited document's text entails the claim's text. Use 0.5 if there is no source.

These enter the glass-box scorer with monotone-increasing constraints, so they can only raise risk. That is the bound. Also report the largest logit contribution each feature can make.

## Lead's architecture study (read this first)

`docs/vision/lab/ARCHITECTURE.md` section 2b and experiment X2 govern this task. In short: run a reader tournament, one sub-question at a time, and let evidence pick the winner per sub-question. Build every reader behind one interface: `og_s1/readers/<name>.py` exposing `score(texts_or_pairs) -> np.ndarray in [0, 1]`. T07 can then re-score them on held-out wording without code changes.

Add this reader for `authority_language`: **purpose-built prompt-injection classifiers.** Confirm the current best small ones from their model cards first, for example Meta Prompt Guard 2 at 86M and 22M, and ProtectAI's DeBERTa-v3 injection classifier. Respect their licences, and record the alternatives you considered.

## Compare these readers

1. **Lexicon baseline:** fixed word lists. This is the floor.
2. **Zero-shot NLI cross-encoder** for `support_gap`, and zero-shot classification for the other two. Use a DeBERTa-v3 NLI checkpoint from Hugging Face, for example one trained on MNLI, FEVER and ANLI. Run it on the Mac (MPS or CPU).
3. **Small trained classifier:** sentence embeddings (a small sentence-transformers model) with logistic regression. Train it on **training text you generate yourself** with a separate script (`make_train_text.py`), using your own templates and wording. Do not use text from `data/ref/`.
4. **No GPU reader in this task.** Which model, if any, reads text on the GPU is decided by architecture study T10 and the lead's decision D10. Do not choose one here.

5. **External decision model** for all three features: one `noul` question per feature, using the action's text fields and the cited document or note as `state`. This model is fast and cheap, and was built for exactly this kind of typed probability. Compare it with readers 1 to 3 on AUROC, calibration and latency.

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

Evaluate on `data/ref/` actions (shifted and not shifted), where the label cause is vague_hype, authority_spoof, poisoned_note, misquote or unsupported_claim. Report:

- AUROC per feature and per reader;
- latency p50 and p99 per action, for each reader and device.

## run.sh

1. Install anything missing into `research/system_one/.venv`. Log the installed versions.
2. Build the training text.
3. Train reader 3.
4. Score readers 1 to 3 on ref.
5. Write `work/T05/results.json` and a table.
6. Run the tests: outputs are in [0, 1]; the scores are deterministic; and `og_s1.text.features(episode)` returns an array aligned with T03's action order.

## Pass bar

- The tests pass.
- The best reader beats the lexicon on shifted ref for each of the three features, with CIs (bootstrap over episodes).
- Latency is reported.
- Model downloads are cached under `research/system_one/data/models/`.
- `og_s1.text` can be imported and run offline once the models are cached.

**Leakage guard:** featurise and score only `og_s1.schema.model_view(episode)`. `meta` (which names the planted family) and `label` are for evaluation only. The reviewer checks this.
