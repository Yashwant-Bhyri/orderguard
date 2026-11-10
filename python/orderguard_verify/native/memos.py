"""Draft research memos from memory: models with no documents and no retrieval write a note on a company, so every
figure in it is a natural truth or a natural mistake. Nothing is planted. Frozen before any memo existed (docs/PROTOCOL.md)."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from ..core.llm import ask_json
from ..paths import DATA

DRAFTERS = {"cohere": "cohere/north-mini-code:free", "flint": "recursive/flint-v1.0:free"}
OUT = DATA / "native" / "memos.json"

SYSTEM = ("You are an equity research analyst writing a short note for a portfolio manager. You have no documents, no internet and "
          "no data feed: write from memory. Reply with JSON {\"memo\": \"...\"}.")
USER = ("Write a research note of 150 to 250 words on {name} ({ticker}) as it would have read on {as_of}. Cover how the business has "
        "been doing in its most recently completed fiscal year and the years before it, include the key reported figures you can "
        "recall (revenue, profit, earnings per share, cash flow, margins, growth, or others), and state the fiscal year each figure "
        "belongs to. End with a one-line view on the stock. Plain prose, no tables.")


def draft(name: str, ticker: str, as_of: str, model: str) -> str:
    data, _ = ask_json(SYSTEM, USER.format(name=name, ticker=ticker, as_of=as_of), model=model, max_tokens=14000)
    return str(data["memo"]).strip()


def build(workers: int = 6) -> dict:
    spec = json.loads((DATA / "native" / "companies.json").read_text())
    split = {t: "dev" for t in spec["dev"]} | {t: "holdout" for t in spec["holdout"]}
    jobs = [(t, d, m) for t in sorted(split) for d, m in DRAFTERS.items()]
    memos = json.loads(OUT.read_text()) if OUT.exists() else {}

    def one(job):
        t, d, m = job
        key = f"{t}-{d}"
        if key in memos:
            return key, memos[key]
        return key, {"ticker": t, "drafter": d, "model": m, "split": split[t], "as_of": spec["as_of"],
                     "text": draft(spec["names"][t], t, spec["as_of"], m)}
    with ThreadPoolExecutor(workers) as pool:
        for key, rec in pool.map(one, jobs):
            memos[key] = rec
    OUT.write_text(json.dumps(memos, indent=1, sort_keys=True))
    return memos


if __name__ == "__main__":
    m = build()
    print(len(m), "memos;", sum(len(r["text"].split()) for r in m.values()) // len(m), "words on average")
