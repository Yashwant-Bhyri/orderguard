# Findings: five real funds below the 80% line by our test

Selected automatically: the largest net-asset strong-category flags that stay below 75% and below the line after removing cash and derivatives from the sensitivity. Selection takes one fund per category first, then the largest remaining funds from categories not already chosen, extending to the full strong-flag set to keep one fund per category. Only if fewer than five distinct categories have any strong flag are the remaining slots filled by the largest remaining flags, and then a category can repeat. Every figure below comes from `score.py` and the same cached N-PORT file.

These are test results, not legal findings.

## 1. VANGUARD EMERGING MARKETS STOCK INDEX FUND

- Series id: `S000005786`; accession `0000857489-26-000084`; filed 31-MAR-2026; net assets $151,771,639,401.
- Category **emerging_markets**; share by our test **73.8%** (sensitivity on the securities book: 76.9%).
- Filing: https://www.sec.gov/Archives/edgar/data/857489/000085748926000084/0000857489-26-000084-index.htm
- Largest holdings outside the predicate: Tencent Holdings Ltd (EC, 4.3% of net assets); Alibaba Group Holding Ltd (EC, 3.4% of net assets); Vanguard Cmt Funds-Vanguard Market Liquidity Fund (cash-like, 2.3% of net assets).
- Other strong tests for this fund: emerging_markets 73.8%, equity 98.0%.

## 2. VANGUARD INTERNATIONAL GROWTH FUND

- Series id: `S000004453`; accession `0000052848-26-000137`; filed 28-JAN-2026; net assets $45,021,681,529.
- Category **international**; share by our test **74.9%** (sensitivity on the securities book: 76.2%).
- Filing: https://www.sec.gov/Archives/edgar/data/52848/000005284826000137/0000052848-26-000137-index.htm
- Largest holdings outside the predicate: MercadoLibre Inc (EC, 3.8% of net assets); Spotify Technology SA (EC, 3.1% of net assets); Sea Ltd (EC, 3.0% of net assets).
- Other strong tests for this fund: international 74.9%, equity 97.3%.

## 3. iShares MSCI Brazil ETF

- Series id: `S000004264`; accession `0001410368-26-006955`; filed 23-JAN-2026; net assets $6,587,795,937.
- Category **equity**; share by our test **74.7%** (sensitivity on the securities book: 75.5%).
- Filing: https://www.sec.gov/Archives/edgar/data/930667/000141036826006955/0001410368-26-006955-index.htm
- Largest holdings outside the predicate: Itau Unibanco Holding SA (EP, 8.7% of net assets); Petroleo Brasileiro SA - Petrobras (EP, 5.6% of net assets); Banco Bradesco SA (EP, 3.8% of net assets).
- Other strong tests for this fund: equity 74.7%.

## 4. BlackRock Ultra-Short Term Bond Portfolio

- Series id: `S000006534`; accession `0001410368-26-020751`; filed 27-FEB-2026; net assets $756,175,738.
- Category **bond**; share by our test **70.3%** (sensitivity on the securities book: 0.0%).
- Filing: https://www.sec.gov/Archives/edgar/data/710826/000141036826020751/0001410368-26-020751-index.htm
- Largest holdings outside the predicate: JPMorgan Securities LLC (cash-like, 13.2% of net assets); TORONTO DOMINION (cash-like, 12.3% of net assets); BofA Securities, Inc. (cash-like, 3.3% of net assets).
- Other strong tests for this fund: bond 70.3%.

## 5. Colorado BondShares A Tax Exempt Fund

- Series id: `S000012064`; accession `0001193125-26-085116`; filed 02-MAR-2026; net assets $1,948,524,338.
- Category **municipal**; share by our test **71.4%** (sensitivity on the securities book: 99.0%).
- Filing: https://www.sec.gov/Archives/edgar/data/810744/000119312526085116/0001193125-26-085116-index.htm
- Largest holdings outside the predicate: MULTNOMAH CNTY ORE HOSP FACS AUTH (DBT, 0.3% of net assets); COLORADO HSG & FIN AUTH (DBT, 0.2% of net assets); PV ERU Holding Trust (DBT, 0.1% of net assets).
- Other strong tests for this fund: municipal 71.4%, bond 72.1%.
