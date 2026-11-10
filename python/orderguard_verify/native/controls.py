"""Honest control memos. The memo writers rarely get every figure right, so few native memos are fully honest, and "does it wrongly stop an
honest memo?" needs honest memos. A model is handed a short table of the company's figures (from the truth store, as of the memo date) and
writes a research note from it. The figures are then labelled independently from the filing documents like every other memo, so a wrong figure in the
table would still be labelled false. Added to the protocol's change log before any hold-out result existed."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from ..core.llm import ask_json
from ..finance.truth_store import TruthStore
from ..paths import DATA

WRITER = "cohere/north-mini-code:free"
SYSTEM = "You are an equity research analyst writing a short note for a portfolio manager. Reply with JSON {\"memo\": \"...\"}."
USER = ("Write a research note of 120 to 180 words on {name} ({ticker}) as it would have read on {as_of}. Use ONLY the figures in the table below, do not "
        "add any other number, and state the fiscal year each figure belongs to (use the fiscal-year names in the table). You may round the way an analyst "
        "would (for example $391 billion) and may mention growth rates or margins that follow from the table. End with a one-line view on the stock.\n\n{table}")
METRICS = [("revenue", "revenue"), ("net_income", "net income"), ("operating_income", "operating income"), ("eps_diluted", "diluted EPS"),
           ("operating_cash_flow", "operating cash flow")]


def table(store: TruthStore, ticker: str, as_of: date) -> str:
    rows = {}
    for s in store.all_public(ticker, as_of):
        if s.duration == "FY" and s.metric in dict(METRICS):
            rows[(s.metric, s.period)] = s          # all_public is oldest first, so the newest version wins
    periods = sorted({p for _, p in rows}, reverse=True)[:2]
    lines = []
    for p in periods:
        for m, label in METRICS:
            s = rows.get((m, p))
            if s:
                lines.append(f"{p} {label}: " + (f"${s.value:.2f} per share" if s.unit == "USD/share" else f"${s.value / 1e9:,.2f} billion"))
    return "\n".join(lines)


def build(workers: int = 4) -> None:
    spec = json.loads((DATA / "native" / "companies.json").read_text())
    path = DATA / "native" / "memos.json"
    memos = json.loads(path.read_text())
    store = TruthStore()
    as_of = date.fromisoformat(spec["as_of"])
    split = {t: "dev" for t in spec["dev"]} | {t: "holdout" for t in spec["holdout"]}

    def one(t):
        key = f"{t}-control"
        if key in memos:
            return key, memos[key]
        user = USER.format(name=spec["names"][t], ticker=t, as_of=spec["as_of"], table=table(store, t, as_of))
        data, _ = ask_json(SYSTEM, user, model=WRITER)
        return key, {"ticker": t, "drafter": "control", "model": WRITER, "split": split[t], "as_of": spec["as_of"], "text": str(data["memo"]).strip(),
                     "kind": "honest control (written from a table of filing figures)"}
    with ThreadPoolExecutor(workers) as pool:
        for key, rec in pool.map(one, sorted(split)):
            memos[key] = rec
    path.write_text(json.dumps(memos, indent=1, sort_keys=True))


if __name__ == "__main__":
    build()
