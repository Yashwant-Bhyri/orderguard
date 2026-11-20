#!/usr/bin/env python3
"""Offline test of the EDGAR C5 parser on saved fixtures.

This covers the round-3 bug: index.json is JSON, not XML. It also checks the
filing parser and the fixed value rule on a tiny N-PORT document. No network.
"""

import sys
from pathlib import Path

from score import compute_fund, holding_flags
from verify_edgar import parse_index, parse_filing, pick_primary_xml

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"


def main():
    bad = 0
    items = parse_index((FIX / "edgar_index.json").read_bytes())
    if len(items) != 4:
        bad += 1
        print("FAIL index.json item count:", len(items))
    xml_name = pick_primary_xml(items)
    if xml_name != "primary_doc.xml":
        bad += 1
        print("FAIL pick_primary_xml:", xml_name)

    net, holdings = parse_filing((FIX / "nport_filing.xml").read_bytes())
    if net != 1000000.0:
        bad += 1
        print("FAIL parsed net assets:", net)
    if len(holdings) != 4:
        bad += 1
        print("FAIL parsed holdings:", len(holdings))
    res = compute_fund(holdings, net, value_mode="cval")
    if abs(res["shares"]["us_treasury"]["share"] - 0.50) > 1e-9:
        bad += 1
        print("FAIL treasury share from XML:", res["shares"]["us_treasury"]["share"])
    ep = next(h for h in holdings if h["asset_cat"] == "EP")
    if holding_flags(ep)["bond"] or holding_flags(ep)["equity"]:
        bad += 1
        print("FAIL EP counts as debt or equity")

    if bad:
        sys.exit(f"{bad} EDGAR parser failures")
    print("PASS EDGAR parser: index.json fixture, primary-XML pick, N-PORT XML, EP excluded")


if __name__ == "__main__":
    main()
