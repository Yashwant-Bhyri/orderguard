"""G1 scoring on the Mac: self-hosted decision models vs the hosted decision reader and the keyword floor.

Uses T05's own sampler, targets, AUROC and episode-bootstrap code, so the numbers are directly comparable to T05.
"""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("t05eval", ROOT / "work/T05/evaluate.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

SEED, EPF, APE, REPS = 20261119, 30, 4, 1000
FEATURES = ("hype", "authority_language", "support_gap")
records = []
for shifted in (False, True):
    for family in ev.FAMILIES:
        records.extend(ev._sample_file(ROOT / f"data/ref/{family}{'.shifted' if shifted else ''}.jsonl", EPF, APE, SEED))
items = [json.loads(l) for l in open(HERE / "items.jsonl")]
assert len(items) == len(records), "items.jsonl is stale: rerun export.py"


def to_matrix(rows: dict[int, dict]) -> np.ndarray:
    m = np.full((len(records), 3), np.nan)
    for i, it in enumerate(items):
        r = rows.get(i)
        if r is None:
            continue
        m[i, 0], m[i, 1], m[i, 2] = r["hype"], r["authority_language"], 1.0 - r["support_gap"]
        if it.get("support_override") is not None:
            m[i, 2] = float(it["support_override"])
    return m


readers: dict[str, np.ndarray] = {}
for f in sorted(HERE.glob("scores_*.jsonl")):
    if f.stem.endswith("_smoke"):
        continue
    rows = {json.loads(l)["i"]: json.loads(l) for l in f.open()}
    readers[f.stem.removeprefix("scores_")] = to_matrix(rows)
hosted, _, err = ev._score_decision(records, 4)          # cached responses only; no spend
if err is None:
    readers["hosted (T05)"] = hosted
lex, _ = ev._score_local("lexicon", records, None)
readers["keyword floor"] = lex

table = {}
for split_name, mask in (("all actions", np.ones(len(records), bool)),
                         ("shifted only", np.array([bool(r["shifted"]) for r in records]))):
    sub = [r for r, k in zip(records, mask) if k]
    print(f"\n{split_name}: {len(sub)} actions; AUROC with episode-bootstrap 95% CI\n")
    print("| reader | coverage | " + " | ".join(FEATURES) + " |")
    print("|---|---|" + "---|" * len(FEATURES))
    for name, m in readers.items():
        mm = m[mask]
        cov = float(np.isfinite(mm[:, 0]).mean())
        cells = []
        for j, feat in enumerate(FEATURES):
            r = ev._auroc_ci(sub, mm[:, j], feat, REPS, SEED)
            cells.append(f"{r['auroc']:.3f} [{r['ci_low']:.3f}, {r['ci_high']:.3f}]" if r.get("auroc") is not None else "n/a")
            table.setdefault(split_name, {}).setdefault(name, {})[feat] = r
        print(f"| {name} | {cov:.2f} | " + " | ".join(cells) + " |")
(HERE / "results.json").write_text(json.dumps(table, indent=1, default=float))
