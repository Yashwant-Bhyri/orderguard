#!/usr/bin/env python3
"""Score N-PORT holdings against fund names, then write the task outputs."""

import argparse
import csv
import datetime
import io
import json
import math
import os
import random
import re
import statistics
import sys
import zipfile
from pathlib import Path

import numpy as np

from names import (name_to_test, is_post_hoc_equity_plus_bond,
                   EM_PROXY, EM_EXTENDED_HUBS, CATEGORIES)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "data" / "sec"

STRONG = ["us_treasury", "us_government", "municipal", "emerging_markets",
          "international", "equity", "bond"]
WEAK = ["global"]
PRED_ORDER = STRONG + WEAK

DERIV_CATS = {"DF", "DO", "DS", "D", "DER", "DERIV", "DERIVATIVE",
              "DFE", "DE", "DCO", "DCR"}
# EP is equity preferred. It is a hybrid whose asset-category coding is not
# consistent enough to test the name focus, so it counts as neither equity nor
# debt. The round-4 change removes it from both sets; `ep_sensitivity` reports
# how many funds cross the 80% line because of that removal.
EQUITY_CATS = {"EC", "RE"}
DEBT_CATS = {"DBT", "LON", "ABS-MBS", "ABS-O", "ABS-CBDO", "ABS-APCP", "SN"}
CASH_CATS = {"CASH", "MMF", "MM", "RA", "STIV"}
CASH_WORDS = ("CASH", "MONEY MARKET", "CASH COLLATERAL", "DEPOSIT",
              "CERTIFICATE OF DEPOSIT")
US_ALIASES = {"US", "USA", "U S", "UNITED STATES"}
EMPTY_COUNTRIES = {"", "N/A", "NA", "NONE", "-"}
AGENCY_WORDS = ("FANNIE", "FEDERAL NATIONAL MORTGAGE", "FREDDIE",
                "FEDERAL HOME LOAN", "FHLB", "FEDERAL FARM CREDIT",
                "GNMA", "GOVERNMENT NATIONAL MORTGAGE",
                "FEDERAL AGRICULTURAL MORTGAGE", "FARMER MAC",
                "FEDERAL HOME LOAN BANK", "SALLIE MAE",
                "TENNESSEE VALLEY AUTHORITY")

PREDICATE_TEXT = {
    "us_treasury": "ISSUER_TYPE == UST",
    "us_government": "ISSUER_TYPE in {UST, USGSE, USGA} or an agency issuer name",
    "municipal": "ISSUER_TYPE == MUN",
    "emerging_markets": "INVESTMENT_COUNTRY in the EM country proxy (strict core + EM offshore hubs)",
    "international": "INVESTMENT_COUNTRY not US/USA and not blank",
    "global": "country-assigned equity/debt (weak; global includes US)",
    "equity": "ASSET_CAT in {EC, RE} (EP preferred excluded)",
    "bond": "ASSET_CAT in the debt set or a row in DEBT_SECURITY (EP preferred excluded)",
}


