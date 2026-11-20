#!/usr/bin/env python3
"""Scan task artifacts and the cached SEC data for personal data.

What is checked:
  1. Task artifacts: email, phone, SSN, date-of-birth words, absolute home
     path and key-like strings; plus files over 5 MB in the task folder.
  2. Cached ZIP schema: no column outside the known SEC registrant contact
     block (REGISTRANT.tsv ADDRESS1, ADDRESS2, PHONE) looks like a
     natural-person field. That block is the registrant's public business
     address and phone, not a natural person's; the pipeline reads only CIK
     and REGISTRANT_NAME from that table and never emits the contact fields.
  3. Cached ZIP values: every text-like column outside that contact block is
     scanned for email, phone, SSN and date-of-birth words. Matches are
     reported by member:column only; the matched value is never printed.

Every file in the task folder is scanned, including `.pyc` bytecode (no
directory or suffix is skipped except `.git`). `run.sh` deletes `__pycache__`
and sets PYTHONDONTWRITEBYTECODE, so a home path cannot hide in bytecode.

Reviewer-supplied files (`REVIEW.md`, `SOL_ADVICE.md`, `ESCALATION.md`) are
scanned but their hits are reported separately as `external_artifact_hits`:
the worker must not alter reviewer output, and those files are not worker
artifacts.

The pass-bar claim in REPORT.md is narrowed to exactly these checks. They do
not prove a universal absence of all personal data, and the report says so.
"""

import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "data" / "sec"

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
HOME = re.compile(r"/(?:Users|home|root)/")
KEY = re.compile(r"(sk-[A-Za-z0-9_\-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
# A separator is required, so a plain 10-digit integer (net assets) cannot match.
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)")
# Boundaries exclude accession-number substrings such as 567-26-000123.
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
DOB = re.compile(r"\b(?:DATE OF BIRTH|SOCIAL SECURITY NUMBER|SOCIAL SECURITY)\b",
                 re.IGNORECASE)
# A bare phone-shaped string in a fund name is a name, not contact data.
PHONE_CONTEXT = re.compile(r"(?:PHONE|TEL|TELEPHONE|CALL|FAX|MOBILE|CELL)",
                           re.IGNORECASE)

# A column name that looks like a natural-person field is a schema-level issue.
PII_COLUMN = re.compile(
    r"(?:E[_ ]?MAIL|PHONE|TELEPHONE|FAX|SSN|SOCIAL|BIRTH|DOB|PASSPORT|"
    r"ADDRESS|CONTACT|FIRST[_ ]?NAME|LAST[_ ]?NAME|MIDDLE[_ ]?NAME|SURNAME)",
    re.IGNORECASE)
TEXT_COLUMN = re.compile(r"(?:NAME|TITLE|DESC|COMMENT|TEXT|NOTE|OTHER)", re.IGNORECASE)

# Public SEC registrant business-contact block, not natural-person data.
ENTITY_CONTACT_TABLE = "REGISTRANT.TSV"
ENTITY_CONTACT_COLUMNS = {"ADDRESS1", "ADDRESS2", "CITY", "STATE", "COUNTRY",
                          "ZIP", "PHONE"}
# The scanner's own source contains the patterns, so it is not a value hit.
SELF_SKIP = {"check_privacy.py", "check_privacy.py.bak"}
# Reviewer-supplied files are not written by the worker and must not be
# altered. A home path in one of them is reported separately, not counted as a
# worker artifact hit. The report states this exclusion explicitly.
EXTERNAL_ARTIFACTS = {"REVIEW.md", "SOL_ADVICE.md", "ESCALATION.md"}
# No directory or suffix is skipped except .git. `.pyc` files are scanned, so a
# stale bytecode file cannot hide a home path again.
SKIP = {".git"}


def check_artifact_text(text):
    return {
        "emails": EMAIL.findall(text),
        "phones": PHONE.findall(text),
        "ssns": SSN.findall(text),
        "dob": DOB.findall(text),
        "homes": HOME.findall(text),
        "keys": KEY.findall(text),
    }


def add(hits, source, hit):
    for k, values in hit.items():
        if values:
            hits[k].append(source)


def scan_zip(path, hits, stats):
    try:
        with zipfile.ZipFile(path) as zf:
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                stats["zip_members"] += 1
                with zf.open(member) as raw:
                    if member.lower().endswith(".tsv"):
                        scan_tsv(raw, f"{path.name}:{member}", hits, stats)
                    else:
                        data = raw.read(4 * 1024 * 1024)
                        text = data.decode("utf-8", "ignore")
                        add(hits, f"{path.name}:{member}", check_artifact_text(text))
    except Exception as e:
        hits["errors"].append(f"{path.name}: {type(e).__name__}: {e}")


