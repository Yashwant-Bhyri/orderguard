# T04 model evaluation — reference world

Every value below is computed by `work/T04/run.sh`.  Cells are
`mean ± seed spread [mean episode-bootstrap 95% CI]`; `n/a` means
undefined for that split (for example AUROC when a split has one class).

## Headline table

| Test | Model | AUROC | Brier | ECE-15 | ECE-adaptive | Clean hold | Recall | Lead mean | Lead median | Top-cause acc |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fake_test | logistic | 0.8889 ± 0.0000 [0.6757, 1.0000] | 0.0599 ± 0.0000 [0.0000, 0.1350] | 0.0677 ± 0.0000 [0.0000, 0.1350] | 0.0677 ± 0.0000 [0.0000, 0.1350] | 0.0000 ± 0.0000 [0.0000, 0.0000] | 0.8015 ± 0.0000 [0.3000, 1.0000] | 0.000 | 0.000 | 0.6972 |
| fake_test | ebm | 0.9046 ± 0.0000 [0.7472, 1.0000] | 0.0650 ± 0.0000 [0.0000, 0.1350] | 0.0800 ± 0.0000 [0.0000, 0.1467] | 0.0801 ± 0.0000 [0.0000, 0.1468] | 0.0000 ± 0.0000 [0.0000, 0.0000] | 0.8015 ± 0.0000 [0.3000, 1.0000] | 0.000 | 0.000 | 0.6972 |
| fake_test | hgb | 0.7457 ± 0.0000 [0.5127, 1.0000] | 0.1133 ± 0.0000 [0.0000, 0.1985] | 0.1133 ± 0.0000 [0.0000, 0.1984] | 0.1133 ± 0.0000 [0.0000, 0.1985] | 0.0083 ± 0.0000 [0.0083, 0.0083] | 0.5000 ± 0.0000 [0.0426, 1.0000] | 14.000 | 0.000 | 0.5147 |
| fake_test | hgb_monotone | 0.7500 ± 0.0000 [0.5213, 1.0000] | 0.1133 ± 0.0000 [0.0000, 0.1985] | 0.1133 ± 0.0000 [0.0000, 0.1984] | 0.1133 ± 0.0000 [0.0000, 0.1985] | 0.0000 ± 0.0000 [0.0000, 0.0000] | 0.5000 ± 0.0000 [0.0426, 1.0000] | 0.000 | 0.000 | 0.5147 |
| fake_test | noisy_and | 0.9407 ± 0.0000 [0.8152, 1.0000] | 0.0822 ± 0.0000 [0.0000, 0.1517] | 0.0943 ± 0.0000 [0.0000, 0.1751] | 0.0943 ± 0.0000 [0.0000, 0.1751] | 0.0000 ± 0.0000 [0.0000, 0.0000] | 0.8529 ± 0.0000 [0.4814, 1.0000] | 0.250 | 0.000 | 0.6552 |

## Split sizes

| Test | Episodes | Actions | Positives | Clean actions |
|---|---:|---:|---:|---:|
| fake_test | 5 | 600 | 136 | 120 |

## EBM monotonicity certificate

All main-effect bins monotone: **True**.
Features checked: 41.  Worst bin-to-bin change: 0 on `drift_out_of_band_weight`.

## Latency (one core, single-action prediction)

| Model | Actions timed | Featurise p50 | Featurise p99 | Predict p50 | Predict p99 | Total p50 | Total p99 |
|---|---:|---:|---:|---:|---:|---:|---:|

