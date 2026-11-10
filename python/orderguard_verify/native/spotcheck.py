"""Pick 25 labelled claims at random (fixed seed) for the owner to check by hand against the filing. Until that is done the labels are
"agent-labelled", never "human-reviewed"."""
from __future__ import annotations

import json
import random

from ..paths import DATA, DOCS


def build(n: int = 25, seed: int = 20261105) -> str:
    manifest = json.loads((DATA / "native" / "filings_manifest.json").read_text())
    memos = json.loads((DATA / "native" / "memos.json").read_text())
    pool = []
    for f in sorted((DATA / "native" / "labels").glob("*.json")):
        d = json.loads(f.read_text())
        for m in d["memos"]:
            for i, c in enumerate(m["claims"]):
                if c["verdict"] in ("true", "false"):
                    pool.append((m["memo_id"], i, d["company"], c))
    pick = random.Random(seed).sample(pool, min(n, len(pool)))
    L = ["# Spot-check: 25 labelled claims for you to verify", "",
         f"Drawn at random (seed {seed}) from {len(pool)} true/false labels. For each, open the filing, find the figure, and write whether you agree with the label. "
         "Agent-labelled until you have done this; please do not call the labels human-reviewed before.", "",
         "| # | Claim (quote from the memo) | Agent says | What the agent says the filing shows | Where | Filing | You agree? |", "|---|---|---|---|---|---|---|"]
    for k, (mid, _, t, c) in enumerate(pick, 1):
        files = {x["file"]: x["url"] for x in manifest[t]}
        where = c.get("evidence", "")
        url = next((u for fn, u in files.items() if where.startswith(fn)), next(iter(files.values())))
        cell = lambda s: str(s).replace("|", "/").replace("\n", " ")
        L.append(f"| {k} | {cell(mid)}: {cell(c['quote'])} | **{c['verdict']}**{' (borderline)' if c.get('borderline') else ''} | {cell(c.get('filing_value', ''))} | "
                 f"{cell(where)[:160]} | [10-K]({url}) | |")
    text = "\n".join(L) + "\n"
    (DOCS / "SPOTCHECK.md").write_text(text)
    return text


if __name__ == "__main__":
    build()
