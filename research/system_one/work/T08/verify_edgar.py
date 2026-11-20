#!/usr/bin/env python3
"""Live C5 check of the flagged sample against the filed N-PORT XML.

Deferred by the lead review: it runs only when SEC_USER_AGENT is set. Without
a contact User-Agent it prints exactly "skipped: no SEC_USER_AGENT" and exits 0.
No email or browser User-Agent is invented here.
"""

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from score import compute_fund

HERE = Path(__file__).resolve().parent
MAX_RPS = 10.0
_starts = []


def paced_get(url, ua, timeout=60):
    now = time.monotonic()
    while _starts and now - _starts[0] >= 1.0:
        _starts.pop(0)
    if len(_starts) >= int(MAX_RPS):
        time.sleep(1.0 - (now - _starts[0]) + 0.002)
        now = time.monotonic()
        while _starts and now - _starts[0] >= 1.0:
            _starts.pop(0)
    _starts.append(now)
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    return urllib.request.urlopen(req, timeout=timeout)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(elem, name):
    for c in elem:
        if local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def num(s):
    s = (s or "").replace(",", "").replace("$", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_index(raw_bytes):
    """Parse EDGAR's filing index.json and return the index items.

    The previous version fed this JSON document to ElementTree, which raised a
    parse error for every filing. This helper is covered by test_edgar.py.
    """
    data = json.loads(raw_bytes.decode("utf-8") if isinstance(raw_bytes, (bytes, bytearray))
                      else raw_bytes)
    return data.get("directory", {}).get("item", [])


def pick_primary_xml(items):
    """Prefer the largest XML; the N-PORT primary doc is normally the biggest."""
    xmls = [it for it in items
            if str(it.get("name", "")).lower().endswith(".xml")]
    if not xmls:
        raise RuntimeError("no primary XML in filing index")
    def size(it):
        try:
            return int(it.get("size", "0") or 0)
        except (TypeError, ValueError):
            return 0
    return max(xmls, key=size)["name"]


def parse_filing(xml_bytes):
    root = ET.fromstring(xml_bytes)
    net_assets = None
    holdings = []
    for e in root.iter():
        if local(e.tag) == "netAssets" and net_assets is None:
            net_assets = num(e.text)
        if local(e.tag) != "invstOrSec":
            continue
        deriv = any(local(c.tag) == "derivativeInfo" for c in e)
        h = {
            "issuer_name": child_text(e, "name"),
            "issuer_title": child_text(e, "title"),
            "currency_value": child_text(e, "valUSD"),
            "exchange_rate": "1",
            "percentage": child_text(e, "pctVal"),
            "asset_cat": child_text(e, "assetCat").upper(),
            "issuer_type": child_text(e, "issuerCat").upper(),
            "investment_country": child_text(e, "invCountry").upper(),
            "derivative_cat": "DERIV" if deriv else "",
        }
        holdings.append(h)
    return net_assets, holdings


def main():
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        print("skipped: no SEC_USER_AGENT")
        return 0
    sample_path = HERE / "flagged_sample.csv"
    if not sample_path.exists():
        print("skipped: flagged_sample.csv not found")
        return 0
    rows = list(csv.DictReader(open(sample_path)))
    seen = {}
    for r in rows:
        seen.setdefault(r["accession_number"], r)
    out = []
    failures = 0
    for acc, r in sorted(seen.items()):
        acc_nodash = acc.replace("-", "")
        cik = str(int(str(r.get("cik") or "0").lstrip("0") or "0"))
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}"
        try:
            items = parse_index(paced_get(base + "/index.json", ua).read())
            xml_name = pick_primary_xml(items)
            net, holdings = parse_filing(paced_get(base + "/" + xml_name, ua).read())
            if not net or net <= 0 or not holdings:
                raise RuntimeError("no net assets or holdings in filing XML")
            # Use the same fixed unit rule as score.py; the XML valUSD is USD.
            res = compute_fund(holdings, net, value_mode="cval")
            cat = r["category"]
            live = res["shares"][cat]["share"]
            csv_share = float(r["share"])
            agree = (live is not None and abs(live - csv_share) <= 0.02
                     and (live < 0.80) == (csv_share < 0.80))
            out.append({
                "accession_number": acc,
                "category": cat,
                "csv_share": csv_share,
                "live_share": live,
                "agree": agree,
                "xml": xml_name,
                "link": r.get("link", ""),
            })
            if not agree:
                failures += 1
        except Exception as e:
            failures += 1
            out.append({
                "accession_number": acc,
                "category": r["category"],
                "csv_share": float(r["share"]),
                "live_share": None,
                "agree": False,
                "xml": "",
                "link": r.get("link", ""),
                "error": str(e),
            })
    out_path = HERE / "verify_edgar_results.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["accession_number", "category", "csv_share",
                                          "live_share", "agree", "xml", "link", "error"])
        w.writeheader()
        for row in out:
            w.writerow(row)
    agree_n = sum(1 for r in out if r["agree"])
    print(f"EDGAR check: {agree_n}/{len(out)} filings agree within 0.02 and the same 80% side; "
          f"wrote {out_path.name}")
    if failures:
        print(f"EDGAR check failures: {failures}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
