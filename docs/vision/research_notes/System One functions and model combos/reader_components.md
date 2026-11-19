# Reader components: off-the-shelf models for short financial text judgment (as of 2026-11-19)

Scope: pretrained components that can read a claim/source pair or a note and return a narrow judgment (decision/classification/verification/injection flag) for an AI-agent supervisor. No generation.

Evidence caveat for the whole file: this pass ran 15 searches and read search snippets only. Primary Hugging Face model cards, the LLM-AggreFact leaderboard, and the arXiv papers were NOT fetched in full. Most 2026 decision-model numbers are vendor-reported or come from secondary blogs. Every 2026 figure below is labelled. No A6000 latency was found for any component. Items marked "unverified" should be checked against the primary page before use.

## Key Question 1: Decision models that score typed questions in one forward pass

### Takeaway
A 2026 family of "decision models" (Jev/TypeSafe, Clef, GLiDE, Perplexity Decider, d3, Liquid d1, Microsoft Decision-1, GLiNER2.5-Decide) returns probabilities over caller-defined options with no text generation. This is the right shape for the supervisor. The strongest open-weight candidates are 9B to 27B decoder-based models (Clef, Decider, d3), with a 340M encoder (GLiNER2.5-Decide) as the CPU/latency option. Scores are mostly vendor-run, and the one independent comparison (Arize, Oct 2026) found the leaders statistically tied on accuracy.

### Catalogue (2026 candidates)

| Component | Release | Params / base | Architecture (as reported) | Licence (as reported) | Reported score | Latency reported | Source status |
|---|---|---|---|---|---|---|---|
| Cloudflare Clef | 2026-10-01 | 27B; base listed as Qwen/Qwen3.8-27B (per HF listing); multimodal tag | Decoder-based; joint schema head scoring permitted answers | Apache-2.0 (changelog + HF LICENSE) | Cloudflare: top score on 7 of 10 of its decision benchmarks; Arize: 85.2% hallucination-detection quarterfinal | Arize: 0.50 s per decision; secondary blog: median 209.3 ms | Licence: primary changelog. Context: conflicting (64K Workers AI listing vs 32K/16K third-party). Scores vendor or secondary |
| Cloudflare Clef-flash | 2026-10-01 | 9B | Same family, smaller | Apache-2.0 (per changelog) | Not found | Not found | Secondary only |
| Perplexity Decider v1 27B | 2026-10-01 | 27B; third-party listing says Qwen3.8-27B fine-tune | Decision types: yes/no, multiple choice, ordered score; returns probabilities | Apache-2.0 weights (third-party listing) | Provider-reported 85.71% on its own 7,210-row panel vs 84.51% Jev 1.13.0 and 74.76% Qwen3.8-27B; baseline settings unspecified | Not found | Vendor. Blog announces v1.3 and Flash v1.3 as successors (not verified on HF) |
| Perplexity Decider Flash v1.3 | 2026 | smaller distilled model | Same API | Apache (per blog) | Not found | Not found | Secondary/vendor |
| vLLM Semantic Router d3 | ~2026-10 (MarkTechPost 2026-10-11) | 27B flagship of Decision 3.0 family; siblings lite, mini, flash, nano | Classification, yes/no, scoring over text/image/video; probabilities | Not confirmed in snippets (check HF card) | Own card: Jev Decision Index 64.7 vs Decider v1.1 27B 62.8; MarkTechPost reports 64.1 and Torchcast Decision 27B at 65.1 vs d3 64.9 on the public text suite; team's internal eval | Not found | Vendor/internal. Served at /v1/systemone; Decision 3.0 support on vLLM main, not in a release at recipe time. Max context null in config |
| Fastino GLiDE | 2026-09-30 | 27B and 9B variants mentioned; "thinking decision model" | Fast first pass; extra reasoning when unconfident; returns selected action, confidence, per-option probabilities | Fastino Community License (one source; weights on HF); commercial use described as restricted (verify) | Fastino: 64.81 on Decision Index 0.2.1 vs 57.91 for Jev 1.13.0; not on public leaderboard (submissions paused) | Not found | Vendor. Context conflicting (40K vs 64K). Price conflicting ($0.15/M vs $0.040/M input) |
| GLiNER2.5-Decide | 2026-09-24 | 340M encoder (English); multilingual variant 287M separate; 1B sibling | Encoder-based decision model for classification; loaded via `gliner2` package, `AutoExtractor.from_pretrained("fastino/GLiNER2.5-Decide")` | Apache-2.0 (per secondary summaries; verify on HF card) | Launch post: 60.1% average over 17 datasets; model card: 60.2%; 1B: 59.6%. Vendor | Runs on CPU (aicybr secondary) | Official ID fastino/GLiNER2.5-Decide. Beware a mirror at helmo/GLiNER2.5-Decide (unverified) |
| Liquid d1 / d1-ultra | 2026 | not found | Decision model | not found | Arize: 0.20 s, $0.034 per 1,000 decisions; in Future AGI (2026-11-11) d1-ultra listed at 70.4 | 0.20 s (Arize cloud) | Vendor and Arize |
| Jev (TypeSafe) 1.13 / 1.14 | 2026 | not found | Reference "decision" interface; the Decision Index is built around it | not found | Jev 1.14 at 67.0 (Future AGI 2026-11-11); Arize cloud final: Jev 91.1% | Jev won on speed in Arize run | The Decision Index reference. Clef and Jev are API-compatible |
| Microsoft Decision-1 | 2026 | not found | Decision model | not found | 62.8 (Future AGI 2026-11-11) | not found | Secondary only |
| OpenDecision (ModernBERT-large) | ~2026-10-08 | ~400M ModernBERT-large, zero-shot NLI base (per BenchLM) | Encoder NLI | not found | BenchLM: 21.64 on JevBench 1.4 vs best 70.82; composite display-only | not found | Author Deepan Wadhwa. Weak evidence; treat as a baseline, not a candidate |
| OpenDecisions benchmark (arXiv 2610.17205, "Releasing the Inner Jev") | 2026-10 | n/a | A benchmark plus a recipe for open decision models | n/a | Rank agreement with official leaderboard: Spearman 0.90 (14 systems); 0.85 on JevBench-Open 231 items | n/a | Academic. Most useful independent resource found; read directly |

