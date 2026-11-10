"""Score the claim extractor against hand-labelled memos (data/extractor_gold.json).

Not part of the gate itself: this answers "does the LLM read memos correctly?" before we trust it.
A gold claim is matched to the extracted claim with the most overlapping quote; then each field is compared.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..core.extractor import extract
from ..core.models import Claim
from ..paths import DATA
from .models import Order
from .pack import FinancePack, load_mandate
from .truth_store import TruthStore

GOLD = DATA / "extractor_gold.json"


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9$.%]+", s.lower()))


def _overlap(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def _same_value(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= 0.005 * max(abs(b), 1e-9) or abs(a - b) < 1e-9


def score_memo(claims: list[Claim], gold: list[dict]) -> dict:
    unused = list(claims)
    rows = []
    for g in gold:
        best = max(unused, key=lambda c: _overlap(c.text, g["quote"]), default=None)
        if best is None or _overlap(best.text, g["quote"]) < 0.6:
            rows.append({"quote": g["quote"], "found": False, "bad_fields": []})
            continue
        unused.remove(best)
        bad = []
        if best.type != g["type"]:
            bad.append(f"type {best.type}!={g['type']}")
        if g["type"] in ("fundamental", "price"):
            for f in ("metric", "period", "unit"):
                got = getattr(best, "attribute" if f == "metric" else f)
                if f in g and got != g[f]:
                    bad.append(f"{f} {got}!={g[f]}")
            if "value" in g and not _same_value(best.value, g["value"]):
                bad.append(f"value {best.value}!={g['value']}")
            if "ticker" in g and best.subject != g["ticker"]:
                bad.append(f"ticker {best.subject}!={g['ticker']}")
        rows.append({"quote": g["quote"], "found": True, "bad_fields": bad})
    extra = [c.text for c in unused if c.type in ("fundamental", "price") and c.value is not None]
    return {"rows": rows, "extra_numeric": extra}


def run(ask, workers: int = 4, path: Path = GOLD) -> dict:
    cases = json.loads(Path(path).read_text())
    pack = FinancePack(TruthStore(), load_mandate(), None)

    def one(case):
        order = Order(**case["order"])
        ex = extract(case["memo"], order, pack, ask)
        return case["id"], score_memo(ex.claims, case["gold"]), ex

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(one, cases))
    total = found = exact = 0
    extras = 0
    failures = []
    for cid, s, _ in results:
        extras += len(s["extra_numeric"])
        for r in s["rows"]:
            total += 1
            found += r["found"]
            exact += r["found"] and not r["bad_fields"]
            if not r["found"] or r["bad_fields"]:
                failures.append((cid, r["quote"], "missing" if not r["found"] else "; ".join(r["bad_fields"])))
        for t in s["extra_numeric"]:
            failures.append((cid, t, "extra numeric claim not in gold"))
    return {"cases": len(cases), "gold_claims": total, "found": found, "exactly_right": exact,
            "extra_numeric_claims": extras, "failures": failures,
            "cost_usd": sum(e.call.cost_usd for _, _, e in results), "seconds": sum(e.call.latency_s for _, _, e in results)}