def num(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace("$", "").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def norm(v):
    return str(v or "").strip().upper()


def parse_filing_date(v):
    """Parse N-PORT FILING_DATE (DD-MMM-YYYY) to a sortable date.

    A string comparison gets 23-JAN-2026 above 23-FEB-2026, so the dedup used
    the older filing for a few duplicate series. A missing or malformed date
    sorts before every real date.
    """
    s = str(v or "").strip()
    if not s:
        return datetime.date.min
    try:
        return datetime.datetime.strptime(s.upper(), "%d-%b-%Y").date()
    except ValueError:
        try:
            return datetime.date.fromisoformat(s[:10])
        except ValueError:
            return datetime.date.min


def is_cash_like(issuer, title, asset_cat):
    if asset_cat in CASH_CATS:
        return True
    blob = f"{issuer} {title}".upper()
    return any(w in blob for w in CASH_WORDS)


def holding_from_row(values):
    return {
        "issuer_name": values.get("issuer_name", ""),
        "issuer_title": values.get("issuer_title", ""),
        "currency_value": values.get("currency_value"),
        "exchange_rate": values.get("exchange_rate"),
        "percentage": values.get("percentage"),
        "asset_cat": norm(values.get("asset_cat")),
        "issuer_type": norm(values.get("issuer_type")),
        "investment_country": norm(values.get("investment_country")),
        "derivative_cat": norm(values.get("derivative_cat")),
    }


def holding_flags(h, debt_id=False):
    ac = h["asset_cat"]
    it = h["issuer_type"]
    c = h["investment_country"]
    blob = f"{h.get('issuer_name', '')} {h.get('issuer_title', '')}".upper()
    deriv = h["derivative_cat"] not in EMPTY_COUNTRIES or ac in DERIV_CATS
    cash = is_cash_like(h["issuer_name"], h["issuer_title"], ac)
    eq = ac in EQUITY_CATS
    dbt = ac in DEBT_CATS or debt_id
    agency = any(w in blob for w in AGENCY_WORDS)
    global_ = c not in EMPTY_COUNTRIES and (eq or dbt)
    em = c in EM_PROXY
    em_extended = c in (EM_PROXY | EM_EXTENDED_HUBS)
    # A non-US sovereign is not automatically EM. If the country is not in the
    # EM proxy we mark it uncertain instead of counting it.
    em_uncertain = it == "NUSS" and not em
    return {
        "is_deriv": deriv,
        "is_cash": cash,
        "us_treasury": it == "UST",
        "us_government": it in ("UST", "USGSE", "USGA") or agency,
        "municipal": it == "MUN",
        "emerging_markets": em,
        "em_extended": em_extended,
        "em_uncertain": em_uncertain,
        "international": c not in EMPTY_COUNTRIES and c not in US_ALIASES,
        "global": global_,
        "is_rf": it == "RF",
        "is_dir": ac == "DIR",
        "is_other": ac == "OTHER",
        "equity": eq,
        "bond": dbt,
    }


def holding_usd(h, mode="mul"):
    cv = num(h["currency_value"])
    if cv is None:
        return None
    if mode == "cval":
        return cv
    rate = num(h["exchange_rate"])
    if rate is None or rate == 0:
        return cv
    return cv * rate


def compute_fund(holdings, net_assets, cash_not_reported=0.0, value_mode="mul",
                 pct_scale=100.0):
    acc = {
        "n_holdings": 0, "n_missing_value": 0,
        "total_usd": 0.0, "total_pct": 0.0,
        "cash_usd": 0.0, "deriv_usd": 0.0,
        "all": {p: 0.0 for p in PRED_ORDER},
        "core": {p: 0.0 for p in PRED_ORDER},
        "pct": {p: 0.0 for p in PRED_ORDER},
    }
    for h in holdings:
        f = holding_flags(h)
        usd = holding_usd(h, value_mode)
        pct = num(h["percentage"])
        acc["n_holdings"] += 1
        if usd is None:
            acc["n_missing_value"] += 1
            usd = 0.0
        acc["total_usd"] += usd
        if pct is not None:
            acc["total_pct"] += pct
        if f["is_cash"]:
            acc["cash_usd"] += usd
        if f["is_deriv"]:
            acc["deriv_usd"] += usd
        core = not f["is_deriv"] and not f["is_cash"]
        for p in PRED_ORDER:
            if f[p]:
                acc["all"][p] += usd
                if core:
                    acc["core"][p] += usd
                if pct is not None:
                    acc["pct"][p] += pct

    denom_core = net_assets - acc["cash_usd"] - cash_not_reported
    shares = {}
    for p in PRED_ORDER:
        share = acc["all"][p] / net_assets if net_assets else None
        share_core = (acc["core"][p] / denom_core) if denom_core and denom_core > 0 else None
        pct_share = acc["pct"][p] / pct_scale
        shares[p] = {
            "share": share,
            "share_core": share_core,
            "pct_share": pct_share,
            "usd": acc["all"][p],
            "usd_core": acc["core"][p],
        }
    return {
        "n_holdings": acc["n_holdings"],
        "n_missing_value": acc["n_missing_value"],
        "total_usd": acc["total_usd"],
        "total_pct": acc["total_pct"],
        "cash_usd": acc["cash_usd"],
        "deriv_usd": acc["deriv_usd"],
        "denom_core": denom_core,
        "shares": shares,
    }


# Fixed unit rule, not selected per quarter. The N-PORT readme calls PERCENTAGE
# a percentage of net assets (so the divisor is 100) and CURRENCY_VALUE the
# reported value. Calibration on the exploratory 2026q2 slice showed that
# CURRENCY_VALUE already agrees with PERCENTAGE/100 without multiplying by
# EXCHANGE_RATE; that is a data-format fact, validated separately on the
# 2026q1 holdout below. The scoring path never chooses the unit from the
# quarter it scores.
VALUE_MODE = "cval"
PCT_SCALE = 100.0
VALUE_RULE_TEXT = (
    "fixed: USD = CURRENCY_VALUE (EXCHANGE_RATE is not a multiplier in this "
    "data-set format); PERCENTAGE is a percent of net assets, divisor 100. "
    "Calibrated on the exploratory 2026q2 slice and validated on the 2026q1 "
    "holdout; not re-selected per quarter."
)


def validate_value_units(zf, member, acc_state, limit=30000):
    """Report agreement with PERCENTAGE for every unit interpretation.

    This is a calibration/validation table, not a selector: VALUE_MODE and
    PCT_SCALE are fixed constants above. Reporting all four options lets the
    reviewer see that the fixed rule is the one that agrees with the filing.
    """

    pairs = {(vm, ps): [] for vm in ("cval", "mul") for ps in (1.0, 100.0)}
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        r = csv.reader(text, delimiter="\t")
        header = [h.strip().upper().lstrip("\ufeff") for h in next(r)]
        ix = {h: i for i, h in enumerate(header)}
        def get(row, name):
            i = ix.get(name)
            return row[i] if i is not None and i < len(row) else ""
        n = 0
        for row in r:
            acc = get(row, "ACCESSION_NUMBER").strip().replace("-", "")
            st = acc_state.get(acc)
            if st is None:
                continue
            cv = num(get(row, "CURRENCY_VALUE"))
            rate = num(get(row, "EXCHANGE_RATE"))
            pct = num(get(row, "PERCENTAGE"))
            na = st["fund"]["net_assets"]
            if cv is None or pct is None or not na or na <= 0:
                continue
            a = cv / na
            b = (cv * rate / na) if rate not in (None, 0) else a
            for vm, val in (("cval", a), ("mul", b)):
                for ps in (1.0, 100.0):
                    pairs[(vm, ps)].append(abs(val - pct / ps))
            n += 1
            if n >= limit:
                break
    options = {}
    for (vm, ps), errs in pairs.items():
        label = f"{vm}/div_{int(ps)}"
        options[label] = {
            "n": len(errs),
            "median_abs_error": float(np.median(errs)) if errs else None,
            "p90_abs_error": float(np.percentile(errs, 90)) if errs else None,
        }
    chosen = f"{VALUE_MODE}/div_{int(PCT_SCALE)}"
    return {
        "chosen": chosen,
        "rule": VALUE_RULE_TEXT,
        "rows_considered": n,
        "options": options,
        "chosen_median_abs_error": options.get(chosen, {}).get("median_abs_error"),
        "chosen_matches_filing": (
            options.get(chosen, {}).get("median_abs_error") is not None
            and options[chosen]["median_abs_error"] <= 1e-9),
    }


def find_member(zf, needle):
    for n in zf.namelist():
        b = os.path.basename(n).upper()
        if needle in b:
            return n
    return None


def read_records(zf, member):
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        r = csv.reader(text, delimiter="\t")
        header = [h.strip().upper().lstrip("\ufeff") for h in next(r)]
        idx = {h: i for i, h in enumerate(header)}
        for row in r:
            if not row:
                continue
            yield row, idx


def col(idx, row, name, default=""):
    i = idx.get(name)
    if i is None or i >= len(row):
        return default
    return row[i]


def load_small(zf, member, fields):
    out = {}
    for row, idx in read_records(zf, member):
        acc = norm(col(idx, row, "ACCESSION_NUMBER"))
        if not acc:
            continue
        rec = {f: col(idx, row, f) for f in fields}
        out[acc] = rec
    return out


def series_ids_in_zip(path):
    """Unique non-empty SERIES_ID values in a quarter's FUND_REPORTED_INFO."""
    path = Path(path)
    if not path.exists():
        return None
    with zipfile.ZipFile(path) as z:
        member = find_member(z, "FUND_REPORTED_INFO")
        if not member:
            return None
        out = set()
        for row, idx in read_records(z, member):
            sid = col(idx, row, "SERIES_ID").strip()
            if sid:
                out.add(sid)
        return out


def accession_dashes(a):
    a = str(a or "").strip()
    if "-" in a:
        return a
    if len(a) == 18 and a.isdigit():
        return f"{a[:10]}-{a[10:12]}-{a[12:]}"
    return a


def edgar_link(acc, cik):
    acc = accession_dashes(acc)
    if not cik:
        cik = acc.split("-")[0]
    try:
        c = str(int(str(cik).lstrip("0") or "0"))
    except ValueError:
        c = str(cik)
    return f"https://www.sec.gov/Archives/edgar/data/{c}/{acc.replace('-', '')}/{acc}-index.htm"


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, c - h), min(1.0, c + h)]


def dist(values):
    if not values:
        return None
    a = np.array(values, dtype=float)
    qs = np.percentile(a, [0, 5, 25, 50, 75, 95, 100])
    return {
        "n": len(values),
        "mean": float(np.mean(a)),
        "min": float(qs[0]),
        "p05": float(qs[1]),
        "p25": float(qs[2]),
        "median": float(qs[3]),
        "p75": float(qs[4]),
        "p95": float(qs[5]),
        "max": float(qs[6]),
    }


def histogram(values):
    bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0),
            (1.0, 1.2), (1.2, float("inf"))]
    out = {f"{a:.1f}-{b:.1f}" if b != float("inf") else f"{a:.1f}+": 0
           for a, b in bins}
    for v in values:
        for (a, b), label in zip(bins, out):
            if a <= v < b or (b == float("inf") and v >= a):
                out[label] += 1
                break
    neg = sum(1 for v in values if v < 0)
    if neg:
        out["<0.0"] = neg
    return out


def group_worst(items):
    g = {}
    for c in items:
        k = c["series_key"]
        if k not in g or c["share"] < g[k]["share"]:
            g[k] = c
    return sorted(g.values(), key=lambda c: c["series_key"])


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_freeze_manifest(require=False):
    path = HERE / "holdout_freeze.json"
    if not path.exists():
        if require:
            sys.exit("holdout_freeze.json is missing; cannot certify the holdout rule")
        return {"present": False}
    man = json.loads(path.read_text())
    ok = True
    detail = {}
    for name, expected in man.get("files", {}).items():
        got = sha256_file(HERE / name)
        detail[name] = {"expected": expected, "actual": got, "match": got == expected}
        ok = ok and got == expected
    if require and not ok:
        bad = [k for k, v in detail.items() if not v["match"]]
        sys.exit(f"holdout freeze mismatch: {bad}")
    return {"present": True, "frozen_at_utc": man.get("frozen_at_utc"),
            "note": man.get("note"), "files": detail, "ok": ok}


def sample_row_usable(c):
    """The deliverable requires a series id, an accession and a filing link."""
    return (bool(str(c.get("series_id") or "").strip())
            and bool(str(c.get("accession_number") or "").strip())
            and bool(str(c.get("link") or "").strip()))


