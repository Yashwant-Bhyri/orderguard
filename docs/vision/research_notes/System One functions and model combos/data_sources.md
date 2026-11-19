# Public datasets and data-generation methods for a trading-agent supervisor (as of November 2026)

Scope: datasets and generation methods for five supervisor learning problems: claim vs evidence verification (numbers, units, periods, entities, actual vs guidance), hype and manipulation, fake authority and prompt injection, agent trajectories with failure labels, and owner or investor preferences. Plus evidence on synthetic and counterfactual data.

Method note: about 23 search and fetch calls, above the usual budget. Licences were checked against the dataset or repo page where it was reachable. Where only a secondary source was found, this is marked "unverified". Nothing was checked against live download sizes.

**Licence flags (read first).**
- Non-commercial: FinanceBench open sample (CC BY-NC 4.0 on Hugging Face). Its full set needs a licence from Patronus AI.
- Eval-only restriction, not a licence: TRAIL's card says it is for evaluation and benchmarking, not for training systems that automate human evaluation. LLM-AggreFact says its data should not be used to pretrain or fine-tune models. Both matter for us because we want to train on these.
- Share-alike: VitaminC is cc-by-sa-3.0 on Hugging Face. Derived training data may need share-alike terms. Check with counsel before shipping a model trained on it.
- Conflicting licence statements: Fin-Fact (Apache-2.0 in YAML, MIT in body); FinQA (MIT on the GitHub page, CC BY 4.0 in a secondary table); FinanceBench (CC BY-NC on Hugging Face, MIT-style claimed by a secondary source).

## Financial claim and numeric verification

### Takeaway
There is one directly relevant claim-verification set (Fin-Fact, small). The large numeric-reasoning sets (FinQA, TAT-QA, ConvFinQA) test calculation over tables, not claim truth, so they need adapting. Numeric NLI (EQUATE) is old and small. The most useful source for our labels may be our own corrupted-claim generator, with a small expert-labelled eval set.

