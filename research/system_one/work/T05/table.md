# T05 reader tournament

Sample: 1440 actions / 360 episodes, seed 20261119.

## AUROC (bootstrap 95% CI over episodes)

| feature | reader | unshifted | shifted |
|---|---|---|---|
| hype | lexicon | 0.806 [0.708, 0.893] | 0.671 [0.603, 0.742] |
| hype | nli | 1.000 [1.000, 1.000] | 0.999 [0.998, 1.000] |
| hype | embed_lr | 0.993 [0.983, 0.999] | 0.966 [0.947, 0.985] |
| hype | decision | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| authority_language | lexicon | 0.913 [0.847, 0.966] | 0.845 [0.767, 0.918] |
| authority_language | nli | 1.000 [1.000, 1.000] | 1.000 [0.999, 1.000] |
| authority_language | embed_lr | 0.977 [0.955, 0.992] | 0.936 [0.900, 0.968] |
| authority_language | injection | 0.454 [0.378, 0.529] | 0.532 [0.458, 0.610] |
| authority_language | injection_fmops | 0.567 [0.473, 0.651] | 0.624 [0.516, 0.728] |
| authority_language | decision | 0.969 [0.932, 0.998] | 0.924 [0.860, 0.973] |
| support_gap | lexicon | 0.884 [0.814, 0.939] | 0.843 [0.775, 0.902] |
| support_gap | nli | 0.997 [0.993, 0.999] | 0.990 [0.983, 0.995] |
| support_gap | embed_lr | 0.657 [0.582, 0.727] | 0.682 [0.601, 0.752] |
| support_gap | decision | 0.999 [0.997, 1.000] | 0.998 [0.995, 1.000] |

## Calibration (ECE / Brier, unshifted and shifted ref)

| feature | reader | ECE unshifted | Brier unshifted | ECE shifted | Brier shifted | n shifted |
|---|---|---|---|---|---|---|
| hype | lexicon | 0.024 | 0.021 | 0.043 | 0.042 | 592 |
| hype | nli | 0.276 | 0.095 | 0.246 | 0.078 | 592 |
| hype | embed_lr | 0.321 | 0.146 | 0.360 | 0.184 | 592 |
| hype | decision | 0.274 | 0.100 | 0.288 | 0.112 | 592 |
| authority_language | lexicon | 0.031 | 0.022 | 0.041 | 0.034 | 612 |
| authority_language | nli | 0.343 | 0.210 | 0.343 | 0.205 | 612 |
| authority_language | embed_lr | 0.209 | 0.081 | 0.152 | 0.074 | 612 |
| authority_language | injection | 0.873 | 0.868 | 0.903 | 0.901 | 612 |
| authority_language | injection_fmops | 0.899 | 0.899 | 0.905 | 0.904 | 612 |
| authority_language | decision | 0.495 | 0.339 | 0.553 | 0.416 | 612 |
| support_gap | lexicon | 0.545 | 0.352 | 0.540 | 0.361 | 624 |
| support_gap | nli | 0.039 | 0.016 | 0.066 | 0.032 | 624 |
| support_gap | embed_lr | 0.533 | 0.380 | 0.519 | 0.369 | 624 |
| support_gap | decision | 0.226 | 0.083 | 0.209 | 0.074 | 624 |

## Eligible pass-bar reader vs lexicon (shifted ref)

| feature | eligible reader | AUROC | delta | delta 95% CI | beats lexicon |
|---|---|---|---|---|---|
| hype | decision | 1.000 | 0.329 | [0.258, 0.400] | True |
| authority_language | decision | 0.924 | 0.079 | [0.018, 0.149] | True |
| support_gap | decision | 0.998 | 0.155 | [0.096, 0.224] | True |

## Raw best reader (may be ineligible; shifted ref)

| feature | raw best | AUROC | delta | delta 95% CI | beats lexicon |
|---|---|---|---|---|---|
| hype | decision | 1.000 | 0.329 | [0.258, 0.400] | True |
| authority_language | nli | 1.000 | 0.155 | [0.080, 0.239] | True |
| support_gap | decision | 0.998 | 0.155 | [0.096, 0.224] | True |

## Selected channel reader vs lexicon (shifted ref)

| feature | selected reader | AUROC | delta | delta 95% CI | beats lexicon |
|---|---|---|---|---|---|
| hype | nli | 0.999 | 0.328 | [0.256, 0.399] | True |
| authority_language | decision | 0.924 | 0.079 | [0.018, 0.149] | True |
| support_gap | nli | 0.990 | 0.147 | [0.091, 0.214] | True |

## Sensitivity: extended authority lexicon (not the floor)

| feature | reader | unshifted | shifted |
|---|---|---|---|
| authority_language | extended lexicon | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
NLI minus extended lexicon on shifted ref: -0.000 [-0.001, 0.000].

## Authority reader vs floor (shifted ref)

| reader | floor | floor AUROC | reader AUROC | delta | delta 95% CI | beats floor |
|---|---|---|---|---|---|---|
| nli (ref-selected; sensitivity) | small registered lexicon | 0.845 | 1.000 | 0.155 | [0.080, 0.239] | True |
| nli (ref-selected; sensitivity) | extended fixed list (sensitivity) | 1.000 | 1.000 | -0.000 | [-0.001, 0.000] | False |
| decision | small registered lexicon | 0.845 | 0.924 | 0.079 | [0.018, 0.149] | True |
| decision | extended fixed list (sensitivity) | 1.000 | 0.924 | -0.076 | [-0.144, -0.026] | False |

## Authority NLI template sensitivity (shifted ref)

| template | AUROC | delta vs small lexicon | 95% CI | beats small lexicon |
|---|---|---|---|---|
| round1_original_reconstructed | 0.655 | -0.189 | [-0.295, -0.091] | False |
| generic_permission_approval_exception | 0.676 | -0.169 | [-0.241, -0.095] | False |
| generic_permission_or_approval | 0.609 | -0.236 | [-0.334, -0.142] | False |
| generic_instruction_to_reviewer | 0.536 | -0.309 | [-0.428, -0.194] | False |
| tuned_restriction_lifted | 1.000 | 0.155 | [0.080, 0.239] | True |

## Reader 3 training holdouts (own generated text)

| feature | n | pos/neg | groups held out | random-row AUROC | template-group AUROC |
|---|---|---|---|---|---|
| hype | 700 | 350/350 | 2/9 | 1.000 | 1.000 |
| authority_language | 700 | 350/350 | 2/9 | 0.997 | 1.000 |
| support_gap | 700 | 369/331 | 1/4 | 0.872 | 0.811 |

## Latency per action

| reader | device | features | p50 ms | p99 ms | n |
|---|---|---|---|---|---|
| lexicon | cpu | hype+authority+support | 0.058 | 0.169 | 1440 |
| nli | mps | hype+authority+support | 244.640 | 935.802 | 1440 |
| embed_lr | mps | hype+authority+support | 37.641 | 158.883 | 1440 |
| injection | mps | authority only | 39.665 | 142.489 | 1440 |
| injection_fmops | mps | authority only | 9.836 | 25.345 | 1440 |
| decision | network | hype+authority+support | 1149.992 | 1657.443 | 1440 |

## Max logit contribution (placeholder)

Unit-weight bound: 1.0 logit per feature. Fitted univariate monotone slopes: hype=7.089, authority_language=2.527, support_gap=5.282.

Decision-model calls: 1440; cost: $0.042320.