def select_samples(candidates, seed, n=30):
    strong = [c for c in candidates if c["strong"]]
    flagged_all = group_worst([c for c in strong if c["share"] < 0.80])
    flagged_keys = {c["series_key"] for c in flagged_all}
    clean_all = group_worst([c for c in strong if c["series_key"] not in flagged_keys])
    robust = group_worst([c for c in strong
                          if c["share"] < 0.80 and c["share_core"] is not None
                          and math.isfinite(c["share_core"]) and c["share_core"] < 0.80])
    # Sampling frame: only rows that carry the identifiers the deliverable
    # promises. The scored/flagged counts are unchanged; this only removes
    # rows with a blank SERIES_ID from the sample draw.
    flagged = [c for c in flagged_all if sample_row_usable(c)]
    clean = [c for c in clean_all if sample_row_usable(c)]
    rng = random.Random(seed)
    flagged_sample = rng.sample(flagged, min(n, len(flagged)))
    clean_sample = rng.sample(clean, min(n, len(clean)))
    return {
        "flagged": flagged,
        "clean": clean,
        "robust": robust,
        "flagged_sample": flagged_sample,
        "clean_sample": clean_sample,
        "flagged_all": len(flagged_all),
        "clean_all": len(clean_all),
        "flagged_missing_id": len(flagged_all) - len(flagged),
        "clean_missing_id": len(clean_all) - len(clean),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarter", default="2026q2")
    ap.add_argument("--seed", type=int, default=20261119)
    ap.add_argument("--out-suffix", default="",
                    help="suffix for results/samples/findings, e.g. _holdout")
    ap.add_argument("--role", default="exploratory",
                    help="exploratory (seen) or holdout (frozen-rule evaluation)")
    ap.add_argument("--require-freeze", action="store_true",
                    help="fail unless names.py/score.py match holdout_freeze.json")
    args = ap.parse_args()
    freeze = check_freeze_manifest(require=args.require_freeze)

    zip_path = DATA / f"{args.quarter}_nport.zip"
    prov_path = DATA / f"{args.quarter}_provenance.json"
    if not zip_path.exists():
        sys.exit(f"missing {zip_path}; run download.py first")
    prov = json.loads(prov_path.read_text()) if prov_path.exists() else {}

    zf = zipfile.ZipFile(zip_path)
    m_info = find_member(zf, "FUND_REPORTED_INFO")
    m_hold = find_member(zf, "FUND_REPORTED_HOLDING")
    m_reg = find_member(zf, "REGISTRANT")
    m_sub = find_member(zf, "SUBMISSION")
    for name, m in [("FUND_REPORTED_INFO", m_info),
                    ("FUND_REPORTED_HOLDING", m_hold),
                    ("REGISTRANT", m_reg), ("SUBMISSION", m_sub)]:
        if not m:
            sys.exit(f"missing table {name} in {zip_path.name}")

    info = load_small(zf, m_info, ["SERIES_NAME", "SERIES_ID", "NET_ASSETS",
                                   "TOTAL_ASSETS", "CASH_NOT_RPTD_IN_C_OR_D"])
    reg = load_small(zf, m_reg, ["CIK", "REGISTRANT_NAME"])
    sub = load_small(zf, m_sub, ["FILING_DATE", "PERIOD", "SUBMISSION_TYPE"])

    funds = {}
    filenames = {}
    filing_groups = {}
    for acc, rec in info.items():
        name = rec.get("SERIES_NAME", "").strip()
        sid = rec.get("SERIES_ID", "").strip()
        key = sid or acc
        net = num(rec.get("NET_ASSETS"))
        cash_nr = num(rec.get("CASH_NOT_RPTD_IN_C_OR_D")) or 0.0
        filing = sub.get(acc, {}).get("FILING_DATE", "")
        cats = name_to_test(name)
        row = {
            "accession": accession_dashes(acc),
            "series_id": sid,
            "series_name": name,
            "series_key": key,
            "net_assets": net,
            "cash_not_reported": cash_nr,
            "categories": cats,
            "testable": [h["category"] for h in cats if h["testable"]],
            "untestable": [h["category"] for h in cats if not h["testable"]],
            "filing_date": filing,
            "filing_date_parsed": parse_filing_date(filing),
            "cik": (reg.get(acc, {}).get("CIK") or "").strip(),
        }
        filing_groups.setdefault(key, []).append(
            (row["filing_date_parsed"], filing, row["accession"]))
        prev = funds.get(key)
        if prev is None or (row["filing_date_parsed"], row["accession"]) > (
                prev["filing_date_parsed"], prev["accession"]):
            funds[key] = row
        filenames[acc] = name

    print(f"filings parsed: {len(info)}  unique series: {len(funds)}", flush=True)
    print(f"series with a testable name: {sum(1 for f in funds.values() if f['testable'])}", flush=True)

    dup_groups = {k: v for k, v in filing_groups.items() if len(v) > 1}
    dedup_examples = []
    for sid in ("S000077183", "S000073033"):
        if sid in funds:
            dedup_examples.append({
                "series_id": sid,
                "chosen_filing_date": funds[sid]["filing_date"],
                "all_filing_dates": [x[1] for x in sorted(filing_groups[sid])],
            })
    dedup_info = {
        "duplicate_series_groups": len(dup_groups),
        "filings_in_duplicate_groups": sum(len(v) for v in dup_groups.values()),
        "rule": "dedup by SERIES_ID (or accession when SERIES_ID is blank), keeping the latest parsed FILING_DATE; ties break on accession",
        "regression_examples": dedup_examples,
    }

    other_quarter = {"2026q1": "2026q2", "2026q2": "2026q1"}.get(args.quarter)
    other_ids = (series_ids_in_zip(DATA / f"{other_quarter}_nport.zip")
                 if other_quarter else None)

    acc_state = {}
    for f in funds.values():
        if f["testable"] and f["net_assets"] and f["net_assets"] > 0:
            acc_state[f["accession"].replace("-", "")] = {
                "fund": f,
                "n_holdings": 0, "n_missing_value": 0, "n_deriv": 0,
                "total_usd": 0.0, "total_pct": 0.0,
                "cash_usd": 0.0, "deriv_usd": 0.0,
                "rf_usd": 0.0, "fund_like_usd": 0.0, "nuss_usd": 0.0,
                "em_extended_usd": 0.0, "em_uncertain_usd": 0.0,
                "corp_usd": 0.0, "us_usd": 0.0, "usga_usd": 0.0,
                "deriv_abs": 0.0, "dir_other_abs": 0.0,
                "ep_all_usd": 0.0, "ep_core_usd": 0.0,
                "ep_not_debt_usd": 0.0, "ep_not_debt_core_usd": 0.0,
                "all": {p: 0.0 for p in PRED_ORDER},
                "core": {p: 0.0 for p in PRED_ORDER},
                "pct": {p: 0.0 for p in PRED_ORDER},
            }

    print(f"scoring accessions with holdings: {len(acc_state)}", flush=True)
    value_mode, pct_scale = VALUE_MODE, PCT_SCALE
    vm_stats = validate_value_units(zf, m_hold, acc_state)
    print(f"value rule (fixed): {vm_stats['chosen']} "
          f"(median error vs PERCENTAGE {vm_stats['chosen_median_abs_error']})", flush=True)

    debt_ids = set()
    m_debt = find_member(zf, "DEBT_SECURITY")
    if m_debt:
        with zf.open(m_debt) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
            r = csv.reader(text, delimiter="\t")
            header = [x.strip().upper().lstrip("\ufeff") for x in next(r)]
            ix = {x: i for i, x in enumerate(header)}
            hi = ix.get("HOLDING_ID")
            if hi is not None:
                for row in r:
                    if hi < len(row):
                        debt_ids.add(row[hi].strip())
        print(f"debt-security holding ids: {len(debt_ids):,}", flush=True)

    with zf.open(m_hold) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        r = csv.reader(text, delimiter="\t")
        header = [h.strip().upper().lstrip("\ufeff") for h in next(r)]
        ix = {h: i for i, h in enumerate(header)}
        i_acc = ix.get("ACCESSION_NUMBER")
        if i_acc is None:
            sys.exit("holdings table has no ACCESSION_NUMBER")
        def get(row, name):
            i = ix.get(name)
            return row[i] if i is not None and i < len(row) else ""
        nrows = 0
        for row in r:
            nrows += 1
            acc = row[i_acc].strip().replace("-", "")
            st = acc_state.get(acc)
            if st is None:
                continue
            holding_id = get(row, "HOLDING_ID").strip()
            h = {
                "holding_id": holding_id,
                "issuer_name": get(row, "ISSUER_NAME"),
                "issuer_title": get(row, "ISSUER_TITLE"),
                "currency_value": get(row, "CURRENCY_VALUE"),
                "exchange_rate": get(row, "EXCHANGE_RATE"),
                "percentage": get(row, "PERCENTAGE"),
                "asset_cat": norm(get(row, "ASSET_CAT")),
                "issuer_type": norm(get(row, "ISSUER_TYPE")),
                "investment_country": norm(get(row, "INVESTMENT_COUNTRY")),
                "derivative_cat": norm(get(row, "DERIVATIVE_CAT")),
            }
            f = holding_flags(h, holding_id in debt_ids)
            usd = holding_usd(h, value_mode)
            pct = num(h["percentage"])
            st["n_holdings"] += 1
            if usd is None:
                st["n_missing_value"] += 1
                usd = 0.0
            st["total_usd"] += usd
            if pct is not None:
                st["total_pct"] += pct
            if f["is_cash"]:
                st["cash_usd"] += usd
            if f["is_deriv"]:
                st["n_deriv"] += 1
                st["deriv_usd"] += usd
                st["deriv_abs"] += abs(usd)
            if f["is_rf"] and not f["is_cash"]:
                st["rf_usd"] += usd
            issuer_blob = f"{h.get('issuer_name', '')} {h.get('issuer_title', '')}".upper()
            it = h["issuer_type"]
            fund_like = (f["is_rf"] or it == "PF" or
                         any(w in issuer_blob for w in (" FUND", " PORTFOLIO", " ETF", " INDEX")))
            if fund_like and not f["is_cash"]:
                st["fund_like_usd"] += usd
            if it == "NUSS":
                st["nuss_usd"] += usd
            if f["em_extended"]:
                st["em_extended_usd"] += usd
            if f["em_uncertain"]:
                st["em_uncertain_usd"] += usd
            if it == "USGA":
                st["usga_usd"] += usd
            if it == "CORP":
                st["corp_usd"] += usd
            if h["investment_country"] in US_ALIASES:
                st["us_usd"] += usd
            if f["is_dir"] or f["is_other"]:
                st["dir_other_abs"] += abs(usd)
            core = not f["is_deriv"] and not f["is_cash"]
            if h["asset_cat"] == "EP":
                # Preferred is neither equity nor debt in the round-4 rule.
                st["ep_all_usd"] += usd
                if core:
                    st["ep_core_usd"] += usd
                if not f["bond"]:
                    st["ep_not_debt_usd"] += usd
                    if core:
                        st["ep_not_debt_core_usd"] += usd
            for p in PRED_ORDER:
                if f[p]:
                    st["all"][p] += usd
                    if core:
                        st["core"][p] += usd
                    if pct is not None:
                        st["pct"][p] += pct
            if nrows % 1_000_000 == 0:
                print(f"  holdings rows: {nrows:,}", flush=True)
    print(f"holdings rows read: {nrows:,}", flush=True)

    rows = []
    for acc, st in acc_state.items():
        f = st["fund"]
        na = f["net_assets"]
        if not na or na <= 0 or st["n_holdings"] == 0:
            continue
        denom_core = na - st["cash_usd"] - f["cash_not_reported"]
        invested = na - st["cash_usd"]
        rf_share = st["rf_usd"] / na
        rf_invested_share = (st["rf_usd"] / invested) if invested > 0 else 0.0
        fund_like_invested_share = (st["fund_like_usd"] / invested) if invested > 0 else 0.0
        deriv_abs_share = st["deriv_abs"] / na
        dir_other_share = st["dir_other_abs"] / na
        deriv_count_share = (st["n_deriv"] / st["n_holdings"]) if st["n_holdings"] else 0.0
        nuss_share = st["nuss_usd"] / na
        em_extended_share = st["em_extended_usd"] / na
        em_uncertain_share = st["em_uncertain_usd"] / na
        corp_share = st["corp_usd"] / na
        us_share = st["us_usd"] / na
        usga_share = st["usga_usd"] / na
        dbt_share = st["all"]["bond"] / na
        structure_reason = None
        if st["n_holdings"] <= 10 and (st["cash_usd"] / na) > 0.50:
            structure_reason = "cash-like shell: <=10 holdings and >50% cash-like"
        elif deriv_count_share >= 0.50:
            structure_reason = "derivative-structured: >=50% of holdings are derivatives"
        elif fund_like_invested_share > 0.25:
            structure_reason = "fund-of-funds: fund/ETF holdings >25% of invested assets"
        elif ("emerging_markets" in f["testable"] and dbt_share > 0.50
              and corp_share > 0.50):
            structure_reason = "EM corporate debt: country field is issuer domicile, not country of risk"
        elif ("emerging_markets" in f["testable"] and dbt_share > 0.50
              and usga_share > 0.50):
            structure_reason = "EM fund with US-agency-coded holdings; data not testable"
        elif deriv_abs_share > 0.50:
            structure_reason = "derivative-heavy: >50% of net assets in derivatives"
        elif dir_other_share > 0.50:
            structure_reason = "direct/other investments >50% of net assets"
        structure = {
            "untestable": structure_reason is not None,
            "reason": structure_reason,
            "rf_share": rf_share,
            "rf_invested_share": rf_invested_share,
            "fund_like_invested_share": fund_like_invested_share,
            "deriv_abs_share": deriv_abs_share,
            "dir_other_share": dir_other_share,
            "deriv_count_share": deriv_count_share,
            "n_deriv": st["n_deriv"],
            "nuss_share": nuss_share,
            "em_extended_share": em_extended_share,
            "em_uncertain_share": em_uncertain_share,
            "corp_share": corp_share,
            "us_share": us_share,
            "usga_share": usga_share,
            "dbt_share": dbt_share,
        }
        shares = {}
        for p in PRED_ORDER:
            share = st["all"][p] / na
            share_core = (st["core"][p] / denom_core) if denom_core > 0 else None
            shares[p] = {
                "share": share,
                "share_core": share_core,
                "pct_share": st["pct"][p] / pct_scale,
                "usd": st["all"][p],
                "usd_core": st["core"][p],
            }
        ep_bond_usd = st["all"]["bond"] + st["ep_not_debt_usd"]
        ep_bond_core = st["core"]["bond"] + st["ep_not_debt_core_usd"]
        ep_equity_usd = st["all"]["equity"] + st["ep_all_usd"]
        ep_equity_core = st["core"]["equity"] + st["ep_core_usd"]
        ep_variants = {
            "ep_all_usd": st["ep_all_usd"],
            "bond_with_ep_share": ep_bond_usd / na,
            "bond_with_ep_share_core": (ep_bond_core / denom_core) if denom_core > 0 else None,
            "equity_with_ep_share": ep_equity_usd / na,
            "equity_with_ep_share_core": (ep_equity_core / denom_core) if denom_core > 0 else None,
        }
        rows.append({
            "accession": f["accession"],
            "series_id": f["series_id"],
            "series_name": f["series_name"],
            "series_key": f["series_key"],
            "net_assets": na,
            "cash_not_reported": f["cash_not_reported"],
            "filing_date": f["filing_date"],
            "cik": f["cik"],
            "n_holdings": st["n_holdings"],
            "n_missing_value": st["n_missing_value"],
            "total_usd": st["total_usd"],
            "cash_usd": st["cash_usd"],
            "deriv_usd": st["deriv_usd"],
            "denom_core": denom_core,
            "em_extended_share": em_extended_share,
            "em_uncertain_share": em_uncertain_share,
            "structure": structure,
            "shares": shares,
            "ep_variants": ep_variants,
            "categories": f["categories"],
            "testable": f["testable"],
            "untestable": f["untestable"],
        })

    if not rows:
        sys.exit("no funds with holdings and usable net assets")

    pct_diffs = []
    for r in rows:
        for p in STRONG:
            if p in r["testable"]:
                pct_diffs.append(abs(r["shares"][p]["share"] - r["shares"][p]["pct_share"]))
    pct_diffs = [x for x in pct_diffs if math.isfinite(x)]

    cat = {}
    for p in PRED_ORDER:
        scored_all = [r for r in rows if p in r["testable"] and not r["structure"]["untestable"]]
        gray = [r for r in rows if p in r["testable"] and r["structure"]["untestable"]]
        scored = [r for r in scored_all
                  if r["shares"][p]["share"] is not None
                  and math.isfinite(r["shares"][p]["share"])
                  and 0.0 <= r["shares"][p]["share"] <= 2.0]
        shares = [r["shares"][p]["share"] for r in scored]
        flagged = sum(1 for x in shares if x < 0.80)
        robust_flags = [r for r in scored
                        if r["shares"][p]["share"] < 0.80
                        and r["shares"][p]["share_core"] is not None
                        and math.isfinite(r["shares"][p]["share_core"])
                        and r["shares"][p]["share_core"] < 0.80]
        core_shares = [r["shares"][p]["share_core"] for r in scored]
        core_shares = [x for x in core_shares if x is not None and math.isfinite(x)]
        cat[p] = {
            "testable": True,
            "predicate": PREDICATE_TEXT[p],
            "strength": "weak" if p in WEAK else "strong",
            "n_names_matched": sum(1 for f in funds.values() if p in [h["category"] for h in f["categories"]]),
            "n_scored": len(shares),
            "n_invalid_share": len(scored_all) - len(scored),
            "n_gray_structure": len(gray),
            "n_flagged": flagged,
            "n_flagged_robust": len(robust_flags),
            "n_gray_cash_deriv": flagged - len(robust_flags),
            "flag_rate": (flagged / len(shares)) if shares else None,
            "flag_rate_ci95": wilson(flagged, len(shares)),
            "flag_rate_robust": (len(robust_flags) / len(shares)) if shares else None,
            "flag_rate_ci95_robust": wilson(len(robust_flags), len(shares)),
            "share": dist(shares),
            "share_core": dist(core_shares),
            "histogram": histogram(shares),
        }
    for p, meta in CATEGORIES.items():
        if not meta["testable"]:
            n = sum(1 for f in funds.values() if p in [h["category"] for h in f["categories"]])
            cat[p] = {
                "testable": False,
                "reason": meta["basis"],
                "n_names_matched": n,
                "n_scored": 0,
                "n_flagged": 0,
                "flag_rate": None,
                "flag_rate_ci95": None,
                "share": None,
                "share_core": None,
                "histogram": None,
            }

    def valid(r, p):
        v = r["shares"][p]["share"]
        return v is not None and math.isfinite(v) and 0.0 <= v <= 2.0
    scored_unique = {r["series_key"] for r in rows
                     if not r["structure"]["untestable"]
                     and any(p in r["testable"] and valid(r, p) for p in STRONG)}
    scored_any_unique = {r["series_key"] for r in rows
                         if not r["structure"]["untestable"]
                         and any(p in r["testable"] and valid(r, p) for p in PRED_ORDER)}
    flagged_strong_unique = {r["series_key"] for r in rows
                             if not r["structure"]["untestable"]
                             and any(p in r["testable"] and valid(r, p)
                                     and r["shares"][p]["share"] < 0.80 for p in STRONG)}
    flagged_any_unique = {r["series_key"] for r in rows
                          if not r["structure"]["untestable"]
                          and any(p in r["testable"] and valid(r, p)
                                  and r["shares"][p]["share"] < 0.80 for p in PRED_ORDER)}
    flagged_robust_unique = {r["series_key"] for r in rows
                             if not r["structure"]["untestable"]
                             and any(p in r["testable"] and valid(r, p)
                                     and r["shares"][p]["share"] < 0.80
                                     and r["shares"][p]["share_core"] is not None
                                     and r["shares"][p]["share_core"] < 0.80 for p in STRONG)}
    structure_untestable_unique = {r["series_key"] for r in rows if r["structure"]["untestable"]}

    def valid_share(v):
        return v is not None and math.isfinite(v) and 0.0 <= v <= 2.0

    def subset_summary(keys):
        rr = [r for r in rows if r["series_key"] in keys]
        inc = [r for r in rr if not r["structure"]["untestable"]]
        scored_strong = {r["series_key"] for r in inc
                         if any(p in r["testable"] and valid(r, p) for p in STRONG)}
        scored_any = {r["series_key"] for r in inc
                      if any(p in r["testable"] and valid(r, p) for p in PRED_ORDER)}
        flag_strong = {r["series_key"] for r in inc
                       if any(p in r["testable"] and valid(r, p)
                              and r["shares"][p]["share"] < 0.80 for p in STRONG)}
        flag_any = {r["series_key"] for r in inc
                    if any(p in r["testable"] and valid(r, p)
                           and r["shares"][p]["share"] < 0.80 for p in PRED_ORDER)}
        return {
            "n_series_in_subset": len(keys),
            "n_scored_strong": len(scored_strong),
            "n_scored_any": len(scored_any),
            "n_flagged_strong": len(flag_strong),
            "n_flagged_any": len(flag_any),
        }

    ep_bond_changes = []
    ep_equity_changes = []
    ep_funds_with_holdings = 0
    for r in rows:
        if r["structure"]["untestable"]:
            continue
        if abs(r["ep_variants"]["ep_all_usd"]) > 1e-9:
            ep_funds_with_holdings += 1
        if "bond" in r["testable"]:
            new = r["shares"]["bond"]["share"]
            old = r["ep_variants"]["bond_with_ep_share"]
            if valid_share(new) and valid_share(old) and ((new < 0.80) != (old < 0.80)):
                ep_bond_changes.append({
                    "series_id": r["series_id"],
                    "series_name": r["series_name"],
                    "share_without_ep": new,
                    "share_with_ep": old,
                    "flagged_without_ep": new < 0.80,
                    "flagged_with_ep": old < 0.80,
                })
        if "equity" in r["testable"]:
            new = r["shares"]["equity"]["share"]
            old = r["ep_variants"]["equity_with_ep_share"]
            if valid_share(new) and valid_share(old) and ((new < 0.80) != (old < 0.80)):
                ep_equity_changes.append({
                    "series_id": r["series_id"],
                    "series_name": r["series_name"],
                    "share_without_ep": new,
                    "share_with_ep": old,
                    "flagged_without_ep": new < 0.80,
                    "flagged_with_ep": old < 0.80,
                })
    ep_sensitivity = {
        "preferred_asset_cat": "EP",
        "rule": ("EP is neither equity nor debt. share_without_ep is the round-4 "
                 "test; share_with_ep is the counterfactual that puts EP back in "
                 "the old equity and debt sets."),
        "n_funds_with_ep_holdings_scored": ep_funds_with_holdings,
        "n_funds_with_ep_unscored": sum(
            1 for r in rows if r["structure"]["untestable"]
            and abs(r["ep_variants"]["ep_all_usd"]) > 1e-9),
        "n_bond_flag_status_changes": len(ep_bond_changes),
        "n_equity_flag_status_changes": len(ep_equity_changes),
        "bond_flag_changes": sorted(
            ep_bond_changes,
            key=lambda x: -(x["share_with_ep"] - x["share_without_ep"]))[:20],
        "equity_flag_changes": sorted(
            ep_equity_changes,
            key=lambda x: -(x["share_with_ep"] - x["share_without_ep"]))[:20],
    }

    if other_ids is not None:
        disjoint_keys = {k for k, f in funds.items()
                         if f["series_id"] and f["series_id"] not in other_ids}
        fund_disjoint = subset_summary(disjoint_keys)
        fund_disjoint["compared_with_quarter"] = other_quarter
        fund_disjoint["n_series_blank_id_cannot_match"] = sum(
            1 for f in funds.values() if not f["series_id"])
    else:
        fund_disjoint = None

    epb_keys = {k for k, f in funds.items()
                if is_post_hoc_equity_plus_bond(f["series_name"])}
    epb = subset_summary(epb_keys)
    epb["n_series_matched"] = len(epb_keys)
    epb["n_series_already_excluded_as_mixed"] = sum(
        1 for k in epb_keys if "mixed" in funds[k]["untestable"])
    epb["examples"] = sorted(funds[k]["series_name"] for k in epb_keys)[:10]
    epb["note"] = ("These names are classed mixed by the round-2 'Equity Plus "
                   "Bond' fix, so the fixed rule scores none of them. Removing "
                   "them from the scored set changes no scored or flag count; "
                   "the effect of the fix is that they are excluded, not scored "
                   "as equity.")
    subsets = {"fund_disjoint": fund_disjoint,
               "equity_plus_bond_removed": epb}

    def structure_reason_with(r, cfg):
        na = r["net_assets"]
        st = r["structure"]
        if (r["n_holdings"] <= cfg["cash_max_holdings"]
                and na and (r["cash_usd"] / na) > cfg["cash_min"]):
            return "cash-like shell"
        if st["deriv_count_share"] >= cfg["deriv_count"]:
            return "derivative-structured"
        if st["fund_like_invested_share"] > cfg["fund_like"]:
            return "fund-of-funds"
        if (cfg.get("em_coding", True) and "emerging_markets" in r["testable"]
                and st["dbt_share"] > 0.50 and st["corp_share"] > 0.50):
            return "EM corporate debt"
        if (cfg.get("em_coding", True) and "emerging_markets" in r["testable"]
                and st["dbt_share"] > 0.50 and st["usga_share"] > 0.50):
            return "EM US-agency coding"
        if st["deriv_abs_share"] > cfg["deriv_abs"]:
            return "derivative-heavy"
        if st["dir_other_share"] > cfg["dir_other"]:
            return "direct/other"
        return None

    STRUCTURE_VARIANTS = {
        "baseline": dict(fund_like=0.25, deriv_count=0.50, deriv_abs=0.50,
                         dir_other=0.50, cash_max_holdings=10, cash_min=0.50,
                         em_coding=True),
        "tighter_exclusions": dict(fund_like=0.15, deriv_count=0.40, deriv_abs=0.40,
                                   dir_other=0.40, cash_max_holdings=15, cash_min=0.40,
                                   em_coding=True),
        "looser_exclusions": dict(fund_like=0.40, deriv_count=0.60, deriv_abs=0.60,
                                  dir_other=0.60, cash_max_holdings=5, cash_min=0.60,
                                  em_coding=True),
        "no_structure_screen": dict(fund_like=9.99, deriv_count=9.99, deriv_abs=9.99,
                                    dir_other=9.99, cash_max_holdings=-1, cash_min=9.99,
                                    em_coding=False),
    }
    structure_sensitivity = {}
    for label, cfg in STRUCTURE_VARIANTS.items():
        inc = [r for r in rows if structure_reason_with(r, cfg) is None]
        s_unique = {r["series_key"] for r in inc
                    if any(p in r["testable"] and valid(r, p) for p in STRONG)}
        f_unique = {r["series_key"] for r in inc
                    if any(p in r["testable"] and valid(r, p)
                           and r["shares"][p]["share"] < 0.80 for p in STRONG)}
        rb_unique = {r["series_key"] for r in inc
                     if any(p in r["testable"] and valid(r, p)
                            and r["shares"][p]["share"] < 0.80
                            and r["shares"][p]["share_core"] is not None
                            and r["shares"][p]["share_core"] < 0.80 for p in STRONG)}
        structure_sensitivity[label] = {
            "scored_unique_strong": len(s_unique),
            "flagged_unique_strong": len(f_unique),
            "flagged_unique_robust": len(rb_unique),
            "excluded_unique": len({r["series_key"] for r in rows}) - len(s_unique),
        }

    em_rows = [r for r in rows if "emerging_markets" in r["testable"]
               and not r["structure"]["untestable"] and valid(r, "emerging_markets")]
    em_strict_flags = [r for r in em_rows if r["shares"]["emerging_markets"]["share"] < 0.80]
    em_extended_flags = [r for r in em_rows if r["em_extended_share"] < 0.80]
    em_uncertain_material = [r for r in em_rows if r["em_uncertain_share"] > 0.05]
    em_sensitivity = {
        "proxy": "EM_CORE (24 MSCI EM countries) + EM_HUBS (KY, BM, VG, MU, JE, GG); NUSS is not automatic",
        "n_em_funds_scored": len(em_rows),
        "n_flagged_strict_proxy": len(em_strict_flags),
        "n_flagged_extended_proxy": len(em_extended_flags),
        "extended_proxy_adds": sorted(EM_EXTENDED_HUBS),
        "n_funds_with_material_uncertain_nuss": len(em_uncertain_material),
        "max_uncertain_nuss_share": max((r["em_uncertain_share"] for r in em_rows), default=0.0),
    }

    testable_n = sum(1 for f in funds.values() if f["testable"])
    nonpositive = sum(1 for f in funds.values()
                      if f["testable"] and (not f["net_assets"] or f["net_assets"] <= 0))
    data_quality = {
        "filings_parsed": len(info),
        "unique_series": len(funds),
        "series_with_net_assets": sum(1 for f in funds.values() if f["net_assets"] and f["net_assets"] > 0),
        "series_with_testable_name": testable_n,
        "testable_series_positive_net_assets": len(acc_state),
        "testable_series_scored": len(rows),
        "testable_series_skipped": len(acc_state) - len(rows),
        "testable_series_nonpositive_net_assets": nonpositive,
        "series_scored_strong": len(scored_unique),
        "series_scored_before_structure": len({r["series_key"] for r in rows
                                               if r["testable"]}),
        "series_scored_any_after_structure": len(scored_any_unique),
        "series_scored_strong_after_structure": len(scored_unique),
        "series_scored_any": len(scored_any_unique),
        "structure_untestable_unique": len(structure_untestable_unique),
        "dedup": dedup_info,
        "ep_sensitivity": ep_sensitivity,
        "subsets": subsets,
        "structure_breakdown": {
            "fund_of_funds": sum(1 for r in rows if (r["structure"]["reason"] or "").startswith("fund-of-funds")),
            "derivative_structured": sum(1 for r in rows if (r["structure"]["reason"] or "").startswith("derivative-structured")),
            "em_corporate_coding": sum(1 for r in rows if (r["structure"]["reason"] or "").startswith("EM corporate")),
            "em_usga_coding": sum(1 for r in rows if (r["structure"]["reason"] or "").startswith("EM fund with US-agency")),
            "derivative_heavy": sum(1 for r in rows if (r["structure"]["reason"] or "").startswith("derivative-heavy")),
            "direct_other": sum(1 for r in rows if (r["structure"]["reason"] or "").startswith("direct/other")),
            "cash_shell": sum(1 for r in rows if (r["structure"]["reason"] or "").startswith("cash-like")),
        },
        "median_abs_share_vs_pct_diff": float(np.median(pct_diffs)) if pct_diffs else None,
        "p95_abs_share_vs_pct_diff": float(np.percentile(pct_diffs, 95)) if pct_diffs else None,
        "funds_with_missing_holding_values": sum(1 for r in rows if r["n_missing_value"] > 0),
        "holdings_rows": nrows,
        "value_mode": value_mode,
        "pct_scale": pct_scale,
        "value_mode_rows_considered": vm_stats["rows_considered"],
        "value_mode_median_abs_error": vm_stats["chosen_median_abs_error"],
        "value_unit_validation": vm_stats,
        "structure_sensitivity": structure_sensitivity,
        "em_sensitivity": em_sensitivity,
    }

    results = {
        "quarter": args.quarter,
        "role": args.role,
        "role_label": ("frozen-rule score (same funds as the exploratory quarter)"
                       if args.role == "frozen_rule" else "exploratory"),
        "out_suffix": args.out_suffix,
        "freeze_manifest": freeze,
        "source": prov,
        "sec_direct_http_status": prov.get("sec_probe"),
        "generated_by": "work/T08/score.py",
        "seed": args.seed,
        "funds": {
            "filings_parsed": len(info),
            "unique_series": len(funds),
            "testable_named_series": testable_n,
            "testable_series_with_positive_net_assets": len(acc_state),
            "scored_before_structure": len({r["series_key"] for r in rows
                                            if r["testable"]}),
            "scored_unique_strong": len(scored_unique),
            "scored_unique_any": len(scored_any_unique),
            "flagged_unique_strong": len(flagged_strong_unique),
            "flagged_unique_robust": len(flagged_robust_unique),
            "flagged_unique_any": len(flagged_any_unique),
            "structure_untestable_unique": len(structure_untestable_unique),
        },
        "categories": cat,
        "data_quality": data_quality,
        "notes": {
            "flag_definition": "flagged when share = (USD value of holdings matching the predicate) / NET_ASSETS < 0.80",
            "share_core": "sensitivity: predicate holdings excluding derivatives and cash-like names, divided by NET_ASSETS less cash-like holdings and CASH_NOT_RPTD_IN_C_OR_D",
            "global": "global is a weak test because a global fund may hold US securities; global flags are reported but kept out of the strong flagged sample",
            "emerging_markets": "EM requires INVESTMENT_COUNTRY in EM_CORE or EM_HUBS; ISSUER_TYPE==NUSS alone is not EM. Non-EM NUSS is recorded as uncertain, not counted.",
            "structure_sensitivity": "the same rows are re-screened under tighter, looser and no structural cutoffs; see data_quality.structure_sensitivity",
            "high_yield": "not scored: N-PORT has no credit-rating field",
            "sector": "not scored: N-PORT has no issuer-industry field",
            "small_mid_cap": "not scored: N-PORT has no market-cap field",
            "robust_flag": "a flag is called robust when it survives the cash/derivative sensitivity: share < 0.80 and share_core < 0.80",
            "not_a_legal_finding": "below the 80% line by our test is not a claim of a legal violation",
            "preferred": "EP (equity preferred) counts as neither equity nor debt; data_quality.ep_sensitivity reports the funds whose flag status changes under the old treatment",
            "money_market": "money-market names are classified as an untestable category, not silently returned as no match",
            "flags_file": "flags.csv lists every strong and any-test flag (one row per fund and test) with an EDGAR link; flags_exploratory.csv is the 2026q2 equivalent",
            "any_test": "scored_unique_any is counted after the structural screen; testable_named_series, scored_before_structure and structure_untestable_unique show the split",
        },
    }

    suffix = args.out_suffix
    out_json = HERE / f"results{suffix}.json"
    out_json.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {out_json.name}", flush=True)

    candidates = []
    for r in rows:
        if r["structure"]["untestable"]:
            continue
        for p in r["testable"]:
            sh = r["shares"][p]["share"]
            if sh is None or not math.isfinite(sh) or not (0.0 <= sh <= 2.0):
                continue
            sc = r["shares"][p]["share_core"]
            robust = (sh < 0.80 and sc is not None and math.isfinite(sc) and sc < 0.80)
            candidates.append({
                "series_key": r["series_key"],
                "series_id": r["series_id"],
                "series_name": r["series_name"],
                "accession_number": r["accession"],
                "category": p,
                "share": sh,
                "share_core": sc,
                "net_assets_usd": r["net_assets"],
                "filing_date": r["filing_date"],
                "cik": r["cik"],
                "link": edgar_link(r["accession"], r["cik"]),
                "strong": p in STRONG,
                "robust": robust,
            })

    sampled = select_samples(candidates, args.seed)
    flagged = sampled["flagged"]
    clean = sampled["clean"]
    robust = sampled["robust"]
    flagged_sample = sampled["flagged_sample"]
    clean_sample = sampled["clean_sample"]
    flagged_keys_all = {c["series_key"] for c in candidates
                        if c["strong"] and c["share"] < 0.80}
    clean_cross_flags = sum(1 for c in clean_sample
                            if c["series_key"] in flagged_keys_all)
    flagged_non_headline = sum(1 for c in flagged_sample if c["share"] >= 0.80)
    if clean_cross_flags or flagged_non_headline:
        sys.exit(f"sample invariant failed: clean cross flags {clean_cross_flags}, "
                 f"flagged non-headline {flagged_non_headline}")

    fields = ["series_id", "series_name", "category", "share", "share_core",
              "robust", "accession_number", "cik", "filing_date",
              "net_assets_usd", "link"]
    def write_csv(path, sample, field_list=None):
        fs = field_list or fields
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fs, extrasaction="ignore")
            w.writeheader()
            for c in sorted(sample, key=lambda x: x["share"]):
                row = {}
                for k in fs:
                    if k == "share" or k == "share_core":
                        v = c.get(k)
                        row[k] = (round(v, 6) if v is not None else "")
                    else:
                        row[k] = c.get(k, "")
                w.writerow(row)

    # Pass-bar item: every flag, not just the 30-row sample, carries a link.
    flag_rows = [c for c in candidates if c["share"] < 0.80]
    flags_fields = ["series_id", "series_name", "category", "share", "share_core",
                    "strong", "robust", "accession_number", "cik", "filing_date",
                    "net_assets_usd", "link"]
    write_csv(HERE / f"flags{suffix}.csv", flag_rows, flags_fields)
    flag_strong_keys = {c["series_key"] for c in flag_rows if c["strong"]}
    flag_any_keys = {c["series_key"] for c in flag_rows}
    linkless = [c for c in flag_rows if not str(c.get("link") or "").strip()]
    if flag_strong_keys != flagged_strong_unique:
        sys.exit("flags.csv strong-flag set does not match funds.flagged_unique_strong")
    if flag_any_keys != flagged_any_unique:
        sys.exit("flags.csv any-flag set does not match funds.flagged_unique_any")
    if linkless:
        sys.exit(f"{len(linkless)} flag rows have no EDGAR link")
    print(f"flags.csv: {len(flag_rows)} flag rows, {len(flag_any_keys)} unique funds, "
          f"{len(flag_strong_keys)} unique strong flags, all linked", flush=True)

    for label, sample in (("flagged", flagged_sample), ("clean", clean_sample)):
        missing = [c for c in sample if not str(c.get("series_id") or "").strip()]
        if missing:
            sys.exit(f"{label} sample has {len(missing)} rows with a blank series_id")
    write_csv(HERE / f"flagged_sample{suffix}.csv", flagged_sample)
    write_csv(HERE / f"clean_sample{suffix}.csv", clean_sample)
    print(f"flagged sample: {len(flagged_sample)}  clean sample: {len(clean_sample)}", flush=True)

    results["samples"] = {
        "flagged_rows": len(flagged_sample),
        "clean_rows": len(clean_sample),
        "flagged_candidates": len(flagged),
        "clean_candidates": len(clean),
        "robust_flagged_candidates": len(robust),
        "headline_flagged_candidates": len(flagged),
        "flagged_candidates_before_id_filter": sampled.get("flagged_all", len(flagged)),
        "clean_candidates_before_id_filter": sampled.get("clean_all", len(clean)),
        "flagged_candidates_missing_series_id": sampled.get("flagged_missing_id", 0),
        "clean_candidates_missing_series_id": sampled.get("clean_missing_id", 0),
        "rule": ("flagged sample is a uniform random draw over unique funds with any strong "
                 "headline flag (share < 0.80) and a non-empty series id, accession and link; "
                 "the robust subset (share_core < 0.80) is reported separately and is not the "
                 "sampling frame"),
        "clean_rule": ("clean sample is drawn only from funds with no strong headline flag in "
                       "any valid strong category and a non-empty series id, accession and link; "
                       "each row is the fund's lowest strong share"),
        "clean_sample_cross_category_flags": clean_cross_flags,
        "flagged_sample_non_headline": flagged_non_headline,
        "flagged_plus_clean": len(flagged) + len(clean),
        "flags_rows": len(flag_rows),
        "flags_unique_any": len(flag_any_keys),
        "flags_unique_strong": len(flag_strong_keys),
        "flags_linkless": len(linkless),
        "flags_file": f"flags{suffix}.csv",
        "seed": args.seed,
    }
    out_json.write_text(json.dumps(results, indent=2) + "\n")

    make_findings(zf, m_hold, rows, flagged, args.seed, value_mode, debt_ids,
                  out_path=HERE / f"FINDINGS{suffix}.md")

    print("\nSUMMARY")
    print(f"  filings parsed: {len(info):,}")
    print(f"  unique series: {len(funds):,}")
    print(f"  scored unique (strong): {len(scored_unique):,}")
    print(f"  scored unique (any, after structure screen): {len(scored_any_unique):,}")
    print(f"  structurally untestable unique: {len(structure_untestable_unique):,}")
    print(f"  flagged unique (strong): {len(flagged_strong_unique):,}")
    print(f"  flagged unique (any): {len(flagged_any_unique):,}")
    print(f"  EP bond flag-status changes: {ep_sensitivity['n_bond_flag_status_changes']}")
    print(f"  median |share - pct_share|: {data_quality['median_abs_share_vs_pct_diff']}")
    for p in STRONG + WEAK:
        c = cat[p]
        if c["n_scored"]:
            print(f"  {p:18} scored {c['n_scored']:5}  flagged {c['n_flagged']:5}  "
                  f"rate {c['flag_rate']:.3f}  median {c['share']['median']:.3f}")
    for p in CATEGORIES:
        c = cat[p]
        if not c["testable"]:
            print(f"  {p:18} UNTESTABLE  names {c['n_names_matched']:5}  ({c['reason']})")


