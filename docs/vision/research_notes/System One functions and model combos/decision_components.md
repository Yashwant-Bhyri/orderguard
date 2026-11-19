# Non-language decision components for an AI-agent supervisor (as of November 2026)

Scope: the non-language stack that turns about 40 exact code features (drift, limits, quote mismatches, provenance) plus a few text-reader scores into one calibrated probability that the owner would not endorse an action. Requirements: monotone in every risk signal; cause named per decision; statistical bound on bad actions allowed; few-shot per-owner adaptation; novelty detection; slow-drift monitoring of trajectories; CPU inference at p99 <= 50 ms.

Method note: 16 web searches were run (the researcher ceiling). Most results were abstracts and snippets, not full papers. Library version numbers and current docs were not checked against live pages. Claims marked "(background)" come from general knowledge and were not verified in this session.

Headline: the pieces that exist and fit the requirements are (1) a monotone-constrained additive or boosted scorer, (2) split/weighted conformal or learn-then-test for the false-allow bound, (3) temperature or isotonic calibration on a held-out set, (4) conformal or e-value novelty flags, and (5) e-detector or CUSUM-style monitors on trajectories. TabPFN-class in-context learners are the weakest fit for the 50 ms CPU budget and should be used only offline, or after distillation, as an owner-adaptation prior.

## 1. Monotone, explainable scorer

### Takeaway
Monotone gradient-boosted trees (LightGBM, XGBoost) and EBMs (InterpretML) both accept per-feature monotone constraints. Monotonicity is only guaranteed for the constrained features, and it can be undone by correlated unconstrained features, so it has to be verified on the fitted shape functions. Monotone NAMs from the credit-scoring literature are the closest published fit for "monotone in every signal plus explainable".