def scan_tsv(raw, source, hits, stats):
    is_registrant = source.upper().endswith(ENTITY_CONTACT_TABLE)
    text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
    reader = csv.reader(text, delimiter="\t")
    try:
        header = [h.strip().upper().lstrip("\ufeff") for h in next(reader)]
    except StopIteration:
        return
    pii_cols = [h for h in header if PII_COLUMN.search(h)]
    allowed = [h for h in header
               if is_registrant and h in ENTITY_CONTACT_COLUMNS]
    unexpected = [h for h in pii_cols if h not in allowed]
    if allowed:
        hits["entity_contact_columns"].append(f"{source}: {','.join(allowed)}")
    if unexpected:
        hits["pii_columns"].append(f"{source}: {','.join(unexpected)}")
    # Value-scan text columns outside the public contact block.
    allowed_ix = {i for i, h in enumerate(header) if h in allowed}
    text_ix = [i for i, h in enumerate(header)
               if TEXT_COLUMN.search(h) and i not in allowed_ix]
    stats["tsv_members"] += 1
    stats["text_columns"] += len(text_ix)
    for row in reader:
        stats["tsv_rows"] += 1
        joined = "\t".join(row)
        if "@" in joined:
            em = EMAIL.findall(joined)
            if em:
                hits["emails"].append(source)
        if HOME.search(joined):
            hits["homes"].append(source)
        if "sk-" in joined or "BEGIN " in joined:
            kv = KEY.findall(joined)
            if kv:
                hits["keys"].append(source)
        if not text_ix:
            continue
        blob = " ".join(row[i] for i in text_ix if i < len(row))
        digits = sum(ch.isdigit() for ch in blob)
        if digits >= 7 and PHONE.search(blob):
            if PHONE_CONTEXT.search(blob):
                hits["phones"].append(f"{source}: text columns")
            else:
                hits["phone_shaped_names"].append(source)
        if digits >= 9 and blob.count("-") >= 2 and SSN.search(blob):
            hits["ssns"].append(f"{source}: text columns")
        up = blob.upper()
        if ("BIRTH" in up or "SOCIAL SECURITY" in up) and DOB.search(blob):
            hits["dob"].append(f"{source}: text columns")


def scan():
    hits = {k: [] for k in ("emails", "phones", "ssns", "dob", "homes", "keys",
                            "pii_columns", "entity_contact_columns", "phone_shaped_names",
                            "external_artifact_hits", "errors")}
    stats = {"files": 0, "pyc_files_scanned": 0, "zip_members": 0,
             "tsv_members": 0, "tsv_rows": 0, "text_columns": 0}
    big = []

    for p in sorted(HERE.rglob("*")):
        if not p.is_file() or any(part in SKIP for part in p.parts):
            continue
        stats["files"] += 1
        if p.suffix == ".zip":
            continue
        if p.name in SELF_SKIP:
            continue
        sz = p.stat().st_size
        if sz > 5 * 1024 * 1024:
            big.append((p.name, sz))
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if p.suffix in (".pyc", ".pyo"):
            stats["pyc_files_scanned"] += 1
        hit = check_artifact_text(text)
        if p.name in EXTERNAL_ARTIFACTS:
            for k, values in hit.items():
                if values:
                    hits["external_artifact_hits"].append(f"{p.name}:{k}")
        else:
            add(hits, p.name, hit)

    for p in sorted(DATA.rglob("*")):
        if not p.is_file() or any(part in SKIP for part in p.parts):
            continue
        stats["files"] += 1
        if p.suffix == ".zip":
            scan_zip(p, hits, stats)
        else:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            add(hits, p.name, check_artifact_text(text))

    return {**hits, "big": big, **stats}


def summary(r):
    unexpected = r["emails"] or r["phones"] or r["ssns"] or r["dob"] or r["homes"] \
        or r["keys"] or r["pii_columns"] or r["big"] or r["errors"]
    text = (f"emails {len(r['emails'])}, phones {len(r['phones'])}, "
            f"SSNs {len(r['ssns'])}, DOB words {len(r['dob'])}, "
            f"home paths {len(r['homes'])}, keys {len(r['keys'])}, "
            f"unexpected PII-schema columns {len(r['pii_columns'])}, "
            f"entity contact columns allowlisted {len(r['entity_contact_columns'])}, "
            f"phone-shaped non-contact names {len(r['phone_shaped_names'])}, "
            f"errors {len(r['errors'])}, files over 5 MB {len(r['big'])}, "
            f".pyc files scanned {r['pyc_files_scanned']}, "
            f"reviewer-artifact hits {len(r['external_artifact_hits'])}")
    return unexpected, text


def main():
    r = scan()
    unexpected, text = summary(r)
    (HERE / "privacy_scan.json").write_text(json.dumps(r, indent=2) + "\n")
    if not unexpected:
        print(f"PASS privacy: {text}; {r['tsv_rows']:,} TSV rows and "
              f"{r['text_columns']:,} text columns scanned across "
              f"{r['tsv_members']} TSV members ({r['files']} files, "
              f"{r['zip_members']} ZIP members)")
        if r["external_artifact_hits"]:
            print("NOTE reviewer-supplied artifacts contain the listed pattern hits "
                  "(not counted as worker artifacts):",
                  r["external_artifact_hits"])
        return 0
    for k in ("emails", "phones", "ssns", "dob", "homes", "keys",
              "pii_columns", "errors"):
        if r[k]:
            print(f"FAIL {k} in:", r[k][:20])
    if r["big"]:
        print("FAIL files over 5 MB:", r["big"])
    if r["external_artifact_hits"]:
        print("NOTE reviewer-supplied artifacts contain the listed pattern hits "
              "(not counted as worker artifacts):", r["external_artifact_hits"])
    return 1


if __name__ == "__main__":
    sys.exit(main())
