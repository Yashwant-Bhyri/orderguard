"""Fetch the two most recent 10-K documents of each company (public on the memo date) as plain text, for the labelling
agent to read. These are the filing documents themselves, not XBRL facts and not the truth store.

SEC fair access: descriptive User-Agent without contact details, well under 10 requests a second."""
from __future__ import annotations

import hashlib
import json
import re
import time
from html.parser import HTMLParser

import httpx

from ..finance.edgar import load_companies, user_agent
from ..paths import DATA

DIR = DATA / "native" / "filings"          # texts are not committed (large); the manifest is
MANIFEST = DATA / "native" / "filings_manifest.json"
BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "section"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style") or tag.endswith(":header"):
            self.skip += 1
        elif tag in ("td", "th"):
            self.out.append(" | ")
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") or tag.endswith(":header"):
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    text = "".join(p.out).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"( \| )+(?=\n)", "", text)
    text = re.sub(r"(\| ?){2,}", "| ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def latest_10ks(client: httpx.Client, cik: int, as_of: str, n: int = 2) -> list[dict]:
    r = client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    r.raise_for_status()
    recent = r.json()["filings"]["recent"]
    rows = [dict(zip(recent, vals)) for vals in zip(*recent.values())]
    ks = [x for x in rows if x["form"] == "10-K" and x["filingDate"] <= as_of]
    return sorted(ks, key=lambda x: x["filingDate"], reverse=True)[:n]


def fetch_all(tickers: list[str], as_of: str) -> dict:
    companies = load_companies()
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    with httpx.Client(headers={"User-Agent": user_agent()}, timeout=120, follow_redirects=True) as c:
        for t in tickers:
            cik = companies[t]["cik"]
            for k in latest_10ks(c, cik, as_of):
                path = DIR / t / f"10-K_{k['filingDate']}.txt"
                if path.exists():
                    continue
                url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{k['accessionNumber'].replace('-', '')}/{k['primaryDocument']}"
                time.sleep(0.3)
                raw = c.get(url)
                raw.raise_for_status()
                path.parent.mkdir(parents=True, exist_ok=True)
                text = html_to_text(raw.text)
                path.write_text(text)
                manifest.setdefault(t, []).append({"file": path.name, "filed": k["filingDate"], "report_date": k["reportDate"], "url": url,
                                                   "sha256_html": hashlib.sha256(raw.content).hexdigest(), "chars": len(text)})
                print(t, k["filingDate"], len(text), flush=True)
    MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return manifest


if __name__ == "__main__":
    spec = json.loads((DATA / "native" / "companies.json").read_text())
    fetch_all(spec["dev"] + spec["holdout"], spec["as_of"])
