#!/usr/bin/env python3
"""Toy-fund tests for the share computation. Run: python test_share.py"""

import sys

from score import compute_fund, holding_flags, parse_filing_date

H = [
    dict(issuer_name="US Treasury", issuer_title="Treasury Note",
         currency_value="50", exchange_rate="1", percentage="50",
         asset_cat="DBT", issuer_type="UST", investment_country="US",
         derivative_cat=""),
    dict(issuer_name="Fannie Mae", issuer_title="MBS",
         currency_value="10", exchange_rate="1", percentage="10",
         asset_cat="DBT", issuer_type="USGSE", investment_country="US",
         derivative_cat=""),
    dict(issuer_name="State of California", issuer_title="Muni Bond",
         currency_value="10", exchange_rate="1", percentage="10",
         asset_cat="DBT", issuer_type="MUN", investment_country="US",
         derivative_cat=""),
    dict(issuer_name="Petrobras", issuer_title="Note",
         currency_value="5", exchange_rate="1", percentage="5",
         asset_cat="DBT", issuer_type="CORP", investment_country="BR",
         derivative_cat=""),
    dict(issuer_name="Apple", issuer_title="Common Stock",
         currency_value="15", exchange_rate="1", percentage="15",
         asset_cat="EC", issuer_type="CORP", investment_country="US",
         derivative_cat=""),
    dict(issuer_name="Cash", issuer_title="Cash",
         currency_value="5", exchange_rate="1", percentage="5",
         asset_cat="CASH", issuer_type="N/A", investment_country="US",
         derivative_cat=""),
    dict(issuer_name="Future", issuer_title="S&P Future",
         currency_value="5", exchange_rate="1", percentage="5",
         asset_cat="DF", issuer_type="N/A", investment_country="US",
         derivative_cat="FUT"),
]

SHARES = {
    "us_treasury": 0.50,
    "us_government": 0.60,
    "municipal": 0.10,
    "emerging_markets": 0.05,
    "international": 0.05,
    "global": 0.90,
    "equity": 0.15,
    "bond": 0.75,
}


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) < tol


def main():
    r = compute_fund(H, 100.0, 0.0)
    bad = 0
    for p, want in SHARES.items():
        got = r["shares"][p]["share"]
        if not close(got, want):
            bad += 1
            print(f"FAIL {p}: expected {want}, got {got}")
    if not close(r["shares"]["us_treasury"]["share_core"], 50.0 / 95.0):
        bad += 1
        print("FAIL treasure core sensitivity")
    if not close(r["shares"]["bond"]["share_core"], 75.0 / 95.0):
        bad += 1
        print("FAIL bond core sensitivity")
    if r["shares"]["global"]["share"] >= 0.80:
        pass
    else:
        bad += 1
        print("FAIL global should not flag at 0.90")
    if r["n_holdings"] != len(H):
        bad += 1
        print("FAIL holding count")
    if not close(r["cash_usd"], 5.0) or not close(r["deriv_usd"], 5.0):
        bad += 1
        print("FAIL cash/derivative sums")

    tb = dict(H[0], issuer_title="Treasury Bill", asset_cat="DBT",
              issuer_type="UST", issuer_name="US Treasury")
    if holding_flags(tb)["is_cash"]:
        bad += 1
        print("FAIL T-bill was treated as cash-like")

    boundary = [dict(H[0], currency_value="80", percentage="80"),
                dict(H[5], currency_value="20", percentage="20")]
    rb = compute_fund(boundary, 100.0, 0.0)
    if rb["shares"]["us_treasury"]["share"] != 0.80:
        bad += 1
        print("FAIL 80% boundary value")
    if rb["shares"]["us_treasury"]["share"] < 0.80:
        bad += 1
        print("FAIL 80% boundary should not flag")

    deriv = [dict(H[0], currency_value="70", percentage="70"),
             dict(H[6], currency_value="10", percentage="10",
                  issuer_type="UST", issuer_name="US Treasury Future"),
             dict(H[5], currency_value="20", percentage="20")]
    rd = compute_fund(deriv, 100.0, 0.0)
    if not close(rd["shares"]["us_treasury"]["share"], 0.80):
        bad += 1
        print("FAIL derivative-inclusive share")
    if not close(rd["shares"]["us_treasury"]["share_core"], 70.0 / 80.0):
        bad += 1
        print("FAIL derivative core share")

    # EM is a country test, not a sovereign-type test.
    jp_nuss = dict(H[0], issuer_name="Japan Government", issuer_title="JGB",
                   asset_cat="DBT", issuer_type="NUSS",
                   investment_country="JP", currency_value="30", percentage="30")
    br_nuss = dict(H[0], issuer_name="Brazil Government", issuer_title="NTN-B",
                   asset_cat="DBT", issuer_type="NUSS",
                   investment_country="BR", currency_value="10", percentage="10")
    us_eq = dict(H[4], currency_value="60", percentage="60")
    em = compute_fund([jp_nuss, br_nuss, us_eq], 100.0, 0.0)
    if not close(em["shares"]["emerging_markets"]["share"], 0.10):
        bad += 1
        print("FAIL NUSS must not be EM without an EM country")
    if holding_flags(jp_nuss)["emerging_markets"]:
        bad += 1
        print("FAIL Japan sovereign counted as EM")
    if not holding_flags(jp_nuss)["em_uncertain"]:
        bad += 1
        print("FAIL non-EM NUSS not marked uncertain")
    if not holding_flags(br_nuss)["emerging_markets"]:
        bad += 1
        print("FAIL Brazil sovereign not counted as EM")

    # EP (equity preferred) is neither equity nor debt. A fund holding only
    # preferred plus cash must be 0% on both tests; the old rule counted EP in
    # both sets, which is the bug review item 2 found.
    ep = dict(H[0], issuer_name="Preferred Co", issuer_title="Preferred Stock",
              asset_cat="EP", issuer_type="CORP", investment_country="US",
              currency_value="80", percentage="80")
    rep = compute_fund([ep, H[5]], 100.0, 0.0)
    if not close(rep["shares"]["bond"]["share"], 0.0):
        bad += 1
        print("FAIL EP counted as debt:", rep["shares"]["bond"]["share"])
    if not close(rep["shares"]["equity"]["share"], 0.0):
        bad += 1
        print("FAIL EP counted as equity:", rep["shares"]["equity"]["share"])
    if holding_flags(ep)["bond"] or holding_flags(ep)["equity"]:
        bad += 1
        print("FAIL EP holding flagged as debt or equity")

    # FILING_DATE is DD-MMM-YYYY; a string compare puts JAN above FEB.
    jan = parse_filing_date("23-JAN-2026")
    feb = parse_filing_date("23-FEB-2026")
    if not (jan < feb):
        bad += 1
        print("FAIL filing date parse ordering:", jan, feb)
    if not ("23-JAN-2026" > "23-FEB-2026"):
        bad += 1
        print("FAIL string comparison should sort JAN above FEB; the parser must not")

    if bad:
        sys.exit(f"{bad} share-computation failures")
    print("PASS share computation: toy fund, 80% boundary, cash/derivative sensitivity, "
          "EM country test, EP excluded from equity/debt, filing-date parse")


if __name__ == "__main__":
    main()