### Cited Findings
- EBM takes a `monotone_constraints` argument, default `None`, one direction value per feature — [interpret.ml ExplainableBoostingRegressor docs](https://interpret.ml/docs/python/api/ExplainableBoostingRegressor.html); also summarized in [tessl registry glassbox docs](https://tessl.io/registry/tessl/pypi-interpret/files/docs/glassbox.md).
- Pitfall: if two copies of a feature exist and only one is constrained, the model can use the correlated feature to undo monotonicity — reported in [interpret GitHub issue #184](https://www.github.com/interpretml/interpret/issues/184). The official docs make a related recommendation to verify the fitted behavior — [interpret.ml EBM docs](https://interpret.ml/docs/ebm).
- A third-party blog says EBM monotone constraints can fall short in low-data tails; single secondary source — [burning-cost EBM insurance post](https://burning-cost.github.io/2026/03/09/explainable-boosting-machines-for-insurance-pricing).
- LightGBM's `monotone_constraints` takes a per-feature list such as `[-1, 0, 1]`; `monotone_constraints_method` is listed with values `basic` (default per one mirror), `intermediate`, and (per rtemis docs) `advanced`. Option set differs by version and the mirrors are third-party — [LightGBM Parameters mirror](https://www.aidoczh.com/LightGBM/Parameters.html), [rtemis setup_LightCART](https://rdrr.io/cran/rtemis/man/setup_LightCART.html). A 2020 arXiv paper proposes a better enforcement method than LightGBM's earlier implementation on Adult — [arXiv 2011.00986](https://arxiv.org/abs/2011.00986v1).
- XGBoost has a monotonic-constraints tutorial — [XGBoost docs](https://xgboost.readthedocs.io/en/latest/tutorials/monotonic.html).
- Monotone Neural Additive Models were proposed for regulated credit scoring, arguing that without monotonicity even an accurate ML model may struggle to gain regulatory acceptance — [arXiv 2209.10070](https://ar5iv.labs.arxiv.org/html/2209.10070).
- A December 2025 credit-risk paper reports that appropriately specified monotone constraints can keep interpretability with small accuracy losses, especially on large portfolios — [arXiv 2512.17945](https://arxiv.org/pdf/2512.17945v2).
- A 2023 ICML paper argues pairwise monotonicity (e.g., recent past dues weighing more than older ones) is often neglected in the literature — cited via [arXiv 2209.10070 search snippet](https://ar5iv.labs.arxiv.org/html/2209.10070). Title not fetched.
- Vendor view (FICO): traditional ML rarely yields full monotonicity without explicit constraints — [FICO blog](https://marketplace.fico.com/blogs/trusted-ai-challenge-monotonicity-and-palatability). Vendor source, not independent.

### Inferences
- A monotone additive model (EBM or monotone NAM) with 40 exact features plus a few text scores is the most defensible choice for "monotone in every signal and names the cause": the per-feature shape functions are the explanation, so the cause is the feature with the largest signed contribution.
- Monotone in the strict sense needs every input that could carry the same signal to be constrained, or a post-fit check on the shape functions. Text-reader scores that correlate with exact features are the likely route for the #184 pitfall. Recommend a unit test that perturbs each feature alone and asserts the sign of the output change.
- LightGBM monotone trees give monotonicity by construction for constrained features, with TreeSHAP for per-decision attribution. Its per-decision cause is the SHAP contribution, which is not guaranteed to be monotone in the feature itself. For the requirement "monotone in every signal", a constrained boosted model plus a checker is viable; an EBM is more direct.

### Gaps
- No primary-source verification of EBM's full direction-value list or of the current LightGBM `monotone_constraints_method` default in official docs.
- Lattice models and monotone neural networks (certified monotone MLPs) were not searched. Background: lattice models give monotonicity by construction; monotone MLPs typically constrain weights.
- No accuracy-under-shift comparison between EBM, monotone GBDT, and monotone NAM was found.
- The regulatory text (SR 11-7 / OCC 2011-12, and the 2021 update the NAM paper cites) was not retrieved.

## 2. Statistical bound on bad-action allowance (conformal risk control, learn-then-test, selective prediction)

### Takeaway
Conformal risk control (CRC) gives a finite-sample guarantee on expected loss for monotone loss functions, and learn-then-test (LTT) extends risk control to non-monotone losses via multiple testing. These bounds hold under exchangeability. Under covariate shift they need a known or estimated likelihood ratio, and under adversarial inputs they can fail. Use the bound as a calibrated rate over a labeled audit set, not as a per-decision guarantee.

### Cited Findings
- CRC (Angelopoulos, Bates, Fisch, Lei, Schuster, ICLR 2024) controls the expected value of any monotone loss; reduces to split conformal in the classic case; tight up to O(1/n) — [ICLR 2024 abstract](https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html), [arXiv 2208.02814](https://arxiv.org/abs/2208.02814).
- The guarantee can fail arbitrarily badly for non-monotone losses (Proposition 1 in the CRC paper) — [arXiv 2208.02814](https://arxiv.org/abs/2208.02814).
- A 2026 follow-up, "Conformal Risk Control for Non-Monotonic Losses" (arXiv 2602.20151), decouples the proof into monotonicity implies stability, and stability implies risk control — [arXiv 2602.20151](https://arxiv.org/html/2602.20151). Abstract-level read only.
- LTT (Angelopoulos, Bates, Candès, Jordan, Lei; arXiv 2110.01052; reported in Annals of Applied Statistics 2025) treats risk control as multiple hypothesis testing over candidate parameters, handles non-monotone risks, gives explicit finite-sample guarantees for bounded risks, and needs no retraining — [arXiv 2110.01052](https://arxiv.org/pdf/2110.01052v4), [Stanford GSB record](https://www.gsb.stanford.edu/faculty-research/publications/learn-then-test-calibrating-predictive-algorithms-achieve-risk).
- Weighted conformal under covariate shift (Tibshirani, Barber, Candès, Ramdas 2019): valid if the test/train covariate likelihood ratio is known; the guarantee degrades with estimation error of the ratio; assumes the conditional law of Y given X is unchanged — [arXiv 1904.06019](https://arxiv.org/abs/1904.06019) (via search snippets), [Gentle introduction arXiv 2107.07511](https://arxiv.org/pdf/2107.07511).
- Training-conditional coverage under covariate shift (2025-2026 preprint) finds the variance proxy depends on the chi-squared divergence of the shift; clipping the likelihood ratio is one way to narrow valid sets — [arXiv 2609.33456](https://arxiv.org/pdf/2609.33456). Preprint, not verified beyond abstract.
- Adaptive Conformal Inference (Gibbs and Candès, NeurIPS 2021) keeps a time-averaged coverage guarantee with no distributional assumption, approximately tight in the worst case — [arXiv 2106.00170](https://arxiv.org/pdf/2106.00170), [NeurIPS abstract](https://proceedings.neurips.cc/paper/2021/hash/0d441de75945e5acbc865406fc9a2559-Abstract.html). The guarantee is on long-run coverage, not per step.
- Conformal novelty detection: split conformal p-values give a bound on false positives for a new normal point under exchangeability, and work with any anomaly score — [arXiv 2602.14251 appendix](https://arxiv.org/pdf/2602.14251). Full-conformal e-values with FDR control under shift are proposed by Lee, Popov, Ren — [arXiv 2501.02703](https://arxiv.org/abs/2501.02703).
- Boundary FDR caveat: applying Benjamini–Hochberg to conformal p-values can inflate false discoveries at the rejection boundary — [arXiv 2601.02610](https://arxiv.org/abs/2601.02610).
- Adversarial caveat: adversarial perturbations can substantially raise the FDR of AdaDetect (a learned conformal novelty detector) while power stays high — [arXiv 2510.00463](https://www.arxiv.org/abs/2510.00463).

### Inferences
- The "statistical bound on how often bad actions are allowed" should be an LTT or CRC bound with loss = indicator(allowed and owner would not endorse), chosen threshold on the calibrated score. The bound holds in expectation over the calibration draw and the test point under exchangeability. It is not a per-decision guarantee.
- Under agent-generated inputs, the calibration set is not exchangeable with future actions (the agent adapts to the supervisor). Expect the bound to be optimistic. Mitigate with ACI-style online updating and periodic re-audits, and report the bound with its assumption.
- Mondrian (class- or owner-conditional) conformal gives per-owner coverage but shrinks calibration sets; with few labels per owner, the bound is wide. This is the central tension with the few-shot-adaptation requirement.
- Background (not verified here): crepes and MAPIE implement split and Mondrian conformal, and MAPIE has risk-control utilities. Confirm versions and APIs before adoption.

### Gaps
- No direct evidence on conformal risk control under adversarial agent behavior. The 2510.00463 result is for novelty detection, not CRC.
- Did not verify whether the non-monotone CRC extension (2602.20151) has a practical cost in tightness.
- Did not search selective prediction (SelectiveNet, risk-coverage curves) or the Chow rejection literature.

## 3. Calibration

### Takeaway
Temperature scaling is cheap but is fit once on clean data and can be badly miscalibrated across domains. Multi-domain or input-dependent temperature, and calibration objectives other than log-loss, reduce that gap. Isotonic and ensembles were not searched in depth.

### Cited Findings
- Multi-domain temperature scaling (Yu et al., NeurIPS 2022): standard TS can be badly miscalibrated on a single domain even when pooled calibration looks fine; learns an input-dependent temperature — [NeurIPS 2022 paper](https://proceedings.neurips.cc/paper_files/paper/2022/file/b054fadf1ccd80b37d465f6082629934-Paper-Conference.pdf).
- Soft calibration objectives (arXiv 2108.00106) beat log-likelihood TS, with larger gains under dataset shift — [arXiv 2108.00106](https://arxiv.org/pdf/2108.00106).
- A 2026 geospatial foundation model study argues temperature scaling fit on clean data never sees corrupted inputs, so it cannot correct shifts it never saw — [arXiv 2608.16614](https://arxiv.org/pdf/2608.16614). Recent preprint; excerpt only.
- Ovadia et al. (2019), as summarized in later papers, found accuracy and calibration deteriorate under shift. Secondhand summary from search; the original paper was not retrieved in this session.

### Inferences
- For a supervisor, calibrate on a held-out set that spans owner and agent types (not the training distribution). Re-fit temperature when the monitor from section 6 fires.
- Monotonicity and calibration interact: a temperature (single scalar) preserves ranking and therefore preserves monotonicity. Input-dependent temperature or isotonic calibration can break the signed-contribution property unless constrained. Use a global scalar or a monotone calibration map.

### Gaps
- Isotonic regression, Platt scaling, and ensemble calibration were not searched. Background: isotonic is monotone by construction, but it is step-wise and needs enough labeled points per bin.
- No direct comparison of calibration error under shift for tabular models (as opposed to vision/geo models).

## 4. Few-shot owner adaptation

### Takeaway
In-context tabular learners (TabPFN-2.5, TabICL) have the strongest published few-shot evidence, but on CPU they are too slow for the 50 ms p99 budget unless used offline or distilled. Hierarchical or partial-pooling models and preference-style updates are cheaper and easier to make monotone, but the search did not find direct evidence for them on owner-level supervision data.

### Cited Findings
- TabPFN-2.5 (Prior Labs, arXiv 2511.08667, revised Feb 2026) reports scale up to about 50,000 rows and 2,000 features, and outperformance on TabArena-Lite. These are the authors' own claims — [arXiv 2511.08667](https://arxiv.org/pdf/2511.08667), [Prior Labs model report](https://priorlabs.ai/technical-reports/tabpfn-2-5-model-report).
- TabPFN-2.5 default vs XGBoost win rate: 100% on classification up to 10K rows and 500 features; 87% on larger datasets, per the authors — [arXiv 2511.08667](https://arxiv.org/pdf/2511.08667). Author-reported.
- A third-party study (TREDBench) reports TabPFN-2.5 was outperformed on 29 of 35 regression datasets by a synthetic-adaptation method. Seen only in a search summary; the source paper's URL was not confirmed, so treat as unverified.
- TabICL (Qu et al., ICML 2025) is a classification foundation model for large tables, pretrained on synthetic data up to 60K samples, scaling to 500K; on par with TabPFNv2 while up to 10x faster; single forward pass with no parameter updates at inference — [arXiv 2502.05564](https://arxiv.org/pdf/2502.05564), [ICML 2025 page](https://proceedings.mlr.press/v267/qu25d.html). Covers classification in the snippets.
- CPU latency: Prior Labs FAQ says TabPFN is slow on CPU, CPU/MPS are usable only for small datasets, and recommends a GPU; the PyPI page says CPU use was limited to about 1,000 samples in older versions and about 5,000 in newer ones — [Prior Labs FAQ](https://docs.priorlabs.ai/faq.md), [PyPI tabpfn](https://pypi.org/project/tabpfn). By default most fitting runs inside predict(), so latency scales with training rows; `fit_mode="fit_with_cache"` is the documented speed-up for repeated predictions — [Prior Labs FAQ](https://docs.priorlabs.ai/faq.md).
- One comparison reports TabPFN at about 101 ms per inference, versus 0.2–2.4 ms for classical models; hardware not stated. Seen in a search summary; the source paper was not confirmed (a candidate is arXiv 2512.00888, unverified). Indicative only.
- One practitioner measured TabICL at about 15 s on CPU vs about 0.5 s on GPU for one dataset — [mindfulmodeler post](https://mindfulmodeler.substack.com/p/making-tabular-foundation-models). Single anecdote.
- Vendor offers a distillation of TabPFN-2.5 into an MLP or tree ensemble with much lower latency, preserving most accuracy — [Prior Labs docs/search summary](https://docs.priorlabs.ai/faq.md). Vendor claim; not verified.
- Tab2Visual (arXiv 2502.07181) and TuneTables (arXiv 2402.11137) are related small-data adaptation methods; not evaluated here.

### Inferences
- A direct TabPFN call at p99 <= 50 ms on CPU is very unlikely given the 101 ms figure and the CPU limits. Do not put TabPFN on the request path. Options: (a) offline use to produce pseudo-labels or priors that train a cheap per-owner model; (b) distilled MLP or tree ensemble if the vendor distillation is validated on our data; (c) fit_with_cache with a small per-owner context, if measured p99 on the target CPU meets budget.
- The owner-specific part is likely a small number of parameters per owner. A monotone model with owner-level offsets or a hierarchical intercept (partial pooling) keeps the monotone shape and the bound structure, and can be updated from a few labels. Recommend a shrinkage prior on the owner offset and report the posterior width as the adaptation uncertainty.
- Few labels per owner also widen Mondrian conformal sets (section 2), so the owner adaptation and the bound trade off. Use a pooled bound plus per-owner shift check, not per-owner bounds, until enough labels exist.

### Gaps
- No evidence found on TabPFN or TabICL for owner-level supervision of a safety judgment (few labels, label noise, changing preference). All evidence is generic tabular benchmarks.
- Hierarchical Bayesian, preference learning (Bradley-Terry, DPO-style on scores), and Bayesian updating were not searched.
- Latency numbers are from non-matching hardware and dataset sizes. A benchmark on the target CPU is required before any claim about p99.

## 5. Novelty and OOD detection

### Takeaway
Energy and Mahalanobis scores were established on image models, and the search found no clean tabular-plus-embedding benchmark. The only tabular-relevant evidence reports that EBM-based OOD detectors do not consistently beat baselines on tabular data. Conformal novelty detection with a calibrated false-alarm rate is the best-supported option for the requirement, and it still assumes exchangeability.

### Cited Findings
- Energy scores beat softmax on image OOD benchmarks, but neither Mahalanobis nor energy dominates across OOD sets (CIFAR-10 tables) — [arXiv 2010.03759](https://arxiv.org/pdf/2010.03759).
- Mahalanobis, Gram and energy statistics vary widely across OOD types; combining them reduces variance — [arXiv 2206.09522](https://arxiv.org/pdf/2206.09522). CIFAR-10 and SVHN only.
- Elflein et al. study EBM-trained OOD detection on tabular and image data and find no consistent advantage for EBMs — [arXiv 2107.08785 references](https://arxiv.org/pdf/2107.08785v1.pdf), [Elflein et al. search summary](https://www.emergentmind.com/papers/2107.08785). Tabular datasets include Segment and Sensorless; values not seen.
- Split-conformal novelty bound and the boundary-FDR and adversarial caveats are in section 2.
- A 2026 multi-agent tabular anomaly paper exists (arXiv 2602.14251), not evaluated.

### Inferences
- For tabular-plus-embedding features, the defensible stack is: a kNN or Mahalanobis distance on the standardized exact features and a text embedding projection, with the conformal p-value from a held-out normal set. This gives a calibrated alert rate, which is what the owner needs, and it fits the CPU budget (kNN over a bounded reference set is fast).
- Isolation forest is cheap and handles mixed features, but it has no calibration guarantee. Use it as a secondary score only.
- Novelty should feed the supervisor as an additional monotone risk signal, not as a bypass. Otherwise an attacker could trigger "novel" to escape the model.

### Gaps
- No tabular OOD benchmark with Mahalanobis, energy, kNN, and isolation forest was found.
- The embedding dimensions and the choice of text encoder for the text-reader scores are not addressed by the search.
- kNN latency at the reference-set sizes expected here was not measured.

## 6. Sequential drift detection on agent trajectories

### Takeaway
CUSUM and Page-Hinkley are cheap, label-free-capable detectors for mean shift, and they run fast on CPU. E-detectors (Shin, Ramdas, Rinaldo) give nonparametric, anytime-valid false-alarm control with a guaranteed average run length, which is the stronger fit for "monitor an agent slowly drifting from a mandate". Benchmarks show ADWIN often beats PHT and CUSUM, so the choice depends on the drift type.

### Cited Findings
- E-detectors (Shin, Ramdas, Rinaldo, NEJSDS 2024): nonparametric, anytime-valid analogues of CUSUM and Shiryaev–Roberts, built from e-values for bounded, sub-Gaussian, Bernoulli or Poisson observations, with a guaranteed average run length to false alarm under every distribution in the pre-change class — [arXiv/search summary, edetect R manual](https://cran.r-universe.dev/edetect/doc/manual.html). The R package `edetect` implements them.
- Anytime-valid e-processes for monitoring whether a deployed model's calibration has shifted, with alarm probability under the null at most alpha for all time (Farran, 2026 preprint). Seen in a search summary; the preprint URL was not confirmed, so treat as unverified.
- Ville's inequality gives the anytime guarantee; e-values are increments of nonnegative supermartingales — [E-values Wikipedia](https://en.wikipedia.org/wiki/E-values).
- Benchmarks: a MOA-based comparison of 16 drift detectors (Mahgoub et al., 2023) on accuracy, runtime and memory — seen in a search summary, source not confirmed. A stream-learning benchmark on real data tested PHT and CUSUM against DDM, EWMA, ADWIN, SEED, STEPD (MOA defaults, 1000-example window, minimum 100 examples) — [arXiv 2005.00113](https://arxiv.org/pdf/2005.00113).
- On a float-data framework, Page-Hinkley outperformed ADWIN on one dataset, though no method did well — [arXiv 2204.13625](https://arxiv.org/pdf/2204.13625).
- In a wireless concept-drift study, ADWIN and DDM outperformed PHT and CUSUM — [arXiv 2508.00042](https://arxiv.org/pdf/2508.00042). Results vary by dataset and parameters.
- PHT and CUSUM can run without labels, which matters when verification delay is high — search summary of a 2026 label-free drift evaluation paper; URL not confirmed.
- Bayesian online change-point detection (Adams and MacKay) was not searched.

### Inferences
- Each agent trajectory yields a sequence of per-step risk scores in [0,1]. An e-detector on the Bernoulli "owner would not endorse" indicator (or on bounded risk scores) gives an anytime false-alarm bound for the drift alarm. This matches the request for a statistical guarantee on monitoring, not just on decisions.
- Slow drift toward an out-of-mandate goal is a mean shift in a small rate, so CUSUM-type or e-detector with a small drift parameter is appropriate. Abrupt changes are better handled by a plain threshold on the monotone score.
- Two monitors are needed: one on the score distribution (calibration drift, e-process) and one on the feature distribution (covariate shift, section 5). Keep them separate so an alarm names which one fired.

### Gaps
- No evidence on drift in agent trajectories specifically. All evidence is classical stream data.
- The pre-change class and the choice of e-value for each feature were not checked.
- Bayesian online change-point detection was not searched; background only.

## 7. Cost-sensitive thresholding and coverage at a fixed false-allow rate (evaluation)

### Takeaway
Report the false-allow rate and the coverage of "allowed" decisions together, with the conformal or LTT bound beside the empirical value. Cost-sensitive thresholds should be set on the calibrated probability by minimizing expected owner cost, and the threshold must be re-audited under drift.

### Cited Findings
- LTT explicitly targets a user-chosen error rate with finite-sample guarantees on bounded risks, and gives worked examples including false discovery rate control in multilabel classification — [arXiv 2110.01052](https://arxiv.org/pdf/2110.01052v4).
- CRC targets expected loss at a chosen level, e.g., a false-negative rate — [ICLR 2024 abstract](https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html).

### Inferences
- Metric: the empirical false-allow rate on a held-out audit set, with the upper confidence bound from LTT or CRC. Also report coverage (fraction of owner-endorsed actions that pass) so that tightening cannot be hidden.
- Tighten-only: the decision is "allow" only if the calibrated score is below threshold AND no hard-limit rule fires. This makes the overall policy monotone, provided the scorer is monotone and the rule set is a logical OR of risk conditions.
- Cost-sensitive threshold: choose the point on the risk-coverage curve that minimizes expected cost with the owner's costs. Owner costs are not in the sources and must be elicited.

### Gaps
- No source found on cost-sensitive thresholding practice in credit or fraud settings, despite the suggested source list. Not searched within the budget.
- Risk-coverage and selective-classification literature not searched.

## 8. Cross-cutting: theory vs practice under shift

### Takeaway
Each guarantee in this catalogue has a theoretical premise (exchangeability, known likelihood ratio, bounded losses, correct pre-change class) that agent-generated inputs are likely to break. Plan on monitoring the premises and reporting the bound with its assumptions, not on the bound alone.

### Cited Findings
- Weighted conformal needs the likelihood ratio; estimation error degrades the guarantee — [arXiv 1904.06019 summary](https://arxiv.org/abs/1904.06019).
- Conformal novelty FDR can be broken by adversarial perturbation — [arXiv 2510.00463](https://www.arxiv.org/abs/2510.00463).
- Conformal FDR at the boundary can be inflated — [arXiv 2601.02610](https://arxiv.org/abs/2601.02610).
- ACI gives long-run, not per-step, coverage — [arXiv 2106.00170](https://arxiv.org/pdf/2106.00170).

### Inferences
- Theory-level guarantees (hold under stated assumptions): CRC and LTT bounds on a calibration set, e-detector anytime false-alarm bounds, split-conformal novelty bounds, ACI long-run coverage.
- Practice-level expectations (not proven here): bounds become optimistic when the agent adapts to the supervisor; the likelihood-ratio estimate is poor on sparse owner data; EBM-style OOD detectors do not beat simple baselines on tabular data.
- A decision record should store the assumptions in force: calibration-set provenance, shift-monitor state, and the owner partition used.

### Gaps
- No empirical study of these guarantees under agent-generated or adversarial trajectories was found.

## Latency budget note (CPU, p99 <= 50 ms)

Inference for a monotone GBDT or EBM over about 40 features plus a few text scores is a small fraction of the budget on CPU (background: sub-millisecond per row for tree ensembles of modest size). Conformal p-values, temperature scaling, and CUSUM/e-detector updates are O(1) or O(n_calibration) per call. kNN novelty is O(reference-set size) and needs an index. The only component that threatens the budget is TabPFN-class in-context inference (about 101 ms per inference in one report, CPU limits of about 1-5K rows), so keep it off the request path. Verify all of this with a benchmark on the target CPU; no benchmark in this session measured the full stack.

## Summary of candidate components

| Function | Primary candidate | Alternatives | Guarantee type | CPU cost | Main pitfall |
|---|---|---|---|---|---|
| Monotone scorer | EBM with monotone constraints | LightGBM/XGBoost monotone + TreeSHAP; monotone NAM; lattice (not searched) | None (constraint by construction, verify) | Low | Correlated unconstrained feature undoes monotonicity |
| Bad-allow bound | LTT or CRC on audit set | Split/weighted conformal | Finite-sample under exchangeability | Negligible | Exchangeability broken by adaptive agent |
| Calibration | Global temperature (keeps ranking) | Monotone isotonic; multi-domain TS | Asymptotic / empirical | Negligible | Fit on clean data only |
| Owner adaptation | Partial-pooled offset on monotone model | TabPFN-2.5 offline or distilled; TabICL offline | Posterior / empirical | Low (offset); high (TabPFN) | TabPFN exceeds CPU budget |
| Novelty | Split-conformal p-value on kNN/Mahalanobis | Energy score, isolation forest | Bounded FPR under exchangeability | Low-moderate | Adversarial inputs can raise FDR |
| Drift (trajectory) | E-detector / CUSUM on bounded risk | Page-Hinkley, ADWIN, Bayesian change-point (not searched) | Anytime false-alarm (e-detector) | Very low | Pre-change class misspecified |
| Evaluation | False-allow rate with LTT upper bound | Coverage, expected owner cost | Same as bound | Negligible | Reporting empirical rate without bound |

## Overall gaps
- Not searched: lattice models, certified monotone MLPs, isotonic and ensemble calibration, Mondrian conformal details, hierarchical Bayesian and preference learning, Bayesian online change-point, risk-coverage and selective prediction, cost-sensitive thresholding in credit or fraud, SR 11-7 text.
- Library versions and APIs were not checked against current documentation pages.
- No benchmark on CPU latency of the full stack. The TabPFN latency figures are indicative only.