### Cited Findings
- Clef is a 27B open-weight decision model returning probabilities over predefined options, released 2026-10-01 under Apache 2.0 — [Cloudflare changelog](https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/); [Clef HF repo](https://huggingface.co/Cloudflare/Clef) (listing only; card not read in full)
- Clef-flash is 9B, same release date — [Let's Data Science](https://letsdatascience.com/news/cloudflare-releases-open-weight-clef-decision-models-c52886d6)
- Clef context window conflicts: 64K (Workers AI listing) vs 32K and 16K (third-party) — [Developers Digest](https://www.developersdigest.tech/blog/cloudflare-clef-decision-models-2026); [featherless.ai](https://featherless.ai/models/Cloudflare/clef)
- Clef median decision time 209.3 ms and $0.24/M input (secondary, unverified) — [Developers Digest](https://www.developersdigest.tech/blog/cloudflare-clef-decision-models-2026)
- Arize (2026-10-07) cloud run: Clef 27B 85.2% vs Liquid 84.8% on hallucination detection quarterfinal, inside confidence intervals; Liquid d1 faster (0.20 vs 0.50 s) and cheaper ($0.034 vs $0.223 per 1,000 decisions) — [Arize benchmark](https://arize.com/blog/decision-model-benchmark.md)
- Arize cloud final: Jev 91.1% vs Liquid 87.6%, overlapping intervals; Jev faster, Liquid cheaper — [Arize benchmark](https://arize.com/blog/decision-model-benchmark.md)
- Perplexity Decider 27B: classification with ordered or unordered labels, returns probabilities; 85.71% on its 7,210-row panel vs 84.51% for Jev 1.13.0 (vendor) — [Perplexity blog](https://www.perplexity.ai/hub/blog/perplexity-decider); [OpenRouter listing](https://openrouter.ai/perplexity/pplx-decider-v1-27b)
- Perplexity Decider 27B weights listed Apache 2.0, 262,144-token context, $0.04/M input (third-party listing) — [OpenRouter](https://openrouter.ai/perplexity/pplx-decider-v1-27b)
- d3: 27B flagship; Jev Decision Index 64.7 vs 62.8 for Decider v1.1 (model card, internal evaluation); MarkTechPost reports 64.1 and Torchcast Decision 27B edging d3 on the public text suite — [HF vllm-sr/d3](https://huggingface.co/vllm-sr/d3); [MarkTechPost](https://www.marktechpost.com/2026/10/11/what-is-decision-3-0-vllm-semantic-routers-new-open-decision-models/); [vLLM recipe](https://recipes.vllm.ai/vllm-sr/d3)
- d3 serves via /v1/systemone; Decision 3.0 support on vLLM main, not in a release at recipe time — [vLLM recipe](https://recipes.vllm.ai/vllm-sr/d3)
- GLiDE: "thinking decision model," returns selected action, confidence and per-option probabilities; vendor 64.81 on Decision Index 0.2.1 vs 57.91 for Jev 1.13.0; released 2026-09-30 — [Fastino GLiDE via BenchLM](https://benchlm.ai/models/fastino-glide); [llmreference](https://www.llmreference.com/model-family/glide)
- GLiDE licence: Fastino Community License per one source, commercial use restricted (unverified) — [llmreference](https://www.llmreference.com/model/glide)
- GLiNER2.5-Decide: 340M, English, Apache 2.0 weights per secondary sources, 60.2% on 17 datasets per model card (60.1% in launch post), released 2026-09-24 — [HF fastino/GLiNER2.5-Decide](https://huggingface.co/fastino/gliner2.5-decide); [Datanorth](https://datanorth.ai/news/fastino-releases-gliner2-5-decide)
- GLiNER2.5-Decide runs on CPU per secondary write-up — [aicybr](https://aicybr.com/blog/gliner2-5-decide-340m-cpu-decision-model)
- Decision-model benchmark agreement: rank agreement with the official leaderboard Spearman 0.90 across 14 systems — [arXiv 2610.17205](https://arxiv.org/pdf/2610.17205)
- OpenDecision ModernBERT-large: 21.64 on JevBench 1.4, not publicly ranked — [BenchLM](https://benchlm.ai/models/opendecision-modernbert-large)
- Later snapshot (2026-11-11): Jev 1.14 at 67.0, Microsoft-Decision-1 at 62.8, d1 at 61.6, d1-ultra at 70.4 — [Future AGI post, cited in search snippet; URL not captured](https://futureagi.com/blog/ai-decision-models-explained/)

### Inferences
- Decision-model scores are not comparable across papers: each vendor runs its own panel and Decision Index version. Use the independent arXiv benchmark to build an in-house panel for the four judgment types instead of trusting any leaderboard number.
- Clef, Decider, d3, and GLiDE are all 27B-class. On two A6000s (96 GB total) a 27B model fits in bf16 on one card with room for KV cache. Whether 27B meets p99 ≤ 300 ms is untested; the Arize 0.50 s cloud figure for Clef suggests a risk. A 9B variant (Clef-flash) is the realistic first target for the latency budget.
- The licence picture is the main differentiator: Clef and Decider (Apache 2.0) are clean for commercial use; GLiDE's Fastino Community License may not be. Confirm before shortlisting.
- GLiNER2.5-Decide is the only encoder-sized decision model found. It is the natural CPU fallback, but English-only and its 60% average is well below the 27B tier.

### Gaps
- No primary HF model card was read in full for Clef, Decider, d3, GLiDE, or GLiNER2.5-Decide. Licences and context lengths need confirmation on each card.
- No fine-tuning code was confirmed for any decision model. Clef, Decider, and GLiNER2.5 have "fine-tuning" or RL platform claims (Cloudflare has an RL fine-tuning platform per Product Hunt snippet, unverified); the exact method (LoRA vs full vs head-only) is not documented in what was read.
- No independent measured latency on A6000 for any model.
- Joint-schema and option-scoring internals were described only at marketing level (for example "joint schema head"). The mechanism is not verified from a paper.
- OpenDecision: no source ties the arXiv benchmark to the BenchLM model; treated as separate.

## Key Question 2: Fact verification and grounding models

### Takeaway
The best-documented open verifier is Bespoke-MiniCheck-7B, reported at 77.4% on LLM-AggreFact (vendor and secondary; leaderboard not loaded). Its licence is CC BY-NC 4.0, which blocks commercial use. The commercial-friendly path is smaller verifiers (MiniCheck variants with Apache or MIT licences, DeBERTa NLI) plus numeric-specific checks. Numeric and financial verification evidence was not found in this pass.

### Cited Findings
- Bespoke-MiniCheck-7B: 77.4% average on LLM-AggreFact per Bespoke Labs (vendor); HHEM 2.1 at 71.8% in the same comparison — [Bespoke docs](https://docs.bespokelabs.ai/models); [Bespoke](https://bespokelabs.ai/bespoke-minicheck)
- Bespoke-MiniCheck-7B is 7.74B, built on internlm2_5-7b-chat, licence CC BY-NC 4.0 — [HF bespokelabs/Bespoke-MiniCheck-7B](https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B)
- A later paper reports Bespoke-MiniCheck-7B at the top of the public LLM-AggreFact Grounded Factuality Leaderboard, above GPT-4o and Claude 3.5 Sonnet (date of that standing not verified) — [arXiv 2505.04847](https://arxiv.org/html/2505.04847v1)
- LLM-AggreFact aggregates 11 factuality datasets, closed-book and grounded — [LLM-AggreFact leaderboard](https://llm-aggrefact.github.io/blog)
- "Verify with Caution" (arXiv 2501.14883) argues imperfect factuality metrics can mislead; relevant to any single-number leaderboard pick — [arXiv 2501.14883](https://arxiv.org/pdf/2501.14883)
- Vectara HHEM-2.3 is commercial and closed; HHEM-2.1-Open is on HF. HHEM-2.3 adds long context and 11 languages (vendor claim). Licence and production terms unclear per a third-party summary — [Vectara docs](https://docs.vectara.com/docs/learn/hallucination-evaluation); [HF vectara/hallucination_evaluation_model](https://huggingface.co/vectara/hallucination_evaluation_model)
- Vectara says HHEM-2.1-Open derives from T5; OECD says DeBERTa-v3-base. Sources conflict — [Vectara blog](https://www.vectara.com/blog/hallucination-detection-commercial-vs-open-source-a-deep-dive); [OECD catalogue](https://oecd.ai/en/catalogue/metrics/hughes-hallucination-evaluation-model-hhem-score)

### Inferences
- MiniCheck-style verifiers are a strong fit for "does this source support this claim," but the 7B size and CC BY-NC licence rule out the 7B model for a commercial supervisor. A distilled or Apache-licensed alternative must be benchmarked on the same panel.
- HHEM's 0.5 threshold is a generic default. A supervisor needing value/unit/period precision will need its own threshold.

### Gaps
- No AlignScore, DeBERTa NLI, ModernBERT NLI, or Qwen3-Reranker verification results found on numeric or financial claims.
- Current LLM-AggreFact standings not loaded (leaderboard page not fetched).
- Qwen3-Reranker: licence Apache-2.0 per HF metadata; MTEB-R 65.80 (0.6B) and 69.76 (4B) per model card reranking table, which lists the 4B model as 1.7B (apparent typo). These are retrieval rerankers, not verifiers, so they are not direct judges of entailment. Source: [HF Qwen3-Reranker-8B README](https://huggingface.co/backups/Qwen3-Reranker-8B/blob/main/README.md); [arXiv 2506.05176](https://arxiv.org/pdf/2506.05176v1). Vendor/model-card numbers.
- bge-reranker: not searched.
- No independent numeric-claim evaluation found.

## Key Question 3: Prompt-injection and jailbreak classifiers

### Takeaway
Two open classifiers are in play: Meta Prompt Guard 2 (86M) and ProtectAI deberta-v3-base-prompt-injection-v2 (Apache 2.0). ProtectAI reports ~95% accuracy and 99.7% recall on its own test; it also warns of false positives on system prompts. Prompt Guard 2 has conflicting third-party evidence: low false positives but low recall on embedded injections. Neither has a robustness-to-adaptive-attacker evaluation in what was found.

### Cited Findings
- ProtectAI deberta-v3-base-prompt-injection-v2: DeBERTa-v3-base, Apache 2.0, labels benign (0) vs injection (1); card reports accuracy 94.8%, recall 99.6% (original) and 95.25% / 99.74% on 20,000 prompts from untrained datasets (later revision); card warns against use on system prompts due to false positives — [HF ProtectAI/deberta-v3-base-prompt-injection-v2](https://huggingface.co/ProtectAI/deberta-v3-base-prompt-injection-v2) (vendor)
- ProtectAI training data includes Harelix/Prompt-Injection-Mixed-Techniques-2024, Salad-Data, jailbreak-classification — same card. Note: in-distribution data, so vendor scores overstate OOD performance
- Prompt Guard 2 86M, vendor claim: 97.5% recall at 1% FPR (Groq model page, method undescribed) — [Groq docs](https://console.groq.com/docs/model/llama-prompt-guard-2-86m) (vendor, unverified)
- Prompt Guard 2 on JailbreakBench: 0.0% FPR, 64.9% recall on 282 prompts (single developer test) — [DEV Community](https://dev.to/ayush_singh_9b0d83152be5b/i-beat-metas-llm-guardrail-with-no-gpu-and-no-team-heres-how-2556) (single, informal)
- Prompt Guard 2 on embedded-injection in tool output: 6 of 629 caught (1%), zero false positives (benchmark cited in snippet, name not captured) — [Ecosistema Startup](https://ecosistemastartup.com/prompt-guard-2-de-meta-detecta-1-de-ataques-reales-a-ai-agents/) (secondary)
- Meta's model card reports TPR, FPR and AUC and cautions that numbers may not match real-world traffic (the 86M figures were not extracted) — [Azure AI catalog](https://ai.azure.com/catalog/models/Prompt-Guard-86M) (secondary)

### Inferences
- The embedded-injection result is the one that matters for a supervisor reading tool output or agent-written notes, and it points to very low recall. Do not rely on either classifier as the sole injection gate.
- Recall and FPR trade off heavily across these classifiers and settings. A system-prompt-like input or a finance note with imperative verbs will trigger false positives.

### Gaps
- No published adaptive-attack robustness study found for either model.
- Lakera Guard: not searched. Commercial API, so out of scope for on-prem but worth a line.
- Licence for Prompt Guard 2 86M: not verified in this pass (Meta community licence is the likely form; check the card).
- No benchmark of these models on financial-note injections specifically.

## Key Question 4: Finance-domain encoders and LLMs

### Takeaway
Domain-specific encoders (FinBERT) hold up in-domain when fine-tuned but generalize poorly outside their pretraining domain. Mid-2025 to late-2025 studies mostly found LLMs (prompted or fine-tuned) competitive or better across sources. Results are mixed and not directly comparable across papers. No finance-specific decision model (as opposed to sentiment classifier) was found.

### Cited Findings
- A Nov 2025 comparison of FinBERT with 7-8B open LLMs (DeepSeek 7B, Llama3 8B, Qwen3 8B) finds FinBERT limited beyond its pretraining domain; LLMs more scalable and capable — [arXiv 2512.00946](https://arxiv.org/abs/2512.00946v1)
- Fine-tuned small models (FinBERT, FinDRoBERTa) outperform zero-shot GPT-3.5/GPT-4 on financial news sentiment (2024) — [arXiv 2409.11408](https://arxiv.org/html/2409.11408v1)
- Few-shot GPT-4o can match a well-tuned FinBERT on financial news/reports (2024) — [arXiv 2410.01987](https://arxiv.org/abs/2410.01987v1)
- On Financial PhraseBank, GPT-4o, GPT-4.1, and o3-mini did not improve with reasoning — [arXiv 2506.04574](https://arxiv.org/html/2506.04574v1)
- A May 2025 study favors fine-tuned GPT-4o-mini and GPT-4o over BERT/FinBERT — [arXiv 2503.03612](https://arxiv.org/abs/2503.03612v4)

### Inferences
- The evidence favors "fine-tune a general or mid-size encoder/decoder on in-house financial labels" over relying on FinBERT. FinBERT as a backbone is a weak default for claim-to-source matching, which is a different task from sentiment.
- None of these studies tests numeric claim verification (value, unit, period, actual vs guidance), which is the supervisor's core need.

### Gaps
- No FinBERT-variant or finance-NLI evaluation on numeric or entity-period claim matching found.
- Specific finance numeric reasoning models: not searched in this pass.
- Results sources are mostly arXiv, not verified against venue acceptance.

## Key Question 5: General encoders as backbones (ModernBERT, NeoBERT, EuroBERT, Ettin, LLM2Vec)

### Takeaway
Ettin (ICLR 2026, arXiv 2507.11412) is the best-documented open-data encoder suite: 17M to 1B across paired encoder/decoder models, with a claimed ModernBERT replication. ModernBERT-large and Ettin-400M perform within noise on classification. EuroBERT and NeoBERT were not covered in this pass.

### Cited Findings
- Ettin: 10 models (5 encoder-decoder pairs), 17M to 1B parameters, up to 2T tokens, open data; first open-data ModernBERT replication — [arXiv 2507.11412](https://arxiv.org/abs/2507.11412)
- Ettin-Enc-400M GLUE 90.8 vs ModernBERT-large 90.4 (one source); a second source gives 88.9 vs 88.4 at a different size. Conflicting; treat as unverified — [Ettin HTML](https://arxiv.org/html/2507.11412v1); [alphaxiv](https://alphaxiv.org/overview/2507.11412v1)
- Community reproduction on a classification dev set: ModernBERT 96.32 ± 0.15, Ettin-400M 96.17 ± 0.10 (single informal comment; weak evidence) — [Ettin paper discussion, huggingface.co/papers/2507.11412](https://huggingface.co/papers/2507.11412)
- The paper finds encoders lead on classification and retrieval while decoders lead on generation — [arXiv 2507.11412](https://arxiv.org/html/2507.11412v2)

### Inferences
- For a classification head, an Ettin or ModernBERT encoder is a light, licensable backbone. Ettin is Apache/MIT with open data (licence not verified in snippet).
- ModernBERT's training-data opacity is a reason to prefer Ettin for audit.

### Gaps
- EuroBERT: no results found; the three-way comparison asked for is not done.
- NeoBERT: not searched.
- LLM2Vec and decoder-to-encoder conversion: not searched.
- Post-training recipes (head-only vs LoRA vs full) for these encoders: not searched.

## Key Question 6: OOD robustness by size and architecture

### Takeaway
No evidence from this pass answers the encoder-vs-LLM OOD question directly for NLI or verification. The LLM-AggreFact leaderboard (which ranks LLMs and encoders on mixed domains) is the closest public proxy but was not loaded. The Ettin paper's classification-vs-generation split and the FinBERT generalization result (Nov 2025) are indirect support that encoders degrade out of domain.

### Cited Findings
- FinBERT limited beyond pretraining domain; LLMs generalize across sources and languages (Nov 2025 comparison) — [arXiv 2512.00946](https://arxiv.org/abs/2512.00946v1)
- ProtectAI injection classifier trained on in-distribution sets; its published accuracy is not an OOD estimate — [HF card](https://huggingface.co/ProtectAI/deberta-v3-base-prompt-injection-v2)
- Prompt Guard 2 embedded-injection recall of 1% vs its clean-benchmark recall of 64.9%–97.5% (vendor vs third-party) shows large shift sensitivity — secondary sources above

### Inferences
- The clearest signal is that task-specific encoder classifiers can look strong on their own test and fail on distribution shift (injection case). This argues for a held-out panel built from real agent-generated notes and tool outputs before any component is chosen.

### Gaps
- No controlled encoder-vs-LLM OOD comparison for NLI or verification was found.
- LLM-AggreFact per-dataset breakdown not read.
- No size-scaling OOD study found.

## Overall gaps and next steps
- Primary-source pass needed: Clef, Decider, d3, GLiNER2.5-Decide, Prompt Guard 2, Bespoke-MiniCheck, LLM-AggreFact leaderboard, arXiv 2610.17205.
- Measure p99 latency on one A6000 for: GLiNER2.5-Decide (340M), Clef-flash (9B), and one 27B decision model, plus a CPU run for the 340M encoder.
- Build an in-house held-out panel (value/unit/period/entity/actual-vs-guidance; hype; authority claims; injection in notes and tool output) before choosing a component. Vendor scores here are not decision-grade.
- Licence check before shortlisting: Clef and Decider (Apache 2.0 per secondary), GLiDE (community licence, restricted), Bespoke-MiniCheck (CC BY-NC, excluded for commercial use), HHEM-2.3 (closed).
