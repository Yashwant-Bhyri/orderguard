# Known failures: engine, holdout companies

Missed false claims (57 of 434; a miss = no matching claim of the arm was marked wrong). 'not_extracted' = the arm never turned that sentence into a claim; 'unchecked' = it did, but its sources could not settle it; 'ok' = it checked it and called it right.

| Memo | Error class | Why missed | Claim | What the filing says (labeller) |
|---|---|---|---|---|
| AMZN-cohere | wrong_derived | unchecked | Gross margin remained stable near 44‑45% | FY2024 gross margin (637,959 - 326,288) / 637,959 = 48.9% (FY2023 47.0%, FY2022 43.8%) |
| AMZN-flint | wrong_derived | unchecked | from 5.3% in FY2023 | FY2023 operating margin 36,852 / 574,785 = 6.4% |
| BA-control | wrong_period | ok | revenue fell to $77.8 billion | FY2024 total revenues are 66,517 million ($66.5 billion), not $77.8 billion. $77.8 billion (77,794 million) is |
| BA-control | wrong_period | ok | net loss widened to $2.22 billion | FY2024 net loss attributable to Boeing shareholders is 11,817 million ($11.8 billion). $2.22 billion (2,222 mi |
| BA-control | wrong_period | not_extracted | operating income improved to $‑0.77 billion | FY2024 loss from operations is (10,707) million (-$10.7 billion), a deterioration from FY2023. -$0.77 billion  |
| BA-control | wrong_period | not_extracted | diluted EPS to $‑3.67 | FY2024 diluted loss per share is ($18.36). ($3.67) is the FY2023 figure |
| BA-control | wrong_period | ok | operating cash flow turned negative at $5.96 billion | FY2024 net cash used by operating activities was (12,080) million (-$12.1 billion). FY2023 operating cash flow |
| BA-cohere | wrong_derived | not_extracted | generation of $5.4 billion | FY2024 free cash flow = operating cash flow - capex = -12,080 - 2,230 = -14,310 million; filings report no FCF |
| BA-cohere | wrong_derived | unchecked | up from $4.9 billion a year earlier | FY2023 free cash flow = 5,960 - 1,527 = 4,433 million; memo says 4.9 billion |
| BA-cohere | wrong_figure | not_extracted | The backlog remained robust at around $560 billion | Total backlog at Dec 31, 2024: 521,336 million (2023: 520,195 million) |
| COST-cohere | wrong_derived | unchecked | maintained a gross margin near 13.5 percent | FY2024 gross margin 27,267 / net sales 249,625 = 10.92%, as reported in the filing (10.92%). |
| COST-cohere | wrong_derived | ok | a net margin of about 2.3 percent | FY2024 net income attributable to Costco 7,367 / total revenue 254,453 = 2.90% (net sales basis 2.95%). |
| COST-cohere | wrong_growth | not_extracted | The consistent double‑digit revenue growth | Total revenue growth FY2023 242,290 / 226,954 - 1 = 6.8%; FY2024 254,453 / 242,290 - 1 = 5.0%. Neither is doub |
| COST-flint | wrong_derived | unchecked | compared with about 3.8% in fiscal 2023 | FY2023 operating income 8,114 / total revenue 242,290 = 3.35% (net sales basis 8,114 / 237,710 = 3.41%). |
| CSCO-cohere | wrong_growth | not_extracted | a modest 4 % increase over FY2023 | FY2024 revenue 53,803 vs FY2023 56,998: 53,803/56,998 - 1 = -5.6% (a decline) |
| CSCO-cohere | wrong_derived | not_extracted | from 17 % in FY2023 | FY2023 net margin 12,613/56,998 = 22.1% |
| CSCO-cohere | wrong_growth | not_extracted | a 7 % top‑line growth rate from FY2022 | FY2023 revenue 56,998 vs FY2022 51,557: 56,998/51,557 - 1 = +10.6% |
| CSCO-cohere | wrong_derived | not_extracted | operating margin moving from about 15 % in FY2022 | FY2022 operating margin 13,969/51,557 = 27.1% |
| CSCO-cohere | wrong_derived | not_extracted | to roughly 19 % in FY2024 | FY2024 operating margin 12,181/53,803 = 22.6% |
| GOOGL-cohere | wrong_derived | unchecked | Gross margin held steady at about 45% | FY2024 gross profit = 350,018 - 146,306 = 203,712; 203,712 / 350,018 = 58.2% (FY2023 56.6%) |
| INTC-cohere | wrong_derived | unchecked | from 44% in FY2023 | FY2023 gross margin 21,711 / 54,228 = 40.0% |
| INTC-flint | wrong_derived | unchecked | around 29% | FY2023 operating margin 93 / 54,228 = 0.2% |
| MCD-cohere | wrong_figure | not_extracted | Same‑store sales rose 4.5 percent | FY2024 global comparable sales decreased 0.1% |
| MCD-cohere | wrong_figure | not_extracted | the robust 5.5 percent gain in FY 2023 | FY2023 global comparable sales increased 9.0% |
| MCD-cohere | wrong_figure | not_extracted | same‑store sales up 8.0 percent | FY2022 total comparable sales increased 10.9% |
| MCD-cohere | wrong_period | not_extracted | same‑store sales growth of about 9.0 percent | FY2021 total comparable sales increased 17.0% (the 9.0% figure is FY2023) |
| MCD-cohere | wrong_derived | not_extracted | with operating margins hovering around 30 percent | Operating margin FY2021 10,356/23,222.9 = 44.6%; FY2022 9,371/23,182.6 = 40.4%; FY2023 11,646.7/25,493.7 = 45. |
| MCD-cohere | wrong_derived | not_extracted | net margins near 27 percent across the period | Net margin FY2021 32.5%; FY2022 26.6%; FY2023 33.2%; FY2024 31.7% (only FY2022 is near 27%) |
| MCD-flint | wrong_figure | not_extracted | Global comparable sales rose only about 0.3% for the year | FY2024 global comparable sales decreased 0.1% |
| MCD-flint | wrong_figure | not_extracted | global comparable sales up 9.4% | FY2023 global comparable sales increased 9.0% (9.4% is the International Developmental Licensed segment figure |
| MCD-flint | wrong_figure | not_extracted | global comparable sales rose 7.1% | FY2022 total comparable sales increased 10.9% |
| MSFT-flint | wrong_period | not_extracted | compared with $72.7 billion and $2.72 in FY2024 | FY2024 diluted EPS is 11.80; 2.72 is the FY2023 dividend declared per share |
| MSFT-flint | wrong_figure | not_extracted | and $54.9 billion and $1.99 in FY2023 | FY2023 diluted EPS 9.68 |
| NFLX-cohere | wrong_figure | not_extracted | subscriber base expanded to about 238 million paid members in FY2023 | Paid memberships at end of FY2023 260,276 thousand (260.3 million) |
| NKE-cohere | wrong_derived | unchecked | operating margin improved to about 10% | Nike reports EBIT margin: FY2024 EBIT 6,539 / revenues 51,362 = 12.7% |
| NKE-cohere | wrong_derived | unchecked | from 9% in FY2023 | FY2023 EBIT margin: 6,195 / 51,217 = 12.1% (filing states 12.1%) |
| NKE-cohere | wrong_period | not_extracted | cash and equivalents of $7.5 billion | FY2024 cash and equivalents 9,860 million; 7,441 million is FY2023 (about $7.4 billion) |
| NKE-flint | wrong_derived | unchecked | operating margin was about 21% | FY2024 EBIT margin 12.7% (EBIT 6,539 / revenues 51,362); income before income taxes 6,700 / 51,362 = 13.0% |
| NVDA-cohere | wrong_growth | not_extracted | a 45 % compound annual growth rate in revenue from FY2023 | CAGR FY2023 to FY2025 = (130,497 / 26,974)^(1/2) - 1 = 119.9% |
| NVDA-cohere | wrong_derived | not_extracted | net margins hovering around 41 % | FY2025 net margin = 72,880 / 130,497 = 55.8% |
| NVDA-cohere | wrong_derived | not_extracted | versus 45 % in FY2023 | FY2023 net margin = 4,368 / 26,974 = 16.2% |
| NVDA-cohere | wrong_derived | not_extracted | gross margins near 60 % | FY2024 gross margin = 44,301 / 60,922 = 72.7% |
| NVDA-cohere | wrong_derived | not_extracted | to ~65 % in FY2025 | FY2025 gross margin = 97,858 / 130,497 = 75.0% |
| ORCL-cohere | wrong_derived | not_extracted | a high‑30 % net margin | FY2024 net margin 10,467 / 52,961 = 19.8% |
| ORCL-cohere | wrong_growth | not_extracted | a 12 % top‑line increase over FY2022 | FY2023 growth 49,954 / 42,440 - 1 = 17.7% |
| PFE-cohere | wrong_growth | not_extracted | a modest 1 % increase over 2023 | FY2024 growth = 63,627 / 59,553 - 1 = 6.8% (filing states 7%). |
| PFE-cohere | wrong_derived | not_extracted | supporting a net margin near 21 % | FY2024 net margin = 8,031 / 63,627 = 12.6%. |
| PFE-cohere | wrong_derived | not_extracted | a net margin of roughly 20 % | FY2023 net margin = 2,119 / 59,553 = 3.6% (3.6% on the originally reported 58,496 base). |
| PFE-cohere | wrong_derived | not_extracted | a net margin around 19 % | FY2022 net margin = 31,372 / 101,175 = 31.0% (31.3% on the originally reported 100,330 base). |
| PFE-cohere | wrong_figure | not_extracted | over $50 billion of cash and equivalents | Cash and cash equivalents at 31 Dec 2024 1,043 million ($1.0 billion); 2023 2,853 million. |
| TSLA-flint | wrong_period | not_extracted | versus $5.52 billion and $0.72 in FY2023 | FY2023 diluted EPS 4.30 (FY2021 1.63); 0.72 appears in no filing figure |
| WMT-cohere | wrong_growth | ok | up about 4.5% from FY2024’s $642 billion | FY2025 net sales 674,538 / FY2024 642,637 - 1 = 5.0% (filing states 5.0%; total revenues growth 5.1%) |
| WMT-cohere | wrong_derived | unchecked | Gross margin held steady around 25‑26% | FY2025 gross profit 162,785 / net sales 674,538 = 24.1% (FY2024 23.7%) |
| WMT-flint | wrong_period | not_extracted | Walmart’s FY2024, ended January 31, 2025 | The year ended January 31, 2025 is fiscal 2025 (FY2025); FY2024 ended January 31, 2024 |
| WMT-flint | wrong_derived | unchecked | Gross margin remained under pressure, around 32.5% | FY2024 gross profit 152,495 / net sales 642,637 = 23.7% |
| WMT-flint | wrong_figure | not_extracted | versus 7.3% in FY2023 | FY2023 reported comparable sales: Total U.S. 8.2%, Walmart U.S. 7.0%, Sam's Club 14.6%; no 7.3% figure |
| WMT-flint | wrong_growth | ok | FY2023 revenue was up 5.7% | FY2023 total revenues 611,289 / FY2022 572,754 - 1 = 6.7% (filing states 6.7%) |

True claims flagged wrong (7 of 259); the strict one-to-one list follows, and 4 of the flagged ones had no false figure beside them:

- INTC-control: operating income of $0.09 billion  (labeller: FY2023 operating income 93 million (0.093 billion))
- NVDA-flint: net margin above 50%  (labeller: FY2025 net margin = 72,880 / 130,497 = 55.8%, which is above 50%)
- WMT-flint: to about $648 billion  (labeller: FY2024 total revenues 648,125 million)
- WMT-flint: from $572 billion in FY2022  (labeller: FY2022 total revenues 572,754 million)

Memos with no false claim that were stopped (1 of 15):

- INTC-control: block

Model failures (counted as misses): 0