### Cited Findings
- **Fin-Fact**: 3,121 claims with professional fact-checker annotations, justifications, evidence and images, from IIT (Rangapur, Wang, Shu, 2023). Labels include Claim Label and Visualisation Bias Label. Licence conflict: YAML says apache-2.0; body says "released under the MIT License". Fit: low-to-medium. It is political and general finance misinformation, not numeric or period checks. [Source](https://huggingface.co/datasets/amanrangapur/Fin-Fact/blob/main/README.md); paper [arXiv 2309.08793](https://arxiv.org/abs/2309.08793v2)
- **FinQA**: question answering over earnings-report tables and text, with programme-of-operations annotations. Licence: MIT on the GitHub page; the page gives no QA-pair counts (it names test.json and a private_test.json). A secondary comparison table lists CC BY 4.0. [Source](https://github.com/czyssrs/FinQA)
- **TAT-QA**: tabular and textual financial QA. Licence: CC BY 4.0, from a secondary comparison table only; primary repo not checked. [Source](https://arxiv.org/abs/2109.00122v1)
- **ConvFinQA**: conversational numeric QA over the same kind of reports (EMNLP 2022). Licence: MIT per Papers with Code (secondary); primary repo not checked. [Source](https://aclanthology.org/2022.emnlp-main.421)
- **FinanceBench**: 10-K-based open-book QA. The open sample is 150 questions with source filings, CC BY-NC 4.0 on Hugging Face. Full set is licensed commercially from Patronus AI. Paper is [arXiv 2311.11944](https://arxiv.org/abs/2311.11944v1). Licence sources disagree. [Source](https://huggingface.co/api/datasets/PatronusAI/financebench)
- **EQUATE** (CoNLL 2019): five NLI test sets focused on quantities (approximation, ordinals, implicit quantities, quantifiers). Nine published NLI models did not beat a majority-class baseline on average. A symbolic baseline (Q-REAS) gained +24.2 on numeric tests but lost 8.1 on verbal reasoning. Licence: not verified. [Source](https://aclanthology.org/K19-1033)
- **VitaminC** (NAACL 2021): contrastive fact-verification pairs from Wikipedia revisions plus synthetic revisions, with over 400k claim-evidence pairs (GitHub says 450k+). Hugging Face says cc-by-sa-3.0. [Source](https://huggingface.co/datasets/tals/vitaminc/blob/main/README.md); [paper](https://arxiv.org/pdf/2103.08541)

### Inferences
- No public dataset checks units, periods, entity, and actual-vs-guidance in the way we need. Fin-Fact is the nearest claim-level set. FinQA and ConvFinQA give programme-level numeric labels that could be turned into claims by corruption.
- Corrupted claims built from FinQA or FinanceBench evidence would give period and unit labels for free, but FinanceBench's non-commercial terms bar its use for a commercial supervisor unless licensed.

### Gaps
- EDGAR and XBRL: not searched. The XBRL facts are structured and carry period and unit tags, so they are a likely source of programmatic claim-evidence pairs. Licence (SEC public domain expected) and XBRL dictionary details still need checking.
- Earnings-call datasets (guidance vs actual): not searched in this pass. The task needs a source for guidance statements and later reported actuals.

## General fact verification for transfer

### Takeaway
VitaminC is the best-documented contrastive transfer source found. LLM-AggreFact is a strong grounding evaluator but is eval-only. FEVER, SciFact, ANLI and WANLI were not checked in this pass, so their licences are open gaps.

### Cited Findings
- **VitaminC**: as above. Paper reports +10% accuracy on adversarial fact verification and +6% on adversarial NLI when trained with the contrastive data. These numbers are from a secondary summary of the paper. [Source](https://arxiv.org/pdf/2103.08541)
- **LLM-AggreFact**: aggregates 10 grounding and factual-consistency datasets (AggreFact-CNN, AggreFact-XSum, TofuEval, WiCE, REVEAL, ClaimVerify, FactCheck-GPT, ExpertQA, LFQA). Sentence-level human labels. Benchmark is for evaluation only and says its data should not be used in pretraining or fine-tuning. A secondary page says 11 datasets and 13,122 instances, which conflicts with the paper's 10. [Source](https://huggingface.co/datasets/lytang/LLM-AggreFact/blob/main/README.md); MiniCheck paper [arXiv 2404.10774](https://arxiv.org/abs/2404.10774)

### Inferences
- LLM-AggreFact is best used as a held-out eval for a grounding checker, not as training data. Keep it out of training.
- VitaminC is the only candidate here that we can train on, subject to share-alike terms.

### Gaps
- FEVER, SciFact, ANLI, WANLI: not searched. Licences and sizes not verified.

## Financial misinformation, hype and manipulation

### Takeaway
No ready-made, large, licensed corpus of labelled financial hype or pump-and-dump text was found. The usable options are research datasets tied to forums or Telegram, plus synthetic generation.

### Cited Findings
- **Nam and Skillicorn (2023)**: pairs stocks showing pump-and-dump price and volume shapes with forum posts from the same period (Reddit, Yahoo Finance). Best model 85% accuracy and 62% F1. Licence and download: not verified. [Source](https://arxiv.org/abs/2301.11403)
- **Telegram crypto pump-announcement dataset (preprint, 2026)**: message-window labels for pump-and-dump coordination. The paper argues that dictionary keyword heuristics are unreliable. Availability and licence: not verified. [Source](https://arxiv.org/html/2605.09431)
- **Fin-Fact** also has a visualisation-bias label, which is a form of misleading-presentation label. [Source](https://huggingface.co/datasets/amanrangapur/Fin-Fact/blob/main/README.md)

### Inferences
- Hype labels will probably have to be built in-house. The pump-and-dump price series is the stronger signal because it is not text-based. Pair it with forum timing from the Nam and Skillicorn data if licence allows.

### Gaps
- Financial sentiment and hype corpora (for example, FinancialPhraseBank-style sets): not searched.
- Licence and redistribution rules for forum-scraped data: not checked.

## Prompt injection and fake authority

### Takeaway
Several public injection sets exist, but each covers a different threat. For agent tool-output injection, AgentDojo and BIPIA are the most relevant. The deepset set is small, generic, and has a weak card. Licences vary.

### Cited Findings
- **deepset/prompt-injections**: 662 rows (546 train, 116 test); label 0 benign and 1 injection. Licence: apache-2.0. Card has no limitations, no provenance, and a title that does not match the dataset name. [Source](https://huggingface.co/datasets/deepset/prompt-injections)
- **AgentDojo** (ETH Zurich SPY Lab): agentic benchmark with tool use and injected tool outputs. Licence: MIT (repo page). Task counts were not stated on the page. [Source](https://github.com/ethz-spylab/agentdojo)
- **BIPIA** (Microsoft, arXiv 2312.14197): indirect injection across five scenarios and 250 attacker goals. One version reports 626,250 training and 86,250 test prompts. Code is at github.com/microsoft/BIPIA, but the README's to-do still lists uploading the dataset to Hugging Face, so the data must be built from scripts. Licence: not verified. [Source](https://github.com/microsoft/BIPIA); [paper](https://arxiv.org/abs/2312.14197)
- **Tensor Trust** (ICLR 2024, arXiv 2311.01011): human-made attacks and defences from an online game, about 563k attacks and 118k defences in the ICLR version (the arXiv v1 counts were lower). Licence: not found. [Source](https://arxiv.org/abs/2311.01011)
- **InjecAgent**: a fetch of the GitHub repo failed (connection refused). Counts and licence not verified.

### Inferences
- Use BIPIA or Tensor Trust for scale and variety of attack text. Use AgentDojo for end-to-end tool-injection tests.
- Fake authority (fake CFO or regulator text) is not covered directly by any of these. It will have to be generated from templates and checked by a small human-labelled set.

### Gaps
- Lakera Gandalf: not searched. Licence and whether a public dump exists are unknown.
- InjecAgent counts and licence: not verified.

## Agent trajectories with failure labels

### Takeaway
Three public trajectory sets have failure labels: Who&When, TRAIL, and AgentRewardBench. TRAIL is the closest match to our error taxonomy but has an eval-only restriction. Who&When gives agent and step labels but its licence could not be checked.

### Cited Findings
- **Who&When** (ICML 2025, arXiv 2505.00212): failure logs from 127 multi-agent systems, with the responsible agent, the decisive error step and a natural-language explanation. Best method gets 53.5% agent-level and 14.2% step-level accuracy. Code and data on GitHub and Hugging Face. The Hugging Face page returned HTTP 401 on fetch, so the licence is unverified. [Source](https://arxiv.org/abs/2505.00212); code [GitHub](https://github.com/mingyin1/Agents_Failure_Attribution)
- **TRAIL** (Patronus AI, arXiv 2505.08638): 148 traces (GAIA and SWE-Bench) with 1,987 OpenTelemetry spans, 575 with at least one error, 841 errors across 9 categories and 20 leaf types. Best model about 11% joint accuracy. Licence: MIT on the card, but the card restricts use to evaluation and benchmarking, not training systems that automate human evaluation. Split counts are inconsistent (117 and 31 in metadata; 118 and 30 in prose). GAIA traces came from o3-mini; SWE-Bench traces from claude-3-7-sonnet with injected constraints to cause errors. [Source](https://huggingface.co/datasets/PatronusAI/TRAIL/blob/main/README.md); [paper](https://arxiv.org/html/2505.08638v3)
- **AgentRewardBench** (arXiv 2504.08942): 1,302 web-agent trajectories from four agents across five benchmarks. Six experts gave three binary labels (success, side effects, repetition). Inter-annotator agreement on success 89.3%. LLM judges and rule-based evaluators both diverge from experts. Licence: not verified. [Source](https://arxiv.org/abs/2504.08942)

### Inferences
- TRAIL's error taxonomy fits our failure labels closely. Its eval-only restriction means we should use it to measure a supervisor, not to train one.
- Our own failure labels from the simulator (planted causes) can give step-level labels with known ground truth. The public sets are the external check.
- Trading-agent logs from public competitions were not searched in this pass.

### Gaps
- Public trading-agent competition logs: not searched.
- Who&When licence: not verified.

## Robo-adviser and investor preferences

### Takeaway
No public dataset of investor preference labels was found in this pass. This is a real gap.

### Cited Findings
- None found in this pass.

### Inferences
- Owner preferences will probably need to be elicited or simulated (for example, persona-based questionnaires) and validated with a small human sample. Public datasets are unlikely to match our preference schema.

### Gaps
- Robo-adviser and investor-survey datasets (for example, suitability questionnaires, behavioural finance surveys): not searched. Licences and personal-data rules would need checking.

## Synthetic and counterfactual data quality

### Takeaway
The most recent evidence (EACL 2026 Findings) says LLM-generated NLI training examples are often too easy, and that harder synthetic examples and harder human examples help more on challenging out-of-distribution sets. Contrastive, minimal-pair data (VitaminC) helps adversarial verification. Difficulty-aware selection is the lever to use.

### Cited Findings
- **Stacey et al., EACL 2026 Findings** ("Improving the OOD Performance of Closed-Source LLMs on NLI Through Strategic Data Selection", pp. 5378–5404; first posted as arXiv 2505.20209): under a fixed budget of 10,000 training instances, replacing part of the training set with LLM-generated examples helped on simpler OOD data (up to +3.7%). The authors find synthetic examples are often too simple. Prompting for more complex synthetic data improves both easy and challenging OOD sets. Upsampling harder training examples improves robustness on highly complex OOD sets (up to +1.5%). [Source](https://aclanthology.org/2026.findings-eacl.286); [arXiv](https://arxiv.org/abs/2505.20209)
- **VitaminC** (NAACL 2021): contrastive evidence pairs (near-identical wording, one supports the claim and one does not). Trained models gained about 10% on adversarial fact verification and 6% on adversarial NLI, per the paper summary. [Source](https://arxiv.org/pdf/2103.08541)
- **Counterfactual data for fallacy detection** (ACL 2026 SRW, pp. 363–374): minimal-pair counterfactual augmentation. Not an NLI or verification study, so transfer to our task is weak. Noted for the counterfactual-generation method only. [Source](https://aclanthology.org/2026.acl-srw.30.pdf)
- **Difficulty-aware selection** (EACL 2026): the same paper finds that upsampling harder human-written examples helps on challenging OOD sets, while synthetic data mainly helps on easier ones. [Source](https://aclanthology.org/2026.findings-eacl.286)

### Inferences
- Our programmatic corruptions (number shifts, unit swaps, period swaps, context lifts) are the kind of minimal-pair data that VitaminC showed helps. They are probably too easy on their own, per the EACL finding. Add difficulty control: keep corruptions that a baseline gets wrong, and mix in human-written hard cases.
- Test OOD robustness on held-out, human-written sets such as EQUATE and LLM-AggreFact, not on our own generator's output, to avoid measuring the generator against itself.
- For the simulator with planted causes, the labels are exact by construction. The risk is that they are too clean. Check whether the supervisor learns the simulator's surface cues by testing on a second simulator or on public data.

### Gaps
- No direct evidence found on simulator-generated financial data quality, or on programmatic number, unit, and period corruptions specifically. This needs a targeted search or an internal pilot.
- No evidence found on how well LLM-judged labels agree with human labels for financial claims.
- Counterfactual augmentation evidence for NLI beyond VitaminC: not checked in this pass.

## Summary of what to use

| Use | Dataset | Licence | Status |
|---|---|---|---|
| Train, claim check | VitaminC | cc-by-sa-3.0 (share-alike) | Usable, check share-alike |
| Train, numeric | FinQA, ConvFinQA | MIT (FinQA primary); ConvFinQA unverified | Check primary repo |
| Eval only, grounding | LLM-AggreFact | Not verified; eval-only use | Keep out of training |
| Eval only, agent failures | TRAIL | MIT on card, but eval-only restriction | Use for measurement |
| Injection, train or eval | deepset prompt-injections | apache-2.0 | Small, weak card |
| Injection, eval | AgentDojo | MIT | Good for tool injection |
| Injection, scale | BIPIA, Tensor Trust | BIPIA unverified; Tensor Trust not found | Check before use |
| Financial QA, eval | FinanceBench | CC BY-NC 4.0 (open sample) | Non-commercial; licence needed |
| Fact check, claim level | Fin-Fact | apache-2.0 vs MIT conflict | Resolve before use |
| Agent failures, step labels | Who&When | Unverified (HF returned 401) | Check licence |
