#!/usr/bin/env python3
"""Measure fund-identity overlap between the 2026q1 score and 2026q2.

The rule is name-based, so a quarter score is not automatically a
disjoint-fund score. This script reports the series-id intersection so the
report can state the limitation instead of hiding it. Two denominators are
reported: the identified-series overlap (non-empty SERIES_ID) and the
all-series overlap (blank-id series cannot be matched across quarters).
"""

import csv
import io
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "data" / "sec"


def series_ids(quarter):
    path = DATA / f"{quarter}_nport.zip"
    zf = zipfile.ZipFile(path)
    member = next(n for n in zf.namelist()
                  if n.upper().endswith("FUND_REPORTED_INFO.TSV"))
    ids = set()
    keys = set()
    blank = 0
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        r = csv.reader(text, delimiter="\t")
        header = [h.strip().upper().lstrip("\ufeff") for h in next(r)]
        ix = {h: i for i, h in enumerate(header)}
        i_sid = ix.get("SERIES_ID")
        i_acc = ix.get("ACCESSION_NUMBER")
        for row in r:
            sid = row[i_sid].strip() if i_sid is not None and i_sid < len(row) else ""
            acc = row[i_acc].strip() if i_acc is not None and i_acc < len(row) else ""
            keys.add(sid or acc)
            if sid:
                ids.add(sid)
            else:
                blank += 1
    return ids, keys, blank


def main():
    q1_ids, q1_keys, q1_blank = series_ids("2026q1")
    q2_ids, q2_keys, q2_blank = series_ids("2026q2")
    inter = q1_ids & q2_ids
    result = {
        "frozen_rule_quarter": "2026q1",
        "exploratory_quarter": "2026q2",
        "holdout_quarter": "2026q1",
        "holdout_series": len(q1_ids),
        "exploratory_series": len(q2_ids),
        "holdout_series_identified": len(q1_ids),
        "exploratory_series_identified": len(q2_ids),
        "holdout_unique_series": len(q1_keys),
        "exploratory_unique_series": len(q2_keys),
        "holdout_blank_series_id_rows": q1_blank,
        "exploratory_blank_series_id_rows": q2_blank,
        "intersection": len(inter),
        "holdout_also_in_exploratory": len(inter) / len(q1_ids) if q1_ids else None,
        "holdout_also_in_exploratory_identified": (
            len(inter) / len(q1_ids) if q1_ids else None),
        "holdout_also_in_exploratory_all_series": (
            len(inter) / len(q1_keys) if q1_keys else None),
        "jaccard": len(inter) / len(q1_ids | q2_ids) if (q1_ids | q2_ids) else None,
        "holdout_only": len(q1_ids - q2_ids),
        "note": (f"The 2026q1 score is untouched by 2026q1 outcomes, but it is not "
                 f"a disjoint-fund score: most q1 series also appear in q2 because "
                 f"the same funds file each quarter. {len(inter):,}/{len(q1_ids):,} "
                 f"identified q1 series also appear in q2 "
                 f"({len(inter)/len(q1_ids)*100 if q1_ids else 0:.1f}%); against all "
                 f"{len(q1_keys):,} q1 series the overlap is "
                 f"{len(inter)/len(q1_keys)*100 if q1_keys else 0:.1f}% because "
                 f"{q1_blank:,} filings have a blank series id and cannot be matched "
                 f"across quarters. The rule is name-based, so the overlap limits "
                 f"how independent the score is."),
    }
    (HERE / "overlap.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"overlap: {result['intersection']:,}/{result['holdout_series_identified']:,} "
          f"identified q1 series also in q2 "
          f"({result['holdout_also_in_exploratory_identified']*100:.1f}%); "
          f"all-series {result['intersection']:,}/{result['holdout_unique_series']:,} "
          f"({result['holdout_also_in_exploratory_all_series']*100:.1f}%); "
          f"jaccard {result['jaccard']:.3f}")


if __name__ == "__main__":
    main()