def make_findings(zf, m_hold, rows, flagged, seed, value_mode="mul", debt_ids=None, out_path=None):
    if not flagged:
        (out_path or (HERE / "FINDINGS.md")).write_text("# Findings\n\nNo strong-category funds fell below the 80% line by our test.\n")
        return
    robust = [c for c in flagged
              if c.get("share_core") is not None and c["share_core"] < 0.80]
    clear = [c for c in robust if c["share"] < 0.75]
    pool = clear if len(clear) >= 5 else robust
    by_cat = {}
    for c in pool:
        by_cat.setdefault(c["category"], []).append(c)
    picked = []
    for p in STRONG:
        if p in by_cat:
            picked.append(max(by_cat[p], key=lambda c: c["net_assets_usd"]))
    picked_cats = {c["category"] for c in picked}
    rest = sorted([c for c in pool if c not in picked
                   and c["category"] not in picked_cats],
                  key=lambda c: c["net_assets_usd"], reverse=True)
    picked = (picked + rest)[:5]
    picked_cats = {c["category"] for c in picked}
    if len(picked) < 5:
        # Extend to the full strong-flag set to keep one fund per category.
        extra = sorted([c for c in flagged if c not in picked
                        and c["category"] not in picked_cats],
                       key=lambda c: c["net_assets_usd"], reverse=True)
        picked = (picked + extra)[:5]
        picked_cats = {c["category"] for c in picked}
    if len(picked) < 5:
        # Only when fewer than five distinct categories have any strong flag:
        # fill the remaining slots with the largest remaining flags. State it.
        extra = sorted([c for c in flagged if c not in picked],
                       key=lambda c: c["net_assets_usd"], reverse=True)
        picked = (picked + extra)[:5]
    accs = {c["accession_number"].replace("-", "") for c in picked}
    holdings = {a: [] for a in accs}
    with zf.open(m_hold) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        r = csv.reader(text, delimiter="\t")
        header = [h.strip().upper().lstrip("\ufeff") for h in next(r)]
        ix = {h: i for i, h in enumerate(header)}
        def get(row, name):
            i = ix.get(name)
            return row[i] if i is not None and i < len(row) else ""
        debt_ids = debt_ids or set()
        for row in r:
            a = get(row, "ACCESSION_NUMBER").strip().replace("-", "")
            if a in holdings:
                holdings[a].append({
                    "holding_id": get(row, "HOLDING_ID").strip(),
                    "issuer_name": get(row, "ISSUER_NAME"),
                    "issuer_title": get(row, "ISSUER_TITLE"),
                    "currency_value": get(row, "CURRENCY_VALUE"),
                    "exchange_rate": get(row, "EXCHANGE_RATE"),
                    "percentage": get(row, "PERCENTAGE"),
                    "asset_cat": norm(get(row, "ASSET_CAT")),
                    "issuer_type": norm(get(row, "ISSUER_TYPE")),
                    "investment_country": norm(get(row, "INVESTMENT_COUNTRY")),
                    "derivative_cat": norm(get(row, "DERIVATIVE_CAT")),
                })
    lines = ["# Findings: five real funds below the 80% line by our test", "",
             "Selected automatically: the largest net-asset strong-category flags that stay below 75% and below the line "
             "after removing cash and derivatives from the sensitivity. Selection takes one fund per category first, then "
             "the largest remaining funds from categories not already chosen, extending to the full strong-flag set to keep "
             "one fund per category. Only if fewer than five distinct categories have any strong flag are the remaining slots "
             "filled by the largest remaining flags, and then a category can repeat. "
             "Every figure below comes from `score.py` and the same cached N-PORT file.",
             "", "These are test results, not legal findings.", ""]
    for i, c in enumerate(picked, 1):
        a = c["accession_number"].replace("-", "")
        hs = holdings.get(a, [])
        fund = next((r for r in rows if r["accession"] == c["accession_number"]), None)
        if not fund:
            continue
        sh = fund["shares"][c["category"]]
        f = lambda h: holding_flags(h, (h.get("holding_id") or "") in debt_ids)
        nonsat = [h for h in hs
                  if not f(h)[c["category"]] and (holding_usd(h, value_mode) or 0) > 0]
        nonsat.sort(key=lambda h: abs(holding_usd(h, value_mode) or 0), reverse=True)
        top = nonsat[:3]
        lines.append(f"## {i}. {c['series_name']}")
        lines.append("")
        lines.append(f"- Series id: `{c['series_id'] or 'n/a'}`; accession `{c['accession_number']}`; "
                     f"filed {c['filing_date'] or 'n/a'}; net assets ${c['net_assets_usd']:,.0f}.")
        core_txt = ("n/a" if sh["share_core"] is None else f"{sh['share_core']*100:.1f}%")
        lines.append(f"- Category **{c['category']}**; share by our test **{sh['share']*100:.1f}%** "
                     f"(sensitivity on the securities book: {core_txt}).")
        lines.append(f"- Filing: {c['link']}")
        if top:
            bits = []
            for h in top:
                u = holding_usd(h, value_mode)
                pct = (u / fund["net_assets"] * 100.0) if u is not None and fund["net_assets"] else None
                hf = f(h)
                tag = "cash-like" if hf["is_cash"] else (
                    "derivative" if hf["is_deriv"] else h["asset_cat"] or "n/a")
                name = (h["issuer_name"] or h["issuer_title"] or "unnamed").strip()
                bits.append(f"{name} ({tag}, {pct:.1f}% of net assets)" if pct is not None else f"{name} ({tag})")
            lines.append("- Largest holdings outside the predicate: " + "; ".join(bits) + ".")
        all_flags = [(p, fund["shares"][p]["share"]) for p in STRONG if p in fund["testable"]]
        all_flags = [(p, s) for p, s in all_flags if s is not None]
        if all_flags:
            lines.append("- Other strong tests for this fund: " +
                         ", ".join(f"{p} {s*100:.1f}%" for p, s in all_flags) + ".")
        lines.append("")
    (out_path or (HERE / "FINDINGS.md")).write_text("\n".join(lines))


if __name__ == "__main__":
    main()
