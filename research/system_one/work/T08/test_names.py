#!/usr/bin/env python3
"""Hand-written classifier cases. Run: python test_names.py"""

import sys
from names import name_to_test

CASES = [
    ("Vanguard Total Bond Market Index Fund", {"bond"}),
    ("iShares 20+ Year Treasury Bond ETF", {"us_treasury", "bond"}),
    ("Treasury Inflation-Protected Securities Fund", {"us_treasury", "bond"}),
    ("Fidelity Municipal Income Fund", {"municipal", "bond"}),
    ("American Funds High-Income Municipal Bond Fund",
     {"municipal", "high_yield", "bond"}),
    ("Vanguard High-Yield Corporate Fund", {"high_yield", "bond"}),
    ("Fidelity Emerging Markets Fund", {"emerging_markets"}),
    ("iShares MSCI Emerging Markets ETF", {"emerging_markets", "equity"}),
    ("Global Technology Fund", {"global", "sector"}),
    ("T. Rowe Price International Discovery Fund", {"international"}),
    ("Vanguard Small-Cap Growth Index Fund", {"small_mid_cap", "equity"}),
    ("Cohen & Steers Real Estate Securities Fund", {"sector"}),
    ("PIMCO Corporate & Income Opportunity Fund", {"bond"}),
    ("Franklin California Tax-Free Income Fund", {"municipal", "bond"}),
    ("Vanguard 500 Index Fund", {"equity"}),
    ("Fidelity Contrafund", set()),
    ("Dodge & Cox Stock Fund", {"equity"}),
    ("Vanguard Wellington Fund", set()),
    ("PIMCO Income Fund", set()),
    ("iShares iBoxx $ High Yield Corporate Bond ETF",
     {"high_yield", "bond"}),
    ("SPDR Bloomberg 1-3 Month T-Bill ETF", {"us_treasury", "bond"}),
    ("Vanguard Short-Term Treasury ETF", {"us_treasury", "bond"}),
    ("Schwab U.S. Aggregate Bond ETF", {"bond"}),
    ("Invesco Global Bond Fund", {"global", "bond"}),
    ("Templeton Foreign Fund", {"international"}),
    ("Vanguard Total International Stock Index Fund",
     {"international", "equity"}),
    ("Fidelity Series Emerging Markets Debt Fund",
     {"emerging_markets", "bond"}),
    ("VanEck Morningstar Wide Moat ETF", set()),
    ("iShares ESG Aware MSCI USA ETF", {"esg", "equity"}),
    ("SPDR Gold Shares", {"commodity"}),
    ("Vanguard Utilities ETF", {"sector"}),
    ("Fidelity MSCI Information Technology Index ETF", {"sector", "equity"}),
    ("iShares J.P. Morgan USD Emerging Markets Bond ETF",
     {"emerging_markets", "bond"}),
    ("Vanguard Total World Stock ETF", {"global", "equity"}),
    ("American Century Sustainable Equity Fund", {"esg", "equity"}),
    ("JPMorgan Equity Income Fund", {"equity"}),
    ("Vanguard Dividend Appreciation ETF", {"dividend", "equity"}),
    ("Fidelity Low-Priced Stock Fund", {"equity"}),
    ("Vanguard Mid-Cap Value ETF", {"small_mid_cap", "equity"}),
    ("iShares National Muni Bond ETF", {"municipal", "bond"}),
    ("Global High Yield Bond Fund", {"global", "high_yield", "bond"}),
    ("International Small Cap Equity Fund",
     {"international", "small_mid_cap", "equity"}),
    ("US Government Agency Mortgage Fund", {"us_government", "bond"}),
    ("Foreign Government Bond Fund", {"international", "bond"}),
    ("Short-Term Municipal Bond Fund", {"municipal", "bond"}),
    ("California Tax-Free Money Market Fund", {"money_market"}),
    ("Vanguard Federal Money Market Fund", {"money_market"}),
    ("Fidelity Money Market Fund", {"money_market"}),
    ("Global Real Estate Fund", {"global", "sector"}),
    ("Emerging Markets Small Cap Fund",
     {"emerging_markets", "small_mid_cap", "equity"}),
    ("Bitcoin Strategy ETF", {"digital_asset"}),
    ("Convertible Securities Fund", {"convertible"}),
    ("iShares Convertible Bond ETF", {"convertible", "bond"}),
    ("Direxion Daily 20+ Year Treasury Bear 3X Shares", {"strategy"}),
    ("ProShares Ultra Nasdaq Cloud Computing", {"strategy"}),
    ("ProShares UltraShort MSCI Emerging Markets", {"strategy"}),
    ("Federated Hermes Muni and Stock Advantage Fund", {"mixed"}),
    ("Fidelity Growth & Income Fund", {"mixed"}),
    ("Nuveen California Municipal Value Fund", {"municipal", "bond"}),
    ("Victory Investment Grade Convertible Fund", {"convertible"}),
    ("SPDR Bloomberg High Yield Bond ETF", {"high_yield", "bond"}),
    ("Eaton Vance Preferred Securities and Income ETF", {"preferred"}),
    ("iShares Preferred and Income Securities ETF", {"preferred"}),
    ("Innovator S&P Investment Grade Preferred ETF", {"preferred"}),
    ("Victory Pioneer Equity Premium Income Fund", {"strategy"}),
    ("Victory Growth and Tax Strategy Fund", {"mixed"}),
    ("CIM Real Assets & Credit Fund", {"mixed"}),
    ("Vanguard Advice Select International Growth Fund", {"international", "equity"}),
    ("Sp Funds Dow Jones Global Sukuk ETF", {"bond", "global"}),
    ("Dunham Corporate/Government Bond Fund", {"bond"}),
    ("iShares Intermediate Government/Credit Bond ETF", {"bond", "credit"}),
    ("Invesco Equity and Income Fund", {"mixed"}),
    ("Pro-Blend Moderate Term Series", {"mixed"}),
    ("Arrow Dow Jones Global Yield ETF", {"mixed"}),
    ("Franklin Income Equity Focus ETF", {"mixed"}),
    ("Wisdom Short Term Government Fund", {"us_government", "bond"}),
    ("S&P MidCap 400 Pure Growth Fund", {"equity"}),
    ("GOVERNMENT STREET OPPORTUNITIES FUND", set()),
    ("College Retirement Equities Fund - Inflation-Linked Bond Account", {"bond"}),
    ("One+One Nasdaq-100 and Bitcoin ETF", {"digital_asset"}),
    ("Virtus Income & Growth Fund", {"mixed"}),
    ("Voya Global Income & Growth Fund", {"mixed"}),
    ("Ashmore Emerging Markets Frontier Equity Fund", {"frontier_markets", "equity"}),
    ("Calamos Convertible Equity Alternative ETF", {"convertible"}),
    ("BondBloxx USD High Yield Bond Sector Rotation ETF", {"high_yield", "bond"}),
    ("PROFUND VP SHORT SMALL CAP", {"strategy"}),
    ("TrueShares Equity Hedge ETF", {"strategy"}),
    ("Matisse Discounted Bond CEF Strategy", {"strategy"}),
    ("Doubleline Shiller Enhanced International CAPE", {"strategy"}),
    ("BNY Mellon Developed Markets Real Estate Securities Fund", {"global", "sector"}),
    ("Wilshire Income Opportunities Fund", set()),
    ("EQ/AB Dynamic Moderate Growth Portfolio", {"mixed"}),
    ("AB CarVal Credit Opportunities Fund", {"credit"}),
    ("Barrow Hanley Credit Opportunities Fund", {"credit"}),
    ("Old Westbury Credit Income Fund", {"credit"}),
    ("Fidelity SAI International Credit Fund", {"international", "credit"}),
    ("BlueBay Destra International Event-Driven Credit Fund", {"strategy"}),
    ("EQ/AB Dynamic Growth Portfolio", {"mixed"}),
    ("BlackRock Credit Relative Value Fund", {"credit"}),
    ("Clough Hedged Equity ETF", {"strategy"}),
    ("WisdomTree Efficient U.S. Plus International Equity Fund", {"mixed"}),
    ("International Equity Plus Bond Alpha Portfolio", {"mixed"}),
    ("Goldman Sachs Emerging Markets Credit Fund", {"emerging_markets", "credit"}),
    ("Ashmore Emerging Markets Short Duration Fund", {"emerging_markets"}),
    ("MORGAN STANLEY EMERGING MARKETS DEBT FUND INC", {"emerging_markets", "bond"}),
    ("Oaktree Asset-Backed Income Fund Inc.", {"asset_backed"}),
    ("iShares ABS Bond ETF", {"asset_backed", "bond"}),
]


def main():
    bad = 0
    for i, (name, expected) in enumerate(CASES, 1):
        got = {h["category"] for h in name_to_test(name)}
        if got != expected:
            bad += 1
            print(f"FAIL {i}: {name}\n  expected {sorted(expected)}\n  got      {sorted(got)}")
    untestable_checks = [
        ("Vanguard Small-Cap Growth Index Fund", "small_mid_cap"),
        ("Global Technology Fund", "sector"),
        ("Vanguard High-Yield Corporate Fund", "high_yield"),
        ("iShares ESG Aware MSCI USA ETF", "esg"),
        ("SPDR Gold Shares", "commodity"),
        ("Fidelity Money Market Fund", "money_market"),
    ]
    for name, cat in untestable_checks:
        hit = [h for h in name_to_test(name) if h["category"] == cat]
        if not hit or hit[0]["testable"] is not False:
            bad += 1
            print(f"FAIL testable flag: {name} -> {cat}")
    if bad:
        sys.exit(f"{bad} failures out of {len(CASES)} cases")
    print(f"PASS name_to_test: {len(CASES)} hand-written names, all expected sets matched")


if __name__ == "__main__":
    main()
