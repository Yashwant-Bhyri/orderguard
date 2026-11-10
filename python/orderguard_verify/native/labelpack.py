"""Build one folder per company for the labelling agent: the memos and the filing texts, nothing else."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from ..paths import DATA, DOCS


def build(out: Path, tickers: list[str]) -> None:
    memos = json.loads((DATA / "native" / "memos.json").read_text())
    for t in tickers:
        d = out / t
        d.mkdir(parents=True, exist_ok=True)
        mine = sorted((k, v) for k, v in memos.items() if v["ticker"] == t)
        (d / "memos.txt").write_text("\n\n".join(f"=== MEMO {k} ===\n{v['text']}" for k, v in mine) + "\n")
        for f in sorted((DATA / "native" / "filings" / t).glob("10-K_*.txt")):
            shutil.copy(f, d / f.name)
        shutil.copy(DOCS / "LABELLING.md", d / "LABELLING.md")


if __name__ == "__main__":
    build(Path(sys.argv[1]), sys.argv[2:])
