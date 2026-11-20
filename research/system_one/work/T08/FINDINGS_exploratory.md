# Findings: five real funds below the 80% line by our test

Selected automatically: the largest net-asset strong-category flags that stay below 75% and below the line after removing cash and derivatives from the sensitivity. Selection takes one fund per category first, then the largest remaining funds from categories not already chosen, extending to the full strong-flag set to keep one fund per category. Only if fewer than five distinct categories have any strong flag are the remaining slots filled by the largest remaining flags, and then a category can repeat. Every figure below comes from `score.py` and the same cached N-PORT file.

These are test results, not legal findings.

## 1. GQG Partners Emerging Markets Equity Fund

- Series id: `S000056013`; accession `0002048251-26-004248`; filed 28-MAY-2026; net assets $21,559,904,353.
- Category **emerging_markets**; share by our test **64.6%** (sensitivity on the securities book: 74.2%).
- Filing: https://www.sec.gov/Archives/edgar/data/1593547/000204825126004248/0002048251-26-004248-index.htm
- Largest holdings outside the predicate: Petroleo Brasileiro S.A. (Petrobras) (cash-like, 4.6% of net assets); TOTALENERGIES SE (EC, 4.4% of net assets); BP P.L.C. (EC, 3.2% of net assets).
- Other strong tests for this fund: emerging_markets 64.6%, equity 91.4%.

## 2. PIMCO International Bond Fund (U.S. Dollar-Hedged)

- Series id: `S000009678`; accession `0001099263-26-007182`; filed 29-MAY-2026; net assets $17,733,325,783.
- Category **international**; share by our test **61.4%** (sensitivity on the securities book: 65.1%).
- Filing: https://www.sec.gov/Archives/edgar/data/810893/000109926326007182/0001099263-26-007182-index.htm
- Largest holdings outside the predicate: UMBS PASS THRU POOLS (ABS-MBS, 13.6% of net assets); PIMCO FUNDS (cash-like, 4.3% of net assets); GNMA PASS THRU POOLS (ABS-MBS, 3.8% of net assets).
- Other strong tests for this fund: international 61.4%, bond 108.0%.

## 3. iShares MSCI Brazil ETF

- Series id: `S000004264`; accession `0001410368-26-039512`; filed 23-APR-2026; net assets $9,654,648,116.
- Category **equity**; share by our test **73.8%** (sensitivity on the securities book: 74.0%).
- Filing: https://www.sec.gov/Archives/edgar/data/930667/000141036826039512/0001410368-26-039512-index.htm
- Largest holdings outside the predicate: Itau Unibanco Holding SA (EP, 9.0% of net assets); Petroleo Brasileiro SA - Petrobras (EP, 6.2% of net assets); Banco Bradesco SA (EP, 3.6% of net assets).
- Other strong tests for this fund: equity 73.8%.

## 4. Sound Enhanced Fixed Income ETF

- Series id: `S000070510`; accession `0002000324-26-001679`; filed 27-APR-2026; net assets $41,206,255.
- Category **bond**; share by our test **28.0%** (sensitivity on the securities book: 34.6%).
- Filing: https://www.sec.gov/Archives/edgar/data/1742912/000200032426001679/0002000324-26-001679-index.htm
- Largest holdings outside the predicate: Mount Vernon Liquid Assets Portfolio, LLC (cash-like, 19.1% of net assets); iShares 0-5 Year High Yield Co (EC, 3.1% of net assets); Ares Capital Corp (EC, 3.1% of net assets).
- Other strong tests for this fund: bond 28.0%.

## 5. Colorado BondShares A Tax Exempt Fund

- Series id: `S000012064`; accession `0001193125-26-247714`; filed 29-MAY-2026; net assets $1,959,473,820.
- Category **municipal**; share by our test **70.7%** (sensitivity on the securities book: 99.6%).
- Filing: https://www.sec.gov/Archives/edgar/data/810744/000119312526247714/0001193125-26-247714-index.htm
- Largest holdings outside the predicate: MULTNOMAH CNTY ORE HOSP FACS AUTH (DBT, 0.3% of net assets); COLORADO HSG & FIN AUTH (DBT, 0.2% of net assets); PV ERU Holding Trust (DBT, 0.1% of net assets).
- Other strong tests for this fund: municipal 70.7%, bond 71.4%.
